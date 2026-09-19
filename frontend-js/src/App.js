import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { lazy, Suspense, useEffect } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./contexts/AuthContext";
import { useBranding } from "./contexts/BrandingContext";
import Layout from "./components/Layout";
import client from "./api/client";
const Login = lazy(() => import("./pages/Login.jsx"));
const Dashboard = lazy(() => import("./pages/Dashboard.js"));
const QuickStartPage = lazy(() => import("./pages/QuickStartPage.jsx"));
const LiveUserActivityPage = lazy(() => import("./pages/LiveUserActivityPage.js"));
const HelpPage = lazy(() => import("./pages/HelpPage.js"));
const DepartmentsPage = lazy(() => import("./pages/masters/DepartmentsPage.js"));
const EmployeeMasterPage = lazy(
  () => import("./pages/masters/EmployeeMasterPage.jsx"),
);
const SuppliersPage = lazy(() => import("./pages/masters/SuppliersPage.js"));
const ItemsPage = lazy(() => import("./pages/masters/ItemsPage.js"));
const WarehousesPage = lazy(() => import("./pages/masters/WarehousesPage.jsx"));
const SettingsPage = lazy(() => import("./pages/masters/SettingsPage.js"));
const ImportDataPage = lazy(() => import("./pages/masters/ImportDataPage.jsx"));
const PRPage = lazy(() => import("./pages/procurement/PRPage.js"));
const RFQPage = lazy(() => import("./pages/procurement/RFQPage.jsx"));
const POPage = lazy(() => import("./pages/procurement/POPage.js"));
const InvoicesPage = lazy(() => import("./pages/procurement/InvoicesPage.js"));
const GRNPage = lazy(() => import("./pages/warehouse/GRNPage.js"));
const ReceivingControlPage = lazy(() => import("./pages/warehouse/ReceivingControlPage.jsx"));
const ReplenishmentCheckPage = lazy(() => import("./pages/warehouse/ReplenishmentCheckPage.jsx"));
const MaterialIssuePage = lazy(
  () => import("./pages/warehouse/MaterialIssuePage.js"),
);
const ReturnsPage = lazy(() => import("./pages/warehouse/ReturnsPage.js"));
const TransfersPage = lazy(() => import("./pages/warehouse/TransfersPage.js"));
const BinTransfersPage = lazy(
  () => import("./pages/warehouse/BinTransfersPage.js"),
);
const AdjustmentsPage = lazy(() => import("./pages/warehouse/AdjustmentsPage.js"));
const StockPage = lazy(() => import("./pages/inventory/StockPage.js"));
const ValuationPage = lazy(() => import("./pages/inventory/ValuationPage.js"));
const ExpiryPage = lazy(() => import("./pages/inventory/ExpiryPage.js"));
const ABCPage = lazy(() => import("./pages/inventory/ABCPage.js"));
const DeadStockPage = lazy(() => import("./pages/inventory/DeadStockPage.js"));
const CycleCountPage = lazy(() => import("./pages/inventory/CycleCountPage.jsx"));
const ToolsPage = lazy(() => import("./pages/advanced/ToolsPage.jsx"));
const VendorScorecardPage = lazy(
  () => import("./pages/advanced/VendorScorecardPage.jsx"),
);
const ReportsPage = lazy(() => import("./pages/reports/ReportsPage.js"));
const WarehouseDeactivationReportsPage = lazy(() => import("./pages/reports/WarehouseDeactivationReportsPage.jsx"));
const ProcurementSchedulePage = lazy(() => import("./pages/ProcurementSchedulePage.jsx"));
const WorkCalendarPage = lazy(() => import("./pages/WorkCalendarPage.js"));
const WorkforceSetupPage = lazy(
  () => import("./pages/EmployeeWorkforceSetupPage.jsx"),
);
const ReferenceDataPage = lazy(() => import("./pages/ReferenceDataPage.jsx"));
const DelegatedAuthorityPage = lazy(
  () => import("./pages/DelegatedAuthorityPage.jsx"),
);
const EmployeeClearancePage = lazy(() => import("./pages/EmployeeClearancePage.jsx"));
function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading)
    return _jsx("div", {
      className: "min-h-screen flex items-center justify-center text-slate-400",
      children: "Loading...",
    });
  if (!user) return _jsx(Navigate, { to: "/login", replace: true });
  return _jsx(Layout, { children: children });
}
function RoleRoute({ children, allowedRoles }) {
  const { user, loading } = useAuth();
  if (loading)
    return _jsx("div", {
      className: "min-h-screen flex items-center justify-center text-slate-400",
      children: "Loading...",
    });
  if (!user) return _jsx(Navigate, { to: "/login", replace: true });
  if (!allowedRoles.includes(user.role)) {
    return _jsx("div", {
      className: "min-h-screen flex items-center justify-center text-slate-600",
      children: "Access denied for this role.",
    });
  }
  return _jsx(Layout, { children: children });
}
export default function App() {
  const { user, loading } = useAuth();
  const { refresh: refreshBranding } = useBranding();
  useEffect(() => {
    // The company endpoint is protected. Requesting it while the login screen
    // is displayed triggers the global 401 redirect and reloads that screen.
    if (loading || !user) return;
    refreshBranding().catch(() => undefined);
  }, [loading, user, refreshBranding]);
  return _jsx(Suspense, {
    fallback: _jsx("div", {
      className: "min-h-screen flex items-center justify-center text-slate-500",
      children: "Loading Procuraflo workspace...",
    }),
    children: _jsxs(Routes, {
      children: [
        _jsx(Route, { path: "/login", element: _jsx(Login, {}) }),
        _jsx(Route, {
          path: "/",
          element: _jsx(ProtectedRoute, { children: _jsx(Dashboard, {}) }),
        }),
        _jsx(Route, {
          path: "/quick-start",
          element: _jsx(ProtectedRoute, { children: _jsx(QuickStartPage, {}) }),
        }),
        _jsx(Route, {
          path: "/live-user-activity",
          element: _jsx(RoleRoute, {
            allowedRoles: ["SupplyChainManager"],
            children: _jsx(LiveUserActivityPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/help",
          element: _jsx(ProtectedRoute, { children: _jsx(HelpPage, {}) }),
        }),
        _jsx(Route, {
          path: "/masters/departments",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "PurchaseManager",
              "WarehouseManager",
            ],
            children: _jsx(DepartmentsPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/masters/employees",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "PurchaseManager",
              "WarehouseManager",
            ],
            children: _jsx(EmployeeMasterPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/masters/company-employees",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "PurchaseManager",
              "PurchaseOfficer",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(Navigate, {
              to: "/masters/employees?tab=company",
              replace: true,
            }),
          }),
        }),
        _jsx(Route, {
          path: "/masters/suppliers",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "PurchaseManager",
              "PurchaseOfficer",
            ],
            children: _jsx(SuppliersPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/masters/items",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "PurchaseManager",
              "PurchaseOfficer",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(ItemsPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/masters/warehouses",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
            ],
            children: _jsx(WarehousesPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/masters/settings",
          element: _jsx(RoleRoute, {
            allowedRoles: ["SupplyChainManager"],
            children: _jsx(SettingsPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/masters/import-data",
          element: _jsx(RoleRoute, {
            allowedRoles: ["SupplyChainManager"],
            children: _jsx(ImportDataPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/masters/reference-data",
          element: _jsx(RoleRoute, {
            allowedRoles: ["SupplyChainManager"],
            children: _jsx(ReferenceDataPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/employees/workforce-setup",
          element: _jsx(RoleRoute, {
            allowedRoles: ["SupplyChainManager"],
            children: _jsx(WorkforceSetupPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/employees/calendar-management",
          element: _jsx(RoleRoute, {
            allowedRoles: ["SupplyChainManager"],
            children: _jsx(WorkCalendarPage, { admin: true }),
          }),
        }),
        _jsx(Route, {
          path: "/delegated-authority",
          element: _jsx(RoleRoute, {
            allowedRoles: ["SupplyChainManager"],
            children: _jsx(DelegatedAuthorityPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/employees/clearance",
          element: _jsx(RoleRoute, {
            allowedRoles: ["SupplyChainManager"],
            children: _jsx(EmployeeClearancePage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/procurement/pr",
          element: _jsx(ProtectedRoute, {
            children: _jsx(PRPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/procurement/rfq",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "PurchaseManager",
              "PurchaseOfficer",
            ],
            children: _jsx(RFQPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/procurement/po",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "PurchaseManager",
              "PurchaseOfficer",
            ],
            children: _jsx(POPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/procurement/invoices",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "PurchaseManager",
              "PurchaseOfficer",
            ],
            children: _jsx(InvoicesPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/procurement/work-calendar",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "PurchaseManager",
              "PurchaseOfficer",
            ],
            children: _jsx(WorkCalendarPage, { scope: "Procurement" }),
          }),
        }),
        _jsx(Route, {
          path: "/warehouse/grn",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(GRNPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/warehouse/pr",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(PRPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/warehouse/replenishment",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(ReplenishmentCheckPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/warehouse/issue",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(MaterialIssuePage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/warehouse/returns",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(ReturnsPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/warehouse/transfers",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(TransfersPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/warehouse/bin-transfers",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(BinTransfersPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/warehouse/adjustments",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
            ],
            children: _jsx(AdjustmentsPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/warehouse/work-calendar",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(WorkCalendarPage, { scope: "Warehouse" }),
          }),
        }),
        _jsx(Route, {
          path: "/inventory/stock",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(StockPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/inventory/valuation",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(ValuationPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/inventory/expiry",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(ExpiryPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/inventory/abc",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(ABCPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/inventory/dead-stock",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(DeadStockPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/inventory/cycle-count",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(CycleCountPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/advanced/tools",
          element: _jsx(RoleRoute, {
            allowedRoles: [
              "SupplyChainManager",
              "WarehouseManager",
              "WarehouseSupervisor",
              "Storekeeper",
            ],
            children: _jsx(ToolsPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/advanced/vendor-scorecard",
          element: _jsx(RoleRoute, {
            allowedRoles: ["SupplyChainManager", "PurchaseManager"],
            children: _jsx(VendorScorecardPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/procurement/operating-schedule",
          element: _jsx(RoleRoute, {
            allowedRoles: ["SupplyChainManager", "PurchaseManager"],
            children: _jsx(ProcurementSchedulePage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/warehouse/receiving-control",
          element: _jsx(RoleRoute, {
            allowedRoles: ["SupplyChainManager","WarehouseManager","WarehouseSupervisor","Storekeeper"],
            children: _jsx(ReceivingControlPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/reports/warehouse-deactivations",
          element: _jsx(RoleRoute, {
            allowedRoles: ["SupplyChainManager"],
            children: _jsx(WarehouseDeactivationReportsPage, {}),
          }),
        }),
        _jsx(Route, {
          path: "/reports",
          element: _jsx(ProtectedRoute, { children: _jsx(ReportsPage, {}) }),
        }),
        _jsx(Route, {
          path: "*",
          element: _jsx(Navigate, { to: "/", replace: true }),
        }),
      ],
    }),
  });
}
