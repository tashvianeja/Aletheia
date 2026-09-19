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
  const FALLBACK_LABELS={cancel:"Cancel",continue:'Continue',redact:'Create redacted copy',strip_metadata:'Remove location first',review_fields:'Review fields',reject_optional:'Reject optional',block:'Block if possible',open_settings:'Review access',mark_expected:'Expected',view_details:'View details',learn_more:'Learn more',clear_clipboard:'Clear clipboard'};
  const SVG='http://www.w3.org/2000/svg';
  // Same glyph set as the desktop widget, drawn inline so no network request is needed.
  const GLYPHS={
    padlock:{c:'#3b5bdb',d:'<path fill="none" stroke="#3b5bdb" stroke-width="1.7" stroke-linecap="round" d="M6.4 10.2V7.3a3.6 3.6 0 0 1 7.2 0v2.9"/><rect x="4.2" y="10.2" width="11.6" height="8.1" rx="2.2" fill="none" stroke="#3b5bdb" stroke-width="1.7"/>'},
    shield:{d:'<path fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" d="M10 2.6 16.4 5v5.1c0 4-3.8 6.4-6.4 7.6-2.6-1.2-6.4-3.6-6.4-7.6V5z"/>'},
    warn:{d:'<path fill="#d97706" d="M10 2.9 18.6 17H1.4z"/><path fill="#fff" d="M9.1 7.3h1.8v5h-1.8zM9.1 13.6h1.8v1.8H9.1z"/>'},
    ok:{d:'<circle cx="10" cy="10" r="7.6" fill="#059669"/><path fill="none" stroke="#fff" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" d="m6.6 10.2 2.4 2.4 4.4-5"/>'},
    info:{d:'<rect x="4" y="9.2" width="12" height="1.7" rx="0.85" fill="#9ca3af"/>'},
    close:{d:'<path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" d="m5.8 5.8 8.4 8.4M14.2 5.8l-8.4 8.4"/>'},
    arrow:{d:'<path fill="none" stroke="#9ca3af" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" d="M4 10h11m-3.4-3.4L15 10l-3.4 3.4"/>'}
  };
  function icon(name){const node=document.createElementNS(SVG,'svg');node.setAttribute('viewBox','0 0 20 20');node.setAttribute('aria-hidden','true');node.innerHTML=GLYPHS[name]?.d||'';return node;}
  function element(tag,className,text){const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node;}
  PG.decisionStates=new Map();
  // Every panel lives in one bottom-right column, newest above, so none of them can
  // cover another one's buttons.
  PG.stack=()=>{
    let host=document.querySelector('.pg-stack');
    if(!host){host=element('div','pg-stack');(document.body||document.documentElement).append(host);}
    else if(host.parentNode!==(document.body||document.documentElement))(document.body||document.documentElement).append(host);
    return host;
  };
  // The widget: one card, laid out exactly as the desktop popup lays it out.
  function buildPanel(decision,state){
    const informational=decision.outcome==='INFORM';
    const panel=element('section','pg-panel');
    panel.setAttribute('role',informational?'status':'alertdialog');
    panel.setAttribute('aria-label','Privacy Guardian');
    panel.setAttribute('aria-live',informational?'polite':'assertive');
    const headline=element('p','pg-headline',decision.headline||decision.explanation);
    const dismiss=()=>{const close=element('button','pg-close');close.type='button';close.setAttribute('aria-label','Dismiss');close.append(icon('close'));close.addEventListener('click',()=>state.dismiss());return close;};
    if(informational){
      const head=element('div','pg-head');
      // A tick reports something that is fine or already handled; anything else that
      // is worth saying gets the neutral mark, never a green all-clear.
      const severity=(decision.findings||[]).some(item=>item.severity==='warn')?'warn':(decision.auto_action||(decision.risk||0)<0.25)?'ok':'info';
      head.append(icon(severity),headline);
      headline.style.margin='0';
      headline.style.flex='1';
      if(decision.destination)head.append(element('span','pg-origin',decision.destination));
      head.append(dismiss());
      panel.append(head);
    }else{
      const head=element('div','pg-head');
      head.append(icon('padlock'),element('span','pg-name','Privacy Guardian'));
      if(decision.destination)head.append(element('span','pg-origin',decision.destination));
      head.append(dismiss());
      panel.append(head,headline);
    }
    const body=element('p','pg-body',decision.body||'');
    const rows=element('ul','pg-rows');
    for(const finding of decision.findings||[]){
      const item=document.createElement('li');
      item.append(icon(finding.severity||'warn'));
      const text=element('span','pg-row-label',finding.label);
      if(finding.detail)text.append(element('span','pg-row-detail',finding.detail));
      item.append(text);
      rows.append(item);
    }
    const order=decision.layout==='findings_first'?[rows,body]:[body,rows];
    for(const part of order){if(part===body&&!decision.body)continue;if(part===rows&&!rows.children.length)continue;panel.append(part);}
    const rationale=element('ul','pg-rationale');
    for(const line of decision.rationale||[])rationale.append(element('li',null,line));
    rationale.hidden=true;panel.append(rationale);
    const remember=element('label','pg-remember');
    const check=document.createElement('input');check.type='checkbox';
    remember.append(check,document.createTextNode("Don't ask again for this site"));
    remember.hidden=true;panel.append(remember);
    if(!informational){
      if(decision.subject||decision.destination){
        panel.append(element('hr','pg-rule'));
        const context=element('div','pg-context');
        context.append(element('span',null,decision.subject||''));
        if(decision.destination){context.append(icon('arrow'),element('span',null,decision.destination));}
        panel.append(context);
      }
      const labels=decision.action_labels||{};
      const primary=decision.primary_action||decision.default_action;
      const tertiary=decision.tertiary_action||'';
      const make=(action,tier)=>{
        const button=element('button','pg-'+tier,labels[action]||FALLBACK_LABELS[action]||action);
        button.type='button';button.dataset.pgAction=action;
        button.addEventListener('click',async()=>{
          button.disabled=true;
          try{await state.apply(await PG.request('action',{event_id:decision.event_id,action,remember:check.checked}));}
          catch(_){body.textContent='That action could not be completed. Your submission remains held.';}
          finally{button.disabled=false;}
        });
        return button;
      };
      const actions=element('div','pg-actions');
      for(const action of decision.actions||[]){if(action===tertiary||action===primary)continue;actions.append(make(action,'secondary'));}
      if((decision.actions||[]).includes(primary))actions.append(make(primary,'primary'));
      if(tertiary&&(decision.actions||[]).includes(tertiary))actions.prepend(make(tertiary,'tertiary'));
      panel.append(actions);
    }
    const foot=element('div','pg-foot');
    foot.append(icon('shield'),element('span',null,'Analysed on this device'));
    if(!informational){
      const why=element('button','pg-why','Why am I seeing this?');why.type='button';
      why.addEventListener('click',()=>{const showing=rationale.hidden;rationale.hidden=!showing||!(decision.rationale||[]).length;remember.hidden=!showing;});
      foot.append(why);
    }
    panel.append(foot);
    return {panel,body,rationale,remember,check};
  }
  PG.showDecision = (decision,onAction) => {
    if(!decision||decision.outcome==='IGNORE')return Promise.resolve({action:'continue'});
    const previous=PG.decisionStates.get(decision.event_id);
    // A page keeps reporting itself, and a later look sharpens what the service has
    // already said about it under the same event id. That belongs in the card that is
    // up: a second card would tell the person the same thing twice.
    if(previous){if(!previous.onAction&&onAction)previous.onAction=onAction;previous.refresh(decision);return previous.promise;}
    const state={onAction,decision,resolved:false,processing:false,watching:false,selected:null};
    state.promise=new Promise(resolve=>{state.resolve=resolve;});PG.decisionStates.set(decision.event_id,state);
    const close=()=>{state.view.panel.remove();PG.panels.delete(decision.event_id);};
    state.apply=async result=>{if(state.resolved||state.processing)return;state.processing=true;try{await state.onAction?.(result);state.selected=result;state.resolved=true;close();state.resolve(result);}catch(_){state.view.body.textContent='That action could not be completed. Your submission remains held.';}finally{state.processing=false;}};
    // Dismissing an intervention is the same as letting it time out: the safe default stands.
    state.dismiss=()=>{if(state.decision.outcome==='INTERVENE'){state.apply({action:state.decision.default_action||'cancel'});}else{state.resolved=true;close();state.resolve({action:'continue'});}};
    // The answer can also be given on the desktop widget, so the page watches for one
    // the whole time it is asking.
    state.watch=()=>{
      if(state.watching||state.resolved)return;
      state.watching=true;
      (async()=>{const started=Date.now();while(!state.resolved&&Date.now()-started<61000){try{const reply=await PG.request('action_poll',{event_id:decision.event_id});if(!reply.pending&&reply.action)await state.apply(reply.action);}catch(_){}if(!state.resolved)await PG.wait(300);}if(!state.resolved)await state.apply({action:state.decision.default_action||'cancel'});setTimeout(()=>PG.decisionStates.delete(decision.event_id),240000);})();
    };
    state.refresh=next=>{
      if(state.resolved||JSON.stringify(next)===JSON.stringify(state.decision))return;
      state.decision=next;
      const refreshed=buildPanel(next,state);
      // Newer wording, same reader: what they have opened or ticked stays as they left it.
      refreshed.check.checked=state.view.check.checked;
      refreshed.remember.hidden=state.view.remember.hidden;
      refreshed.rationale.hidden=state.view.remember.hidden||!(next.rationale||[]).length;
      // Keep its place in the column so the card being read does not jump; if the page
      // has torn the old one out from under us, put the new one back in the stack.
      if(state.view.panel.parentNode)state.view.panel.replaceWith(refreshed.panel);else PG.stack().append(refreshed.panel);
      state.view=refreshed;PG.panels.set(next.event_id,refreshed.panel);
      if(next.outcome!=='INFORM')state.watch();
    };
    state.view=buildPanel(decision,state);
    PG.stack().append(state.view.panel);PG.panels.set(decision.event_id,state.view.panel);
    if(decision.auto_action){
      // The user authorised this action; carry it out, record it, let the toast report it.
      (async()=>{try{await state.onAction?.({action:decision.auto_action});}catch(_){}
        try{await PG.request('action',{event_id:decision.event_id,action:decision.auto_action});}catch(_){}})();
    }
    if(decision.outcome!=='INFORM')state.watch();
    return state.promise;
  };
  PG.awaitDecision = async(decision,onAction)=> {
    if(!decision||decision.outcome!=='INTERVENE'){PG.showDecision(decision,onAction);return {action:'continue'};}
    return PG.showDecision(decision,onAction);
  };
  // The compact bar from the component set: what just happened, and a way to dismiss it.
  PG.confirm = message=>{
    document.querySelector('.pg-panel[data-pg-confirm]')?.remove();
    const panel=element('section','pg-panel');panel.dataset.pgConfirm='1';
    panel.setAttribute('role','status');panel.style.width='auto';panel.style.padding='12px 14px';
    const row=element('div','pg-head');row.style.margin='0';
    row.append(icon('padlock'),element('span','pg-row-label',message));
    const done=element('button','pg-primary','Done');done.type='button';
    done.style.marginLeft='14px';
    done.addEventListener('click',()=>panel.remove());
    row.append(done);panel.append(row);
    PG.stack().append(panel);
    setTimeout(()=>panel.remove(),8000);
    return panel;
  };
  // Take every card down at once, each the way its own close control would: the
  // safe answer stands for anything a card was holding. The desktop asks for this
  // when the thorough check goes up in the same corner.
  PG.dismissAll = ()=>{
    for(const state of PG.decisionStates.values())if(!state.resolved)state.dismiss();
    document.querySelectorAll('.pg-panel[data-pg-confirm]').forEach(panel=>panel.remove());
  };
  // "Show me where": find the quoted clause on the page and take the reader to it.
  PG.showClauses = citations=>{
    const wanted=(citations||[]).map(text=>String(text).replace(/\s+/g,' ').trim().slice(0,120)).filter(Boolean);
    let first=null,found=0;
    if(wanted.length){
      const walker=document.createTreeWalker(document.body||document.documentElement,NodeFilter.SHOW_TEXT);
      const seen=new Set();
      for(let node=walker.nextNode();node;node=walker.nextNode()){
        const text=(node.textContent||'').replace(/\s+/g,' ');
        for(const phrase of wanted){
          if(seen.has(phrase)||phrase.length<24||!text.includes(phrase))continue;
          const host=node.parentElement;
          if(!host||host.closest('.pg-panel,.pg-stack'))continue;
          seen.add(phrase);host.classList.add('pg-review');
          host.setAttribute('aria-description','Privacy Guardian flagged this clause');
          first=first||host;found++;
        }
      }
    }
    if(first)first.scrollIntoView({behavior:'smooth',block:'center'});
    PG.confirm(found?`${found} clause${found===1?'':'s'} highlighted on this page`:'The clause text could not be located on this page');
    return found;
  };
  PG.highlight = fields=>{for(const field of fields||[]){const element=PG.queryAll('[data-pg-field-id]').find(node=>node.dataset.pgFieldId===field.field_id);if(element){element.classList.add('pg-review');element.setAttribute('aria-description','Review this information before sharing');}}};
  PG.collectContext = async(requestId)=>{
    const payload={origin:location.origin,request_id:requestId};
    for(const collector of PG.collectors){try{Object.assign(payload,await collector());}catch(_){}}
    return PG.request('context',payload);
  };
  api.runtime.onMessage.addListener((message,_sender,sendResponse)=>{
    if(message.pg==='refresh_context'){PG.collectContext(message.request_id).then(result=>sendResponse({ok:true,result})).catch(()=>sendResponse({ok:false}));return true;}
    if(message.pg==='dismiss_panels'){PG.dismissAll();sendResponse({ok:true});}
    if(message.pg==='tracking_identifier_confirmed'){window.postMessage({pgBridge:'mark_tracking_identifier',hash:message.hash},location.origin);sendResponse({ok:true});}
    if(message.pg==='block_local_tracking'){window.postMessage({pgBridge:'clear_tracking_identifiers'},location.origin);PG.rejectConsent?.();sendResponse({ok:true});}
  });
  const bypass=new WeakSet(),bypassClicks=new WeakSet();
  PG.approvedForms=new WeakSet();
  PG.checkSubmission=async form=>{for(const check of PG.submitChecks){if(!await check(form))return false;}return true;};
  document.addEventListener('click',async event=>{
    const button=event.target.closest?.('button,input[type=submit],input[type=image]');
    if(!button||!button.form||button.type==='button'||button.type==='reset'||button.closest('.pg-panel,.pg-stack'))return;
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
