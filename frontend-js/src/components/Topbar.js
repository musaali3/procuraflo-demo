import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { ROLE_LABELS } from '../types';
import Modal from './Modal';
import client from '../api/client';
import { useBranding } from '../contexts/BrandingContext';
import { ProductBrand } from './Branding';

const SEARCH_PAGES = [
    { label: 'Dashboard', type: 'Page', path: '/', keywords: 'overview kpi tasks' },
    { label: 'Items', type: 'Master Data', path: '/masters/items', keywords: 'item catalog stock uom material' },
    { label: 'Suppliers', type: 'Master Data', path: '/masters/suppliers', keywords: 'vendor supplier payment terms' },
    { label: 'Warehouses & Locations', type: 'Master Data', path: '/masters/warehouses', keywords: 'warehouse bin location storage' },
    { label: 'Employee Master', type: 'Administration', path: '/masters/employees', roles: ['SupplyChainManager', 'PurchaseManager', 'WarehouseManager'], keywords: 'employee user role access' },
    { label: 'Purchase Requisitions', type: 'Procurement', path: '/procurement/pr', keywords: 'pr request requisition approval' },
    { label: 'RFQ & Quotations', type: 'Procurement', path: '/procurement/rfq', roles: ['SupplyChainManager', 'PurchaseManager', 'PurchaseOfficer'], keywords: 'rfq quotation sourcing supplier' },
    { label: 'Purchase Orders', type: 'Procurement', path: '/procurement/po', roles: ['SupplyChainManager', 'PurchaseManager', 'PurchaseOfficer'], keywords: 'po order supplier purchase' },
    { label: 'Goods Receipt (GRN)', type: 'Warehouse', path: '/warehouse/grn', keywords: 'grn receipt receiving delivery note' },
    { label: 'Inspection & Put-Away', type: 'Warehouse', path: '/warehouse/receiving-control', keywords: 'inspection receiving put away' },
    { label: 'Material Issue', type: 'Warehouse', path: '/warehouse/issue', keywords: 'issue material gin employee' },
    { label: 'Returns', type: 'Warehouse', path: '/warehouse/returns', keywords: 'return employee item' },
    { label: 'Transfers', type: 'Warehouse', path: '/warehouse/transfers', keywords: 'transfer warehouse stock' },
    { label: 'Real-Time Stock', type: 'Inventory', path: '/inventory/stock', keywords: 'inventory stock quantity available' },
    { label: 'Reports', type: 'Reports', path: '/reports', keywords: 'report export pdf excel' },
    { label: 'Help Center', type: 'Help', path: '/help?department=Getting%20Started', keywords: 'help guide how to' },
];
const SEARCH_ENDPOINTS = [
    { endpoint: '/masters/items', path: '/masters/items', type: 'Item', roles: null, title: row => [row.item_code, row.description].filter(Boolean).join(' - '), detail: row => [row.category, row.uom].filter(Boolean).join(' · ') },
    { endpoint: '/masters/suppliers', path: '/masters/suppliers', type: 'Supplier', roles: ['SupplyChainManager', 'PurchaseManager', 'PurchaseOfficer'], title: row => [row.supplier_code, row.name].filter(Boolean).join(' - '), detail: row => [row.contact_person, row.payment_terms].filter(Boolean).join(' · ') },
    { endpoint: '/procurement/prs', path: row => `/procurement/pr?open=${row.id}`, type: 'Purchase Requisition', roles: null, title: row => row.pr_number, detail: row => [row.status, row.requestor_name, row.department_name].filter(Boolean).join(' · ') },
    { endpoint: '/procurement/pos', path: row => `/procurement/po?open=${row.id}`, type: 'Purchase Order', roles: null, title: row => row.po_number, detail: row => [row.status, row.supplier_name, row.delivery_warehouse_name].filter(Boolean).join(' · ') },
    { endpoint: '/warehouse/grns', path: '/warehouse/grn', type: 'GRN', roles: ['SupplyChainManager', 'WarehouseManager', 'WarehouseSupervisor', 'Storekeeper'], title: row => row.grn_number, detail: row => [row.po_number, row.supplier_name, row.status].filter(Boolean).join(' · ') },
];
function includesRole(entry, role) {
    return !entry.roles || entry.roles.includes(role);
}
function haystackFor(...values) {
    return values.filter(value => value != null).join(' ').toLowerCase();
}
function matchesNeedle(needle, ...values) {
    return haystackFor(...values).includes(needle);
}

