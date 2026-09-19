import { showErrorGuidance } from '../../utils/errorGuidance';
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import client from '../../api/client';
import DataTable from '../../components/DataTable';
import Modal from '../../components/Modal';
import StatusBadge from '../../components/StatusBadge';
import { useAuth } from '../../contexts/AuthContext';
import { useSearchParams } from 'react-router-dom';
import SearchSelect from '../../components/SearchSelect';
import { isUsableStorageLocation } from '../../utils/locations';
import useAutoRefresh from '../../hooks/useAutoRefresh';
function LegacySearchSelect({ label, options, value, onChange, placeholder, }) {
    const [query, setQuery] = useState('');
    const [open, setOpen] = useState(false);
    useEffect(() => {
        const selected = options.find((opt) => String(opt.value) === String(value))?.label || String(value || '');
        setQuery(selected);
    }, [value, options]);
    const filtered = options.filter((opt) => `${opt.label}`.toLowerCase().includes(query.toLowerCase()));
    return (_jsxs("div", { className: "relative", children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: label }), _jsx("input", {"data-field": "query",  className: "input mt-1 w-full", placeholder: placeholder, value: query, onChange: (e) => {
                    setQuery(e.target.value);
                    setOpen(true);
                }, onFocus: () => setOpen(true), onBlur: () => setTimeout(() => setOpen(false), 120) }), open && filtered.length > 0 && (_jsx("div", { className: "absolute z-20 mt-1 w-full rounded-lg border border-slate-200 bg-white shadow-lg", children: filtered.map((opt) => (_jsx("button", { type: "button", className: "block w-full px-3 py-2 text-left text-sm hover:bg-slate-50", onMouseDown: () => {
                        setQuery(opt.label);
                        onChange(opt.value);
                        setOpen(false);
                    }, children: opt.label }, opt.value))) }))] }));
}
export default function AdjustmentsPage() {
    const [searchParams, setSearchParams] = useSearchParams();
    const { user } = useAuth();
    const [adjustments, setAdjustments] = useState([]);
    const [items, setItems] = useState([]);
    const [warehouses, setWarehouses] = useState([]);
    const [locations, setLocations] = useState([]);
    const [showForm, setShowForm] = useState(false);
    const [form, setForm] = useState({});
    const [error, setError] = useState('');
    const [reviewing, setReviewing] = useState(null);
    function load() {
        client.get('/warehouse/adjustments').then((res) => setAdjustments(res.data));
    }
    useAutoRefresh(load);
    useEffect(() => {
        load();
        client.get('/masters/operational-items').then((res) => setItems(res.data));
        client.get('/masters/warehouses').then((res) => setWarehouses(res.data));
        client.get('/masters/locations').then((res) => setLocations(res.data));
    }, []);
    useEffect(() => {
        const openId = Number(searchParams.get('open'));
        const target = openId ? adjustments.find((row) => row.id === openId) : null;
        if (!target)
            return;
        setSearchParams({}, { replace: true });
        setReviewing(target);
    }, [adjustments, searchParams, setSearchParams]);
    async function submit() {
        setError('');
        if (!form.item_id || !form.warehouse_id || !form.location_id || !Number.isFinite(form.quantity_change) || form.quantity_change === 0 || !String(form.reason || '').trim())
            return setError('Select an item, warehouse and physical Bin, enter a non-zero quantity change, and provide a reason.');
        try {
            await client.post('/warehouse/adjustments', form);
            setShowForm(false);
            setForm({});
            load();
        }
        catch (e) {
            setError(e?.response?.data?.error || 'Failed to submit adjustment');
        }
    }
    async function approve(id) {
        try {
            await client.put(`/warehouse/adjustments/${id}/approve`);
            load();
        }
        catch (e) {
            showErrorGuidance({message: e?.response?.data?.error || 'Approval failed'});
        }
    }
    const canApprove = user?.role === 'SupplyChainManager';
    return (_jsxs("div", { children: [_jsxs("div", { className: "flex items-center justify-between mb-4", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-xl font-semibold text-slate-900", children: "Stock Adjustments" }), _jsx("p", { className: "text-sm text-slate-500", children: "Controlled adjustment process \u2014 requires reason and approval, fully audited." })] }), _jsx("button", { className: "btn-primary", onClick: () => setShowForm(true), children: "+ New Adjustment" })] }), _jsx("div", { className: "card", children: _jsx(DataTable, { columns: [
                        { key: 'adjustment_number', label: 'Adjustment Number' },
                        { key: 'item_code', label: 'Item' },
                        { key: 'warehouse_name', label: 'Warehouse' },
                        { key: 'location_code', label: 'Physical Bin' },
                        { key: 'quantity_change', label: 'Qty Change' },
                        { key: 'reason', label: 'Reason' },
                        { key: 'status', label: 'Status', render: (r) => _jsx(StatusBadge, { status: r.status }) },
                    ], rows: adjustments, actions: (r) => r.status === 'Pending' && canApprove ? (_jsx("button", { className: "text-emerald-600 text-xs font-medium", onClick: () => setReviewing(r), children: "Review" })) : null }) }), showForm && (_jsx(Modal, { title: "New Stock Adjustment", onClose: () => setShowForm(false), children: _jsxs("div", { className: "compact-form", children: [_jsx("div", { children: _jsx(SearchSelect, {"data-field": "item_id",  label: "Item", options: items.map((it) => ({ value: it.id, label: `${it.item_code} - ${it.description}` })), value: form.item_id ?? '', onChange: (val) => setForm({ ...form, item_id: Number(val) }), placeholder: "Search item" }) }), _jsx("div", { children: _jsx(SearchSelect, {"data-field": "warehouse_id",  label: "Warehouse", options: warehouses.map((w) => ({ value: w.id, label: w.name })), value: form.warehouse_id ?? '', onChange: (val) => setForm({ ...form, warehouse_id: Number(val) }), placeholder: "Search warehouse" }) }), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Physical Storage Bin" }), _jsxs("select", {"data-field": "location_id",  className: "input mt-1", value: form.location_id || '', onChange: e => setForm({ ...form, location_id: Number(e.target.value) }), children: [_jsx("option", { value: "", children: "Select Bin..." }), locations.filter(l => isUsableStorageLocation(l) && Number(l.warehouse_id) === Number(form.warehouse_id)).map(l => _jsxs("option", { value: l.id, children: [l.code, l.label ? ` — ${l.label}` : ''] }, l.id))] })] }), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Quantity Change (+/-)" }), _jsx("input", {"data-field": "quantity_change",  className: "input mt-1", type: "number", value: form.quantity_change ?? '', onChange: (e) => setForm({ ...form, quantity_change: Number(e.target.value) }) })] }), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Reason" }), _jsx("input", {"data-field": "reason",  className: "input mt-1", value: form.reason ?? '', onChange: (e) => setForm({ ...form, reason: e.target.value }) })] }), error && _jsx("div", {"data-error-message": true, role: "alert",  className: "text-sm text-rose-600 bg-rose-50 rounded-lg px-3 py-2", children: error }), _jsxs("div", { className: "flex justify-end gap-2 pt-2", children: [_jsx("button", { className: "btn-secondary", onClick: () => setShowForm(false), children: "Cancel" }), _jsx("button", { className: "btn-primary", onClick: submit, children: "Submit" })] })] }) })), reviewing && _jsx(Modal, { title: `Stock Adjustment - ${reviewing.adjustment_number}`, onClose: () => setReviewing(null), children: _jsxs("div", { className: "space-y-4 text-sm", children: [_jsxs("div", { className: "grid grid-cols-2 gap-3", children: [_jsxs("div", { children: [_jsx("span", { className: "text-slate-500", children: "Item:" }), " ", _jsx("strong", { children: reviewing.item_code })] }), _jsxs("div", { children: [_jsx("span", { className: "text-slate-500", children: "Warehouse:" }), " ", _jsx("strong", { children: reviewing.warehouse_name })] }), _jsxs("div", { children: [_jsx("span", { className: "text-slate-500", children: "Physical Bin:" }), " ", _jsx("strong", { children: reviewing.location_code })] }), _jsxs("div", { children: [_jsx("span", { className: "text-slate-500", children: "Quantity change:" }), " ", _jsx("strong", { children: reviewing.quantity_change })] }), _jsxs("div", { children: [_jsx("span", { className: "text-slate-500", children: "Status:" }), " ", _jsx(StatusBadge, { status: reviewing.status })] })] }), _jsxs("div", { children: [_jsx("span", { className: "text-slate-500", children: "Reason:" }), _jsx("div", { className: "mt-1 rounded-lg bg-slate-50 p-3", children: reviewing.reason })] }), reviewing.status === 'Pending' && canApprove && _jsx("div", { className: "flex justify-end", children: _jsx("button", { className: "btn-primary", onClick: async () => { await approve(reviewing.id); setReviewing(null); }, children: "Approve Adjustment" }) })] }) })] }));
}
