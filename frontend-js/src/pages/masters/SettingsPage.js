import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import client from '../../api/client';
import { currencyFieldLabel, DEFAULT_COMPANY_CURRENCY, setStoredCurrency } from '../../utils/currency';
import CurrencyInput from '../../components/CurrencyInput';
import { useBranding } from '../../contexts/BrandingContext';
import { normalizeCompanyLogo } from '../../utils/companyLogo';
import { CompanyLogo } from '../../components/Branding';
const APPROVAL_ROLES = [
    { role: 'SupplyChainManager', label: 'Supply Chain Manager', key: 'approval_limit_supply_chain_manager' },
    { role: 'PurchaseManager', label: 'Purchase Manager', key: 'approval_limit_purchase_manager' },
    { role: 'PurchaseOfficer', label: 'Purchase Officer', key: 'approval_limit_purchase_officer' },
    { role: 'WarehouseManager', label: 'Warehouse Manager', key: 'approval_limit_warehouse_manager' },
    { role: 'WarehouseSupervisor', label: 'Warehouse Supervisor', key: 'approval_limit_warehouse_supervisor' },
    { role: 'Storekeeper', label: 'Storekeeper', key: 'approval_limit_storekeeper' },
];
export default function SettingsPage() {
    const { refresh: refreshBranding } = useBranding();
    const [company, setCompany] = useState({ name: '', address: '', phone: '', email: '', website: '', registration_number: '', branch_info: '', tax_info: '', currency: DEFAULT_COMPANY_CURRENCY, base_currency: DEFAULT_COMPANY_CURRENCY, country_code: 'SA', time_zone: 'Asia/Riyadh', financial_year: '', installation_id: '', licensed_company_name: '', license_locked: false, license_locked_at: '', logo_url: '' });
    const [reference, setReference] = useState({ countries: [], cities: [], currencies: [] });
    const [logoFile, setLogoFile] = useState(null);
    const [logoPreview, setLogoPreview] = useState('');
    const [saved, setSaved] = useState(false);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState('');
    const [limits, setLimits] = useState({});
    const [uploading, setUploading] = useState(false);
    const [users, setUsers] = useState([]);
    const [restoreFile, setRestoreFile] = useState(null);
    const [nextFinancialYear, setNextFinancialYear] = useState('');
    const [message, setMessage] = useState('');
    const [showReset, setShowReset] = useState(false);
    const [resetPassword, setResetPassword] = useState('');
    const [resetPhrase, setResetPhrase] = useState('');
    const [resetAcknowledged, setResetAcknowledged] = useState(false);
    const [resetting, setResetting] = useState(false);
    const [resetError, setResetError] = useState('');
    const [showAccounts, setShowAccounts] = useState(false);
    const [backupPolicy,setBackupPolicy]=useState({automatic_month_end_backup:'1',backup_time:'16:00',backup_time_zone:'Asia/Riyadh',backup_warning_minutes:'30',backup_reminder_minutes:'10'});
    const [timeZones,setTimeZones]=useState([]);
    useEffect(() => {
        client.get('/settings').then((res) => {
            Object.entries(res.data).forEach(([key, value]) => {
                if (key.startsWith('approval_limit_')) {
                    setLimits((prev) => ({ ...prev, [key]: String(value ?? '') }));
                }
            });
        });
        client.get('/settings/company').then((res) => {
            setCompany(res.data || {});
            if (res.data?.base_currency || res.data?.currency)
                setStoredCurrency(res.data.base_currency || res.data.currency);
        });
        client.get('/auth/users').then((res) => setUsers(res.data)).catch(() => undefined);
        client.get('/workforce/reference').then(res => setReference(res.data)).catch(() => undefined);
        client.get('/settings/backup-policy').then(res=>setBackupPolicy(res.data)).catch(()=>undefined);
        client.get('/masters/time-zones').then(res=>setTimeZones(res.data)).catch(()=>undefined);
    }, []);
    useEffect(() => {
        if (!logoFile) {
            setLogoPreview('');
            return;
        }
        const preview = URL.createObjectURL(logoFile);
        setLogoPreview(preview);
        return () => URL.revokeObjectURL(preview);
    }, [logoFile]);
    async function save() {
        setSaving(true);
        setSaved(false);
        setSaveError('');
        try {
            await client.put('/settings/company', company);
            await Promise.all(APPROVAL_ROLES.map(({ key }) => client.put(`/settings/${key}`, { value: limits[key] || '0' })));
            if (logoFile && !(await uploadLogo()))
                return;
            setStoredCurrency(company.base_currency || company.currency || DEFAULT_COMPANY_CURRENCY);
            await refreshBranding();
            setSaved(true);
            setMessage('All editable system settings were saved successfully.');
            setTimeout(() => setSaved(false), 3000);
        }
        catch (error) {
            setSaveError(error?.response?.data?.error || 'Unable to save all settings. Please review the fields and try again.');
        }
        finally {
            setSaving(false);
        }
    }
    async function uploadLogo() {
        if (!logoFile)
            return false;
        const form = new FormData();
        setUploading(true);
        setSaveError('');
        try {
            const normalizedLogo = await normalizeCompanyLogo(logoFile);
            form.append('logo', normalizedLogo);
            // Let the browser add the required multipart boundary.
            const res = await client.post('/settings/company-logo', form);
            setCompany((prev) => ({ ...prev, logo_url: res.data.logo_url }));
            setLogoFile(null);
            await refreshBranding();
            setMessage('Company logo was cleaned, cropped, standardized, and applied throughout Procuraflo.');
            return true;
        }
        catch (error) {
            setSaveError(error?.response?.data?.error || error?.message || 'Unable to prepare and upload the company logo.');
            return false;
        }
        finally {
            setUploading(false);
        }
    }
    async function downloadBackup() {
        const res = await client.post('/settings/backup', {}, { responseType: 'blob' });
        const url = URL.createObjectURL(res.data);
        const a = document.createElement('a');
        a.href = url;
        a.download = `procuraflo-backup-${new Date().toISOString().slice(0, 10)}.db`;
        a.click();
        URL.revokeObjectURL(url);
        setMessage('Backup created and downloaded.');
    }
    async function saveBackupPolicy(){try{const res=await client.put('/settings/backup-policy',backupPolicy);setBackupPolicy(res.data);setMessage('Automatic month-end backup policy saved.');}catch(error){setSaveError(error.response?.data?.error||'Unable to save backup policy');}}
    async function stageRestore() {
        if (!restoreFile || !confirm('Validate and stage this backup for restoration? Existing data is not changed until the backend is restarted with the staged restore path.'))
            return;
        const body = new FormData();
        body.append('backup', restoreFile);
        const res = await client.post('/settings/restore', body, { headers: { 'Content-Type': 'multipart/form-data' } });
        setMessage(res.data.message);
    }
    async function closeFiscalYear() {
        if (!nextFinancialYear || !confirm('Close the current fiscal year? A database backup will be created before the year changes.'))
            return;
        const res = await client.post('/settings/fiscal-close', { next_financial_year: nextFinancialYear });
        setCompany({ ...company, financial_year: res.data.financial_year });
        setMessage(`Fiscal year changed. Backup: ${res.data.backup_file}`);
    }
    async function unlockUser(id) {
        await client.put(`/auth/users/${id}/unlock`);
        const res = await client.get('/auth/users');
        setUsers(res.data);
        setMessage('Account restored. The user must change the password within 7 days.');
    }
    async function factoryReset() {
        if (!resetAcknowledged || resetPhrase !== 'RESET PROCURAFLO' || !resetPassword)
            return;
        if (!confirm('FINAL WARNING: Reset all Procuraflo company, master, transaction, report, audit, and uploaded-document data?'))
            return;
        setResetting(true);
        setResetError('');
        try {
            const res = await client.post('/settings/factory-reset', {
                current_password: resetPassword,
                confirmation_phrase: resetPhrase,
                acknowledge_permanent_deletion: resetAcknowledged,
            });
            setCompany({ name: 'New Company', address: '', phone: '', email: '', website: '', registration_number: '', branch_info: '', tax_info: '', currency: DEFAULT_COMPANY_CURRENCY, financial_year: '', installation_id: '', licensed_company_name: '', license_locked: false, license_locked_at: '', logo_url: '' });
            setStoredCurrency(DEFAULT_COMPANY_CURRENCY);
            setUsers((current) => current.filter((entry) => entry.username === res.data.retained_admin));
            setLimits({});
            setShowReset(false);
            setResetPassword('');
            setResetPhrase('');
            setResetAcknowledged(false);
            setMessage(`Factory reset completed. Recovery backup: ${res.data.recovery_backup}. Your administrator login was retained.`);
        }
        catch (error) {
            setResetError(error?.response?.data?.error || 'Factory reset failed. No further action should be taken until the database is checked.');
        }
        finally {
            setResetting(false);
        }
    }
    return (_jsxs("div", { children: [_jsx("h1", { className: "text-xl font-semibold text-slate-900 mb-1", children: "System Settings" }), _jsx("p", { className: "text-sm text-slate-500 mb-4", children: "Administration controls for company details, approval thresholds, and role limits." }), _jsxs("div", { className: "grid lg:grid-cols-2 gap-6", children: [_jsxs("div", { className: "card p-5 space-y-4", children: [company.license_locked && _jsxs("div", { className: "rounded-xl border border-emerald-200 bg-emerald-50 p-3", children: [_jsx("div", { className: "text-sm font-semibold text-emerald-900", children: "Single-company installation active" }), _jsxs("div", { className: "mt-1 text-xs text-emerald-700", children: ["This deployment is permanently licensed to ", _jsx("strong", { children: company.licensed_company_name || company.name }), ". Company identity and cross-company restore controls are enforced by the server."] }), company.installation_id && _jsxs("div", { className: "mt-2 font-mono text-[10px] text-emerald-600", children: ["Installation ID: ", company.installation_id] })] }), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Company Name" }), _jsx("input", {"data-field": "name",  className: `input mt-1 ${company.license_locked ? 'bg-slate-100' : ''}`, readOnly: company.license_locked, value: company.name ?? '', onChange: (e) => setCompany({ ...company, name: e.target.value }) }), company.license_locked && _jsx("p", { className: "mt-1 text-xs text-slate-500", children: "Locked by the Procuraflo installation license." })] }), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Address" }), _jsx("input", {"data-field": "address",  className: "input mt-1", value: company.address ?? '', onChange: (e) => setCompany({ ...company, address: e.target.value }) })] }), _jsxs("div", { className: "grid gap-3 sm:grid-cols-2", children: [_jsxs("label", { className: "text-sm font-medium text-slate-700", children: ["Telephone", _jsx("input", {"data-field": "phone",  className: "input mt-1", value: company.phone ?? '', onChange: e => setCompany({ ...company, phone: e.target.value }) })] }), _jsxs("label", { className: "text-sm font-medium text-slate-700", children: ["Email", _jsx("input", {"data-field": "email",  type: "email", className: "input mt-1", value: company.email ?? '', onChange: e => setCompany({ ...company, email: e.target.value }) })] }), _jsxs("label", { className: "text-sm font-medium text-slate-700", children: ["Website", _jsx("input", {"data-field": "website",  className: "input mt-1", placeholder: "https://", value: company.website ?? '', onChange: e => setCompany({ ...company, website: e.target.value }) })] }), _jsxs("label", { className: "text-sm font-medium text-slate-700", children: ["Registration Number", _jsx("input", {"data-field": "registration_number",  className: "input mt-1", value: company.registration_number ?? '', onChange: e => setCompany({ ...company, registration_number: e.target.value }) })] })] }), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Branch Information" }), _jsx("input", {"data-field": "branch_info",  className: "input mt-1", value: company.branch_info ?? '', onChange: e => setCompany({ ...company, branch_info: e.target.value }) })] }), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Tax / Registration" }), _jsx("input", {"data-field": "tax_info",  className: "input mt-1", value: company.tax_info ?? '', onChange: (e) => setCompany({ ...company, tax_info: e.target.value }) })] }), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Base Currency" }), _jsx("select", {"data-field": "base_currency",  className: "input mt-1", value: company.base_currency ?? company.currency ?? DEFAULT_COMPANY_CURRENCY, onChange: (e) => {
                                            const nextCurrency = e.target.value;
                                            setCompany({ ...company, currency: nextCurrency, base_currency: nextCurrency });
                                            setStoredCurrency(nextCurrency);
                                        }, children: reference.currencies.map((c) => _jsxs("option", { value: c.currency_code, children: [c.currency_code, " \u2014 ", c.currency_name] }, c.currency_code)) })] }), _jsxs("div", { className: "grid gap-3 sm:grid-cols-2", children: [_jsxs("label", { className: "text-sm font-medium text-slate-700", children: ["Company Country", _jsxs("select", {"data-field": "country_code",  className: "input mt-1", value: company.country_code || '', onChange: e => { const selected = reference.countries.find((c) => c.country_code === e.target.value); setCompany({ ...company, country_code: e.target.value, base_currency: company.base_currency || selected?.default_currency_code, currency: company.currency || selected?.default_currency_code }); }, children: [_jsx("option", { value: "", children: "Select country" }), reference.countries.map((c) => _jsx("option", { value: c.country_code, children: c.country_name }, c.country_code))] })] }), _jsxs("label", { className: "text-sm font-medium text-slate-700", children: ["Time Zone", _jsx("input", {"data-field": "time_zone",  className: "input mt-1", value: company.time_zone || '', onChange: e => setCompany({ ...company, time_zone: e.target.value }) })] })] }), _jsxs("div", { className: "grid gap-3 sm:grid-cols-3", children: [_jsxs("label", { className: "text-sm font-medium text-slate-700", children: ["City", _jsxs("select", {"data-field": "city_id",  className: "input mt-1", value: company.city_id || '', onChange: e => setCompany({ ...company, city_id: e.target.value ? Number(e.target.value) : null }), children: [_jsx("option", { value: "", children: "Select city" }), reference.cities.filter((c) => c.country_code === company.country_code).map((c) => _jsx("option", { value: c.id, children: c.city_name }, c.id))] })] }), _jsxs("label", { className: "text-sm font-medium text-slate-700", children: ["Region / Province", _jsx("input", {"data-field": "region_province",  className: "input mt-1", value: company.region_province || '', onChange: e => setCompany({ ...company, region_province: e.target.value }) })] }), _jsxs("label", { className: "text-sm font-medium text-slate-700", children: ["Postal Code", _jsx("input", {"data-field": "postal_code",  className: "input mt-1", value: company.postal_code || '', onChange: e => setCompany({ ...company, postal_code: e.target.value }) })] })] }), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Financial Year" }), _jsx("input", {"data-field": "financial_year",  className: "input mt-1", value: company.financial_year ?? '', onChange: (e) => setCompany({ ...company, financial_year: e.target.value }) })] }), _jsxs("label", {className:"block text-sm font-medium text-slate-700",children:["Default RFQ Payment Terms",_jsx("textarea",{"data-field": "default_payment_terms", className:"input mt-1",value:company.default_payment_terms ?? "",onChange:e=>setCompany({...company,default_payment_terms:e.target.value}),placeholder:"Configure the company default for new RFQs"})]}), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Company Logo (PNG, JPG, or WebP)" }), _jsxs("div", { className: "mt-2 flex min-h-28 items-center gap-4 rounded-xl border border-slate-200 bg-slate-50 p-4", children: [_jsx("div", { className: "flex h-24 w-44 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white p-3 shadow-sm", children: (logoPreview || company.logo_url)
                                                    ? _jsx(CompanyLogo, { company: company, src: logoPreview || company.logo_url, size: "document", className: "max-h-full max-w-full" })
                                                    : _jsx("span", { className: "text-center text-xs text-slate-400", children: "No company logo uploaded" }) }), _jsxs("div", { className: "min-w-0 text-sm", children: [_jsx("div", { className: "font-medium text-slate-800", children: logoFile ? 'Selected logo preview' : company.logo_url ? 'Current company logo' : 'Company identity' }), _jsx("div", { className: "mt-1 truncate text-xs text-slate-500", children: logoFile?.name || (company.logo_url ? 'Active throughout Procuraflo' : 'Select an image below') })] })] }), _jsx("input", { className: "input mt-2", type: "file", accept: "image/png,image/jpeg,image/webp", onChange: (e) => { setSaveError(''); setLogoFile(e.target.files?.[0] || null); } }), _jsx("p", { className: "text-xs text-slate-500 mt-1", children: "Procuraflo automatically removes a plain light background, crops excess whitespace, preserves proportions, and creates a high-resolution transparent PNG for consistent use everywhere." }), _jsx("button", { className: "btn-secondary mt-2", onClick: uploadLogo, disabled: !logoFile || uploading || saving, children: uploading ? 'Uploading...' : 'Upload Logo Now' })] }), _jsxs("div", { className: "flex items-center gap-3", children: [_jsx("button", { className: "btn-primary", onClick: save, disabled: saving || uploading, children: saving ? 'Saving all settings...' : 'Save All Settings' }), saved && _jsx("span", { className: "text-emerald-600 text-sm", children: "All settings saved" })] }), saveError && _jsx("div", {"data-error-message": true, role: "alert",  className: "text-sm text-red-700", children: saveError })] }), _jsxs("div", { className: "card p-5 space-y-4", children: [_jsx("h2", { className: "font-medium text-slate-800", children: "Role-Based Approvals" }), _jsx("p", { className: "text-xs text-slate-500", children: "These database values are the default monetary approval limits used by approval workflows. An explicitly assigned employee limit takes precedence." }), APPROVAL_ROLES.map(({ role, label, key }) => (_jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: currencyFieldLabel(`${label} Approval Limit`, company.currency) }), _jsx(CurrencyInput, { currency: company.currency, min: "0", step: "0.01", value: limits[key] ?? '', onChange: (e) => setLimits({ ...limits, [key]: e.target.value }) })] }, role)))] }), _jsxs("div", { className: "card p-5 space-y-4 lg:col-span-2", children: [_jsx("h2", { className: "font-medium text-slate-800", children: "Backup, Restore & Fiscal Year Close" }), _jsx("p", { className: "text-sm text-slate-500", children: "Create a backup before each month-end and before changing the fiscal year. Restores are validated and staged to avoid overwriting a live database." }), _jsxs("div", { className: "flex flex-wrap gap-2", children: [_jsx("button", { className: "btn-secondary", onClick: downloadBackup, children: "Download Database Backup" }), _jsx("input", { className: "input max-w-sm", type: "file", accept: ".db,.sqlite,.sqlite3", onChange: (e) => setRestoreFile(e.target.files?.[0] || null) }), _jsx("button", { className: "btn-secondary", disabled: !restoreFile, onClick: stageRestore, children: "Validate & Stage Restore" })] }), _jsxs("div", { className: "flex flex-wrap items-end gap-2 border-t border-slate-100 pt-4", children: [_jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-700", children: "Next Fiscal Year" }), _jsx("input", {"data-field": "nextFinancialYear",  className: "input mt-1", placeholder: "e.g. FY2027", value: nextFinancialYear, onChange: (e) => setNextFinancialYear(e.target.value) })] }), _jsx("button", { className: "btn-primary", onClick: closeFiscalYear, children: "Backup & Close Fiscal Year" })] }), message && _jsx("div", { className: "text-sm text-emerald-600", children: message })] }), _jsxs("div", { className: "card overflow-hidden lg:col-span-2 border border-slate-200 shadow-sm", children: [_jsx("button", { type: "button", className: "w-full text-left bg-gradient-to-r from-slate-900 via-blue-950 to-blue-900 px-5 py-5 text-white", onClick: () => setShowAccounts((open) => !open), "aria-expanded": showAccounts, children: _jsxs("div", { className: "flex flex-col lg:flex-row lg:items-center justify-between gap-4", children: [_jsxs("div", { className: "flex items-center gap-3", children: [_jsx("div", { className: "h-11 w-11 rounded-xl bg-white/10 ring-1 ring-white/20 flex items-center justify-center text-xl", children: "\u2659" }), _jsxs("div", { children: [_jsx("div", { className: "text-xs uppercase tracking-[0.18em] text-blue-200", children: "Access Governance" }), _jsx("h2", { className: "text-lg font-semibold", children: "User Account Status" }), _jsx("p", { className: "text-xs text-slate-300 mt-0.5", children: "Monitor employee access, password lifecycle, and locked accounts" })] })] }), _jsxs("div", { className: "flex items-center gap-5", children: [_jsxs("div", { className: "grid grid-cols-4 gap-4 text-center", children: [_jsxs("div", { children: [_jsx("div", { className: "text-xl font-semibold", children: users.length }), _jsx("div", { className: "text-[10px] uppercase tracking-wider text-slate-300", children: "Total" })] }), _jsxs("div", { children: [_jsx("div", { className: "text-xl font-semibold text-emerald-300", children: users.filter((u) => u.is_active && !u.locked_reason).length }), _jsx("div", { className: "text-[10px] uppercase tracking-wider text-slate-300", children: "Active" })] }), _jsxs("div", { children: [_jsx("div", { className: "text-xl font-semibold text-amber-300", children: users.filter((u) => u.locked_reason).length }), _jsx("div", { className: "text-[10px] uppercase tracking-wider text-slate-300", children: "Locked" })] }), _jsxs("div", { children: [_jsx("div", { className: "text-xl font-semibold text-rose-300", children: users.filter((u) => !u.is_active && !u.locked_reason).length }), _jsx("div", { className: "text-[10px] uppercase tracking-wider text-slate-300", children: "Inactive" })] })] }), _jsx("span", { className: `text-xl transition-transform duration-200 ${showAccounts ? 'rotate-180' : ''}`, children: "\u2304" })] })] }) }), showAccounts && _jsxs("div", { className: "bg-white", children: [_jsxs("div", { className: "flex items-center justify-between px-5 py-3 border-b border-slate-100 bg-slate-50", children: [_jsxs("div", { children: [_jsx("div", { className: "text-sm font-medium text-slate-800", children: "Account Directory" }), _jsx("div", { className: "text-xs text-slate-500", children: "Only authorized administrators can restore access." })] }), _jsxs("span", { className: "text-xs font-medium text-slate-500", children: [users.length, " account", users.length === 1 ? '' : 's'] })] }), _jsx("div", { className: "overflow-x-auto", children: _jsxs("table", { className: "table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Employee" }), _jsx("th", { children: "Login ID" }), _jsx("th", { children: "Assigned Role" }), _jsx("th", { children: "Password Expiry" }), _jsx("th", { children: "Access Status" }), _jsx("th", { children: "Action" })] }) }), _jsxs("tbody", { children: [users.map((user) => { const locked = Boolean(user.locked_reason); const active = Boolean(user.is_active) && !locked; return _jsxs("tr", { className: "hover:bg-blue-50/40", children: [_jsxs("td", { children: [_jsx("div", { className: "font-medium text-slate-800", children: user.full_name }), _jsx("div", { className: "text-[11px] text-slate-400", children: "Employee account" })] }), _jsx("td", { children: _jsx("span", { className: "font-mono text-sm text-blue-700 bg-blue-50 px-2 py-1 rounded", children: user.username }) }), _jsx("td", { children: _jsx("span", { className: "text-xs font-medium text-slate-600", children: String(user.role).replace(/([a-z])([A-Z])/g, '$1 $2') }) }), _jsx("td", { children: _jsx("div", { className: "text-sm text-slate-700", children: user.password_expires_at || 'Not set' }) }), _jsxs("td", { children: [_jsxs("span", { className: `inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${active ? 'bg-emerald-50 text-emerald-700' : locked ? 'bg-amber-50 text-amber-700' : 'bg-rose-50 text-rose-700'}`, children: [_jsx("span", { className: `h-1.5 w-1.5 rounded-full ${active ? 'bg-emerald-500' : locked ? 'bg-amber-500' : 'bg-rose-500'}` }), active ? 'Active' : locked ? 'Locked' : 'Inactive'] }), locked && _jsx("div", { className: "text-[11px] text-amber-700 mt-1 max-w-xs", children: user.locked_reason })] }), _jsx("td", { children: (locked || !user.is_active) ? _jsx("button", { className: "btn-secondary", onClick: () => unlockUser(user.id), children: "Restore Access" }) : _jsx("span", { className: "text-xs text-slate-400", children: "No action required" }) })] }, user.id); }), users.length === 0 && _jsx("tr", { children: _jsx("td", { colSpan: 6, className: "text-center py-10 text-slate-400", children: "No user accounts are available." }) })] })] }) })] })] }), _jsxs("div", { className: "card p-5 space-y-4 lg:col-span-2 border border-red-200 bg-red-50/40", children: [_jsxs("div", { children: [_jsx("h2", { className: "font-semibold text-red-800", children: "Danger Zone \u2014 Reset for a New Company" }), _jsx("p", { className: "text-sm text-red-700 mt-1", children: "Creates a recovery backup, then permanently removes all company, employee, supplier, item, procurement, warehouse, inventory, report, audit, notification, and uploaded-document data. Only your Supply Chain Manager login is retained for initial setup." })] }), !showReset ? _jsx("button", { className: "px-4 py-2 rounded bg-red-700 text-white text-sm font-medium hover:bg-red-800", onClick: () => setShowReset(true), children: "Start Secure Factory Reset" }) : _jsxs("div", { className: "rounded-lg border border-red-300 bg-white p-4 space-y-3 max-w-xl", children: [_jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-800", children: "Confirm your current password" }), _jsx("input", {"data-field": "resetPassword",  className: "input mt-1", type: "password", autoComplete: "current-password", value: resetPassword, onChange: (e) => setResetPassword(e.target.value) })] }), _jsxs("div", { children: [_jsx("label", { className: "text-sm font-medium text-slate-800", children: "Type RESET PROCURAFLO" }), _jsx("input", {"data-field": "resetPhrase",  className: "input mt-1 font-mono", value: resetPhrase, onChange: (e) => setResetPhrase(e.target.value) })] }), _jsxs("label", { className: "flex gap-2 text-sm text-slate-700", children: [_jsx("input", { type: "checkbox", checked: resetAcknowledged, onChange: (e) => setResetAcknowledged(e.target.checked) }), _jsx("span", { children: "I understand that current application data and uploaded documents will be permanently deleted after the automatic backup." })] }), resetError && _jsx("div", {"data-error-message": true, role: "alert",  className: "text-sm text-red-700", children: resetError }), _jsxs("div", { className: "flex gap-2", children: [_jsx("button", { className: "px-4 py-2 rounded bg-red-700 text-white text-sm font-medium disabled:opacity-40", disabled: resetting || !resetPassword || resetPhrase !== 'RESET PROCURAFLO' || !resetAcknowledged, onClick: factoryReset, children: resetting ? 'Creating backup and resetting...' : 'Permanently Reset All Data' }), _jsx("button", { className: "btn-secondary", disabled: resetting, onClick: () => { setShowReset(false); setResetPassword(''); setResetPhrase(''); setResetAcknowledged(false); setResetError(''); }, children: "Cancel" })] })] })] })] })] }));
}
