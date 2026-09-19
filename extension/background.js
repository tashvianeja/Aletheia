/* Browser identity comes exclusively from runtime sender and browser APIs. */
if (typeof importScripts === 'function') importScripts('schema-validator.js');
const api = globalThis.browser || chrome;
const HOST = 'com.privacyguardian.host';
let port = null, reconnectTimer = null, reconnectDelay = 250;
const pending = new Map(), tabSignals = new Map(), tabContexts = new Map(), storageOrigins = new Map(), storageTabs = new Map(), dnsCache = new Map();
let sequence = 0, schemas = null;
const schemaReady = Promise.all(['request','response','event'].map(async name => [name, await (await fetch(api.runtime.getURL(`schema/${name}.json`))).json()])).then(entries => {schemas = Object.fromEntries(entries);});
function badge(text, color = '#b45309') { api.action.setBadgeText({text}); api.action.setBadgeBackgroundColor({color}); }
function connect() {
  if (port) return;
  try {
    port = api.runtime.connectNative(HOST);
    port.onMessage.addListener(message => {
      if (!schemas || !PGValidate(message, schemas.response)) return;
      const waiter = pending.get(message.id);
      if (!waiter) return;
      clearTimeout(waiter.timer); pending.delete(message.id);
      message.ok ? waiter.resolve(message.result) : waiter.reject(new Error(message.error?.message || 'Local analysis failed'));
    });
    port.onDisconnect.addListener(() => {
      const error = api.runtime.lastError;
      void error; port = null; badge('!');
      for (const waiter of pending.values()) {clearTimeout(waiter.timer); waiter.reject(new Error('Local service disconnected'));}
      pending.clear();
      clearTimeout(reconnectTimer); reconnectTimer = setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(2000, reconnectDelay * 2);
    });
    native('ping', {browser: typeof browser === 'undefined' ? 'chromium' : 'firefox'}, 5000).then(() => {badge(''); reconnectDelay = 250;}).catch(() => {});
  } catch (_) {port = null; badge('!'); reconnectTimer = setTimeout(connect, 1000);}
}
async function native(type, payload, timeout = 25000) {
  await schemaReady;
  if (!port) connect();
  if (!port) throw new Error('Local service disconnected');
  const request = {v:1,id:`pg-${Date.now()}-${++sequence}`,type,payload};
  if (!PGValidate(request, schemas.request) || JSON.stringify(request).length > 900 * 1024) throw new Error('Invalid native request');
  return new Promise((resolve,reject) => {
    const timer = setTimeout(() => {pending.delete(request.id); reject(new Error('Local analysis timed out'));}, timeout);
    pending.set(request.id,{resolve,reject,timer});
    try {port.postMessage(request);} catch (error) {clearTimeout(timer);pending.delete(request.id);reject(error);}
  });
}
function trustedRequester(sender) {
  const origin = new URL(sender.url || sender.tab?.url || 'https://invalid.local').origin;
  return {kind:'website',origin,display_name:new URL(origin).hostname,purpose:'unknown',purpose_confidence:0,trust_tier:'unknown'};
}
function rememberSignals(tabId, signals) {
  if (!signals || typeof signals !== 'object') return;
  tabSignals.set(tabId,{title:String(signals.title || '').slice(0,500),meta:String(signals.meta || '').slice(0,1000),headings:Array.isArray(signals.headings)?signals.headings.slice(0,10).map(value=>String(value).slice(0,300)):[],cta:String(signals.cta||'').slice(0,500),url_path:String(signals.url_path||'').split('?')[0].slice(0,500)});
}
async function blockTracking(tabId, origin, hosts) {
  const pageHost = new URL(origin).hostname;
  const cleanHosts = [...new Set(hosts)].filter(host => /^[a-z0-9.-]+$/i.test(host)).slice(0,100);
  const existing = await api.declarativeNetRequest.getDynamicRules();
  const base = 10000 + Math.abs(tabId % 10000) * 100;
  const removeRuleIds = existing.filter(rule => rule.id >= base && rule.id < base + 100).map(rule => rule.id);
  const addRules = cleanHosts.map((host,index)=>({id:base+index,priority:1,action:{type:'block'},condition:{urlFilter:`||${host}^`,initiatorDomains:[pageHost],resourceTypes:['script','image','xmlhttprequest','sub_frame','ping','other']}}));
  await api.declarativeNetRequest.updateDynamicRules({removeRuleIds,addRules});
  for (const host of cleanHosts) {
    const cookies = await api.cookies.getAll({domain:host});
    for (const cookie of cookies) await api.cookies.remove({url:`${cookie.secure?'https':'http'}://${cookie.domain.replace(/^\./,'')}${cookie.path}`,name:cookie.name,storeId:cookie.storeId});
  }
  await api.tabs.sendMessage(tabId,{pg:'block_local_tracking'}).catch(()=>{});
}
async function handleCommands(result) {
  for (const command of result?.commands || []) {
    if (command.type !== 'collect_context') continue;
    const tabs = await api.tabs.query({active:true,lastFocusedWindow:true});
    if (tabs[0]?.id) await api.tabs.sendMessage(tabs[0].id,{pg:'refresh_context',request_id:command.id}).catch(()=>{});
  }
}
async function route(message,sender) {
  await schemaReady;
  if (!message || message.pg !== 'request' || !sender.tab || !/^https?:/.test(sender.url || '')) throw new Error('Invalid browser sender');
  const tabId = sender.tab.id, requester = trustedRequester(sender);
  rememberSignals(tabId,message.signals);
  const payload = {...(message.payload || {})};
  if (message.type === 'event') {
    payload.event = {...payload.event,source:'browser',requester};
    if (payload.event.fields) {
      const allowed = ['field_id','category','label','name','input_type','autocomplete','required','asserted_required','filled','confidence'];
      payload.event.fields = payload.event.fields.map(field => Object.fromEntries(Object.entries(field).filter(([key])=>allowed.includes(key))));
    }
    if (!PGValidate(payload.event,schemas.event)) throw new Error('Invalid event');
    payload.signals = tabSignals.get(tabId) || {};
  }
  if (message.type === 'file_start') {payload.requester=requester;payload.signals=tabSignals.get(tabId)||{};}
  if (message.type === 'context') {
    payload.origin=requester.origin;payload.signals=tabSignals.get(tabId)||{};
    tabContexts.set(tabId,{...tabContexts.get(tabId),origin:requester.origin,signals:payload.signals});
  }
  if (message.type === 'storage_identifier') {
    if (!/^[a-f0-9]{64}$/.test(payload.hash||'')) throw new Error('Invalid identifier hash');
    const origins = storageOrigins.get(payload.hash) || new Set();origins.add(requester.origin);storageOrigins.set(payload.hash,origins);
    const tabs=storageTabs.get(payload.hash)||new Set();tabs.add(tabId);storageTabs.set(payload.hash,tabs);
    if(origins.size>1)for(const target of tabs)api.tabs.sendMessage(target,{pg:'tracking_identifier_confirmed',hash:payload.hash}).catch(()=>{});
    if(storageOrigins.size>2000)storageOrigins.delete(storageOrigins.keys().next().value);
    return {origin_count:origins.size};
  }
  if(message.type === 'fetch_policy') {
    const url=new URL(payload.url);if(!['https:','http:'].includes(url.protocol))throw new Error('Invalid policy URL');
    const response=await fetch(url.href,{credentials:'include',redirect:'follow'});if(!response.ok)throw new Error('Policy unavailable');
    const text=(await response.text()).slice(0,2000000);return {text:text.replace(/<script[\s\S]*?<\/script>/gi,' ').replace(/<style[\s\S]*?<\/style>/gi,' ').replace(/<[^>]+>/g,' ')};
  }
  if (message.type === 'block_tracking') {await blockTracking(tabId,requester.origin,payload.hosts||[]);return {blocked:true};}
  if (message.type === 'tracking_context') {
    const observed = tabContexts.get(tabId) || {};
    const cookies = await api.cookies.getAll({});
    const cname_hosts=[];
    if(api.dns?.resolve){for(const host of [...(observed.request_hosts||[])].slice(0,30)){if(!dnsCache.has(host)){try{const record=await api.dns.resolve(host,['canonical_name','offline']);dnsCache.set(host,record.canonicalName||'');}catch(_){dnsCache.set(host,'');}}const canonical=dnsCache.get(host);if(canonical&&canonical!==host)cname_hosts.push(canonical);}}
    return {cname_hosts,request_hosts:[...(observed.request_hosts||[])],urls:[...(observed.urls||[])],cookies:cookies.filter(cookie => (observed.request_hosts||new Set()).has(cookie.domain.replace(/^\./,''))).map(cookie=>({domain:cookie.domain,name:cookie.name,third_party:!requester.origin.endsWith(cookie.domain.replace(/^\./,'')),lifetime_days:cookie.expirationDate?Math.max(0,(cookie.expirationDate-Date.now()/1000)/86400):0}))};
  }
  if (message.type === 'action_poll') {
    const result = await native(message.type,payload);
    const action = result.action;
    if (action?.action === 'block') await blockTracking(tabId,requester.origin,(tabContexts.get(tabId)||{}).tracker_domains||[]);
    return result;
  }
  const result = await native(message.type,payload);
  if (result.tracking?.profile?.tracker_domains) tabContexts.set(tabId,{...tabContexts.get(tabId),tracker_domains:result.tracking.profile.tracker_domains});
  return result;
}
api.runtime.onMessage.addListener((message,sender,sendResponse)=> {
  route(message,sender).then(result=>sendResponse({ok:true,result})).catch(error=>sendResponse({ok:false,error:String(error.message||error)}));
  return true;
});
api.webRequest.onBeforeRequest.addListener(details => {
  if (details.tabId < 0) return;
  const context = tabContexts.get(details.tabId) || {};
  context.request_hosts = context.request_hosts || new Set(); context.urls=context.urls||new Set();
  try {context.request_hosts.add(new URL(details.url).hostname);} catch (_) {}
  // URL identifiers remain in transient browser memory; only category analysis results persist.
  if (context.urls.size<200) context.urls.add(details.url.slice(0,2000));
  tabContexts.set(details.tabId,context);
},{urls:['http://*/*','https://*/*']});
api.tabs.onRemoved.addListener(tabId=>{tabContexts.delete(tabId);tabSignals.delete(tabId);});
api.tabs.onUpdated.addListener((tabId,change)=>{if(change.status==='loading'){tabContexts.delete(tabId);tabSignals.delete(tabId);}});
api.action.onClicked.addListener(async tab => {
  if (!tab.id) return;
  await api.tabs.sendMessage(tab.id,{pg:'refresh_context'}).catch(()=>{});
  await native('deep_check',{origin:new URL(tab.url).origin}).catch(()=>{});
});
setInterval(()=>native('ping',{browser:'webextension'},4000).then(handleCommands).catch(()=>{}),1000);
connect();
