import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
export default function SearchSelect({ label, options, value, onChange, placeholder, onSearch, disabled = false, portalMenu = false, "data-field": fieldName }) {
    const [query, setQuery] = useState(''), [open, setOpen] = useState(false);
    const inputRef = useRef(null);
    const menuRef = useRef(null);
    const [menuPosition, setMenuPosition] = useState(null);
    const selectedLabel = options.find(option => String(option.value) === String(value))?.label || '';
    // Synchronize only when the external selection changes. Parent forms often
    // rebuild the options array while typing; that must never erase the query.
    useEffect(() => { setQuery(selectedLabel); }, [value, selectedLabel]);
    const normalized = query.trim().toLocaleLowerCase();
    const filtered = options.filter(option => !normalized || option.label.toLocaleLowerCase().includes(normalized)).slice(0, 100);
    useLayoutEffect(() => {
        if (!portalMenu || !open) return;
        const updatePosition = () => {
            const rect = inputRef.current?.getBoundingClientRect();
            if (!rect) return;
            const roomBelow = window.innerHeight - rect.bottom - 8;
            const roomAbove = rect.top - 8;
            const above = roomBelow < 180 && roomAbove > roomBelow;
            const maxHeight = Math.min(256, Math.max(80, (above ? roomAbove : roomBelow) - 4));
            const left = Math.max(8, Math.min(rect.left, window.innerWidth - 88));
            setMenuPosition({ position: 'fixed', left, ...(above ? { bottom: window.innerHeight - rect.top + 4 } : { top: rect.bottom + 4 }), width: Math.min(rect.width, window.innerWidth - left - 8), maxHeight, zIndex: 1100 });
        };
        updatePosition();
        window.addEventListener('scroll', updatePosition, true);
        window.addEventListener('resize', updatePosition);
        return () => { window.removeEventListener('scroll', updatePosition, true); window.removeEventListener('resize', updatePosition); };
    }, [open, portalMenu]);
    useEffect(() => {
        if (!portalMenu || !open) return;
        const closeOutside = event => {
            if (event.target !== inputRef.current && !menuRef.current?.contains(event.target)) setOpen(false);
        };
        document.addEventListener('pointerdown', closeOutside);
        document.addEventListener('focusin', closeOutside);
        return () => { document.removeEventListener('pointerdown', closeOutside); document.removeEventListener('focusin', closeOutside); };
    }, [open, portalMenu]);
    const menu = open && _jsx("div", { ref: menuRef, className: `search-select-menu ${portalMenu ? 'fixed' : 'absolute mt-1 w-full max-h-64'} z-30 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg`, style: portalMenu ? menuPosition || { display: 'none' } : undefined, children: filtered.length ? filtered.map(option => _jsx("button", { type: "button", className: "block w-full px-3 py-2 text-left text-sm hover:bg-blue-50 focus:bg-blue-50", onMouseDown: event => { event.preventDefault(); setQuery(option.label); onChange(option.value); setOpen(false); }, children: option.label }, option.value)) : _jsx("div", { className: "px-3 py-2 text-sm text-slate-500", children: "No matching results" }) });
    return _jsxs("div", { className: "relative", children: [label && _jsx("label", { className: "text-sm font-medium text-slate-700", children: label }), _jsx("input", {ref: inputRef, "data-field": fieldName,  className: "input mt-1 w-full", type: "search", disabled, "aria-label": label || placeholder, autoComplete: "off", placeholder: placeholder, value: query, onChange: event => { const next = event.target.value; setQuery(next); setOpen(true); onSearch?.(next); if (!next)
                    onChange(''); }, onFocus: () => setOpen(true), onKeyDown: event => { if (event.key === 'Enter' && filtered.length) {
                    event.preventDefault();
                    setQuery(filtered[0].label);
                    onChange(filtered[0].value);
                    setOpen(false);
                } if (event.key === 'Escape')
                    setOpen(false); }, onBlur: () => { if (!portalMenu) window.setTimeout(() => setOpen(false), 150); } }), portalMenu && open ? createPortal(menu, document.body) : menu] });
}
