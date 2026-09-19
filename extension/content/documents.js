(() => {
  const analyzed=new Map(),agreed=new Set();let cachedPolicy=null,cachedTerms=null;
  function links(kind){const pattern=kind==='terms'?/terms|conditions|agreement|nutzungsbedingungen|condiciones/i:/privacy|datenschutz|confidentialit|privacidad/i;return PG.queryAll('a[href]').filter(link=>pattern.test(`${link.textContent} ${link.getAttribute('href')}`)).map(link=>link.href).filter(url=>/^https?:/.test(url));}
  function inline(kind){const selectors=kind==='terms'?'[data-terms-text],#terms-text,.terms-content':'[data-privacy-policy],#privacy-policy,.privacy-policy-content';return PG.queryAll(selectors).map(node=>node.textContent).join('\n');}
  async function getDocument(kind){const embedded=inline(kind);if(embedded.trim())return embedded.slice(0,2_000_000);const url=links(kind)[0];if(!url)return '';
    try{const response=await fetch(url,{credentials:'include'});if(!response.ok)throw new Error('Policy fetch failed');const text=(await response.text()).slice(0,2_000_000);return new DOMParser().parseFromString(text,'text/html').body.textContent||text;}catch(_){try{return (await PG.request('fetch_policy',{url})).text||'';}catch(_){return '';}}
  }
  async function analyze(kind,trigger=false){const text=await getDocument(kind);const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))).map(byte=>byte.toString(16).padStart(2,'0')).join('');const key=`${kind}:${digest}`;
    if(trigger&&(await PG.request('document_acknowledged',{key})).acknowledged)return {document_key:key,acknowledged:true};
    if(!trigger&&analyzed.has(key))return analyzed.get(key);const result=await PG.request('context',{[kind]:{text},trigger_action:trigger});analyzed.set(key,result);if(kind==='policy')cachedPolicy={text};else cachedTerms={text,document_key:key};return {...result,document_key:key};}
  async function firstVisit(){if(PG.queryAll('form,input[type=file],input[type=email],input[type=checkbox]').length||PG.queryAll('[id*=cookie],[class*=consent]').length)await analyze('policy').catch(()=>{});}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',firstVisit,{once:true});else firstVisit();
  const bypass=new WeakSet();
  document.addEventListener('click',async event=>{
    const target=event.target.closest?.('input[type=checkbox],button,[role=button]');if(!target||target.closest('.pg-panel')||bypass.has(target)){bypass.delete(target);return;}
    const label=(target.labels?Array.from(target.labels).map(node=>node.textContent).join(' '):'')+' '+(target.getAttribute('aria-label')||target.textContent||'');
    if(!/i agree|agree to|accept terms|accept.*conditions|by continuing|zustimm|j.accepte|acepto/i.test(label)||!links('terms').length&&!inline('terms'))return;
    const cachedKey=cachedTerms?.document_key;if(cachedKey&&agreed.has(cachedKey))return;event.preventDefault();event.stopImmediatePropagation();const intendedChecked=target instanceof HTMLInputElement?target.checked:null;
    try{const result=await PG.safeRace(analyze('terms',true),4000,null);if(!result){if(intendedChecked!==null){target.checked=intendedChecked;target.dispatchEvent(new Event('change',{bubbles:true}));}else{bypass.add(target);target.click();}return;}const decision=result.terms?.decision;const selected=await PG.awaitDecision(decision);if(selected.action==='continue'||!decision||decision.outcome!=='INTERVENE'){agreed.add(result.document_key);await PG.request('document_acknowledge',{key:result.document_key});if(intendedChecked!==null){target.checked=intendedChecked;target.dispatchEvent(new Event('change',{bubbles:true}));}else{bypass.add(target);target.click();}}}catch(_){}
  },true);
  PG.collectors.push(async()=>{if(!cachedPolicy)await analyze('policy').catch(()=>{});if(links('terms').length&&!cachedTerms)await analyze('terms').catch(()=>{});return {policy:cachedPolicy||{text:''},terms:{text:cachedTerms?.text||'',absent:!cachedTerms}};});
})();
