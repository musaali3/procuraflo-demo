import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import client from '../../api/client';
import DataTable from '../../components/DataTable';
import Modal from '../../components/Modal';
import { formatCurrency } from '../../utils/currency';
import useAutoRefresh from '../../hooks/useAutoRefresh';
export default function ValuationPage() {
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const [layers, setLayers] = useState(null);
    const [layerItem, setLayerItem] = useState(null);
    const load = () => {
        setLoading(true);
        client
            .get('/inventory/valuation')
            .then((res) => setRows(res.data))
            .finally(() => setLoading(false));
    };
    useAutoRefresh(load);
    useEffect(() => { load(); }, []);
    function openLayers(row) {
        setLayerItem(row);
        client.get(`/inventory/valuation/${row.item_id}/layers`).then((res) => setLayers(res.data));
    }
    const totalValue = rows.reduce((s, r) => s + r.value, 0);
    return (_jsxs("div", { children: [_jsxs("div", { className: "flex items-center justify-between mb-1", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-xl font-semibold text-slate-900", children: "FIFO Inventory Valuation" }), _jsx("p", { className: "text-sm text-slate-500", children: "First-In-First-Out cost layers determine on-hand inventory value." })] }), _jsxs("div", { className: "text-right", children: [_jsx("div", { className: "text-xs text-slate-500 uppercase", children: "Total Inventory Value" }), _jsx("div", { className: "text-xl font-bold text-slate-900", children: formatCurrency(totalValue) })] })] }), _jsx("div", { className: "card mt-4", children: _jsx(DataTable, { loading: loading, columns: [
                        { key: 'item_code', label: 'Item Code' },
                        { key: 'description', label: 'Description' },
                        { key: 'quantity', label: 'On Hand Qty' },
                        { key: 'avg_unit_cost', label: 'Avg Unit Cost', render: (r) => formatCurrency(r.avg_unit_cost) },
                        { key: 'value', label: 'Total Value', render: (r) => formatCurrency(r.value) },
                    ], rows: rows, onRowClick: openLayers }) }), layerItem && layers && (_jsxs(Modal, { title: `FIFO Cost Layers — ${layerItem.item_code}`, onClose: () => setLayerItem(null), wide: true, children: [_jsxs("div", { className: "mb-3 text-sm text-slate-600", children: ["Total: ", layers.totalQty, " units, ", formatCurrency(layers.totalValue)] }), _jsx(DataTable, { columns: [
                            { key: 'received_date', label: 'Received Date' },
                            { key: 'batch', label: 'Batch' },
                            { key: 'quantity_remaining', label: 'Qty Remaining' },
                            { key: 'unit_cost', label: 'Unit Cost', render: (r) => formatCurrency(r.unit_cost) },
                            { key: 'layer_value', label: 'Layer Value', render: (r) => formatCurrency(r.quantity_remaining * r.unit_cost) },
                        ], rows: layers.layers })] }))] }));
}
