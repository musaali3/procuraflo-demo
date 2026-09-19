import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import MasterDataPage from './MasterDataPage';
import client from '../../api/client';
import { useAuth } from '../../contexts/AuthContext';
export default function SuppliersPage() {
    const { user } = useAuth();
    const [paymentTerms, setPaymentTerms] = useState([]);
    const [paymentTermsText, setPaymentTermsText] = useState('');
    const [saved, setSaved] = useState(false);
    const [reference, setReference] = useState({ countries: [], currencies: [] });
    useEffect(() => {
        client.get('/settings').then((res) => {
            const configured = String(res.data.global_payment_terms || 'Due on Receipt, Net 15, Net 30, Net 45, Net 60, Net 90');
            setPaymentTermsText(configured);
            setPaymentTerms(configured.split(',').map((term) => term.trim()).filter(Boolean).map((term) => ({ value: term, label: term })));
        });
        client.get('/workforce/reference').then(res => setReference(res.data)).catch(() => undefined);
    }, []);
    async function saveTerms() { await client.put('/settings/global_payment_terms', { value: paymentTermsText }); setPaymentTerms(paymentTermsText.split(',').map((term) => term.trim()).filter(Boolean).map((term) => ({ value: term, label: term }))); setSaved(true); setTimeout(() => setSaved(false), 2000); }
    return (_jsxs("div", { className: "space-y-4", children: [user && ['SupplyChainManager', 'PurchaseManager'].includes(user.role) && _jsxs("div", { className: "card p-4", children: [_jsx("h2", { className: "font-semibold text-blue-900", children: "Supplier Configuration" }), _jsx("p", { className: "text-xs text-slate-500 mt-1", children: "Payment terms available on supplier records and purchase orders. Enter comma-separated values." }), _jsx("label", { className: "block text-sm font-medium mt-3 mb-1", children: "Available Supplier Payment Terms" }), _jsxs("div", { className: "flex gap-2", children: [_jsx("input", {"data-field": "paymentTermsText",  className: "input", value: paymentTermsText, onChange: (e) => setPaymentTermsText(e.target.value) }), _jsx("button", { className: "btn-secondary shrink-0", onClick: saveTerms, children: "Save Terms" })] }), saved && _jsx("div", { className: "text-xs text-emerald-600 mt-2", children: "Payment terms saved." })] }), _jsx(MasterDataPage, { title: "Suppliers", description: "Vendor master with contact details, payment terms, and rating.", endpoint: "/masters/suppliers", columns: [
                    { key: 'supplier_code', label: 'Code' },
                    { key: 'name', label: 'Name' },
                    { key: 'contact_person', label: 'Contact' },
                    { key: 'phone', label: 'Phone' },
                    { key: 'payment_terms', label: 'Payment Terms' },
                    { key: 'country_code', label: 'Country' },
                    { key: 'preferred_currency', label: 'Preferred Currency' },
                    { key: 'rating', label: 'Rating' },
                ], fields: [
                    { key: 'supplier_code', label: 'Supplier Code (generated on save)', readOnly: true },
                    { key: 'name', label: 'Supplier Name' },
                    { key: 'contact_person', label: 'Contact Person' },
                    { key: 'phone', label: 'Phone' },
                    { key: 'email', label: 'Email' },
                    { key: 'address', label: 'Address' },
                    { key: 'payment_terms', label: 'Payment Terms', type: 'select', options: paymentTerms },
                    { key: 'country_code', label: 'Country', type: 'select', options: reference.countries.map((c) => ({ value: c.country_code, label: c.country_name })) },
                    { key: 'preferred_currency', label: 'Preferred Currency', type: 'select', options: reference.currencies.map((c) => ({ value: c.currency_code, label: `${c.currency_code} — ${c.currency_name}` })) },
                    { key: 'rating', label: 'Performance Rating (automatic: quality 45%, quantity 25%, on-time delivery 30%)', type: 'number', readOnly: true },
                ] })] }));
}
