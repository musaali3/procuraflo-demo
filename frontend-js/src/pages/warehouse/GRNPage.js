import GRNReceiptForm from '../../components/GRNReceiptForm';
import DocumentCopyActions from '../../components/DocumentCopyActions';
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import client from "../../api/client";
import DataTable from "../../components/DataTable";
import Modal from "../../components/Modal";
import { formatCurrency } from "../../utils/currency";
import DocumentAttachments from "../../components/DocumentAttachments";
import { useAuth } from "../../contexts/AuthContext";
import ProfessionalGoodsReceiptNote from "../../components/ProfessionalGoodsReceiptNote";
import StatusBadge from "../../components/StatusBadge";
import {
  COMPANY_COPY,
  GRN_VENDOR_COPY,
} from "../../utils/printCopies";
import { downloadElementPdf } from "../../utils/downloadPdf";
import useAutoRefresh from "../../hooks/useAutoRefresh";
export default function GRNPage() {
  const { user } = useAuth();
  const receiptRequest = useRef(null);
  const receiptStorageKey = `procuraflo:pending-grn:${localStorage.getItem('procuraflow_company_key') || 'default'}`;
  const authorizedWarehouseIds = (user?.warehouse_ids || []).map(Number);
  const singleWarehouseId =
    authorizedWarehouseIds.length === 1 ? authorizedWarehouseIds[0] : "";
  const [grns, setGrns] = useState([]);
  const [pos, setPos] = useState([]);
  const [items, setItems] = useState([]);
  const [locations, setLocations] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [receivedForEmployeeId, setReceivedForEmployeeId] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [poId, setPoId] = useState("");
  const [deliveryNote, setDeliveryNote] = useState("");
  const [receivingWarehouseId, setReceivingWarehouseId] =
    useState(singleWarehouseId);
  const [lines, setLines] = useState([
    {
      item_id: "",
      item_search: "",
      quantity_received: 1,
      accepted_qty: 1,
      rejected_qty: 0,
      rejection_reason: "",
      unit_cost: 0,
      batch: "",
      expiry_date: "",
      warehouse_id: "",
    },
  ]);
  const [error, setError] = useState("");
  const [viewing, setViewing] = useState(null);
  const receivingEmployees = employees.filter((employee) => {
    if (!/warehouse/i.test(employee.department_name || "")) return false;
    if (!receivingWarehouseId) return false;
    let assigned = [];
    try { assigned = JSON.parse(employee.warehouse_ids_json || "[]").map(Number); } catch { assigned = []; }
    return Number(employee.all_warehouses_yn) === 1 || Number(employee.warehouse_id) === Number(receivingWarehouseId) || assigned.includes(Number(receivingWarehouseId));
  });
  function load() {
    client.get("/warehouse/grns").then((res) => setGrns(res.data));
  }
  useAutoRefresh(load);
  useEffect(() => {
    load();
    client
      .get("/procurement/pos")
      .then((res) =>
        setPos(
          res.data.filter(
            (p) =>
              ["Approved", "Printed", "Partially Received"].includes(p.status) &&
              !Number(p.fully_received),
          ),
        ),
      );
    client.get("/masters/operational-items").then((res) => setItems(res.data));
    client.get("/masters/locations").then((res) => setLocations(res.data));
    client.get("/masters/departments").then((res) => setDepartments(res.data));
    client.get("/masters/employee-directory").then((res) => {
      setEmployees(res.data);
      const current = res.data.find(
        (employee) => employee.name === user?.full_name,
      );
      if (current) setReceivedForEmployeeId(current.id);
    });
  }, [user?.full_name]);
  useEffect(() => {
    if (singleWarehouseId) setReceivingWarehouseId(singleWarehouseId);
  }, [singleWarehouseId]);
  function updateLine(i, key, val) {
    setLines((current) =>
      current.map((line, index) => {
        if (index !== i) return line;
        const updated = { ...line, [key]: val };
        if (key === "quantity_received") updated.accepted_qty = val;
        if (key === "accepted_qty")
          updated.rejected_qty = Math.max(0, updated.quantity_received - val);
        if (key === "rejected_qty")
          updated.accepted_qty = Math.max(0, updated.quantity_received - val);
        return updated;
      }),
    );
  }
  function itemRequiresInspection(itemId) {
    return items.find((it) => it.id === itemId)?.inspection_required_yn;
  }
  async function selectPurchaseOrder(value) {
    const selectedId = Number(value);
    setPoId(selectedId || "");
    setError("");
    if (!selectedId) {
      setLines([]);
      return;
    }
    const selected = pos.find((entry) => Number(entry.id) === selectedId);
    if (!receivingWarehouseId || !authorizedWarehouseIds.includes(Number(receivingWarehouseId)) ||
        Number(selected?.intended_delivery_warehouse_id) !== Number(receivingWarehouseId)) {
      setPoId("");
      setLines([]);
      return setError("Select a PO assigned to the receiving warehouse.");
    }
    try {
      const po = (await client.get(`/procurement/pos/${selectedId}`)).data;
      const outstandingLines = po.items
        .filter((line) => Number(line.outstanding_qty ?? line.quantity) > 0)
        .map((line) => {
          const outstanding = Number(line.outstanding_qty ?? line.quantity);
          const recommendedLocation = locations.find((location) => Number(location.id) === Number(line.last_location_id) && Number(location.warehouse_id) === Number(receivingWarehouseId));
          return {
            item_id: line.item_id,
            item_search: `${line.item_code} - ${line.description}`,
            item_code: line.item_code,
            description: line.description,
            uom: line.purchase_uom || line.uom || "",
            ordered_qty: Number(line.quantity),
            previously_received_qty: Number(line.received_qty || 0),
            outstanding_qty: outstanding,
            quantity_received: outstanding,
            accepted_qty: outstanding,
            rejected_qty: 0,
            rejection_reason: "",
            unit_cost: Number(line.price || 0),
            tax: Number(line.tax || 0),
            batch: "",
            expiry_date: "",
            warehouse_id: receivingWarehouseId,
            location_id: recommendedLocation?.id || "",
            recommended_location_code: recommendedLocation?.code || "",
          };
        });
      setLines(outstandingLines);
      if (!outstandingLines.length)
        setError("No quantity is currently due for delivery. Check PO Receiving Issues / Partial Receipt Details: remaining stock may still require inspection or put-away.");
    } catch (e) {
      setLines([]);
      setError(e?.response?.data?.error || "Unable to load PO items");
    }
  }
  async function submit() {
    try {
      if (!receivingWarehouseId)
        return setError("Select the receiving warehouse.");
      if (!authorizedWarehouseIds.includes(Number(receivingWarehouseId)) ||
          !pos.some((entry) => Number(entry.id) === Number(poId) &&
            Number(entry.intended_delivery_warehouse_id) === Number(receivingWarehouseId)))
        return setError("Select a PO assigned to your receiving warehouse.");
      if (!receivedForEmployeeId)
        return setError("Select the employee responsible for this receipt.");
      const receiptBody = {
        po_id: poId,
        delivery_note: deliveryNote,
        warehouse_id: receivingWarehouseId,
        received_for_employee_id: Number(receivedForEmployeeId),
        items: lines.map((line) => ({
          ...line,
          warehouse_id: receivingWarehouseId,
          location_id: null,
        })),
      };
      const fingerprint = JSON.stringify(receiptBody);
      if (!receiptRequest.current) { try { receiptRequest.current = JSON.parse(sessionStorage.getItem(receiptStorageKey)); } catch { /* Retain the in-memory retry key if storage is unavailable. */ } }
      if (receiptRequest.current?.fingerprint !== fingerprint) receiptRequest.current = { fingerprint, key: crypto.randomUUID() };
      try { sessionStorage.setItem(receiptStorageKey, JSON.stringify(receiptRequest.current)); } catch { /* In-memory retries remain protected. */ }
      await client.post("/warehouse/grns", { ...receiptBody, request_key: receiptRequest.current.key });
      try { sessionStorage.removeItem(receiptStorageKey); } catch { /* Successful request is already recorded by the backend. */ }
      receiptRequest.current = null;
      setShowForm(false);
      setPoId("");
      setDeliveryNote("");
      setReceivedForEmployeeId("");
      setLines([
        {
          item_id: "",
          item_search: "",
          quantity_received: 1,
          accepted_qty: 1,
          rejected_qty: 0,
          rejection_reason: "",
          unit_cost: 0,
          batch: "",
          expiry_date: "",
          warehouse_id: "",
        },
      ]);
      load();
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to post GRN");
    }
  }
  async function viewGrn(id) {
    try {
      setViewing((await client.get(`/warehouse/grns/${id}`)).data);
    } catch (e) {
      setError(e?.response?.data?.error || "Unable to view GRN");
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
                children: "Goods Receipt Note (GRN)",
              }),
              _jsx("p", {
                className: "text-sm text-slate-500",
                children:
                  "Split accepted vs. rejected quantity on inspection. Only accepted quantity creates FIFO cost layers and updates stock; the item's last purchase price is updated automatically.",
              }),
            ],
          }),
          _jsx("button", {
            className: "btn-primary",
            onClick: () => setShowForm(true),
            children: "+ New GRN",
          }),
        ],
      }),
      _jsx("div", {
        className: "card",
        children: _jsx(DataTable, {
          columns: [
            { key: "grn_number", label: "GRN Number" },
            { key: "po_number", label: "PO Number" },
            { key: "supplier_name", label: "Supplier" },
            { key: "delivery_note", label: "Delivery Note" },
            {
              key: "accepted_value",
              label: "Accepted Value",
              render: (r) => formatCurrency(r.accepted_value ?? 0),
            },
            {
              key: "status",
              label: "GRN Status",
              render: (r) => _jsx(StatusBadge, { status: r.status }),
            },
            { key: "grn_date", label: "Date" },
          ],
          rows: grns,
          actions: (row) =>
            _jsx("button", {
              className: "text-brand-600 text-xs font-medium",
              onClick: () => viewGrn(row.id),
              children: "Print / Download",
            }),
        }),
      }),
      showForm &&
        _jsx(Modal, {
          title: "New GRN",
          onClose: () => setShowForm(false),
          wide: true,
          children: _jsx(GRNReceiptForm, {
            pos: pos.filter((entry) => receivingWarehouseId &&
              authorizedWarehouseIds.includes(Number(receivingWarehouseId)) &&
              Number(entry.intended_delivery_warehouse_id) === Number(receivingWarehouseId)),
            poId, selectPurchaseOrder, locations, receivingWarehouseId,
            authorizedWarehouseIds, singleWarehouseId, user, setReceivingWarehouseId,
            setLines, receivingEmployees, departments, receivedForEmployeeId,
            setReceivedForEmployeeId, setEmployees, deliveryNote, setDeliveryNote,
            lines, items, updateLine, error, onCancel: () => setShowForm(false), submit,
          }),
        }),
      viewing &&
        _jsx(Modal, {
          title: `GRN - ${viewing.grn_number}`,
          onClose: () => setViewing(null),
          wide: true,
          children: _jsxs("div", {
            className: "space-y-4",
            children: [
              _jsxs("div", {
                className: "flex justify-end gap-2 print:hidden",
                children: [
                  _jsx(DocumentCopyActions, { documentId: "grn-print-document", filename: viewing.grn_number, copies: [{...COMPANY_COPY,label:'Company Record'},{...GRN_VENDOR_COPY,label:'Supplier Record'}] }),
                ],
              }),
              _jsx(ProfessionalGoodsReceiptNote, { grn: viewing }),
              _jsx("div", {
                className: "print:hidden",
                children: _jsx(DocumentAttachments, {
                  type: "GRN",
                  documentId: viewing.id,
                }),
              }),
            ],
          }),
        }),
    ],
  });
}
