import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import React, { useEffect, useState } from 'react';
import client from '../api/client';
import { formatCurrency } from '../utils/currency';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import useAutoRefresh from '../hooks/useAutoRefresh';
function MiniBars({ title, subtitle, rows, series }) {
    const max = Math.max(1, ...rows.flatMap(row => series.map(s => Number(row[s.key] || 0))));
    return _jsxs("div", { className: "card flex min-h-64 flex-col p-4", children: [_jsxs("div", { children: [_jsx("h3", { className: "font-semibold text-slate-800", children: title }), _jsx("p", { className: "text-xs text-slate-500", children: subtitle })] }), _jsx("div", { className: "mt-4 flex flex-1 items-end gap-3 border-b border-slate-200 px-1", children: rows.map((row, index) => _jsx("div", { className: "flex h-40 flex-1 items-end justify-center gap-1", children: series.map(s => _jsx("div", { title: `${s.label}: ${Number(row[s.key] || 0).toLocaleString()}`, className: `w-full max-w-5 rounded-t ${s.color} transition hover:brightness-110`, style: { height: `${Math.max(4, Number(row[s.key] || 0) / max * 125)}px` } }, s.key)) }, `${row.month || row.label}-${index}`)) }), _jsx("div", { className: "mt-2 flex justify-around gap-2 text-[9px] text-slate-500", children: rows.map((row, index) => _jsx("span", { children: String(row.month || row.label || '').slice(-7) }, index)) }), _jsx("div", { className: "mt-3 flex flex-wrap justify-center gap-3", children: series.map(s => _jsxs("span", { className: "flex items-center gap-1 text-[10px] text-slate-600", children: [_jsx("i", { className: `h-2 w-2 rounded-full ${s.color}` }), s.label] }, s.key)) })] });
}
function StatusBars({ rows }) { const total = rows.reduce((sum, row) => sum + Number(row.value || 0), 0); const colors = ['bg-blue-600', 'bg-cyan-500', 'bg-emerald-500', 'bg-amber-500', 'bg-rose-500', 'bg-cyan-500']; return _jsxs("div", { className: "card min-h-64 p-4", children: [_jsx("h3", { className: "font-semibold text-slate-800", children: "PO Status Portfolio" }), _jsx("p", { className: "text-xs text-slate-500", children: "Distribution of purchase orders by lifecycle status." }), _jsx("div", { className: "mt-5 flex h-4 overflow-hidden rounded-full bg-slate-100", children: rows.map((r, i) => _jsx("div", { title: `${r.label}: ${r.value}`, className: colors[i % colors.length], style: { width: `${total ? Number(r.value) / total * 100 : 0}%` } }, r.label)) }), _jsx("div", { className: "mt-4 grid grid-cols-2 gap-2", children: rows.map((r, i) => _jsxs("div", { className: "flex items-center justify-between rounded-lg bg-slate-50 px-2.5 py-2 text-xs", children: [_jsxs("span", { className: "flex min-w-0 items-center gap-2", children: [_jsx("i", { className: `h-2.5 w-2.5 shrink-0 rounded-full ${colors[i % colors.length]}` }), _jsx("span", { className: "truncate", children: r.label })] }), _jsx("strong", { children: r.value })] }, r.label)) })] }); }
function KpiCard({ label, value, accent, helper, tone = 'blue' }) {
    const navigate = useNavigate();
    const tones = { blue: 'from-blue-500 to-cyan-600', emerald: 'from-emerald-500 to-teal-600', amber: 'from-amber-400 to-orange-500', special: 'from-blue-600 to-cyan-500', rose: 'from-rose-500 to-pink-600', cyan: 'from-cyan-500 to-blue-500' };
    const destinations = {
        'Total Inventory Value': '/inventory/valuation', 'Inventory Value': '/inventory/valuation',
        'Monthly Purchase': '/reports?report=po-register', 'Monthly Consumption': '/reports?report=daily-issues',
        'Low Stock Items': '/inventory/stock', 'Out of Stock': '/inventory/stock',
        'Pending Approvals': '/reports?report=approval-governance', 'Active Suppliers': '/masters/suppliers',
        'Avg Supplier Rating': '/advanced/vendor-scorecard', 'Supplier Rating': '/masters/suppliers',
        'Open Purchase Orders': '/procurement/po', 'Outstanding PO Value': '/procurement/po', 'Overdue Purchase Orders': '/procurement/po', 'Overdue POs': '/procurement/po', 'RFQ closing': '/procurement/rfq', 'RFQ award approval': '/procurement/rfq',
        'Invoice Exceptions': '/procurement/invoices', 'Invoices Pending': '/procurement/invoices', 'Matched Invoices': '/procurement/invoices',
        'Potential Duplicate Items': '/reports?report=duplicate-item-analysis', 'Open Requisitions': '/procurement/pr',
        'Inactive Items': '/masters/items', 'Reorder Data Gaps': '/masters/items',
        'Employees Unavailable': '/employees/calendar-management', 'Unavailable Employees': '/warehouse/work-calendar',
    };
    const destination = destinations[label];
    return (_jsxs("button", { type: "button", disabled: !destination, onClick: () => destination && navigate(destination), title: destination ? `Open ${label} details` : undefined, className: `card group relative min-h-32 overflow-hidden bg-gradient-to-br from-white to-slate-50 p-4 text-left transition-all duration-200 hover:-translate-y-1 hover:shadow-lg ${destination ? 'cursor-pointer focus:outline-none focus:ring-2 focus:ring-cyan-400' : 'cursor-default'}`, children: [_jsx("div", { className: `absolute inset-x-0 top-0 h-1 bg-gradient-to-r ${tones[tone]}` }), _jsx("div", { className: `absolute -right-8 -top-8 h-24 w-24 rounded-full bg-gradient-to-br ${tones[tone]} opacity-[0.08] transition-transform group-hover:scale-125` }), _jsx("div", { className: "relative text-xs uppercase tracking-wide text-slate-500 font-semibold", children: label }), _jsx("div", { className: `relative text-2xl font-bold mt-2 ${accent || 'text-slate-900'}`, children: value }), helper ? _jsx("div", { className: "text-xs text-slate-500 mt-2", children: helper }) : null, destination ? _jsx("div", { className: "relative mt-2 text-[10px] font-semibold text-blue-600 opacity-0 transition-opacity group-hover:opacity-100", children: "Open details →" }) : null] }));
}
function StockRiskCard({ lowStock = 0, outOfStock = 0, onOpen }) {
    return _jsxs("button", { type: "button", onClick: onOpen, className: "stock-risk-card card group relative min-h-24 overflow-hidden p-3 text-left focus:outline-none focus:ring-2 focus:ring-amber-300", title: "Open real-time stock", children: [
        _jsx("div", { className: "absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-amber-500 to-red-500" }),
        _jsx("div", { className: "text-[10px] font-semibold uppercase tracking-wide text-slate-500", children: "Stock Risk" }),
        _jsxs("div", { className: "mt-2 flex items-end justify-between gap-2", children: [
            _jsxs("span", { children: [_jsx("strong", { className: "block text-xl text-amber-600", children: lowStock }), _jsx("small", { className: "text-[10px] text-slate-500", children: "Low Stock" })] }),
            _jsxs("span", { className: "text-right", children: [_jsx("strong", { className: "block text-xl text-red-600", children: outOfStock }), _jsx("small", { className: "text-[10px] text-slate-500", children: "Out of Stock" })] })
        ] }),
        _jsx("div", { className: "mt-1 text-[10px] font-semibold text-blue-600 opacity-0 transition-opacity group-hover:opacity-100", children: "Open details →" })
    ] });
}
function TrendChart({ data, title, colorClass }) {
    const [hovered, setHovered] = useState(null);
    const max = Math.max(...data.map((d) => d.value), 1);
    return (_jsxs("div", { className: "card p-5 bg-gradient-to-br from-white to-slate-50 transition-shadow hover:shadow-md", children: [_jsxs("div", { className: "mb-4 flex items-center justify-between", children: [_jsx("div", { className: "font-semibold text-slate-800", children: title }), _jsx("div", { className: "text-xs text-slate-400", children: "Hover for value" })] }), _jsx("div", { className: "flex items-end gap-2 h-44 border-b border-slate-200", children: data.map((item, index) => (_jsxs("div", { className: "relative flex h-full flex-1 flex-col items-center justify-end gap-2", onMouseEnter: () => setHovered(index), onMouseLeave: () => setHovered(null), children: [hovered === index && _jsx("div", { className: "absolute z-10 rounded-lg bg-slate-900 px-2.5 py-1.5 text-xs font-semibold text-white shadow-lg", style: { bottom: `${Math.max(18, (item.value / max) * 125) + 30}px` }, children: formatCurrency(item.value) }), _jsx("div", { className: `w-full max-w-10 rounded-t-md ${colorClass} transition-all duration-300 ${hovered === index ? 'brightness-110 shadow-lg scale-x-110' : 'opacity-85'}`, style: { height: `${Math.max(12, (item.value / max) * 125)}px` } }), _jsx("div", { className: "h-6 text-[10px] text-slate-500 text-center", children: item.label })] }, item.label))) })] }));
}
function DistributionBars({ rows, labelKey, valueKey, color = 'bg-blue-600' }) {
    const max = Math.max(...rows.map((row) => Number(row[valueKey] || 0)), 1);
    return _jsx("div", { className: "space-y-3", children: rows.length ? rows.map((row, index) => _jsxs("div", { className: "group", children: [_jsxs("div", { className: "mb-1 flex justify-between gap-3 text-xs", children: [_jsx("span", { className: "truncate font-medium text-slate-600 group-hover:text-slate-900", children: row[labelKey] }), _jsx("span", { className: "font-semibold text-slate-800", children: formatCurrency(row[valueKey]) })] }), _jsx("div", { className: "h-2.5 overflow-hidden rounded-full bg-slate-100", children: _jsx("div", { className: `h-full rounded-full ${color} transition-all duration-500 group-hover:brightness-110`, style: { width: `${Math.max(3, Number(row[valueKey] || 0) / max * 100)}%` } }) })] }, `${row[labelKey]}-${index}`)) : _jsx("div", { className: "text-sm text-slate-400", children: "No activity recorded." }) });
}
function PortfolioDonut({ rows }) {
    const [hovered, setHovered] = useState(null);
    const total = rows.reduce((sum, row) => sum + Number(row.total_value || 0), 0);
    const circumference = 251.2;
    const colors = ['#1677D8', '#12B8B0', '#14B866', '#6D5DFB', '#F59E0B', '#EF4444'];
    let offset = 0;
    const segments = rows.map((row, index) => { const fraction = total ? Number(row.total_value || 0) / total : 0; const segment = { ...row, index, dash: fraction * circumference, offset }; offset += segment.dash; return segment; });
    const selected = hovered == null ? null : segments[hovered];
    return _jsxs("div", { className: "flex flex-col items-center gap-5 sm:flex-row", children: [_jsxs("div", { className: "relative h-48 w-48 shrink-0", children: [_jsxs("svg", { viewBox: "0 0 100 100", className: "h-full w-full", children: [_jsx("circle", { cx: "50", cy: "50", r: "40", fill: "none", stroke: "#e2e8f0", strokeWidth: "12" }), segments.map((segment) => _jsx("circle", { cx: "50", cy: "50", r: "40", fill: "none", stroke: colors[segment.index % colors.length], strokeWidth: hovered === segment.index ? 15 : 12, strokeDasharray: `${segment.dash} ${circumference - segment.dash}`, strokeDashoffset: -segment.offset, strokeLinecap: "butt", transform: "rotate(-90 50 50)", className: "cursor-pointer transition-all", onMouseEnter: () => setHovered(segment.index), onMouseLeave: () => setHovered(null) }, segment.warehouse_name))] }), _jsxs("div", { className: "pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center", children: [_jsx("span", { className: "text-[10px] uppercase text-slate-400", children: selected ? 'Selected' : 'Inventory' }), _jsx("strong", { className: "max-w-28 text-sm text-slate-800", children: selected ? formatCurrency(selected.total_value) : formatCurrency(total) })] })] }), _jsx("div", { className: "w-full space-y-2", children: segments.map((segment) => _jsxs("div", { className: `flex cursor-pointer items-center justify-between rounded-lg px-2 py-1.5 text-xs transition-colors ${hovered === segment.index ? 'bg-slate-100' : 'hover:bg-slate-50'}`, onMouseEnter: () => setHovered(segment.index), onMouseLeave: () => setHovered(null), children: [_jsxs("span", { className: "flex items-center gap-2", children: [_jsx("i", { className: "h-2.5 w-2.5 rounded-full", style: { backgroundColor: colors[segment.index % colors.length] } }), segment.warehouse_name] }), _jsxs("strong", { children: [total ? (Number(segment.total_value) / total * 100).toFixed(1) : '0.0', "%"] })] }, segment.warehouse_name)) })] });
}
function RoleDashboard({ kpis, user, tasks, isProcurement, isLoading, lastUpdated, onRefresh, onOpenTask, period, warehouseId, warehouses, onPeriodChange, onWarehouseChange }) {
    const [expanded, setExpanded] = useState(false), profileLabel = isProcurement ? 'Procurement Operations Center' : 'Warehouse Operations Center', description = isProcurement ? 'Purchasing, sourcing, supplier, delivery and invoice intelligence for this procurement role.' : 'Inventory, receiving, issues and stock-control intelligence for the employee’s authorized warehouse scope.';
    return _jsxs("div", { className: "role-dashboard-summary", children: [_jsx(DashboardSummaryHeader, { kpis, period, warehouseId, warehouses, lastUpdated, onPeriodChange, onWarehouseChange, onRefresh, isLoading, heading:profileLabel, description, isExecutive:false, isProcurement, tasks }), _jsx("div", { className: "mb-6 rounded-2xl border border-cyan-200 bg-gradient-to-r from-cyan-50 via-white to-cyan-50 p-4 shadow-sm", children: _jsxs("div", { className: "flex flex-wrap items-center justify-between gap-3", children: [_jsxs("div", { children: [_jsx("div", { className: "text-xs font-semibold uppercase tracking-[.18em] text-blue-600", children: "Daily Action Center" }), _jsx("div", { className: "mt-1 text-lg font-bold text-slate-900", children: "My Task List" }), _jsx("div", { className: "text-xs text-slate-500", children: "Only work assigned to this role and authorized scope is displayed." })] }), _jsx("button", { className: "btn-primary", onClick: () => setExpanded(value => !value), children: expanded ? 'Close My Task List' : 'Open My Task List' })] }) }), expanded && _jsx("div", { className: "mb-6", children: _jsx(TaskList, { tasks: tasks, onOpen: onOpenTask, forceExpanded: true }) }), _jsxs("div", { className: "mb-6 flex items-end justify-between", children: [_jsxs("div", { children: [_jsx("h2", { className: "text-xl font-semibold text-slate-900", children: "Live KPI Snapshot" }), _jsx("p", { className: "text-sm text-slate-500", children: "Real-time, role-authorized operational indicators." })] }), _jsx("button", { className: "btn-secondary", disabled: isLoading, onClick: onRefresh, children: isLoading ? 'Refreshing...' : 'Refresh' })] }), _jsx("div", { className: "executive-kpi-grid grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6", children: isProcurement ? _jsxs(_Fragment, { children: [_jsx(KpiCard, { label: "Monthly Purchase", value: formatCurrency(kpis.monthly_purchase), tone: "special" }), _jsx(KpiCard, { label: "Open Requisitions", value: String(kpis.open_prs || 0), helper: `${kpis.pending_pr_approvals || 0} pending`, tone: "cyan" }), _jsx(KpiCard, { label: "Open Purchase Orders", value: String(kpis.open_pos || 0), helper: formatCurrency(kpis.outstanding_po_value || 0), tone: "blue" }), _jsx(KpiCard, { label: "Overdue POs", value: String(kpis.overdue_pos || 0), tone: "rose" }), _jsx(KpiCard, { label: "Active Suppliers", value: String(kpis.supplier_count || 0), tone: "cyan" }), _jsx(KpiCard, { label: "Invoice Exceptions", value: String(kpis.invoice_exceptions || 0), tone: "amber" })] }) : _jsxs(_Fragment, { children: [_jsx(KpiCard, { label: "Inventory Value", value: formatCurrency(kpis.total_inventory_value), helper: "Authorized warehouses", tone: "blue" }), _jsx(KpiCard, { label: "Monthly Consumption", value: formatCurrency(kpis.monthly_consumption), tone: "emerald" }), _jsx(KpiCard, { label: "Low Stock Items", value: String(kpis.low_stock_items || 0), tone: "amber" }), _jsx(KpiCard, { label: "Out of Stock", value: String(kpis.out_of_stock_items || 0), tone: "rose" }), _jsx(KpiCard, { label: "Reorder Data Gaps", value: String(kpis.items_missing_reorder_level || 0), tone: "amber" }), _jsx(KpiCard, { label: "Unavailable Employees", value: String(kpis.employees_unavailable_today || 0), tone: "special" })] }) }), _jsx("div", { className: "mt-6 grid gap-4 lg:grid-cols-2", children: isProcurement ? _jsxs(_Fragment, { children: [_jsx(TrendChart, { data: kpis.purchase_trend ?? [], title: "Purchase Trend", colorClass: "bg-blue-600" }), _jsx(StatusBars, { rows: kpis.po_status_distribution ?? [] }), _jsx(MiniBars, { title: "Invoice Match Control", subtitle: "Matched, pending and exception outcomes.", rows: kpis.invoice_match_trend ?? [], series: [{ key: 'matched', label: 'Matched', color: 'bg-emerald-500' }, { key: 'exceptions', label: 'Exceptions', color: 'bg-rose-500' }, { key: 'pending', label: 'Pending', color: 'bg-amber-500' }] })] }) : _jsxs(_Fragment, { children: [_jsx(TrendChart, { data: kpis.consumption_trend ?? [], title: "Consumption Trend", colorClass: "bg-emerald-500" }), _jsx(MiniBars, { title: "Stock Movement", subtitle: "Authorized warehouse inbound and outbound quantities.", rows: kpis.stock_movement_trend ?? [], series: [{ key: 'stock_in', label: 'Stock In', color: 'bg-emerald-500' }, { key: 'stock_out', label: 'Stock Out', color: 'bg-blue-600' }] }), _jsxs("div", { className: "card p-5", children: [_jsx("h2", { className: "mb-3 font-semibold", children: "Warehouse Inventory Portfolio" }), _jsx(PortfolioDonut, { rows: kpis.warehouse_values ?? [] })] }), _jsxs("div", { className: "card p-5", children: [_jsx("h2", { className: "mb-3 font-semibold", children: "Consumption by Department" }), _jsx(DistributionBars, { rows: kpis.department_consumption ?? [], labelKey: "department_name", valueKey: "total_value", color: "bg-emerald-500" })] })] }) })] });
}
function TaskList({ tasks, onOpen, forceExpanded = false, requestedGroup }) {
    const [expanded, setExpanded] = useState({});
    const groups = Array.from(tasks.reduce((map, task) => {
        const type = String(task.type || 'Other Tasks');
        map.set(type, [...(map.get(type) || []), task]);
        return map;
    }, new Map()).entries());
    useEffect(() => {
        if (!requestedGroup)
            return;
        setExpanded(current => ({ ...current, [requestedGroup.type]: true }));
    }, [requestedGroup?.requestId]);
    useEffect(() => { if (!forceExpanded)
        setExpanded({}); }, [forceExpanded]);
    const hasExpandedGroup = groups.some(([type]) => expanded[type]);
    const wide = forceExpanded || hasExpandedGroup;
    const priorityClass = (priority) => priority === 'Critical' ? 'bg-rose-100 text-rose-800' : priority === 'High' ? 'bg-amber-100 text-amber-800' : 'bg-sky-100 text-sky-800';
    return _jsxs("div", { id: "my-task-list", className: `card scroll-mt-4 flex flex-col overflow-hidden p-5 transition-all duration-300 ${wide ? 'h-[28rem] w-full' : 'h-[18rem] w-full lg:max-w-3xl'}`, children: [_jsxs("div", { className: "mb-3 flex shrink-0 items-center justify-between", children: [_jsxs("div", { children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsx("h2", { className: "font-medium text-slate-800", children: "My Task List" }), _jsx("span", { className: "h-2 w-2 animate-pulse rounded-full bg-rose-500" })] }), _jsx("p", { className: "text-xs text-slate-500", children: "Open a task group to expand the workspace. Select an entry to open it." })] }), _jsxs("span", { className: "rounded-full bg-cyan-50 px-3 py-1 text-xs font-semibold text-blue-700", children: [tasks.length, " open \u00B7 ", groups.length, " groups"] })] }), _jsx("div", { className: "min-h-0 flex-1 overflow-auto rounded-lg border border-slate-200", children: _jsxs("table", { className: "table-base", children: [_jsx("thead", { className: "sticky top-0 z-10 bg-slate-100 shadow-sm", children: _jsxs("tr", { children: [_jsx("th", { children: "Task" }), _jsx("th", { children: "Reference" }), _jsx("th", { children: "Priority" }), _jsx("th", { children: "Due / Date" })] }) }), _jsx("tbody", { children: groups.length ? groups.map(([type, group]) => _jsxs(React.Fragment, { children: [_jsx("tr", { className: "border-t border-cyan-100 bg-gradient-to-r from-cyan-50 to-sky-50", children: _jsx("td", { colSpan: 4, className: "p-0", children: _jsxs("button", { type: "button", className: "flex w-full items-center justify-between px-3 py-2 text-left", onClick: () => setExpanded(current => ({ ...current, [type]: !current[type] })), children: [_jsxs("span", { className: "flex items-center gap-2 font-semibold text-blue-900", children: [_jsx("span", { className: `text-xs transition-transform ${expanded[type] ? '' : 'rotate-[-90deg]'}`, children: "\u25BC" }), type] }), _jsx("span", { className: "rounded-full bg-white px-2.5 py-0.5 text-xs font-semibold text-blue-700 shadow-sm", children: group.length })] }) }) }), expanded[type] && group.map((task, index) => _jsxs("tr", { className: "cursor-pointer select-none hover:bg-cyan-50/50", title: "Open this task", tabIndex: 0, onClick: () => onOpen(task), onKeyDown: (event) => { if (event.key === 'Enter' || event.key === ' ') onOpen(task); }, children: [_jsx("td", { className: "text-xs text-slate-500", children: "Action required" }), _jsx("td", { className: "font-medium text-brand-700", children: task.number }), _jsx("td", { children: _jsx("span", { className: `rounded-full px-2 py-1 text-xs font-semibold ${priorityClass(task.priority)}`, children: task.priority }) }), _jsx("td", { children: task.due_date || '—' })] }, `${type}-${task.id}-${index}`))] }, type)) : _jsx("tr", { children: _jsx("td", { colSpan: 4, className: "text-center text-slate-400", children: "No open tasks" }) }) })] }) })] });
}
function PurchaseConsumptionTrend({ purchases = [], consumption = [] }) {
    const labels = Array.from(new Set([...purchases, ...consumption].map(row => row.label)));
    const purchaseMap = new Map(purchases.map(row => [row.label, Number(row.value || 0)]));
    const consumptionMap = new Map(consumption.map(row => [row.label, Number(row.value || 0)]));
    const maximum = Math.max(1, ...labels.flatMap(label => [purchaseMap.get(label) || 0, consumptionMap.get(label) || 0]));
    const purchaseTotal = purchases.reduce((sum, row) => sum + Number(row.value || 0), 0);
    const consumptionTotal = consumption.reduce((sum, row) => sum + Number(row.value || 0), 0);
    const net = purchaseTotal - consumptionTotal;
    return _jsxs("section", { className: "card p-4 xl:col-span-8", children: [
        _jsxs("div", { className: "mb-4 flex flex-wrap items-start justify-between gap-3", children: [
            _jsxs("div", { children: [_jsx("h2", { className: "font-semibold text-slate-800", children: "Purchase vs Consumption" }), _jsx("p", { className: "text-xs text-slate-500", children: "Monthly value comparison for management review." })] }),
            _jsxs("div", { className: "flex gap-3 text-xs", children: [_jsxs("span", { className: "flex items-center gap-1.5", children: [_jsx("i", { className: "h-2.5 w-2.5 rounded-full bg-blue-600" }), "Purchase"] }), _jsxs("span", { className: "flex items-center gap-1.5", children: [_jsx("i", { className: "h-2.5 w-2.5 rounded-full bg-emerald-500" }), "Consumption"] })] })
        ] }),
        _jsx("div", { className: "mb-3 grid grid-cols-3 gap-2", children: [
            ['Purchase', formatCurrency(purchaseTotal), 'text-blue-700'],
            ['Consumption', formatCurrency(consumptionTotal), 'text-emerald-700'],
            ['Net', `${net >= 0 ? '+' : ''}${formatCurrency(net)}`, net >= 0 ? 'text-blue-700' : 'text-amber-700']
        ].map(([label, value, color]) => _jsxs("div", { className: "rounded-lg border border-slate-200 bg-slate-50 px-3 py-2", children: [_jsx("div", { className: "text-[9px] font-semibold uppercase tracking-wide text-slate-500", children: label }), _jsx("div", { className: `mt-0.5 text-sm font-bold ${color}`, children: value })] }, label)) }),
        labels.length ? _jsx("div", { className: "flex h-44 items-end gap-2 border-b border-slate-200 px-1", children: labels.map(label => {
            const purchase = purchaseMap.get(label) || 0, used = consumptionMap.get(label) || 0;
            return _jsxs("div", { className: "flex h-full min-w-0 flex-1 flex-col items-center justify-end", children: [
                _jsxs("div", { className: "flex h-40 w-full items-end justify-center gap-1", children: [
                    _jsx("div", { className: "w-full max-w-5 rounded-t bg-blue-600", title: `Purchase: ${formatCurrency(purchase)}`, style: { height: `${Math.max(4, purchase / maximum * 145)}px` } }),
                    _jsx("div", { className: "w-full max-w-5 rounded-t bg-emerald-500", title: `Consumption: ${formatCurrency(used)}`, style: { height: `${Math.max(4, used / maximum * 145)}px` } })
                ] }),
                _jsx("span", { className: "mt-2 truncate text-[9px] text-slate-500", title: label, children: label })
            ] }, label);
        }) }) : _jsx("div", { className: "flex h-52 items-center justify-center text-sm text-slate-400", children: "No monthly trend data available." })
    ] });
}

