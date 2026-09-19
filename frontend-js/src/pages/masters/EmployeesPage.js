import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import client from '../../api/client';
import MasterDataPage from './MasterDataPage';
import Modal from '../../components/Modal';
import { useAuth } from '../../contexts/AuthContext';
import { currencyFieldLabel, formatCurrency } from '../../utils/currency';
import { formatRole } from '../../utils/roles';
const PERMISSIONS = [
    { key: 'task.pr', type: 'Task', label: 'Purchase Requisitions' }, { key: 'task.rfq', type: 'Task', label: 'RFQs & Quotations' }, { key: 'task.po', type: 'Task', label: 'Purchase Orders' }, { key: 'task.invoices', type: 'Task', label: 'Invoices & Three-Way Match' },
    { key: 'task.grn', type: 'Task', label: 'Goods Receipts (GRN)' }, { key: 'task.material_issue', type: 'Task', label: 'Material Issues' }, { key: 'task.returns', type: 'Task', label: 'Material Returns' }, { key: 'task.transfers', type: 'Task', label: 'Warehouse Transfers' }, { key: 'task.adjustments', type: 'Task', label: 'Stock Adjustments' },
    { key: 'task.inventory', type: 'Task', label: 'Inventory Inquiry & Valuation' }, { key: 'task.cycle_count', type: 'Task', label: 'Cycle Counts' }, { key: 'task.tools', type: 'Task', label: 'Tool Management' }, { key: 'task.vendor_scorecard', type: 'Task', label: 'Vendor Scorecards' },
    { key: 'task.employees', type: 'Administration', label: 'Employee Master' }, { key: 'task.suppliers', type: 'Administration', label: 'Supplier Master' }, { key: 'task.items', type: 'Administration', label: 'Item Master' }, { key: 'task.warehouses', type: 'Administration', label: 'Warehouses & Locations' }, { key: 'task.settings', type: 'Administration', label: 'System Settings' }, { key: 'task.import_data', type: 'Administration', label: 'Data Imports' }, { key: 'task.live_activity', type: 'Administration', label: 'Live User Activity' },
    { key: 'report.procurement', type: 'Report', label: 'Procurement Reports' }, { key: 'report.inventory', type: 'Report', label: 'Inventory Reports' }, { key: 'report.warehouse', type: 'Report', label: 'Warehouse Reports' }, { key: 'report.employee', type: 'Report', label: 'Employee Accountability Reports' }, { key: 'report.tools', type: 'Report', label: 'Tool Reports' }, { key: 'report.system', type: 'Report', label: 'System Administration Reports' }, { key: 'report.executive', type: 'Report', label: 'Executive Reports' },
];
const ROLE_DEFAULTS = { SupplyChainManager: PERMISSIONS.map(p => p.key).filter(key => key !== 'task.items'), PurchaseManager: ['task.pr', 'task.rfq', 'task.po', 'task.invoices', 'task.employees', 'task.suppliers', 'task.items', 'report.procurement'], PurchaseOfficer: ['task.pr', 'task.rfq', 'task.po', 'task.invoices', 'task.suppliers', 'task.items', 'report.procurement'], WarehouseManager: ['task.pr', 'task.po', 'task.grn', 'task.material_issue', 'task.returns', 'task.transfers', 'task.adjustments', 'task.inventory', 'task.cycle_count', 'task.tools', 'task.employees', 'task.warehouses', 'report.inventory', 'report.warehouse', 'report.employee', 'report.tools'], WarehouseSupervisor: ['task.pr', 'task.po', 'task.grn', 'task.material_issue', 'task.returns', 'task.transfers', 'task.adjustments', 'task.inventory', 'task.cycle_count', 'task.tools', 'task.warehouses', 'report.inventory', 'report.warehouse', 'report.employee', 'report.tools'], Storekeeper: ['task.pr', 'task.po', 'task.grn', 'task.material_issue', 'task.returns', 'task.transfers', 'task.inventory', 'task.cycle_count', 'task.tools', 'report.inventory', 'report.warehouse', 'report.employee', 'report.tools'], Helper: [] };
ROLE_DEFAULTS.SupplyChainManager = PERMISSIONS.map(permission => permission.key);
const REPORTING_HIERARCHY = { SupplyChainManager: ['SupplyChainManager'], PurchaseManager: ['SupplyChainManager'], PurchaseOfficer: ['PurchaseManager', 'SupplyChainManager'], WarehouseManager: ['SupplyChainManager'], WarehouseSupervisor: ['WarehouseManager', 'SupplyChainManager'], Storekeeper: ['WarehouseSupervisor', 'WarehouseManager', 'SupplyChainManager'], Helper: ['WarehouseSupervisor', 'WarehouseManager', 'SupplyChainManager'] };
const WAREHOUSE_ROLES = [
    { value: 'WarehouseManager', label: 'Warehouse Manager' },
    { value: 'WarehouseSupervisor', label: 'Warehouse Supervisor' },
    { value: 'Storekeeper', label: 'Storekeeper' },
    { value: 'Helper', label: 'Helper — workforce only, no login' },
    { value: 'SupplyChainManager', label: 'Supply Chain Manager' },
];
const PROCUREMENT_ROLES = [
    { value: 'PurchaseOfficer', label: 'Purchase Officer' },
    { value: 'PurchaseManager', label: 'Purchase Manager' },
    { value: 'SupplyChainManager', label: 'Supply Chain Manager' },
];
function permissionList(value, role) { try {
    return value ? JSON.parse(value) : ROLE_DEFAULTS[role] || [];
}
catch {
    return ROLE_DEFAULTS[role] || [];
} }
function warehouseIds(employee) { try {
    return JSON.parse(employee.warehouse_ids_json || '[]').map(Number);
}
catch {
    return employee.warehouse_id ? [Number(employee.warehouse_id)] : [];
} }
function reportingRolesForForm(form, employees) { const role = String(form.approval_role || ''), chain = REPORTING_HIERARCHY[role] || []; if (chain.length < 2)
    return chain; const selected = (Array.isArray(form.warehouse_ids) ? form.warehouse_ids : []).map(Number); const available = chain.find(managerRole => employees.some(employee => { if (employee.approval_role !== managerRole)
    return false; if (role === 'PurchaseOfficer' || managerRole === 'SupplyChainManager')
    return true; return !!employee.all_warehouses_yn || selected.some((id) => warehouseIds(employee).includes(id)); })); return available ? [available] : [chain[chain.length - 1]]; }
