import HorizontalScroll from './HorizontalScroll';
import { PRODUCT_BRAND } from '../config/brand';
import { useMemo, useState } from "react";
import { formatCurrency, isCurrencyField } from "../utils/currency";
import Modal from "./Modal";

const HIDDEN_DETAIL_FIELD = /password|token|secret|hash|permission_keys|warehouse_ids_json/i;

function safeDetailValue(value) {
  if (value == null || value === "") return "—";
  if (typeof value !== "object") return String(value);
  try { return JSON.stringify(value); } catch { return "Unable to display this value"; }
}

function rowDetailTitle(row) {
  return `${row.name || row.description || row.employee_code || row.supplier_code || row.item_code || row.po_number || row.pr_number || row.grn_number || row.invoice_number || "Record"} — Details`;
}

export function RecordDetailModal({ row, onClose, actions }) {
  if (!row) return null;
  const status = row.status ?? row.approval_status ?? (row.active_yn != null ? (Number(row.active_yn) ? "Active" : "Inactive") : null);
  return (
    <Modal title={rowDetailTitle(row)} wide onClose={onClose}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-900">
        <span>Record details and authorized workflow actions</span>
        {status != null && status !== "" && (
          <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold uppercase tracking-wide text-blue-700 shadow-sm">{String(status)}</span>
        )}
      </div>
      {actions && <section className="record-detail-actions sticky top-0 z-20 mb-4 rounded-xl border-2 border-blue-300 bg-blue-50 p-4 shadow-lg">
        <div className="record-detail-actions-title">Available document actions</div>
        <div className="flex flex-wrap gap-3" onClick={(event) => { if (event.target.closest("button")) onClose(); }}>{actions}</div>
      </section>}
      <dl className="record-detail-grid">
        {Object.entries(row).filter(([key]) => !HIDDEN_DETAIL_FIELD.test(key)).map(([key, value]) => (
          <div key={key}>
            <dt>{key.replace(/_id$/, " ID").replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase())}</dt>
            <dd>{safeDetailValue(value)}</dd>
          </div>
        ))}
      </dl>
    </Modal>
  );
}

function openRowDetails(row) {
  document.getElementById("record-detail-dialog")?.remove();
  const dialog = document.createElement("dialog");
  dialog.id = "record-detail-dialog";
  dialog.className = "record-detail-dialog";
  const header = document.createElement("header"),
    title = document.createElement("h2"),
    close = document.createElement("button");
  title.textContent = `${row.name || row.description || row.employee_code || row.supplier_code || row.item_code || "Record"} — Details`;
  close.type = "button";
  close.className = "btn-secondary";
  close.textContent = "× Close";
  close.onclick = () => dialog.close();
  const logo = document.createElement("img");
  logo.src = PRODUCT_BRAND.logo;
  logo.alt = PRODUCT_BRAND.name;
  logo.className = "product-brand h-8 w-32 rounded object-contain";
  header.append(logo, title, close);
  const hint = document.createElement("p");
  hint.className = "record-detail-hint";
  hint.textContent = "Read-only master-data record";
  const details = document.createElement("dl");
  details.className = "record-detail-grid";
  const hidden =
    /password|token|secret|hash|permission_keys|warehouse_ids_json/i;
  Object.entries(row)
    .filter(([key]) => !hidden.test(key))
    .forEach(([key, value]) => {
      const field = document.createElement("div"),
        term = document.createElement("dt"),
        description = document.createElement("dd");
      term.textContent = key
        .replace(/_id$/, " ID")
        .replace(/_/g, " ")
        .replace(/\b\w/g, (character) => character.toUpperCase());
      description.textContent =
        value == null || value === ""
          ? "—"
          : typeof value === "object"
            ? JSON.stringify(value)
            : String(value);
      field.append(term, description);
      details.append(field);
    });
  dialog.append(header, hint, details);
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
  dialog.showModal();
}

function compareValues(left, right, direction) {
  if (left == null || left === "") return right == null || right === "" ? 0 : 1;
  if (right == null || right === "") return -1;
  const leftNumber = Number(left),
    rightNumber = Number(right);
  const result =
    Number.isFinite(leftNumber) && Number.isFinite(rightNumber)
      ? leftNumber - rightNumber
      : String(left).localeCompare(String(right), undefined, {
          numeric: true,
          sensitivity: "base",
        });
  return result * (direction === "asc" ? 1 : -1);
}

