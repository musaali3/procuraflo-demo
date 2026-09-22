import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { ROLE_LABELS } from '../types';
import Modal from './Modal';
import client from '../api/client';
import { useBranding } from '../contexts/BrandingContext';

const LABELS = {
    masters: 'Master Data',
    procurement: 'Supply Chain',
    warehouse: 'Warehouse',
    inventory: 'Inventory',
    advanced: 'Advanced',
    reports: 'Reports',
    employees: 'Administration',
    delegated: 'Administration',
};

function titleCase(value) {
    return String(value || '')
        .replace(/-/g, ' ')
        .replace(/\b\w/g, character => character.toUpperCase());
}

export default function Topbar() {
    const { company, product } = useBranding();
    const { user, logout } = useAuth();
    const location = useLocation();
    const [showPassword, setShowPassword] = useState(false);
    const [passwords, setPasswords] = useState({ current_password: '', new_password: '' });
    const [error, setError] = useState('Enter your current password, then choose a different new password with at least 8 characters. Use a private passphrase that is difficult to guess. You will be signed out after the change and must log in with the new password.');
    const crumbs = useMemo(() => {
        if (location.pathname === '/') return [company.company_name || 'Workspace', product.name];
        const parts = location.pathname.split('/').filter(Boolean);
        const first = LABELS[parts[0]] || titleCase(parts[0]);
        const current = titleCase(parts[parts.length - 1]);
        return [first, current];
    }, [company.company_name, location.pathname, product.name]);
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
        _jsxs("nav", { className: "topbar-breadcrumb flex min-w-0 items-center gap-2 text-sm", "aria-label": "Breadcrumb", children: [
            _jsx("span", { className: "truncate font-semibold text-slate-600", children: crumbs[0] }),
            _jsx("span", { className: "text-slate-300", children: ">" }),
            _jsx("span", { className: "truncate font-semibold text-blue-600", children: crumbs[1] })
        ] }),
        _jsxs("div", { className: "topbar-search hidden min-w-[18rem] max-w-xl flex-1 items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm shadow-sm lg:flex", children: [
            _jsx("span", { className: "topbar-search-icon", "aria-hidden": "true" }),
            _jsx("input", { "aria-label": "Search items, purchase orders and suppliers", className: "min-w-0 flex-1 border-0 bg-transparent text-sm text-slate-700 outline-none placeholder:text-slate-400", placeholder: "Search items, POs, suppliers..." })
        ] }),
        _jsxs("div", { className: "flex shrink-0 items-center gap-4", children: [
            (user?.must_change_password || (user?.password_days_remaining != null && user.password_days_remaining <= 7)) && _jsx("button", { className: "rounded-full bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700", onClick: () => setShowPassword(true), children: user.must_change_password ? 'Change default password' : `Password expires in ${user.password_days_remaining} days` }),
            _jsxs("button", { type: "button", className: "topbar-alert relative flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 bg-white text-blue-700 shadow-sm", "aria-label": "Notifications", children: [
                _jsx("span", { "aria-hidden": "true", children: "!" }),
                _jsx("span", { className: "absolute right-2 top-2 h-2 w-2 rounded-full bg-blue-600" })
            ] }),
            _jsxs("div", { className: "hidden text-right sm:block", children: [
                _jsx("div", { className: "text-sm font-semibold text-slate-950", children: user?.full_name }),
                _jsx("div", { className: "text-xs text-slate-500", children: user ? ROLE_LABELS[user.role] : '' })
            ] }),
            _jsx("div", { className: "flex h-11 w-11 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white shadow-lg shadow-blue-600/20", children: user?.full_name?.charAt(0) }),
            _jsx("button", { onClick: logout, className: "btn-secondary px-3 py-1.5 text-xs", children: "Logout" })
        ] }),
        showPassword && _jsx(Modal, { title: "Change Password", onClose: () => setShowPassword(false), children: _jsxs("div", { className: "space-y-3", children: [
            _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium", children: "Current Password" }), _jsx("input", { "data-field": "current_password", className: "input mt-1", type: "password", placeholder: "Enter current password", value: passwords.current_password, onChange: (e) => setPasswords({ ...passwords, current_password: e.target.value }) })] }),
            _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium", children: "New Password" }), _jsx("input", { "data-field": "new_password", className: "input mt-1", type: "password", placeholder: "Minimum 8 characters", value: passwords.new_password, onChange: (e) => setPasswords({ ...passwords, new_password: e.target.value }) })] }),
            error && _jsx("div", { "data-error-message": true, role: "alert", className: "text-sm text-rose-600", children: error }),
            _jsx("div", { className: "flex justify-end", children: _jsx("button", { className: "btn-primary", onClick: changePassword, children: "Change Password" }) })
        ] }) })
    ] }));
}
