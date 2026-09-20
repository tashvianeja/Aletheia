/* Sensor/actuator only: Python makes all privacy and purpose decisions. */
(() => {
  if(window.__aletheiaMain)return;window.__aletheiaMain=true;
  const capturedOpen=XMLHttpRequest.prototype.open,xhrAsync=new WeakMap();
  const capturedFetch=window.fetch, capturedSend=XMLHttpRequest.prototype.send, capturedSubmit=HTMLFormElement.prototype.submit;
  const waiting=new Map(),binaryFiles=new WeakMap(),storageKeys=new Map(),databaseKeys=[],confirmedHashes=new Set();
  const blobArrayBuffer=Blob.prototype.arrayBuffer;
  Blob.prototype.arrayBuffer=async function(){const bytes=await blobArrayBuffer.call(this);binaryFiles.set(bytes,this);return bytes;};
  const readArrayBuffer=FileReader.prototype.readAsArrayBuffer;
  FileReader.prototype.readAsArrayBuffer=function(blob){this.addEventListener('load',()=>{if(this.result instanceof ArrayBuffer)binaryFiles.set(this.result,blob);},{once:true});return readArrayBuffer.call(this,blob);};
  // A chunked upload sends slices of the chosen file, so a slice keeps its origin.
  const blobSlice=Blob.prototype.slice,slicedFrom=new WeakMap();
  Blob.prototype.slice=function(...args){const part=blobSlice.apply(this,args);const origin=chosenFile(this);if(origin)slicedFrom.set(part,origin);return part;};
  // Adding a slice to a form re-wraps it as an anonymous File; carry the origin across.
  for(const method of ['append','set']){const original=FormData.prototype[method];FormData.prototype[method]=function(name,value,...rest){
    const origin=chosenFile(value);const result=original.call(this,name,value,...rest);
    if(origin){const stored=this.getAll(name).pop();if(stored instanceof File&&stored!==origin)slicedFrom.set(stored,origin);}
    return result;
  };}
  const attachShadow=Element.prototype.attachShadow;
  Element.prototype.attachShadow=function(options){const root=attachShadow.call(this,options);if(options.mode==='open')queueMicrotask(()=>window.postMessage({pgBridge:'shadow_attached'},location.origin));return root;};
  window.addEventListener('message',event=>{
    if(event.source!==window)return;
    if(event.data?.pgBridge==='mark_tracking_identifier'&&/^[a-f0-9]{64}$/.test(event.data.hash||'')){confirmedHashes.add(event.data.hash);return;}
    if(event.data?.pgBridge==='clear_tracking_identifiers'){
      for(const [key,entry]of storageKeys){if(confirmedHashes.has(entry.hash)&&localStorage.getItem(key)===entry.value)localStorage.removeItem(key);}storageKeys.clear();
      for(const entry of databaseKeys){if(!confirmedHashes.has(entry.hash))continue;try{const transaction=entry.database.transaction(entry.store,'readwrite');const store=transaction.objectStore(entry.store),request=store.get(entry.key);request.onsuccess=()=>{const current=request.result;if(typeof current==='string'&&current===entry.value){store.delete(entry.key);}else if(current&&typeof current==='object'&&entry.field!==null&&current[entry.field]===entry.value){delete current[entry.field];if(store.keyPath===null)store.put(current,entry.key);else store.put(current);}};}catch(_){}}databaseKeys.length=0;
      return;
    }
    const waiter=waiting.get(event.data?.id);if(!waiter)return;
    if(event.data.pgBridge==='upload_hold'){waiter.intervene=true;return;}
    if(event.data.pgBridge==='upload_result'){waiting.delete(event.data.id);waiter.resolve(event.data);}
  });
  // What counts as "a file this person is sharing". Only something that came from a
  // file picker, a drop or the clipboard does: a File, or a slice of one. A Blob the
  // page built itself is a request body — telemetry, a JSON payload, a media chunk —
  // and treating those as uploads announced a file share on nearly every site.
  function chosenFile(value){
    if(!(value instanceof Blob)||!value.size)return null;
    const origin=slicedFrom.get(value);
    if(origin)return origin;
    // A Blob put into a form arrives as a File the browser names "blob"; anything
    // the person picked, dropped or pasted carries its own filename.
    return value instanceof File&&value.name&&value.name!=='blob'?value:null;
  }
  function formFiles(body){return Array.from(body.values()).map(chosenFile).filter(Boolean);}
  function bufferFile(body){
    const source=body instanceof ArrayBuffer?binaryFiles.get(body):ArrayBuffer.isView(body)?binaryFiles.get(body.buffer):null;
    return source?chosenFile(source):null;
  }
  function hasFiles(body){
    if(body instanceof FormData)return formFiles(body).length>0;
    if(body instanceof Blob)return !!chosenFile(body);
    return !!bufferFile(body);
  }
  async function checkBody(body){let files=[],binary=false;
    if(body instanceof FormData)files=formFiles(body);
    else if(body instanceof Blob){const file=chosenFile(body);files=file?[file]:[];}
    else {const file=bufferFile(body);if(file){files=[file];binary=true;}}
    if(!files.length)return {allowed:true,body};
    const id=crypto.randomUUID();const result=await new Promise(resolve=>{
      const waiter={resolve,intervene:false};waiting.set(id,waiter);window.postMessage({pgBridge:'upload_check',id,files},location.origin);
      setTimeout(()=>{if(waiting.has(id)&&!waiter.intervene){waiting.delete(id);resolve({allowed:true,files});}},4000);
      setTimeout(()=>{if(waiting.has(id)){waiting.delete(id);resolve({allowed:false,files:[]});}},64000);
    });
    if(!result.allowed)return {allowed:false,body};
    if(body instanceof FormData){const replacement=new FormData();let index=0;for(const [name,value] of body.entries()){if(chosenFile(value)){const file=result.files[index++]||value;replacement.append(name,file,file.name);}else replacement.append(name,value);}return {allowed:true,body:replacement};}
    const replacement=result.files[0]||body;return {allowed:true,body:binary?await blobArrayBuffer.call(replacement):replacement};
  }
  // A Request swallows its body, so remember when one was built around a chosen file.
  const NativeRequest=window.Request,requestFiles=new WeakMap();
  try{window.Request=new Proxy(NativeRequest,{construct(target,args,newTarget){
    const request=Reflect.construct(target,args,newTarget);
    const carried=args[0] instanceof NativeRequest&&args[1]?.body===undefined?requestFiles.get(args[0]):null;
    const file=chosenFile(args[1]?.body)||carried;
    if(file)requestFiles.set(request,file);
    return request;
  }});}catch(_){}
  window.fetch=async function(input,init){
    let body=init?.body,request=input;
    if(input instanceof NativeRequest&&body===undefined&&!['GET','HEAD'].includes(input.method)){
      const contentType=input.headers.get('content-type')||'';
      try{if(contentType.includes('multipart/form-data'))body=await input.clone().formData();else body=requestFiles.get(input);}catch(_){}
    }
    const result=await checkBody(body);if(!result.allowed)throw new DOMException('Upload cancelled by Aletheia','AbortError');
    if(input instanceof NativeRequest&&body){const headers=new Headers(init?.headers||input.headers);if(result.body instanceof FormData)headers.delete('content-type');request=new NativeRequest(input,{...init,headers,body:result.body});return capturedFetch.call(this,request);}
    return capturedFetch.call(this,request,init?{...init,body:result.body}:init);
  };
  XMLHttpRequest.prototype.open=function(method,url,async=true,...args){xhrAsync.set(this,async!==false);return capturedOpen.call(this,method,url,async,...args);};
  XMLHttpRequest.prototype.send=function(body){if(!hasFiles(body))return capturedSend.call(this,body);if(xhrAsync.get(this)===false){this.abort();throw new DOMException("Synchronous file uploads cannot wait for privacy review","InvalidStateError");}const xhr=this;checkBody(body).then(result=>{if(result.allowed)capturedSend.call(xhr,result.body);else xhr.abort();}).catch(()=>xhr.abort());};
  const sendBeacon=navigator.sendBeacon?.bind(navigator);if(sendBeacon)navigator.sendBeacon=function(url,data){if(!hasFiles(data))return sendBeacon(url,data);checkBody(data).then(result=>{if(result.allowed)sendBeacon(url,result.body);});return true;};
  HTMLFormElement.prototype.submit=function(){const event=new Event('submit',{bubbles:true,cancelable:true});if(this.dispatchEvent(event))capturedSubmit.call(this);};
  const observed=new Set();let timer=null;
  function report(name){observed.add(name);if(!timer)timer=setTimeout(()=>{window.postMessage({pgBridge:'tracking_signals',api_calls:[...observed]},location.origin);timer=null;},200);}
  function wrap(object,name,label){try{const original=object?.[name];if(typeof original!=='function')return;object[name]=function(...args){report(label);return Reflect.apply(original,this,args);};}catch(_){}}
  wrap(HTMLCanvasElement.prototype,'toDataURL','canvas.toDataURL');wrap(CanvasRenderingContext2D.prototype,'getImageData','canvas.getImageData');wrap(CanvasRenderingContext2D.prototype,'fillText','canvas.fillText');wrap(CanvasRenderingContext2D.prototype,'drawImage','canvas.drawImage');
  if(window.AnalyserNode){wrap(AnalyserNode.prototype,'getFloatFrequencyData','audio.analysis');wrap(AnalyserNode.prototype,'getByteFrequencyData','audio.analysis');}
  for(const constructor of ['AudioContext','OfflineAudioContext']){try{const Original=window[constructor];if(Original)window[constructor]=new Proxy(Original,{construct(target,args,newTarget){report(constructor);return Reflect.construct(target,args,newTarget);}});}catch(_){}}
  for(const name of ['plugins','hardwareConcurrency','deviceMemory']){try{const descriptor=Object.getOwnPropertyDescriptor(Navigator.prototype,name);if(descriptor?.get)Object.defineProperty(Navigator.prototype,name,{...descriptor,get(){report(`navigator.${name}`);return descriptor.get.call(this);}});}catch(_){}}
  for(const constructor of ['WebGLRenderingContext','WebGL2RenderingContext']){try{const prototype=window[constructor]?.prototype;if(!prototype)continue;const original=prototype.getParameter;prototype.getParameter=function(parameter){if(parameter===37445||parameter===37446)report('WebGL.renderer');return original.call(this,parameter);};}catch(_){}}
  if(window.FontFaceSet)wrap(FontFaceSet.prototype,'check','font.enumeration');
  // Shared-storage comparison uses hashes and origin counts in extension memory, never raw identifier values.
  function storageIdentifier(value) {
    if(typeof value !== 'string' || !/^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(value))return;
    crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)).then(hash=>window.postMessage({pgBridge:'storage_identifier',hash:Array.from(new Uint8Array(hash)).map(byte=>byte.toString(16).padStart(2,'0')).join('')},location.origin));
  }
  function hashIdentifier(value,callback){crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)).then(hash=>callback(Array.from(new Uint8Array(hash)).map(byte=>byte.toString(16).padStart(2,'0')).join('')));}
  if(window.IDBObjectStore)for(const name of ['put','add']){const original=IDBObjectStore.prototype[name];IDBObjectStore.prototype[name]=function(value,...args){
    try{const entries=typeof value==='string'?[[null,value]]:value&&typeof value==='object'?Object.entries(value).slice(0,30):[];
      const key=args[0]??(typeof this.keyPath==='string'?value?.[this.keyPath]:undefined);
      for(const [field,item]of entries)if(typeof item==='string'&&/^[a-f0-9]{8}-[a-f0-9-]{27,}$/i.test(item)){storageIdentifier(item);if(key!==undefined&&field!==this.keyPath)hashIdentifier(item,hash=>databaseKeys.push({database:this.transaction.db,store:this.name,key,field,value:item,hash}));}
    }catch(_){}return original.call(this,value,...args);
  };}
  function tcfSnapshot(){if(typeof window.__tcfapi==='function')try{window.__tcfapi('getTCData',2,(data,ok)=>{if(ok&&data)window.postMessage({pgBridge:'tcf_snapshot',purpose_consents:data.purpose?.consents||{},vendor_count:Object.keys(data.vendor?.consents||{}).length},location.origin);});}catch(_){}}
  setTimeout(tcfSnapshot,500);setTimeout(tcfSnapshot,2000);
  const storageSet=Storage.prototype.setItem;
  Storage.prototype.setItem=function(key,value){try{if(typeof value==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(value)){hashIdentifier(value,hash=>storageKeys.set(String(key),{value,hash}));crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)).then(hash=>window.postMessage({pgBridge:'storage_identifier',hash:Array.from(new Uint8Array(hash)).map(byte=>byte.toString(16).padStart(2,'0')).join('')},location.origin));}}catch(_){}return storageSet.call(this,key,value);};
})();
