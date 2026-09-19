const CONTROL = 'input:not([type="hidden"]),select,textarea,[role="combobox"]';
let lastAction, lastActionAt=0, panel, activeScope, entries = [], serial = 0, apiMessage;
const seen = new WeakMap();
const norm = value => String(value || '').replace(/([a-z])([A-Z])/g,'$1 $2').toLowerCase().replace(/[_-]/g,' ').replace(/\b(id|ids)\b/g,'').replace(/\bqty\b/g,'quantity').replace(/\s+/g,' ').trim();
const visible = el => el?.isConnected && !!el.getClientRects().length && !el.closest('[hidden],[aria-hidden="true"]');
export function errorContext() {
  const dialogs = [...document.querySelectorAll('[role="dialog"]')].filter(visible);
  const dialog = dialogs.at(-1);
  const action = Date.now()-lastActionAt<5000 && visible(lastAction) && (!dialog || dialog.contains(lastAction)) ? lastAction : null;
  return {scope:dialog || action?.closest('form') || document.querySelector('main') || document.getElementById('root'),action,path:location.pathname+location.search};
}
function labelFor(el) {
  const explicit = el.getAttribute('aria-label') || [...(el.labels || [])].map(x=>x.textContent).join(' ');
  if(explicit)return explicit.trim();
  const parentLabel = el.parentElement?.querySelector(':scope > label') || el.parentElement?.parentElement?.querySelector(':scope > label');
  if(parentLabel)return parentLabel.textContent.trim();
  const cell=el.closest('td');
  if(cell){const header=cell.closest('table')?.querySelectorAll('thead tr:last-child th')[cell.cellIndex];if(header)return header.textContent.replace(/[???]/g,'').trim();}
  return el.getAttribute('placeholder') || el.dataset.field || el.name || 'Field';
}
function clearMark(entry) {
  const el=entry.target;if(!el)return;
  el.classList.remove('error-field-highlight','error-action-highlight');
  const row=el.closest('tr');if(row&&!row.querySelector('.error-field-highlight'))row.classList.remove('error-row-highlight');
  if(entry.field){if(entry.previousInvalid===null)el.removeAttribute('aria-invalid');else el.setAttribute('aria-invalid',entry.previousInvalid);if(entry.previousDescription===null)el.removeAttribute('aria-describedby');else el.setAttribute('aria-describedby',entry.previousDescription);}
}
export function clearErrorGuidance() { entries.forEach(clearMark);entries=[];panel?.remove();panel=null;activeScope=null;document.documentElement.classList.remove('error-guidance-open'); }
function jump(el) {
  if (!visible(el)) return;
  const pageX = window.scrollX;
  const horizontalPositions = [];
  for (let parent = el.parentElement; parent; parent = parent.parentElement) {
    if (parent.scrollWidth > parent.clientWidth) horizontalPositions.push([parent, parent.scrollLeft]);
  }
  el.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
  // Bring the field into view vertically without sliding the form sideways.
  for (const [parent, left] of horizontalPositions) parent.scrollLeft = left;
  if (window.scrollX !== pageX) window.scrollTo({left:pageX,top:window.scrollY,behavior:'instant'});
  el.focus({preventScroll:true});
}
function render() {
  panel?.remove();if(!entries.length){document.documentElement.classList.remove('error-guidance-open');return;}
  // Keep the viewport at the left edge while the fixed warning is visible.
  document.documentElement.classList.add('error-guidance-open');
  if (window.scrollX) window.scrollTo({left:0,top:window.scrollY,behavior:'instant'});
  panel=document.createElement('aside');panel.className='error-guidance print:hidden';panel.dataset.outputExclude='true';panel.setAttribute('aria-label','Error guidance');panel.setAttribute('role','alert');
  const heading=document.createElement('strong');heading.textContent='Please review';panel.append(heading);
  const close=document.createElement('button');close.type='button';close.textContent='Dismiss';close.className='error-guidance-dismiss';close.onclick=clearErrorGuidance;panel.append(close);
  const list=document.createElement('ul');
  entries.forEach(entry=>{const li=document.createElement('li');li.id=entry.id;const message=document.createElement('div');message.textContent=entry.message;li.append(message);
    if(visible(entry.target)){const link=document.createElement('button');link.type='button';link.textContent=entry.field?'Go to '+entry.label:'Go to the affected action';link.onclick=()=>jump(entry.target);li.append(link);}
    else {const help=document.createElement('small');help.textContent=entry.help || 'Review the message above. No specific editable field was identified.';li.append(help);}
    list.append(li);});panel.append(list);document.body.append(panel);
  // Native validation may already have moved the dialog's outer scroll area.
  const dialogScroller = activeScope?.matches?.('[role="dialog"]') && activeScope.querySelector('.horizontal-scroll-content');
  if (dialogScroller) {
    dialogScroller.scrollLeft = 0;
    requestAnimationFrame(() => { if (panel?.isConnected && activeScope?.contains(dialogScroller)) dialogScroller.scrollLeft = 0; });
  }
}
function targetsFor(issue,scope) {
  let controls=[...scope.querySelectorAll(CONTROL)].filter(el=>visible(el)&&!el.disabled&&!el.readOnly);
  const namedRow=String(issue.message||'').match(/\b(?:row|line)\s+(\d+)\b/i);
  if(namedRow && !issue.field && !issue.loc?.length){const index=Number(namedRow[1])-1;controls=controls.filter(el=>{const row=el.closest('tr');return row&&[...row.parentElement.children].indexOf(row)===index;});}
  const fieldList=String(issue.message||'').match(/\b(?:missing|required|mandatory|invalid)\s+(?:fields?|values?)\s*:\s*(.+)/i);
  if(fieldList){const keys=fieldList[1].split(/,|\band\b/i).map(norm);const found=controls.filter(el=>keys.includes(norm(el.dataset.field||el.name))||keys.includes(norm(labelFor(el))));return found.filter(el=>found.filter(other=>norm(other.dataset.field||other.name)===norm(el.dataset.field||el.name)).length===1);}
  const loc=(issue.loc || issue.field?.replace(/\[(\d+)\]/g,'.$1').split('.') || []).filter(x=>!['body','query','path'].includes(x));
  const key=norm(loc.at(-1));
  let candidates=key?controls.filter(el=>norm(el.dataset.field||el.name)===key):[];
  const rowIndex=loc.find(x=>typeof x==='number'||/^\d+$/.test(x));
  if(rowIndex!==undefined){const index=Number(rowIndex);candidates=candidates.filter(el=>{const row=el.closest('tr');return row && [...row.parentElement.children].indexOf(row)===index;});}
  if(candidates.length===1)return candidates;
  if(key && !candidates.length)candidates=controls.filter(el=>norm(labelFor(el))===key);
  if(candidates.length===1)return candidates;
  if(key)return []; // Do not guess a repeated row when the server did not identify it.
  const message=norm(issue.message);
  const aliases={qty:'quantity', 'supplier name':'supplier', 'delivery warehouse':'warehouse', 'payment terms system default':'payment terms'};
  const hits=controls.map(el=>{let label=norm(labelFor(el)).replace(/\([^)]*\)/g,'').trim();label=aliases[label]||label;const field=norm(el.dataset.field||el.name);const tokens=[label,field].filter(x=>x.length>=3&&!['value','search','field','name','date'].includes(x));const score=Math.max(0,...tokens.filter(x=>(' '+message+' ').includes(' '+x+' ')).map(x=>x.length));return {el,score};}).filter(x=>x.score>0);
  const best=Math.max(0,...hits.map(x=>x.score));const matches=hits.filter(x=>x.score===best);
  return matches.length===1?[matches[0].el]:[];
}
export function showErrorGuidance({message,issues=[],context=errorContext(),target,focus=true,status}={}) {
  if(!message || context.path!==location.pathname+location.search || !context.scope?.isConnected)return;
  const scope=context.scope;
  if(activeScope!==scope)clearErrorGuidance();activeScope=scope;
  const problems=issues.length?issues:[{message}];
  for(const problem of problems){const text=problem.message||problem.msg||message;const targets=target?[target]:status>=500||status===401||status===403?[]:targetsFor({...problem,message:text},scope);
    const nodes=targets.length?targets:[context.action];
    for(const node of nodes){if(entries.some(e=>e.message===text&&e.target===node))continue;
      const field=targets.length>0;const id='error-guidance-'+(++serial);const entry={id,message:text,target:node,field,label:field?labelFor(node)+(node.closest('tbody > tr')?' (row '+([...node.closest('tr').parentElement.children].indexOf(node.closest('tr'))+1)+')':''):'',previousInvalid:node?.getAttribute('aria-invalid'),previousDescription:node?.getAttribute('aria-describedby'),help:status>=500?'The server could not complete this action. Try again; if it continues, contact your administrator.':status===403?'Your account cannot perform this action. Ask an authorized person to review it.':status===401?'Check your sign-in details or sign in again.':undefined};
      if(node){node.classList.add(field?'error-field-highlight':'error-action-highlight');if(field){node.closest('tr')?.classList.add('error-row-highlight');node.setAttribute('aria-invalid','true');node.setAttribute('aria-describedby',[entry.previousDescription,id].filter(Boolean).join(' '));}}
      entries.push(entry);
    }
  }
  render();if(focus){const first=entries.find(x=>x.field&&visible(x.target));if(first)jump(first.target);}
}
export function installErrorGuidance() {
  document.addEventListener('click',event=>{const action=event.target.closest('button,input[type="submit"]');if(action&&!action.closest('.error-guidance')){lastAction=action;lastActionAt=Date.now();if(/^(save|submit|confirm|import|create|approve|reject|upload|update|record|post|send|sign in|register|print|download|cancel|delete)\b/i.test(action.textContent.trim()))clearErrorGuidance();}},true);
  document.addEventListener('submit',event=>{lastAction=event.submitter||lastAction;lastActionAt=Date.now();clearErrorGuidance();},true);
  document.addEventListener('invalid',event=>{const el=event.target;showErrorGuidance({message:el.validationMessage||'Check this field.',target:el,focus:false});queueMicrotask(()=>jump(entries.find(x=>x.field)?.target));},true);
  const edit=event=>{const removed=entries.filter(x=>x.target===event.target);removed.forEach(clearMark);entries=entries.filter(x=>x.target!==event.target);render();};
  document.addEventListener('input',edit,true);document.addEventListener('change',edit,true);
  window.addEventListener('procuraflo:api-error',event=>{apiMessage=event.detail;setTimeout(()=>showErrorGuidance(event.detail),0);});
  let path=location.pathname+location.search;
  new MutationObserver(()=>{
    if(path!==location.pathname+location.search){path=location.pathname+location.search;clearErrorGuidance();}
    if(activeScope&&!visible(activeScope))clearErrorGuidance();
    const removed=entries.filter(entry=>entry.target&&!entry.target.isConnected);if(removed.length){removed.forEach(clearMark);entries=entries.filter(entry=>!removed.includes(entry));render();}
    document.querySelectorAll('[data-error-message]').forEach(el=>{const text=el.textContent.trim();if(!text){seen.set(el,'');return;}if(!visible(el)||seen.get(el)===text)return;seen.set(el,text);const context=errorContext();if(apiMessage?.message===text&&apiMessage.context?.scope===context.scope)return;if(!context.scope?.contains(el))return;showErrorGuidance({message:text,context,focus:false});});
  }).observe(document.body,{subtree:true,childList:true,characterData:true});
}
