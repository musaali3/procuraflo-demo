import { ProductBrand } from './Branding';
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import React, { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { useBranding } from "../contexts/BrandingContext";
import { CompanyBrand } from "./Branding";
const ROLE_VISIBILITY = {
  SupplyChainManager: [
    "overview",
    "master data",
    "procurement",
    "warehouse",
    "inventory",
    "advanced",
    "reports",
    "help",
  ],
  PurchaseManager: [
    "overview",
    "master data",
    "procurement",
    "reports",
    "help",
  ],
  PurchaseOfficer: ["overview", "procurement", "reports", "help"],
  WarehouseManager: ["overview", "warehouse", "inventory", "reports", "help"],
  WarehouseSupervisor: [
    "overview",
    "warehouse",
    "inventory",
    "reports",
    "help",
  ],
  Storekeeper: ["overview", "warehouse", "inventory", "reports", "help"],
};
// Keep navigation visibility aligned with the roles allowed by each route.
// Server-side RBAC remains the authority; this prevents confusing links.
const ITEM_ROLES = {
  "/": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/quick-start": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/live-user-activity": ["SupplyChainManager"],
  "/help?department=Getting%20Started": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/help?department=Procurement": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/help?department=Warehouse": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/help?department=Inventory": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/help?department=Master%20Data%20%26%20Administration": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/help?department=Reports": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/masters/departments": [
    "SupplyChainManager",
    "PurchaseManager",
    "WarehouseManager",
  ],
  "/masters/employees": [
    "SupplyChainManager",
    "PurchaseManager",
    "WarehouseManager",
  ],
  "/masters/company-employees": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/masters/suppliers": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
  ],
  "/masters/items": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/masters/warehouses": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
  ],
  "/masters/settings": ["SupplyChainManager"],
  "/masters/reference-data": ["SupplyChainManager"],
  "/masters/import-data": ["SupplyChainManager"],
  "/employees/workforce-setup": ["SupplyChainManager"],
  "/employees/calendar-management": ["SupplyChainManager"],
  "/delegated-authority": ["SupplyChainManager"],
  "/employees/clearance": ["SupplyChainManager"],
  "/procurement/pr": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
  ],
  "/procurement/rfq": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
  ],
  "/procurement/po": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
  ],
  "/procurement/invoices": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
  ],
  "/procurement/work-calendar": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
  ],
  "/warehouse/grn": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/warehouse/receiving-control": ["SupplyChainManager","WarehouseManager","WarehouseSupervisor","Storekeeper"],
  "/warehouse/pr": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/warehouse/replenishment": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/warehouse/issue": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/warehouse/returns": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/warehouse/transfers": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/warehouse/bin-transfers": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/warehouse/adjustments": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
  ],
  "/warehouse/work-calendar": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/inventory/stock": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/inventory/valuation": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/inventory/expiry": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/inventory/abc": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/inventory/dead-stock": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/inventory/cycle-count": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/advanced/tools": [
    "SupplyChainManager",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
  "/advanced/vendor-scorecard": ["SupplyChainManager", "PurchaseManager"],
  "/reports": [
    "SupplyChainManager",
    "PurchaseManager",
    "PurchaseOfficer",
    "WarehouseManager",
    "WarehouseSupervisor",
    "Storekeeper",
  ],
};
const PATH_PERMISSION = {
  "/live-user-activity": "task.live_activity",
  "/employees/clearance": "task.employees",
  "/masters/employees": "task.employees",
  "/masters/company-employees": "task.employees",
  "/masters/suppliers": "task.suppliers",
  "/masters/items": "task.items",
  "/masters/warehouses": "task.warehouses",
  "/masters/settings": "task.settings",
  "/masters/reference-data": "task.settings",
  "/masters/import-data": "task.import_data",
  "/procurement/pr": "task.pr",
  "/warehouse/pr": "task.pr",
  "/procurement/rfq": "task.rfq",
  "/procurement/po": "task.po",
  "/procurement/invoices": "task.invoices",
  "/warehouse/grn": "task.grn",
  "/warehouse/replenishment": "task.pr",
  "/warehouse/receiving-control": "task.grn",
  "/warehouse/issue": "task.material_issue",
  "/warehouse/returns": "task.returns",
  "/warehouse/transfers": "task.transfers",
  "/warehouse/bin-transfers": "task.transfers",
  "/warehouse/adjustments": "task.adjustments",
  "/inventory/stock": "task.inventory",
  "/inventory/valuation": "task.inventory",
  "/inventory/expiry": "task.inventory",
  "/inventory/abc": "task.inventory",
  "/inventory/dead-stock": "task.inventory",
  "/inventory/cycle-count": "task.cycle_count",
  "/advanced/tools": "task.tools",
  "/advanced/vendor-scorecard": "task.vendor_scorecard",
};
const NAV_GROUPS = [
  {
    label: "Overview",
    items: [
      { to: "/", label: "Dashboard" },
      { to: "/live-user-activity", label: "Live User Activity" },
      { to: "/quick-start", label: "Quick Start Guide" },
    ],
  },
  {
    label: "Master Data",
    items: [
      { to: "/masters/departments", label: "Departments" },
      { to: "/masters/suppliers", label: "Suppliers" },
      { to: "/masters/items", label: "Items" },
      { to: "/masters/warehouses", label: "Warehouses & Locations" },
      { to: "/masters/settings", label: "System Settings" },
      { to: "/masters/reference-data", label: "Reference Data" },
      { to: "/masters/import-data", label: "Import Data" },
    ],
  },
  {
    label: "Administration / Controls",
    items: [
      { to: "/masters/employees", label: "Employee Master" },
      {
        to: "/employees/workforce-setup",
        label: "Workforce Setup",
      },
      { to: "/employees/calendar-management", label: "Calendar Management" },
      { to: "/delegated-authority", label: "Delegated Authority" },
      { to: "/employees/clearance", label: "Employee Clearance" },
      { to: "/reports?report=employee-workday", label: "Calendar Reports" },
    ],
  },
  {
    label: "Procurement",
    items: [
      { to: "/procurement/pr", label: "Purchase Requisitions" },
      { to: "/procurement/rfq", label: "RFQ & Quotations" },
      { to: "/procurement/po", label: "Purchase Orders" },
      { to: "/procurement/invoices", label: "Invoices & 3-Way Match" },
      { to: "/procurement/work-calendar", label: "Workday Calendar" },
      { to: "/procurement/operating-schedule", label: "Operating Schedule" },
    ],
  },
  {
    label: "Warehouse",
    items: [
      { to: "/warehouse/pr", label: "Purchase Requisitions" },
      { to: "/warehouse/replenishment", label: "Stock Replenishment Check" },
      { to: "/warehouse/grn", label: "Goods Receipt (GRN)" },
      { to: "/warehouse/receiving-control", label: "Inspection & Put-Away" },
      { to: "/warehouse/issue", label: "Material Issue" },
      { to: "/warehouse/returns", label: "Returns" },
      { to: "/warehouse/transfers", label: "Transfers" },
      { to: "/warehouse/bin-transfers", label: "BIN Transfers" },
      { to: "/warehouse/adjustments", label: "Stock Adjustments" },
      { to: "/warehouse/work-calendar", label: "Workday Calendar" },
    ],
  },
  {
    label: "Inventory",
    items: [
      { to: "/inventory/stock", label: "Real-Time Stock" },
      { to: "/inventory/valuation", label: "FIFO Valuation" },
      { to: "/inventory/expiry", label: "Expiry Tracking" },
      { to: "/inventory/abc", label: "ABC Classification" },
      { to: "/inventory/dead-stock", label: "Dead Stock" },
      { to: "/inventory/cycle-count", label: "Cycle Count" },
    ],
  },
  {
    label: "Advanced",
    items: [
      { to: "/advanced/tools", label: "Tool Management" },
      { to: "/advanced/vendor-scorecard", label: "Vendor Scorecard" },
    ],
  },
  {
    label: "Reports",
    items: [{ to: "/reports", label: "Reports" },{ to: "/reports/warehouse-deactivations", label: "Warehouse Deactivation Reports" }],
  },
  {
    label: "Help",
    items: [
      { to: "/help?department=Getting%20Started", label: "Getting Started" },
      { to: "/help?department=Procurement", label: "Procurement Guide" },
      { to: "/help?department=Warehouse", label: "Warehouse Guide" },
      { to: "/help?department=Inventory", label: "Inventory Guide" },
      {
        to: "/help?department=Master%20Data%20%26%20Administration",
        label: "Master Data & Admin",
      },
      { to: "/help?department=Reports", label: "Reports Guide" },
    ],
  },
];
const GROUP_ICONS = {
  Overview: "dashboard",
  "Master Data": "cube",
  "Administration / Controls": "users",
  Procurement: "cart",
  Warehouse: "warehouse",
  Inventory: "layers",
  Advanced: "tool",
  Reports: "chart",
  Help: "help",
};
const ITEM_ICON_RULES = [
  [/dashboard|activity/i, "dashboard"],
  [/quick|guide|help|getting/i, "help"],
  [/item|catalog/i, "cube"],
  [/supplier|vendor/i, "users"],
  [/warehouse|location|bin/i, "warehouse"],
  [/inventory|stock|expiry|dead|valuation|abc|cycle/i, "layers"],
  [/employee|workforce|calendar|delegated|clearance/i, "users"],
  [/procurement|purchase|requisition|rfq|order|invoice|schedule/i, "cart"],
  [/receiving|receipt|grn|issue|return|transfer|adjustment|replenishment/i, "warehouse"],
  [/report|scorecard/i, "chart"],
  [/setting|tool|import|reference/i, "tool"],
];
const ICON_PATHS = {
  dashboard: "M4 5.5A1.5 1.5 0 0 1 5.5 4h4A1.5 1.5 0 0 1 11 5.5v4A1.5 1.5 0 0 1 9.5 11h-4A1.5 1.5 0 0 1 4 9.5v-4Zm9 0A1.5 1.5 0 0 1 14.5 4h4A1.5 1.5 0 0 1 20 5.5v2A1.5 1.5 0 0 1 18.5 9h-4A1.5 1.5 0 0 1 13 7.5v-2ZM13 14.5a1.5 1.5 0 0 1 1.5-1.5h4a1.5 1.5 0 0 1 1.5 1.5v4a1.5 1.5 0 0 1-1.5 1.5h-4a1.5 1.5 0 0 1-1.5-1.5v-4ZM4 16.5A1.5 1.5 0 0 1 5.5 15h4a1.5 1.5 0 0 1 1.5 1.5v2A1.5 1.5 0 0 1 9.5 20h-4A1.5 1.5 0 0 1 4 18.5v-2Z",
  cube: "M12 3 4.5 7.1v9.8L12 21l7.5-4.1V7.1L12 3Zm0 2.3 4.7 2.6L12 10.5 7.3 7.9 12 5.3Zm-5.5 4.2 4.5 2.5v5.9l-4.5-2.5V9.5Zm6.5 8.4V12l4.5-2.5v5.9L13 17.9Z",
  users: "M8.5 11a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7Zm7-1a3 3 0 1 1 0-6 3 3 0 0 1 0 6ZM3.5 19.5c.4-3.3 2.4-5 5-5s4.6 1.7 5 5h-10Zm10.5 0c-.2-1.7-.8-3.1-1.8-4.2.8-.5 1.9-.8 3.3-.8 2.5 0 4.4 1.6 4.8 5H14Z",
  cart: "M5 5h2l1.2 8.1A2 2 0 0 0 10.2 15h6.7a2 2 0 0 0 1.9-1.4L20 8H8.4M10 20a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Zm7 0a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z",
  warehouse: "M3.5 20V9.3L12 4l8.5 5.3V20h-3v-7h-11v7h-3Zm5-5v5h7v-5h-7Zm-2-4h11v-.6L12 7l-5.5 3.4v.6Z",
  layers: "M12 3 3.5 7.5 12 12l8.5-4.5L12 3Zm-6.6 8.2L3.5 12.2 12 17l8.5-4.8-1.9-1L12 14.8l-6.6-3.6Zm0 5L3.5 17.2 12 22l8.5-4.8-1.9-1L12 19.8l-6.6-3.6Z",
  tool: "M14.5 4.5a5 5 0 0 0 5 5l-7.8 7.8a3 3 0 1 1-4.2-4.2l7.8-7.8c-.3-.2-.5-.5-.8-.8ZM7 18a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z",
  chart: "M5 19h15v2H3V4h2v15Zm3-2V9h3v8H8Zm5 0V5h3v12h-3Zm5 0v-6h3v6h-3Z",
  help: "M11 17h2v-2h-2v2Zm1-14a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm0 2a5 5 0 0 1 1.3 9.8V13c0-1 .5-1.5 1.2-2.1.8-.7 1.5-1.4 1.5-2.9 0-2-1.6-3.5-4-3.5-2 0-3.5 1-4.2 2.8l1.8.8c.4-1 1.2-1.6 2.3-1.6 1.2 0 2 .7 2 1.6 0 .8-.4 1.2-1.2 1.8-1 .8-1.7 1.5-1.7 3.1v.3a5 5 0 0 1 1-9.9Z",
};
function iconForItem(label) {
  return ITEM_ICON_RULES.find(([pattern]) => pattern.test(label))?.[1] || "dashboard";
}
function NavIcon({ name, item = false }) {
  return _jsx("span", { className: `nav-icon ${item ? "nav-icon-item" : ""}`, "aria-hidden": "true", children: _jsx("svg", { viewBox: "0 0 24 24", focusable: "false", children: _jsx("path", { d: ICON_PATHS[name] || ICON_PATHS.dashboard }) }) });
}
export default function Sidebar() {
  const { company } = useBranding();
  const { user } = useAuth();
  const { pathname, search } = useLocation();
  const visibleGroups = user?.role ? (ROLE_VISIBILITY[user.role] || []) : [];
  const warehouseLogin = ["WarehouseManager", "WarehouseSupervisor", "Storekeeper"].includes(user?.role);
  const canSee = (to) => {
    if(to === "/procurement/pr")return Boolean(user) && !warehouseLogin;
    if(to === "/warehouse/pr" && warehouseLogin)return true;
    if (!user || !(ITEM_ROLES[to] || []).includes(user.role)) return false;
    const required = to === "/masters/items" ? undefined : PATH_PERMISSION[to];
    if (
      required &&
      user.permission_keys &&
      !user.permission_keys.includes(required)
    )
      return false;
    if (
      to === "/reports" &&
      user.permission_keys &&
      !user.permission_keys.some((key) => key.startsWith("report."))
    )
      return false;
    return true;
  };
  const [openGroups, setOpenGroups] = useState(() => new Set(["Overview"]));
  // Always reveal the section containing the page being viewed. Other sections
  // remain collapsed until the user chooses to open them.
  useEffect(() => {
    const activeGroup = NAV_GROUPS.find((group) =>
      group.items.some((item) =>
        item.to === "/"
          ? pathname === "/"
          : pathname.startsWith(item.to.split("?")[0]),
      ),
    );
    if (activeGroup) {
      setOpenGroups(new Set([activeGroup.label]));
    }
  }, [pathname]);
  function toggleGroup(label) {
    setOpenGroups((current) => {
      return current.has(label) ? new Set() : new Set([label]);
    });
  }
  return _jsxs("aside", {
    className:
      "app-sidebar w-64 min-h-screen self-stretch bg-slate-950 text-slate-300 flex flex-col flex-shrink-0",
    children: [
      _jsx("div", {
        className: "px-5 py-5 border-b border-white/10",
        children: _jsx("div", {
          className:
            "px-4 py-3 text-center text-lg font-bold text-white",
          children: _jsx(ProductBrand, { compact: true, inverse: true }),
        }),
      }),
      _jsx("nav", {
        className: "py-3 flex-1",
        children: NAV_GROUPS.filter(
          (group) =>
            visibleGroups.includes(group.label.toLowerCase()) ||
            group.items.some((item) => canSee(item.to)),
        ).map((group) => {
          const items = group.items.filter((item) => canSee(item.to));
          if (items.length === 0) return null;
          const isOpen = openGroups.has(group.label);
          const hasActiveItem = items.some((item) =>
            item.to === "/"
              ? pathname === "/"
              : pathname.startsWith(item.to.split("?")[0]),
          );
          return _jsxs(
            "div",
            {
              className: "mb-1 px-2",
              children: [
                _jsxs("button", {
                  type: "button",
                  onClick: () => toggleGroup(group.label),
                  "aria-expanded": isOpen,
                  className: `sidebar-group-button flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider transition-colors ${isOpen ? "text-cyan-200" : hasActiveItem ? "text-cyan-100" : "text-slate-400 hover:text-white"}`,
                  children: [
                    _jsxs("span", { className: "flex min-w-0 items-center gap-3", children: [
                      _jsx(NavIcon, { name: GROUP_ICONS[group.label] || "dashboard" }),
                      _jsx("span", { className: "truncate", children: group.label })
                    ] }),
                    _jsx("svg", {
                      className: `h-3.5 w-3.5 transition-transform ${isOpen ? "rotate-180" : ""}`,
                      viewBox: "0 0 20 20",
                      fill: "currentColor",
                      "aria-hidden": "true",
                      children: _jsx("path", {
                        fillRule: "evenodd",
                        d: "M5.23 7.21a.75.75 0 0 1 1.06.02L10 11.17l3.71-3.94a.75.75 0 1 1 1.09 1.04l-4.25 4.5a.75.75 0 0 1-1.09 0l-4.25-4.5a.75.75 0 0 1 .02-1.06Z",
                        clipRule: "evenodd",
                      }),
                    }),
                  ],
                }),
                isOpen &&
                  _jsx("div", {
                    className: "mb-2 overflow-hidden",
                    children: items.map((item) =>
                      _jsxs(
                        React.Fragment,
                        {
                          children: [
                            item.section &&
                              _jsx("div", {
                                className:
                                  "px-4 pl-6 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500",
                                children: item.section,
                              }),
                            _jsx(NavLink, {
                              to: item.to,
                              end: item.to === "/",
                              className: ({ isActive }) =>
                                `sidebar-link block rounded-lg px-4 py-2 pl-6 text-sm transition-colors ${(item.to.includes("?") ? `${pathname}${search}` === item.to : isActive && !search) ? "bg-gradient-to-r from-cyan-600 to-emerald-500 text-white font-semibold border-l-4 border-cyan-200 shadow-sm" : "text-slate-300 border-l-4 border-transparent hover:bg-cyan-400/10 hover:border-cyan-400/60 hover:text-white"}`,
                              children: _jsxs("span", { className: "flex min-w-0 items-center gap-3", children: [
                                _jsx(NavIcon, { name: iconForItem(item.label), item: true }),
                                _jsx("span", { className: "truncate", children: item.label })
                              ] }),
                            }),
                          ],
                        },
                        item.to,
                      ),
                    ),
                  }),
              ],
            },
            group.label,
          );
        }),
      }),
      _jsxs("div", {
        className:
          "mt-auto border-t border-white/10 bg-transparent p-4",
        children: [
          _jsx("div", {
            className:
              "mb-2 text-[9px] uppercase tracking-[.2em] text-slate-500",
            children: "Operating Organization",
          }),
          _jsx(CompanyBrand, {
            company: company,
            compact: true,
            inverse: true,
          }),
        ],
      }),
    ],
  });
}
