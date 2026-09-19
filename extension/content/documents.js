(() => {
  const analyzed=new Map(),agreed=new Set(),partialDocuments=new Map();let cachedPolicy=null,cachedTerms=null;
  function links(kind){const pattern=kind==='terms'?/terms|conditions|agreement|nutzungsbedingungen|condiciones/i:/privacy|datenschutz|confidentialit|privacidad/i;return PG.queryAll('a[href],link[rel~=privacy-policy][href]').filter(link=>(kind==='policy'&&link.rel==='privacy-policy')||pattern.test(`${link.textContent} ${link.getAttribute('href')}`)).map(link=>link.href).filter(url=>/^https?:/.test(url));}
  function inline(kind){const selectors=kind==='terms'?'[data-terms-text],#terms-text,.terms-content':'[data-privacy-policy],#privacy-policy,.privacy-policy-content';return PG.queryAll(selectors).map(node=>node.textContent).join('\n');}
  function boundedText(kind,text,partial=false){let bounded=text;while(new TextEncoder().encode(JSON.stringify({text:bounded})).length>600*1024)bounded=bounded.slice(0,Math.floor(bounded.length*0.8));partialDocuments.set(kind,partial||bounded.length<text.length);return bounded;}
  function htmlText(text){return new DOMParser().parseFromString(text,'text/html').body.textContent||text;}
  async function getDocument(kind,discover=false){
    partialDocuments.set(kind,false);const embedded=inline(kind);if(embedded.trim())return boundedText(kind,embedded);
    const url=links(kind)[0];if(!url){if(kind==='policy'&&discover){try{const text=await Promise.any(['/privacy','/privacy-policy','/legal/privacy'].map(async path=>{const response=await fetch(new URL(path,location.origin),{signal:AbortSignal.timeout(1800)});if(!response.ok)throw new Error('missing');return htmlText(await response.text());}));return boundedText(kind,text);}catch(_){}}return '';}
    try{const response=await fetch(url,{credentials:'include',signal:AbortSignal.timeout(2000)});if(!response.ok)throw new Error('Policy fetch failed');return boundedText(kind,htmlText(await response.text()));}
    catch(_){try{const result=await PG.request('fetch_policy',{url});return boundedText(kind,result.text||'',!!result.partial);}catch(_){return '';}}
  }
  async function analyze(kind,trigger=false,discover=false){const text=await getDocument(kind,trigger||discover);const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))).map(byte=>byte.toString(16).padStart(2,'0')).join('');const key=`${kind}:${digest}`;
    if(trigger&&!partialDocuments.get(kind)&&(await PG.request('document_acknowledged',{key})).acknowledged)return {document_key:key,acknowledged:true};
    if(!trigger&&analyzed.has(key))return analyzed.get(key);const result=await PG.request('context',{[kind]:{text,partial:!!partialDocuments.get(kind)},trigger_action:trigger});analyzed.set(key,result);if(kind==='policy')cachedPolicy={text,partial:!!partialDocuments.get(kind)};else cachedTerms={text,partial:!!partialDocuments.get(kind),document_key:key};return {...result,document_key:key,partial:!!partialDocuments.get(kind)};}
  async function firstVisit(){if(PG.queryAll('form,input[type=file],input[type=email],input[type=checkbox]').length||PG.queryAll('[id*=cookie],[class*=consent]').length)await analyze('policy').catch(()=>{});}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',firstVisit,{once:true});else firstVisit();
  const bypass=new WeakSet();
  document.addEventListener('click',async event=>{
    const target=event.target.closest?.('input[type=checkbox],button,[role=button]');if(!target||target.closest('.pg-panel,.pg-stack')||bypass.has(target)){bypass.delete(target);return;}
    const label=(target.labels?Array.from(target.labels).map(node=>node.textContent).join(' '):'')+' '+(target.getAttribute('aria-label')||target.textContent||'');
    if(!/i agree|agree to|accept terms|accept.*conditions|by continuing|zustimm|j.accepte|acepto/i.test(label)||!links('terms').length&&!inline('terms'))return;
    event.preventDefault();event.stopImmediatePropagation();const intendedChecked=target instanceof HTMLInputElement?target.checked:null;
    try{const result=await PG.safeRace(analyze('terms',true),4000,null);if(!result){if(intendedChecked!==null){target.checked=intendedChecked;target.dispatchEvent(new Event('change',{bubbles:true}));}else{bypass.add(target);target.click();}return;}const decision=result.terms?.decision;const citations=(decision?.findings||[]).map(finding=>finding.detail).filter(Boolean);const selected=await PG.awaitDecision(decision,action=>{if(action.action==='view_details')PG.showClauses(citations);});if(selected.action==='continue'||!decision||decision.outcome!=='INTERVENE'){agreed.add(result.document_key);if(!result.partial)await PG.request('document_acknowledge',{key:result.document_key});if(intendedChecked!==null){target.checked=intendedChecked;target.dispatchEvent(new Event('change',{bubbles:true}));}else{bypass.add(target);target.click();}}else if(selected.action==='view_details'){PG.showClauses(citations);}}catch(_){}
  },true);
  PG.collectors.push(async()=>{if(!cachedPolicy||!cachedPolicy.text)await analyze('policy',false,true).catch(()=>{});if(links('terms').length&&!cachedTerms)await analyze('terms').catch(()=>{});return {policy:cachedPolicy||{text:''},terms:{text:cachedTerms?.text||'',partial:!!cachedTerms?.partial,absent:!cachedTerms}};});
})();
