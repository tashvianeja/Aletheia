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
  const FALLBACK_LABELS={cancel:"Cancel",continue:'Continue',redact:'Create redacted copy',strip_metadata:'Remove location first',review_fields:'Review fields',clear_fields:"Send only what's needed",redact_fields:'Redact these fields',reject_optional:'Reject optional',block:'Block if possible',open_settings:'Review access',mark_expected:'Expected',view_details:'View details',learn_more:'Learn more',clear_clipboard:'Clear clipboard'};
  // What a notice does not offer, mirroring engine.presentation.NOTICE_SILENT: nothing
  // is held up, so there is nothing to carry on with or refuse, and "Learn more" is
  // the footer's "Why am I seeing this?" by another name.
  const NOTICE_SILENT=new Set(['continue','cancel','learn_more']);
  const SVG='http://www.w3.org/2000/svg';
  // Same glyph set as the desktop widget, drawn inline so no network request is needed.
  const GLYPHS={
    padlock:{c:'#3b5bdb',d:'<path fill="none" stroke="#3b5bdb" stroke-width="1.7" stroke-linecap="round" d="M6.4 10.2V7.3a3.6 3.6 0 0 1 7.2 0v2.9"/><rect x="4.2" y="10.2" width="11.6" height="8.1" rx="2.2" fill="none" stroke="#3b5bdb" stroke-width="1.7"/>'},
    shield:{d:'<path fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" d="M10 2.6 16.4 5v5.1c0 4-3.8 6.4-6.4 7.6-2.6-1.2-6.4-3.6-6.4-7.6V5z"/>'},
    // Filled marks take their colour from CSS (currentColor), so a warning row on a red
    // card is red and the same row on an amber card is amber.
    warn:{d:'<path fill="currentColor" d="M10 2.9 18.6 17H1.4z"/><path fill="var(--pg-cut,#fff)" d="M9.1 7.3h1.8v5h-1.8zM9.1 13.6h1.8v1.8H9.1z"/>'},
    ok:{d:'<circle cx="10" cy="10" r="7.6" fill="currentColor"/><path fill="none" stroke="var(--pg-cut,#fff)" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" d="m6.6 10.2 2.4 2.4 4.4-5"/>'},
    info:{d:'<rect x="4" y="9.2" width="12" height="1.7" rx="0.85" fill="currentColor"/>'},
    stop:{d:'<path fill="currentColor" d="M6.7 2.2h6.6l4.5 4.5v6.6l-4.5 4.5H6.7l-4.5-4.5V6.7z"/><path fill="var(--pg-cut,#fff)" d="M9.1 5.9h1.8v5.4h-1.8zM9.1 12.7h1.8v1.8H9.1z"/>'},
    alert:{d:'<circle cx="10" cy="10" r="7.6" fill="currentColor"/><path fill="var(--pg-cut,#fff)" d="M9.1 5.9h1.8v5.4h-1.8zM9.1 12.7h1.8v1.8H9.1z"/>'},
    note:{d:'<circle cx="10" cy="10" r="7.6" fill="currentColor"/><path fill="var(--pg-cut,#fff)" d="M9.1 8.8h1.8v5.4h-1.8zM9.1 5.8h1.8v1.8H9.1z"/>'},
    close:{d:'<path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" d="m5.8 5.8 8.4 8.4M14.2 5.8l-8.4 8.4"/>'},
    arrow:{d:'<path fill="none" stroke="#9ca3af" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" d="M4 10h11m-3.4-3.4L15 10l-3.4 3.4"/>'}
  };
  function icon(name){const node=document.createElementNS(SVG,'svg');node.setAttribute('viewBox','0 0 20 20');node.setAttribute('aria-hidden','true');node.innerHTML=GLYPHS[name]?.d||'';return node;}
  // The band across the top of every card: the tier's icon and the tier in words. The
  // service sends the tier; the fallback mirrors engine.presentation.urgency_for for a
  // decision built by an older service.
  const URGENCY_ICONS={act_now:'stop',attention:'warn',heads_up:'alert',all_clear:'ok',note:'note'};
  const URGENCY_LABELS={act_now:'Act now',attention:'Needs your attention',heads_up:'Heads up',all_clear:'All clear',note:'For your information'};
  function urgencyFor(decision){
    if(decision.urgency&&URGENCY_ICONS[decision.urgency])return decision.urgency;
    const risk=decision.risk||0;
    if(decision.outcome==='INTERVENE')return risk>=0.75?'act_now':'attention';
    if(decision.auto_action)return 'all_clear';
    if((decision.findings||[]).some(item=>item.severity==='warn'))return 'heads_up';
    if(risk<0.25)return 'all_clear';
    return decision.outcome==='INFORM'?'heads_up':'note';
  }
  function band(urgency,label,onClose){
    const head=element('div','pg-band');
    head.append(icon(URGENCY_ICONS[urgency]||'note'),element('span','pg-band-label',label));
    head.append(element('span','pg-brand','Privacy Guardian'));
    if(onClose){const close=element('button','pg-close');close.type='button';close.setAttribute('aria-label','Dismiss');close.append(icon('close'));close.addEventListener('click',onClose);head.append(close);}
    return head;
  }
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
    const urgency=urgencyFor(decision);
    const panel=element('section','pg-panel');
    panel.dataset.pgUrgency=urgency;
    panel.setAttribute('role',informational?'status':'alertdialog');
    panel.setAttribute('aria-label','Privacy Guardian: '+(URGENCY_LABELS[urgency]||''));
    panel.setAttribute('aria-live',informational?'polite':'assertive');
    const headline=element('p','pg-headline',decision.headline||decision.explanation);
    const label=urgency==='all_clear'&&decision.auto_action?'Handled for you':URGENCY_LABELS[urgency];
    panel.append(band(urgency,label,()=>state.dismiss()),headline);
    const body=element('p','pg-body',decision.body||'');
    const rows=element('ul','pg-rows');
    for(const finding of decision.findings||[]){
      const item=document.createElement('li');
      item.dataset.pgSeverity=finding.severity||'warn';
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
    if(decision.subject||decision.destination){
      panel.append(element('hr','pg-rule'));
      const context=element('div','pg-context');
      context.append(element('strong',null,decision.subject||''));
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
        catch(_){body.textContent=informational?'That could not be done. Nothing on this page has changed.':'That action could not be completed. Your submission remains held.';}
        finally{button.disabled=false;}
      });
      return button;
    };
    const actions=element('div','pg-actions');
    if(!informational){
      for(const action of decision.actions||[]){if(action===tertiary||action===primary)continue;actions.append(make(action,'secondary'));}
      if((decision.actions||[]).includes(primary))actions.append(make(primary,'primary'));
      if(tertiary&&(decision.actions||[]).includes(tertiary))actions.prepend(make(tertiary,'tertiary'));
    }else{
      // A notice asks for no decision, so it has no "carry on" and no "refuse": it
      // holds nothing up for either to apply to. It does offer its remedies — the
      // workflows the person may want run now they know: block the trackers, take
      // the location out of the photo, reject the optional cookies — and it always
      // has OK, because a card whose only control is the cross in its corner reads
      // as a card still waiting for something. OK does exactly what the cross does.
      const offered=(decision.actions||[]).filter(action=>!NOTICE_SILENT.has(action));
      const ok=element('button',offered.length?'pg-secondary':'pg-primary','OK');
      ok.type='button';ok.dataset.pgAck='1';ok.setAttribute('aria-label','OK');
      ok.addEventListener('click',()=>state.dismiss());
      actions.append(ok);
      for(const action of offered){if(action!==primary)actions.append(make(action,'secondary'));}
      if(offered.includes(primary))actions.append(make(primary,'primary'));
    }
    panel.append(actions);
    const foot=element('div','pg-foot');
    foot.append(icon('shield'),element('span',null,'Analysed on this device'));
    // Everything the card does not say out loud lives behind this: how it is being
    // done, the reasoning, and the way to stop being told about this site. An
    // informational card needs it most, being the one with no buttons at all.
    const why=element('button','pg-why','Why am I seeing this?');why.type='button';
    // Keyed off the checkbox, which is always there: the reasoning list is not, and
    // a card without one used to open and never close again.
    why.addEventListener('click',()=>{const showing=remember.hidden;rationale.hidden=!showing||!(decision.rationale||[]).length;remember.hidden=!showing;});
    foot.append(why);
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
    // Closing anything else is an answer too, and saying so is what stops it coming
    // back on the next page — and what makes "Don't ask again for this site" mean
    // something. A card nobody ever answers is one the person may never have seen.
    // Making room for another surface is not the person answering: that path passes
    // answered=false, so anything the card was holding still takes its safe default
    // but the question itself stays open and is put to them again.
    state.dismiss=(answered=true)=>{
      if(state.decision.outcome==='INTERVENE'){state.apply({action:state.decision.default_action||'cancel'});return;}
      state.resolved=true;
      if(answered&&(state.decision.actions||[]).includes('continue'))PG.request('action',{event_id:decision.event_id,action:'continue',remember:state.view.check.checked}).catch(()=>{});
      close();state.resolve({action:'continue'});
    };
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
  // The card a finished workflow shows for itself: the same card as every other, in
  // the green register, with "Done" on the band and OK as its one button. It stays
  // until it is read — a receipt that removes itself after a few seconds is one the
  // person may never have finished reading. The service composes the words, so the
  // desktop and the page report the same workflow in the same sentence.
  // A workflow that hands the page over the moment it has run — blanking a form's
  // fields and sending it — shows its receipt on a page that is about to be replaced.
  // It is carried across to the next page in this tab, for a few seconds only: a
  // receipt turning up on some later visit would be a receipt for nothing anyone
  // remembers doing. Session storage is the page's own, and holds nothing the page
  // did not already know: which of its fields went, never what was in them.
  const CARRY_KEY='pg-receipt',CARRY_MS=15000;
  PG.showResult = (report,options={})=>{
    const headline=String(report?.headline||'');if(!headline)return null;
    if(options.carry){try{sessionStorage.setItem(CARRY_KEY,JSON.stringify({report,at:Date.now()}));}catch(_){}}
    for(const existing of document.querySelectorAll('.pg-panel[data-pg-result]')){
      // The same receipt twice is one receipt: replace it rather than stack it.
      if(existing.dataset.pgHeadline===headline)existing.remove();
    }
    const panel=element('section','pg-panel');panel.dataset.pgResult='1';panel.dataset.pgUrgency='all_clear';panel.dataset.pgHeadline=headline;
    panel.setAttribute('role','status');panel.setAttribute('aria-live','polite');
    panel.setAttribute('aria-label','Privacy Guardian: Done');
    const close=()=>panel.remove();
    panel.append(band('all_clear','Done',close),element('p','pg-headline',headline));
    if(report.body)panel.append(element('p','pg-body',String(report.body)));
    if(report.subject||report.destination){
      panel.append(element('hr','pg-rule'));
      const context=element('div','pg-context');
      context.append(element('strong',null,String(report.subject||'')));
      if(report.destination){context.append(icon('arrow'),element('span',null,String(report.destination)));}
      panel.append(context);
    }
    const actions=element('div','pg-actions');
    const ok=element('button','pg-primary','OK');ok.type='button';ok.dataset.pgAck='1';ok.setAttribute('aria-label','OK');
    ok.addEventListener('click',close);actions.append(ok);panel.append(actions);
    const foot=element('div','pg-foot');
    foot.append(icon('shield'),element('span',null,'Analysed on this device'));
    panel.append(foot);
    PG.stack().append(panel);
    return panel;
  };
  // Blank the fields a form has no business asking for, and mark them so the person
  // can see which. What is removed is only ever the box's contents; nothing is read.
  PG.clearFields = fieldIds=>{
    let cleared=0;
    for(const id of fieldIds||[]){
      const element_=PG.queryAll('[data-pg-field-id]').find(node=>node.dataset.pgFieldId===id);
      if(!element_)continue;
      if(element_.isContentEditable)element_.textContent='';
      else if(['checkbox','radio'].includes(element_.type))element_.checked=false;
      else element_.value='';
      // Say so the way typing would, so a page that watches its own fields notices.
      element_.dispatchEvent(new Event('input',{bubbles:true}));
      element_.dispatchEvent(new Event('change',{bubbles:true}));
      element_.classList.add('pg-review');element_.setAttribute('aria-description','Left blank: not needed for this');
      const tag=document.createElement('span');tag.className='pg-badge';tag.dataset.pgCleared='1';tag.textContent='Left blank';tag.setAttribute('role','note');
      element_.insertAdjacentElement('afterend',tag);
      cleared++;
    }
    return cleared;
  };
  // Replace what a form has no business asking for with bullets, in the boxes
  // themselves, before anything is sent. Nothing is read back and nothing is stored:
  // each box is handed as many bullets as it held characters, so a page that checks
  // the length of what it was given still sees what it expects, and a box the form
  // insists on stays filled in — which is why this is offered where blanking cannot be.
  const BULLET='\u2022';
  PG.redactFields = fieldIds=>{
    let redacted=0;
    for(const id of fieldIds||[]){
      const element_=PG.queryAll('[data-pg-field-id]').find(node=>node.dataset.pgFieldId===id);
      if(!element_)continue;
      const held=element_.isContentEditable?(element_.textContent||''):(element_.value||'');
      if(!held)continue;
      const mask=BULLET.repeat(Math.max(1,Math.min(held.length,512)));
      if(element_.isContentEditable)element_.textContent=mask;else element_.value=mask;
      // A box that would not take the bullets — one that keeps only dates, or only
      // numbers — is left exactly as it was rather than quietly emptied.
      if((element_.isContentEditable?element_.textContent:element_.value)!==mask)continue;
      // Say so the way typing would, so a page that watches its own fields notices.
      element_.dispatchEvent(new Event('input',{bubbles:true}));
      element_.dispatchEvent(new Event('change',{bubbles:true}));
      element_.classList.remove('pg-review');
      element_.classList.add('pg-redacted');
      // Marked on the box itself, so the next inventory pass does not put the
      // "May be unnecessary" badge back on a box that has already been dealt with.
      element_.dataset.pgRedacted='1';
      element_.setAttribute('aria-description','Redacted: this box now holds bullets, not what you typed');
      // The "May be unnecessary" beside this box has been answered, so it goes and the
      // mark saying what was done takes its place. Left there, the two sat side by side
      // and the box read as both dealt with and still outstanding.
      while(element_.nextElementSibling?.classList?.contains('pg-badge'))element_.nextElementSibling.remove();
      const tag=document.createElement('span');tag.className='pg-badge';tag.dataset.pgRedacted='1';tag.textContent='Redacted';tag.setAttribute('role','note');
      element_.insertAdjacentElement('afterend',tag);
      redacted++;
    }
    return redacted;
  };
  // Take one card down without answering it. The question it asked has been overtaken
  // by a larger one about the same thing — the form being looked at is now the form
  // being sent — and the two of them up together ask the person the same thing twice.
  // Nothing is recorded, because nothing was answered: the larger card carries it now.
  PG.putDown = eventId=>{
    const state=PG.decisionStates.get(eventId);
    if(state&&!state.resolved)state.dismiss(false);
  };
  // Take every card down at once, each the way its own close control would: the
  // safe answer stands for anything a card was holding. The desktop asks for this
  // when the thorough check goes up in the same corner.
  PG.dismissAll = ()=>{
    // The check card needs this corner; the person has not said anything about what
    // was in it. An informational card is owed to them again on the next page.
    for(const state of PG.decisionStates.values())if(!state.resolved)state.dismiss(false);
    document.querySelectorAll('.pg-panel[data-pg-result]').forEach(panel=>panel.remove());
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
    PG.showResult(found
      ?{headline:`${found} clause${found===1?'':'s'} highlighted on this page`,body:'Each one is outlined in amber where it appears. Nothing has been agreed to yet.'}
      :{headline:'The clause text could not be located on this page',body:'Read the terms yourself before agreeing to them. Nothing has been agreed to yet.'});
    return found;
  };
  PG.highlight = fields=>{for(const field of fields||[]){const element=PG.queryAll('[data-pg-field-id]').find(node=>node.dataset.pgFieldId===field.field_id);if(element){element.classList.add('pg-review');element.setAttribute('aria-description','Review this information before sharing');}}};
  const carried=()=>{
    let raw=null;
    try{raw=sessionStorage.getItem(CARRY_KEY);if(raw)sessionStorage.removeItem(CARRY_KEY);}catch(_){return;}
    if(!raw)return;
    try{const {report,at}=JSON.parse(raw);if(Date.now()-Number(at)<CARRY_MS&&report&&typeof report==='object')PG.showResult(report);}catch(_){}
  };
  if(window.top===window){if(document.body)carried();else document.addEventListener('DOMContentLoaded',carried,{once:true});}
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