function ExecutiveDashboard({ kpis, tasks, isLoading, lastUpdated, onRefresh, onOpenTask, onNavigate, period, warehouseId, warehouses, onPeriodChange, onWarehouseChange }) {
    const [showTasks, setShowTasks] = useState(false);
    const variance = Number(kpis.monthly_purchase || 0) - Number(kpis.monthly_consumption || 0);
    const invoiceTotal = Number(kpis.matched_invoices || 0) + Number(kpis.invoices_pending || 0) + Number(kpis.invoice_exceptions || 0);
    const invoiceMatchPercent = invoiceTotal ? Math.round(Number(kpis.matched_invoices || 0) / invoiceTotal * 100) : 0;
    const attention = [
        ['Pending Approvals', kpis.pending_approvals || 0, '/reports?report=approval-governance', 'text-amber-700'],
        ['Overdue Purchase Orders', kpis.overdue_pos || 0, '/procurement/po', 'text-red-600'],
        ['Low Stock Items', kpis.low_stock_items || 0, '/inventory/stock', 'text-amber-700'],
        ['Invoice Exceptions', kpis.invoice_exceptions || 0, '/procurement/invoices', 'text-red-600'],
    ];
    return _jsxs("div", { id: "executive-dashboard-summary", children: [
        _jsx(DashboardSummaryHeader, { kpis, period, warehouseId, warehouses, lastUpdated, onPeriodChange, onWarehouseChange, onRefresh, isLoading }),
        _jsx("section", { "aria-label": "Executive key performance indicators", className: "executive-kpi-grid grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6", children: [
            _jsx(KpiCard, { label: "Total Inventory Value", value: formatCurrency(kpis.total_inventory_value), tone: "blue" }),
            _jsx(KpiCard, { label: "Monthly Purchase", value: formatCurrency(kpis.monthly_purchase), tone: "special" }),
            _jsx(KpiCard, { label: "Monthly Consumption", value: formatCurrency(kpis.monthly_consumption), tone: "emerald" }),
            _jsx(KpiCard, { label: "Outstanding PO Value", value: formatCurrency(kpis.outstanding_po_value || 0), tone: "blue" }),
            _jsx(KpiCard, { label: "Pending Approvals", value: String(kpis.pending_approvals || 0), tone: "amber" }),
            _jsx(StockRiskCard, { lowStock: kpis.low_stock_items || 0, outOfStock: kpis.out_of_stock_items || 0, onOpen: () => onNavigate('/inventory/stock') })
        ] }),
        _jsx("section", { "aria-label": "Secondary management indicators", className: "mt-2.5 grid grid-cols-2 overflow-hidden rounded-xl border border-slate-200 bg-white sm:grid-cols-4", children: [
            ['Open POs', kpis.open_pos || 0, '/procurement/po'],
            ['Open PRs', kpis.open_prs || 0, '/procurement/pr'],
            ['Open Replenishment Checks', kpis.open_replenishment_checks || 0, '/warehouse/replenishment'],
            ['Supplier Score', `${kpis.avg_supplier_rating || 0} / 5`, '/advanced/vendor-scorecard']
        ].map(([label, value, path]) => _jsxs("button", { type: "button", onClick: () => onNavigate(path), className: "border-b border-slate-100 px-3 py-2 text-left transition hover:bg-cyan-50 focus:outline-none focus:ring-2 focus:ring-blue-200 sm:border-b-0 sm:border-r last:border-r-0", children: [_jsx("span", { className: "block text-[9px] font-semibold uppercase tracking-wide text-slate-500", children: label }), _jsx("strong", { className: "mt-0.5 block text-base text-slate-900", children: value })] }, label)) }),
        _jsxs("div", { className: "mt-3 grid grid-cols-1 gap-3 xl:grid-cols-12", children: [
            _jsx(PurchaseConsumptionTrend, { purchases: kpis.purchase_trend || [], consumption: kpis.consumption_trend || [] }),
            _jsxs("section", { className: "card p-4 xl:col-span-4", children: [_jsxs("div", { className: "mb-2 flex items-center justify-between gap-2", children: [_jsxs("div", { children: [_jsx("h2", { className: "font-semibold text-slate-800", children: "Needs Attention" }), _jsxs("p", { className: "text-xs text-slate-500", children: [tasks.length, " assigned tasks"] })] }), _jsx("button", { type: "button", className: "btn-secondary px-2.5 py-1 text-[10px]", onClick: () => setShowTasks(value => !value), children: showTasks ? 'Hide Tasks' : 'View All My Tasks' })] }), _jsx("div", { className: "divide-y divide-slate-100", children: attention.map(([label, count, path, color]) => _jsxs("button", { type: "button", className: "flex w-full items-center justify-between gap-3 py-2 text-left hover:text-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-200", onClick: () => onNavigate(path), children: [_jsx("span", { className: "text-xs text-slate-700", children: label }), _jsxs("span", { className: `text-xs font-bold ${color}`, children: [count, " · Open"] })] }, label)) })] })
        ] }),
        _jsxs("div", { className: "mt-3 grid grid-cols-1 gap-3 xl:grid-cols-12", children: [
            _jsxs("section", { className: "card p-4 xl:col-span-5", children: [_jsx("h2", { className: "font-semibold text-slate-800", children: "Inventory Value by Warehouse" }), _jsx("p", { className: "mb-2 text-xs text-slate-500", children: "Company-wide inventory concentration with visible values." }), _jsx(PortfolioDonut, { rows: kpis.warehouse_values || [] })] }),
            _jsxs("section", { className: "card p-4 xl:col-span-7", children: [_jsx("h2", { className: "font-semibold text-slate-800", children: "Procurement & Financial Health" }), _jsx("p", { className: "mb-3 text-xs text-slate-500", children: "Commitments, monthly balance, delivery exceptions, and invoice matching." }), _jsx("div", { className: "grid grid-cols-1 gap-x-5 sm:grid-cols-2", children: [
                ['Outstanding Commitments', formatCurrency(kpis.outstanding_po_value || 0), 'text-blue-700', 'Approved and printed POs'],
                ['Purchase vs Consumption', `${variance >= 0 ? '+' : ''}${formatCurrency(variance)}`, variance >= 0 ? 'text-blue-700' : 'text-amber-700', 'Current month variance'],
                ['PO Delivery Exceptions', `${kpis.overdue_pos || 0} overdue`, Number(kpis.overdue_pos) ? 'text-red-600' : 'text-emerald-700', 'On-time percentage requires backend KPI'],
                ['Invoice Match Health', `${invoiceMatchPercent}% matched`, Number(kpis.invoice_exceptions) ? 'text-amber-700' : 'text-emerald-700', `${kpis.invoice_exceptions || 0} exceptions · ${kpis.invoices_pending || 0} pending`]
            ].map(([label, value, color, helper]) => _jsxs("div", { className: "border-b border-slate-100 py-2.5", children: [_jsx("div", { className: "text-[10px] font-semibold uppercase tracking-wide text-slate-500", children: label }), _jsx("div", { className: `mt-0.5 text-base font-bold ${color}`, children: value }), _jsx("div", { className: "text-[10px] text-slate-500", children: helper })] }, label)) })] })
        ] }),
        showTasks ? _jsx("div", { className: "mt-4", children: _jsx(TaskList, { tasks, onOpen: onOpenTask, forceExpanded: true }) }) : null
    ] });
}

 export default function Dashboard() {
    const navigate = useNavigate();
    const { user } = useAuth();
    const [kpis, setKpis] = useState(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState(null);
    const [lastUpdated, setLastUpdated] = useState(null);
    const [tasks, setTasks] = useState([]);
    const [period, setPeriod] = useState('this_month');
    const [warehouseId, setWarehouseId] = useState('all');
    const [warehouses, setWarehouses] = useState([]);
    const profile = kpis?.dashboard_profile || (user?.role === 'SupplyChainManager' ? 'executive' : ['PurchaseManager', 'PurchaseOfficer'].includes(user?.role || '') ? 'procurement' : 'warehouse');
    const isExecutive = profile === 'executive', isProcurement = profile === 'procurement';
    const loadKpis = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const res = await client.get('/dashboard/kpis', { params: { period, warehouse_id: warehouseId } });
            setKpis(res.data);
            setLastUpdated(new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }));
        }
        catch (err) {
            setError('Unable to load KPI data right now. Please try again in a moment.');
            setKpis(null);
        }
        finally {
            setIsLoading(false);
        }
    };
    const loadTasks = () => client.get('/dashboard/tasks').then((taskRes) => setTasks(taskRes.data)).catch(() => setTasks([]));
    const refreshDashboard = () => Promise.all([loadKpis(), loadTasks()]);
    useAutoRefresh(refreshDashboard);
    useEffect(() => {
        loadKpis();
        const intervalId = window.setInterval(loadKpis, 30000);
        return () => window.clearInterval(intervalId);
    }, [period, warehouseId]);
    useEffect(() => {
        loadTasks();
    }, []);
    useEffect(() => {
        client.get('/masters/warehouses').then(({ data }) => setWarehouses(data.filter(warehouse => warehouse.active_yn !== 0 && (user?.role==='SupplyChainManager' || user?.warehouse_ids?.includes(warehouse.id))))).catch(() => setWarehouses([]));
    }, [user?.role]);
    function openTask(task) {
        const destinations = {
            'PO approval': `/procurement/po?open=${task.id}`,
            'PR review': `/procurement/pr?open=${task.id}`,
            'PR warehouse review': `/procurement/pr?open=${task.id}`,
            'PO delivery overdue': `/procurement/po?open=${task.id}`,
            'Issue approval': `/warehouse/issue?open=${task.id}`,
            'Adjustment approval': `/warehouse/adjustments?open=${task.id}`,
            'Cycle count approval': `/inventory/cycle-count?open=${task.id}`,
            'Low stock': `/inventory/stock?item=${task.id}`,
            'Expiry approaching': `/inventory/expiry?layer=${task.id}`,
            'Month-end database backup required': '/masters/settings',
            'Workday calendar publication due': '/employees/calendar-management',
            'Duplicate items pending review': '/reports?report=duplicate-item-analysis', 'Employee coverage gap': '/reports?report=shift-coverage', 'Three-way match exception': '/procurement/invoices',
            'RFQ closing': '/procurement/rfq', 'RFQ award approval': '/procurement/rfq',
        };
        const destination = destinations[task.type];
        if (destination)
            navigate(destination);
    }
    if (isLoading && !kpis)
        return _jsx("div", { className: "card p-6 text-sm text-slate-500", role: "status", children: "Loading dashboard data…" });
    if (error || !kpis)
        return _jsxs("div", { className: "card border-red-200 p-6", role: "alert", children: [_jsx("h1", { className: "text-lg font-semibold text-red-700", children: "Dashboard data is unavailable" }), _jsx("p", { className: "mt-1 text-sm text-slate-600", children: error || "No dashboard data was returned." }), _jsx("button", { type: "button", className: "btn-primary mt-4", onClick: loadKpis, children: "Try Again" })] });
    if (kpis && !isExecutive)
        return _jsx(RoleDashboard, { kpis: kpis, user: user, tasks: tasks, isProcurement: isProcurement, isLoading: isLoading, lastUpdated: lastUpdated, onRefresh: loadKpis, onOpenTask: openTask, period, warehouseId, warehouses, onPeriodChange:setPeriod, onWarehouseChange:setWarehouseId });
    return _jsx(ExecutiveDashboard, { kpis, tasks, isLoading, lastUpdated, onRefresh: loadKpis, onOpenTask: openTask, onNavigate: navigate, period, warehouseId, warehouses, onPeriodChange: setPeriod, onWarehouseChange: setWarehouseId });
}

