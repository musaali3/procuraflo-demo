import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import client from '../../api/client';
import DataTable from '../../components/DataTable';
import useAutoRefresh from '../../hooks/useAutoRefresh';
export default function DeadStockPage() {
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const load = () => {
        setLoading(true);
        client
            .get('/inventory/dead-stock')
            .then((res) => setRows(res.data))
            .finally(() => setLoading(false));
    };
    useAutoRefresh(load);
    useEffect(() => { load(); }, []);
    return (_jsxs("div", { children: [_jsx("h1", { className: "text-xl font-semibold text-slate-900 mb-1", children: "Dead Stock Analysis" }), _jsx("p", { className: "text-sm text-slate-500 mb-4", children: "Items with no movement (GRN, issue, or transfer) for 90+, 180+, or 365+ days." }), _jsx("div", { className: "card", children: _jsx(DataTable, { loading: loading, emptyLabel: "No dead stock detected", columns: [
                        { key: 'item_code', label: 'Item Code' },
                        { key: 'description', label: 'Description' },
                        { key: 'quantity', label: 'On Hand Qty' },
                        { key: 'last_movement', label: 'Last Movement', render: (r) => r.last_movement || 'Never' },
                        { key: 'days_since_movement', label: 'Days Idle', render: (r) => r.days_since_movement ?? '—' },
                        { key: 'bucket', label: 'Bucket' },
                    ], rows: rows }) })] }));
}
