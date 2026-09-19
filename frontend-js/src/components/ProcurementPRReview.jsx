import { useState } from 'react';
import Modal from './Modal';
import DocumentAttachments from './DocumentAttachments';
import client from '../api/client';

export default function ProcurementPRReview({ requisition, onClose, onSaved }) {
  const [lines,setLines]=useState(requisition.items.map(line=>({...line,approved_quantity:line.approved_quantity ?? line.requested_quantity,adjustment_reason:line.procurement_adjustment_reason || ''})));
  const [error,setError]=useState(''),[busy,setBusy]=useState(false);
  const change=(id,key,value)=>setLines(current=>current.map(line=>line.id===id?{...line,[key]:value}:line));
  async function save(approve) {
    setError('');setBusy(true);
    try {
      await client.put(`/procurement/prs/${requisition.id}/review`,{items:lines.map(line=>({id:line.id,approved_quantity:Number(line.approved_quantity),adjustment_reason:line.adjustment_reason}))});
      if(approve)await client.put(`/procurement/prs/${requisition.id}/status`,{status:'Approved'});
      onSaved();onClose();
    } catch(e) {setError(e?.response?.data?.error || 'Unable to complete Procurement review');}
    finally {setBusy(false);}
  }
  return <Modal title={`Procurement Review — ${requisition.pr_number}`} wide onClose={onClose}>
    <p className="mb-3 text-sm text-slate-600">Review specifications, requested quantities, dates and supporting documents. The Supply Chain Manager may approve their own PR. Other users require assigned authority and explicit delegation for self-approval.</p>
    <div className="mb-3 text-sm">Originating warehouse: {requisition.warehouse_name || requisition.trigger_warehouse_id || '?'} · Submitted: {requisition.warehouse_submitted_at || 'Not submitted'}</div>
    <div className="overflow-x-auto"><table className="table w-full"><thead><tr><th>Item / Specification</th><th>Required Date</th><th>Requested</th><th>Approved</th><th>Variance</th><th>Adjustment Reason</th></tr></thead><tbody>{lines.map(line=><tr key={line.id}>
      <td><strong>{line.item_code}</strong><div>{line.description}</div><div className="text-xs text-slate-500">{line.reason}</div>{Number(line.quantity)===0&&<div className="mt-1 rounded bg-amber-50 px-2 py-1 text-xs font-medium text-amber-800">Warehouse changed system recommendation to zero: {line.adjustment_reason || 'Reason not recorded'}{line.adjustment_note?` - ${line.adjustment_note}`:''}</div>}</td>
      <td>{line.required_date || '—'}</td><td>{line.requested_quantity} {line.transaction_uom || line.purchase_uom || line.uom}</td>
      <td><input data-field={"approved_quantity"} aria-label={`Approved quantity for ${line.item_code}`} className="input min-w-24" type="number" min="0" step="any" value={line.approved_quantity} onChange={e=>change(line.id,'approved_quantity',e.target.value)}/></td>
      <td>{Number(line.approved_quantity)-Number(line.requested_quantity)}</td>
      <td><input data-field={"adjustment_reason"} aria-label={`Adjustment reason for ${line.item_code}`} className="input min-w-48" value={line.adjustment_reason} onChange={e=>change(line.id,'adjustment_reason',e.target.value)} placeholder="Required when quantity changes"/></td>
    </tr>)}</tbody></table></div>
    <DocumentAttachments type="PR" documentId={requisition.id}/>
    {error&&<p data-error-message="true" role="alert" className="mt-3 text-sm text-rose-700">{error}</p>}
    <div className="mt-4 flex justify-end gap-2"><button className="btn-secondary" disabled={busy} onClick={()=>save(false)}>Save Review</button><button className="btn-primary" disabled={busy} onClick={()=>save(true)}>Save Review & Approve</button></div>
  </Modal>;
}
