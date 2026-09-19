import SearchSelect from './SearchSelect';
import EmployeePicker from './EmployeePicker';
import ReceivingIssueFields from './ReceivingIssueFields';
import HorizontalScroll from './HorizontalScroll';
import { currencyFieldLabel, formatCurrency } from '../utils/currency';
import { isUsableStorageLocation } from '../utils/locations';

export default function GRNReceiptForm({
  pos, poId, selectPurchaseOrder, locations, receivingWarehouseId,
  authorizedWarehouseIds, singleWarehouseId, user, setReceivingWarehouseId,
  setLines, receivingEmployees, departments, receivedForEmployeeId,
  setReceivedForEmployeeId, setEmployees, deliveryNote, setDeliveryNote,
  lines, items, updateLine, error, onCancel, submit,
}) {
  const po = pos.find((entry) => Number(entry.id) === Number(poId));
  const totalOutstanding = lines.reduce((sum, line) => sum + Number(line.outstanding_qty || 0), 0);
  const warehouseOptions = Array.from(new Map(locations.filter((location) =>
    authorizedWarehouseIds.includes(Number(location.warehouse_id))).map((location) => [
    Number(location.warehouse_id),
    { id: Number(location.warehouse_id), name: location.warehouse_name },
  ])).values());

  return <div className="compact-form space-y-3">
    <div className="grid gap-3 lg:grid-cols-2">
      <section className="form-section-tinted min-w-0">
        <h3 className="form-section-title">Receipt Details</h3>
        <SearchSelect data-field="poId" label="Purchase Order"
          options={pos.map((entry) => ({
            value: entry.id,
            label: `${entry.po_number} — ${[entry.delivery_warehouse_code, entry.delivery_warehouse_name].filter(Boolean).join(' — ')} — ${entry.supplier_name}${entry.committed_delivery_date ? ` — Due ${entry.committed_delivery_date}` : ''}`,
          }))}
          value={poId} onChange={selectPurchaseOrder} placeholder="Search PO" />
        {po && <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-700">
          <div className="col-span-2 min-w-0"><span className="text-slate-500">Supplier</span><div className="truncate font-medium" title={po.supplier_name}>{po.supplier_name || '—'}</div></div>
          <div className="col-span-2 min-w-0"><span className="text-slate-500">Delivery Warehouse</span><div className="font-medium">{[po.delivery_warehouse_code, po.delivery_warehouse_name].filter(Boolean).join(' — ') || '—'}</div></div>
          <div><span className="text-slate-500">PO Date</span><div className="font-medium">{po.po_date || po.created_at?.slice(0, 10) || '—'}</div></div>
          <div><span className="text-slate-500">Status</span><div className="font-medium">{po.status || '—'}</div></div>
          <div><span className="text-slate-500">Outstanding Items</span><div className="font-medium">{lines.length}</div></div>
          <div><span className="text-slate-500">Outstanding Quantity</span><div className="font-medium tabular-nums">{totalOutstanding.toLocaleString()}</div></div>
        </div>}
      </section>
      <section className="form-section-tinted min-w-0">
        <h3 className="form-section-title">Receiving Information</h3>
        <div className="grid gap-3">
          <div>
            <label className="text-sm font-medium text-slate-700">Receiving Warehouse</label>
            {authorizedWarehouseIds.length === 1
              ? <div className="input mt-1 bg-slate-100 text-slate-700">{locations.find((location) => Number(location.warehouse_id) === Number(singleWarehouseId))?.warehouse_name || user?.warehouse_name || 'Assigned warehouse'}</div>
              : <select data-field="receivingWarehouseId" className="input mt-1" value={receivingWarehouseId} onChange={(event) => {
                const id = Number(event.target.value) || '';
                setReceivingWarehouseId(id);
                selectPurchaseOrder('');
              }}>
                <option value="">Select authorized warehouse...</option>
                {warehouseOptions.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>)}
              </select>}
          </div>
          <EmployeePicker label="Receiving Employee" employees={receivingEmployees} departments={departments}
            value={receivedForEmployeeId} onChange={(value) => setReceivedForEmployeeId(value ? Number(value) : '')}
            onCreated={(employee) => setEmployees((current) => [...current, employee])} />
          <div><label className="text-sm font-medium text-slate-700">Delivery Note</label>
            <input data-field="deliveryNote" className="input mt-1" value={deliveryNote} onChange={(event) => setDeliveryNote(event.target.value)} />
          </div>
        </div>
      </section>
    </div>

    <section className="form-section min-w-0">
      <h3 className="form-section-title">Received Items</h3>
      {poId && lines.length > 0 && <HorizontalScroll role="region" aria-label="Goods receipt item lines">
        <div className="min-w-[72rem] space-y-2">
          <div className="grid grid-cols-[minmax(15rem,2.4fr)_repeat(3,minmax(6rem,1fr))_repeat(3,minmax(7rem,1.1fr))_minmax(8rem,1.2fr)] gap-2 px-3 text-xs font-semibold text-slate-600">
            <span>Item</span><span>Ordered Qty</span><span>Previously Received</span><span>Outstanding Qty</span>
            <span>Quantity Received</span><span>Accepted Qty</span><span>Rejected Qty</span><span>{currencyFieldLabel('Unit Cost')}</span>
          </div>
          {lines.map((line, i) => {
            const item = items.find((entry) => Number(entry.id) === Number(line.item_id));
            const inspectionRequired = Boolean(Number(item?.inspection_required_yn));
            const batchRequired = Boolean(Number(item?.batch_control_yn));
            const expiryRequired = Boolean(Number(item?.expiry_control_yn));
            const hasException = Number(line.rejected_qty || 0) > 0 || Number(line.damaged_qty || 0) > 0 || Number(line.short_qty || 0) > 0 || Boolean(line.receiving_issue_reason || line.receiving_notes);
            const quantityCell = (field, label, max) => <input data-field={field} aria-label={`${label} for ${line.item_code || `item ${i + 1}`}`}
              className="input w-full tabular-nums" type="number" min="0" max={max} value={line[field]}
              onChange={(event) => updateLine(i, field, Number(event.target.value))} />;
            return <div className="form-line-card min-w-[72rem] space-y-2" key={`${line.item_id || 'item'}-${i}`}>
              <div className="grid grid-cols-[minmax(15rem,2.4fr)_repeat(3,minmax(6rem,1fr))_repeat(3,minmax(7rem,1.1fr))_minmax(8rem,1.2fr)] items-center gap-2">
                <div className="min-w-0 text-sm text-slate-800"><strong>{line.item_code}</strong> — {line.description}<span className="block text-xs text-slate-500">{line.uom || 'Unit'}{inspectionRequired ? ' · Inspection required' : ''}</span></div>
                <div className="text-sm tabular-nums">{Number(line.ordered_qty || 0).toLocaleString()}</div>
                <div className="text-sm tabular-nums">{Number(line.previously_received_qty || 0).toLocaleString()}</div>
                <div className="text-sm font-medium tabular-nums">{Number(line.outstanding_qty || 0).toLocaleString()}</div>
                {quantityCell('quantity_received', 'Quantity received', line.outstanding_qty)}
                {quantityCell('accepted_qty', 'Accepted quantity')}
                {quantityCell('rejected_qty', 'Rejected quantity')}
                <div className="text-sm font-semibold tabular-nums" title="Locked from approved PO">{formatCurrency(line.unit_cost)}</div>
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-slate-100 pt-2 text-xs text-slate-600">
                {(batchRequired || expiryRequired || line.batch || line.expiry_date) && <span className="font-medium text-blue-700">Batch / expiry details required</span>}
                {line.recommended_location_code && <span>Recommended location: {line.recommended_location_code}</span>}
                <details className="group basis-full" key={`batch-${i}-${batchRequired || expiryRequired}`} defaultOpen={batchRequired || expiryRequired}>
                  <summary className="cursor-pointer font-medium text-brand-700">Batch &amp; Expiry</summary>
                  <div className="mt-2 flex flex-wrap gap-3 rounded-lg bg-slate-50 p-3">
                    <label className="min-w-44 flex-1">Batch Number<input data-field="batch" className="input mt-1" placeholder="Batch" value={line.batch} onChange={(event) => updateLine(i, 'batch', event.target.value)} /></label>
                    <label className="min-w-44 flex-1">Expiry Date<input data-field="expiry_date" className="input mt-1" type="date" value={line.expiry_date} onChange={(event) => updateLine(i, 'expiry_date', event.target.value)} /></label>
                  </div>
                </details>
                <details className="group basis-full" key={`exception-${i}-${hasException}`} defaultOpen={hasException}>
                  <summary className="cursor-pointer font-medium text-brand-700">{inspectionRequired ? 'Exceptions & Inspection' : 'Exceptions'}{hasException ? ' · Review' : ''}</summary>
                  <div className="mt-2 grid gap-3 rounded-lg bg-amber-50 p-3 text-sm">
                    {Number(line.rejected_qty || 0) > 0 && <label>Rejection Reason<input data-field="rejection_reason" className="input mt-1" value={line.rejection_reason} onChange={(event) => updateLine(i, 'rejection_reason', event.target.value)} /></label>}
                    <ReceivingIssueFields line={line} onChange={(key, value) => updateLine(i, key, value)} />
                  </div>
                </details>
                <details className="group basis-full">
                  <summary className="cursor-pointer font-medium text-brand-700">Value Details</summary>
                  <div className="mt-2 grid grid-cols-4 gap-3 rounded-lg bg-slate-50 p-3 text-xs">
                    <div>PO Tax<div className="font-semibold">{Number(line.tax || 0).toLocaleString(undefined, {maximumFractionDigits: 2})}%</div></div>
                    <div>Accepted Net Value<div className="font-semibold">{formatCurrency(Number(line.accepted_qty || 0) * Number(line.unit_cost || 0))}</div></div>
                    <div>Accepted Tax<div className="font-semibold">{formatCurrency(Number(line.accepted_qty || 0) * Number(line.unit_cost || 0) * Number(line.tax || 0) / 100)}</div></div>
                    <div>Accepted Gross Value<div className="font-semibold">{formatCurrency(Number(line.accepted_qty || 0) * Number(line.unit_cost || 0) * (1 + Number(line.tax || 0) / 100))}</div></div>
                  </div>
                </details>
                <div className="hidden">
                  <label>Put-away Storage Bin</label>
                  <select data-field="location_id" className="input mt-1" value={line.location_id || ''} onChange={(event) => updateLine(i, 'location_id', Number(event.target.value))}>
                    <option value="">Select the physical Bin...</option>
                    {locations.filter((location) => isUsableStorageLocation(location) && Number(location.warehouse_id) === Number(receivingWarehouseId)).map((location) => <option key={location.id} value={location.id}>{location.code}{location.label ? ` — ${location.label}` : ''}</option>)}
                  </select>
                </div>
              </div>
            </div>;
          })}
        </div>
      </HorizontalScroll>}
      {!poId && <div className="rounded-lg bg-amber-50 px-3 py-3 text-sm text-amber-800">Select a purchase order to load its items.</div>}
    </section>
    {error && <div data-error-message role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-600">{error}</div>}
    <div className="flex justify-end gap-2 pt-2">
      <button className="btn-secondary" onClick={onCancel}>Cancel</button>
      <button className="btn-primary" disabled={!receivingWarehouseId || !poId || !lines.length} onClick={submit}>Post GRN</button>
    </div>
  </div>;
}