function DashboardSummaryHeader({ kpis, period, warehouseId, warehouses, lastUpdated, onPeriodChange, onWarehouseChange, onRefresh, isLoading, heading='Executive Supply Chain View', description='Management overview of supply-chain health and exceptions.', isExecutive=true, isProcurement=false, tasks=[] }) {
  return _jsxs("header", { className: "executive-summary-header mb-5 flex flex-col gap-4 border-b border-slate-200 pb-4 lg:flex-row lg:items-center lg:justify-between", children: [
            _jsxs("div", { className: "flex min-w-0 items-center gap-3", children: [kpis.company_logo_url ? _jsx("img", { src: kpis.company_logo_url, alt: `${kpis.company_name || 'Company'} logo`, className: "h-12 w-12 shrink-0 object-contain" }) : _jsx("div", { className: "flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-blue-600 to-cyan-500 text-sm font-bold text-white", "aria-hidden": "true", children: "PF" }), _jsxs("div", { className: "min-w-0", children: [_jsx("div", { className: "text-[10px] font-semibold uppercase tracking-[.18em] text-cyan-700", children: heading }), _jsx("h1", { className: "mt-0.5 truncate text-xl font-bold text-slate-900", children: kpis.company_name || 'Procuraflo' }), _jsx("p", { className: "mt-0.5 text-xs text-slate-500", children: description })] })] }),
            _jsxs("div", { className: "flex flex-wrap items-center gap-2 text-xs", children: [
                _jsxs("select", {"data-field": "period",  "aria-label": "Dashboard period", className: "input h-9 min-h-0 w-auto py-1 text-xs", value: period, onChange: event => onPeriodChange(event.target.value), children: [_jsx("option", { value: "this_month", children: "This Month" }), _jsx("option", { value: "last_month", children: "Last Month" }), _jsx("option", { value: "this_quarter", children: "This Quarter" }), _jsx("option", { value: "this_year", children: "This Year" })] }),
                _jsxs("select", {"data-field": "warehouseId",  "aria-label": "Warehouse scope", className: "input h-9 min-h-0 w-auto py-1 text-xs", value: warehouseId, onChange: event => onWarehouseChange(event.target.value), children: [_jsx("option", { value: "all", children: isExecutive ? "All Warehouses" : "Authorized Warehouses" }), ...warehouses.map(warehouse => _jsx("option", { value: String(warehouse.id), children: warehouse.name }, warehouse.id))] }),
                _jsxs("span", { className: "rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-600", children: [new Date().toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }), " · Updated ", lastUpdated || '—'] }),
                _jsxs("span", { className: "rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 font-semibold text-amber-800", children: [(isExecutive ? kpis.pending_approvals : isProcurement ? kpis.pending_pr_approvals : tasks.length) || 0, isExecutive ? " approvals" : isProcurement ? " PR approvals" : " tasks"] }),
                _jsxs("span", { className: "rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 font-semibold text-red-700", children: [(isProcurement ? kpis.invoice_exceptions : kpis.low_stock_items) || 0, isProcurement ? " invoice exceptions" : " stock alerts"] }),
                _jsx("button", { type: "button", className: "btn-secondary px-3 py-2 text-xs", onClick: onRefresh, disabled: isLoading, children: isLoading ? 'Refreshing…' : 'Refresh' })
            ] })
        ] });
}
