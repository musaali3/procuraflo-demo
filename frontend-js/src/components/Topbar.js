import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { ROLE_LABELS } from '../types';
import Modal from './Modal';
import client from '../api/client';
import { useBranding } from '../contexts/BrandingContext';
import { CompanyLogo } from './Branding';
export default function Topbar() {
    const { company, product } = useBranding();
    const { user, logout } = useAuth();
    const [showPassword, setShowPassword] = useState(false);
    const [passwords, setPasswords] = useState({ current_password: '', new_password: '' });
    const [error, setError] = useState('Enter your current password, then choose a different new password with at least 8 characters. Use a private passphrase that is difficult to guess. You will be signed out after the change and must log in with the new password.');
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
    return (_jsxs("header", { className: "app-topbar h-16 bg-white border-b border-slate-200 flex items-center justify-between px-6 sticky top-0 z-10", children: [_jsxs("div", { className: "flex min-w-0 items-center gap-2", children: [_jsx(CompanyLogo, { company: company, size: "nav" }), _jsxs("div", { className: "truncate text-sm", children: [_jsx("span", { className: "font-semibold text-slate-800", children: company.company_name }), _jsx("span", { className: "mx-2 text-slate-300", children: "|" }), _jsx("span", { className: "font-semibold text-primary", children: product.name })] })] }), _jsxs("div", { className: "flex items-center gap-4", children: [(user?.must_change_password || (user?.password_days_remaining != null && user.password_days_remaining <= 7)) && _jsx("button", { className: "rounded-lg bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700", onClick: () => setShowPassword(true), children: user.must_change_password ? 'Change default password' : `Password expires in ${user.password_days_remaining} days` }), _jsxs("div", { className: "text-right", children: [_jsx("div", { className: "text-sm font-medium text-slate-800", children: user?.full_name }), _jsx("div", { className: "text-xs text-slate-500", children: user ? ROLE_LABELS[user.role] : '' })] }), _jsx("div", { className: "w-9 h-9 rounded-full bg-brand-500 text-white flex items-center justify-center font-semibold text-sm", children: user?.full_name?.charAt(0) }), _jsx("button", { onClick: logout, className: "btn-secondary text-xs px-3 py-1.5", children: "Logout" })] }), showPassword && _jsx(Modal, { title: "Change Password", onClose: () => setShowPassword(false), children: _jsxs("div", { className: "space-y-3", children: [_jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium", children: "Current Password" }), _jsx("input", {"data-field": "current_password",  className: "input mt-1", type: "password", placeholder: "Enter current password", value: passwords.current_password, onChange: (e) => setPasswords({ ...passwords, current_password: e.target.value }) })] }), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium", children: "New Password" }), _jsx("input", {"data-field": "new_password",  className: "input mt-1", type: "password", placeholder: "Minimum 8 characters", value: passwords.new_password, onChange: (e) => setPasswords({ ...passwords, new_password: e.target.value }) })] }), error && _jsx("div", {"data-error-message": true, role: "alert",  className: "text-sm text-rose-600", children: error }), _jsx("div", { className: "flex justify-end", children: _jsx("button", { className: "btn-primary", onClick: changePassword, children: "Change Password" }) })] }) })] }));
}
