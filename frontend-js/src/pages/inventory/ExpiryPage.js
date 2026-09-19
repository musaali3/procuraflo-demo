import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import client from '../../api/client';
import DataTable from '../../components/DataTable';
import useAutoRefresh from '../../hooks/useAutoRefresh';
const ALERT_COLORS = {
    Expired: 'bg-rose-100 text-rose-700',
    '30-day': 'bg-amber-100 text-amber-700',
    '60-day': 'bg-yellow-100 text-yellow-700',
};
export default function ExpiryPage() {
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const load = () => {
        setLoading(true);
        client
            .get('/inventory/expiry')
            .then((res) => setRows(res.data))
            .finally(() => setLoading(false));
    };
    useAutoRefresh(load);
    useEffect(() => { load(); }, []);
    return (_jsxs("div", { children: [_jsx("h1", { className: "text-xl font-semibold text-slate-900 mb-1", children: "Expiry Tracking" }), _jsx("p", { className: "text-sm text-slate-500 mb-4", children: "Batches with expiry dates, with 30-day / 60-day / expired alerts." }), _jsx("div", { className: "card", children: _jsx(DataTable, { loading: loading, columns: [
                        { key: 'item_code', label: 'Item Code' },
                        { key: 'description', label: 'Description' },
                        { key: 'batch', label: 'Batch' },
                        { key: 'expiry_date', label: 'Expiry Date' },
                        { key: 'quantity_remaining', label: 'Qty Remaining' },
                        { key: 'days_remaining', label: 'Days Remaining' },
                        {
                            key: 'alert',
                            label: 'Alert',
                            render: (r) => r.alert ? (_jsx("span", { className: `px-2 py-0.5 rounded-full text-xs font-medium ${ALERT_COLORS[r.alert]}`, children: r.alert })) : ('—'),
                        },
                    ], rows: rows }) })] }));
}
