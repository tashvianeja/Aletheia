(() => {
  let adapters={}, current=null, last='', timer=null, tcf=null;
  window.addEventListener('message',event=>{if(event.source===window&&event.data?.pgBridge==='tcf_snapshot'){tcf=event.data;schedule();}});
  const ready=fetch(PG.api.runtime.getURL('data/cmp_adapters.json')).then(response=>response.json()).then(value=>{adapters=value;});
  function colorLuminance(color){const values=(color.match(/[\d.]+/g)||[]).slice(0,3).map(Number).map(value=>{value/=255;return value<=.04045?value/12.92:((value+.055)/1.055)**2.4;});return values.length===3?.2126*values[0]+.7152*values[1]+.0722*values[2]:1;}
  function contrast(element){const style=getComputedStyle(element);const foreground=colorLuminance(style.color),background=colorLuminance(style.backgroundColor);return (Math.max(foreground,background)+.05)/(Math.min(foreground,background)+.05);}
  async function snapshot(){await ready;let banner=null,cmp='unknown',selectors=[];
    for(const [name,adapter]of Object.entries(adapters)){for(const selector of adapter.selectors){const match=PG.queryAll(selector).find(PG.visible);if(match){banner=match;cmp=name;selectors.push(selector);break;}}if(banner)break;}
    if(!banner)banner=PG.queryAll('[role=dialog],[role=region],aside,section,div').slice(0,2000).find(element=>{if(element.closest('.pg-panel'))return false;const style=getComputedStyle(element);return ['fixed','sticky'].includes(style.position)&&PG.visible(element)&&/cookies?|consent|privacy preferences/i.test(element.textContent||'')&&element.querySelector('button,[role=button]');});
    if(!banner)return null;current={banner,cmp};const text=(banner.textContent||'').slice(0,12000);
    const buttons=Array.from(banner.querySelectorAll('button,a,[role=button],input[type=button]')).map(button=>{const rect=button.getBoundingClientRect();return {text:(button.textContent||button.value||'').slice(0,200),visible:PG.visible(button),area:rect.width*rect.height,contrast:contrast(button),layer:1};});
    const toggles=Array.from(banner.querySelectorAll('input[type=checkbox],[role=switch]')).map(toggle=>({purpose:(toggle.labels?.[0]?.textContent||toggle.getAttribute('aria-label')||toggle.name||'optional').trim().slice(0,200),enabled:!!toggle.checked||toggle.getAttribute('aria-checked')==='true',optional:!toggle.disabled,legitimate_interest:/legitimate interest/i.test(toggle.closest('label,section,div')?.textContent||'')}));
    const vendorMatch=text.match(/(\d+)\s+(?:vendors|partners)/i);
    return {text,cmp,selectors,buttons,toggles,vendor_count:vendorMatch?Number(vendorMatch[1]):0,tcf_present:!!tcf||!!document.querySelector('iframe[name="__tcfapiLocator"]'),tcf_purpose_consents:tcf?.purpose_consents||{},tcf_vendor_count:tcf?.vendor_count||0,fixed_or_sticky:true,reject_clicks:buttons.some(button=>/reject|decline|necessary only/i.test(button.text))?1:2};
  }
  PG.rejectConsent=async()=>{await ready;if(!current)return false;const adapter=adapters[current.cmp];
    const clickSelectors=selectors=>{for(const selector of selectors||[]){const button=PG.queryAll(selector).find(PG.visible);if(button){button.click();return true;}}return false;};
    if(clickSelectors(adapter?.reject))return true;
    const match=Array.from(current.banner.querySelectorAll('button,a,[role=button]')).find(button=>PG.visible(button)&&/reject|decline|necessary only|refuser|ablehnen|rechazar/i.test(button.textContent||''));if(match){match.click();return true;}
    if(clickSelectors(adapter?.manage)){await PG.wait(150);if(clickSelectors(adapter.reject))return true;}
    const manage=Array.from(current.banner.querySelectorAll('button,a')).find(button=>/manage|preferences|settings/i.test(button.textContent||''));if(manage){manage.click();await PG.wait(150);const reject=PG.queryAll('button,a').find(button=>PG.visible(button)&&/reject all|necessary only|decline all/i.test(button.textContent||''));if(reject){reject.click();return true;}manage.classList.add('pg-review');}
    return false;
  };
  async function analyze(){try{const value=await snapshot();if(!value)return;const fingerprint=JSON.stringify(value);if(last===fingerprint)return;last=fingerprint;const result=await PG.request('context',{consent:{snapshot:value}});if(result.consent?.decision)PG.showDecision(result.consent.decision,async action=>{if(action.action==='reject_optional')await PG.rejectConsent();});}catch(_){}}
  function schedule(){clearTimeout(timer);timer=setTimeout(analyze,150);}
  PG.collectors.push(async()=>{const value=await snapshot();return {consent:{snapshot:value||{text:"",cmp:"none",buttons:[],toggles:[],fixed_or_sticky:false}}};});
  const start=()=>{new MutationObserver(records=>{if(records.some(record=>!record.target.closest?.('.pg-panel')))schedule();}).observe(document.documentElement,{childList:true,subtree:true});schedule();};
  if(document.documentElement)start();else document.addEventListener('DOMContentLoaded',start,{once:true});
})();
