import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from 'react';
import { formatCurrencyAmount, getStoredCurrency } from '../utils/currency';
export default function CurrencyInput({ currency = getStoredCurrency(), className = '', value, onChange, onFocus, onBlur, ...props }) {
    const [focused, setFocused] = useState(false);
    const code = String(currency || getStoredCurrency()).toUpperCase();
    const empty = value == null || value === '';
    const displayed = empty ? '' : focused ? String(value) : formatCurrencyAmount(value);
    return _jsxs("div", { className: "relative mt-1", children: [_jsx("span", { className: "pointer-events-none absolute inset-y-0 left-0 flex min-w-14 items-center justify-center rounded-l-lg border-r border-slate-200 bg-slate-100 px-2 text-xs font-bold text-slate-600", children: code }), _jsx("input", {"data-field": "displayed",  ...props, type: "text", inputMode: "decimal", value: displayed, className: `input pl-16 text-right tabular-nums ${className}`, onFocus: (event) => { setFocused(true); onFocus?.(event); }, onBlur: (event) => { setFocused(false); onBlur?.(event); }, onChange: (event) => {
                    const cleaned = event.currentTarget.value.replace(/[^0-9.-]/g, '');
                    event.currentTarget.value = cleaned;
                    onChange?.(event);
                } })] });
}
