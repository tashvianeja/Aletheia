/* Sensor/actuator only: Python makes all privacy and purpose decisions. */
(() => {
  if(window.__privacyGuardianMain)return;window.__privacyGuardianMain=true;
  const capturedOpen=XMLHttpRequest.prototype.open,xhrAsync=new WeakMap();
  const capturedFetch=window.fetch, capturedSend=XMLHttpRequest.prototype.send, capturedSubmit=HTMLFormElement.prototype.submit;
  const waiting=new Map(),binaryFiles=new WeakMap(),storageKeys=new Map(),databaseKeys=[],confirmedHashes=new Set();
  const blobArrayBuffer=Blob.prototype.arrayBuffer;
  Blob.prototype.arrayBuffer=async function(){const bytes=await blobArrayBuffer.call(this);binaryFiles.set(bytes,this);return bytes;};
  const readArrayBuffer=FileReader.prototype.readAsArrayBuffer;
  FileReader.prototype.readAsArrayBuffer=function(blob){this.addEventListener('load',()=>{if(this.result instanceof ArrayBuffer)binaryFiles.set(this.result,blob);},{once:true});return readArrayBuffer.call(this,blob);};
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
  function hasFiles(body){return body instanceof Blob||(body instanceof FormData&&Array.from(body.values()).some(value=>value instanceof File&&value.size))||(body instanceof ArrayBuffer&&binaryFiles.has(body))||(ArrayBuffer.isView(body)&&binaryFiles.has(body.buffer));}
  async function checkBody(body){let files=[],binary=false;
    if(body instanceof FormData)files=Array.from(body.values()).filter(value=>value instanceof File&&value.size);
    else if(body instanceof Blob)files=[body];
    else if(body instanceof ArrayBuffer&&binaryFiles.has(body)){files=[binaryFiles.get(body)];binary=true;}
    else if(ArrayBuffer.isView(body)&&binaryFiles.has(body.buffer)){files=[binaryFiles.get(body.buffer)];binary=true;}
    if(!files.length)return {allowed:true,body};
    const id=crypto.randomUUID();const result=await new Promise(resolve=>{
      const waiter={resolve,intervene:false};waiting.set(id,waiter);window.postMessage({pgBridge:'upload_check',id,files},location.origin);
      setTimeout(()=>{if(waiting.has(id)&&!waiter.intervene){waiting.delete(id);resolve({allowed:true,files});}},4000);
      setTimeout(()=>{if(waiting.has(id)){waiting.delete(id);resolve({allowed:false,files:[]});}},64000);
    });
    if(!result.allowed)return {allowed:false,body};
    if(body instanceof FormData){const replacement=new FormData();let index=0;for(const [name,value] of body.entries()){if(value instanceof File&&value.size){const file=result.files[index++]||value;replacement.append(name,file,file.name);}else replacement.append(name,value);}return {allowed:true,body:replacement};}
    const replacement=result.files[0]||body;return {allowed:true,body:binary?await blobArrayBuffer.call(replacement):replacement};
  }
  window.fetch=async function(input,init){
    let body=init?.body,request=input;
    if(input instanceof Request&&!body&&!['GET','HEAD'].includes(input.method)){
      const contentType=input.headers.get('content-type')||'';
      try{if(contentType.includes('multipart/form-data'))body=await input.clone().formData();else if(/application\/pdf|image\/|application\/octet-stream/.test(contentType))body=await input.clone().blob();}catch(_){}
    }
    const result=await checkBody(body);if(!result.allowed)throw new DOMException('Upload cancelled by Privacy Guardian','AbortError');
    if(input instanceof Request&&body){const headers=new Headers(init?.headers||input.headers);if(result.body instanceof FormData)headers.delete('content-type');request=new Request(input,{...init,headers,body:result.body});return capturedFetch.call(this,request);}
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
