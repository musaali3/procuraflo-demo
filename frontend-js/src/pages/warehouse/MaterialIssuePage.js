import ProfessionalMaterialIssue from '../../components/ProfessionalMaterialIssue';
import MaterialIssueForm from '../../components/MaterialIssueForm';
import { showErrorGuidance } from '../../utils/errorGuidance';
import {
  jsx as _jsx,
  Fragment as _Fragment,
  jsxs as _jsxs,
} from "react/jsx-runtime";
import { useEffect, useState } from "react";
import client from "../../api/client";
import DataTable from "../../components/DataTable";
import Modal from "../../components/Modal";
import StatusBadge from "../../components/StatusBadge";
import { useAuth } from "../../contexts/AuthContext";
import { formatCurrency } from "../../utils/currency";
import { useSearchParams } from "react-router-dom";
import { downloadElementPdf } from "../../utils/downloadPdf";
import { printElement } from "../../utils/printCopies";
import useAutoRefresh from "../../hooks/useAutoRefresh";
export default function MaterialIssuePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { user } = useAuth();
  const warehouseRole =
    !!user &&
    ["WarehouseManager", "WarehouseSupervisor", "Storekeeper"].includes(
      user.role,
    );
  const authorizedWarehouseIds = (user?.warehouse_ids || []).map(Number);
  // Lock the form only when the account has exactly one authorized warehouse.
  // Managers/supervisors with multiple or all-warehouse scope must select one.
  const warehouseBound = warehouseRole && authorizedWarehouseIds.length === 1;
  const assignedWarehouseId = warehouseBound ? authorizedWarehouseIds[0] : "";
  const [issues, setIssues] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [items, setItems] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [threshold, setThreshold] = useState(500);
  const [editingId,setEditingId]=useState(null);
  const [showForm, setShowForm] = useState(false);
  const [employeeId, setEmployeeId] = useState("");
  const [purpose, setPurpose] = useState("");
  const [lines, setLines] = useState([
    {
      item_id: "",
      item_search: "",
      warehouse_id: assignedWarehouseId,
      quantity: 1,
    },
  ]);
  const [error, setError] = useState("");
  const [viewing, setViewing] = useState(null);
  const [stock, setStock] = useState([]);
  const [thresholdSaved, setThresholdSaved] = useState(false);
  function load() {
    client.get("/warehouse/material-issues").then((res) => setIssues(res.data));
  }
  useAutoRefresh(load);
  useEffect(() => {
    load();
    client
      .get("/masters/employee-directory")
      .then((res) => setEmployees(res.data));
    client.get("/masters/departments").then((res) => setDepartments(res.data));
    client
      .get("/masters/operational-items")
      .then((res) => setItems(res.data.filter((i) => i.active_yn !== 0)));
    client.get("/masters/warehouses").then((res) => setWarehouses(res.data));
    client.get("/settings").then((res) => {
      const configured = Number(res.data.material_issue_approval_threshold);
      setThreshold(Number.isFinite(configured) ? configured : 500);
    });
    client.get("/inventory/stock").then((res) => setStock(res.data));
  }, []);
  useEffect(() => {
    const openId = Number(searchParams.get("open"));
    const target = openId ? issues.find((row) => row.id === openId) : null;
    if (!target) return;
    setSearchParams({}, { replace: true });
    viewIssue(target);
  }, [issues, searchParams, setSearchParams]);
  useEffect(() => {
    if (!assignedWarehouseId) return;
    setLines((current) =>
      current.map((line) => ({ ...line, warehouse_id: assignedWarehouseId })),
    );
  }, [assignedWarehouseId]);
  function addLine() {
    setLines((current) => [
      ...current,
      {
        item_id: "",
        item_search: "",
        warehouse_id: assignedWarehouseId,
        quantity: 1,
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
  const [valuation,setValuation] = useState(null);
  const [valuationMessage,setValuationMessage] = useState("");
  useEffect(() => {
    let active=true;setValuation(null);
    if(!showForm)return;
    if(lines.some(line=>!line.item_id||!line.warehouse_id||!line.location_id||Number(line.quantity)<=0)){
      setValuationMessage("Select an item, warehouse, storage location and positive quantity to check value and approval.");return;
    }
    setValuationMessage("Checking FIFO value and approval limit...");
    const timer=setTimeout(()=>client.post("/warehouse/material-issue-preview",{items:lines}).then(({data})=>{
      if(active){setValuation(data);setValuationMessage("");}
    }).catch(error=>{if(active)setValuationMessage(error.response?.data?.error||"Unable to check issue value. Please retry.");}),250);
    return ()=>{active=false;clearTimeout(timer);};
  },[lines,showForm]);
  const hasHighValueItem = lines.some(
    (l) =>
      items.find((it) => it.id === l.item_id)?.high_value_flag ||
      items.find((it) => it.id === l.item_id)?.always_approval_yn,
  );
  const hasReturnableItem = lines.some(
    (line) => items.find((item) => item.id === line.item_id)?.consumable_returnable === "Returnable",
  );
  async function submit() {
    setError("");
    if (
      !employeeId ||
      lines.some(
        (line) =>
          !line.item_id ||
          !line.warehouse_id ||
          !line.location_id ||
          !(line.quantity > 0),
      )
    )
      return setError(
        "Employee, item, storage Bin, and a quantity greater than zero are required for every line.",
      );
    const low = lines.find(
      (line) =>
        line.quantity >
        stock
          .filter(
            (s) =>
              s.item_id === line.item_id &&
              s.warehouse_id === line.warehouse_id &&
              s.location_id === line.location_id,
          )
          .reduce((sum, s) => sum + Number(s.quantity), 0),
    );
    if (low)
      return setError(
        "Requested quantity exceeds available stock. Review the available quantity shown beside each line.",
      );
    try {
      await client.request({method:editingId?"put":"post",url:editingId?`/warehouse/material-issues/${editingId}`:"/warehouse/material-issues",data: {
        employee_id: employeeId,
        purpose,
        items: lines,
      }});
      setShowForm(false);setEditingId(null);
      setEmployeeId("");
      setPurpose("");
      setLines([
        {
          item_id: "",
          item_search: "",
          warehouse_id: assignedWarehouseId,
          quantity: 1,
        },
      ]);
      load();
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to issue material");
    }
  }
  async function approve(id) {
    try {
      await client.put(`/warehouse/material-issues/${id}/approve`);
      load();
    } catch (e) {
      showErrorGuidance({message: e?.response?.data?.error || "Approval failed"});
    }
  }
  async function reject(id) {
    try {
      await client.put(`/warehouse/material-issues/${id}/reject`);
      load();
    } catch (e) {
      showErrorGuidance({message: e?.response?.data?.error || "Rejection failed"});
    }
  }
  const canApprove =
    user && ["Storekeeper", "WarehouseSupervisor", "WarehouseManager", "SupplyChainManager"].includes(user.role);
  const canConfigureThreshold = user?.role === "SupplyChainManager";
  const canViewThreshold =
    !!user && ["WarehouseManager", "SupplyChainManager"].includes(user.role);
  async function saveThreshold() {
    await client.put("/settings/material_issue_approval_threshold", {
      value: threshold,
    });
    setThresholdSaved(true);
    setTimeout(() => setThresholdSaved(false), 2000);
  }
  async function editIssue(row){
    try{const {data}=await client.get(`/warehouse/material-issues/${row.id}`);
      setEditingId(data.id);setEmployeeId(data.employee_id);setPurpose(data.purpose||"");
      setLines(data.items.map(line=>({...line,item_search:`${line.item_code} - ${line.description}`})));
      setViewing(null);setError("");setShowForm(true);
    }catch(e){setError(e.response?.data?.error||"Unable to open Material Issue for editing");}
  }
  async function viewIssue(row) {
    try {
      setViewing(
        (await client.get(`/warehouse/material-issues/${row.id}`)).data,
      );
    } catch (e) {
      setError(e?.response?.data?.error || "Unable to view issue");
    }
  }
  return _jsxs("div", {
    children: [
      _jsxs("div", {
        className: "flex items-center justify-between mb-4",
        children: [
          _jsxs("div", {
            children: [
              _jsx("h1", {
                className: "text-xl font-semibold text-slate-900",
                children: "Material Issue",
              }),
              _jsx("p", {
                className: "text-sm text-slate-500",
                children: canViewThreshold
                  ? _jsxs(_Fragment, {
                      children: [
                        "Track consumption by employee. Issues over ",
                        formatCurrency(threshold),
                        " or containing high-value/always-approval items route to the next approval authority before stock is consumed.",
                      ],
                    })
                  : _jsx(_Fragment, {
                      children:
                        "Track consumption by employee. The system will indicate when an issue requires Warehouse Manager approval before stock is consumed.",
                    }),
              }),
            ],
          }),
          _jsx("button", {
            className: "btn-primary",
            onClick: () => setShowForm(true),
            children: "+ New Issue",
          }),
        ],
      }),
      canViewThreshold &&
        _jsxs("div", {
          className: "card p-4 mb-4",
          children: [
            _jsx("h2", {
              className: "font-semibold text-blue-900",
              children: "Material Issue Approval Control",
            }),
            _jsx("p", {
              className: "text-xs text-slate-500 mt-1",
              children:
                "Issues above this value require Warehouse Manager approval before stock is deducted.",
            }),
            canConfigureThreshold
              ? _jsxs("div", {
                  className: "flex items-end gap-2 mt-3 max-w-md",
                  children: [
                    _jsxs("div", {
                      className: "flex-1",
                      children: [
                        _jsx("label", {
                          className: "text-sm font-medium",
                          children: "Approval Threshold",
                        }),
                        _jsx("input", {"data-field": "threshold",
                          className: "input mt-1",
                          type: "number",
                          min: "0",
                          value: threshold,
                          onChange: (e) => setThreshold(Number(e.target.value)),
                        }),
                      ],
                    }),
                    _jsx("button", {
                      className: "btn-secondary",
                      onClick: saveThreshold,
                      children: "Save Threshold",
                    }),
                  ],
                })
              : _jsxs("div", {
                  className: "mt-3 max-w-md",
                  children: [
                    _jsx("label", {
                      className: "text-sm font-medium",
                      children: "Approval Threshold (Read Only)",
                    }),
                    _jsx("div", {
                      className:
                        "input mt-1 bg-slate-100 font-semibold text-slate-700",
                      children: formatCurrency(threshold),
                    }),
                    _jsx("p", {
                      className: "mt-1 text-xs text-amber-700",
                      children:
                        "Only the Supply Chain Manager can change this control.",
                    }),
                  ],
                }),
            thresholdSaved &&
              _jsx("div", {
                className: "text-xs text-emerald-600 mt-2",
                children:
                  "Approval threshold saved and recorded in the audit log.",
              }),
          ],
        }),
      _jsx("div", {
        className: "card",
        children: _jsx(DataTable, {
          columns: [
            { key: "issue_number", label: "Issue Number" },
            { key: "employee_code", label: "Employee Code" },
            { key: "employee_name", label: "Employee" },
            { key: "employee_department_name", label: "Department" },
            { key: "issue_date", label: "Date" },
            {
              key: "total_value",
              label: "Value",
              render: (r) => formatCurrency(r.total_value ?? 0),
            },
            {
              key: "status",
              label: "Status",
              render: (r) => _jsx(StatusBadge, { status: r.status }),
            },
          ],
          rows: issues,
          actions: (r) =>
            _jsxs("div", {
              className: "flex gap-2 justify-end",
              children: [
                _jsx("button", {
                  className: "text-brand-600 text-xs font-medium",
                  onClick: () => viewIssue(r),
                  children: r.status==="PendingApproval"?"Review":"Print / Download",
                }),
                r.can_edit && _jsx("button", {className:"text-brand-600 text-xs font-medium",onClick:()=>editIssue(r),children:"Edit"}),
                r.status === "PendingApproval" &&
                  canApprove && r.can_approve &&
                  _jsxs(_Fragment, {
                    children: [
                      _jsx("button", {
                        className: "text-emerald-600 text-xs font-medium",
                        onClick: () => approve(r.id),
                        children: "Approve",
                      }),
                      _jsx("button", {
                        className: "text-rose-600 text-xs font-medium",
                        onClick: () => reject(r.id),
                        children: "Reject",
                      }),
                    ],
                  }),
              ],
            }),
        }),
      }),
      showForm &&
        _jsx(Modal, {
          title: editingId ? "Review & Edit Material Issue" : "New Material Issue",
          onClose: () => setShowForm(false),
          wide: true,
          children: _jsx(MaterialIssueForm, {
            employees, departments, employeeId, setEmployeeId, setEmployees,
            purpose, setPurpose, lines, items, warehouses, warehouseBound,
            assignedWarehouseId, user, stock, setLines, updateLine, removeLine,
            addLine, valuation, valuationMessage, hasHighValueItem,
            hasReturnableItem, error,
            onCancel: () => { setShowForm(false); setEditingId(null); },
            submit, editingId,
          }),
        }),
      viewing &&
        _jsx(Modal, {
          title: `Material Issue - ${viewing.issue_number}`,
          onClose: () => setViewing(null),
          wide: true,
          children: _jsxs("div", {
            className: "space-y-3 text-sm",
            children: [
              _jsxs("div", {
                className: "sticky top-0 z-10 flex justify-end gap-2 rounded-lg border border-blue-100 bg-white/95 p-3 shadow-sm print:hidden",
                children: [
                  _jsx("button", {
                    className: "btn-secondary",
                    onClick: () => downloadElementPdf("material-issue-print-document", viewing.issue_number),
                    children: "Download PDF",
                  }),
                  _jsx("button", {
                    className: "btn-primary",
                    onClick: () => printElement("material-issue-print-document"),
                    children: "Print Document",
                  }),
                ],
              }),
              _jsx(ProfessionalMaterialIssue, {issue:viewing}),
              viewing.can_edit && _jsx("button",{className:"btn-secondary",onClick:()=>editIssue(viewing),children:"Edit Material Issue"}),
              viewing.status === "PendingApproval" &&
                canApprove &&
                _jsxs("div", {
                  className: "flex justify-end gap-2",
                  children: [
                    _jsx("button", {
                      className: "btn-secondary text-rose-600",
                      onClick: async () => {
                        await reject(viewing.id);
                        setViewing(null);
                      },
                      children: "Reject",
                    }),
                    _jsx("button", {
                      className: "btn-primary",
                      onClick: async () => {
                        await approve(viewing.id);
                        setViewing(null);
                      },
                      children: "Approve",
                    }),
                  ],
                }),
            ],
          }),
        }),
    ],
  });
}
