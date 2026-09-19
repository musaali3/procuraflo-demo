import { useEffect, useMemo, useState } from "react";
import client from "../../api/client";
import DataTable from "../../components/DataTable";
import Modal from "../../components/Modal";
import StatusBadge from "../../components/StatusBadge";
import useAutoRefresh from "../../hooks/useAutoRefresh";

const reasons = ["Item no longer required", "Stock found", "Duplicate requirement", "Upcoming transfer", "Incorrect reorder level", "Demand change", "Other"];
const n = value => Number(value || 0).toLocaleString();
const activityStatus = status => ({ Draft: "Created", "Review Complete": "Reviewed" }[status] || status);

export default function ReplenishmentCheckPage() {
  const [warehouses, setWarehouses] = useState([]);
  const [warehouseId, setWarehouseId] = useState("");
  const [drafts, setDrafts] = useState([]);
  const [detail, setDetail] = useState(null);
  const [selectedLine, setSelectedLine] = useState(null);
  const [error, setError] = useState("");
  const [warning, setWarning] = useState(null);
  const [checkResult, setCheckResult] = useState(null);
  const [checking, setChecking] = useState(false);

  const load = () => Promise.all([client.get("/masters/warehouses"), client.get("/warehouse/replenishment/drafts")]).then(([w, d]) => {
    setWarehouses(w.data);
    setDrafts(d.data);
    if (!warehouseId && w.data.length === 1) setWarehouseId(String(w.data[0].id));
  });
  useAutoRefresh(load);
  useEffect(() => { load().catch(e => setError(e.response?.data?.error || "Unable to load replenishment data")); }, []);

  const rows = useMemo(() => detail?.lines || [], [detail]);
  const changed = rows.some(line => line.line_status === "Re-Review Required");

  async function runCheck() {
    if (checking || !warehouseId) return;
    setError(""); setWarning(null); setCheckResult(null); setChecking(true);
    try {
      const response = await client.post("/warehouse/replenishment/check", { warehouse_id: Number(warehouseId) });
      await load();
      if (response.data.created) await openDraft(response.data.id);
      else { setDetail(null); setCheckResult(response.data); }
    } catch (e) {
      setError(e.response?.data?.error || "Unable to run replenishment check");
    } finally { setChecking(false); }
  }

  async function openDraft(id, clearWarning = true) {
    const response = await client.get(`/warehouse/replenishment/drafts/${id}`);
    setDetail(response.data);
    if (clearWarning) setWarning(null);
  }

  function updateLine(id, field, value) {
    setDetail({ ...detail, lines: detail.lines.map(line => line.id === id ? { ...line, [field]: value } : line) });
  }

  async function completeReview() {
    setError(""); setWarning(null);
    try {
      await client.put(`/warehouse/replenishment/drafts/${detail.id}/review`, { lines: detail.lines.map(line => ({ id: line.id, reviewed_qty: Number(line.reviewed_qty), adjustment_reason: line.adjustment_reason || "" })) });
      await openDraft(detail.id);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || "Unable to complete review");
    }
  }

  async function revalidate() {
    setError(""); setWarning(null);
    try {
      const response = await client.post(`/warehouse/replenishment/drafts/${detail.id}/revalidate`);
      if (response.data.changed) setWarning({ message: "Stock Position Changed", changes: response.data.changes });
      await openDraft(detail.id, false);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || "Unable to revalidate draft");
    }
  }

  async function createPR() {
    setError(""); setWarning(null);
    try {
      await client.post(`/warehouse/replenishment/drafts/${detail.id}/create-pr`);
      setDetail(null);
      await load();
    } catch (e) {
      const data = e.response?.data?.error;
      if (data && typeof data === "object") setWarning({ message: data.message || "Stock Position Changed", changes: data.changes || [] });
      else setError(data || "Unable to create PR");
      if (detail) openDraft(detail.id, false).catch(() => undefined);
    }
  }

  return <div>
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Stock Replenishment Check</h1>
        <p className="text-sm text-slate-500">Find stock below the Item Master minimum. Existing PRs, POs and incoming receipts reduce the additional quantity required. A draft is saved only when an uncovered shortage is found.</p>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-sm font-medium">Warehouse
          <select className="input mt-1 min-w-64" value={warehouseId} disabled={checking} onChange={e => { setWarehouseId(e.target.value); setCheckResult(null); }}>
            <option value="">Select warehouse...</option>
            {warehouses.map(warehouse => <option key={warehouse.id} value={warehouse.id}>{warehouse.warehouse_code} - {warehouse.name}</option>)}
          </select>
        </label>
        <button className="btn-primary" disabled={!warehouseId || checking} onClick={runCheck}>{checking ? "Checking stock..." : "Run Replenishment Check"}</button>
      </div>
    </div>
    {error && <div data-error-message="true" role="alert" className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
    {checkResult && <section className="mb-3 rounded-lg border border-blue-200 bg-blue-50 p-3">
      <p role="status" className="text-sm font-medium text-blue-900">{checkResult.message}</p>
      <p className="mt-1 text-xs text-blue-800">No replenishment record was created.</p>
      {checkResult.lines?.length > 0 && <div className="mt-3"><DataTable rows={checkResult.lines} columns={[
        { key: "item_code", label: "Item" }, { key: "description", label: "Description" },
        { key: "available_qty", label: "Available" }, { key: "reorder_level", label: "Minimum" },
        { key: "active_pr_qty", label: "Active PR" }, { key: "outstanding_po_qty", label: "PO Open" },
        { key: "inspection_putaway_qty", label: "Inspection / Put-Away" },
        { key: "system_recommended_qty", label: "Additional Required" },
        { key: "status_labels", label: "Coverage" },
      ]} /></div>}
    </section>}
    <div className="card">
      <DataTable rows={drafts} columns={[
        { key: "draft_number", label: "Draft Number" },
        { key: "warehouse_name", label: "Warehouse" },
        { key: "created_at", label: "Check Date" },
        { key: "checked_by_name", label: "Checked By" },
        { key: "item_count", label: "Items" },
        { key: "replenishment_required_count", label: "Required" },
        { key: "zero_reviewed_count", label: "Zero Qty" },
        { key: "status", label: "Status", render: row => <StatusBadge status={activityStatus(row.status)} /> },
        { key: "pr_number", label: "Resulting PR", render: row => row.pr_number || "-" },
      ]} actions={row => <button className="btn-secondary text-xs" onClick={() => openDraft(row.id)}>Open</button>} />
    </div>
    {detail && <Modal wide title={`${detail.draft_number} - ${detail.warehouse_name}`} onClose={() => setDetail(null)}>
      <div className="space-y-4">
        <div className="grid gap-2 rounded-lg bg-slate-50 p-3 text-sm md:grid-cols-4">
          <div><strong>Status</strong><br /><StatusBadge status={activityStatus(detail.status)} /></div>
          <div><strong>Checked</strong><br />{detail.created_at}</div>
          <div><strong>Checked By</strong><br />{detail.checked_by_name || "-"}</div>
          <div><strong>PR</strong><br />{detail.pr_number || "-"}</div>
        </div>
        {warning && <div data-error-message="true" role="alert" className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          <strong>{warning.message}</strong>
          <div className="mt-2 space-y-2">{warning.changes.map(change => <div key={change.line_id} className="rounded bg-white p-2">
            <div className="font-semibold">{change.item_code} - {change.description}</div>
            <div>Recommended Qty: {n(change.previous_recommended_qty)} to {n(change.current_recommended_qty)}</div>
            {change.changes.map(diff => <div key={diff.field} className="text-xs">{diff.field.replaceAll("_", " ")}: {n(diff.previous)} to {n(diff.current)}</div>)}
          </div>)}</div>
        </div>}
        <div className="overflow-x-auto">
          <table className="table-base">
            <thead><tr><th>Item</th><th>Available</th><th>Minimum</th><th>Active PR</th><th>PO Open</th><th>Inspection / Put-Away</th><th>Effective</th><th>System Rec.</th><th>Reviewed Qty</th><th>Status</th><th>Reason</th></tr></thead>
            <tbody>{rows.map(line => {
              const changedQty = Number(line.reviewed_qty) !== Number(line.system_recommended_qty);
              const editable = !["Converted to PR", "Cancelled"].includes(detail.status);
              return <tr key={line.id} className={line.line_status === "Re-Review Required" ? "bg-amber-50" : ""}>
                <td><button className="font-semibold text-blue-700 hover:underline" onClick={() => setSelectedLine(line)}>{line.item_code_snapshot}</button><div className="text-xs text-slate-500">{line.description_snapshot}</div></td>
                <td>{n(line.available_qty)}</td><td>{n(line.reorder_level)}</td><td>{n(line.active_pr_qty)}</td><td>{n(line.outstanding_po_qty)}</td><td>{n(line.inspection_putaway_qty)}</td><td>{n(line.effective_stock_qty)}</td><td>{n(line.system_recommended_qty)}</td>
                <td>{editable ? <input className="input w-24 py-1" type="number" min="0" value={line.reviewed_qty} onChange={e => updateLine(line.id, "reviewed_qty", e.target.value)} /> : n(line.reviewed_qty)}</td>
                <td><StatusBadge status={activityStatus(editable ? line.line_status : detail.status)} /></td>
                <td>{editable && changedQty ? <select className="input min-w-44 py-1" value={line.adjustment_reason || ""} onChange={e => updateLine(line.id, "adjustment_reason", e.target.value)}><option value="">Select reason...</option>{reasons.map(reason => <option key={reason}>{reason}</option>)}</select> : line.adjustment_reason || "-"}</td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <button className="btn-secondary" onClick={() => setDetail(null)}>Close</button>
          {!["Converted to PR", "Cancelled"].includes(detail.status) && <button className="btn-secondary" onClick={revalidate}>Revalidate</button>}
          {!["Converted to PR", "Cancelled"].includes(detail.status) && <button className="btn-primary" onClick={completeReview}>Complete Review</button>}
          {detail.status === "Review Complete" && !changed && <button className="btn-primary" onClick={createPR}>Create PR</button>}
        </div>
      </div>
    </Modal>}
    {selectedLine && <Modal title={`${selectedLine.item_code_snapshot} Calculation`} onClose={() => setSelectedLine(null)}>
      <div className="space-y-3 text-sm">
        <div className="rounded-lg bg-slate-50 p-3">
          <div><strong>Available Stock:</strong> {n(selectedLine.available_qty)}</div>
          <div><strong>Active PR Qty:</strong> {n(selectedLine.active_pr_qty)}</div>
          <div><strong>Outstanding PO Qty:</strong> {n(selectedLine.outstanding_po_qty)}</div>
          <div><strong>Inspection / Put-Away Qty:</strong> {n(selectedLine.inspection_putaway_qty)}</div>
          <div><strong>Effective Stock Position:</strong> {n(selectedLine.effective_stock_qty)}</div>
          <div><strong>Recommended Qty:</strong> {n(selectedLine.system_recommended_qty)}</div>
        </div>
        <div className="space-y-2">{selectedLine.sources?.length ? selectedLine.sources.map(source => <div key={source.id} className="rounded-lg border border-slate-200 p-2">
          <strong>{source.source_type} {source.source_number || source.source_id}</strong>
          <div>Status: {source.status}</div>
          <div>Quantity: {n(source.quantity)}</div>
        </div>) : <div className="text-slate-500">No active source documents contribute to this line.</div>}</div>
      </div>
    </Modal>}
  </div>;
}
