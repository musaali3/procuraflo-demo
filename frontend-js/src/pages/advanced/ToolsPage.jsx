import { useEffect, useMemo, useState } from 'react';
import client from '../../api/client';
import DataTable from '../../components/DataTable';
import Modal from '../../components/Modal';
import SearchSelect from '../../components/SearchSelect';
import useAutoRefresh from '../../hooks/useAutoRefresh';
import { useAuth } from '../../contexts/AuthContext';

const emptyForm = { item_id: '', warehouse_id: '', serial_number: '', make: '', model: '', calibration_due_date: '', calibration_required_yn: false };

export default function ToolsPage() {
  const { user } = useAuth();
  const [pendingTool, setPendingTool] = useState(null);
  const [returnTool, setReturnTool] = useState(null);
  const [returnCondition, setReturnCondition] = useState('Good');
  const [history, setHistory] = useState(null);
  const [lifecycleTool, setLifecycleTool] = useState(null);
  const [lifecycle, setLifecycle] = useState({ action: 'calibrate', reason: '', warehouse_id: '', location_id: '', calibration_due_date: '' });
  const [locations, setLocations] = useState([]);
  const [busy, setBusy] = useState(false);
  const [tools, setTools] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [items, setItems] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [checkoutTool, setCheckoutTool] = useState(null);
  const [checkoutEmployee, setCheckoutEmployee] = useState('');
  const [error, setError] = useState('');

  const load = () => client.get('/advanced/tools').then(({ data }) => setTools(data));
  useAutoRefresh(load);
  useEffect(() => {
    load();
    Promise.all([
      client.get('/masters/employee-directory'),
      client.get('/masters/operational-items'),
      client.get('/masters/warehouses'),
      client.get('/masters/locations'),
    ]).then(([employeeResult, itemResult, warehouseResult, locationResult]) => {
      setLocations(locationResult.data);
      setEmployees(employeeResult.data);
      setItems(itemResult.data.filter(item => item.consumable_returnable === 'Returnable' && item.active_yn !== 0));
      setWarehouses(warehouseResult.data.filter(warehouse => warehouse.active_yn !== 0));
    });
  }, []);

  const selectedItem = useMemo(() => items.find(item => Number(item.id) === Number(form.item_id)), [items, form.item_id]);
  async function createTool() {
    try {
      setError(''); setBusy(true);
      if (pendingTool) await client.put(`/advanced/tools/${pendingTool.id}/register`, form);
      else await client.post('/advanced/tools', { ...form, item_id: Number(form.item_id), warehouse_id: Number(form.warehouse_id) });
      setShowForm(false); setPendingTool(null); setForm(emptyForm); await load();
    } catch (requestError) { setError(requestError.response?.data?.error || 'Unable to register tool.'); } finally { setBusy(false); }
  }
  async function perform(action, done) {
    setBusy(true); setError('');
    try { await action(); done?.(); await load(); }
    catch (requestError) { setError(requestError.response?.data?.error || 'Unable to complete tool action.'); }
    finally { setBusy(false); }
  }
  const checkout = () => perform(() => client.put(`/advanced/tools/${checkoutTool.id}/checkout`, { employee_id: Number(checkoutEmployee), warehouse_id: checkoutTool.warehouse_id }), () => { setCheckoutTool(null); setCheckoutEmployee(''); });
  const checkin = () => perform(() => client.put(`/advanced/tools/${returnTool.id}/checkin`, { condition: returnCondition }), () => setReturnTool(null));
  const viewHistory = row => perform(async () => { const { data } = await client.get(`/advanced/tools/${row.id}/history`); setHistory({ ...data, tool_code: row.tool_code }); });
  const canIssue = row => !row.transfer_pending_yn && row.status === 'Available' && row.condition === 'Good' && !row.employee_id && (!row.source_grn_item_id || row.location_id) && (!row.calibration_required_yn || (row.calibration_due_date && row.calibration_due_date >= new Date().toLocaleDateString('en-CA')));
  const beginRegistration = row => { setPendingTool(row); setForm({ ...emptyForm, ...row, serial_number: row.serial_number || '', make: row.make || '', model: row.model || '', calibration_due_date: row.calibration_due_date || '' }); setError(''); setShowForm(true); };
  const employeeName = id => employees.find(employee => employee.id === id)?.name || '—';

  return <div>
    <div className="mb-4 flex items-center justify-between">
      <div><h1 className="text-xl font-semibold text-slate-900">Tool Management</h1><p className="text-sm text-slate-500">Accepted GRN tools await individual registration. Select a Tool Code to issue or return it manually.</p></div>
      <button className="btn-primary" onClick={() => { setPendingTool(null); setForm(emptyForm); setError(''); setShowForm(true); }}>+ Register Tool</button>
    </div>
    {error && <div role="alert" className="mb-3 rounded bg-rose-50 p-3 text-rose-700">{error}</div>}
    <div className="mb-3 text-sm">Pending Tool Registration: <strong>{tools.filter(row => row.status === 'Pending Tool Registration').length}</strong></div>
    <div className="card"><DataTable columns={[
      { key: 'tool_code', label: 'Tool Code' }, { key: 'item_description', label: 'Description' },
      { key: 'warehouse_name', label: 'Warehouse' }, { key: 'serial_number', label: 'Manufacturer Serial Number' },
      { key: 'employee_id', label: 'Assigned To', render: row => row.employee_id ? employeeName(row.employee_id) : '—' },
      { key: 'status', label: 'Status' }, { key: 'source_grn_item_id', label: 'GRN Line' }, { key: 'readiness', label: 'Issue Readiness', render: row => row.transfer_pending_yn ? 'In transit ? confirm warehouse receipt' : canIssue(row) ? 'Ready' : row.source_grn_item_id && !row.location_id ? 'Awaiting receipt inspection / put-away' : 'Check status / condition / calibration' }, { key: 'condition', label: 'Condition' }, { key: 'calibration_due_date', label: 'Calibration Due' },
    ]} rows={tools} actions={row => <div className="flex flex-wrap gap-2">
      {row.status === 'Pending Tool Registration' ? <button className="btn-primary" onClick={() => beginRegistration(row)}>Complete Registration</button>
        : row.employee_id && !row.return_date ? <button className="btn-secondary" onClick={() => { setReturnTool(row); setReturnCondition('Good'); setError(''); }}>Check In</button>
        : <button className="btn-primary" disabled={!canIssue(row)} onClick={() => { setCheckoutTool(row); setError(''); }}>Check Out</button>}
      <button className="btn-secondary" onClick={() => viewHistory(row)}>History</button>
      {['SupplyChainManager','WarehouseManager','WarehouseSupervisor'].includes(user?.role) && !row.employee_id && !row.transfer_pending_yn && !['Pending Tool Registration','Retired'].includes(row.status) && <button className="btn-secondary" onClick={() => { setLifecycleTool(row); setLifecycle({ action: ['Quarantined','Damaged','Under Repair'].includes(row.status) ? 'repair_complete' : 'calibrate', reason: '', warehouse_id: '', location_id: '', calibration_due_date: row.calibration_due_date || '' }); }}>Manage</button>}
    </div>} /></div>

    {showForm && <Modal title={pendingTool ? `Complete Registration: ${pendingTool.tool_code}` : "Register Tool"} onClose={() => setShowForm(false)}>
      <div className="compact-form">
        <SearchSelect disabled={!!pendingTool} data-field={"item_id"} label="Linked Returnable Item" options={items.map(item => ({ value: item.id, label: `${item.item_code} — ${item.description}` }))} value={form.item_id} onChange={value => setForm({ ...form, item_id: value })} placeholder="Search item code or description" />
        <div><label className="text-sm font-medium text-slate-700">Item Description</label><input className="input mt-1 bg-slate-50" readOnly value={selectedItem?.description || 'Select an item first'} /></div>
        <SearchSelect disabled={!!pendingTool} data-field={"warehouse_id"} label="Warehouse" options={warehouses.filter(warehouse => (user?.warehouse_ids || []).includes(warehouse.id)).map(warehouse => ({ value: warehouse.id, label: warehouse.name }))} value={form.warehouse_id} onChange={value => setForm({ ...form, warehouse_id: value })} placeholder="Search authorized warehouse" />
        <div><label className="text-sm font-medium text-slate-700">Tool Code</label><input className="input mt-1 bg-slate-50" readOnly value={pendingTool?.tool_code || 'Generated automatically after save'} /></div>
        <div className="grid grid-cols-2 gap-3"><div><label className="text-sm font-medium">Manufacturer Serial Number</label><input data-field={"serial_number"} className="input mt-1" value={form.serial_number} onChange={e => setForm({ ...form, serial_number: e.target.value })} /></div><div><label className="text-sm font-medium">Calibration Due</label><input data-field={"calibration_due_date"} className="input mt-1" type="date" value={form.calibration_due_date} onChange={e => setForm({ ...form, calibration_due_date: e.target.value })} /></div></div>
        <label className="flex items-center gap-2"><input type="checkbox" checked={!!form.calibration_required_yn} onChange={e => setForm({ ...form, calibration_required_yn: e.target.checked })} />Calibration required</label>
        <div className="grid grid-cols-2 gap-3"><div><label className="text-sm font-medium">Make</label><input data-field={"make"} className="input mt-1" value={form.make} onChange={e => setForm({ ...form, make: e.target.value })} /></div><div><label className="text-sm font-medium">Model</label><input data-field={"model"} className="input mt-1" value={form.model} onChange={e => setForm({ ...form, model: e.target.value })} /></div></div>
        {error && <div data-error-message="true" role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
        <div className="flex justify-end gap-2"><button className="btn-secondary" onClick={() => setShowForm(false)}>Cancel</button><button className="btn-primary" disabled={busy || !form.item_id || !form.warehouse_id || !form.serial_number.trim()} onClick={createTool}>Register Tool</button></div>
      </div>
    </Modal>}
    {checkoutTool && <Modal title={`Check Out ${checkoutTool.tool_code}`} onClose={() => setCheckoutTool(null)}><div className="space-y-3"><SearchSelect label="Tool Code" options={tools.filter(canIssue).map(row => ({ value: row.id, label: `${row.tool_code} ? ${row.item_description}` }))} value={checkoutTool.id} onChange={id => { setCheckoutTool(tools.find(row => row.id === Number(id)) || checkoutTool); setCheckoutEmployee(''); }} /><p><strong>{checkoutTool.tool_code}</strong> ? {checkoutTool.item_description}</p><p>Manufacturer Serial Number: {checkoutTool.serial_number || 'Not recorded'}<br />{checkoutTool.make} {checkoutTool.model}<br />Warehouse: {checkoutTool.warehouse_name}</p><SearchSelect data-field={"checkoutEmployee"} label="Employee" options={employees.map(employee => ({ value: employee.id, label: employee.name }))} value={checkoutEmployee} onChange={setCheckoutEmployee} placeholder="Search employee" /><div className="flex justify-end gap-2"><button className="btn-secondary" onClick={() => setCheckoutTool(null)}>Cancel</button><button className="btn-primary" disabled={busy || !checkoutEmployee} onClick={checkout}>Confirm Checkout</button></div></div></Modal>}
    {returnTool && <Modal title={`Check In ${returnTool.tool_code}`} onClose={() => setReturnTool(null)}><div className="space-y-3">
      <p>{returnTool.item_description} ? Manufacturer Serial Number: {returnTool.serial_number}</p>
      <label>Return condition<select className="input" value={returnCondition} onChange={e => setReturnCondition(e.target.value)}>{['Good','Damaged','Needs Repair'].map(value => <option key={value}>{value}</option>)}</select></label>
      <p className="text-sm">Damaged tools enter quarantine. Tools needing repair enter the repair queue.</p>
      <button className="btn-primary" disabled={busy} onClick={checkin}>Confirm Return</button>
    </div></Modal>}
    {history && <Modal title={`History: ${history.tool_code}`} onClose={() => setHistory(null)}><div className="space-y-3">
      <p>Source GRN: {history.grn?.grn_number || 'Legacy/manual registration'}</p>
      <DataTable columns={[{ key: 'employee_name', label: 'Employee' }, { key: 'checked_out_at', label: 'Issued' }, { key: 'checked_in_at', label: 'Returned' }, { key: 'return_condition', label: 'Return Condition' }]} rows={history.custody} />
      {history.events.map(event => <div key={event.id} className="border-b py-2 text-sm"><strong>{event.changed_at}</strong><pre className="whitespace-pre-wrap">{JSON.stringify(JSON.parse(event.new_values || '{}'), null, 2)}</pre></div>)}
    </div></Modal>}
    {lifecycleTool && <Modal title={`Manage ${lifecycleTool.tool_code}`} onClose={() => setLifecycleTool(null)}><div className="space-y-3">
      <label>Action<select className="input" value={lifecycle.action} onChange={e => setLifecycle({ ...lifecycle, action: e.target.value })}>{[['calibrate','Record Calibration'],['repair_complete','Complete Repair / Release Quarantine'],['transfer','Transfer to Another Warehouse'],['retire','Retire'],['lost','Record Lost']].map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {lifecycle.action === 'calibrate' && <label>Calibration Due<input className="input" type="date" value={lifecycle.calibration_due_date} onChange={e => setLifecycle({ ...lifecycle, calibration_due_date: e.target.value })} /></label>}
      {lifecycle.action === 'transfer' && <><SearchSelect label="Destination Warehouse" options={warehouses.filter(w => w.id !== lifecycleTool.warehouse_id).map(w => ({ value: w.id, label: w.name }))} value={lifecycle.warehouse_id} onChange={value => setLifecycle({ ...lifecycle, warehouse_id: value, location_id: '' })} /><SearchSelect label="Destination Location" options={locations.filter(l => Number(l.warehouse_id) === Number(lifecycle.warehouse_id)).map(l => ({ value: l.id, label: l.code }))} value={lifecycle.location_id} onChange={value => setLifecycle({ ...lifecycle, location_id: value })} /></>}
      {lifecycle.action === 'repair_complete' && !lifecycleTool.location_id && <SearchSelect label="Repaired Tool Storage Location" options={locations.filter(l => Number(l.warehouse_id) === Number(lifecycleTool.warehouse_id)).map(l => ({ value: l.id, label: l.code }))} value={lifecycle.location_id} onChange={value => setLifecycle({ ...lifecycle, location_id: value })} />}
      {lifecycle.action === 'transfer' && <p className="text-sm">Dispatch creates a warehouse transfer. The destination warehouse must confirm receipt and complete put-away before this tool can be issued.</p>}
      <label>Reason / Reference<input className="input" value={lifecycle.reason} onChange={e => setLifecycle({ ...lifecycle, reason: e.target.value })} /></label>
      <button className="btn-primary" disabled={busy || !lifecycle.reason.trim()} onClick={() => perform(() => client.put(`/advanced/tools/${lifecycleTool.id}/lifecycle`, { ...lifecycle, warehouse_id: Number(lifecycle.warehouse_id), location_id: Number(lifecycle.location_id) }), () => setLifecycleTool(null))}>Confirm Action</button>
    </div></Modal>}
  </div>;
}
