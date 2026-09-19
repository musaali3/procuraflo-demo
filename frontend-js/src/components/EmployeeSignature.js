import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import client from '../api/client';
export default function EmployeeSignature({ src, name, className = 'h-12 max-w-36' }) { const [url, setUrl] = useState(''); useEffect(() => { let active = true, object = ''; if (!src) {
    setUrl('');
    return;
} client.get(src, { responseType: 'blob', validateStatus: status => (status>=200 && status<300) || status===404 }).then(r => { if(r.status===404){if(active)setUrl('');return;} object = URL.createObjectURL(r.data); if (active)
    setUrl(object); }).catch(() => setUrl('')); return () => { active = false; if (object)
    URL.revokeObjectURL(object); }; }, [src]); return url ? _jsx("img", { src: url, alt: `${name || 'Employee'} signature`, className: `${className} object-contain` }) : null; }
const formatSystemTimestamp = (value) => { if (!value)
    return 'Pending action'; const raw = String(value); const normalized = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(raw) ? `${raw.replace(' ', 'T')}Z` : raw; const parsed = new Date(normalized); return Number.isNaN(parsed.getTime()) ? raw : parsed.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium' }); };
export function ResponsibleSignature({ label, name, src, date, lookupByName = true, missingDateLabel = 'Pending action' }) { const signatureSource = src || (lookupByName && name ? `/masters/employee-signature-by-name?name=${encodeURIComponent(name)}` : ''); return _jsxs("div", { className: "print-avoid-break flex min-h-24 flex-col items-center justify-end border-t border-slate-500 pt-1", "data-signature-required": name ? "true" : "false", "data-signature-name": name || '', children: [_jsx(EmployeeSignature, { src: signatureSource, name: name, className: "employee-signature-image mb-1 h-11 max-w-32" }), _jsx("div", { children: label }), _jsx("strong", { children: name || 'Name / Signature / Date' }), _jsx("span", { className: "mt-0.5 text-[9px] text-slate-500", children: date ? formatSystemTimestamp(date) : missingDateLabel })] }); }
