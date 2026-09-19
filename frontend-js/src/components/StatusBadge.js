import { jsx as _jsx } from "react/jsx-runtime";
const COLORS = {
    Draft: 'bg-slate-100 text-slate-600',
    Submitted: 'bg-blue-100 text-blue-700',
    PendingApproval: 'bg-amber-100 text-amber-700',
    Approved: 'bg-emerald-100 text-emerald-700',
    'Partially Received': 'bg-amber-100 text-amber-800',
    Printed: 'bg-blue-100 text-blue-700',
    Rejected: 'bg-rose-100 text-rose-700',
    Closed: 'bg-slate-200 text-slate-600',
    Pending: 'bg-amber-100 text-amber-700',
    Open: 'bg-blue-100 text-blue-700',
    Counted: 'bg-blue-100 text-blue-700',
    Active: 'bg-emerald-100 text-emerald-700',
    Inactive: 'bg-slate-100 text-slate-500',
    'Clear for HR Processing': 'bg-emerald-100 text-emerald-800',
    'Not Clear': 'bg-rose-100 text-rose-800',
    'Partially Clear': 'bg-amber-100 text-amber-800',
    Cancelled: 'bg-slate-200 text-slate-700',
};
export default function StatusBadge({ status }) {
    const cls = COLORS[status] || 'bg-slate-100 text-slate-600';
    return _jsx("span", { className: `px-2 py-0.5 rounded-full text-xs font-medium ${cls}`, children: status });
}
