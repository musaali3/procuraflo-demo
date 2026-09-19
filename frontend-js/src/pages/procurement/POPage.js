import POReceivingDetails from '../../components/POReceivingDetails';
import DocumentCopyActions from '../../components/DocumentCopyActions';
import { showErrorGuidance } from '../../utils/errorGuidance';
import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useRef, useState } from 'react';
import client from '../../api/client';
import DataTable from '../../components/DataTable';
import Modal from '../../components/Modal';
import HorizontalScroll from '../../components/HorizontalScroll';
import StatusBadge from '../../components/StatusBadge';
import { useAuth } from '../../contexts/AuthContext';
import { formatCurrency, getStoredCurrency } from '../../utils/currency';
import DocumentAttachments from '../../components/DocumentAttachments';
import ProfessionalPurchaseOrder from '../../components/ProfessionalPurchaseOrder';
import ManagementApprovalRequest from '../../components/ManagementApprovalRequest';
import { useSearchParams } from 'react-router-dom';
import { COMPANY_COPY, MANAGEMENT_COPY, PO_VENDOR_COPY } from '../../utils/printCopies';
import { downloadElementPdf } from '../../utils/downloadPdf';
import useAutoRefresh from '../../hooks/useAutoRefresh';
function normalizePoDocument(data) {
    if (data?.po?.po_number)
        return data;
    if (data?.po_number) {
        const { items = [], company = {}, approvals = [], ...po } = data;
        return { po, items, company, approvals };
    }
    throw new Error('Purchase order document data is incomplete');
}
import SearchSelect from '../../components/SearchSelect';
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
function PriceReference({ line, currency }) {
    if (!line.item_id) return null;
    const lowest = Number(line.global_lowest_price);
    const current = Number(line.price || 0);
    const hasLowest = Number.isFinite(lowest) && lowest > 0;
    const variance = hasLowest ? current - lowest : 0;
    return _jsxs("div", { className: "col-span-12 border-t border-slate-200 pt-2 text-xs", children: [
        hasLowest && variance > 0.0001 && _jsxs("div", { className: "mb-2 rounded-md bg-amber-50 px-2 py-1 font-medium text-amber-800", children: ["Current PO price is above the lowest historical price by ", formatCurrency(variance, currency)] }),
        _jsxs("details", { children: [
            _jsx("summary", { className: "cursor-pointer font-medium text-brand-600", children: "View Price History" }),
            _jsxs("div", { className: "mt-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-slate-700", children: [
                _jsxs("div", { className: "grid gap-2 sm:grid-cols-2 lg:grid-cols-3", children: [
                    _jsxs("div", { children: [_jsx("span", { className: "block text-slate-500", children: "Lowest historical price" }), _jsx("strong", { children: hasLowest ? formatCurrency(lowest, currency) : "No closed-PO history" }), hasLowest && _jsxs("div", { className: "text-[10px]", children: [line.global_lowest_supplier_name || "Supplier not recorded", line.global_lowest_po_number ? ` ? ${line.global_lowest_po_number}` : "", line.global_lowest_po_date ? ` ? ${line.global_lowest_po_date}` : ""] })] }),
                    _jsxs("div", { children: [_jsx("span", { className: "block text-slate-500", children: "Selected supplier lowest price" }), _jsx("strong", { children: line.supplier_lowest_price != null ? formatCurrency(line.supplier_lowest_price, currency) : "No supplier history" })] }),
                    _jsxs("div", { children: [_jsx("span", { className: "block text-slate-500", children: "Last purchase price" }), _jsx("strong", { children: line.last_purchase_price != null ? formatCurrency(line.last_purchase_price, currency) : "Not available" }), line.last_purchase_po_number && _jsxs("div", { className: "text-[10px]", children: [line.last_purchase_supplier_name || "Supplier not recorded", line.last_purchase_po_number ? ` ? ${line.last_purchase_po_number}` : ""] })] }),
                    _jsxs("div", { children: [_jsx("span", { className: "block text-slate-500", children: "Current PO price" }), _jsx("strong", { children: formatCurrency(current, currency) })] }),
                    _jsxs("div", { children: [_jsx("span", { className: "block text-slate-500", children: "Price variance" }), _jsx("strong", { children: hasLowest ? formatCurrency(variance, currency) : "No historical comparison" })] }),
                    _jsxs("div", { children: [_jsx("span", { className: "block text-slate-500", children: "Pricing basis" }), _jsx("strong", { children: line.pricing_basis || "Normalized reference per purchase UOM" })] }),
                ] }),
                hasLowest && _jsx("p", { className: "mt-2 text-[10px] text-slate-500", children: "Lowest price is reference only. The entered PO price remains editable and follows existing approval rules." }),
            ] }),
        ] }),
    ] });
}
export default function POPage() {
    const [searchParams, setSearchParams] = useSearchParams();
    const { user } = useAuth();
    const [pos, setPos] = useState([]);
    const [suppliers, setSuppliers] = useState([]);
    const [items, setItems] = useState([]);
    const [warehouses, setWarehouses] = useState([]);
    const [showForm, setShowForm] = useState(false);
    const [supplierId, setSupplierId] = useState('');
    const [lines, setLines] = useState([{ item_id: '', quantity: 1, price: 0, tax: 0 }]);
    const [error, setError] = useState('');
    const [committedDeliveryDate, setCommittedDeliveryDate] = useState('');
    const [deliveryWarehouseId, setDeliveryWarehouseId] = useState('');
    const [approving, setApproving] = useState(null);
    const [approvalRef, setApprovalRef] = useState('');
    const [approvalPerson, setApprovalPerson] = useState('');
    const [history, setHistory] = useState([]);
    const [doc, setDoc] = useState(null);
    const [editingId, setEditingId] = useState(null);
    const [openPrs, setOpenPrs] = useState([]);
    const [selectedPrIds, setSelectedPrIds] = useState([]);
    const prLoadSequence = useRef(0);
    function load() {
        client.get('/procurement/pos').then((res) => setPos(res.data));
        client.get('/procurement/eligible-prs').then((res) => setOpenPrs(res.data));
    }
    useAutoRefresh(load);
    useEffect(() => {
        load();
        client.get('/masters/suppliers').then((res) => setSuppliers(res.data));
        client.get('/masters/items').then((res) => setItems(res.data.filter((i) => i.active_yn !== 0)));
        client.get('/masters/warehouses').then((res) => {
            const active = res.data.filter((w) => w.active_yn !== 0);
            setWarehouses(active);
            if (active.length === 1)
                setDeliveryWarehouseId(active[0].id);
        });
    }, []);
    useEffect(() => {
        const openId = Number(searchParams.get('open'));
        const target = openId ? pos.find((row) => row.id === openId) : null;
        if (!target)
            return;
        setSearchParams({}, { replace: true });
        openApproval(target);
    }, [pos, searchParams, setSearchParams]);
    const pricingItemKey = Array.from(new Set(lines.map((line) => Number(line.item_id)).filter(Number.isInteger))).sort((a, b) => a - b).join(',');
    useEffect(() => {
        if (!pricingItemKey)
            return;
        let cancelled = false;
        client.post('/procurement/pos/pricing', { supplier_id: supplierId || undefined, transaction_currency: getStoredCurrency(), item_ids: pricingItemKey.split(',').map(Number) }).then((response) => {
            if (cancelled)
                return;
            const pricing = new Map(response.data.map((row) => [Number(row.item_id), row]));
            setLines((current) => current.map((line) => {
                const history = pricing.get(Number(line.item_id));
                if (!history)
                    return line;
                return {
                    ...line,
                    price: history.latest_supplier_price != null ? Number(history.latest_supplier_price) : line.price,
                    tax: history.latest_supplier_tax != null ? Number(history.latest_supplier_tax) : line.tax,
                    latest_supplier_po_number: history.latest_supplier_po_number,
                    pricing_basis: history.pricing_basis,
                    global_lowest_price: history.global_lowest_price,
                    global_lowest_supplier_name: history.global_lowest_supplier_name,
                    global_lowest_po_number: history.global_lowest_po_number,
                    global_lowest_po_date: history.global_lowest_po_date,
                    last_purchase_price: history.last_purchase_price,
                    last_purchase_supplier_name: history.last_purchase_supplier_name,
                    last_purchase_po_number: history.last_purchase_po_number,
                    supplier_lowest_price: history.supplier_lowest_price,
                    all_supplier_average_price: history.all_supplier_average_price,
                    received_history_count: Number(history.received_history_count || 0),
                };
            }));
        }).catch((e) => { if (!cancelled)
            setError(e?.response?.data?.error || 'Unable to load supplier price history'); });
        return () => { cancelled = true; };
    }, [supplierId, pricingItemKey]);
    function addLine() {
        setLines((current) => [...current, { item_id: '', item_search: '', quantity: 1, price: 0, tax: 0 }]);
    }
    function removeLine(index) {
        setLines((current) => current.length === 1 ? current : current.filter((_, lineIndex) => lineIndex !== index));
    }
    function updateLine(i, key, val) {
        setLines((current) => current.map((line, index) => index === i ? { ...line, [key]: val } : line));
    }
    const estimatedTotal = lines.reduce((s, l) => s + (l.quantity || 0) * (l.price || 0) * (1 + (l.tax || 0) / 100), 0);
    async function submit() {
        setError('');
        if (!supplierId)
            return setError('Select a vendor before submitting the purchase order.');
        if (!committedDeliveryDate)
            return setError('Committed delivery date is required.');
        if (!Number.isInteger(Number(deliveryWarehouseId)))
            return setError('Select the delivery warehouse for this purchase order.');
        if (!editingId && committedDeliveryDate < new Date().toISOString().slice(0, 10))
            return setError('Committed delivery date cannot be earlier than today.');
        if (!lines.length || lines.some((line) => !Number.isInteger(Number(line.item_id)) || !(Number(line.quantity) > 0) || Number(line.price) < 0 || Number(line.tax || 0) < 0))
            return setError('Select a valid item and enter a positive quantity and non-negative price/tax for every PO line.');
        const overPrBalance = lines.find((line) => line.pr_available_quantity != null && Number(line.quantity) > Number(line.pr_available_quantity) + 0.0001);
        if (overPrBalance)
            return setError(`${overPrBalance.item_search || 'PO item'} quantity cannot exceed the approved outstanding PR balance of ${Number(overPrBalance.pr_available_quantity).toLocaleString()}.`);
        try {
            if (editingId)
                await client.put(`/procurement/pos/${editingId}`, { supplier_id: supplierId, delivery_warehouse_id: Number(deliveryWarehouseId), committed_delivery_date: committedDeliveryDate, items: lines });
            else
                await client.post('/procurement/pos', { supplier_id: supplierId, delivery_warehouse_id: Number(deliveryWarehouseId), committed_delivery_date: committedDeliveryDate, pr_ids: selectedPrIds, items: lines });
            setShowForm(false);
            setLines([{ item_id: '', item_search: '', quantity: 1, price: 0, tax: 0 }]);
            setSupplierId('');
            setCommittedDeliveryDate('');
            setDeliveryWarehouseId('');
            setEditingId(null);
            setSelectedPrIds([]);
            load();
        }
        catch (e) {
            setError(e?.response?.data?.error || 'Failed to create PO');
        }
    }
    async function approve() {
        if (approving.external_approval_required && (!approvalRef.trim() || !approvalPerson.trim())) {
            showErrorGuidance({message: 'Enter the external approval reference and approving management person after uploading the signed approval document.'});
            return;
        }
        try {
            await client.put(`/procurement/pos/${approving.id}/approve`, {
                approval_ref_number: approvalRef,
                approval_person_name: approvalPerson,
            });
            setApproving(null);
            setApprovalRef('');
            setApprovalPerson('');
            load();
        }
        catch (e) {
            showErrorGuidance({message: e?.response?.data?.error || 'Approval failed'});
        }
    }
    async function cancelPo(row) {
        const reason=window.prompt(`Reason for cancelling ${row.po_number}:`);
        if (!reason?.trim()) return;
        try { await client.put(`/procurement/pos/${row.id}/cancel`, {reason: reason.trim()}); await load(); }
        catch(e) { showErrorGuidance({message: e?.response?.data?.error || 'Unable to cancel purchase order'}); }
    }
    async function reject(id) {
        await client.put(`/procurement/pos/${id}/reject`);
        load();
    }
    async function loadPrForPo(prIds = selectedPrIds) {
        const sequence = ++prLoadSequence.current;
        if (!prIds.length) {
            setLines([{ item_id: '', item_search: '', quantity: 1, price: 0, tax: 0 }]);
            setError('');
            return;
        }
        try {
            const requisitions = await Promise.all(prIds.map((id) => client.get(`/procurement/prs/${id}`).then((response) => response.data)));
            if (sequence !== prLoadSequence.current)
                return;
            const originIds=[...new Set(requisitions.map(pr=>pr.trigger_warehouse_id).filter(Boolean))];
            if(originIds.length>1) throw new Error("Select PRs for the same delivery warehouse");
            if(originIds.length===1)setDeliveryWarehouseId(originIds[0]);
            const consolidated = new Map();
            requisitions.forEach((pr) => pr.items.forEach((line) => {
                const masterItem = items.find((candidate) => candidate.id === line.item_id);
                const purchaseFactor=masterItem?.purchase_uom === masterItem?.uom ? 1 : Number(masterItem?.conversion_factor || 1);
                const prFactor=Number(line.base_quantity || line.quantity)/Number(line.quantity);
                const available=Number(line.remaining_quantity ?? line.quantity)*prFactor/purchaseFactor;
                const existing = consolidated.get(line.item_id);
                if (existing) {
                    existing.quantity += available;
                    existing.pr_available_quantity += available;
                }
                else
                    consolidated.set(line.item_id, {
                        item_id: line.item_id,
                        item_search: `${line.item_code} - ${line.description}`,
                        quantity: available,
                        pr_available_quantity: available,
                        price: Number(masterItem?.last_purchase_price ?? masterItem?.standard_cost ?? 0),
                        tax: 0,
                    });
            }));
            setLines(Array.from(consolidated.values()).filter((line) => line.quantity > 0));
            const requestedDates = requisitions.flatMap((pr) => pr.items.map((line) => line.required_date).filter(Boolean)).sort();
            if (requestedDates.length && !committedDeliveryDate)
                setCommittedDeliveryDate(requestedDates[requestedDates.length - 1]);
            setError('');
        }
        catch (e) {
            if (sequence === prLoadSequence.current)
                setError(e?.response?.data?.error || 'Unable to consolidate the selected PRs');
        }
    }
    function togglePurchaseRequisition(prId) {
        const next = selectedPrIds.includes(prId) ? selectedPrIds.filter((id) => id !== prId) : [...selectedPrIds, prId];
        setSelectedPrIds(next);
        loadPrForPo(next);
    }
    async function openDoc(id) {
        try {
            const res = await client.get(`/procurement/pos/${id}/document`);
            setDoc(normalizePoDocument(res.data));
            load();
        }
        catch (e) {
            showErrorGuidance({message: e?.response?.data?.error || 'Cannot view this PO'});
        }
    }
    async function printDoc(id) {
        try {
            await client.post(`/procurement/pos/${id}/print`);
            await openDoc(id);
        }
        catch (e) {
            showErrorGuidance({message: e?.response?.data?.error || e?.response?.data?.detail || (e?.response?.status >= 500 ? 'The server could not prepare this PO for printing. Reopen the PO and retry; if it continues, ask your administrator to check the server error log.' : 'Unable to reach the server to prepare this PO. Check the connection and retry.')});
        }
    }
    async function openApproval(row) {
        try {
            const [detail, approvalHistory] = await Promise.all([
                client.get(`/procurement/pos/${row.id}/document`),
                client.get(`/procurement/pos/${row.id}/approval-history`),
            ]);
            setApproving({ ...row, document: normalizePoDocument(detail.data) });
            setHistory(approvalHistory.data);
        }
        catch (e) {
            showErrorGuidance({message: e?.response?.data?.error || 'Cannot open PO for approval'});
        }
    }
    async function editPo(row) { try {
        const detail = (await client.get(`/procurement/pos/${row.id}`)).data;
        setEditingId(row.id);
        setSupplierId(detail.supplier_id);
        setCommittedDeliveryDate(detail.committed_delivery_date || '');
        setDeliveryWarehouseId(detail.delivery_warehouse_id || '');
        setLines(detail.items);
        setShowForm(true);
    }
    catch (e) {
        setError(e?.response?.data?.error || 'Unable to edit PO');
    } }
    const canApprove = user && ['PurchaseOfficer', 'PurchaseManager', 'SupplyChainManager'].includes(user.role);
    const canEditPending = user && ['PurchaseOfficer', 'PurchaseManager', 'SupplyChainManager'].includes(user.role);
            return (_jsxs("div", { children: [_jsxs("div", { className: "flex items-center justify-between mb-4", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-xl font-semibold text-slate-900", children: "Purchase Orders" }), _jsx("p", { className: "text-sm text-slate-500", children: "Approval routing follows both value limits and upward hierarchy: Purchase Officer creators route to Purchase Manager, Purchase Manager creators route to Supply Chain Manager, and POs above the Supply Chain Manager limit require signed higher-management approval." })] }), _jsx("button", { className: "btn-primary", onClick: () => setShowForm(true), children: "+ New PO" })] }), _jsx("div", { className: "card", children: _jsx(DataTable, { columns: [
                        { key: 'po_number', label: 'PO Number' },
                        { key: 'pr_number', label: 'Source PR' },
                        { key: 'supplier_name', label: 'Supplier' },
                        { key: 'delivery_warehouse_name', label: 'Delivery Warehouse', render: (r) => [r.delivery_warehouse_code, r.delivery_warehouse_name].filter(Boolean).join(' ? ') || '?' },
                        { key: 'committed_delivery_date', label: 'Committed Delivery', render: (r) => _jsxs("div", { children: [_jsx("div", { children: r.committed_delivery_date || 'Not set' }), r.delivery_status === 'Overdue' && _jsxs("div", { className: "text-[10px] font-semibold text-rose-600", children: [r.days_overdue, " day", r.days_overdue === 1 ? '' : 's', " overdue"] })] }) },
                        { key: 'total_amount', label: 'Total', render: (r) => formatCurrency(r.total_amount) },
                        { key: 'status', label: 'Status', render: (r) => _jsx(StatusBadge, { status: r.status }) },
                    ], rows: pos, actions: (r) => (_jsxs("div", { className: "flex gap-2 justify-end", children: [r.status === 'PendingApproval' && r.external_approval_required ? (_jsx("button", { className: "rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-800 hover:bg-amber-100", onClick: () => openApproval(r), children: "Management Approval Request" })) : r.status === 'PendingApproval' && canApprove && (_jsxs(_Fragment, { children: [_jsx("button", { className: "text-emerald-600 text-xs font-medium", onClick: () => openApproval(r), children: "Approve" }), _jsx("button", { className: "text-rose-600 text-xs font-medium", onClick: () => reject(r.id), children: "Reject" })] })), canApprove && ['Draft','PendingApproval','Approved','Printed'].includes(r.status) && _jsx("button", { className: "text-rose-600 text-xs font-medium", onClick: () => cancelPo(r), children: "Cancel PO" }), r.status === 'PendingApproval' && canEditPending && _jsx("button", { className: "text-slate-600 text-xs font-medium", onClick: () => editPo(r), children: "Edit Qty / PO" }), r.status === 'PendingApproval' && r.external_approval_required && user?.role === 'SupplyChainManager' && _jsx("button", { className: "text-rose-600 text-xs font-medium", onClick: () => reject(r.id), children: "Reject" }), _jsx("button", { className: "text-slate-600 text-xs font-medium", onClick: () => openDoc(r.id), children: "View" }), r.status === 'Approved' && (_jsx("button", { className: "text-brand-600 text-xs font-medium", onClick: () => printDoc(r.id), children: "Print" }))] })) }) }), showForm && (_jsx(Modal, { title: editingId ? 'Edit Pending Purchase Order' : 'New Purchase Order', onClose: () => { setShowForm(false); setEditingId(null); }, wide: true, children: _jsxs("div", { className: "compact-form", children: [_jsxs("div", { className: "grid gap-3 lg:grid-cols-2", children: [!editingId ? _jsxs("div", { className: "form-section-tinted min-w-0", children: [_jsx("h3", { className: "font-medium text-emerald-900 mb-1", children: "Approved PR Selection" }), _jsx("label", { className: "block text-sm font-medium mb-2", children: "Approved PRs Awaiting PO" }), _jsx("div", { className: "max-h-32 overflow-y-auto rounded-lg border border-emerald-200 bg-white divide-y divide-slate-100", children: openPrs.length ? openPrs.map((pr) => _jsxs("label", { className: "flex cursor-pointer items-start gap-3 px-3 py-2 text-sm hover:bg-emerald-50", children: [_jsx("input", { type: "checkbox", className: "mt-1", checked: selectedPrIds.includes(pr.id), onChange: () => togglePurchaseRequisition(pr.id) }), _jsxs("span", { children: [_jsx("strong", { children: pr.pr_number }), _jsxs("span", { className: "block text-xs text-slate-500", children: [pr.department_name || 'No department', " \u00B7 ", pr.requestor_name || 'Unknown requestor', ' ? ', [pr.warehouse_code, pr.warehouse_name].filter(Boolean).join(' ? ') || 'No warehouse'] })] })] }, pr.id)) : _jsx("div", { className: "px-3 py-4 text-sm text-slate-500", children: "No approved PRs awaiting PO creation are available." }) }), _jsx("div", { className: "mt-3 text-xs text-emerald-700", children: selectedPrIds.length ? `${selectedPrIds.length} PR${selectedPrIds.length === 1 ? '' : 's'} selected: ${openPrs.filter(pr => selectedPrIds.includes(pr.id)).map(pr => pr.pr_number).join(', ')}` : 'No PR selected.' })] }) : _jsxs("div", { className: "form-section-tinted min-w-0", children: [_jsx("h3", { className: "form-section-title", children: "Approved PR Selection" }), _jsx("p", { className: "text-xs text-slate-600", children: pos.find(po => po.id === editingId)?.pr_number || (pos.find(po => po.id === editingId)?.pr_id ? `Source PR #${pos.find(po => po.id === editingId).pr_id}` : "Source PR references remain linked to this PO.") })] }), _jsxs("div", { className: "form-section-tinted min-w-0", children: [_jsx("h3", { className: "form-section-title", children: "Supplier & Delivery Details" }), _jsxs("div", { className: "grid gap-3", children: [_jsx(SearchSelect, {"data-field": "supplierId",  label: "Supplier", options: suppliers.map((s) => ({ value: s.id, label: s.name })), value: supplierId, onChange: (val) => setSupplierId(Number(val)), placeholder: "Search supplier" }), _jsx(SearchSelect, { "data-field": "deliveryWarehouseId", label: "Delivery Warehouse", options: warehouses.map(w => ({ value: w.id, label: [w.warehouse_code, w.name].filter(Boolean).join(' ? ') })), value: deliveryWarehouseId, onChange: value => setDeliveryWarehouseId(Number(value)), disabled: Boolean(editingId) || selectedPrIds.length > 0, placeholder: "Select delivery warehouse" }), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Committed Delivery Date" }), _jsx("input", {"data-field": "committedDeliveryDate",  className: "input mt-1", type: "date", min: editingId ? undefined : new Date().toISOString().slice(0, 10), value: committedDeliveryDate, onChange: (e) => setCommittedDeliveryDate(e.target.value) }), ] })] })] })] }), _jsxs("div", { className: "form-section", children: [_jsx("h3", { className: "form-section-title", children: "Purchase Lines" }), _jsx(HorizontalScroll, { className: "space-y-2 mt-1", role: "region", "aria-label": "Purchase order item lines", children: lines.map((line, i) => (_jsxs("div", { className: "form-line-card grid min-w-[56rem] grid-cols-12 gap-2 items-start", children: [_jsx("div", { className: "col-span-4", children: _jsx(SearchSelect, {"data-field": "item_id",  label: "Item", options: items.map((it) => ({ value: it.id, label: `${it.item_code} - ${it.description}` })), value: line.item_id || line.item_search || '', onChange: (val) => {
                                                        const selected = items.find((it) => it.id === Number(val));
                                                        setLines((current) => current.map((currentLine, index) => index === i ? { ...currentLine, item_id: selected?.id || '', item_search: selected ? `${selected.item_code} - ${selected.description}` : '' } : currentLine));
                                                    }, placeholder: "Search item" }) }), (() => {
                                                const selectedItem = items.find((item) => item.id === line.item_id);
                                                const unit = selectedItem?.purchase_uom || selectedItem?.uom || 'Unit';
                                                const wholeNumber = ['EA', 'PCS', 'PC', 'BOX', 'BAG', 'SET', 'PR', 'PAIR', 'PACK', 'ROLL', 'BOTTLE', 'CAN', 'DRUM', 'PALLET'].includes(String(unit).toUpperCase());
                                                return _jsxs(_Fragment, { children: [_jsxs("div", { className: "col-span-2", children: [_jsxs("label", { className: "text-sm font-medium text-slate-700", children: ["Quantity (", unit, ")"] }), _jsx("input", {"data-field": "quantity",  className: "input mt-1", type: "number", min: wholeNumber ? 1 : 0.001, max: line.pr_available_quantity != null ? Number(line.pr_available_quantity) : undefined, step: wholeNumber ? 1 : 0.001, placeholder: `Qty in ${unit}`, value: line.quantity, onChange: (e) => updateLine(i, 'quantity', Number(e.target.value)) }), line.pr_available_quantity != null && _jsxs("div", { className: "mt-1 text-[10px] font-medium text-emerald-700", children: ["Approved PR balance: ", Number(line.pr_available_quantity).toLocaleString(), " ", unit] })] }), _jsxs("div", { className: "col-span-2", children: [_jsxs("label", { className: "text-sm font-medium text-slate-700", children: ["Price / ", unit] }), _jsx("input", {"data-field": "price",  className: "input mt-1", type: "number", min: "0", step: "0.01", placeholder: `Price per ${unit}`, value: line.price, onChange: (e) => updateLine(i, 'price', Number(e.target.value)) })] })] });
                                            })(), _jsxs("div", { className: "col-span-1", children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Tax %" }), _jsx("input", {"data-field": "tax",  className: "input mt-1", type: "number", min: "0", step: "0.01", placeholder: "Tax percentage", value: line.tax, onChange: (e) => updateLine(i, 'tax', Number(e.target.value)) })] }), _jsxs("div", { className: "col-span-2 text-sm", children: [_jsx("label", { className: "font-medium text-slate-700", children: "Line Total" }), _jsx("div", { className: "mt-2 font-semibold text-slate-900", children: formatCurrency(Number(line.quantity || 0) * Number(line.price || 0) * (1 + Number(line.tax || 0) / 100)) })] }), _jsx("div", { className: "col-span-1 flex justify-end lg:pt-8", children: lines.length > 1 && _jsx("button", { type: "button", className: "text-xs font-medium text-rose-600 hover:text-rose-800", onClick: () => removeLine(i), children: "Remove" }) }), _jsx(PriceReference, { line: line, currency: getStoredCurrency() })] }, i))) }), _jsx("button", { type: "button", className: "text-brand-600 text-sm font-medium mt-2", onClick: addLine, children: "+ Add Another Item" })] }), _jsxs("div", { className: "text-right text-sm font-medium text-slate-700", children: ["Estimated Total: ", formatCurrency(estimatedTotal)] }), error && _jsx("div", {"data-error-message": true, role: "alert",  className: "text-sm text-rose-600 bg-rose-50 rounded-lg px-3 py-2", children: error }), _jsxs("div", { className: "flex justify-end gap-2 pt-2", children: [_jsx("button", { className: "btn-secondary", onClick: () => setShowForm(false), children: "Cancel" }), _jsx("button", { className: "btn-primary", onClick: submit, children: editingId ? 'Save Changes' : 'Submit PO' })] })] }) })), approving && (_jsx(Modal, { title: approving.external_approval_required ? `Higher Management Approval — ${approving.po_number}` : `Approve ${approving.po_number}`, onClose: () => setApproving(null), wide: !!approving.external_approval_required, children: _jsxs("div", { className: "space-y-3", children: [_jsxs("div", { className: "text-sm text-slate-600", children: ["Total amount: ", _jsx("span", { className: "font-semibold", children: formatCurrency(approving.total_amount) })] }), approving.document && !approving.external_approval_required && (_jsxs("div", { className: "rounded-lg border border-slate-200 p-3", children: [_jsxs("div", { className: "text-sm mb-2", children: [_jsx("span", { className: "text-slate-500", children: "Supplier:" }), " ", approving.document.po.supplier_name] }), _jsx("div", { className: "max-w-full overflow-x-auto", children: _jsxs("table", { className: "table-base", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Item" }), _jsx("th", { children: "Qty" }), _jsx("th", { children: "Price" }), _jsx("th", { children: "Tax" })] }) }), _jsx("tbody", { children: approving.document.items.map((line) => _jsxs("tr", { children: [_jsxs("td", { children: [line.item_code, " - ", line.description] }), _jsx("td", { children: line.quantity }), _jsx("td", { children: formatCurrency(line.price) }), _jsxs("td", { children: [line.tax, "%"] })] }, line.id)) })] }) })] })), approving.external_approval_required ? _jsxs(_Fragment, { children: [_jsx("div", { className: "rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900", children: "This PO exceeds the Supply Chain Manager approval limit. Print the separate request below, obtain higher-management approval, then upload the signed document before approving the PO in Procuraflo." }), _jsxs("div", { className: "rounded-lg bg-blue-50 px-3 py-2 text-sm text-blue-900", children: [_jsx("span", { className: "text-blue-500", children: "System approval request reference:" }), " ", _jsx("strong", { className: "select-all", children: approving.document?.po?.management_approval_request_number || approving.management_approval_request_number })] }), _jsxs("div", { className: "sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-blue-200 bg-white/95 p-3 shadow-sm print:hidden", children: [_jsxs("div", { children: [_jsx("div", { className: "font-semibold text-blue-900", children: "Professional Management Approval Request" }), _jsx("div", { className: "text-xs text-slate-500", children: "Print, obtain signature, and upload the signed copy below." })] }), _jsxs("div", { className: "flex gap-2", children: [_jsx(DocumentCopyActions, { documentId: "management-approval-document", filename: `${approving.po_number}-management-approval`, copies: [{...COMPANY_COPY,label:'Company Record'},{...MANAGEMENT_COPY,label:'Management Record'}] })] })] }), approving.document && _jsx(ManagementApprovalRequest, { doc: approving.document }), _jsx(DocumentAttachments, { type: "MANUAL_APPROVAL", documentId: approving.id, onUploaded: (result) => { if (result.po_status === 'Approved') {
                                        alert('Signed management approval uploaded. The PO is now approved and ready for procurement to print.');
                                        setApproving(null);
                                        load();
                                    } } })] }) : _jsx(DocumentAttachments, { type: "PO", documentId: approving.id }), history.length > 0 && (_jsxs("div", { className: "text-xs bg-slate-50 rounded-lg p-2 space-y-1", children: [_jsx("div", { className: "font-medium text-slate-600 mb-1", children: "Approval history" }), history.map((h) => (_jsxs("div", { className: "flex justify-between text-slate-500", children: [_jsxs("span", { children: [h.required_role || 'Requested', " by ", h.requested_by_name || '—'] }), _jsxs("span", { children: [h.decision, h.decision_by_name ? ` — ${h.decision_by_name}` : ''] })] }, h.id)))] })), _jsxs("div", { children: [_jsxs("label", { className: "text-sm font-medium text-slate-700", children: ["Signed Management Decision Reference ", approving.external_approval_required ? _jsx("span", { className: "text-rose-600", children: "(required after approval)" }) : null] }), _jsx("input", {"data-field": "approvalRef",  className: "input mt-1", value: approvalRef, onChange: (e) => setApprovalRef(e.target.value) })] }), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Approval Person Name" }), _jsx("input", {"data-field": "approvalPerson",  className: "input mt-1", value: approvalPerson, onChange: (e) => setApprovalPerson(e.target.value), placeholder: user?.full_name })] }), _jsxs("div", { className: "flex justify-end gap-2", children: [_jsx("button", { className: "btn-secondary", onClick: () => setApproving(null), children: "Cancel" }), Number(approving.created_by) === Number(user?.id) && user?.role !== 'SupplyChainManager' ? _jsx("span", { className: "rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700", children: "You created this PO and cannot record its approval." }) : approving.external_approval_required && user?.role !== 'SupplyChainManager' ? _jsx("span", { className: "rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800", children: "SCM must record the signed external-management approval." }) : _jsx("button", { className: "btn-primary", onClick: approve, children: approving.external_approval_required ? "Record External Approval" : "Confirm Approval" })] })] }) })), doc && (_jsx(Modal, { title: `Purchase Order — ${doc.po.po_number}`, onClose: () => setDoc(null), wide: true, children: _jsxs("div", { className: "space-y-4", children: [_jsx(ProfessionalPurchaseOrder, { doc: doc }), _jsx(POReceivingDetails,{po:doc.po}), _jsx("div", { className: "po-supporting-documents print:hidden", children: _jsx(DocumentAttachments, { type: "PO", documentId: doc.po.id }) }), _jsxs("div", { className: "flex justify-end print:hidden", children: [_jsx(DocumentCopyActions, { documentId: "po-print-document", filename: doc.po.po_number, copies: [{...COMPANY_COPY,label:'Company Record'},{...PO_VENDOR_COPY,label:'Vendor Record'}] })] })] }) }))] }));
}
