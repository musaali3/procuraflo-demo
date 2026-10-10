import { useMemo, useState } from "react";
import { formatCurrency, isCurrencyField } from "../utils/currency";
import Modal from "./Modal";

const HIDDEN_DETAIL_FIELD = /password|token|secret|hash|permission_keys|warehouse_ids_json/i;

function safeDetailValue(value) {
  if (value == null || value === "") return "-";
  if (typeof value !== "object") return String(value);
  try { return JSON.stringify(value); } catch { return "Unable to display this value"; }
}

function rowDetailTitle(row) {
  return `${row.name || row.description || row.employee_code || row.supplier_code || row.item_code || row.po_number || row.pr_number || row.grn_number || row.invoice_number || "Record"} - Details`;
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

function compareValues(left, right, direction) {
  if (left == null || left === "") return right == null || right === "" ? 0 : 1;
  if (right == null || right === "") return -1;
  const leftNumber = Number(left);
  const rightNumber = Number(right);
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
  actionLabel = "View Details",
  inlineActions = false,
  detailActions = true,
  footer,
  searchable = true,
}) {
  const [query, setQuery] = useState("");
  const [detailRow, setDetailRow] = useState(null);
  const [sort, setSort] = useState({ key: "", direction: "asc" });

  const visibleRows = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return needle
      ? rows.filter((row) =>
          Object.values(row).some((value) =>
            String(value ?? "").toLocaleLowerCase().includes(needle),
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
    if (raw == null || raw === "") return "-";
    return isCurrencyField(key)
      ? formatCurrency(raw, row.currency || undefined)
      : String(raw);
  };

  const renderCell = (row, column) =>
    column.render ? column.render(row) : displayValue(row, String(column.key));

  const viewDetails = (row) =>
    onRowDoubleClick ? onRowDoubleClick(row) : setDetailRow(row);

  const primaryColumn = columns[0];
  const secondaryColumn = columns[1];
  const detailColumns = columns.slice(2);
  const sortableColumns = columns.filter((column) => column.sortable !== false).slice(0, 6);

  return (
    <div className="record-browser">
      {searchable && (
        <div className="data-table-toolbar flex flex-col gap-3 border-b border-slate-100 p-3 sm:flex-row sm:items-center sm:justify-between">
          <label className="data-table-search relative block w-full max-w-md">
            <span className="data-table-search-icon pointer-events-none absolute left-4 top-1/2 -translate-y-1/2" aria-hidden="true" />
            <input
              data-field="query"
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

      <div className="record-list-shell">
        {sortableColumns.length > 0 && (
          <div className="record-list-sortbar" aria-label="Sort records">
            <span>Sort by</span>
            <div>
              {sortableColumns.map((column) => (
                <button
                  type="button"
                  key={String(column.key)}
                  className={sort.key === String(column.key) ? "is-active" : ""}
                  onClick={() => sortBy(column)}
                  aria-pressed={sort.key === String(column.key)}
                >
                  {column.label}
                  {sort.key === String(column.key) && (
                    <span aria-hidden="true">{sort.direction === "asc" ? " up" : " down"}</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        {loading && <div className="record-list-empty" role="status">Loading...</div>}

        {!loading && sortedRows.length === 0 && (
          <div className="record-list-empty">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-slate-100 text-xl font-semibold text-slate-500">PF</div>
            <div className="mt-4 text-lg font-semibold text-slate-950">{emptyLabel}</div>
            <div className="mt-2 text-sm text-slate-500">Create a new record or adjust your search filters.</div>
          </div>
        )}

        {!loading && sortedRows.length > 0 && (
          <div className="record-list">
            {sortedRows.map((row, index) => (
              <article
                key={row.id ?? index}
                className="record-card"
                onClick={() => onRowClick?.(row)}
                onDoubleClick={() => viewDetails(row)}
                title="Double-click to view details"
              >
                <div className="record-card-main">
                  <div className="record-card-title">
                    {primaryColumn ? renderCell(row, primaryColumn) : "Record"}
                  </div>
                  {secondaryColumn && (
                    <div className="record-card-subtitle">{renderCell(row, secondaryColumn)}</div>
                  )}
                </div>

                <dl className="record-card-fields">
                  {detailColumns.slice(0, 8).map((column) => (
                    <div key={String(column.key)}>
                      <dt>{column.label}</dt>
                      <dd className={isCurrencyField(String(column.key)) ? "tabular-nums" : ""}>
                        {renderCell(row, column)}
                      </dd>
                    </div>
                  ))}
                </dl>

                <div
                  className="record-card-actions"
                  onClick={(event) => event.stopPropagation()}
                  onDoubleClick={(event) => event.stopPropagation()}
                >
                  <button type="button" className="record-view-button" onClick={() => viewDetails(row)}>
                    {actionLabel}
                  </button>
                  {inlineActions && actions?.(row)}
                </div>
              </article>
            ))}
          </div>
        )}

        {!loading && rows.length > 0 && footer && (
          <div className="record-list-footer">
            {footer.map((cell, index) => (
              <span key={index}>{cell}</span>
            ))}
          </div>
        )}
      </div>

      <RecordDetailModal row={detailRow} onClose={() => setDetailRow(null)} actions={detailActions && detailRow ? actions?.(detailRow) : null} />
    </div>
  );
}
