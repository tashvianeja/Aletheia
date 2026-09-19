(() => {
  if (globalThis.PG) return;
  const api = globalThis.browser || chrome;
  const PG = globalThis.PG = {api, collectors:[], submitChecks:[], panels:new Map()};
  PG.roots = () => {
    const roots=[document];
    for (let index=0;index<roots.length;index++) for(const element of roots[index].querySelectorAll('*')) if(element.shadowRoot) roots.push(element.shadowRoot);
    return roots;
  };
  PG.queryAll = selector => PG.roots().flatMap(root=>Array.from(root.querySelectorAll(selector)));
  PG.visible = element => element.getClientRects().length>0 && getComputedStyle(element).visibility!=='hidden' && getComputedStyle(element).display!=='none';
  PG.signals = () => ({title:document.title,meta:document.querySelector('meta[name="description"]')?.content||'',headings:PG.queryAll('h1,h2').slice(0,8).map(node=>node.textContent.slice(0,200)),cta:PG.queryAll('button,input[type=submit]').slice(0,5).map(node=>node.textContent||node.getAttribute('value')||'').join(' '),url_path:location.pathname});
  PG.request = async (type,payload={}) => {
    const response=await api.runtime.sendMessage({pg:'request',type,payload,signals:PG.signals()});
    if (!response?.ok) throw new Error(response?.error||'Local service unavailable');
    return response.result;
  };
  PG.wait = milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));
  PG.safeRace = (promise,milliseconds,fallback)=>Promise.race([promise,PG.wait(milliseconds).then(()=>fallback)]);
  const names={cancel:"Don't share",continue:'Continue',redact:'Create redacted copy',strip_metadata:'Strip location metadata',review_fields:'Review fields',reject_optional:'Reject optional',block:'Block if possible',open_settings:'Open system settings',mark_expected:'Mark as expected',view_details:'View details',learn_more:'Learn more',clear_clipboard:'Clear clipboard'};
  PG.showDecision = (decision,onAction) => {
    if(!decision||decision.outcome==='IGNORE'||PG.panels.has(decision.event_id)) return;
    const panel=document.createElement('section'); panel.className='pg-panel'; panel.setAttribute('role','status');panel.setAttribute('aria-label','Privacy Guardian');
    const title=document.createElement('strong');title.textContent='Privacy Guardian';panel.append(title);
    const explanation=document.createElement('p');explanation.textContent=decision.explanation;panel.append(explanation);
    const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Why?';details.append(summary);
    const rationale=document.createElement('p');rationale.textContent=(decision.rationale||[]).join(' ');details.append(rationale);panel.append(details);
    const actions=document.createElement('div');actions.className='pg-actions';
    for(const action of decision.actions||[]){const button=document.createElement('button');button.type='button';button.textContent=names[action]||action;button.dataset.pgAction=action;
      button.addEventListener('click',async()=>{button.disabled=true;try{const result=await PG.request('action',{event_id:decision.event_id,action});await onAction?.(result);panel.remove();PG.panels.delete(decision.event_id);}catch(_){button.disabled=false;explanation.textContent='That action could not be completed. Your submission remains held.';}});actions.append(button);}
    panel.append(actions);(document.body||document.documentElement).append(panel);PG.panels.set(decision.event_id,panel);
    if(decision.outcome==='INFORM') setTimeout(()=>{panel.remove();PG.panels.delete(decision.event_id);},8000);
  };
  PG.awaitDecision = async(decision,onAction)=> {
    if(!decision||decision.outcome!=='INTERVENE'){PG.showDecision(decision,onAction);return {action:'continue'};}
    let selected=null;
    PG.showDecision(decision,async action=>{await onAction?.(action);selected=action;});
    const started=Date.now();
    while(Date.now()-started<61000){if(selected)return selected;try{const reply=await PG.request('action_poll',{event_id:decision.event_id});if(!reply.pending&&reply.action){PG.panels.get(decision.event_id)?.remove();PG.panels.delete(decision.event_id);await onAction?.(reply.action);return reply.action;}}catch(_){}await PG.wait(300);}
    PG.panels.get(decision.event_id)?.remove();PG.panels.delete(decision.event_id);return {action:decision.default_action||'cancel'};
  };
  PG.highlight = fields=>{for(const field of fields||[]){const element=PG.queryAll('[data-pg-field-id]').find(node=>node.dataset.pgFieldId===field.field_id);if(element){element.classList.add('pg-review');element.setAttribute('aria-description','Review this information before sharing');}}};
  PG.collectContext = async(requestId)=>{
    const payload={origin:location.origin,request_id:requestId};
    for(const collector of PG.collectors){try{Object.assign(payload,await collector());}catch(_){}}
    return PG.request('context',payload);
  };
  api.runtime.onMessage.addListener((message,_sender,sendResponse)=>{
    if(message.pg==='refresh_context'){PG.collectContext(message.request_id).then(result=>sendResponse({ok:true,result})).catch(()=>sendResponse({ok:false}));return true;}
    if(message.pg==='tracking_identifier_confirmed'){window.postMessage({pgBridge:'mark_tracking_identifier',hash:message.hash},location.origin);sendResponse({ok:true});}
    if(message.pg==='block_local_tracking'){window.postMessage({pgBridge:'clear_tracking_identifiers'},location.origin);PG.rejectConsent?.();sendResponse({ok:true});}
  });
  const bypass=new WeakSet(),bypassClicks=new WeakSet();
  PG.approvedForms=new WeakSet();
  PG.checkSubmission=async form=>{for(const check of PG.submitChecks){if(!await check(form))return false;}return true;};
  document.addEventListener('click',async event=>{
    const button=event.target.closest?.('button,input[type=submit],input[type=image]');
    if(!button||!button.form||button.type==='button'||button.type==='reset'||button.closest('.pg-panel'))return;
    if(bypassClicks.has(button)){bypassClicks.delete(button);return;}
    event.preventDefault();event.stopImmediatePropagation();
    try{if(await PG.checkSubmission(button.form)){PG.approvedForms.add(button.form);bypassClicks.add(button);button.click();setTimeout(()=>PG.approvedForms.delete(button.form),0);}}catch(_){}
  },true);
  document.addEventListener('submit',async event=>{
    const form=event.target;if(!(form instanceof HTMLFormElement)||bypass.has(form)){bypass.delete(form);return;}
    if(PG.approvedForms.has(form)){PG.approvedForms.delete(form);return;}
    event.preventDefault();event.stopImmediatePropagation();
    let allowed=true;
    for(const check of PG.submitChecks){try{if(!await check(form)){allowed=false;break;}}catch(_){/* Sensor failure uses documented fail-open after bounded analysis. */}}
    if(allowed){bypass.add(form);if(form.requestSubmit)form.requestSubmit(event.submitter||undefined);else HTMLFormElement.prototype.submit.call(form);}
  },true);
})();
