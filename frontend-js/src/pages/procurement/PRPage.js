import ProcurementPRReview from '../../components/ProcurementPRReview';
import {
  jsx as _jsx,
  jsxs as _jsxs,
  Fragment as _Fragment,
} from "react/jsx-runtime";
import { useEffect, useState } from "react";
import client from "../../api/client";
import DataTable from "../../components/DataTable";
import Modal from "../../components/Modal";
import StatusBadge from "../../components/StatusBadge";
import { useAuth } from "../../contexts/AuthContext";
import DocumentAttachments from "../../components/DocumentAttachments";
import ProfessionalPurchaseRequisition from "../../components/ProfessionalPurchaseRequisition";
import { downloadElementPdf } from "../../utils/downloadPdf";
import { printElement } from "../../utils/printCopies";
import { useSearchParams } from "react-router-dom";
import SearchSelect from "../../components/SearchSelect";
import EmployeePicker from "../../components/EmployeePicker";
import useAutoRefresh from "../../hooks/useAutoRefresh";
function LegacySearchSelect({ label, options, value, onChange, placeholder }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const selected =
      options.find((opt) => String(opt.value) === String(value))?.label ||
      String(value || "");
    setQuery(selected);
  }, [value, options]);
  const filtered = options.filter((opt) =>
    `${opt.label}`.toLowerCase().includes(query.toLowerCase()),
  );
  return _jsxs("div", {
    className: "relative",
    children: [
      _jsx("label", {
        className: "text-sm font-medium text-slate-700",
        children: label,
      }),
      _jsx("input", {"data-field": "query",
        className: "input mt-1 w-full",
        placeholder: placeholder,
        value: query,
        onChange: (e) => {
          setQuery(e.target.value);
          setOpen(true);
        },
        onFocus: () => setOpen(true),
        onBlur: () => setTimeout(() => setOpen(false), 120),
      }),
      open &&
        filtered.length > 0 &&
        _jsx("div", {
          className:
            "absolute z-20 mt-1 w-full rounded-lg border border-slate-200 bg-white shadow-lg",
          children: filtered.map((opt) =>
            _jsx(
              "button",
              {
                type: "button",
                className:
                  "block w-full px-3 py-2 text-left text-sm hover:bg-slate-50",
                onMouseDown: () => {
                  setQuery(opt.label);
                  onChange(opt.value);
                  setOpen(false);
                },
                children: opt.label,
              },
              opt.value,
            ),
          ),
        }),
    ],
  });
}
export default function PRPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { user } = useAuth();
  const [rows, setRows] = useState([]);
  const [reviewing,setReviewing]=useState(null);
  const [warehouses,setWarehouses]=useState([]);
  const [warehouseId,setWarehouseId]=useState("");
  const [items, setItems] = useState([]);
  const [depts, setDepts] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [departmentId, setDepartmentId] = useState("");
  const [requestorEmployeeId, setRequestorEmployeeId] = useState("");
  const [lines, setLines] = useState([
    {
      item_id: "",
      item_search: "",
      quantity: 1,
      required_date: "",
      reason: "",
    },
  ]);
  const [error, setError] = useState("");
  const [viewing, setViewing] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [createdPrNumber, setCreatedPrNumber] = useState("");
  function canSeePr(row) {
    if (!['Storekeeper', 'WarehouseSupervisor', 'WarehouseManager'].includes(user?.role)) return true;
    const authorized = new Set((user?.warehouse_ids || []).map(Number));
    const linked = row?.warehouse_scope_ids || (row?.trigger_warehouse_id ? [row.trigger_warehouse_id] : []);
    return linked.some((id) => authorized.has(Number(id)));
  }
  function load() {
    client.get("/procurement/prs").then((res) => setRows(res.data.filter(canSeePr)));
  }
  useAutoRefresh(load);
  useEffect(() => {
    load();
    client.get("/masters/warehouses").then(({data})=>{setWarehouses(data);if(data.length===1)setWarehouseId(data[0].id);});
    client
      .get("/masters/items")
      .then((res) => setItems(res.data.filter((i) => i.active_yn !== 0)));
    client.get("/masters/departments").then((res) => setDepts(res.data));
    client.get("/masters/employee-directory").then((res) => {
      setEmployees(res.data);
      const current = res.data.find(
        (employee) => employee.name === user?.full_name,
      );
      if (current) {
        setRequestorEmployeeId(current.id);
        setDepartmentId(current.department_id || "");
      }
    });
  }, [user]);
  useEffect(() => {
    const openId = Number(searchParams.get("open"));
    const target = openId ? rows.find((row) => row.id === openId) : null;
    if (!target) return;
    setSearchParams({}, { replace: true });
    viewPr(target);
  }, [rows, searchParams, setSearchParams]);
  function addLine() {
    setLines((current) => [
      ...current,
      {
        item_id: "",
        item_search: "",
        quantity: 1,
        required_date: "",
        reason: "",
      },
    ]);
  }
  function removeLine(index) {
    setLines((current) =>
      current.length === 1
        ? current
        : current.filter((_, lineIndex) => lineIndex !== index),
    );
  }
  function updateLine(i, key, val) {
    setLines((current) =>
      current.map((line, index) =>
        index === i ? { ...line, [key]: val } : line,
      ),
    );
  }
  async function submit() {
    setError("");
    if (
      !warehouseId ||
      !departmentId ||
      !requestorEmployeeId ||
      lines.some(
        (line) =>
          !line.item_id ||
          !Number.isFinite(line.quantity) ||
          line.quantity <= 0,
      )
    ) {
      setError(
        "Select a requestor, department, and valid item quantity greater than zero for every line.",
      );
      return;
    }
    try {
      if (editingId)
        await client.put(`/procurement/prs/${editingId}`, {
          warehouse_id: Number(warehouseId),
          department_id: departmentId,
          requestor_employee_id: Number(requestorEmployeeId),
          items: lines,
        });
      else {
        const response = await client.post("/procurement/prs", {
          warehouse_id: Number(warehouseId),
          department_id: departmentId,
          requestor_employee_id: Number(requestorEmployeeId),
          items: lines,
        });
        setCreatedPrNumber(response.data.pr_number);
      }
      setShowForm(false);
      setLines([
        {
          item_id: "",
          item_search: "",
          quantity: 1,
          required_date: "",
          reason: "",
        },
      ]);
      setDepartmentId("");
      setRequestorEmployeeId("");
      setEditingId(null);
      load();
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to submit PR");
    }
  }
  async function setStatus(id, status) {
    if (!canSeePr(rows.find((row) => row.id === id))) return setError('PR is outside your authorized warehouse scope.');
    try {
      await client.put(`/procurement/prs/${id}/status`, { status });
      load();
    } catch (e) {
      setError(
        e?.response?.data?.error || `Failed to ${status.toLowerCase()} PR`,
      );
    }
  }
  async function viewPr(row) {
    if (!canSeePr(row)) return setError('PR is outside your authorized warehouse scope.');
    try {
      setViewing({
        ...row,
        ...(await client.get(`/procurement/prs/${row.id}`)).data,
      });
    } catch (e) {
      setError(e?.response?.data?.error || "Unable to view PR");
    }
  }
  async function reviewPr(row) {
    if (!canSeePr(row)) return setError('PR is outside your authorized warehouse scope.');
    try {setReviewing((await client.get(`/procurement/prs/${row.id}`)).data);} catch(e){setError(e?.response?.data?.error || "Unable to open review");}
  }
  async function editPr(row) {
    if (!canSeePr(row)) return setError('PR is outside your authorized warehouse scope.');
    try {
      const detail = (await client.get(`/procurement/prs/${row.id}`)).data;
      setEditingId(row.id);setError("");
      setWarehouseId(detail.trigger_warehouse_id || "");
      setDepartmentId(detail.department_id);
      setRequestorEmployeeId(detail.business_requestor_employee_id || "");
      setLines(detail.items);
      setShowForm(true);
    } catch (e) {
      setError(e?.response?.data?.error || "Unable to edit PR");
    }
  }
  const canCreate = Boolean(user);
  const canApprove =
    !!user && ["PurchaseOfficer", "PurchaseManager", "SupplyChainManager"].includes(user.role);
  const canCloseBalance =
    !!user &&
    ["PurchaseOfficer", "PurchaseManager", "SupplyChainManager"].includes(
      user.role,
    );
  return _jsxs("div", {
    children: [
      _jsxs("div", {
        className: "flex items-center justify-between mb-4",
        children: [
          _jsxs("div", {
            children: [
              _jsx("h1", {
                className: "text-xl font-semibold text-slate-900",
                children: "Purchase Requisitions",
              }),
              _jsx("p", {
                className: "text-sm text-slate-500",
                children:
                  "Department requests that kick off the procurement workflow.",
              }),
            ],
          }),
          canCreate &&
            _jsx("button", {
              className: "btn-primary",
              onClick: () => {
                setError("");
                setShowForm(true);
              },
              children: "+ New PR",
            }),
        ],
      }),
      _jsx("div", {
        className: "card",
        children: _jsx(DataTable, {
          columns: [
            { key: "pr_number", label: "PR Number" },
            { key: "department_name", label: "Department" },
            { key: "warehouse_name", label: "Warehouse", render: (r) => [r.warehouse_code, r.warehouse_name].filter(Boolean).join(" ? ") || "?" },
            { key: "requestor_name", label: "Requestor" },
            {
              key: "source_label",
              label: "Source",
              render: (r) => r.source_label || "Manual Request",
            },
            {
              key: "approval_decision",
              label: "Approval",
              render: (r) =>
                _jsx(StatusBadge, { status: r.warehouse_draft ? "Warehouse Review" : r.approval_decision || "Pending" }),
            },
            { key: "pr_date", label: "Date" },
            {
              key: "status",
              label: "Status",
              render: (r) => _jsx(StatusBadge, { status: r.warehouse_draft ? "Warehouse Review" : r.status }),
            },
          ],
          rows: rows,
          actions: (r) =>
            _jsxs("div", {
              className: "flex gap-2 justify-end",
              children: [
                _jsx("button", {
                  className: "text-brand-600 text-xs font-medium",
                  onClick: () => viewPr(r),
                  children: "Print / Download",
                }),
                r.status === "Draft" && r.can_manage_draft && _jsxs(_Fragment, { children: [_jsx("button", { className: "text-slate-600 text-xs font-medium", onClick: () => editPr(r), children: "Review / Edit" }), r.can_submit_draft && _jsx("button", { className: "text-emerald-600 text-xs font-medium", onClick: async () => { try { await client.post(`/procurement/prs/${r.id}/submit-to-procurement`); load(); } catch(e) { setError(e?.response?.data?.error || "Unable to submit PR"); } }, children: r.warehouse_owned ? "Submit to Procurement" : "Submit for Review" }), r.warehouse_draft && _jsx("button", { className: "text-rose-600 text-xs font-medium", onClick: () => setStatus(r.id,"Closed"), children: "No Purchase Required" })] }),
                r.status === "Submitted" &&
                  r.approval_decision !== "Approved" &&
                  canApprove &&
                  _jsxs(_Fragment, {
                    children: [
                      _jsx("button", {
                        className: "text-emerald-600 text-xs font-medium",
                        onClick: () => reviewPr(r),
                        children: "Review / Approve",
                      }),
                      _jsx("button", {
                        className: "text-rose-600 text-xs font-medium",
                        onClick: () => setStatus(r.id, "Rejected"),
                        children: "Reject",
                      }),
                    ],
                  }),
              ],
            }),
        }),
      }),
      reviewing && _jsx(ProcurementPRReview,{requisition:reviewing,onClose:()=>setReviewing(null),onSaved:load}),
      showForm &&
        _jsx(Modal, {
          title: editingId
            ? "Edit Purchase Requisition"
            : "New Purchase Requisition",
          onClose: () => {
            setShowForm(false);
            setEditingId(null);
          },
          wide: true,
          children: _jsxs("div", {
            className: "compact-form",
            children: [
              _jsxs("div", {
                className: "form-section-tinted",
                children: [
                  _jsx("h3", {
                    className: "form-section-title",
                    children: "Request Details",
                  }),
                  _jsxs("div", {
                    className: "grid grid-cols-1 md:grid-cols-3 gap-3",
                    children: [
                      _jsx(EmployeePicker, {
                        label: "Requested By",
                        employees: employees,
                        departments: depts,
                        value: requestorEmployeeId,
                        onChange: (val, employee) => {
                          setRequestorEmployeeId(val ? Number(val) : "");
                          if (employee?.department_id)
                            setDepartmentId(employee.department_id);
                        },
                        onCreated: (employee) =>
                          setEmployees((current) => [...current, employee]),
                      }),
                      _jsx(SearchSelect, {"data-field": "departmentId",
                        label: "Department",
                        options: depts.map((d) => ({
                          value: d.id,
                          label: d.name,
                        })),
                        value: departmentId,
                        onChange: (val) => setDepartmentId(Number(val)),
                        placeholder: "Search department",
                      }),
                      _jsx(SearchSelect, {"data-field": "warehouseId", label:"Warehouse",options:warehouses.map(w=>({value:w.id,label:[w.warehouse_code,w.name].filter(Boolean).join(" ? ")})),value:warehouseId,onChange:value=>setWarehouseId(Number(value)),disabled:Boolean(editingId)}),
                    ],
                  }),
                ],
              }),
              _jsxs("div", {
                className: "form-section",
                children: [
                  _jsx("h3", {
                    className: "form-section-title",
                    children: "Requested Items",
                  }),
                  _jsx("div", {
                    className: "space-y-2 mt-1",
                    children: lines.map((line, i) =>
                      _jsxs(
                        "div",
                        {
                          className:
                            "form-line-card grid grid-cols-12 gap-2 items-start",
                          children: [
                            _jsx("div", {
                              className: "col-span-12 lg:col-span-4",
                              children: _jsx(SearchSelect, {"data-field": "item_id",
                                label: "Item",
                                options: items.map((it) => ({
                                  value: it.id,
                                  label: `${it.item_code} - ${it.description}`,
                                })),
                                value: line.item_id || line.item_search || "",
                                onChange: (val) => {
                                  const selected = items.find(
                                    (it) => it.id === Number(val),
                                  );
                                  setLines((current) =>
                                    current.map((currentLine, index) =>
                                      index === i
                                        ? {
                                            ...currentLine,
                                            item_id: selected?.id || "",
                                            item_search: selected
                                              ? `${selected.item_code} - ${selected.description}`
                                              : "",
                                          }
                                        : currentLine,
                                    ),
                                  );
                                },
                                placeholder: "Search item",
                              }),
                            }),
                            _jsxs("div", {
                              className: "col-span-4 lg:col-span-2",
                              children: [
                                _jsx("label", {
                                  className: "text-sm font-medium",
                                  children: "Quantity",
                                }),
                                _jsx("input", {"data-field": "quantity",
                                  className: "input mt-1",
                                  type: "number",
                                  min: "0.0001",
                                  step: "any",
                                  placeholder: "Qty",
                                  value: line.quantity,
                                  onChange: (e) =>
                                    updateLine(
                                      i,
                                      "quantity",
                                      Number(e.target.value),
                                    ),
                                }),
                              ],
                            }),
                            _jsxs("div", {
                              className: "col-span-8 lg:col-span-2",
                              children: [
                                _jsx("label", {
                                  className: "text-sm font-medium",
                                  children: "Required Date",
                                }),
                                _jsx("input", {"data-field": "required_date",
                                  className: "input mt-1",
                                  type: "date",
                                  value: line.required_date,
                                  onChange: (e) =>
                                    updateLine(
                                      i,
                                      "required_date",
                                      e.target.value,
                                    ),
                                }),
                              ],
                            }),
                            _jsxs("div", {
                              className: "col-span-12 lg:col-span-3",
                              children: [
                                _jsx("label", {
                                  className: "text-sm font-medium",
                                  children: "Reason",
                                }),
                                _jsx("input", {"data-field": "reason",
                                  className: "input mt-1",
                                  placeholder: "Reason",
                                  value: line.reason,
                                  onChange: (e) =>
                                    updateLine(i, "reason", e.target.value),
                                }),
                              ],
                            }),
                            _jsx("div", {
                              className: "col-span-12 lg:col-span-1 flex justify-end lg:pt-8",
                              children:
                                lines.length > 1 &&
                                _jsx("button", {
                                  type: "button",
                                  className:
                                    "text-xs font-medium text-rose-600 hover:text-rose-800",
                                  onClick: () => removeLine(i),
                                  children: "Remove",
                                }),
                            }),
                            line.recommended_base_quantity != null && _jsxs("div", {
                              className: "col-span-12 border-t border-slate-200 pt-2 text-xs text-slate-600",
                              children: [
                                _jsxs("div", { className: "grid gap-1 sm:grid-cols-3", children: [
                                  _jsxs("div", { children: ["Recommended Quantity: ", Number(line.recommended_base_quantity).toLocaleString(), " ", line.base_uom || ""] }),
                                  _jsxs("div", { children: ["Entered Quantity: ", (Number(line.quantity || 0) * Number(line.conversion_factor_used || 1)).toLocaleString(), " ", line.base_uom || ""] }),
                                  _jsxs("div", { children: ["Difference / Variance: ", (Number(line.quantity || 0) * Number(line.conversion_factor_used || 1) - Number(line.recommended_base_quantity)).toLocaleString(), " ", line.base_uom || ""] }),
                                ] }),
                                (Number(line.quantity || 0) * Number(line.conversion_factor_used || 1) !== Number(line.recommended_base_quantity) || Boolean(line.adjustment_reason) || Boolean(line.adjustment_note)) && _jsxs("details", {
                                  className: "mt-2",
                                  open: true,
                                  children: [
                                    _jsx("summary", { className: "cursor-pointer font-medium text-brand-600", children: "Explain Quantity Change" }),
                                    _jsxs("div", { className: "mt-2 grid gap-3 sm:grid-cols-2", children: [
                                      _jsxs("div", { className: "min-w-0", children: [_jsx("label", { className: "text-sm font-medium", children: "Reason for Quantity Change" }), _jsxs("select", {"data-field": "adjustment_reason",  className: "input mt-1", value: line.adjustment_reason || "", onChange: e => updateLine(i, "adjustment_reason", e.target.value), children: [_jsx("option", { value: "", children: "Select when quantity is changed..." }), ["Item no longer required","Stock found","Duplicate requirement","Upcoming transfer","Incorrect reorder level","Reduced demand","Other"].map(reason => _jsx("option", { value: reason, children: reason }, reason))] })] }),
                                      line.adjustment_reason === "Other" && _jsxs("div", { className: "min-w-0", children: [_jsx("label", { className: "text-sm font-medium", children: "Adjustment Note" }), _jsx("input", {"data-field": "adjustment_note",  className: "input mt-1", value: line.adjustment_note || "", onChange: e => updateLine(i, "adjustment_note", e.target.value), placeholder: "Short explanation" })] }),
                                    ] }),
                                  ],
                                }),
                              ],
                            }),
                          ],
                        },
                        i,
                      ),
                    ),
                  }),
                  _jsx("button", {
                    type: "button",
                    className: "text-brand-600 text-sm font-medium mt-2",
                    onClick: addLine,
                    children: "+ Add Another Item",
                  }),
                ],
              }),
              error &&
                _jsx("div", {"data-error-message": true, role: "alert",
                  className:
                    "text-sm text-rose-600 bg-rose-50 rounded-lg px-3 py-2",
                  children: error,
                }),
              _jsxs("div", {
                className: "flex justify-end gap-2 pt-2",
                children: [
                  _jsx("button", {
                    className: "btn-secondary",
                    onClick: () => setShowForm(false),
                    children: "Cancel",
                  }),
                  _jsx("button", {
                    className: "btn-primary",
                    onClick: submit,
                    children: "Save Draft",
                  }),
                ],
              }),
            ],
          }),
        }),
      createdPrNumber &&
        _jsx(Modal, {
          title: "Purchase Requisition Submitted",
          onClose: () => setCreatedPrNumber(""),
          children: _jsxs("div", {
            className: "space-y-4 text-sm",
            children: [
              _jsx("p", {
                className: "text-slate-600",
                children:
                  "The system generated the following unique PR reference:",
              }),
              _jsx("div", {
                className:
                  "rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-center text-xl font-bold text-emerald-800 select-all",
                children: createdPrNumber,
              }),
              _jsx("p", {
                className: "text-xs text-slate-500",
                children:
                  "Use this reference for review, approval, reporting, and PO conversion.",
              }),
              _jsx("div", {
                className: "flex justify-end",
                children: _jsx("button", {
                  className: "btn-primary",
                  onClick: () => setCreatedPrNumber(""),
                  children: "Done",
                }),
              }),
            ],
          }),
        }),
      viewing &&
        _jsx(Modal, {
          title: `Purchase Requisition - ${viewing.pr_number}`,
          onClose: () => setViewing(null),
          wide: true,
          children: _jsxs("div", {
            className: "space-y-4",
            children: [
              _jsxs("div", {
                className: "flex justify-end gap-2 print:hidden",
                children: [
                  _jsx("button", {
                    className: "btn-secondary",
                    onClick: () =>
                      downloadElementPdf(
                        "pr-print-document",
                        viewing.pr_number,
                      ),
                    children: "Download PDF",
                  }),
                  _jsx("button", {
                    className: "btn-primary",
                    onClick: () => printElement("pr-print-document"),
                    children: "Print Professional PR",
                  }),
                ],
              }),
              _jsx(ProfessionalPurchaseRequisition, { requisition: viewing }),
              _jsx("div", {
                className: "print:hidden",
                children: _jsx(DocumentAttachments, {
                  type: "PR",
                  documentId: viewing.id,
                }),
              }),
              viewing.status === "Submitted" &&
                !viewing.approvals?.some(
                  (approval) => approval.decision === "Approved",
                ) &&
                canApprove &&
                _jsxs("div", {
                  className: "flex justify-end gap-2 print:hidden",
                  children: [
                    _jsx("button", {
                      className: "btn-secondary text-rose-600",
                      onClick: async () => {
                        await setStatus(viewing.id, "Rejected");
                        setViewing(null);
                      },
                      children: "Reject",
                    }),
                    _jsx("button", {
                      className: "btn-primary",
                      onClick: async () => {
                        await reviewPr(viewing);
                        setViewing(null);
                      },
                      children: "Review / Approve",
                    }),
                  ],
                }),
            ],
          }),
        }),
    ],
  });
}