export default function DataTable({
  columns = [],
  rows = [],
  loading,
  emptyLabel = "No records found",
  onRowClick,
  onRowDoubleClick,
  actions,
  actionLabel = "View Document",
  inlineActions = false,
  detailActions = true,
  footer,
  searchable = true,
  tableClassName = "",
}) {
  const [query, setQuery] = useState(""),
    [detailRow, setDetailRow] = useState(null),
    [sort, setSort] = useState({ key: "", direction: "asc" });
  const visibleRows = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return needle
      ? rows.filter((row) =>
          Object.values(row).some((value) =>
            String(value ?? "")
              .toLocaleLowerCase()
              .includes(needle),
          ),
        )
      : rows;
  }, [rows, query]);
  const sortedRows = useMemo(
    () =>
      !sort.key
        ? visibleRows
        : [...visibleRows].sort((a, b) =>
            compareValues(a[sort.key], b[sort.key], sort.direction),
          ),
    [visibleRows, sort],
  );
  const sortBy = (column) =>
    column.sortable !== false &&
    setSort((current) =>
      current.key === String(column.key)
        ? {
            key: String(column.key),
            direction: current.direction === "asc" ? "desc" : "asc",
          }
        : { key: String(column.key), direction: "asc" },
    );
  const displayValue = (row, key) => {
    const raw = row[key];
    if (raw == null || raw === "") return "—";
    return isCurrencyField(key)
      ? formatCurrency(raw, row.currency || undefined)
      : String(raw);
  };
  const viewDetails = (row) =>
    onRowDoubleClick ? onRowDoubleClick(row) : setDetailRow(row);
  return (
    <div>
      {searchable && (
        <div className="data-table-toolbar flex flex-col gap-3 border-b border-slate-100 p-3 sm:flex-row sm:items-center sm:justify-between">
          <label className="data-table-search relative block w-full max-w-md">
            <span className="data-table-search-icon pointer-events-none absolute left-4 top-1/2 -translate-y-1/2" aria-hidden="true" />
            <input data-field={"query"}
              type="search"
              autoComplete="off"
              className="input w-full"
              placeholder="Search records, codes, names..."
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <div className="data-table-count rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-500 shadow-sm">
            {query
              ? `${visibleRows.length} matching records`
              : `${rows.length} total records`}
          </div>
        </div>
      )}
      <HorizontalScroll
        className={`data-table-scroll overflow-x-auto ${tableClassName ? "data-table-scroll-wide" : ""}`.trim()}
        tabIndex={0}
        role="region"
        aria-label="Scrollable data table. Use Shift and mouse wheel, the horizontal scrollbar, or keyboard arrow keys to view all columns."
      >
        <table className={`table-base ${tableClassName}`.trim()} data-managed-sort="true">
          {columns.some(column=>column.width)&&<colgroup>{columns.map(column=><col key={String(column.key)} style={{width:column.width}}/>)}<col style={{width:"8.25rem"}}/></colgroup>}
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  key={String(column.key)}
                  aria-sort={
                    sort.key === String(column.key)
                      ? sort.direction === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button
                    type="button"
                    className="table-sort-button"
                    onClick={() => sortBy(column)}
                    disabled={column.sortable === false}
                  >
                    <span>{column.label}</span>
                    {column.sortable !== false && (
                      <span className="table-sort-indicator" aria-hidden="true">
                        {sort.key === String(column.key)
                          ? sort.direction === "asc"
                            ? "▲"
                            : "▼"
                          : "↕"}
                      </span>
                    )}
                  </button>
                </th>
              ))}
              <th className="text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td
                  colSpan={columns.length + 1}
                  className="text-center py-8 text-slate-400"
                >
                  Loading...
                </td>
              </tr>
            )}
            {!loading && sortedRows.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length + 1}
                  className="data-table-empty py-16 text-center text-slate-500"
                >
                  <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-blue-50 text-3xl font-semibold text-blue-600">D</div>
                  <div className="mt-4 text-lg font-semibold text-slate-950">{emptyLabel}</div>
                  <div className="mt-2 text-sm text-slate-500">Create a new record or adjust your search filters.</div>
                </td>
              </tr>
            )}
            {!loading &&
              sortedRows.map((row, index) => (
                <tr
                  key={row.id ?? index}
                  onClick={() => onRowClick?.(row)}
                  onDoubleClick={() => viewDetails(row)}
                  title={
                    "Double-click to view details"
                  }
                  className={
                    onRowClick || sortedRows.length
                      ? "cursor-pointer hover:bg-slate-50"
                      : ""
                  }
                >
                  {columns.map((column) => (
                    <td
                      key={String(column.key)}
                      className={
                        isCurrencyField(String(column.key))
                          ? "text-right tabular-nums"
                          : ""
                      }
                    >
                      {column.render
                        ? column.render(row)
                        : displayValue(row, String(column.key))}
                    </td>
                  ))}
                  <td
                    className="text-right"
                    onClick={(event) => event.stopPropagation()}
                    onDoubleClick={(event) => event.stopPropagation()}
                  >
                    <div className="flex flex-wrap justify-end gap-2">
                      <button type="button" className="record-view-button" onClick={() => viewDetails(row)}>
                        {actionLabel}
                      </button>
                      {inlineActions && actions?.(row)}
                    </div>
                  </td>
                </tr>
              ))}
          </tbody>
          {!loading && rows.length > 0 && footer && (
            <tfoot>
              <tr className="bg-slate-100 font-bold text-slate-900">
                {footer.map((cell, index) => (
                  <td
                    key={index}
                    className="border-t-2 border-slate-300 px-4 py-3"
                  >
                    {cell}
                  </td>
                ))}
                <td className="border-t-2 border-slate-300" />
              </tr>
            </tfoot>
          )}
        </table>
      </HorizontalScroll>
      <RecordDetailModal row={detailRow} onClose={() => setDetailRow(null)} actions={detailActions && detailRow ? actions?.(detailRow) : null} />
    </div>
  );
}
