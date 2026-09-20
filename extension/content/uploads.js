(() => {
  let preparationSent=false;
  function prepare(){if(preparationSent||!PG.queryAll('input[type=file]').length)return;preparationSent=true;PG.request('context',{uploads_available:true}).catch(()=>{preparationSent=false;});}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',prepare,{once:true});else prepare();
  if(document.documentElement)new MutationObserver(prepare).observe(document.documentElement,{childList:true,subtree:true});
  const records=new WeakMap(),scanQueue=[];let activeScans=0;
  function enqueue(operation){return new Promise((resolve,reject)=>{scanQueue.push({operation,resolve,reject});pump();});}
  function pump(){while(activeScans<2&&scanQueue.length){const job=scanQueue.shift();activeScans++;job.operation().then(job.resolve,job.reject).finally(()=>{activeScans--;pump();});}}
  const bytesToBase64=bytes=>{let binary='';for(let offset=0;offset<bytes.length;offset+=32768)binary+=String.fromCharCode(...bytes.subarray(offset,offset+32768));return btoa(binary);};
  async function artifact(action){const chunks=[];let offset=0;for(;;){const result=await PG.request('action_poll',{event_id:action.event_id,artifact_offset:offset});const binary=atob(result.data||'');const chunk=Uint8Array.from(binary,char=>char.charCodeAt(0));chunks.push(chunk);offset+=chunk.length;if(result.eof)break;if(!chunk.length)throw new Error('Incomplete redacted copy');}return new File(chunks,action.filename,{type:action.mime});}
  async function applyAction(record,action){
    if(record.actionPromise)return record.actionPromise;
    record.actionPromise=(async()=>{
      if(['redact','strip_metadata'].includes(action.action)){
        const replacement=await artifact(action);
        for(const input of PG.queryAll('input[type=file]')){
          if(!Array.from(input.files||[]).includes(record.file))continue;
          try{const transfer=new DataTransfer();for(const file of input.files)transfer.items.add(file===record.file?replacement:file);input.files=transfer.files;}
          catch(_){record.action='cancel';return;}
        }
        record.replacement=replacement;
      }
      record.action=action.action;
      // Only now, with the safe copy actually in the page's file input: a receipt
      // for a copy that failed to arrive would be a receipt for nothing.
      if(action.report)PG.showResult(action.report);
    })();
    try{await record.actionPromise;}catch(error){record.action='cancel';throw error;}
  }
  function scan(file){if(records.has(file))return records.get(file);const record={file,action:null,replacement:null,decision:null};records.set(file,record);
    record.promise=enqueue(async()=>{const upload_id=crypto.randomUUID();await PG.request('file_start',{upload_id,filename:file.name,size:file.size,mime:file.type});let sequence=0;
      for(let offset=0;offset<file.size;offset+=550*1024){const bytes=new Uint8Array(await file.slice(offset,offset+550*1024).arrayBuffer());await PG.request('file_chunk',{upload_id,sequence:sequence++,data:bytesToBase64(bytes)});}
      const result=await PG.request('file_finish',{upload_id});record.decision=result.decision;if(record.expired){await PG.request('disconnect',{event_id:result.decision.event_id,reason:'analysis_timeout'}).catch(()=>{});return record;}PG.showDecision(result.decision,action=>applyAction(record,action));return record;
    }).catch(()=>{record.failed=true;return record;});return record;
  }
  async function permit(file,onHold){const record=scan(file);if(record.expired)return {allowed:true,file};await PG.safeRace(record.promise,4000,null);if(!record.decision){record.expired=true;return {allowed:true,file};}
    if(record.actionPromise)await record.actionPromise;
    if(record.action)return {allowed:['continue','redact','strip_metadata'].includes(record.action),file:record.replacement||file};
    if(record.decision.outcome==='INTERVENE')onHold?.();
    const action=await PG.awaitDecision(record.decision,result=>applyAction(record,result));return {allowed:['continue','redact','strip_metadata'].includes(action.action),file:record.replacement||file};
  }
  document.addEventListener('change',event=>{const input=event.target;if(input instanceof HTMLInputElement&&input.type==='file')for(const file of input.files||[])scan(file);},true);
  const replayed=new WeakSet();
  for(const kind of ['drop','paste'])document.addEventListener(kind,async event=>{
    if(replayed.has(event)){replayed.delete(event);return;}
    const files=Array.from((kind==='drop'?event.dataTransfer:event.clipboardData)?.files||[]);if(!files.length)return;
    event.preventDefault();event.stopImmediatePropagation();
    const results=await Promise.all(files.map(file=>permit(file)));if(results.some(result=>!result.allowed))return;
    const transfer=new DataTransfer();results.forEach(result=>transfer.items.add(result.file));
    if(event.target instanceof HTMLInputElement&&event.target.type==='file'){event.target.files=transfer.files;event.target.dispatchEvent(new Event('change',{bubbles:true}));return;}
    const replay=kind==='drop'?new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}):new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:transfer});replayed.add(replay);event.target.dispatchEvent(replay);
  },true);
  PG.submitChecks.unshift(async form=>{for(const input of Array.from(form.querySelectorAll('input[type=file]')))for(const file of input.files||[]){const result=await permit(file);if(!result.allowed)return false;}return true;});
  window.addEventListener('message',async event=>{
    if(event.source!==window||event.data?.pgBridge!=='upload_check'||typeof event.data.id!=='string'||!Array.isArray(event.data.files))return;
    const files=event.data.files.filter(file=>file instanceof File||file instanceof Blob);const checked=await Promise.all(files.map(file=>permit(file instanceof File?file:new File([file],'upload.bin',{type:file.type}),()=>window.postMessage({pgBridge:'upload_hold',id:event.data.id},location.origin))));
    window.postMessage({pgBridge:'upload_result',id:event.data.id,allowed:checked.every(result=>result.allowed),files:checked.map(result=>result.file)},location.origin);
  });
  PG.collectors.push(async()=>({uploads_available:!!PG.queryAll('input[type=file]').length,uploads_in_progress:PG.queryAll('input[type=file]').reduce((count,input)=>count+(input.files?.length||0),0)}));
})();
