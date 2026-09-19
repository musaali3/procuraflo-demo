import { CompanyContact, CompanyLogo, GeneratedByFooter } from './Branding';
import { ResponsibleSignature } from './EmployeeSignature';

const qty = (value) => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 3 });
const date = (value) => value ? new Date(String(value)).toLocaleString() : '—';

export default function WarehouseTransferDocument({ transfer, company, mode }) {
  const receipt = mode === 'receipt';
  const rows = transfer.items?.length ? transfer.items : [transfer];
  return <article id={receipt ? 'transfer-receipt-print-document' : 'transfer-dispatch-print-document'} className="controlled-print-document rounded-lg border border-slate-200 bg-white p-7 text-slate-900">
    <header className="flex justify-between gap-6 border-b-2 border-emerald-800 pb-5">
      <div className="flex min-w-0 gap-4"><CompanyLogo company={company} size="document" /><div><h1 className="text-xl font-bold text-emerald-950">{company?.name || company?.company_name || 'Company Name'}</h1><div className="mt-1 whitespace-pre-line text-xs leading-5 text-slate-600">{company?.address || 'Company address not configured'}</div><CompanyContact company={company} /></div></div>
      <div className="shrink-0 text-right"><div className="text-xl font-bold tracking-wide text-emerald-950">{receipt ? 'INTER-WAREHOUSE RECEIVING CONFIRMATION' : 'WAREHOUSE TRANSFER DISPATCH NOTE'}</div><div className="mt-2 text-sm font-bold">{receipt ? transfer.receipt_number : transfer.transfer_number}</div><div className="text-xs text-slate-600">Transfer: {transfer.transfer_number}</div><div className="text-xs text-slate-600">{receipt ? 'Received' : 'Dispatched'}: {date(receipt ? transfer.received_at : transfer.dispatched_at)}</div><div className="text-xs text-slate-600">Status: {transfer.status}</div></div>
    </header>
    <section className="my-5 grid grid-cols-2 gap-5 text-xs">
      <div className="rounded-md border border-slate-300 p-3"><div className="font-bold uppercase text-emerald-950">Dispatch From</div><div className="mt-2">Warehouse: <strong>{transfer.from_warehouse_name}</strong></div><div>Dispatched By: <strong>{transfer.dispatched_by_name || '—'}</strong></div></div>
      <div className="rounded-md border border-slate-300 p-3"><div className="font-bold uppercase text-emerald-950">Deliver To</div><div className="mt-2">Warehouse: <strong>{transfer.to_warehouse_name}</strong></div><div>Received By: <strong>{receipt ? transfer.received_by_name || '—' : 'Awaiting confirmation'}</strong></div></div>
    </section>
    <table className="w-full border-collapse text-xs"><thead><tr className="bg-emerald-900 text-white">{['Item','Source Bin','Destination Bin','Dispatched','Received Qty','Good','Damaged','Rejected','Shortage','Status'].map((heading) => <th key={heading} className="border border-emerald-800 p-2 text-left">{heading}</th>)}</tr></thead>
      <tbody>{rows.map((line, index) => <tr key={line.id || index}>
        <td className="border border-slate-300 p-2"><strong>{line.item_code}</strong><div>{line.description}</div></td>
        <td className="border border-slate-300 p-2">{line.from_location_code || transfer.from_location_code || '—'}</td>
        <td className="border border-slate-300 p-2">{line.to_location_code || transfer.to_location_code || '—'}</td>
        <td className="border border-slate-300 p-2 text-right">{qty(line.dispatched_quantity ?? line.quantity)}</td>
        <td className="border border-slate-300 p-2 text-right">{qty(Number(line.received_good_quantity || 0) + Number(line.damaged_quantity || 0) + Number(line.rejected_quantity || 0))}</td>
        <td className="border border-slate-300 p-2 text-right">{qty(line.received_good_quantity)}</td>
        <td className="border border-slate-300 p-2 text-right">{qty(line.damaged_quantity)}</td>
        <td className="border border-slate-300 p-2 text-right">{qty(line.rejected_quantity)}</td>
        <td className="border border-slate-300 p-2 text-right">{qty(line.shortage_quantity)}</td>
        <td className="border border-slate-300 p-2">{Number(line.outstanding_quantity || 0) > 0 ? 'In Transit' : Number(line.damaged_quantity || 0) + Number(line.rejected_quantity || 0) + Number(line.shortage_quantity || 0) > 0 ? 'Received With Variance' : 'Received'}</td>
      </tr>)}</tbody>
    </table>
    {receipt && transfer.receipt_items?.length > 0 && <section className="mt-5"><h2 className="mb-2 text-xs font-bold text-emerald-950">Receipt Details</h2><table className="w-full border-collapse text-xs"><thead><tr className="bg-slate-100">{['Receipt','Item','Destination Bin','Physical','Good','Damaged','Rejected','Shortage'].map((heading) => <th key={heading} className="border border-slate-300 p-2 text-left">{heading}</th>)}</tr></thead><tbody>{transfer.receipt_items.map((line) => <tr key={line.id}><td className="border border-slate-300 p-2">{line.receipt_number}</td><td className="border border-slate-300 p-2">{line.item_code}</td><td className="border border-slate-300 p-2">{line.location_code}</td><td className="border border-slate-300 p-2">{qty(line.physical_quantity)}</td><td className="border border-slate-300 p-2">{qty(line.good_quantity)}</td><td className="border border-slate-300 p-2">{qty(line.damaged_quantity)}</td><td className="border border-slate-300 p-2">{qty(line.rejected_quantity)}</td><td className="border border-slate-300 p-2">{qty(line.shortage_quantity)}</td></tr>)}</tbody></table></section>}
    <section className="mt-5 grid grid-cols-2 gap-5 text-xs"><div className="rounded border border-slate-300 p-3"><div className="font-bold text-emerald-900">Transport Details</div><div className="mt-2">Mode: <strong>{transfer.transport_mode || '—'}</strong></div><div>Vehicle: <strong>{transfer.vehicle_reference || '—'}</strong></div><div>Driver / Custodian: <strong>{transfer.driver_name || '—'}</strong></div><div>Tracking Reference: <strong>{transfer.tracking_reference || '—'}</strong></div></div><div className="rounded border border-slate-300 p-3"><div className="font-bold text-emerald-900">{receipt ? 'Receipt Confirmation' : 'Transfer Instructions'}</div><p className="mt-2 whitespace-pre-line">{receipt ? transfer.receiving_note || 'The receiving warehouse confirms the quantities recorded above.' : transfer.remarks || 'Destination receipt is pending.'}</p></div></section>
    <section className="mt-14 grid grid-cols-3 gap-8 text-center text-xs"><ResponsibleSignature label="Dispatched by" name={transfer.dispatched_by_name} date={transfer.dispatched_at} /><ResponsibleSignature label="Transport custodian" name={transfer.driver_name} /><ResponsibleSignature label={receipt ? 'Received and confirmed by' : 'Receiving warehouse confirmation'} name={receipt ? transfer.received_by_name : undefined} date={receipt ? transfer.received_at : undefined} /></section>
    <GeneratedByFooter note={receipt ? 'Inter-warehouse receiving confirmation; not a supplier GRN.' : 'Controlled evidence of stock dispatched between warehouses.'} />
  </article>;
}