export default function Topbar() {
    const { user, logout } = useAuth();
    const location = useLocation();
    const navigate = useNavigate();
    const [showPassword, setShowPassword] = useState(false);
    const [showNotifications, setShowNotifications] = useState(false);
    const [showAccountMenu, setShowAccountMenu] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [recordResults, setRecordResults] = useState([]);
    const [searchOpen, setSearchOpen] = useState(false);
    const [searchLoading, setSearchLoading] = useState(false);
    const notificationsRef = useRef(null);
    const accountMenuRef = useRef(null);
    const searchRef = useRef(null);
    const [passwords, setPasswords] = useState({ current_password: '', new_password: '' });
    const [error, setError] = useState('Enter your current password, then choose a different new password with at least 8 characters. Use a private passphrase that is difficult to guess. You will be signed out after the change and must log in with the new password.');
    useEffect(() => {
        const closeMenus = event => {
            const target = event.target;
            if (!(target instanceof Node)) return;
            if (notificationsRef.current?.contains(target) || accountMenuRef.current?.contains(target) || searchRef.current?.contains(target)) return;
            setShowNotifications(false);
            setShowAccountMenu(false);
            setSearchOpen(false);
        };
        const closeOnEscape = event => {
            if (event.key !== 'Escape') return;
            setShowNotifications(false);
            setShowAccountMenu(false);
            setSearchOpen(false);
        };
        document.addEventListener('pointerdown', closeMenus);
        document.addEventListener('focusin', closeMenus);
        document.addEventListener('keydown', closeOnEscape);
        return () => {
            document.removeEventListener('pointerdown', closeMenus);
            document.removeEventListener('focusin', closeMenus);
            document.removeEventListener('keydown', closeOnEscape);
        };
    }, []);
    useEffect(() => {
        setShowNotifications(false);
        setShowAccountMenu(false);
        setSearchOpen(false);
    }, [location.pathname]);
    const pageResults = useMemo(() => {
        const needle = searchQuery.trim().toLowerCase();
        if (!needle) return [];
        return SEARCH_PAGES
            .filter(entry => includesRole(entry, user?.role))
            .filter(entry => matchesNeedle(needle, entry.label, entry.type, entry.keywords, entry.path))
            .slice(0, 5)
            .map(entry => ({ ...entry, source: 'page' }));
    }, [searchQuery, user?.role]);
    const searchResults = useMemo(() => [...pageResults, ...recordResults].slice(0, 8), [pageResults, recordResults]);
    useEffect(() => {
        const needle = searchQuery.trim().toLowerCase();
        if (needle.length < 2 || !user) {
            setRecordResults([]);
            setSearchLoading(false);
            return;
        }
        let cancelled = false;
        setSearchLoading(true);
        const timer = setTimeout(() => {
            const endpoints = SEARCH_ENDPOINTS.filter(entry => includesRole(entry, user.role));
            Promise.allSettled(endpoints.map(entry => client.get(entry.endpoint, { skipAutoRefresh: true }).then(response => ({ entry, rows: response.data || [] }))))
                .then(results => {
                    if (cancelled) return;
                    const next = [];
                    results.forEach(result => {
                        if (result.status !== 'fulfilled') return;
                        const { entry, rows } = result.value;
                        rows.filter(row => matchesNeedle(needle, entry.title(row), entry.detail(row), row.status, row.item_code, row.description, row.name, row.supplier_name, row.po_number, row.pr_number, row.grn_number))
                            .slice(0, 4)
                            .forEach(row => next.push({
                                source: 'record',
                                type: entry.type,
                                label: entry.title(row),
                                detail: entry.detail(row),
                                path: typeof entry.path === 'function' ? entry.path(row) : entry.path,
                            }));
                    });
                    setRecordResults(next.slice(0, 8));
                    setSearchLoading(false);
                })
                .catch(() => {
                    if (!cancelled) {
                        setRecordResults([]);
                        setSearchLoading(false);
                    }
                });
        }, 250);
        return () => {
            cancelled = true;
            clearTimeout(timer);
        };
    }, [searchQuery, user]);
    function openSearchResult(result) {
        if (!result?.path) return;
        navigate(result.path);
        setSearchQuery('');
        setRecordResults([]);
        setSearchOpen(false);
    }
    function handleSearchKeyDown(event) {
        if (event.key === 'Escape') {
            setSearchOpen(false);
            return;
        }
        if (event.key !== 'Enter') return;
        const first = searchResults[0];
        if (!first) return;
        event.preventDefault();
        openSearchResult(first);
    }
    async function changePassword() {
        if (!passwords.current_password) {
            setError('Enter your current password before choosing a new password.');
            return;
        }
        if (passwords.new_password.length < 8) {
            setError('The new password must contain at least 8 characters.');
            return;
        }
        if (passwords.current_password === passwords.new_password) {
            setError('The new password must be different from your current password.');
            return;
        }
        try {
            await client.put('/auth/change-password', passwords);
            alert('Password changed. Please log in again.');
            logout();
        }
        catch (e) {
            setError(e?.response?.data?.error || 'Password change failed');
        }
    }
    return (_jsxs("header", { className: "app-topbar sticky top-0 z-10 flex h-16 items-center justify-between gap-4 border-b border-slate-200 bg-white px-6", children: [
        _jsx("div", { className: "topbar-left flex min-w-0 items-center gap-5", children: _jsx("div", { className: "topbar-product-logo shrink-0", children: _jsx(ProductBrand, { compact: true, inverse: true }) }) }),
        _jsxs("div", { ref: searchRef, className: "topbar-search relative hidden min-w-[18rem] max-w-xl flex-1 items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm shadow-sm lg:flex", children: [
            _jsx("span", { className: "topbar-search-icon", "aria-hidden": "true" }),
            _jsx("input", { "aria-label": "Search items, purchase orders and suppliers", className: "min-w-0 flex-1 border-0 bg-transparent text-sm text-slate-700 outline-none placeholder:text-slate-400", placeholder: "Search items, POs, suppliers...", value: searchQuery, onFocus: () => setSearchOpen(true), onChange: event => { setSearchQuery(event.target.value); setSearchOpen(true); }, onKeyDown: handleSearchKeyDown }),
            searchQuery && _jsx("button", { type: "button", className: "topbar-search-clear", "aria-label": "Clear search", onClick: () => { setSearchQuery(''); setRecordResults([]); setSearchOpen(false); }, children: "x" }),
            searchOpen && searchQuery.trim() && _jsxs("div", { className: "topbar-search-results", role: "listbox", children: [
                searchResults.length ? searchResults.map((result, index) => _jsxs("button", { type: "button", className: "topbar-search-result", role: "option", onMouseDown: event => { event.preventDefault(); openSearchResult(result); }, children: [
                    _jsxs("span", { className: "min-w-0", children: [
                        _jsx("span", { className: "block truncate text-sm font-semibold", children: result.label }),
                        result.detail && _jsx("span", { className: "block truncate text-xs text-slate-500", children: result.detail })
                    ] }),
                    _jsx("span", { className: "topbar-search-result-type", children: result.type })
                ] }, `${result.source}-${result.path}-${index}`)) : _jsx("div", { className: "px-3 py-3 text-sm text-slate-500", children: searchLoading ? "Searching..." : "No matching pages or records." }),
                searchLoading && searchResults.length > 0 && _jsx("div", { className: "border-t border-slate-100 px-3 py-2 text-xs text-slate-400", children: "Checking records..." })
            ] })
        ] }),
        _jsxs("div", { className: "flex shrink-0 items-center gap-4", children: [
            (user?.must_change_password || (user?.password_days_remaining != null && user.password_days_remaining <= 7)) && _jsx("button", { className: "rounded-full bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700", onClick: () => setShowPassword(true), children: user.must_change_password ? 'Change default password' : `Password expires in ${user.password_days_remaining} days` }),
            _jsxs("div", { ref: notificationsRef, className: "topbar-notification-wrap relative", children: [
                _jsxs("button", { type: "button", className: "topbar-alert relative flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 bg-white text-blue-700 shadow-sm", "aria-label": "Notifications", "aria-expanded": showNotifications, onClick: () => { setShowAccountMenu(false); setShowNotifications((value) => !value); }, children: [
                    _jsx("svg", { viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false", children: _jsx("path", { d: "M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22Zm7-6h-1.4V10a5.6 5.6 0 0 0-4.1-5.4V3a1.5 1.5 0 0 0-3 0v1.6A5.6 5.6 0 0 0 6.4 10v6H5a1 1 0 0 0 0 2h14a1 1 0 0 0 0-2Zm-3.4 0H8.4V10a3.6 3.6 0 1 1 7.2 0v6Z" }) }),
                    _jsx("span", { className: "absolute right-2 top-2 h-2 w-2 rounded-full bg-blue-600" })
                ] }),
                showNotifications && _jsxs("div", { className: "topbar-notification-panel", role: "status", children: [
                    _jsx("div", { className: "text-sm font-semibold", children: "Notifications" }),
                    _jsx("div", { className: "mt-1 text-xs", children: "No new system alerts right now." }),
                    (user?.password_days_remaining != null && user.password_days_remaining <= 7) && _jsx("button", { type: "button", className: "mt-3 text-xs font-semibold", onClick: () => { setShowNotifications(false); setShowPassword(true); }, children: "Review password status" })
                ] })
            ] }),
            _jsxs("div", { ref: accountMenuRef, className: "topbar-account-wrap relative", children: [
                _jsxs("button", { type: "button", className: "topbar-account-button", "aria-label": "Open account menu", "aria-expanded": showAccountMenu, onClick: () => { setShowNotifications(false); setShowAccountMenu(value => !value); }, children: [
                    _jsxs("span", { className: "hidden text-right sm:block", children: [
                        _jsx("span", { className: "block text-sm font-semibold text-slate-950", children: user?.full_name }),
                        _jsx("span", { className: "block text-xs text-slate-500", children: user ? ROLE_LABELS[user.role] : '' })
                    ] }),
                    _jsx("span", { className: "flex h-11 w-11 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white shadow-lg shadow-blue-600/20", children: user?.full_name?.charAt(0) })
                ] }),
                showAccountMenu && _jsxs("div", { className: "topbar-account-menu", role: "menu", children: [
                    _jsx("button", { type: "button", role: "menuitem", className: "topbar-account-menu-item", onClick: () => { setShowAccountMenu(false); setShowPassword(true); }, children: "Change Password" }),
                    _jsx("button", { type: "button", role: "menuitem", className: "topbar-account-menu-item topbar-account-menu-item-danger", onClick: () => { setShowAccountMenu(false); logout(); }, children: "Logout" })
                ] })
            ] })
        ] }),
        showPassword && _jsx(Modal, { title: "Change Password", onClose: () => setShowPassword(false), children: _jsxs("div", { className: "space-y-3", children: [
            _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium", children: "Current Password" }), _jsx("input", { "data-field": "current_password", className: "input mt-1", type: "password", placeholder: "Enter current password", value: passwords.current_password, onChange: (e) => setPasswords({ ...passwords, current_password: e.target.value }) })] }),
            _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium", children: "New Password" }), _jsx("input", { "data-field": "new_password", className: "input mt-1", type: "password", placeholder: "Minimum 8 characters", value: passwords.new_password, onChange: (e) => setPasswords({ ...passwords, new_password: e.target.value }) })] }),
            error && _jsx("div", { "data-error-message": true, role: "alert", className: "text-sm text-rose-600", children: error }),
            _jsx("div", { className: "flex justify-end", children: _jsx("button", { className: "btn-primary", onClick: changePassword, children: "Change Password" }) })
        ] }) })
    ] }));
}
