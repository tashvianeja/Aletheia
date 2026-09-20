(() => {
  let nextId=0, timer=null, typingTimer=null, lastFingerprint='', assessments=[], noticeKey='', noticeId='';
  const ids=new WeakMap();
  // What the page calls this box. A form built out of divs — every survey builder, most
  // single-page apps — ties its question to its input with aria-labelledby or with
  // nothing but position, so a field asking for a password or a card number arrived
  // here anonymous and was judged as though it had asked for nothing at all.
  const textOf=node=>(node?.textContent||'').replace(/\s+/g,' ').trim();
  function byIds(element,attribute){
    const ids=(element.getAttribute(attribute)||'').split(/\s+/).filter(Boolean);
    if(!ids.length)return '';
    const root=element.getRootNode?.();
    return ids.map(id=>textOf((root&&root.getElementById?root.getElementById(id):null)||document.getElementById(id))).filter(Boolean).join(' ');
  }
  // The heading of the block this box sits in: a survey's question, a fieldset's legend.
  // A question block holds one answer. A container holding several different boxes is a
  // section, and its heading describes all of them at once, so lending it to each box in
  // turn would label every field of a checkout "Credit card details".
  function groupText(element){
    const container=element.closest?.('[role=listitem],fieldset,[role=group],[role=radiogroup],li');
    if(!container)return '';
    const controls=Array.from(container.querySelectorAll('input,select,textarea,[contenteditable=true]')).filter(node=>!['hidden','submit','button','reset','image'].includes(node.type));
    if(controls.length>1&&!controls.every(node=>['radio','checkbox'].includes(node.type)))return '';
    const labelled=byIds(container,'aria-labelledby')||container.getAttribute?.('aria-label')||'';
    const heading=container.querySelector?.('[role=heading],legend,h1,h2,h3,h4,h5,h6');
    return (labelled||textOf(heading)).slice(0,300);
  }
  // The classic "caption above the box" with no markup joining the two.
  function precedingText(element){
    for(let node=element.previousElementSibling;node;node=node.previousElementSibling){
      if(node.querySelector?.('input,select,textarea,[contenteditable=true]'))break;
      const text=textOf(node);
      if(text&&text.length<=120)return text;
    }
    return '';
  }
  function describe(element){
    const own=element.labels?Array.from(element.labels).map(label=>label.textContent).join(' '):'';
    // A radio or a checkbox is labelled with its option, not with the question, so the
    // question has to come from the group for "Male"/"Female" to be read as gender.
    const grouped=['checkbox','radio'].includes(element.type)?groupText(element):'';
    // A placeholder was written for this box; a caption above it is only inferred from
    // where it sits, so it is the last thing tried before the box's own title.
    const candidates=[own,byIds(element,'aria-labelledby'),element.getAttribute('aria-label'),grouped,groupText(element),element.getAttribute('placeholder'),precedingText(element),element.getAttribute('title')];
    const first=candidates.find(value=>(value||'').trim());
    return [grouped&&grouped!==first?grouped:'',first||''].filter(Boolean).join(' ').replace(/\s+/g,' ').trim().slice(0,300);
  }
  function fields(form=null){return PG.queryAll('input,select,textarea,[contenteditable=true]').filter(element=>PG.visible(element)&&(!form||element.form===form||form.contains(element))&&!['file','hidden','submit','button','reset','image'].includes(element.type)).map(element=>{
    if(!ids.has(element))ids.set(element,`pg-field-${++nextId}`);const field_id=ids.get(element);element.dataset.pgFieldId=field_id;
    const label=describe(element);
    return {field_id,label,name:(element.name||element.id||'').slice(0,100),input_type:element.type||element.tagName.toLowerCase(),autocomplete:element.autocomplete||'',required:!!element.required||element.getAttribute('aria-required')==='true',asserted_required:/\*/.test(label)||element.dataset.required==='true',max_length:Math.max(0,Math.min(4096,element.maxLength>0?element.maxLength:0)),filled:element.isContentEditable?!!element.textContent?.trim():['checkbox','radio'].includes(element.type)?element.checked:!!element.value};
  });}

  const clean=text=>(text||'').replace(/\s+/g,' ').trim();
  function submitText(form){
    const scope=form||document;
    const buttons=Array.from(scope.querySelectorAll('button,input[type=submit],input[type=image],[role=button]')).filter(node=>PG.visible(node)&&node.type!=='reset'&&!node.closest('.pg-panel,.pg-stack'));
    const preferred=buttons.filter(node=>node.type==='submit'||node.tagName==='BUTTON');
    return clean((preferred[0]||buttons[0])?.textContent||(preferred[0]||buttons[0])?.getAttribute?.('value')||'').slice(0,120);
  }
  function heading(form){
    // The nearest preceding heading is what the page calls this form.
    let node=form;
    while(node&&node!==document.body){
      for(let sibling=node.previousElementSibling;sibling;sibling=sibling.previousElementSibling){
        const found=sibling.matches?.('h1,h2,h3,h4,legend')?sibling:sibling.querySelector?.('h1,h2,h3,h4,legend');
        if(found&&PG.visible(found))return clean(found.textContent).slice(0,200);
      }
      node=node.parentElement;
    }
    return clean(document.querySelector('h1')?.textContent||'').slice(0,200);
  }
  function context(form){
    const host=form||document.body||document.documentElement;
    const legend=clean(host.querySelector?.('legend')?.textContent||'').slice(0,200);
    const aria=clean(form?.getAttribute?.('aria-label')||'').slice(0,200);
    // Short surrounding prose: enough for "we will email you the PDF", not the whole page.
    const nearby=clean(Array.from(host.querySelectorAll?.('p,label,span,small')||[]).filter(node=>PG.visible(node)&&!node.closest('.pg-panel,.pg-stack')).slice(0,12).map(node=>node.textContent).join(' ')).slice(0,400);
    let action='';
    try{action=new URL(form?.getAttribute?.('action')||location.href,location.href).pathname.slice(0,200);}catch(_){action=location.pathname.slice(0,200);}
    return {submit_text:submitText(form),heading:heading(form)||aria,legend:legend||aria,action_path:action,nearby_text:nearby,page_title:clean(document.title).slice(0,200)};
  }
  // The form that owns most of the page's visible fields is the one being filled in.
  function dominantForm(){
    const counts=new Map();
    for(const element of PG.queryAll('input,select,textarea')){if(!PG.visible(element)||!element.form)continue;counts.set(element.form,(counts.get(element.form)||0)+1);}
    let best=null,most=0;
    for(const [form,count] of counts)if(count>most){best=form;most=count;}
    return best;
  }
  // Whether a box has something in it is part of the inventory: an optional box is
  // only worth naming once the person has actually put something in it, and a
  // fingerprint that pretended every box was empty meant that moment never arrived.
  // What is compared is the boolean, never the value, which is never sent anywhere.
  async function inventory(){const items=fields();const fingerprint=JSON.stringify(items);if(fingerprint===lastFingerprint)return;lastFingerprint=fingerprint;
    try{const result=await PG.request('context',{forms:{fields:items,context:context(dominantForm())}});if(fingerprint!==lastFingerprint)return;assessments=result.forms?.fields||[];
      // A box already dealt with keeps its "Redacted" mark: this pass runs again on
      // the very next keystroke, and wiping it would take the receipt off the page.
      PG.queryAll('.pg-badge').forEach(node=>{if(node.dataset.pgRedacted!=='1')node.remove();});
      for(const assessment of assessments){if(!assessment.badge)continue;const element=PG.queryAll('[data-pg-field-id]').find(node=>node.dataset.pgFieldId===assessment.field.field_id);if(!element||element.dataset.pgRedacted==='1')continue;const badge=document.createElement('span');badge.className='pg-badge';badge.textContent='May be unnecessary';badge.title=assessment.necessity?.rationale||'';badge.setAttribute('role','note');element.insertAdjacentElement('afterend',badge);}
      await notice(items);
    }catch(_){lastFingerprint='';}}
  // One card for the whole form, not one per field. A badge beside a box says which
  // box; it does not say that anything can be done about it, and a person watching a
  // password box collect a badge has no way to find out that it can. This is that
  // offer, made once: the service keys the card on what this form asks for, so every
  // later pass sharpens the card already up rather than raising a second one.
  //
  // What is sent is the same inventory the badges came from — which boxes, what they
  // are called, whether they hold anything. Never what they hold.
  async function notice(items){
    const flagged=assessments.filter(assessment=>assessment.badge).map(assessment=>assessment.field);
    // Re-asked when the flagged boxes change, and when one of them first gets
    // something typed into it: that is the moment there are contents to redact.
    const key=flagged.map(field=>field.field_id+(field.filled?'\u0001':'')).join('\u001f');
    if(key===noticeKey)return;
    noticeKey=key;
    if(!flagged.length)return;
    try{
      const result=await PG.safeRace(PG.request('event',{event:{event_type:'form_observed',fields:items,context:context(dominantForm())}}),4000,null);
      // Analysis that ran out of time is not an answer of "nothing to say": the next
      // pass over this form asks again rather than staying quiet about it for good.
      if(!result?.decision){noticeKey='';return;}
      noticeId=result.decision.event_id;
      PG.showDecision(result.decision,selected=>{
        if(selected.action==='redact_fields'){
          // The service names the fields: the ones the card warned about that have
          // something in them. Each is handed bullets in place of its contents.
          const redacted=PG.redactFields(selected.fields||[]);
          if(selected.report&&redacted)PG.showResult(selected.report);
        }
        if(selected.action==='review_fields'){
          PG.highlight(flagged);
          PG.showResult(selected.report||{headline:`${flagged.length} field${flagged.length===1?'':'s'} marked as not needed`,body:'They are outlined on the page. Nothing has been sent yet.'});
        }
      });
    }catch(_){noticeKey='';}
  }
  const schedule=()=>{clearTimeout(timer);timer=setTimeout(inventory,10);};
  // Typing moves no element and changes no attribute, so nothing else here notices it.
  // Waiting for a pause keeps this to one pass per field rather than one per keystroke.
  const scheduleTyped=()=>{clearTimeout(typingTimer);typingTimer=setTimeout(inventory,500);};
  for(const name of ['input','change'])document.addEventListener(name,scheduleTyped,true);
  const observedRoots=new WeakSet();
  function observeRoots(){for(const root of PG.roots()){if(observedRoots.has(root))continue;observedRoots.add(root);new MutationObserver(records=>{if(records.some(record=>!record.target.closest?.('.pg-panel,.pg-badge'))){observeRoots();schedule();}}).observe(root===document?document.documentElement:root,{subtree:true,childList:true,attributes:true,attributeFilter:['required','aria-required','name','type','style','class']});}}
  function observe(){observeRoots();schedule();}
  if(document.documentElement)observe();else document.addEventListener('DOMContentLoaded',observe,{once:true});
  PG.collectors.push(async()=>({forms:{fields:fields(),context:context(dominantForm())}}));
  PG.submitChecks.push(async form=>{
    const items=fields(form);if(!items.some(field=>field.filled))return true;
    const result=await PG.safeRace(PG.request('event',{event:{event_type:'form_submit',fields:items,context:context(form)}}),4000,null);if(!result)return true;
    // The card about this form sitting on the page is overtaken by the card about it
    // being sent: the same fields, the same remedies, and now something actually held
    // up. It goes before the larger one arrives rather than stacking beneath it.
    if(noticeId){PG.putDown(noticeId);noticeId='';}
    const action=await PG.awaitDecision(result.decision,selected=>{
      if(selected.action==='review_fields'){
        const flagged=assessments.filter(assessment=>assessment.badge).map(assessment=>assessment.field).filter(field=>items.some(item=>item.field_id===field.field_id));
        PG.highlight(flagged);
        PG.showResult(selected.report||{headline:`${flagged.length} field${flagged.length===1?'':'s'} marked as not needed`,body:'They are outlined on the page. Nothing has been sent yet.'});
      }
      if(selected.action==='clear_fields'){
        // The service names the fields: the ones the card warned about that are
        // filled in and not required. They are blanked here, before the submission
        // below goes ahead with what is left.
        PG.clearFields(selected.fields||[]);
        // The submission below may be a whole new page; the receipt goes with it.
        if(selected.report)PG.showResult(selected.report,{carry:true});
      }
    });
    return action.action==='continue'||action.action==='clear_fields';
  });
  // Open shadow roots attached later are inventoried by the regular mutation pass and a low-frequency check.
  window.addEventListener('message',event=>{if(event.source===window&&event.data?.pgBridge==='shadow_attached'){observeRoots();schedule();}});
  setInterval(()=>{observeRoots();},100);
})();
