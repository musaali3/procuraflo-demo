import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from 'react';
import client from '../../api/client';
import DataTable from '../../components/DataTable';
import Modal from '../../components/Modal';
import SearchSelect from '../../components/SearchSelect';
import { isUsableStorageLocation } from '../../utils/locations';
import useAutoRefresh from '../../hooks/useAutoRefresh';

const uniqueOptions = (rows, valueKey, label) => Array.from(new Map(rows.map(row => [String(row[valueKey]), { value: row[valueKey], label: label(row) }])).values());

export default function ReturnsPage() {
    const [returns, setReturns] = useState([]), [outstanding, setOutstanding] = useState([]);
    const [warehouses, setWarehouses] = useState([]), [locations, setLocations] = useState([]);
    const [showForm, setShowForm] = useState(false), [employeeId, setEmployeeId] = useState(''), [itemId, setItemId] = useState('');
    const [destination, setDestination] = useState({}), [selected, setSelected] = useState({}), [error, setError] = useState('');
    const keyFor = row => `${row.employee_id}:${row.item_id}`;
    function load() { client.get('/warehouse/returns').then(res => setReturns(res.data)); client.get('/warehouse/returns/outstanding').then(res => setOutstanding(res.data)); }
    useAutoRefresh(load);
    useEffect(() => { load(); client.get('/masters/warehouses').then(res => setWarehouses(res.data)); client.get('/masters/locations').then(res => setLocations(res.data)); }, []);
    const employeeOptions = useMemo(() => uniqueOptions(outstanding.filter(row => !itemId || Number(row.item_id) === Number(itemId)), 'employee_id', row => `${row.employee_code} - ${row.employee_name}`), [outstanding, itemId]);
    const itemOptions = useMemo(() => uniqueOptions(outstanding.filter(row => !employeeId || Number(row.employee_id) === Number(employeeId)), 'item_id', row => `${row.item_code} - ${row.description}`), [outstanding, employeeId]);
    const custodyRows = useMemo(() => outstanding.filter(row => (!employeeId || Number(row.employee_id) === Number(employeeId)) && (!itemId || Number(row.item_id) === Number(itemId))), [outstanding, employeeId, itemId]);
    function openForm() { setEmployeeId(''); setItemId(''); setDestination({}); setSelected({}); setError(''); setShowForm(true); }
    function choose(row, checked) {
        const key=keyFor(row);
        if (!checked) { setSelected(current => { const next={...current}; delete next[key]; return next; }); return; }
        const activeEmployee=Object.values(selected)[0]?.employee_id;
        if (activeEmployee && Number(activeEmployee)!==Number(row.employee_id)) { setError('A return batch can contain items for one employee only.'); return; }
        setEmployeeId(Number(row.employee_id)); setError('');
        setSelected(current => ({...current,[key]:{...row,quantity:Number(row.outstanding_quantity),condition:'Good'}}));
    }
    function updateLine(key,field,value) { setSelected(current => ({...current,[key]:{...current[key],[field]:value}})); }
    async function submit() {
        setError(''); const lines=Object.values(selected);
        if (!employeeId) return setError('Search for and select an employee with outstanding returnable items.');
        if (!lines.length) return setError('Select at least one outstanding item to return.');
        if (!destination.warehouse_id || !destination.location_id) return setError('Select the return warehouse and destination Bin.');
        if (lines.some(line => !(Number(line.quantity)>0) || Number(line.quantity)>Number(line.outstanding_quantity) || !line.condition)) return setError('Each selected item needs a condition and a quantity within its outstanding balance.');
        try {
            await client.post('/warehouse/returns',{employee_id:Number(employeeId),warehouse_id:Number(destination.warehouse_id),location_id:Number(destination.location_id),items:lines.map(line => ({item_id:Number(line.item_id),quantity:Number(line.quantity),condition:line.condition}))});
            setShowForm(false); load();
        } catch (e) { setError(e?.response?.data?.error || 'Failed to record return'); }
    }
    return (_jsxs("div", { children: [_jsxs("div", { className: "flex items-center justify-between mb-4", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-xl font-semibold text-slate-900", children: "Returns" }), _jsx("p", { className: "text-sm text-slate-500", children: "Record one or more outstanding returnable items against the employee who holds them." })] }), _jsx("button", { className: "btn-primary", onClick: openForm, children: "+ New Return" })] }), _jsx("div", { className: "card", children: _jsx(DataTable, { columns: [
        { key: 'return_number', label: 'Return Number' }, { key: 'item_code', label: 'Item' }, { key: 'employee_name', label: 'Employee' }, { key: 'quantity', label: 'Quantity' }, { key: 'condition', label: 'Condition' }, { key: 'location_code', label: 'Stored Bin' }, { key: 'return_date', label: 'Date' },
    ], rows: returns }) }), showForm && (_jsx(Modal, { title: "Return Employee Custody Items", onClose: () => setShowForm(false), wide: true, children: _jsxs("div", { className: "space-y-4", children: [
        _jsxs("div", { className: "grid gap-3 md:grid-cols-2", children: [_jsx(SearchSelect, {"data-field": "employeeId",  label: "Employee", options: employeeOptions, value: employeeId, onChange: val => {setEmployeeId(val ? Number(val) : '');setSelected({});setError('');}, placeholder: "Search employee name or ID" }), _jsx(SearchSelect, {"data-field": "itemId",  label: "Returnable Item", options: itemOptions, value: itemId, onChange: val => {setItemId(val ? Number(val) : '');setSelected({});setError('');}, placeholder: "Search item code or description" })] }),
        !employeeId && !itemId ? _jsx("div", { className: "rounded-lg border border-sky-200 bg-sky-50 px-3 py-3 text-sm text-sky-900", children: "Search by employee to load all items in their custody, or search by item to see every employee with that item outstanding." }) : null,
        (employeeId || itemId) && !custodyRows.length ? _jsx("div", { className: "rounded-lg bg-emerald-50 px-3 py-3 text-sm text-emerald-800", children: "No outstanding returnable custody matches this selection." }) : null,
        custodyRows.length ? _jsx("div", { className: "overflow-x-auto rounded-lg border border-slate-200", children: _jsxs("table", { className: "w-full text-sm", children: [_jsx("thead", { className: "bg-slate-800 text-white", children: _jsxs("tr", { children: [_jsx("th", { className: "w-12 px-3 py-2" }),_jsx("th", { className: "px-3 py-2 text-left", children: "Employee" }),_jsx("th", { className: "px-3 py-2 text-left", children: "Item" }),_jsx("th", { className: "px-3 py-2 text-right", children: "Outstanding" }),_jsx("th", { className: "px-3 py-2 text-left", children: "Return Qty" }),_jsx("th", { className: "px-3 py-2 text-left", children: "Condition" })] }) }), _jsx("tbody", { children: custodyRows.map(row => { const key=keyFor(row),line=selected[key]; return _jsxs("tr", { className: "border-t border-slate-100", children: [
            _jsx("td", { className: "px-3 py-2 text-center", children: _jsx("input", { type: "checkbox", checked: !!line, onChange: e => choose(row,e.target.checked) }) }),
            _jsxs("td", { className: "px-3 py-2", children: [_jsx("strong", { children: row.employee_name }),_jsxs("div", { className: "text-xs text-slate-500", children: [row.employee_code,row.department_name ? ` - ${row.department_name}`:''] })] }),
            _jsxs("td", { className: "px-3 py-2", children: [_jsx("strong", { children: row.item_code }),_jsx("div", { className: "text-xs text-slate-500", children: row.description })] }),
            _jsxs("td", { className: "px-3 py-2 text-right font-semibold", children: [Number(row.outstanding_quantity).toLocaleString()," ",row.uom||''] }),
            _jsx("td", { className: "min-w-32 px-3 py-2", children: _jsx("input", { className: "input", type: "number", min: "0.000001", max: row.outstanding_quantity, step: "any", disabled: !line, value: line?.quantity ?? '', onChange: e => updateLine(key,'quantity',Number(e.target.value)) }) }),
            _jsx("td", { className: "min-w-40 px-3 py-2", children: _jsxs("select", { className: "input", disabled: !line, value: line?.condition ?? '', onChange: e => updateLine(key,'condition',e.target.value), children: [_jsx("option", { value: "Good", children: "Good" }),_jsx("option", { value: "Damaged", children: "Damaged" }),_jsx("option", { value: "Needs Repair", children: "Needs Repair" })] }) })
        ] }, key);}) })] }) }) : null,
        _jsxs("div", { className: "grid gap-3 border-t border-slate-200 pt-4 md:grid-cols-2", children: [_jsx(SearchSelect, {"data-field": "warehouse_id",  label: "Return to Warehouse", options: warehouses.map(w => ({value:w.id,label:w.name})), value: destination.warehouse_id ?? '', onChange: val => setDestination({warehouse_id:Number(val),location_id:null}), placeholder: "Search warehouse" }), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Destination Storage Bin" }),_jsxs("select", {"data-field": "location_id",  className: "input mt-1", value: destination.location_id||'', onChange: e => setDestination({...destination,location_id:Number(e.target.value)}), children: [_jsx("option", { value: "", children: "Select Bin..." }),locations.filter(location => isUsableStorageLocation(location)&&Number(location.warehouse_id)===Number(destination.warehouse_id)).map(location => _jsxs("option", { value: location.id, children: [location.code,location.label?` - ${location.label}`:''] },location.id))] })] })] }),
        error && _jsx("div", {"data-error-message": true, role: "alert",  className: "rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700", children: error }),
        _jsxs("div", { className: "flex items-center justify-between gap-3 pt-2", children: [_jsxs("span", { className: "text-sm text-slate-500", children: [Object.keys(selected).length," item",Object.keys(selected).length===1?'':'s'," selected"] }),_jsxs("div", { className: "flex gap-2", children: [_jsx("button", { className: "btn-secondary", onClick: () => setShowForm(false), children: "Cancel" }),_jsx("button", { className: "btn-primary", onClick: submit, children: "Record Return" })] })] })
    ] }) }))] }));
}
