import { useEffect, useMemo, useState } from "react";
import client from "../../api/client";
import DataTable from "../../components/DataTable";
import Modal from "../../components/Modal";
import StatusBadge from "../../components/StatusBadge";
import useAutoRefresh from "../../hooks/useAutoRefresh";

export default function CycleCountPage() {
  const [counts, setCounts] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [items, setItems] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [warehouseId, setWarehouseId] = useState("");
  const [itemIds, setItemIds] = useState([]);
  const [itemQuery, setItemQuery] = useState("");
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [countedQtys, setCountedQtys] = useState({});
  const [reviewReason, setReviewReason] = useState("");
  const [reviewComments, setReviewComments] = useState("");

  const load = () => client.get("/inventory/cycle-counts").then((response) => setCounts(response.data));
  useAutoRefresh(load);

  useEffect(() => {
    load();
    client.get("/inventory/cycle-count-warehouses").then((response) => setWarehouses(response.data));
    client.get("/masters/operational-items").then((response) => setItems(response.data));
  }, []);

  const countWarehouses = useMemo(() => warehouses.filter((warehouse) => warehouse.can_create_cycle_count), [warehouses]);
  useEffect(() => {
    if (warehouseId && !countWarehouses.some((warehouse) => String(warehouse.id) === String(warehouseId))) setWarehouseId("");
  }, [countWarehouses, warehouseId]);

  const visibleItems = useMemo(() => {
    const query = itemQuery.trim().toLowerCase();
    return query ? items.filter((item) => `${item.item_code} ${item.description}`.toLowerCase().includes(query)) : items;
  }, [items, itemQuery]);
  const allSelected = items.length > 0 && itemIds.length === items.length;

  async function createCount() {
    setError("");
    if (!warehouseId || !itemIds.length) return setError("Select a warehouse and at least one item.");
    try {
      await client.post("/inventory/cycle-counts", { warehouse_id: Number(warehouseId), item_ids: itemIds });
      setShowForm(false);
      setWarehouseId("");
      setItemIds([]);
      setItemQuery("");
      load();
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to create count sheet");
    }
  }

  async function openDetail(count) {
    try {
      const { data } = await client.get(`/inventory/cycle-counts/${count.id}`);
      setDetail(data);
      setCountedQtys(Object.fromEntries(data.items.map((item) => [item.item_id, item.counted_qty ?? item.system_qty])));
      setReviewReason("");
      setReviewComments("");
    } catch (e) {
      setError(e?.response?.data?.error || "Unable to open count sheet");
    }
  }

  async function submitCounts() {
    const submitted = detail.items.map((item) => ({
      item_id: item.item_id,
      counted_qty: Number(countedQtys[item.item_id]),
      count_note: item.count_note || "",
    }));
    if (submitted.some((line) => !Number.isFinite(line.counted_qty) || line.counted_qty < 0)) return setError("Counted quantities must be zero or greater.");
    try {
      await client.put(`/inventory/cycle-counts/${detail.id}/submit-counts`, { counts: submitted });
      setDetail(null);
      load();
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to submit counts");
    }
  }

  async function approveCount(id) {
    try {
      await client.put(`/inventory/cycle-counts/${id}/approve`);
      setDetail(null);
      load();
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to approve count");
    }
  }

  async function decideCount(action) {
    try {
      await client.put(`/inventory/cycle-counts/${detail.id}/decision`, { action, reason: reviewReason });
      setDetail(null);
      load();
    } catch (e) {
      setError(e?.response?.data?.error || `Failed to ${action.toLowerCase()} count`);
    }
  }

  async function proposeAdjustments() {
    try {
      await client.post(`/inventory/cycle-counts/${detail.id}/adjustments`, { reason: reviewReason, comments: reviewComments });
      setDetail(null);
      load();
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to submit adjustment to SCM");
    }
  }

  async function approveAdjustments(id) {
    try {
      await client.put(`/inventory/cycle-counts/${id}/adjustments/approve`);
      setDetail(null);
      load();
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to approve adjustments");
    }
  }

  return <div>
    <div className="mb-4 flex items-center justify-between">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Cycle Count</h1>
        <p className="text-sm text-slate-500">Controlled count, variance review, adjustment approval, and inventory posting.</p>
      </div>
      <button className="btn-primary" onClick={() => { setError(""); setShowForm(true); }}>+ New Count Sheet</button>
    </div>
    {error && <div data-error-message="true" role="alert" className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
    <div className="card">
      <DataTable
        columns={[
          { key: "count_number", label: "Count Number" },
          { key: "count_date", label: "Date" },
          { key: "warehouse_name", label: "Warehouse" },
          { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
        ]}
        rows={counts}
        actions={(row) => <div className="flex flex-wrap gap-2">
          <button className="btn-secondary" onClick={() => openDetail(row)}>{row.can_count ? "Open Count" : "Review"}</button>
          {row.can_approve_adjustments && <button className="btn-primary" onClick={() => approveAdjustments(row.id)}>Approve Adjustment</button>}
        </div>}
      />
    </div>
    {showForm && <Modal title="New Cycle Count" wide onClose={() => setShowForm(false)}>
      <div className="space-y-4">
        <div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-800">Create a controlled physical count sheet for an authorized warehouse.</div>
        <label className="block text-sm font-medium text-slate-700">Warehouse
          <select data-field="warehouseId" className="input mt-1" value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)}>
            <option value="">Select warehouse...</option>
            {countWarehouses.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>)}
          </select>
        </label>
        {!countWarehouses.length && <div data-error-message="true" role="alert" className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">No assigned warehouse is currently eligible for Storekeeper cycle count.</div>}
        <div className="rounded-lg border border-slate-200 p-3">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <input data-field="itemQuery" type="search" className="input min-w-64 flex-1" placeholder="Search item code or description..." value={itemQuery} onChange={(e) => setItemQuery(e.target.value)} />
            <button type="button" className="btn-secondary" onClick={() => setItemIds(allSelected ? [] : items.map((item) => item.id))}>{allSelected ? "Clear All" : "Select All Items"}</button>
            <span className="text-sm font-semibold text-blue-700">{itemIds.length} selected</span>
          </div>
          <div className="grid max-h-72 gap-2 overflow-y-auto md:grid-cols-2">
            {visibleItems.map((item) => <label key={item.id} className="flex items-start gap-2 rounded-lg border border-slate-100 p-2 text-sm hover:bg-slate-50">
              <input className="mt-1" type="checkbox" checked={itemIds.includes(item.id)} onChange={(e) => setItemIds(e.target.checked ? [...itemIds, item.id] : itemIds.filter((id) => id !== item.id))} />
              <span><strong className="block text-slate-800">{item.item_code}</strong><span className="text-slate-500">{item.description}</span></span>
            </label>)}
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-200 pt-3">
          <button className="btn-secondary" onClick={() => setShowForm(false)}>Cancel</button>
          <button className="btn-primary" onClick={createCount}>Generate Count Sheet</button>
        </div>
      </div>
    </Modal>}
    {detail && <Modal title={`Count Sheet - ${detail.count_number}`} wide onClose={() => setDetail(null)}>
      <div className="space-y-4">
        <div className="overflow-x-auto">
          <table className="table-base">
            <thead><tr><th>Item</th><th>System Qty</th><th>Counted Qty</th><th>Variance</th><th>Notes</th></tr></thead>
            <tbody>{detail.items.map((item) => {
              const variance = Number(countedQtys[item.item_id] ?? item.counted_qty ?? item.system_qty) - Number(item.system_qty);
              return <tr key={item.id}>
                <td>{item.item_code} - {item.description}</td>
                <td>{item.system_qty}</td>
                <td>{detail.can_count ? <input data-field={item.item_id} className="input py-1" type="number" min="0" value={countedQtys[item.item_id] ?? ""} onChange={(e) => setCountedQtys({ ...countedQtys, [item.item_id]: e.target.value })} /> : item.counted_qty ?? "Not counted"}</td>
                <td className={Math.abs(variance) > 0.000001 ? "font-semibold text-amber-700" : "text-emerald-700"}>{variance.toLocaleString()}</td>
                <td>{detail.can_count ? <input className="input py-1" value={item.count_note || ""} onChange={(e) => setDetail({ ...detail, items: detail.items.map((line) => line.id === item.id ? { ...line, count_note: e.target.value } : line) })} /> : item.count_note || "-"}</td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        {detail.adjustments?.length > 0 && <div className="rounded-lg border border-amber-200 p-3 text-sm">
          <h3 className="font-semibold text-amber-900">Linked Variance Adjustments</h3>
          <div className="mt-2 space-y-1">{detail.adjustments.map((adjustment) => <div key={adjustment.id} className="flex justify-between gap-3">
            <span>{adjustment.adjustment_number} - {adjustment.item_code}</span>
            <span><StatusBadge status={adjustment.status} /></span>
          </div>)}</div>
        </div>}
        {detail.can_review && <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm font-medium">Review Reason
            <select className="input mt-1" value={reviewReason} onChange={(e) => setReviewReason(e.target.value)}>
              <option value="">Select...</option>
              <option>Count accepted</option>
              <option>Variance verified</option>
              <option>Documentation incomplete</option>
              <option>Recount required</option>
              <option>Other</option>
            </select>
          </label>
          <label className="text-sm font-medium">Review Comments
            <textarea className="input mt-1" value={reviewComments} onChange={(e) => setReviewComments(e.target.value)} />
          </label>
        </div>}
        <div className="flex flex-wrap justify-end gap-2">
          <button className="btn-secondary" onClick={() => setDetail(null)}>Close</button>
          {detail.can_count && <button className="btn-primary" onClick={submitCounts}>Submit Counts</button>}
          {detail.can_review && <button className="btn-secondary" onClick={() => decideCount("Request Recount")}>Request Recount</button>}
          {detail.can_review && <button className="btn-secondary" onClick={() => decideCount("Reject")}>Reject</button>}
          {detail.can_review && detail.items.every((item) => Math.abs(Number(item.variance || 0)) <= 0.000001) && <button className="btn-primary" onClick={() => approveCount(detail.id)}>Approve No Variance</button>}
          {detail.can_review && detail.items.some((item) => Math.abs(Number(item.variance || 0)) > 0.000001) && <button className="btn-primary" onClick={proposeAdjustments}>Submit Adjustment to SCM</button>}
          {detail.can_approve_adjustments && <button className="btn-primary" onClick={() => approveAdjustments(detail.id)}>Approve Adjustment & Post Inventory</button>}
        </div>
      </div>
    </Modal>}
  </div>;
}
