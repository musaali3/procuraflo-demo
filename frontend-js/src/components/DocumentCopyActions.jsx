import {useState} from 'react';
import {printControlledCopySet} from '../utils/printCopies';
import {downloadElementPdf} from '../utils/downloadPdf';

export default function DocumentCopyActions({documentId,filename,copies}) {
  const [busy,setBusy]=useState(false);
  async function output(copy,download){
    if(busy)return;
    setBusy(true);
    try{
      if(download)await downloadElementPdf(documentId,`${filename}-${copy.label.toLowerCase().replace(/[^a-z0-9]+/g,'-')}`,{copies:[copy],copyTitle:copy.title});
      else await printControlledCopySet(documentId,[copy],{labelCopy:true});
    }finally{setBusy(false);}
  }
  return <div className="flex flex-wrap justify-end gap-3 print:hidden">{copies.map(copy=><div key={copy.title} className="flex flex-wrap gap-2"><button type="button" className="btn-primary" disabled={busy} onClick={()=>output(copy,false)}>Print {copy.label}</button><button type="button" className="btn-secondary" disabled={busy} onClick={()=>output(copy,true)}>Download {copy.label} PDF</button></div>)}</div>;
}
