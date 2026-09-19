import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import client from '../../api/client';
import DataTable from '../../components/DataTable';
import Modal from '../../components/Modal';
import CurrencyInput from '../../components/CurrencyInput';
import { isCurrencyField } from '../../utils/currency';
import { normalizeSignature } from '../../utils/signature';
import EmployeeSignature from '../../components/EmployeeSignature';
import SearchSelect from '../../components/SearchSelect';
import { useAuth } from '../../contexts/AuthContext';
import useAutoRefresh from '../../hooks/useAutoRefresh';
export default function MasterDataPage({ title, description, endpoint, columns, fields, singleRecord, onCreated, onSaved, deriveForm, extraPayload, renderFormExtra, wideForm, transformFieldChange, initialForm = {}, readOnly = false, canCreate = !readOnly, canEdit, canDelete, tableClassName = '' }) {
    const { user } = useAuth();
    const effectiveCanEdit = canEdit ?? (!readOnly && user?.role === 'SupplyChainManager');
    const effectiveCanDelete = canDelete ?? (!readOnly && user?.role === 'SupplyChainManager');
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const [editing, setEditing] = useState(null);
    const [showForm, setShowForm] = useState(false);
    const [form, setForm] = useState({});
    const [error, setError] = useState('');
    const [search, setSearch] = useState('');
    function load() {
        setLoading(true);
        client
            .get(endpoint)
            .then((res) => setRows(res.data))
            .finally(() => setLoading(false));
    }
    useAutoRefresh(load);
    useEffect(() => {
        load();
    }, [endpoint]);
    function openCreate() {
        setEditing(null);
        setForm({ ...initialForm });
        setError('');
        setShowForm(true);
    }
    function openEdit(row) {
        setEditing(row);
        setForm(deriveForm ? deriveForm(row) : row);
        setError('');
        setShowForm(true);
    }
    async function save() {
        try {
            const payload = { ...Object.fromEntries(fields.filter((field) => !['signature', 'section'].includes(field.type) && field.submit !== false && (!field.createOnly || !editing) && (!field.readOnly || !editing)).map((field) => [field.key, form[field.key]])), ...(extraPayload?.(form, !!editing) || {}) };
            let saved;
            if (editing) {
                saved = (await client.put(`${endpoint}/${editing.id}`, payload)).data;
            }
            else {
                const response = await client.post(endpoint, payload);
                saved = response.data;
                onCreated?.(response.data);
            }
            const signature = fields.find(field => field.type === 'signature');
            const file = signature ? form[signature.key] : null;
            if (file instanceof File) {
                const blob = await normalizeSignature(file);
                const body = new FormData();
                body.append('signature', blob, 'employee-signature.png');
                await client.post(`${endpoint}/${saved.id}/signature`, body, { headers: { 'Content-Type': 'multipart/form-data' } });
            }
            await onSaved?.(saved, form, !!editing);
            setShowForm(false);
            load();
        }
        catch (e) {
            setError(e?.response?.data?.error || 'Save failed');
        }
    }
    async function remove(row) {
        if (!confirm(`Delete this record?`))
            return;
        try {
            await client.delete(`${endpoint}/${row.id}`);
            setError('');
            load();
        }
        catch (e) {
            setError(e?.response?.data?.error || 'Delete failed');
        }
    }
    const filteredRows = (singleRecord ? rows.slice(0, 1) : rows).filter((row) => {
        if (!search.trim())
            return true;
        const haystack = Object.values(row).join(' ').toLowerCase();
                return haystack.includes(search.toLowerCase());
    });
    return (_jsxs("div", { children: [_jsxs("div", { className: "flex items-center justify-between mb-1", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-xl font-semibold text-slate-900", children: title }), _jsx("p", { className: "text-sm text-slate-500", children: description })] }), canCreate && !(singleRecord && rows.length > 0) && (_jsxs("button", { className: "btn-primary", onClick: openCreate, children: ["+ Add ", title.replace(/s$/, '')] }))] }), _jsxs("div", { className: "card mt-4", children: [error && !showForm && _jsx("div", {"data-error-message": true, role: "alert",  className: "mb-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700", children: error }), _jsxs("div", { className: "flex items-center justify-between gap-3 mb-3", children: [_jsx("div", { className: "text-sm text-slate-500", children: "Search existing records to avoid duplicates." }), _jsx("input", {"data-field": "search",  className: "input max-w-xs", placeholder: `Search ${title.toLowerCase()}...`, value: search, onChange: (e) => setSearch(e.target.value) })] }), _jsx(DataTable, { tableClassName: tableClassName, columns: columns, rows: filteredRows, loading: loading, actions: !effectiveCanEdit && !effectiveCanDelete ? undefined : (row) => (_jsxs("div", { className: "flex gap-2 justify-end", children: [effectiveCanEdit && _jsx("button", { className: "text-brand-600 text-xs font-medium", onClick: () => openEdit(row), children: "Edit" }), effectiveCanDelete && !singleRecord && (_jsx("button", { className: "text-rose-600 text-xs font-medium", onClick: () => remove(row), children: "Delete" }))] })) })] }), showForm && (_jsx(Modal, { title: editing ? `Edit ${title}` : `New ${title}`, onClose: () => setShowForm(false), wide: wideForm, children: _jsxs("div", { className: `grid gap-x-4 gap-y-3 ${wideForm ? 'md:grid-cols-2 xl:grid-cols-3' : 'md:grid-cols-2'}`, children: [fields.filter((f) => f.visible?.(form) !== false).map((f) => (_jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: f.label }), f.type === 'signature' ? _jsxs("div", { className: "mt-1 rounded-lg border border-sky-200 bg-slate-50 p-3", children: [_jsxs("div", { className: "flex items-center gap-4", children: [editing?.signature_url && _jsx(EmployeeSignature, { src: editing.signature_url, name: editing.name }), _jsx("input", { type: "file", accept: "image/png,image/jpeg,image/webp", onChange: e => setForm({ ...form, [f.key]: e.target.files?.[0] }) })] }), _jsx("p", { className: "mt-2 text-xs text-slate-500", children: "Upload a clear signature on white or transparent background. Procuraflo automatically removes the background, crops whitespace and stores a transparent PNG." })] }) : f.type === 'checkbox' ? (_jsx("input", { type: "checkbox", className: "mt-1 ml-1", checked: !!form[f.key], onChange: (e) => setForm({ ...form, [f.key]: e.target.checked ? 1 : 0 }) })) : f.type === 'multicheckbox' ? (_jsxs("div", { className: "mt-1 grid max-h-40 gap-1 overflow-y-auto rounded-lg border border-slate-300 bg-white p-2 sm:grid-cols-2", children: [((typeof f.options === 'function' ? f.options(form) : f.options) || []).map((o) => { const selected = Array.isArray(form[f.key]) && form[f.key].some((value) => String(value) === String(o.value)); return _jsxs("label", { className: `flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm ${selected ? 'border-sky-400 bg-sky-50 text-sky-900' : 'border-slate-200 text-slate-700 hover:bg-slate-50'}`, children: [_jsx("input", { type: "checkbox", checked: selected, onChange: e => { const current = Array.isArray(form[f.key]) ? form[f.key] : []; const value = e.target.checked ? [...current, o.value] : current.filter((item) => String(item) !== String(o.value)); const next = transformFieldChange?.(f, value, form) || { ...form, [f.key]: value }; setForm(deriveForm ? deriveForm(next) : next); } }), _jsx("span", { children: o.label })] }, String(o.value)); }), !((typeof f.options === 'function' ? f.options(form) : f.options) || []).length && _jsx("div", { className: "col-span-full px-2 py-3 text-sm text-amber-700", children: "No active warehouses are available. Create a warehouse first." })] })) : f.type === 'multiselect' ? (_jsx("select", { multiple: true, className: "input mt-1 min-h-28", value: Array.isArray(form[f.key]) ? form[f.key].map(String) : [], onChange: e => { const value = Array.from(e.target.selectedOptions).map(option => option.value); const next = transformFieldChange?.(f, value, form) || { ...form, [f.key]: value }; setForm(deriveForm ? deriveForm(next) : next); }, children: (typeof f.options === 'function' ? f.options(form) : f.options)?.map((o) => _jsx("option", { value: o.value, children: o.label }, String(o.value))) })) : f.type === 'select' ? (_jsxs("select", {"data-field": f.key,  className: "input mt-1", value: form[f.key] ?? '', onChange: (e) => { const next = transformFieldChange?.(f, e.target.value, form) || { ...form, [f.key]: e.target.value }; setForm(deriveForm ? deriveForm(next) : next); }, children: [_jsx("option", { value: "", children: "Select..." }), (typeof f.options === 'function' ? f.options(form) : f.options)?.map((o) => (_jsx("option", { value: o.value, children: o.label }, o.value)))] })) : f.type === 'number' && isCurrencyField(f.key) ? (_jsx(CurrencyInput, { value: form[f.key] ?? '', min: "0", readOnly: f.readOnly, onChange: (e) => {
                                        const next = { ...form, [f.key]: e.target.value === '' ? '' : Number(e.target.value) };
                                        setForm(deriveForm ? deriveForm(next) : next);
                                    } })) : f.type === 'searchselect' ? (_jsx(SearchSelect, {"data-field": f.key,  label: "", options: (typeof f.options === 'function' ? f.options(form) : f.options) || [], value: form[f.key] ?? '', placeholder: f.placeholder || 'Search and select...', onChange: (value) => { const next = transformFieldChange?.(f, value, form) || { ...form, [f.key]: value }; setForm(deriveForm ? deriveForm(next) : next); } })) : (_jsx("input", {"data-field": f.key,  className: "input mt-1", type: f.type === 'number' ? 'number' : f.type === 'date' ? 'date' : 'text', value: form[f.key] ?? '', readOnly: f.readOnly, onChange: (e) => {
                                        const next = { ...form, [f.key]: f.type === 'number' ? Number(e.target.value) : e.target.value };
                                        setForm(deriveForm ? deriveForm(next) : next);
                                    } }))] }, f.key))), renderFormExtra && _jsx("div", { className: "md:col-span-2 xl:col-span-3", children: renderFormExtra(form, setForm, editing) }), error && _jsx("div", {"data-error-message": true, role: "alert",  className: "md:col-span-2 xl:col-span-3 text-sm text-rose-600 bg-rose-50 rounded-lg px-3 py-2", children: error }), _jsxs("div", { className: "flex justify-end gap-2 pt-2 md:col-span-2 xl:col-span-3", children: [_jsx("button", { className: "btn-secondary", onClick: () => setShowForm(false), children: "Cancel" }), _jsx("button", { className: "btn-primary", onClick: save, children: "Save" })] })] }) }))] }));
}
