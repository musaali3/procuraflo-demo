import { useEffect, useState } from 'react';
import client from '../api/client';
import DataTable from './DataTable';
import Modal from './Modal';
import SearchSelect from './SearchSelect';
import HorizontalScroll from './HorizontalScroll';
import ProfessionalWarehouseTransfer from './ProfessionalWarehouseTransfer';
import { useAuth } from '../contexts/AuthContext';
import { useBranding } from '../contexts/BrandingContext';
import { downloadElementPdf } from '../utils/downloadPdf';
import { printElement } from '../utils/printCopies';
import { isUsableStorageLocation } from '../utils/locations';
import useAutoRefresh from '../hooks/useAutoRefresh';

const emptyLine = () => ({ item_id: '', from_location_id: '', quantity: 1 });
const number = (value) => Number(value || 0);

export default function TransfersWorkflow() {
  const { user } = useAuth();
  const { company } = useBranding();
  const [transfers, setTransfers] = useState([]);
  const [items, setItems] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [locations, setLocations] = useState([]);
  const [stock, setStock] = useState([]);
  const [modes, setModes] = useState([]);
  const [modesText, setModesText] = useState('');
  const [settingsSaved, setSettingsSaved] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ from_warehouse_id: '', to_warehouse_id: '', transport_mode: '' });
  const [lines, setLines] = useState([emptyLine()]);
  const [error, setError] = useState('');
  const [receiving, setReceiving] = useState(null);
  const [receipt, setReceipt] = useState({});
  const [receiptLines, setReceiptLines] = useState([]);
  const [documentView, setDocumentView] = useState(null);

  function load() { client.get('/warehouse/transfers').then(({ data }) => setTransfers(data)); }
  useAutoRefresh(load);
  useEffect(() => {
    load();
    client.get('/masters/operational-items').then(({ data }) => setItems(data.filter((item) => item.active_yn !== 0)));
    client.get('/masters/warehouses').then(({ data }) => setWarehouses(data));
    client.get('/masters/locations').then(({ data }) => setLocations(data));
    client.get('/inventory/stock').then(({ data }) => setStock(data));
    client.get('/settings').then(({ data }) => {
      const configured = String(data.global_transport_modes || 'Company Vehicle, Courier, Third-Party Truck, Employee Hand Carry, Internal Forklift');
      setModesText(configured);
      setModes(configured.split(',').map((mode) => mode.trim()).filter(Boolean));
    });
  }, []);

  const updateLine = (index, changes) => setLines((current) => current.map((line, i) => i === index ? { ...line, ...changes } : line));
  function resetForm() { setShowForm(false); setForm({ from_warehouse_id: '', to_warehouse_id: '', transport_mode: '' }); setLines([emptyLine()]); setError(''); }
  function available(line) {
    return stock.filter((entry) => number(entry.item_id) === number(line.item_id) && number(entry.warehouse_id) === number(form.from_warehouse_id) && number(entry.location_id) === number(line.from_location_id))
      .reduce((sum, entry) => sum + number(entry.quantity), 0);
  }
  async function submit() {
    setError('');
    if (!form.from_warehouse_id || !form.to_warehouse_id) return setError('Select both warehouses.');
    if (number(form.from_warehouse_id) === number(form.to_warehouse_id)) return setError('Source and destination warehouses must be different.');
    if (!form.transport_mode) return setError('Select a transport mode.');
    if (!lines.length) return setError('Add at least one item.');
    const seen = new Set();
    for (const [index, line] of lines.entries()) {
      const label = `Item line ${index + 1}`;
      if (!line.item_id || !line.from_location_id || !(number(line.quantity) > 0)) return setError(`${label}: select an item, source Bin, and positive quantity.`);
      if (number(line.quantity) > available(line)) return setError(`${label}: quantity exceeds available stock in the selected source Bin.`);
      const key = `${line.item_id}:${line.from_location_id}`;
      if (seen.has(key)) return setError(`${label}: this item and source Bin are already on the transfer.`);
      seen.add(key);
    }
    try {
      await client.post('/warehouse/transfers', { ...form, items: lines.map(({ item_id, from_location_id, quantity }) => ({ item_id, from_location_id, quantity })) });
      resetForm(); load();
      client.get('/inventory/stock').then(({ data }) => setStock(data));
    } catch (failure) { setError(failure?.response?.data?.error || 'Failed to record transfer'); }
  }
  function openReceipt(transfer) {
    setReceiving(transfer); setError('');
    const sequence = new Set((transfer.receipt_items || []).map((item) => item.receipt_number)).size + 1;
    setReceipt({ to_location_id: '', receiving_reference: `TRR-${transfer.transfer_number}-${String(sequence).padStart(2, '0')}`, receiving_note: '' });
    setReceiptLines((transfer.items || []).filter((line) => number(line.outstanding_quantity) > 0).map((line) => ({
      transfer_item_id: line.id, to_location_id: '', physical_quantity: number(line.outstanding_quantity),
      good_quantity: number(line.outstanding_quantity), damaged_quantity: 0, rejected_quantity: 0, shortage_quantity: 0,
    })));
  }
  async function receive() {
    setError('');
    try {
      if (receiving.multi_item_yn) {
        for (const [index, line] of receiptLines.entries()) {
          if (!line.to_location_id) return setError(`Item line ${index + 1}: select a receiving Bin.`);
          if ([line.physical_quantity, line.good_quantity, line.damaged_quantity, line.rejected_quantity, line.shortage_quantity].some((value) => number(value) < 0)) return setError(`Item line ${index + 1}: quantities cannot be negative.`);
          if (Math.abs(number(line.good_quantity) + number(line.damaged_quantity) + number(line.rejected_quantity) - number(line.physical_quantity)) > 0.000001) return setError(`Item line ${index + 1}: physical quantity must equal good, damaged and rejected quantities.`);
        }
        await client.put(`/warehouse/transfers/${receiving.id}/receive`, { receiving_note: receipt.receiving_note, remarks: receipt.remarks, items: receiptLines });
      } else {
        if (!receipt.to_location_id) return setError('Select the physical Bin where the transferred stock was received.');
        await client.put(`/warehouse/transfers/${receiving.id}/receive`, receipt);
      }
      setReceiving(null); setReceipt({}); setReceiptLines([]); load();
    } catch (failure) { setError(failure?.response?.data?.error || 'Unable to receive transfer'); }
  }
  async function saveModes() {
    try {
      await client.put('/settings/global_transport_modes', { value: modesText });
      setModes(modesText.split(',').map((mode) => mode.trim()).filter(Boolean));
      setSettingsSaved(true); setTimeout(() => setSettingsSaved(false), 2000);
    } catch (failure) { setError(failure?.response?.data?.error || 'Unable to save transfer modes'); }
  }

  return <div>
    <div className="mb-4 flex items-center justify-between gap-3"><div><h1 className="text-xl font-semibold text-slate-900">Warehouse Transfers</h1><p className="text-sm text-slate-500">Move inventory between warehouses and confirm receipt at the destination.</p></div><button className="btn-primary" onClick={() => { setError(''); setShowForm(true); }}>+ New Transfer</button></div>
    {user && ['SupplyChainManager', 'WarehouseManager'].includes(user.role) && <details className="card mb-4 p-4"><summary className="cursor-pointer font-semibold text-blue-900">Transfer Configuration / Available Transfer Modes</summary><div className="mt-3 flex flex-wrap gap-2"><input data-field="transportModesText" className="input min-w-56 flex-1" value={modesText} onChange={(event) => setModesText(event.target.value)} /><button className="btn-secondary" onClick={saveModes}>Save Modes</button></div>{settingsSaved && <p className="mt-2 text-xs text-emerald-600">Transfer modes saved.</p>}</details>}
    {error && !showForm && !receiving && <div data-error-message role="alert" className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-600">{error}</div>}
    <div className="card"><DataTable columns={[
      { key: 'transfer_number', label: 'Transfer Number' },
      { key: 'item_count', label: 'Items' },
      { key: 'from_warehouse_name', label: 'From Warehouse' },
      { key: 'to_warehouse_name', label: 'To Warehouse' },
      { key: 'transfer_date', label: 'Dispatch Date' },
      { key: 'transport_mode', label: 'Transport Mode' },
      { key: 'status', label: 'Receipt Status' },
      { key: 'receipt_number', label: 'Transfer Receipt' },
    ]} rows={transfers} actions={(row) => <div className="flex flex-wrap gap-2">
      <button className="text-xs font-semibold text-blue-700" onClick={() => setDocumentView({ transfer: row, mode: 'dispatch' })}>Transit Note / Items</button>
      {['Received', 'Received With Variance', 'Closed'].includes(row.status) && <button className="text-xs font-semibold text-emerald-700" onClick={() => setDocumentView({ transfer: row, mode: 'receipt' })}>Receipt Confirmation</button>}
      {['In Transit', 'Partially Received'].includes(row.status) && user?.warehouse_ids?.map(Number).includes(number(row.to_warehouse_id)) && number(row.dispatched_by) !== number(user?.id) && <button className="text-xs font-semibold text-emerald-700" onClick={() => openReceipt(row)}>Create Receipt</button>}
    </div>} /></div>

    {showForm && <Modal title="New Transfer" wide onClose={resetForm}><div className="compact-form space-y-3">
      <section className="form-section-tinted"><h3 className="form-section-title">Transfer Route</h3><div className="grid gap-3 md:grid-cols-[1fr_auto_1fr] md:items-end">
        <SearchSelect data-field="from_warehouse_id" label="Transfer From · Source Warehouse" options={warehouses.map((warehouse) => ({ value: warehouse.id, label: warehouse.name }))} value={form.from_warehouse_id} onChange={(value) => { setForm((current) => ({ ...current, from_warehouse_id: number(value) || '', from_location_id: null })); setLines((current) => current.map((line) => ({ ...line, from_location_id: '' }))); }} placeholder="Search source warehouse" />
        <span className="hidden pb-2 text-xl text-slate-400 md:block" aria-hidden="true">→</span>
        <SearchSelect data-field="to_warehouse_id" label="Transfer To · Destination Warehouse" options={warehouses.map((warehouse) => ({ value: warehouse.id, label: warehouse.name }))} value={form.to_warehouse_id} onChange={(value) => setForm((current) => ({ ...current, to_warehouse_id: number(value) || '' }))} placeholder="Search destination warehouse" />
      </div></section>
      <section className="form-section min-w-0"><h3 className="form-section-title">Items to Transfer</h3>
        <HorizontalScroll role="region" aria-label="Transfer item lines"><div className="min-w-[56rem] space-y-2">
          <div className="grid grid-cols-[minmax(15rem,2fr)_minmax(12rem,1.5fr)_minmax(7rem,.8fr)_minmax(7rem,.8fr)_minmax(5rem,.5fr)] gap-2 px-2 text-xs font-semibold text-slate-600"><span>Item</span><span>Source Bin</span><span>Available</span><span>Qty</span><span>Remove</span></div>
          {lines.map((line, index) => <div className="form-line-card grid min-w-[56rem] grid-cols-[minmax(15rem,2fr)_minmax(12rem,1.5fr)_minmax(7rem,.8fr)_minmax(7rem,.8fr)_minmax(5rem,.5fr)] items-end gap-2" key={index}>
            <SearchSelect portalMenu data-field="item_id" label="Item" options={items.map((item) => ({ value: item.id, label: `${item.item_code} - ${item.description}` }))} value={line.item_id} onChange={(value) => updateLine(index, { item_id: number(value) || '', from_location_id: '' })} placeholder="Search item" />
            <label>Source Bin<select data-field="from_location_id" className="input mt-1" value={line.from_location_id} onChange={(event) => updateLine(index, { from_location_id: number(event.target.value) || '' })}><option value="">Select stocked Bin...</option>{stock.filter((entry) => number(entry.item_id) === number(line.item_id) && number(entry.warehouse_id) === number(form.from_warehouse_id) && entry.location_id && number(entry.quantity) > 0).map((entry) => <option key={entry.id} value={entry.location_id}>{entry.location_code} — Available {number(entry.quantity).toLocaleString()}</option>)}</select></label>
            <div className="pb-2 text-sm font-semibold tabular-nums text-emerald-700">{available(line).toLocaleString()}</div>
            <label>Quantity<input data-field="quantity" className="input mt-1" type="number" min="0" value={line.quantity} onChange={(event) => updateLine(index, { quantity: Number(event.target.value) })} /></label>
            <div className="pb-2">{lines.length > 1 && <button type="button" className="text-xs font-medium text-rose-600" onClick={() => setLines((current) => current.filter((_, i) => i !== index))}>Remove</button>}</div>
          </div>)}
        </div></HorizontalScroll><button type="button" className="mt-2 text-sm font-medium text-brand-600" onClick={() => setLines((current) => [...current, emptyLine()])}>+ Add Another Item</button>
      </section>
      <section className="form-section"><h3 className="form-section-title">Transport Details</h3><div className="grid gap-3 sm:grid-cols-2">
        <label>Transport Mode<select data-field="transport_mode" className="input mt-1" value={form.transport_mode} onChange={(event) => setForm((current) => ({ ...current, transport_mode: event.target.value }))}><option value="">Select...</option>{modes.map((mode) => <option key={mode}>{mode}</option>)}</select></label>
        <label>Vehicle Reference<input data-field="vehicle_reference" className="input mt-1" value={form.vehicle_reference || ''} onChange={(event) => setForm((current) => ({ ...current, vehicle_reference: event.target.value }))} /></label>
        <label>Driver / Custodian<input data-field="driver_name" className="input mt-1" value={form.driver_name || ''} onChange={(event) => setForm((current) => ({ ...current, driver_name: event.target.value }))} /></label>
        <label>Tracking Reference<input data-field="tracking_reference" className="input mt-1" value={form.tracking_reference || ''} onChange={(event) => setForm((current) => ({ ...current, tracking_reference: event.target.value }))} /></label>
        <label className="sm:col-span-2">Remarks<textarea data-field="remarks" className="input mt-1" value={form.remarks || ''} onChange={(event) => setForm((current) => ({ ...current, remarks: event.target.value }))} /></label>
      </div></section>
      {error && <div data-error-message role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-600">{error}</div>}
      <div className="flex justify-end gap-2"><button className="btn-secondary" onClick={resetForm}>Cancel</button><button className="btn-primary" onClick={submit}>Save Transfer</button></div>
    </div></Modal>}

    {receiving && <Modal title={`Receive ${receiving.transfer_number}`} wide={Boolean(receiving.multi_item_yn)} onClose={() => setReceiving(null)}><div className="compact-form space-y-3">
      <div className="rounded-lg bg-blue-50 px-3 py-2 text-sm text-blue-900"><strong>{receiving.transfer_number}</strong> · {receiving.from_warehouse_name} → {receiving.to_warehouse_name} · {receiving.item_count} item{receiving.item_count === 1 ? '' : 's'}</div>
      {receiving.multi_item_yn ? <HorizontalScroll role="region" aria-label="Transfer receipt item lines"><div className="min-w-[76rem] space-y-2">
        <div className="grid grid-cols-[minmax(14rem,2fr)_minmax(11rem,1.5fr)_repeat(5,minmax(7rem,1fr))] gap-2 px-2 text-xs font-semibold text-slate-600"><span>Item / Outstanding</span><span>Receiving / Staging Bin</span><span>Physical</span><span>Good</span><span>Damaged</span><span>Rejected</span><span>Shortage</span></div>
        {receiptLines.map((line, index) => { const source = receiving.items.find((entry) => entry.id === line.transfer_item_id); return <div key={line.transfer_item_id} className="form-line-card grid grid-cols-[minmax(14rem,2fr)_minmax(11rem,1.5fr)_repeat(5,minmax(7rem,1fr))] items-center gap-2">
          <div className="text-sm"><strong>{source?.item_code}</strong> — {source?.description}<span className="block text-xs text-slate-500">Outstanding: {number(source?.outstanding_quantity).toLocaleString()}</span></div>
          <select data-field="to_location_id" aria-label={`Receiving Bin for ${source?.item_code}`} className="input" value={line.to_location_id} onChange={(event) => setReceiptLines((current) => current.map((entry, i) => i === index ? { ...entry, to_location_id: number(event.target.value) || '' } : entry))}><option value="">Select Bin...</option>{locations.filter((location) => isUsableStorageLocation(location) && number(location.warehouse_id) === number(receiving.to_warehouse_id)).map((location) => <option key={location.id} value={location.id}>{location.code}</option>)}</select>
          {['physical_quantity','good_quantity','damaged_quantity','rejected_quantity','shortage_quantity'].map((field) => <input key={field} data-field={field} aria-label={`${field.replaceAll('_', ' ')} for ${source?.item_code}`} className="input" type="number" min="0" value={line[field]} onChange={(event) => setReceiptLines((current) => current.map((entry, i) => i === index ? { ...entry, [field]: Number(event.target.value) } : entry))} />)}
        </div>; })}</div></HorizontalScroll> : <SearchSelect data-field="to_location_id" label="Receiving / Staging Bin" options={locations.filter((location) => isUsableStorageLocation(location) && number(location.warehouse_id) === number(receiving.to_warehouse_id)).map((location) => ({ value: location.id, label: `${location.code}${location.label ? ` — ${location.label}` : ''}` }))} value={receipt.to_location_id} onChange={(value) => setReceipt((current) => ({ ...current, to_location_id: number(value) }))} placeholder="Search receiving Bin" />}
      <div className="grid gap-3 sm:grid-cols-2"><label>Transfer Receipt Number<input data-field="receiving_reference" className="input mt-1 bg-slate-100" value={receipt.receiving_reference || ''} readOnly /></label><label>Receiving Note<textarea data-field="receiving_note" className="input mt-1" value={receipt.receiving_note || ''} onChange={(event) => setReceipt((current) => ({ ...current, receiving_note: event.target.value }))} /></label></div>
      {error && <div data-error-message role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-600">{error}</div>}
      <div className="flex justify-end gap-2"><button className="btn-secondary" onClick={() => setReceiving(null)}>Cancel</button><button className="btn-primary" onClick={receive}>Post Transfer Receipt</button></div>
    </div></Modal>}

    {documentView && <Modal wide title={documentView.mode === 'dispatch' ? `Transfer Dispatch Note — ${documentView.transfer.transfer_number}` : `Receiving Confirmation — ${documentView.transfer.receipt_number}`} onClose={() => setDocumentView(null)}><div className="space-y-4"><div className="flex justify-end gap-2 print:hidden"><button className="btn-secondary" onClick={() => downloadElementPdf(documentView.mode === 'dispatch' ? 'transfer-dispatch-print-document' : 'transfer-receipt-print-document', documentView.mode === 'dispatch' ? `${documentView.transfer.transfer_number}-transit-note` : `${documentView.transfer.receipt_number}-receiving-confirmation`)}>Download PDF</button><button className="btn-primary" onClick={() => printElement(documentView.mode === 'dispatch' ? 'transfer-dispatch-print-document' : 'transfer-receipt-print-document')}>Print</button></div><ProfessionalWarehouseTransfer transfer={documentView.transfer} company={company} mode={documentView.mode} /></div></Modal>}
  </div>;
}
