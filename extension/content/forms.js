(() => {
  let nextId=0, timer=null, lastFingerprint='', assessments=[];
  const ids=new WeakMap();
  function fields(form=null){return PG.queryAll('input,select,textarea,[contenteditable=true]').filter(element=>PG.visible(element)&&(!form||element.form===form||form.contains(element))&&!['file','hidden','submit','button','reset','image'].includes(element.type)).map(element=>{
    if(!ids.has(element))ids.set(element,`pg-field-${++nextId}`);const field_id=ids.get(element);element.dataset.pgFieldId=field_id;
    const labels=element.labels?Array.from(element.labels).map(label=>label.textContent).join(' '):'';
    const label=(labels||element.getAttribute('aria-label')||element.getAttribute('placeholder')||'').trim().slice(0,300);
    return {field_id,label,name:(element.name||element.id||'').slice(0,100),input_type:element.type||element.tagName.toLowerCase(),autocomplete:element.autocomplete||'',required:!!element.required||element.getAttribute('aria-required')==='true',asserted_required:/\*/.test(label)||element.dataset.required==='true',filled:element.isContentEditable?!!element.textContent?.trim():['checkbox','radio'].includes(element.type)?element.checked:!!element.value};
  });}
  async function inventory(){const items=fields();const fingerprint=JSON.stringify(items.map(field=>({...field,filled:false})));if(fingerprint===lastFingerprint)return;lastFingerprint=fingerprint;
    try{const result=await PG.request('context',{forms:{fields:items}});if(fingerprint!==lastFingerprint)return;assessments=result.forms?.fields||[];PG.queryAll('.pg-badge').forEach(node=>node.remove());
      for(const assessment of assessments){if(!assessment.badge)continue;const element=PG.queryAll('[data-pg-field-id]').find(node=>node.dataset.pgFieldId===assessment.field.field_id);if(!element)continue;const badge=document.createElement('span');badge.className='pg-badge';badge.textContent='May be unnecessary';badge.title=assessment.necessity?.rationale||'';badge.setAttribute('role','note');element.insertAdjacentElement('afterend',badge);}
    }catch(_){lastFingerprint='';}}
  const schedule=()=>{clearTimeout(timer);timer=setTimeout(inventory,10);};
  const observedRoots=new WeakSet();
  function observeRoots(){for(const root of PG.roots()){if(observedRoots.has(root))continue;observedRoots.add(root);new MutationObserver(records=>{if(records.some(record=>!record.target.closest?.('.pg-panel,.pg-badge'))){observeRoots();schedule();}}).observe(root===document?document.documentElement:root,{subtree:true,childList:true,attributes:true,attributeFilter:['required','aria-required','name','type','style','class']});}}
  function observe(){observeRoots();schedule();}
  if(document.documentElement)observe();else document.addEventListener('DOMContentLoaded',observe,{once:true});
  PG.collectors.push(async()=>({forms:{fields:fields()}}));
  PG.submitChecks.push(async form=>{
    const items=fields(form);if(!items.some(field=>field.filled))return true;
    const result=await PG.safeRace(PG.request('event',{event:{event_type:'form_submit',fields:items}}),4000,null);if(!result)return true;
    const action=await PG.awaitDecision(result.decision,selected=>{if(selected.action==='review_fields')PG.highlight(assessments.filter(assessment=>assessment.badge).map(assessment=>assessment.field).filter(field=>items.some(item=>item.field_id===field.field_id)));});
    return action.action==='continue';
  });
  // Open shadow roots attached later are inventoried by the regular mutation pass and a low-frequency check.
  window.addEventListener('message',event=>{if(event.source===window&&event.data?.pgBridge==='shadow_attached'){observeRoots();schedule();}});
  setInterval(()=>{observeRoots();},100);
})();
