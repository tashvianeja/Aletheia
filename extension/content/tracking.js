(() => {
  const calls=new Set();let sharedIdentifiers=0,timer=null,last='';
  window.addEventListener('message',event=>{if(event.source!==window)return;if(event.data?.pgBridge==='tracking_signals'&&Array.isArray(event.data.api_calls)){event.data.api_calls.forEach(value=>calls.add(String(value).slice(0,80)));schedule();}if(event.data?.pgBridge==='storage_identifier'&&/^[a-f0-9]{64}$/.test(event.data.hash||'')){PG.request('storage_identifier',{hash:event.data.hash}).then(result=>{sharedIdentifiers=result.origin_count>1?result.origin_count:0;schedule();}).catch(()=>{});}});
  async function snapshot(){const observed=await PG.request('tracking_context');return {...observed,origin:location.origin,urls:[location.href,...observed.urls],api_calls:[...calls],storage_shared_identifiers:sharedIdentifiers,pixel_beacons:PG.queryAll('img').filter(image=>image.width<=1&&image.height<=1&&image.src.startsWith('http')).length,pixel_hosts:PG.queryAll('img').filter(image=>image.width<=1&&image.height<=1&&image.src.startsWith('http')).map(image=>new URL(image.src).hostname)};}
  async function analyze(){try{const current=await snapshot();const fingerprint=JSON.stringify(current);if(fingerprint===last)return;last=fingerprint;const result=await PG.request('context',{tracking:{snapshot:current}});const decision=result.tracking?.decision;if(decision)PG.showDecision(decision,async action=>{if(action.action==='block')await PG.request('block_tracking',{hosts:result.tracking.profile.tracker_domains||[]});});}catch(_){}}
  function schedule(){clearTimeout(timer);timer=setTimeout(analyze,400);}
  PG.collectors.push(async()=>({tracking:{snapshot:await snapshot()}}));
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',schedule,{once:true});else schedule();
  setTimeout(schedule,2000);
})();
