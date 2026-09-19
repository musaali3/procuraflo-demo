import { showErrorGuidance } from './errorGuidance';
export const A4 = Object.freeze({ width: 210, height: 297, margin: 10 });

export function outputSource(id) {
  const source=document.getElementById(id);
  if(!source)throw new Error('Open the document before printing or downloading it.');
  // Business authorization belongs to the API and explicit document state, not text matching.
  if(source.dataset.outputAuthorized==='false')throw new Error('Complete this document’s required authorization before exporting it.');
  return source;
}

export function outputError(error) {
  const message=error?.message || 'Unable to prepare the document. Please reopen it and try again.';
  showErrorGuidance({message});
  return {success:false,error:message};
}

export async function waitForImages(root) {
  await document.fonts?.ready;
  await Promise.all([...root.querySelectorAll('img')].map(img=>Promise.race([
    img.decode().catch(()=>undefined),new Promise(resolve=>setTimeout(resolve,4000)),
  ])));
}

export function documentClone(source) {
  const clone=source.cloneNode(true);
  clone.removeAttribute('id');
  clone.querySelectorAll('[id]').forEach(node=>node.removeAttribute('id'));
  // Calendar day buttons contain the roster, not just an action control.
  // Preserve that content as ordinary blocks before removing export controls.
  if (source.id === 'work-calendar-print') {
    clone.classList.add('work-calendar-document', 'calendar-export-mode');
    clone.querySelectorAll('button.calendar-date-card').forEach(button => {
      const card=document.createElement('div');
      card.className=button.className;
      card.append(...button.childNodes);
      button.replaceWith(card);
    });
  }
  clone.querySelectorAll('button,input,select,.print\\:hidden,[data-output-exclude],.print-page-number,.page-counter').forEach(node=>node.remove());
  clone.querySelectorAll('.error-field-highlight,.error-action-highlight,.error-row-highlight').forEach(node=>node.classList.remove('error-field-highlight','error-action-highlight','error-row-highlight'));
  clone.classList.add('controlled-document-clone');
  clone.style.cssText+=';width:100%;max-width:none;min-width:0;height:auto;max-height:none;overflow:visible;margin:0;box-shadow:none;';
  clone.querySelectorAll('table').forEach(table=>{table.style.cssText+=';width:100%;min-width:0;max-width:100%;table-layout:fixed;';});
  clone.querySelectorAll('th,td').forEach(cell=>{cell.style.cssText+=';overflow-wrap:anywhere;white-space:normal;line-height:1.5;padding:8px;vertical-align:top;';});
  clone.querySelectorAll('.truncate').forEach(node=>{node.style.cssText+=';overflow:visible;white-space:normal;text-overflow:clip;';});
  clone.querySelectorAll('.overflow-x-auto,.overflow-y-auto,.overflow-hidden').forEach(node=>{node.style.overflow='visible';node.style.maxHeight='none';});
  return clone;
}
