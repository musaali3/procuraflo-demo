import { printControlledCopySet, COMPANY_COPY } from '../utils/printCopies';
import { PRODUCT_BRAND } from '../config/brand';
import {
  jsx as _jsx,
  jsxs as _jsxs,
  Fragment as _Fragment,
} from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import client from "../api/client";
import { useAuth } from "../contexts/AuthContext";
import { useBranding } from "../contexts/BrandingContext";
import StatusBadge from "../components/StatusBadge";
import { downloadElementPdf } from "../utils/downloadPdf";
import { CompanyLogo } from "../components/Branding";
import { brandedSpreadsheetHtml } from "../utils/brandedSpreadsheet";
import useAutoRefresh from "../hooks/useAutoRefresh";
import WorkforceSetupPage from "./WorkforceSetupPage";
const scheduleHours = row => row.closed_periods?.length ? workingHours(row) || "Closed" : `${row.override_start_time || row.shift_start || "-"} - ${row.override_end_time || row.shift_end || "-"}`;
const workingHours = row => (row.working_intervals || []).map(interval => `${interval.start.slice(11)}-${interval.end.slice(11)}`).join(", ");
const shiftTone = {
  MORNING: "bg-amber-50 text-amber-800 border-amber-200",
  AFTERNOON: "bg-sky-50 text-sky-800 border-sky-200",
  EVENING: "bg-cyan-50 text-cyan-800 border-cyan-200",
  OFF: "bg-slate-100 text-slate-700 border-slate-200",
  HOLIDAY: "bg-rose-50 text-rose-800 border-rose-200",
};
export default function WorkCalendarPage(props) {
  const { user } = useAuth();
  const [section, setSection] = useState("calendar");
  if (!props.admin || user?.role !== "SupplyChainManager") return _jsx(WorkCalendarView, { ...props });
  return _jsxs("div", { children: [
    _jsx("div", { className: "mb-4 flex flex-wrap gap-2", role: "tablist", "aria-label": "Calendar Management", children: ["calendar", "holidays"].map(value => _jsx("button", {
      type: "button", role: "tab", "aria-selected": section === value,
      className: section === value ? "btn-primary" : "btn-secondary",
      onClick: () => setSection(value), children: value === "calendar" ? "Work Calendar" : "Holidays",
    }, value)) }),
    section === "holidays" ? _jsx(WorkforceSetupPage, { section: "holidays" }) : _jsx(WorkCalendarView, { ...props }),
  ] });
}
function WorkCalendarView({ scope, admin = false }) {
  const { user } = useAuth(),
    { company } = useBranding();
  const canAdjustCalendar = admin && user?.role === "SupplyChainManager";
  const [period, setPeriod] = useState("current"),
    [view, setView] = useState("calendar"),
    [adminScope, setAdminScope] = useState("Warehouse"),
    [warehouseId, setWarehouseId] = useState(""),
    [data, setData] = useState({ rows: [], warehouses: [] }),
    [refs, setRefs] = useState({ shifts: [] }),
    [error, setError] = useState(""),
    [editing, setEditing] = useState(),
    [detailDate, setDetailDate] = useState("");
  const effectiveScope = scope || adminScope;
  const effectiveWarehouseId =
    effectiveScope === "Warehouse" ? warehouseId : "";
  const adjustmentShifts = editing
    ? refs.shifts.filter((shift) =>
        editing.warehouse_id == null
          ? shift.warehouse_id == null
          : Number(shift.warehouse_id) === Number(editing.warehouse_id),
      )
    : [];
  const load = () =>
    Promise.all([
      client.get("/workforce/calendar", {
        params: {
          scope: effectiveScope,
          period,
          ...(effectiveWarehouseId
            ? { warehouse_id: effectiveWarehouseId }
            : {}),
        },
      }),
      client.get("/workforce/reference"),
    ])
      .then(([c, r]) => {
        setData(c.data);
        setRefs(r.data);
        setError("");
      })
      .catch((e) =>
        setError(e.response?.data?.error || "Unable to load workday calendar"),
      );
  useAutoRefresh(load);
  useEffect(() => {
    if (effectiveScope === "Procurement" && warehouseId) setWarehouseId("");
    load();
  }, [period, effectiveScope, effectiveWarehouseId]);
  const days = useMemo(() => {
    if (!data.range?.from || !data.range?.to) return [];
    const grouped = data.rows.reduce((a, r) => {
        var _a;
        (a[(_a = r.calendar_date)] ?? (a[_a] = [])).push(r);
        return a;
      }, {}),
      out = [];
    for (
      let cursor = new Date(`${data.range.from}T00:00:00Z`),
        end = new Date(`${data.range.to}T00:00:00Z`);
      cursor <= end;
      cursor.setUTCDate(cursor.getUTCDate() + 1)
    ) {
      const date = cursor.toISOString().slice(0, 10);
      out.push({ date, rows: grouped[date] || [] });
    }
    return out;
  }, [data.rows, data.range?.from, data.range?.to]);
  const detailed = data.rows;
  async function generate() {
    await client.post("/workforce/calendar/generate", {
      from: data.range?.from,
      to: data.range?.to,
    });
    load();
  }
  async function publish(status) {
    await client.put("/workforce/calendar/bulk-status", {
      from: data.range.from,
      to: data.range.to,
      status,
      scope: effectiveScope,
      warehouse_id: effectiveWarehouseId || null,
    });
    load();
  }
  async function save() {
    try {
      await client.put(`/workforce/calendar/${editing.id}`, {
        ...editing,
        unlock: editing.status === "LOCKED",
      });
      setEditing(null);
      load();
    } catch (e) {
      setError(e.response?.data?.error || "Adjustment failed");
    }
  }
  async function audit(action_type, format) {
    await client.post("/workforce/calendar/export-audit", {
      action_type,
      format,
      department_scope: effectiveScope,
      warehouse_id: effectiveWarehouseId || null,
      date_from: data.range.from,
      date_to: data.range.to,
    });
  }
  async function prepareCalendarOutput() {
    if (view !== "calendar") setView("calendar");
    await new Promise((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(resolve)),
    );
    if (document.fonts?.ready) await document.fonts.ready;
    return document.getElementById("work-calendar-print");
  }
  async function print() {
    await audit("PRINT", "PDF");
    await prepareCalendarOutput();
    await printControlledCopySet('work-calendar-print', [COMPANY_COPY], {orientation:'landscape'});
  }
  async function pdf() {
    await audit("DOWNLOAD", "PDF");
    const element = await prepareCalendarOutput();
    element?.classList.add("calendar-export-mode");
    try {
      await new Promise((resolve) => requestAnimationFrame(resolve));
      await downloadElementPdf(
        "work-calendar-print",
        `${effectiveScope}-workday-calendar-${data.range.from}`,
        { orientation: "landscape" },
      );
    } finally {
      element?.classList.remove("calendar-export-mode");
    }
  }
  async function csv() {
    await audit("DOWNLOAD", "CSV");
    const keys = [
      "calendar_date",
      "employee_code",
      "employee_name",
      "role_code",
      "warehouse_name",
      "shift_label",
      "shift_start",
      "shift_end",
      "working_minutes",
      "work_periods_json",
      "day_type",
      "operating_status",
      "display_label",
      "holiday_name",
      "remarks",
      "availability_status",
      "reports_to_name",
      "status",
    ];
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const blob = new Blob(
      [
        [
          [...keys, "generated_by"].join(","),
          ...data.rows.map((r) => [...keys.map((k) => esc(r[k])), esc(PRODUCT_BRAND.name)].join(",")),
        ].join("\r\n"),
      ],
      { type: "text/csv" },
    );
    const url = URL.createObjectURL(blob),
      a = document.createElement("a");
    a.href = url;
    a.download = `Procuraflo-${effectiveScope}-calendar-${data.range.from}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }
  async function excel() {
    await audit("DOWNLOAD", "EXCEL");
    const keys = Object.keys(data.rows[0] || {}).filter(
      (k) => !["id", "created_by", "updated_by"].includes(k),
    );
    const tableHtml = `<table><tr>${keys.map((k) => `<th>${k.replace(/_/g, " ")}</th>`).join("")}</tr>${data.rows.map((r) => `<tr>${keys.map((k) => `<td>${r[k] ?? ""}</td>`).join("")}</tr>`).join("")}</table>`;
    const html = brandedSpreadsheetHtml({ companyName: company.company_name, title: `${effectiveScope} Work Calendar`, generatedBy: user?.full_name, filters: `${data.range.from} to ${data.range.to}`, tableHtml });
    const url = URL.createObjectURL(
        new Blob([html], { type: "application/vnd.ms-excel" }),
      ),
      a = document.createElement("a");
    a.href = url;
    a.download = `${effectiveScope}-calendar-${data.range.from}.xls`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return _jsxs("div", {
    children: [
      _jsxs("div", {
        className:
          "mb-5 flex flex-wrap items-start justify-between gap-3 print:hidden",
        children: [
          _jsxs("div", {
            children: [
              _jsx("h1", {
                className: "text-2xl font-bold",
                children: admin
                  ? "Employee Calendar Management"
                  : `${scope} Workday Calendar`,
              }),
              _jsx("p", {
                className: "text-sm text-slate-500",
                children:
                  "Professional shift calendar with warehouse isolation, availability, rest days and reporting relationships.",
              }),
            ],
          }),
          _jsxs("div", {
            className: "flex flex-wrap gap-2",
            children: [
              _jsx("button", {
                className: "btn-secondary",
                onClick: print,
                children: "Print Calendar",
              }),
              _jsx("button", {
                className: "btn-secondary",
                onClick: pdf,
                children: "Download PDF",
              }),
              _jsx("button", {
                className: "btn-secondary",
                onClick: excel,
                children: "Excel",
              }),
              _jsx("button", {
                className: "btn-secondary",
                onClick: csv,
                children: "CSV",
              }),
            ],
          }),
        ],
      }),
      _jsxs("div", {
        className: "card mb-4 flex flex-wrap gap-2 p-3 print:hidden",
        children: [
          admin &&
            _jsxs("select", {"data-field": "adminScope", 
              className: "input max-w-48",
              value: adminScope,
              onChange: (e) => {
                setAdminScope(e.target.value);
                setWarehouseId("");
              },
              children: [
                _jsx("option", { children: "Warehouse" }),
                _jsx("option", { children: "Procurement" }),
              ],
            }),
          effectiveScope === "Warehouse" &&
            data.warehouses?.length > 0 &&
            _jsxs("select", {"data-field": "warehouseId", 
              className: "input max-w-64",
              value: warehouseId,
              onChange: (e) => setWarehouseId(e.target.value),
              children: [
                _jsx("option", {
                  value: "",
                  children: "All authorized warehouses",
                }),
                data.warehouses.map((w) =>
                  _jsxs(
                    "option",
                    {
                      value: w.id,
                      children: [w.warehouse_code, " \u2014 ", w.name],
                    },
                    w.id,
                  ),
                ),
              ],
            }),
          _jsx("button", {
            className: period === "current" ? "btn-primary" : "btn-secondary",
            onClick: () => setPeriod("current"),
            children: "Current 15 Days",
          }),
          _jsx("button", {
            className: period === "next" ? "btn-primary" : "btn-secondary",
            onClick: () => setPeriod("next"),
            children: "Next 15 Days",
          }),
          _jsx("button", {
            className: view === "calendar" ? "btn-primary" : "btn-secondary",
            onClick: () => setView("calendar"),
            children: "Calendar View",
          }),
          _jsx("button", {
            className: view === "roster" ? "btn-primary" : "btn-secondary",
            onClick: () => setView("roster"),
            children: "Detailed Roster",
          }),
          admin &&
            _jsxs(_Fragment, {
              children: [
                _jsx("button", {
                  className: "btn-secondary",
                  onClick: generate,
                  children: "Generate Monthly 15-Day Cycles",
                }),
                ["PUBLISHED"].map((s) =>
                  _jsx(
                    "button",
                    {
                      className: "btn-secondary",
                      onClick: () => publish(s),
                      children: s,
                    },
                    s,
                  ),
                ),
              ],
            }),
          _jsxs("span", {
            className: "ml-auto self-center text-sm text-slate-500",
            children: [data.range?.from, " \u2014 ", data.range?.to],
          }),
        ],
      }),
      error &&
        _jsx("div", {"data-error-message": true, role: "alert", 
          className: "mb-3 rounded bg-rose-50 p-3 text-rose-700",
          children: error,
        }),
      !error &&
        !admin &&
        data.range &&
        !data.rows.length &&
        _jsx("div", {
          className:
            "mb-4 rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-900 shadow-sm",
          children: _jsxs("div", {
            className: "flex items-start gap-3",
            children: [
              _jsx("span", {
                className:
                  "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-200 font-bold",
                children: "!",
              }),
              _jsxs("div", {
                children: [
                  _jsx("h2", {
                    className: "font-semibold",
                    children: "Workday calendar not published yet",
                  }),
                  _jsxs("p", {
                    className: "mt-1 text-sm",
                    children: [
                      "The Supply Chain Manager is preparing the schedule for ",
                      data.range.from,
                      " to ",
                      data.range.to,
                      ". Draft and provisional schedules remain confidential until reviewed and published. Please check again later.",
                    ],
                  }),
                ],
              }),
            ],
          }),
        }),
      _jsxs("article", {
        id: "work-calendar-print",
        className:
          "work-calendar-document controlled-print-document rounded-xl border border-slate-200 bg-white p-5",
        children: [
          _jsxs("header", {
            className:
              "mb-5 flex items-center justify-between border-b border-blue-100 pb-4",
            children: [
              _jsxs("div", {
                className: "flex items-center gap-4",
                children: [
                  _jsx(CompanyLogo, { company: company, size: "report" }),
                  _jsxs("div", {
                    children: [
                      _jsx("div", {
                        className: "text-xl font-bold text-slate-900",
                        children: company.company_name,
                      }),
                      _jsx("div", {
                        className:
                          "text-xs font-semibold uppercase tracking-[.2em] text-blue-600",
                        children: "Procuraflo",
                      }),
                      _jsxs("h2", {
                        className: "mt-1 text-lg font-semibold",
                        children: [effectiveScope, " Workday Calendar"],
                      }),
                    ],
                  }),
                ],
              }),
              _jsxs("div", {
                className: "text-right text-xs text-slate-600",
                children: [
                  _jsxs("div", {
                    children: [
                      _jsx("strong", { children: "Period:" }),
                      " ",
                      data.range?.from,
                      " \u2014 ",
                      data.range?.to,
                    ],
                  }),
                  _jsxs("div", {
                    children: [
                      _jsx("strong", { children: "Warehouse:" }),
                      " ",
                      data.warehouses?.find((w) => String(w.id) === warehouseId)
                        ?.name || "All authorized",
                    ],
                  }),
                  _jsxs("div", {
                    children: [
                      _jsx("strong", { children: "Generated:" }),
                      " ",
                      new Date().toLocaleString(),
                    ],
                  }),
                  _jsxs("div", {
                    children: [
                      _jsx("strong", { children: "Generated By:" }),
                      " ",
                      user?.full_name,
                    ],
                  }),
                ],
              }),
            ],
          }),
          view === "calendar"
            ? _jsxs(_Fragment, {
                children: [
                  _jsx("div", {
                    className:
                      "grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5",
                    children: days.map((day) => {
                      const counts = (code) =>
                        day.rows.filter((r) =>
                          code === "OFF"
                            ? !["WORKDAY", "HOLIDAY_WORKING"].includes(r.day_type)
                            : (r.shift_code === code || r.shift_code?.endsWith(`-${code}`) || r.shift_code?.endsWith(`-SHIFT-${code === "MORNING" ? 1 : code === "AFTERNOON" ? 2 : 3}`)) && ["WORKDAY", "HOLIDAY_WORKING"].includes(r.day_type),
                        ).length;
                      return _jsxs(
                        "button",
                        {
                          type: "button",
                          onClick: () => setDetailDate(day.date),
                          onDoubleClick: () => setDetailDate(day.date),
                          title: "Click to open the complete daily employee and shift roster.",
                          className: "calendar-date-card print-avoid-break rounded-xl border border-slate-200 p-2.5 text-left shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-blue-400 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-blue-300",
                          children: [
                            _jsxs("div", {
                              className:
                                "mb-2 flex items-start justify-between border-b pb-1.5",
                              children: [
                                _jsxs("div", {
                                  children: [
                                    _jsx("strong", {
                                      className: "text-base",
                                      children: new Date(
                                        `${day.date}T00:00:00`,
                                      ).toLocaleDateString(undefined, {
                                        day: "2-digit",
                                        month: "short",
                                      }),
                                    }),
                                    _jsx("div", {
                                      className:
                                        "text-xs uppercase text-slate-500",
                                      children: new Date(
                                        `${day.date}T00:00:00`,
                                      ).toLocaleDateString(undefined, {
                                        weekday: "short",
                                      }),
                                    }),
                                  ],
                                }),
                                _jsx(StatusBadge, {
                                  status: day.rows[0]?.status,
                                }),
                              ],
                            }),
                            _jsx("div", {
                              className: "grid grid-cols-4 gap-1",
                              children: ["MORNING", "AFTERNOON", "EVENING", "OFF"].map(
                                (code) =>
                                  _jsxs(
                                    "div",
                                    {
                                      className: `flex min-w-0 flex-col items-center rounded border px-1 py-1 text-[9px] font-semibold ${shiftTone[code]}`,
                                      title: code[0] + code.slice(1).toLowerCase(),
                                      children: [
                                        _jsx("span", { className: "truncate uppercase", children: code.slice(0, 3) }),
                                        _jsx("strong", { className: "text-xs", children: counts(code) }),
                                      ],
                                    },
                                    code,
                                  ),
                              ),
                            }),
                            _jsxs("div", {
                              className: "mt-2 space-y-1",
                              children: [
                                day.rows.map((r, rowIndex) =>
                                    _jsxs(
                                      "div",
                                      {
                                        className: `calendar-card-employee ${rowIndex >= 3 ? "calendar-card-overflow hidden" : "grid"} grid-cols-[minmax(0,1fr)_auto] gap-2 rounded-md border border-slate-100 bg-white/80 px-2 py-1 text-[11px] ${user?.full_name === r.employee_name ? "font-bold text-blue-700" : "text-slate-600"}`,
                                        children: [
                                          _jsxs("span", { className: "min-w-0", children: [_jsx("span", { className: "block truncate font-semibold", children: r.employee_name }), _jsxs("span", { className: "block truncate text-[9px] text-slate-400", children: [r.employee_code, " · ", String(r.role_code || "").replace(/([a-z])([A-Z])/g, "$1 $2")] })] }),
                                          _jsxs("span", { className: "text-right", children: [_jsx("span", { className: "block font-semibold", children: r.display_label || r.shift_code || r.day_type }), _jsxs("span", { className: "block whitespace-nowrap text-[9px] text-slate-400", children: ["WORKDAY", "HOLIDAY_WORKING"].includes(r.day_type) ? [scheduleHours(r), ...(r.closed_breaks || []).map(period => _jsx("span", { className: "block text-amber-700", children: `Break ${period.start.slice(11)}-${period.end.slice(11)}` }, period.start))] : [r.operating_status !== r.display_label ? r.operating_status : "", r.holiday_notes ? ` ${r.holiday_notes}` : ""] })] }),
                                        ],
                                      },
                                      r.id,
                                    ),
                                  ),
                                !day.rows.length && _jsx("div", { className: "rounded bg-slate-50 px-2 py-3 text-center text-[10px] text-slate-400", children: "No employees scheduled" }),
                                day.rows.length > 3 && _jsxs("div", { className: "calendar-screen-only rounded-md bg-blue-50 px-2 py-1 text-center text-[10px] font-semibold text-blue-700", children: ["+", day.rows.length - 3, " more · click for details"] }),
                              ],
                            }),
                          ],
                        },
                        day.date,
                      );
                    }),
                  }),
                ],
              })
            : _jsx(Roster, {
                rows: detailed,
                admin: admin,
                user: user,
                adjust: (r) => setEditing({ ...r, reason: "" }),
              }),
          _jsxs("footer", {
            className:
              "mt-5 flex justify-between border-t border-slate-200 pt-3 text-[10px] text-slate-500",
            children: [
              _jsxs("span", {
                children: [
                  "Generated By: ",
                  user?.full_name,
                  " \u00B7 Generated On: ",
                  new Date().toLocaleString(),
                ],
              }),
            ],
          }),
        ],
      }),
      detailDate &&
        _jsx("div", {
          className:
            "fixed inset-0 z-[115] flex items-center justify-center bg-slate-950/60 p-4 print:hidden",
          onMouseDown: (event) => {
            if (event.target === event.currentTarget) setDetailDate("");
          },
          children: _jsxs("div", {
            className:
              "card max-h-[88vh] w-full max-w-6xl overflow-hidden p-0 shadow-2xl",
            children: [
              _jsxs("div", {
                className:
                  "flex items-center justify-between border-b border-blue-100 bg-gradient-to-r from-blue-50 to-sky-50 px-5 py-4",
                children: [
                  _jsxs("div", {
                    children: [
                      _jsx("h2", {
                        className: "text-lg font-bold text-blue-950",
                        children: "Daily Employee Shift Roster",
                      }),
                      _jsx("p", {
                        className: "text-sm text-slate-600",
                        children: new Date(
                          `${detailDate}T00:00:00`,
                        ).toLocaleDateString(undefined, {
                          weekday: "long",
                          day: "2-digit",
                          month: "long",
                          year: "numeric",
                        }),
                      }),
                    ],
                  }),
                  _jsx("button", {
                    type: "button",
                    className: "btn-secondary",
                    onClick: () => setDetailDate(""),
                    children: "Close",
                  }),
                ],
              }),
              _jsx("div", {
                className: "max-h-[calc(88vh-82px)] overflow-auto p-4",
                children: _jsx(Roster, {
                  rows: data.rows.filter(
                    (row) => row.calendar_date === detailDate,
                  ),
                  admin: admin,
                  user: user,
                  adjust: (row) => {
                    setDetailDate("");
                    setEditing({ ...row, reason: "" });
                  },
                }),
              }),
            ],
          }),
        }),
      editing && canAdjustCalendar &&
        createPortal(_jsx("div", {
          className:
            "fixed inset-0 z-[120] flex items-center justify-center overflow-y-auto overscroll-contain bg-slate-950/55 p-3 backdrop-blur-sm print:hidden sm:p-6",
          role: "dialog",
          "aria-modal": "true",
          "aria-label": "Manual Calendar Adjustment",
          children: _jsxs("div", {
            className: "card mx-auto my-auto w-full max-w-lg space-y-3 p-5 shadow-2xl",
            children: [
              _jsx("h2", {
                className: "font-bold",
                children: "Manual Calendar Adjustment",
              }),
              _jsxs("label", {
                className: "block text-sm",
                children: [
                  "Work Status",
                  _jsx("select", {"data-field": "day_type", 
                    className: "input mt-1",
                    value: editing.day_type,
                    onChange: (e) =>
                      setEditing({ ...editing, day_type: e.target.value }),
                    children: [
                      "WORKDAY",
                      "OFF",
                      "HOLIDAY",
                      "HOLIDAY_WORKING",
                    ].map((x) => _jsx("option", { children: x }, x)),
                  }),
                ],
              }),
              _jsxs("label", {
                className: "block text-sm",
                children: [
                  "Shift",
                  _jsxs("select", {"data-field": "shift_id", 
                    className: "input mt-1",
                    value: editing.shift_id || "",
                    onChange: (e) =>
                      setEditing({
                        ...editing,
                        shift_id: Number(e.target.value) || null,
                      }),
                    children: [
                      _jsx("option", { value: "", children: "No shift" }),
                      adjustmentShifts.map((s) =>
                        _jsx(
                          "option",
                          {
                            value: s.id,
                            children: `${s.shift_label} (${String(s.start_time).slice(0, 5)}–${String(s.end_time).slice(0, 5)})`,
                          },
                          s.id,
                        ),
                      ),
                    ],
                  }),
                ],
              }),
              _jsxs("div", {
                className: "grid grid-cols-2 gap-2",
                children: [
                  _jsxs("label", {
                    className: "text-sm",
                    children: [
                      "Override Start",
                      _jsx("input", {"data-field": "override_start_time", 
                        type: "time",
                        className: "input mt-1",
                        value: editing.override_start_time || "",
                        onChange: (e) =>
                          setEditing({
                            ...editing,
                            override_start_time: e.target.value,
                          }),
                      }),
                    ],
                  }),
                  _jsxs("label", {
                    className: "text-sm",
                    children: [
                      "Override End",
                      _jsx("input", {"data-field": "override_end_time", 
                        type: "time",
                        className: "input mt-1",
                        value: editing.override_end_time || "",
                        onChange: (e) =>
                          setEditing({
                            ...editing,
                            override_end_time: e.target.value,
                          }),
                      }),
                    ],
                  }),
                ],
              }),
              _jsxs("label", {
                className: "block text-sm",
                children: [
                  "Mandatory Reason",
                  _jsx("input", {"data-field": "reason", 
                    className: "input mt-1",
                    value: editing.reason,
                    onChange: (e) =>
                      setEditing({ ...editing, reason: e.target.value }),
                  }),
                ],
              }),
              _jsxs("label", {
                className: "block text-sm",
                children: [
                  "Remarks",
                  _jsx("textarea", {"data-field": "remarks", 
                    className: "input mt-1",
                    value: editing.remarks || "",
                    onChange: (e) =>
                      setEditing({ ...editing, remarks: e.target.value }),
                  }),
                ],
              }),
              _jsxs("div", {
                className: "flex justify-end gap-2",
                children: [
                  _jsx("button", {
                    className: "btn-secondary",
                    onClick: () => setEditing(null),
                    children: "Cancel",
                  }),
                  _jsx("button", {
                    className: "btn-primary",
                    onClick: save,
                    children: "Save Protected Override",
                  }),
                ],
              }),
            ],
          }),
        }), document.body),
    ],
  });
}
function Roster({ rows, admin, user, adjust }) {
  const canAdjustCalendar = admin && user?.role === "SupplyChainManager";
  const [sort, setSort] = useState({ key: "employee_name", direction: "asc" });
  const compare = (left, right) => String(left ?? "").localeCompare(String(right ?? ""), undefined, { numeric: true, sensitivity: "base" }) * (sort.direction === "asc" ? 1 : -1);
  const sortHeader = (key, label) => _jsx("th", {
    "aria-sort": sort.key === key ? (sort.direction === "asc" ? "ascending" : "descending") : "none",
    children: _jsxs("button", {
      type: "button",
      className: "table-sort-button",
      onClick: () => setSort(current => current.key === key ? { key, direction: current.direction === "asc" ? "desc" : "asc" } : { key, direction: "asc" }),
      children: [_jsx("span", { children: label }), _jsx("span", { className: "table-sort-indicator", "aria-hidden": "true", children: sort.key === key ? (sort.direction === "asc" ? "▲" : "▼") : "↕" })],
    }),
  });
  const groupedRows = Array.from(
    rows.reduce((groups, row) => {
      const date = row.calendar_date || "Unscheduled";
      groups.set(date, [...(groups.get(date) || []), row]);
      return groups;
    }, new Map()),
  ).sort(([left], [right]) => String(left).localeCompare(String(right)) * (sort.key === "calendar_date" && sort.direction === "desc" ? -1 : 1)).map(([date,dateRows]) => [date, sort.key === "calendar_date" ? dateRows : [...dateRows].sort((left,right) => compare(left[sort.key],right[sort.key]))]);
  return _jsx("div", {
    className: "overflow-x-auto",
    children: _jsxs("table", {
      className: "table-base",
      children: [
        _jsx("thead", {
          children: _jsxs("tr", {
            children: [
              sortHeader("calendar_date", "Date"),
              sortHeader("employee_name", "Employee"),
              sortHeader("role_code", "Role"),
              sortHeader("warehouse_name", "Warehouse"),
              sortHeader("reports_to_name", "Reports To"),
              sortHeader("shift_start", "Shift"),
              sortHeader("shift_start", "Time"),
              sortHeader("availability_status", "Work / Availability"),
              sortHeader("assignment_source", "Source"),
              sortHeader("status", "Status"),
              canAdjustCalendar && _jsx("th", { children: "Action" }),
            ],
          }),
        }),
        _jsx("tbody", {
          children: groupedRows.map(([date, dateRows]) =>
            _jsxs(_Fragment, {
              children: [
                _jsx("tr", {
                  className: "roster-date-group border-y border-blue-200 bg-gradient-to-r from-blue-50 to-sky-50",
                  children: _jsx("td", {
                    colSpan: canAdjustCalendar ? 11 : 10,
                    className: "px-3 py-2",
                    children: _jsxs("div", {
                      className: "flex flex-wrap items-center justify-between gap-2",
                      children: [
                        _jsxs("div", {
                          children: [
                            _jsx("strong", {
                              className: "text-sm text-blue-950",
                              children: date === "Unscheduled" ? date : new Date(`${date}T00:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "2-digit", month: "long", year: "numeric" }),
                            }),
                            _jsxs("span", { className: "ml-2 text-xs text-slate-500", children: ["· ", dateRows.length, " employee", dateRows.length === 1 ? "" : "s"] }),
                          ],
                        }),
                        _jsx("span", { className: "rounded-full bg-white px-2.5 py-1 text-[10px] font-semibold text-blue-700 shadow-sm", children: date }),
                      ],
                    }),
                  }),
                }),
                dateRows.map((r) =>
            _jsxs(
              "tr",
              {
                className:
                  user?.full_name === r.employee_name ? "bg-cyan-50" : "",
                children: [
                  _jsx("td", { children: r.calendar_date }),
                  _jsxs("td", {
                    children: [
                      _jsx("strong", { children: r.employee_name }),
                      _jsx("div", {
                        className: "text-xs text-slate-400",
                        children: r.employee_code,
                      }),
                    ],
                  }),
                  _jsx("td", {
                    children: String(r.role_code).replace(
                      /([a-z])([A-Z])/g,
                      "$1 $2",
                    ),
                  }),
                  _jsx("td", { children: r.warehouse_name || "—" }),
                  _jsx("td", {
                    children: r.reports_to_name
                      ? _jsxs(_Fragment, {
                          children: [
                            r.reports_to_name,
                            _jsx("div", {
                              className: "text-[10px] text-slate-400",
                              children: String(r.reports_to_role || "").replace(
                                /([a-z])([A-Z])/g,
                                "$1 $2",
                              ),
                            }),
                          ],
                        })
                      : "—",
                  }),
                  _jsx("td", { children: r.display_label || r.shift_label || "—" }),
                  _jsxs("td", {
                    children: ["WORKDAY", "HOLIDAY_WORKING"].includes(r.day_type) ? [
                      scheduleHours(r),
                      r.working_minutes != null && _jsx("div", { className: "text-xs text-slate-600", children: `${(r.working_minutes / 60).toFixed(2)} working hours` }),
                      (r.closed_breaks || []).map(period => _jsx("div", { className: "text-xs text-amber-700", children: `Closed / break: ${period.start.slice(11)}-${period.end.slice(11)}` }, period.start)),
                    ] : [r.operating_status || "Off Day / Closed", _jsx("div", { className: "text-xs text-slate-500", children: r.holiday_notes || r.remarks || "" })],
                  }),
                  _jsxs("td", {
                    children: [
                      _jsx("div", { children: r.operating_status || r.day_type }),
                      _jsx("div", {
                        className: "text-[10px] text-slate-500",
                        children: r.closed_periods?.length ? r.closed_periods.map(period => `Closed ${period.start.slice(11)}-${period.end.slice(11)}: ${period.reason}`).join("; ") : r.availability_status || "Available",
                      }),
                    ],
                  }),
                  _jsxs("td", {
                    children: [
                      r.assignment_source,
                      r.manual_override_yn ? " · Manual Adjustment" : "",
                    ],
                  }),
                  _jsx("td", {
                    children: _jsx(StatusBadge, { status: r.status }),
                  }),
                  canAdjustCalendar &&
                    _jsx("td", {
                      children: _jsx("button", {
                        className: "btn-secondary",
                        onClick: () => adjust(r),
                        children: "Adjust",
                      }),
                    }),
                ],
              },
              r.id,
            ),
                ),
              ],
            }, date),
          ),
        }),
      ],
    }),
  });
}
