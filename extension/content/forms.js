(() => {
  let nextId=0, timer=null, typingTimer=null, lastFingerprint='', assessments=[];
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
    try{const result=await PG.request('context',{forms:{fields:items,context:context(dominantForm())}});if(fingerprint!==lastFingerprint)return;assessments=result.forms?.fields||[];PG.queryAll('.pg-badge').forEach(node=>node.remove());
      for(const assessment of assessments){if(!assessment.badge)continue;const element=PG.queryAll('[data-pg-field-id]').find(node=>node.dataset.pgFieldId===assessment.field.field_id);if(!element)continue;const badge=document.createElement('span');badge.className='pg-badge';badge.textContent='May be unnecessary';badge.title=assessment.necessity?.rationale||'';badge.setAttribute('role','note');element.insertAdjacentElement('afterend',badge);}
    }catch(_){lastFingerprint='';}}
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
    const action=await PG.awaitDecision(result.decision,selected=>{if(selected.action!=='review_fields')return;const flagged=assessments.filter(assessment=>assessment.badge).map(assessment=>assessment.field).filter(field=>items.some(item=>item.field_id===field.field_id));PG.highlight(flagged);PG.confirm(`${flagged.length} field${flagged.length===1?'':'s'} marked as not needed`);});
    return action.action==='continue';
  });
  // Open shadow roots attached later are inventoried by the regular mutation pass and a low-frequency check.
  window.addEventListener('message',event=>{if(event.source===window&&event.data?.pgBridge==='shadow_attached'){observeRoots();schedule();}});
  setInterval(()=>{observeRoots();},100);
})();