export default function EmployeesPage() {
    const { user } = useAuth();
    const [depts, setDepts] = useState([]);
    const [employees, setEmployees] = useState([]);
    const [warehouses, setWarehouses] = useState([]);
    const [credentials, setCredentials] = useState(null);
    const [roleLimits, setRoleLimits] = useState({});
    const [roleDefaults, setRoleDefaults] = useState(ROLE_DEFAULTS);
    const departmentIsWarehouse = (departmentId) => /\bwarehouse\b/i.test(String(depts.find(dept => String(dept.value) === String(departmentId))?.label || ''));
    const departmentIsProcurement = (departmentId) => /\b(procurement|purchas)/i.test(String(depts.find(dept => String(dept.value) === String(departmentId))?.label || ''));
    const operationalDepartments = depts.filter(dept => /\b(warehouse|procurement|purchas)/i.test(String(dept.label || '')));
    const rolesForDepartment = (form) => departmentIsWarehouse(form.department_id) ? WAREHOUSE_ROLES : departmentIsProcurement(form.department_id) ? PROCUREMENT_ROLES : [];
const isHelper = (form) => String(form.approval_role || '') === 'Helper';
    // Keep an explicit selection flag so the dependent warehouse controls render in
    // the same event cycle as the Department change. The lookup remains the source
    // of truth when an existing employee is opened for editing.
    const isWarehouseDepartment = (form) => form._warehouse_department_selected === true || departmentIsWarehouse(form.department_id);
    useEffect(() => {
        client.get('/masters/departments').then((res) => setDepts(res.data.map((d) => ({ value: d.id, label: d.name }))));
        client.get('/masters/employee-directory').then((res) => setEmployees(res.data.map((e) => ({ ...e, value: e.id, label: `${e.employee_code} — ${e.name} (${formatRole(e.approval_role)}${e.department_name ? ` / ${e.department_name}` : ''})` }))));
        client.get('/masters/warehouses').then((res) => setWarehouses(res.data.map((w) => ({ value: w.id, label: w.name }))));
        client.get('/settings/approval-limits').then((res) => setRoleLimits(res.data)).catch(() => undefined);
        client.get('/masters/role-permission-defaults').then((res) => setRoleDefaults({ ...ROLE_DEFAULTS, ...res.data })).catch(() => undefined);
    }, []);
    return (_jsxs(_Fragment, { children: [_jsx(MasterDataPage, { title: "Employees", description: "Used for material issuance, approval routing, and reporting structure.", endpoint: "/masters/employees", deriveForm: (form) => ({ ...form, warehouse_ids: Array.isArray(form.warehouse_ids) ? form.warehouse_ids : (() => { try {
                        return JSON.parse(form.warehouse_ids_json || '[]');
                    }
                    catch {
                        return form.warehouse_id ? [form.warehouse_id] : [];
                    } })(), primary_warehouse_id: form.primary_warehouse_id || form.warehouse_id, name: [form.first_name, form.last_name].map((v) => String(v || '').trim()).filter(Boolean).join(' ') }), wideForm: true, transformFieldChange: (field, value, form) => field.key === 'department_id' ? (() => { const warehouse = departmentIsWarehouse(value); return { ...form, department_id: value, approval_role: '', system_access_yn: 0, permission_keys: '[]', _warehouse_department_selected: warehouse, ...(!warehouse ? { warehouse_ids: [], warehouse_id: null, primary_warehouse_id: null, all_warehouses_yn: 0 } : {}), reports_to_employee_id: null }; })() : field.key === 'approval_role' ? { ...form, approval_role: value, position: value === 'Helper' && !form.position ? 'Helper' : form.position, reports_to_employee_id: null, approval_limit: roleLimits[value] ?? 0, permission_keys: JSON.stringify(roleDefaults[value] || []), system_access_yn: value === 'Helper' ? 0 : 1 } : field.key === 'warehouse_ids' ? (() => { const selected = (Array.isArray(value) ? value : []).map(Number).filter(Boolean), currentPrimary = Number(form.primary_warehouse_id); const primary = selected.includes(currentPrimary) ? currentPrimary : (selected[0] || null); return { ...form, warehouse_ids: selected, warehouse_id: primary, primary_warehouse_id: primary }; })() : field.key === 'primary_warehouse_id' ? (() => { const primary = Number(value) || null, selected = (Array.isArray(form.warehouse_ids) ? form.warehouse_ids : []).map(Number).filter(Boolean); return { ...form, warehouse_ids: primary && !selected.includes(primary) ? [...selected, primary] : selected, primary_warehouse_id: primary, warehouse_id: primary }; })() : { ...form, [field.key]: value }, extraPayload: user?.role === 'SupplyChainManager' ? (form, editing) => { const helper = isHelper(form), allowed = new Set(ROLE_DEFAULTS[String(form.approval_role || '')] || []), warehouse = isWarehouseDepartment(form), warehouseId = warehouse ? (Number(form.primary_warehouse_id || form.warehouse_id) || null) : null, base = { permission_keys: helper ? '[]' : JSON.stringify(permissionList(form.permission_keys, String(form.approval_role || '')).filter((key) => allowed.has(key))), system_access_yn: helper ? 0 : 1, approval_limit: helper ? 0 : form.approval_limit, warehouse_id: warehouseId }; return editing ? base : { ...base, warehouse_ids: warehouse ? (form.warehouse_ids || []) : [], all_warehouses_yn: warehouse && form.all_warehouses_yn ? 1 : 0, primary_warehouse_id: warehouseId }; } : undefined, onSaved: user?.role === 'SupplyChainManager' ? async (record, form, editing) => { if (editing)
                    await client.put(`/masters/employees/${record.id}/warehouse-assignments`, { warehouse_ids: form.warehouse_ids || [], all_warehouses_yn: !!form.all_warehouses_yn, primary_warehouse_id: form.primary_warehouse_id || null }); const role = String(form.approval_role || record.approval_role || ''); const keys = permissionList(form.permission_keys, role); if (role) {
                    await client.put(`/masters/role-permission-defaults/${role}`, { permission_keys: keys });
                    setRoleDefaults(current => ({ ...current, [role]: keys }));
                } } : undefined, renderFormExtra: user?.role === 'SupplyChainManager' ? (form, setForm) => { const role = String(form.approval_role || ''); const allowed = ROLE_DEFAULTS[role] || []; const selected = permissionList(form.permission_keys, role).filter((key) => allowed.includes(key)); const types = ['Task', 'Administration', 'Report']; if (role === 'Helper') return _jsx("div", { className: "rounded-xl border border-emerald-200 bg-emerald-50/50 p-4 text-sm text-emerald-900", children: "Helper is a workforce-only record. No login, approval limit, application permissions, email, birth date, or signature is required." }); return _jsxs(_Fragment, { children: [_jsxs("div", { className: "rounded-xl border border-sky-200 bg-sky-50/40 p-4", children: [_jsx("h3", { className: "font-semibold text-sky-950", children: "Reporting Structure" }), _jsx("p", { className: "mt-1 text-xs text-slate-600", children: "The Reports To list uses the nearest active manager for the role and warehouse. If that manager role is unavailable, it automatically falls back to the Supply Chain Manager." }), _jsx("div", { className: "mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3", children: Object.entries(REPORTING_HIERARCHY).filter(([roleName]) => roleName !== 'SupplyChainManager').map(([roleName, managerRoles]) => _jsxs("div", { className: "rounded-lg border border-sky-100 bg-white px-3 py-2", children: [_jsx("span", { className: "font-semibold text-slate-700", children: formatRole(roleName) }), _jsx("span", { className: "mx-2 text-sky-500", children: "\u2192" }), _jsx("span", { className: "text-slate-600", children: managerRoles.map((managerRole, index) => (index ? 'SCM fallback: ' : 'Primary: ') + formatRole(managerRole)).join(' · ') })] }, roleName)) })] }), _jsxs("div", { className: "rounded-xl border border-blue-200 bg-blue-50/30 p-4", children: [_jsxs("div", { className: "flex flex-wrap items-start justify-between gap-3", children: [_jsxs("div", { children: [_jsx("h3", { className: "font-semibold text-blue-950", children: "Application Task & Report Assignment" }), _jsx("p", { className: "mt-1 text-xs text-slate-600", children: "Role-approved functions are preselected. Clear a function to restrict this individual; permissions outside the selected role cannot be assigned." })] }), _jsx("button", { type: "button", className: "btn-secondary", disabled: !role, onClick: () => setForm(current => ({ ...current, permission_keys: JSON.stringify(roleDefaults[role] || allowed) })), children: "Apply Role Defaults" })] }), !role ? _jsx("div", { className: "mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800", children: "Select an Approval Role to load its authorized task and report matrix." }) : _jsx("div", { className: "mt-4 overflow-hidden rounded-lg border border-slate-200 bg-white", children: _jsxs("table", { className: "w-full text-sm", children: [_jsx("thead", { className: "bg-slate-800 text-white", children: _jsxs("tr", { children: [_jsx("th", { className: "px-3 py-2 text-left", children: "Type" }), _jsx("th", { className: "px-3 py-2 text-left", children: "Application Function / Report Group" }), _jsx("th", { className: "px-3 py-2 text-center", children: "Assigned" })] }) }), _jsx("tbody", { children: types.flatMap(type => PERMISSIONS.filter(permission => permission.type === type && allowed.includes(permission.key)).map((permission, index) => _jsxs("tr", { className: "border-t border-slate-100 hover:bg-blue-50/50", children: [_jsx("td", { className: "px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500", children: index === 0 ? type : '' }), _jsx("td", { className: "px-3 py-2 font-medium text-slate-700", children: permission.label }), _jsx("td", { className: "px-3 py-2 text-center", children: _jsx("input", { type: "checkbox", checked: selected.includes(permission.key), onChange: (e) => { const next = e.target.checked ? [...selected, permission.key] : selected.filter((key) => key !== permission.key); setForm(current => ({ ...current, permission_keys: JSON.stringify(next) })); } }) })] }, permission.key))) })] }) }), _jsxs("div", { className: "mt-3 flex justify-between text-xs text-slate-500", children: [_jsxs("span", { children: ["Selected role: ", _jsx("strong", { children: role.replace(/([a-z])([A-Z])/g, '$1 $2') || 'None' })] }), _jsxs("span", { children: [_jsx("strong", { children: selected.length }), " of ", allowed.length, " role-authorized functions assigned"] })] })] })] }); } : undefined, onCreated: (record) => setCredentials(record.credentials || null), columns: [
                    { key: 'employee_code', label: 'Employee ID', render: (record) => _jsxs("div", { className: "min-w-28", children: [_jsx("strong", { className: "font-mono text-slate-900", children: record.employee_code }), record.payroll_number ? _jsxs("div", { className: "text-xs text-slate-500", children: ["Payroll ", record.payroll_number] }) : null] }) },
                    { key: 'name', label: 'Employee Name', render: (record) => _jsx("strong", { className: "min-w-36 text-slate-900", children: record.name || '—' }) },
                    { key: 'department_name', label: 'Department / Role', render: (record) => _jsxs("div", { children: [_jsx("strong", { children: record.department_name || '—' }), _jsxs("div", { className: "text-xs text-slate-500", children: [formatRole(record.approval_role), record.position ? ` · ${record.position}` : ''] })] }) },
                    { key: 'assigned_warehouses', label: 'Assignment', render: (record) => _jsxs("div", { children: [_jsx("div", { children: record.all_warehouses_yn ? 'All Warehouses' : record.assigned_warehouses || warehouses.find((warehouse) => Number(warehouse.value) === Number(record.warehouse_id))?.label || '—' }), _jsxs("div", { className: "text-xs text-slate-500", children: ["Reports to: ", employees.find((employee) => Number(employee.id) === Number(record.reports_to_employee_id))?.name || '—'] })] }) },
                    { key: 'login_id', label: 'Access', render: (record) => record.login_id ? _jsxs("div", { children: [_jsx("strong", { className: "font-mono text-blue-700", children: record.login_id }), _jsxs("div", { className: "text-xs text-slate-500", children: [permissionList(record.permission_keys, record.approval_role).length, " functions · ", record.login_status] })] }) : _jsx("span", { className: "text-xs text-slate-500", children: "Workforce only · No login" }) },
                    { key: 'status', label: 'Status', render: (record) => _jsx("span", { className: `rounded-full px-2 py-1 text-xs font-semibold ${record.status === 'Active' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'}`, children: record.status }) },
                ], fields: [
                    { key: 'department_id', label: 'Department', type: 'select', options: operationalDepartments },
                    { key: 'approval_role', label: 'Employee Role', type: 'select', options: rolesForDepartment },
                    { key: 'first_name', label: _jsx("span", { className: "employee-name-field employee-name-first", children: "First Name" }) },
                    { key: 'middle_name', label: _jsx("span", { className: "employee-name-field", children: "Middle Name" }) },
                    { key: 'last_name', label: _jsx("span", { className: "employee-name-field", children: "Last Name" }) },
                    { key: 'name', label: 'Display Name (automatic)', readOnly: true },
                    { key: 'email', label: 'Email Address', visible: (form) => !isHelper(form) },
                    { key: 'signature_file', label: 'Employee Signature', type: 'signature', visible: (form) => !isHelper(form) },
                    { key: 'date_of_birth', label: 'Date of Birth', type: 'date', visible: (form) => !isHelper(form) },
                    { key: 'payroll_number', label: 'Employee / Payroll No.' },
                    { key: 'position', label: 'Position' },
                    { key: 'warehouse_ids', label: _jsx("span", { className: "employee-warehouse-field employee-warehouse-first", children: "Assigned Warehouses" }), type: 'multicheckbox', options: warehouses, submit: false, visible: isWarehouseDepartment },
                    { key: 'all_warehouses_yn', label: _jsxs("span", { className: "employee-warehouse-field", children: ["All Warehouses", _jsx("small", { className: "ml-1 font-normal text-slate-500", children: "(includes future sites)" })] }), type: 'checkbox', submit: false, visible: isWarehouseDepartment },
                    { key: 'primary_warehouse_id', label: _jsx("span", { className: "employee-warehouse-field", children: "Primary Warehouse" }), type: 'select', options: warehouses, submit: false, visible: isWarehouseDepartment },
                    { key: 'reports_to_employee_id', label: 'Reports To (automatic active-role fallback)', type: 'select', options: (form) => { const allowed = reportingRolesForForm(form, employees); const selected = (Array.isArray(form.warehouse_ids) ? form.warehouse_ids : []).map(Number); return employees.filter((employee) => { if (Number(employee.id) === Number(form.id) || !allowed.includes(String(employee.approval_role)))
                            return false; if (!['WarehouseSupervisor', 'Storekeeper', 'Helper'].includes(String(form.approval_role)) || employee.approval_role === 'SupplyChainManager')
                            return true; const managerWarehouses = warehouseIds(employee); return !!employee.all_warehouses_yn || selected.some((id) => managerWarehouses.includes(id)); }); } },
                    { key: 'approval_limit', label: currencyFieldLabel('Approval Limit'), type: 'number', visible: (form) => !isHelper(form) },
                    {
                        key: 'status',
                        label: 'Status',
                        type: 'select',
                        options: [
                            { value: 'Active', label: 'Active' },
                            { value: 'Inactive', label: 'Inactive' },
                        ],
                    },
                ] }), credentials && (_jsx(Modal, { title: "Employee Login Created", onClose: () => setCredentials(null), children: _jsxs("div", { className: "space-y-4 text-sm", children: [_jsx("p", { className: "text-slate-600", children: "The employee ID and login were generated automatically. Save these credentials now; the temporary password is shown only on this screen." }), _jsxs("div", { className: "rounded-lg bg-slate-50 border border-slate-200 p-4 space-y-2", children: [_jsxs("div", { children: [_jsx("span", { className: "text-slate-500", children: "Employee ID:" }), " ", _jsx("strong", { className: "select-all", children: credentials.employee_code })] }), _jsxs("div", { children: [_jsx("span", { className: "text-slate-500", children: "Username:" }), " ", _jsx("strong", { className: "select-all", children: credentials.username })] }), _jsxs("div", { children: [_jsx("span", { className: "text-slate-500", children: "Temporary password:" }), " ", _jsx("strong", { className: "select-all", children: credentials.password })] })] }), _jsx("div", { className: "flex justify-end", children: _jsx("button", { className: "btn-primary", onClick: () => setCredentials(null), children: "I have saved it" }) })] }) }))] }));
}
