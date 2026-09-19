import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import client from '../../api/client';
import DataTable from '../../components/DataTable';
import { formatCurrency } from '../../utils/currency';
import useAutoRefresh from '../../hooks/useAutoRefresh';
const CLASS_COLORS = {
    A: 'bg-rose-100 text-rose-700',
    B: 'bg-amber-100 text-amber-700',
    C: 'bg-emerald-100 text-emerald-700',
};
export default function ABCPage() {
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const load = () => {
        setLoading(true);
        client
            .get('/inventory/abc-classification')
            .then((res) => setRows(res.data))
            .finally(() => setLoading(false));
    };
    useAutoRefresh(load);
    useEffect(() => { load(); }, []);
    return (_jsxs("div", { children: [_jsx("h1", { className: "text-xl font-semibold text-slate-900 mb-1", children: "ABC Inventory Classification" }), _jsx("p", { className: "text-sm text-slate-500 mb-4", children: "A = high-value items (top 80% of cumulative value), B = medium-value (next 15%), C = low-value / high quantity (remaining 5%)." }), _jsx("div", { className: "card", children: _jsx(DataTable, { loading: loading, columns: [
                        { key: 'item_code', label: 'Item Code' },
                        { key: 'description', label: 'Description' },
                        { key: 'value', label: 'Inventory Value', render: (r) => formatCurrency(r.value) },
                        { key: 'cumulative_pct', label: 'Cumulative %', render: (r) => `${r.cumulative_pct}%` },
                        {
                            key: 'classification',
                            label: 'Class',
                            render: (r) => (_jsx("span", { className: `px-2 py-0.5 rounded-full text-xs font-bold ${CLASS_COLORS[r.classification]}`, children: r.classification })),
                        },
                    ], rows: rows }) })] }));
}
