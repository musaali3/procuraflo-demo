import SearchSelect from './SearchSelect';
import EmployeePicker from './EmployeePicker';
import HorizontalScroll from './HorizontalScroll';
import { formatCurrency } from '../utils/currency';

export default function MaterialIssueForm({
  employees, departments, employeeId, setEmployeeId, setEmployees, purpose,
  setPurpose, lines, items, warehouses, warehouseBound, assignedWarehouseId,
  user, stock, setLines, updateLine, removeLine, addLine, valuation,
  valuationMessage, hasHighValueItem, hasReturnableItem, error, onCancel,
  submit, editingId,
}) {
  const employee = employees.find((entry) => Number(entry.id) === Number(employeeId));
  const departmentName = employee?.department_name || departments.find((entry) => Number(entry.id) === Number(employee?.department_id))?.name;

  return <div className="compact-form space-y-3">
    <section className="form-section-tinted">
      <h3 className="form-section-title">Issue Details</h3>
      <div className="grid gap-3 md:grid-cols-2">
        <div><EmployeePicker label="Employee" employees={employees} departments={departments}
          value={employeeId} onChange={(value) => setEmployeeId(value ? Number(value) : '')}
          onCreated={(created) => setEmployees((current) => [...current, created])} />
          {departmentName && <p className="mt-1 text-xs text-slate-500">Department: {departmentName}</p>}
        </div>
        <div><label className="text-sm font-medium text-slate-700">Purpose</label>
          <input data-field="purpose" className="input mt-1" value={purpose} onChange={(event) => setPurpose(event.target.value)} placeholder="e.g. Line 3 maintenance" />
        </div>
      </div>
    </section>

    <section className="form-section min-w-0">
      <h3 className="form-section-title">Items to Issue</h3>
      <HorizontalScroll role="region" aria-label="Material issue item lines">
        <div className="min-w-[70rem] space-y-2">
          <div className="grid grid-cols-[minmax(16rem,2.5fr)_minmax(10rem,1.5fr)_minmax(11rem,1.6fr)_minmax(8rem,1fr)_minmax(8rem,1fr)_minmax(5rem,.6fr)] gap-2 px-2 text-xs font-semibold text-slate-600">
            <span>Item</span><span>Warehouse</span><span>Storage Bin</span><span>Available Stock</span><span>Quantity</span><span>Remove</span>
          </div>
          {lines.map((line, i) => {
            const selectedItem = items.find((entry) => Number(entry.id) === Number(line.item_id));
            const balances = stock.filter((balance) => balance.item_id === line.item_id && (!line.warehouse_id || balance.warehouse_id === line.warehouse_id));
            const selectedBinStock = balances.filter((balance) => Number(balance.location_id) === Number(line.location_id)).reduce((sum, balance) => sum + Number(balance.quantity), 0);
            const warehouseStock = balances.reduce((sum, balance) => sum + Number(balance.quantity), 0);
            return <div className="form-line-card min-w-[70rem]" key={`${line.item_id || 'new'}-${i}`}>
              <div className="grid grid-cols-[minmax(16rem,2.5fr)_minmax(10rem,1.5fr)_minmax(11rem,1.6fr)_minmax(8rem,1fr)_minmax(8rem,1fr)_minmax(5rem,.6fr)] items-start gap-2">
                <div><SearchSelect data-field="item_id" label="Item" portalMenu options={items.map((entry) => ({value: entry.id, label: `${entry.item_code} - ${entry.description}`}))}
                  value={line.item_id || line.item_search || ''} placeholder="Search item" onChange={(value) => {
                    const selected = items.find((entry) => entry.id === Number(value));
                    setLines((current) => current.map((currentLine, index) => index === i ? {
                      ...currentLine, item_id: selected ? selected.id : '',
                      item_search: selected ? `${selected.item_code} - ${selected.description}` : '',
                      location_id: '',
                    } : currentLine));
                  }} />
                  {selectedItem && <p className="mt-1 text-xs text-slate-500">Unit: {selectedItem.issue_uom || selectedItem.uom || '—'}</p>}
                </div>
                <div>
                  {warehouseBound ? <div><label className="text-sm font-medium">Warehouse</label><div className="input mt-1 bg-slate-100 text-slate-700">{warehouses.find((entry) => Number(entry.id) === Number(assignedWarehouseId))?.name || user?.warehouse_name || 'Assigned warehouse'}</div></div>
                    : <div><label className="text-sm font-medium">Warehouse</label><select data-field="warehouse_id" className="input mt-1" value={line.warehouse_id} onChange={(event) => updateLine(i, 'warehouse_id', Number(event.target.value))}>
                      <option value="">Warehouse...</option>{warehouses.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}
                    </select></div>}
                </div>
                <div><label className="text-sm font-medium">Storage Bin</label><select data-field="location_id" className="input mt-1" value={line.location_id || ''} onChange={(event) => updateLine(i, 'location_id', Number(event.target.value))}>
                  <option value="">Select stocked Bin...</option>
                  {stock.filter((balance) => balance.item_id === line.item_id && balance.warehouse_id === line.warehouse_id && Number(balance.quantity) > 0 && balance.location_id).map((balance) =>
                    <option key={balance.id} value={balance.location_id}>{balance.location_code} — Available {Number(balance.quantity).toLocaleString()}</option>)}
                </select></div>
                <div className="pt-1 text-sm tabular-nums"><span className="block text-xs font-medium text-slate-600">Available Stock</span><strong className={line.item_id && line.location_id && selectedBinStock <= 0 ? 'text-rose-600' : 'text-emerald-700'}>{line.location_id ? selectedBinStock.toLocaleString() : warehouseStock.toLocaleString()}</strong>
                  <span className="block text-[11px] text-slate-500">{line.location_id ? 'in selected bin' : 'in warehouse'}</span>
                </div>
                <div><label className="text-sm font-medium">Quantity</label><input data-field="quantity" className="input mt-1" type="number" placeholder="Quantity" value={line.quantity} onChange={(event) => updateLine(i, 'quantity', Number(event.target.value))} /></div>
                <div className="pt-7">{lines.length > 1 && <button type="button" className="text-xs font-medium text-rose-600 hover:text-rose-800" onClick={() => removeLine(i)}>Remove</button>}</div>
              </div>
              {line.item_id && <details className="mt-2 text-xs text-slate-600"><summary className="cursor-pointer font-medium text-brand-700">Stock by location</summary>
                <div className="mt-1 space-y-1 rounded-lg bg-slate-50 p-2">{balances.length ? balances.map((balance) => <div key={balance.id} className="flex justify-between gap-2"><span>{balance.warehouse_name} · {balance.location_code ? `${balance.location_type || 'Location'} ${balance.location_code}` : 'Unassigned'}</span><span className="tabular-nums">{Number(balance.quantity).toLocaleString()}</span></div>) : <span className="text-rose-600">No available stock or assigned location found for this item{line.warehouse_id ? ' in the selected warehouse' : ''}.</span>}</div>
              </details>}
            </div>;
          })}
        </div>
      </HorizontalScroll>
      <button type="button" className="mt-2 text-sm font-medium text-brand-600" onClick={addLine}>+ Add Another Item</button>
    </section>

    {hasReturnableItem && <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">Returnable tools must be issued manually in Tool Management using their Tool Codes.</div>}
    <section className="form-section">
      <h3 className="form-section-title">Value / Approval Information</h3>
      {valuation ? <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-slate-700">
        <div>Estimated Issue Value <strong className="ml-1 tabular-nums">{formatCurrency(valuation.estimated_value)}</strong></div>
        <div>Approval Required: <strong>{valuation.approval_required ? 'Yes' : 'No'}</strong></div>
        {valuation.approval_required && <div>Approver: <strong>{valuation.approver_name || 'Assigned approver'}</strong></div>}
        {valuation.approval_required && (valuation.exceeds_limit || hasHighValueItem) && <div className="basis-full text-xs text-amber-800">{valuation.exceeds_limit ? `Above assigned limit of ${formatCurrency(valuation.approval_limit)}. ` : ''}Stock remains unchanged until approval.</div>}
      </div> : <p className="text-xs text-slate-600">{valuationMessage}</p>}
    </section>
    {error && <div data-error-message role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-600">{error}</div>}
    <div className="flex justify-end gap-2 pt-2"><button className="btn-secondary" onClick={onCancel}>Cancel</button><button className="btn-primary" disabled={!valuation} onClick={submit}>{editingId ? 'Save Changes' : 'Submit Material Issue'}</button></div>
  </div>;
}
