import {
  jsx as _jsx,
  jsxs as _jsxs,
  Fragment as _Fragment,
} from "react/jsx-runtime";
import { useEffect, useState } from "react";
import client from "../api/client";
import { RecordDetailModal } from "../components/DataTable";
import useAutoRefresh from "../hooks/useAutoRefresh";
import ProcurementSchedulePage from "./ProcurementSchedulePage.jsx";
const HOLIDAY_COLUMNS = ["holiday_name", "country_code", "holiday_date", "holiday_end_date", "observed_date", "holiday_type", "applicability", "region", "active_yn"];
const REFERENCE_TABS = [
  "Countries",
  "Cities",
  "Currencies",
  "Exchange Rates",
];
const WORKFORCE_TABS = [
  "Shifts",
  "Availability",
  "Coverage",
  "Helper Supervision",
];
function shiftMinutes(start, end) {
  if (!/^\d{2}:\d{2}$/.test(String(start || "")) || !/^\d{2}:\d{2}$/.test(String(end || ""))) return 0;
  const [sh, sm] = start.split(":").map(Number), [eh, em] = end.split(":").map(Number);
  return (((eh * 60 + em) - (sh * 60 + sm)) + 1440) % 1440 || 1440;
}
function endAfter(start, duration) {
  if (!/^\d{2}:\d{2}$/.test(String(start || ""))) return "";
  const [hours, minutes] = start.split(":").map(Number);
  const end = (hours * 60 + minutes + duration) % 1440;
  return `${String(Math.floor(end / 60)).padStart(2, "0")}:${String(end % 60).padStart(2, "0")}`;
}
export default function WorkforceSetupPage({ section = "workforce" }) {
  const tabs = section === "reference" ? REFERENCE_TABS : section === "holidays" ? ["Holidays"] : WORKFORCE_TABS;
  const [data, setData] = useState({
    countries: [],
    currencies: [],
    exchange_rates: [],
    holidays: [],
    shifts: [],
    availability: [],
    coverage: [],
    employees: [],
    departments: [],
  });
  const [tab, setTab] = useState(tabs[0]),
    [form, setForm] = useState({}),
    [shiftDrafts, setShiftDrafts] = useState([]),
    [holidayPreview, setHolidayPreview] = useState(null),
    [ratePreview, setRatePreview] = useState(null),
    [referenceDetail, setReferenceDetail] = useState(null),
    [message, setMessage] = useState(""),
    [error, setError] = useState("");
  useEffect(() => {
    setTab(tabs[0]);
    setForm(section === "holidays" ? { year: new Date().getFullYear(), holiday_type: "Government Public Holiday", day_scope: "FULL_DAY", applicability: "ALL" } : {});
    setHolidayPreview(null);
    setRatePreview(null);
    setMessage("");
    setError("");
  }, [section]);
  const load = () =>
    Promise.all([
      client.get("/workforce/reference"),
      client.get("/workforce/availability"),
      client.get("/workforce/coverage"),
      client.get("/masters/employee-directory"),
      client.get("/masters/departments"),
    ]).then(([r, a, c, e, d]) =>
      setData({
        ...r.data,
        availability: a.data,
        coverage: c.data,
        employees: e.data,
        departments: d.data,
      }),
    );
  useAutoRefresh(load);
  useEffect(() => {
    load().catch((e) =>
      setError(e.response?.data?.error || "Unable to load setup data"),
    );
  }, []);
  async function save() {
    try {
      let response;
      if (tab === "Shifts") {
        setShiftDrafts((current) => [...current.filter((item) => item.id !== form.id), { ...form }]);
        setMessage("Shift change saved temporarily. Update any adjoining shifts needed to remove gaps or overlaps, then confirm all temporary changes.");
        setError("");
        return;
      }
      else if (tab === "Helper Supervision")
        await client.put("/workforce/helper-supervisor-roles", {
          roles: form.roles || data.helper_supervisor_roles,
        });
      else {
        const endpoint = {
          Countries: "countries",
          Cities: "cities",
          Currencies: "currencies",
          "Exchange Rates": "exchange-rates",
          Holidays: "holidays",
          Availability: "availability",
          Coverage: "coverage",
        };
        const payload = tab === "Holidays"
          ? { ...form, country_code: form.country_code || data.company?.country_code, holiday_type: form.holiday_type || "Government Public Holiday", day_scope: form.day_scope || "FULL_DAY" }
          : form;
        if (tab === "Holidays" && form.id) await client.put(`/workforce/holidays/${form.id}`, payload);
        else await client.post(`/workforce/${endpoint[tab]}`, payload);
      }
      setForm({});
      setMessage(response?.data?.message || `${tab} saved successfully.`);
      setError("");
      await load();
    } catch (e) {
      setError(e.response?.data?.error || "Unable to save record");
    }
  }
  async function applyShiftDrafts() {
    try {
      const response = await client.put("/workforce/shifts/batch", { shifts: shiftDrafts });
      setShiftDrafts([]);setForm({});setError("");setMessage(response.data.message);await load();
    } catch (e) {
      setError(e.response?.data?.error || "The temporary shift changes cannot be applied because the schedule still has a gap or overlap.");
    }
  }
  async function synchronizeHolidays(confirm = false) {
    try {
      const country = form.country_code || data.company?.country_code,
        year = Number(form.year || new Date().getFullYear());
      if (!country) {
        setError("Select a country before synchronizing official holidays.");
        return;
      }
      const res = await client.post("/workforce/holidays/synchronize", {
        country_code: country,
        year,
        confirm,
        expected_fingerprint: confirm ? holidayPreview?.fingerprint : undefined,
      });
      if (res.data.preview) setHolidayPreview(res.data);
      else setHolidayPreview(null);
      setMessage(
        res.data.message || `${Number(res.data.created || 0)} holiday records stored.`,
      );
      setForm({ ...form, country_code: country, year });
      setError("");
      if (!res.data.preview) await load();
    } catch (e) {
      setError(e.response?.data?.error || "Holiday synchronization failed");
    }
  }
  async function synchronizeExchangeRate(confirm = false) {
    try {
      const res = await client.post("/workforce/exchange-rates/synchronize", {
        country_code: form.country_code || undefined,
        from_currency: form.from_currency || undefined,
        to_currency: form.to_currency || undefined,
        effective_date: form.effective_date || undefined,
        expiry_date: form.expiry_date || undefined,
        confirm,
        expected_rate: confirm ? ratePreview?.rate : undefined,
      });
      if (res.data.preview) setRatePreview(res.data);
      else setRatePreview(null);
      setForm({ ...form, from_currency: res.data.from_currency, to_currency: res.data.to_currency, rate: res.data.rate, effective_date: res.data.effective_date, source: res.data.source });
      setMessage(res.data.message);setError("");if (!res.data.preview) await load();
    } catch (e) { setError(e.response?.data?.error || "Authenticated exchange-rate synchronization failed"); }
  }
  async function deleteExchangeRate(row) {
    if (!window.confirm(`Deactivate ${row.from_currency} to ${row.to_currency} rate effective ${row.effective_date}? Historical evidence will remain available.`)) return;
    try { const res=await client.delete(`/workforce/exchange-rates/${row.id}`);setMessage(res.data.message);setError("");await load(); }
    catch(e){setError(e.response?.data?.error||"Unable to deactivate exchange rate");}
  }
  const rows =
    tab === "Countries"
      ? data.countries
      : tab === "Cities"
        ? data.cities
        : tab === "Currencies"
          ? data.currencies
          : tab === "Exchange Rates"
            ? data.exchange_rates
            : tab === "Holidays"
              ? data.holidays
              : tab === "Availability"
                ? data.availability
                : tab === "Coverage"
                  ? data.coverage
                  : tab === "Helper Supervision"
                    ? []
                    : data.shifts;
  const shiftScopes = [{ key: "company", warehouse: null }, ...(data.warehouses || []).map((warehouse) => ({ key: String(warehouse.id), warehouse }))];
  const shiftGroups = shiftScopes.map(({key, warehouse}) => {
    const shifts=(data.shifts || []).filter((shift)=>warehouse?Number(shift.warehouse_id)===Number(warehouse.id):shift.warehouse_id==null);
    const enabled=warehouse?!!warehouse.shifts_enabled_yn:!!data.shift_mode?.procurement?.shifts_enabled_yn;
    const standardStart=warehouse?.operating_start_time||data.shift_mode?.procurement?.operating_start_time;
    const standardEnd=warehouse?.operating_end_time||data.shift_mode?.procurement?.operating_end_time;
    return {
      key,
      name: warehouse?.name || "Company / Procurement",
      code: warehouse?.warehouse_code || "COMPANY",
      enabled,
      standardWindow: `${standardStart || "—"} - ${standardEnd || "—"} standard operating hours`,
      window: warehouse ? `${warehouse.operating_start_time} — ${warehouse.operating_end_time}` : "Company-wide shift schedule",
      shifts: [...shifts].sort((left, right) => warehouse
        ? ((shiftMinutes(warehouse.operating_start_time, left.start_time) % 1440) - (shiftMinutes(warehouse.operating_start_time, right.start_time) % 1440))
        : String(left.start_time).localeCompare(String(right.start_time))),
    };
  }).sort((left, right) => left.key === "company" ? -1 : right.key === "company" ? 1 : left.name.localeCompare(right.name));
  const holidayLocationCount = holiday => {
    const scope = holiday.applicability || "ALL";
    const country = holiday.country_code || data.company?.country_code;
    const region = String(holiday.region || "").trim().toLowerCase();
    const locations = [
      ...(scope !== "PROCUREMENT" ? (data.warehouses || []).filter(w => !holiday.warehouse_id || Number(w.id) === Number(holiday.warehouse_id)) : []),
      ...(scope !== "WAREHOUSE" && !holiday.warehouse_id && data.company ? [data.company] : []),
    ];
    return locations.filter(location => location.country_code === country && (!region || String(location.region_province || "").trim().toLowerCase() === region)).length;
  };
  const input = (key, label, type = "text") =>
    _jsxs("label", {
      className: "text-sm font-medium text-slate-700",
      children: [
        label,
        _jsx("input", {"data-field": key, 
          type: type,
          className: "input mt-1",
          value: form[key] ?? "",
          onChange: (e) => {
            const value =
              type === "number" ? Number(e.target.value) : e.target.value;
            setForm({ ...form, [key]: value });
          },
        }),
      ],
    });
  return _jsxs("div", {
    children: [
      _jsx("h1", {
        className: "text-2xl font-bold",
        children: section === "holidays" ? "Holidays" : "Country, Currency & Workforce Setup",
      }),
      _jsx("p", {
        className: "mb-4 text-sm text-slate-500",
        children:
          section === "holidays" ? "Manage holidays and synchronize official dates with the employee work calendar." : "Supply Chain Manager controls for enterprise masters, employee availability, minimum coverage and shift rules.",
      }),
      section !== "holidays" && _jsx("div", {
        className: "mb-4 flex flex-wrap gap-2",
        children: tabs.map((x) =>
          _jsx(
            "button",
            {
              className: tab === x ? "btn-primary" : "btn-secondary",
              onClick: () => {
                setTab(x);
                setForm(x === "Availability"
                  ? { availability_status: "Unavailable" }
                  : x === "Holidays"
                    ? { country_code: data.company?.country_code || "", year: new Date().getFullYear(), holiday_type: "Government Public Holiday", day_scope: "FULL_DAY", applicability: "ALL" }
                    : {});
                setMessage("");
                setError("");
              },
              children: x,
            },
            x,
          ),
        ),
      }),
      _jsxs("div", {
        className: "card mb-4 grid gap-3 p-4 md:grid-cols-4",
        children: [
          tab === "Countries" &&
            _jsxs(_Fragment, {
              children: [
                input("country_name", "Country Name"),
                input("iso_alpha2", "ISO Alpha-2"),
                input("iso_alpha3", "ISO Alpha-3"),
                _jsxs("label", {
                  className: "text-sm font-medium",
                  children: [
                    "Default Currency",
                    _jsxs("select", {"data-field": "default_currency_code", 
                      className: "input mt-1",
                      value: form.default_currency_code || "",
                      onChange: (e) =>
                        setForm({
                          ...form,
                          default_currency_code: e.target.value,
                        }),
                      children: [
                        _jsx("option", { value: "", children: "Select" }),
                        data.currencies.map((c) =>
                          _jsx("option", { children: c.currency_code }, c.id),
                        ),
                      ],
                    }),
                  ],
                }),
              ],
            }),
          tab === "Cities" &&
            _jsxs(_Fragment, {
              children: [
                _jsxs("label", {
                  className: "text-sm font-medium",
                  children: [
                    "Country",
                    _jsxs("select", {"data-field": "country_code", 
                      className: "input mt-1",
                      value: form.country_code || "",
                      onChange: (e) =>
                        setForm({ ...form, country_code: e.target.value }),
                      children: [
                        _jsx("option", { value: "", children: "Select" }),
                        data.countries.map((c) =>
                          _jsx(
                            "option",
                            { value: c.country_code, children: c.country_name },
                            c.id,
                          ),
                        ),
                      ],
                    }),
                  ],
                }),
                input("city_name", "City Name"),
                input("city_code", "City Code"),
                input("state_province_region", "State / Province / Region"),
              ],
            }),
          tab === "Currencies" &&
            _jsxs(_Fragment, {
              children: [
                input("currency_code", "Currency Code"),
                input("currency_name", "Currency Name"),
                input("currency_symbol", "Symbol"),
                input("decimal_places", "Decimal Places", "number"),
              ],
            }),
          tab === "Exchange Rates" &&
            _jsxs(_Fragment, {
              children: [
                _jsxs("label", { className: "text-sm font-medium", children: ["Country (optional)", _jsxs("select", {"data-field": "country_code",  className: "input mt-1", value: form.country_code || "", onChange: e => { const selected=data.countries.find(c=>c.country_code===e.target.value);setForm({ ...form, country_code:e.target.value, from_currency:selected?.default_currency_code||form.from_currency }); }, children: [_jsx("option", { value:"", children:"Select country or currencies directly" }), data.countries.map(c=>_jsx("option", { value:c.country_code, children:c.country_name }, c.id))] })] }),
                _jsxs("label", {
                  className: "text-sm font-medium",
                  children: [
                    "From Currency",
                    _jsxs("select", {"data-field": "from_currency", 
                      className: "input mt-1",
                      value: form.from_currency || "",
                      onChange: (e) =>
                        setForm({ ...form, from_currency: e.target.value }),
                      children: [
                        _jsx("option", { value: "", children: "Select" }),
                        data.currencies.map((c) =>
                          _jsx("option", { children: c.currency_code }, c.id),
                        ),
                      ],
                    }),
                  ],
                }),
                _jsxs("label", {
                  className: "text-sm font-medium",
                  children: [
                    "To Currency",
                    _jsxs("select", {"data-field": "to_currency", 
                      className: "input mt-1",
                      value: form.to_currency || "",
                      onChange: (e) =>
                        setForm({ ...form, to_currency: e.target.value }),
                      children: [
                        _jsx("option", { value: "", children: "Select" }),
                        data.currencies.map((c) =>
                          _jsx("option", { children: c.currency_code }, c.id),
                        ),
                      ],
                    }),
                  ],
                }),
                input("rate", "Conversion Rate", "number"),
                input("effective_date", "Effective Date", "date"),
                input("expiry_date", "Expiry Date (optional)", "date"),
                _jsx("div", { className:"md:col-span-4 rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900", children:"Authenticated synchronization uses the selected country’s currency or the From Currency and converts it to the company base currency. The provider source is stored and displayed in the table." }),
                _jsx("button", { type:"button", className:"btn-secondary md:col-span-4", onClick:()=>synchronizeExchangeRate(false), children:"Preview Live Exchange Rate" }),
                ratePreview && _jsxs("div", { className:"md:col-span-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm", children:[_jsxs("div", { className:"font-semibold", children:[ratePreview.from_currency," to ",ratePreview.to_currency,": ",ratePreview.rate] }),_jsxs("div", { children:["Source: ",ratePreview.source," | Effective: ",ratePreview.effective_date," | Expiry: ",ratePreview.expiry_date||"No expiry"] }),_jsx("div", { className:"mt-1", children:"This rate affects new transactions only; historical documents retain their saved rates." }),_jsx("button", { type:"button", className:"btn-primary mt-3", onClick:()=>synchronizeExchangeRate(true), children:"Confirm and Activate Rate" })] }),
              ],
            }),
          tab === "Holidays" &&
            _jsxs(_Fragment, {
              children: [
                _jsxs("label", {
                  className: "text-sm font-medium",
                  children: [
                    "Country",
                    _jsxs("select", {"data-field": "country_code", 
                      className: "input mt-1",
                      value:
                        form.country_code || data.company?.country_code || "",
                      onChange: (e) =>
                        setForm({ ...form, country_code: e.target.value }),
                      children: [
                        _jsx("option", { value: "", children: "Select" }),
                        data.countries.map((c) =>
                          _jsx(
                            "option",
                            { value: c.country_code, children: c.country_name },
                            c.id,
                          ),
                        ),
                      ],
                    }),
                  ],
                }),
                input("year", "Calendar Year", "number"),
                _jsx("button", {
                  type: "button",
                  className: "btn-secondary self-end",
                  onClick: () => synchronizeHolidays(false),
                  children: "Preview Official Holidays",
                }),
                holidayPreview && _jsxs("div", { className:"md:col-span-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm", children:[_jsxs("div", { className:"font-semibold", children:[holidayPreview.candidate_count," holidays from ",holidayPreview.provider,"; ",holidayPreview.new_count," new records"] }),holidayPreview.fallback_used&&_jsxs("div", { className:"text-amber-800", children:["Fallback provider used: ",holidayPreview.fallback_reason] }),_jsx("div", { className:"mt-2 max-h-40 overflow-y-auto", children:holidayPreview.holidays.map(item=>_jsxs("div", { children:[item.holiday_date," - ",item.holiday_name] },`${item.holiday_date}-${item.holiday_name}`)) }),_jsx("button", { type:"button", className:"btn-primary mt-3", onClick:()=>synchronizeHolidays(true), children:"Confirm and Update Calendar" })] }),
                input("holiday_name", "Manual Holiday Name"),
                input("holiday_date", "Holiday Start Date", "date"),
                input("holiday_end_date", "Holiday End Date (inclusive; blank for one day)", "date"),
                input("observed_date", "Observed Date (optional)", "date"),
                input("region", "Region / Province / State (optional)"),
                _jsx("p", { className: "text-xs text-slate-500 md:col-span-4", children: "Leave Region blank for a country-wide holiday. Entering a region restricts the holiday to locations configured with that exact region; All locations still respects this restriction." }),
                !!form.region?.trim() && holidayLocationCount(form) === 0 && _jsx("div", { role: "status", className: "rounded-lg bg-amber-50 p-3 text-sm text-amber-900 md:col-span-4", children: `No configured locations match region "${form.region}" in the selected country and scope. This holiday will not change their calendars. Check the region, or leave it blank for a country-wide holiday.` }),
                _jsxs("label", { className: "text-sm font-medium", children: ["Holiday Type", _jsxs("select", {"data-field": "holiday_type",  className: "input mt-1", value: form.holiday_type || "Government Public Holiday", onChange: e => setForm({ ...form, holiday_type: e.target.value }), children: ["Government Public Holiday","Statutory Holiday","National Holiday","Regional / Provincial / State Holiday","Religious Public Holiday","Special Government Holiday","Company Holiday","Emergency Closure"].map(value => _jsx("option", { value, children: value }, value)) })] }),
                _jsxs("label", { className: "text-sm font-medium", children: ["Day Coverage", _jsxs("select", {"data-field": "day_scope",  className: "input mt-1", value: form.day_scope || "FULL_DAY", onChange: e => setForm({ ...form, day_scope: e.target.value }), children: [_jsx("option", { value: "FULL_DAY", children: "Full Day" }), _jsx("option", { value: "PARTIAL_DAY", children: "Partial Day" })] })] }),
                form.day_scope === "PARTIAL_DAY" && input("start_time", "Partial Holiday Start", "time"),
                form.day_scope === "PARTIAL_DAY" && input("end_time", "Partial Holiday End", "time"),
                input("source", "Official Source"),
                _jsxs("label", { className: "text-sm font-medium", children: ["Applies To", _jsx("select", { className: "input mt-1", value: form.applicability || "ALL", onChange: e => setForm({ ...form, applicability: e.target.value, warehouse_id: null }), children: ["ALL", "WAREHOUSE", "PROCUREMENT"].map(value => _jsx("option", { value, children: { ALL: "All locations", WAREHOUSE: "Warehouses", PROCUREMENT: "Procurement office" }[value] }, value)) })] }),
                form.applicability === "WAREHOUSE" && _jsxs("label", { className: "text-sm font-medium", children: ["Warehouse", _jsxs("select", { className: "input mt-1", value: form.warehouse_id || "", onChange: e => setForm({ ...form, warehouse_id: e.target.value ? Number(e.target.value) : null }), children: [_jsx("option", { value: "", children: "All matching warehouses" }), ...(data.warehouses || []).map(w => _jsx("option", { value: w.id, children: w.name }, w.id))] })] }),
                form.applicability !== "WAREHOUSE" && _jsxs("label", { className: "flex items-center gap-2 text-sm", children: [_jsx("input", { type: "checkbox", checked: !!form.procurement_work_required, onChange: e => setForm({ ...form, procurement_work_required: e.target.checked ? 1 : 0 }) }), "Procurement office operates on this holiday"] }),
                form.applicability !== "WAREHOUSE" && !!form.procurement_work_required && input("procurement_work_reason", "Reason for Procurement Holiday Work"),
                input("notes", "Notes"),
              ],
            }),
          tab === "Shifts" &&
            _jsxs(_Fragment, {
              children: [
                _jsxs("label", {
                  className: "text-sm font-medium",
                  children: [
                    "Warehouse",
                    _jsxs("select", {"data-field": "warehouse_id", 
                      className: "input mt-1",
                      value: form.warehouse_id || "",
                      onChange: (e) => setForm({ warehouse_id: Number(e.target.value) || null }),
                      children: [
                        _jsx("option", { value: "", children: "Company / Procurement shifts" }),
                        (data.warehouses || []).map((warehouse) => _jsx("option", { value: warehouse.id, children: `${warehouse.warehouse_code || ""} — ${warehouse.name}` }, warehouse.id)),
                      ],
                    }),
                  ],
                }),
                _jsxs("label", {
                  className: "text-sm font-medium",
                  children: [
                    "Shift",
                    _jsxs("select", {"data-field": "id", 
                      className: "input mt-1",
                      value: form.id || "",
                      onChange: (e) =>
                        setForm(
                          (()=>{const selected=data.shifts.find(
                            (s) => s.id === Number(e.target.value),
                          ) || {};return shiftDrafts.find((item)=>item.id===selected.id)||selected;})(),
                        ),
                      children: [
                        _jsx("option", { value: "", children: "Select shift" }),
                        data.shifts.filter((s) => Number(s.warehouse_id || 0) === Number(form.warehouse_id || 0)).map((s) =>
                          _jsx(
                            "option",
                            { value: s.id, children: `${s.shift_label} (${s.start_time}–${s.end_time})` },
                            s.id,
                          ),
                        ),
                      ],
                    }),
                  ],
                }),
                input("shift_label", "Shift Label"),
                input("start_time", "Start Time", "time"),
                input("end_time", "End Time", "time"),
                input("break_minutes", "Break Minutes", "number"),
                _jsxs("div", {
                  className:
                    "rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900",
                  children: [
                    _jsx("div", {
                      className: "font-semibold",
                      children:
                        form.start_time && form.end_time
                          ? `${form.start_time} — ${form.end_time} · ${(shiftMinutes(form.start_time, form.end_time) / 60).toFixed(1)} scheduled hours including break`
                          : "Enter the shift times within this warehouse operating window",
                    }),
                    _jsxs("div", {
                      className: "mt-1 text-xs",
                      children: [
                        "Break: ",
                        Number(form.break_minutes ?? 30),
                        " minutes · Working time excluding break: ",
                        ((shiftMinutes(form.start_time, form.end_time) - Number(form.break_minutes || 0)) / 60).toFixed(
                          1,
                        ),
                        " hours. Breaks occur at the shift midpoint; the site is closed during breaks.",
                      ],
                    }),
                  ],
                }),
                input("effective_from", "Effective From", "date"),
              ],
            }),
          tab === "Availability" &&
            _jsxs(_Fragment, {
              children: [
                _jsx("div", {
                  className:
                    "md:col-span-4 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900",
                  children:
                    "Active employees are available by default and are added to the workforce calendar automatically. Enter a record here only when an employee is unavailable; saving the exception immediately updates the affected calendar dates.",
                }),
                _jsxs("label", {
                  className: "text-sm font-medium",
                  children: [
                    "Employee",
                    _jsxs("select", {"data-field": "employee_id", 
                      className: "input mt-1",
                      value: form.employee_id || "",
                      onChange: (e) =>
                        setForm({
                          ...form,
                          employee_id: Number(e.target.value),
                        }),
                      children: [
                        _jsx("option", {
                          value: "",
                          children: "Select employee",
                        }),
                        data.employees.map((e) =>
                          _jsxs(
                            "option",
                            {
                              value: e.id,
                              children: [e.employee_code, " \u2014 ", e.name],
                            },
                            e.id,
                          ),
                        ),
                      ],
                    }),
                  ],
                }),
                input("date_from", "From Date", "date"),
                input("date_to", "To Date", "date"),
                _jsxs("label", {
                  className: "text-sm font-medium",
                  children: [
                    "Unavailability Type",
                    _jsxs("select", {"data-field": "availability_status", 
                      className: "input mt-1",
                      value: form.availability_status || "",
                      onChange: (e) =>
                        setForm({
                          ...form,
                          availability_status: e.target.value,
                        }),
                      children: [
                        _jsx("option", { value: "", children: "Select" }),
                        [
                          "Leave",
                          "Training",
                          "Sick",
                          "Unavailable",
                          "Other",
                        ].map((x) => _jsx("option", { children: x }, x)),
                      ],
                    }),
                  ],
                }),
                input("reason", "Reason"),
              ],
            }),
          tab === "Coverage" &&
            _jsxs(_Fragment, {
              children: [
                _jsxs("label", {
                  className: "text-sm font-medium",
                  children: [
                    "Department",
                    _jsxs("select", {"data-field": "department_id", 
                      className: "input mt-1",
                      value: form.department_id || "",
                      onChange: (e) =>
                        setForm({
                          ...form,
                          department_id: Number(e.target.value),
                        }),
                      children: [
                        _jsx("option", { value: "", children: "Select" }),
                        data.departments.map((d) =>
                          _jsx(
                            "option",
                            { value: d.id, children: d.name },
                            d.id,
                          ),
                        ),
                      ],
                    }),
                  ],
                }),
                _jsxs("label", {
                  className: "text-sm font-medium",
                  children: [
                    "Employee Role",
                    _jsxs("select", {"data-field": "role_code", 
                      className: "input mt-1",
                      value: form.role_code || "",
                      onChange: (e) => setForm({ ...form, role_code: e.target.value }),
                      children: [
                        _jsx("option", { value: "", children: "Select role" }),
                        ((data.departments.find((d) => Number(d.id) === Number(form.department_id))?.name || "").toLowerCase().includes("warehouse")
                          ? ["WarehouseManager", "WarehouseSupervisor", "Storekeeper", "Helper", "SupplyChainManager"]
                          : ["PurchaseManager", "PurchaseOfficer", "SupplyChainManager"]
                        ).map((role) => _jsx("option", { value: role, children: role.replace(/([a-z])([A-Z])/g, "$1 $2") }, role)),
                      ],
                    }),
                  ],
                }),
                _jsxs("label", {
                  className: "text-sm font-medium",
                  children: [
                    "Shift",
                    _jsxs("select", {"data-field": "shift_id", 
                      className: "input mt-1",
                      value: form.shift_id || "",
                      onChange: (e) =>
                        setForm({ ...form, shift_id: Number(e.target.value) }),
                      children: [
                        _jsx("option", { value: "", children: "Select" }),
                        data.shifts.map((s) =>
                          _jsx(
                            "option",
                            { value: s.id, children: s.shift_label },
                            s.id,
                          ),
                        ),
                      ],
                    }),
                  ],
                }),
                input("minimum_staff", "Minimum Staff", "number"),
              ],
            }),
          tab === "Helper Supervision" &&
            _jsxs("div", {
              className: "md:col-span-4",
              children: [
                _jsx("div", {
                  className: "mb-2 text-sm font-semibold",
                  children: "Roles permitted to supervise Helpers",
                }),
                _jsx("div", {
                  className: "flex flex-wrap gap-4",
                  children: [
                    "WarehouseManager",
                    "WarehouseSupervisor",
                    "Storekeeper",
                  ].map((role) => {
                    const selected =
                      form.roles || data.helper_supervisor_roles || [];
                    return _jsxs(
                      "label",
                      {
                        className:
                          "flex items-center gap-2 rounded-lg border p-3",
                        children: [
                          _jsx("input", {
                            type: "checkbox",
                            checked: selected.includes(role),
                            onChange: (e) =>
                              setForm({
                                ...form,
                                roles: e.target.checked
                                  ? [...selected, role]
                                  : selected.filter((x) => x !== role),
                              }),
                          }),
                          role.replace(/([a-z])([A-Z])/g, "$1 $2"),
                        ],
                      },
                      role,
                    );
                  }),
                }),
              ],
            }),
          _jsx("button", {
            className: "btn-primary md:col-span-4",
            disabled: tab === "Shifts" && !form.id,
            onClick: save,
            children: tab === "Shifts" ? "Temporarily Save Shift" : tab === "Exchange Rates" ? "Save Manual Exchange Rate" : `Save ${tab}`,
          }),
          tab === "Shifts" && shiftDrafts.length > 0 && _jsxs("div", { className: "md:col-span-4 rounded-lg border border-amber-300 bg-amber-50 p-3", children: [_jsxs("p", { className: "text-sm font-semibold text-amber-900", children: [shiftDrafts.length, " temporary shift change(s) are not yet stored in the database."] }), _jsx("p", { className: "mt-1 text-xs text-amber-800", children: "Review and update adjoining shifts so every shift starts exactly when the previous shift ends. Confirmation will be rejected if any gap or overlap remains." }), _jsxs("div", { className: "mt-3 flex gap-2", children: [_jsx("button", { className: "btn-primary", onClick: applyShiftDrafts, children: "Confirm All Shift Changes" }), _jsx("button", { className: "btn-secondary", onClick: ()=>{setShiftDrafts([]);setMessage("Temporary shift changes discarded.");setError("");}, children: "Discard Temporary Changes" })] })] }),
        ],
      }),
      message &&
        _jsx("div", {
          className: "mb-3 rounded bg-emerald-50 p-3 text-emerald-700",
          children: message,
        }),
      error &&
        _jsx("div", {"data-error-message": true, role: "alert", 
          className: "mb-3 rounded bg-rose-50 p-3 text-rose-700",
          children: error,
        }),
      tab === "Shifts" ? _jsx("div", {
        className: "space-y-4",
        children: shiftGroups.map((group) => _jsxs("section", {
          className: "card overflow-hidden",
          children: [
            _jsxs("div", { className: "flex flex-wrap items-center justify-between gap-2 border-b border-blue-100 bg-gradient-to-r from-blue-50 to-sky-50 px-4 py-3", children: [
              _jsxs("div", { children: [_jsx("h3", { className: "font-semibold text-blue-950", children: group.name }), _jsxs("p", { className: "text-xs text-slate-500", children: [group.code, " · Operating window: ", group.window] })] }),
              _jsx("span", { className: `rounded-full bg-white px-3 py-1 text-xs font-semibold shadow-sm ${group.enabled?"text-blue-700":"text-slate-600"}`, children: group.enabled?`${group.shifts.length} shift${group.shifts.length === 1 ? "" : "s"}`:"Shift function disabled" }),
            ] }),
            !group.enabled && _jsxs("div", { className: "border-b border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600", children: ["No configurable shifts are shown because this shift function is disabled. Employees currently follow ", _jsx("strong", { children: group.standardWindow }), group.key === "company" ? ". Enable procurement shifts in Procurement Shift Setup below to edit the saved multi-shift setup." : ". Enable shifts in Warehouse Sites & Storage Locations to edit the saved multi-shift setup."] }),
            group.key === "company" && _jsx("div", { className: "p-4", children: _jsx(ProcurementSchedulePage, { embedded: true, onSaved: async () => { setShiftDrafts(current => current.filter(shift => shift.warehouse_id != null)); setForm(current => current.id && current.warehouse_id == null ? {} : current); await load(); } }) }),
            _jsx("div", { className: "overflow-x-auto", children: _jsxs("table", { className: "table-base", children: [
              _jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Shift" }), _jsx("th", { children: "Start" }), _jsx("th", { children: "End" }), _jsx("th", { children: "Break" }), _jsx("th", { children: "Status" }), _jsx("th", { children: "Action" })] }) }),
              _jsx("tbody", { children: group.shifts.map((shift) => {const shown=shiftDrafts.find((item)=>item.id===shift.id)||shift;const drafted=shown!==shift;return _jsxs("tr", { className:drafted?"bg-amber-50":"", children: [_jsxs("td", { children: [_jsx("strong", { children: shown.shift_label }), _jsx("div", { className: "text-[10px] text-slate-400", children: shift.shift_code })] }), _jsx("td", { children: shown.start_time }), _jsx("td", { children: shown.end_time }), _jsxs("td", { children: [shown.break_minutes, " min", Number(shown.break_minutes) > 0 && _jsx("div", { className: "text-xs text-amber-700", children: `Closed ${endAfter(shown.start_time, Math.min(Math.floor(shiftMinutes(shown.start_time, shown.end_time) / 2), shiftMinutes(shown.start_time, shown.end_time) - Number(shown.break_minutes)))}-${endAfter(shown.start_time, Math.min(Math.floor(shiftMinutes(shown.start_time, shown.end_time) / 2), shiftMinutes(shown.start_time, shown.end_time) - Number(shown.break_minutes)) + Number(shown.break_minutes))}` })] }), _jsx("td", { children: drafted?"Temporary":(shift.active_yn ? "Active" : "Inactive") }), _jsx("td", { children: _jsx("button", { className: "btn-secondary text-xs", onClick: () => setForm({ ...shown }), children: drafted?"Continue Editing":"Edit" }) })] }, shift.id);}) }),
            ] }) }),
          ],
        }, group.key)),
      }) : _jsx("div", {
        className: "card overflow-x-auto",
        children: _jsxs("table", {
          className: "table-base",
          children: [
            _jsx("thead", {
              children: _jsx("tr", {
                children:
                  rows[0] &&
                  (tab === "Holidays" ? HOLIDAY_COLUMNS : Object.keys(rows[0]).slice(0, 9))
                    .map((k) =>
                      _jsx("th", { children: k.replace(/_/g, " ") }, k),
                    )
                    .concat(
                      [_jsx("th", { children: "Action" }, "action")],
                    ),
              }),
            }),
            _jsx("tbody", {
              children: rows.map((r) =>
                _jsx(
                  "tr",
                  {
                    onDoubleClick: () => setReferenceDetail(r),
                    className: "cursor-pointer hover:bg-slate-50",
                    children: (tab === "Holidays" ? HOLIDAY_COLUMNS : Object.keys(r).slice(0, 9))
                      .map((k) =>
                        _jsx("td", { children: tab === "Holidays" && k === "region" && r.region?.trim() && holidayLocationCount(r) === 0 ? _jsxs("span", { className: "text-amber-800", children: [r.region, _jsx("span", { className: "block text-xs", children: "No matching locations" })] }) : String(r[k] ?? "-") }, k),
                      )
                      .concat(
                        [
                              _jsx(
                                "td",
                                {
                                  children: _jsxs("div", { className: "flex gap-2", children: [_jsx("button", { type:"button", className:"text-brand-600 text-xs font-medium", onClick:()=>setReferenceDetail(r), children:"View Details" }), tab === "Holidays" && _jsx("button", { type:"button", className:"btn-secondary text-xs", onClick:()=>{setForm({...r});setError("");setMessage("");}, children:"Edit" })] }),
                                },
                                "action",
                              ),
                            ],
                      ),
                  },
                  r.id,
                ),
              ),
            }),
          ],
        }),
      }),
      _jsx(RecordDetailModal, { row: referenceDetail, onClose: () => setReferenceDetail(null), actions: referenceDetail && tab === "Exchange Rates" ? (referenceDetail.active_yn ? _jsx("button", { type:"button", className:"btn btn-danger btn-sm", onClick:()=>deleteExchangeRate(referenceDetail), children:"Deactivate Exchange Rate" }) : _jsx("span", { className:"text-muted", children:"Exchange rate is inactive" })) : null }),
    ],
  });
}
