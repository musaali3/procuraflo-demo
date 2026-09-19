import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException

from .audit import log_audit
from .calculations import decimal_value
from .database import transaction

WAREHOUSE_ROLES = {"SupplyChainManager", "WarehouseManager", "WarehouseSupervisor", "Storekeeper"}
TERMINAL_DRAFT_STATUSES = {"Converted to PR", "Cancelled"}


def _number(c, kind, prefix):
    company = c.execute("SELECT financial_year FROM company ORDER BY id DESC LIMIT 1").fetchone()
    import re
    years = re.findall(r"\d{4}", str(company["financial_year"] if company else ""))
    year = years[-1] if years else str(datetime.now().year)
    row = c.execute("SELECT last_number FROM numbering_counters WHERE doc_type=? AND year=?", (kind, year)).fetchone()
    seq = (row["last_number"] if row else 0) + 1
    c.execute("INSERT INTO numbering_counters(doc_type,year,last_number)VALUES(?,?,?) ON CONFLICT(doc_type,year)DO UPDATE SET last_number=excluded.last_number", (kind, year, seq))
    return f"{prefix}-{year}-{seq:06d}"


def _as_float(value):
    return float(decimal_value(value or 0))


def _source(source_type, source_id, source_number, status, quantity, **detail):
    return {"source_type": source_type, "source_id": source_id, "source_number": source_number, "status": status, "quantity": float(quantity), "detail": detail}


def warehouse_scope(user, warehouse_id):
    try:
        warehouse_id = int(warehouse_id)
    except (TypeError, ValueError):
        raise HTTPException(400, "A valid warehouse is required")
    if user["role"] != "SupplyChainManager" and warehouse_id not in {int(x) for x in user.get("warehouse_ids", [])}:
        raise HTTPException(403, "Warehouse is outside your authorized scope")
    return warehouse_id


def _item_rows(c, warehouse_id):
    return c.execute(
        """SELECT i.*,CASE WHEN i.min_stock>0 THEN i.min_stock ELSE COALESCE(i.reorder_level,0) END minimum_threshold,COALESCE((SELECT SUM(s.quantity) FROM inventory_stock s WHERE s.item_id=i.id AND s.warehouse_id=?),0) available_qty
           FROM items i
          WHERE i.deleted_at IS NULL AND i.active_yn=1
            AND CASE WHEN i.min_stock>0 THEN i.min_stock ELSE COALESCE(i.reorder_level,0) END>0
            AND (i.default_warehouse_id=?
                 OR EXISTS(SELECT 1 FROM item_warehouse_settings iws WHERE iws.item_id=i.id AND iws.warehouse_id=?)
                 OR EXISTS(SELECT 1 FROM inventory_stock s WHERE s.item_id=i.id AND s.warehouse_id=?)
                 OR EXISTS(SELECT 1 FROM inventory_layers l WHERE l.item_id=i.id AND l.warehouse_id=?)
                 OR EXISTS(SELECT 1 FROM inventory_quarantine q WHERE q.item_id=i.id AND q.warehouse_id=? AND q.released_at IS NULL))
          ORDER BY i.item_code""",
        (warehouse_id, warehouse_id, warehouse_id, warehouse_id, warehouse_id, warehouse_id),
    ).fetchall()


def _active_pr(c, warehouse_id, item_id):
    rows = c.execute(
        """SELECT pr.id,pr.pr_number,pr.status,pi.id pr_item_id,
                  MAX(0,COALESCE(pi.approved_base_quantity,pi.base_quantity,pi.approved_quantity,pi.quantity)
                    - COALESCE((SELECT SUM(a.quantity*COALESCE(pi.conversion_factor_used,1))
                        FROM po_pr_item_allocations a JOIN purchase_orders po ON po.id=a.po_id
                       WHERE a.pr_item_id=pi.id AND po.status IN ('Draft','PendingApproval','Approved','Printed','Partially Received','Closed')),0)) remaining_qty
             FROM pr_items pi JOIN purchase_requisitions pr ON pr.id=pi.pr_id
            WHERE pi.item_id=? AND COALESCE(pi.source_warehouse_id,pr.trigger_warehouse_id)=?
              AND pr.status IN ('Draft','Submitted','Approved','Partially Ordered')
            ORDER BY pr.id,pi.id""",
        (item_id, warehouse_id),
    ).fetchall()
    sources = [_source("PR", row["id"], row["pr_number"], row["status"], row["remaining_qty"], pr_item_id=row["pr_item_id"]) for row in rows if _as_float(row["remaining_qty"]) > 0]
    return sum(Decimal(str(src["quantity"])) for src in sources), sources


def _po_outstanding(c, warehouse_id, item_id):
    rows = c.execute(
        """SELECT po.id,po.po_number,po.status,pi.id po_item_id,
                  COALESCE(pi.base_quantity,pi.quantity*COALESCE(pi.conversion_factor_used,1),pi.quantity) ordered_qty,
                  COALESCE((SELECT SUM(COALESCE(gi.accepted_base_quantity,gi.accepted_qty*COALESCE(gi.conversion_factor_used,1),gi.accepted_qty))
                      FROM grn_items gi JOIN grns g ON g.id=gi.grn_id
                     WHERE g.po_id=po.id AND gi.item_id=pi.item_id AND gi.warehouse_id=?),0) received_qty
             FROM po_items pi JOIN purchase_orders po ON po.id=pi.po_id
            WHERE pi.item_id=? AND COALESCE(po.delivery_warehouse_id,(SELECT r.delivery_warehouse_id FROM rfqs r WHERE r.id=po.rfq_id),?)=?
              AND po.status IN ('Draft','PendingApproval','Approved','Printed','Partially Received')
            ORDER BY po.id,pi.id""",
        (warehouse_id, item_id, warehouse_id, warehouse_id),
    ).fetchall()
    sources = []
    for row in rows:
        outstanding = max(Decimal("0"), decimal_value(row["ordered_qty"]) - decimal_value(row["received_qty"]))
        if outstanding > 0:
            sources.append(_source("PO", row["id"], row["po_number"], row["status"], outstanding, po_item_id=row["po_item_id"], ordered_qty=_as_float(row["ordered_qty"]), received_qty=_as_float(row["received_qty"])))
    return sum(Decimal(str(src["quantity"])) for src in sources), sources


def _inspection_putaway(c, warehouse_id, item_id):
    grn_columns = {row["name"] for row in c.execute("PRAGMA table_info(grns)").fetchall()}
    grn_status_expr = "g.status" if "status" in grn_columns else "'Posted'"
    rows = c.execute(
        f"""SELECT q.id,q.inventory_status,
                  CASE WHEN q.inventory_status='INSPECTION_PENDING' THEN MAX(0,q.quantity-COALESCE((SELECT SUM(inspected_quantity) FROM goods_inspections WHERE hold_id=q.id),0)) ELSE q.quantity END quantity,q.audit_reference,g.grn_number,{grn_status_expr} grn_status
             FROM inventory_quarantine q
             LEFT JOIN grn_items gi ON gi.id=q.source_grn_item_id
             LEFT JOIN grns g ON g.id=gi.grn_id
            WHERE q.item_id=? AND q.warehouse_id=? AND q.released_at IS NULL
              AND q.inventory_status IN ('INSPECTION_PENDING','PUT_AWAY_PENDING')
            ORDER BY q.id""",
        (item_id, warehouse_id),
    ).fetchall()
    sources = [_source("GRN", row["id"], row["grn_number"] or row["audit_reference"], row["inventory_status"], row["quantity"], grn_status=row["grn_status"]) for row in rows if _as_float(row["quantity"]) > 0]
    return sum(Decimal(str(src["quantity"])) for src in sources), sources


def calculate_replenishment(c, warehouse_id):
    results = []
    now = datetime.now(timezone.utc).isoformat()
    for item in _item_rows(c, warehouse_id):
        available = decimal_value(item["available_qty"])
        reorder = decimal_value(item["minimum_threshold"])
        pr_qty, pr_sources = _active_pr(c, warehouse_id, item["id"])
        po_qty, po_sources = _po_outstanding(c, warehouse_id, item["id"])
        hold_qty, hold_sources = _inspection_putaway(c, warehouse_id, item["id"])
        effective = available + pr_qty + po_qty + hold_qty
        recommended = max(Decimal("0"), reorder - effective)
        labels = ["Replenishment Required" if recommended > 0 else ("Below Minimum - Covered by Existing Supply" if available < reorder else "No Replenishment Required")]
        if pr_qty > 0: labels.append("PR In Progress")
        if po_qty > 0: labels.append("PO In Progress")
        if hold_qty > 0: labels.append("Inspection / Put-Away Pending")
        if sum(1 for qty in (pr_qty, po_qty, hold_qty) if qty > 0) > 1: labels.append("Multiple Supply Stages Active")
        results.append({"item_id": item["id"], "item_code": item["item_code"], "description": item["description"], "uom": item["uom"], "reorder_level": float(reorder), "available_qty": float(available), "active_pr_qty": float(pr_qty), "outstanding_po_qty": float(po_qty), "inspection_putaway_qty": float(hold_qty), "effective_stock_qty": float(effective), "system_recommended_qty": float(recommended), "reviewed_qty": float(recommended), "status_labels": " - ".join(labels), "last_checked_at": now, "sources": pr_sources + po_sources + hold_sources})
    return results


def create_replenishment_draft(warehouse_id, user):
    if user["role"] not in WAREHOUSE_ROLES:
        raise HTTPException(403, "Warehouse access is required")
    warehouse_id = warehouse_scope(user, warehouse_id or (user.get("warehouse_ids") or [None])[0])
    with transaction(immediate=True) as c:
        if not c.execute("SELECT 1 FROM warehouses WHERE id=? AND deleted_at IS NULL", (warehouse_id,)).fetchone():
            raise HTTPException(404, "Warehouse not found")
        checked = calculate_replenishment(c, warehouse_id)
        lines = [line for line in checked if line["available_qty"] < line["reorder_level"]]
        required = [line for line in lines if line["system_recommended_qty"] > 0]
        if not required:
            message = ("No items are below the minimum stock threshold. Replenishment is not required."
                       if not lines else "Items below minimum stock are already covered by active PRs, outstanding POs, or incoming receipts. No additional replenishment is required.")
            return {"created": False, "id": None, "message": message, "items_checked": len(checked),
                    "below_minimum_count": len(lines), "required_count": 0, "lines": lines}
        draft_number = _number(c, "REPLENISHMENT", "RPL")
        draft_id = c.execute("INSERT INTO replenishment_drafts(draft_number,warehouse_id,checked_by)VALUES(?,?,?)", (draft_number, warehouse_id, user["id"])).lastrowid
        for line in lines:
            line_id = c.execute("""INSERT INTO replenishment_draft_lines(draft_id,item_id,item_code_snapshot,description_snapshot,uom,reorder_level,available_qty,active_pr_qty,outstanding_po_qty,inspection_putaway_qty,effective_stock_qty,system_recommended_qty,reviewed_qty,status_labels,last_checked_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (draft_id, line["item_id"], line["item_code"], line["description"], line["uom"], line["reorder_level"], line["available_qty"], line["active_pr_qty"], line["outstanding_po_qty"], line["inspection_putaway_qty"], line["effective_stock_qty"], line["system_recommended_qty"], line["reviewed_qty"], line["status_labels"], line["last_checked_at"])).lastrowid
            for source in line["sources"]:
                c.execute("INSERT INTO replenishment_draft_sources(line_id,source_type,source_id,source_number,status,quantity,detail_json)VALUES(?,?,?,?,?,?,?)", (line_id, source["source_type"], source["source_id"], source["source_number"], source["status"], source["quantity"], json.dumps(source["detail"])))
        log_audit(c, "replenishment_drafts", draft_id, "CREATE", user["id"], after={"warehouse_id": warehouse_id, "line_count": len(lines)})
    return {"created": True, "id": draft_id, "draft_number": draft_number, "line_count": len(lines), "required_count": len(required)}


def draft_detail(c, draft_id):
    draft = c.execute("""SELECT d.*,w.name warehouse_name,w.warehouse_code,pr.pr_number,pr.status pr_status,u.full_name checked_by_name,ru.full_name reviewed_by_name FROM replenishment_drafts d JOIN warehouses w ON w.id=d.warehouse_id LEFT JOIN purchase_requisitions pr ON pr.id=d.resulting_pr_id LEFT JOIN users u ON u.id=d.checked_by LEFT JOIN users ru ON ru.id=d.reviewed_by WHERE d.id=?""", (draft_id,)).fetchone()
    if not draft: return None
    result = dict(draft)
    result["lines"] = [dict(row) for row in c.execute("SELECT * FROM replenishment_draft_lines WHERE draft_id=? ORDER BY id", (draft_id,))]
    for line in result["lines"]:
        line["sources"] = [dict(row) for row in c.execute("SELECT * FROM replenishment_draft_sources WHERE line_id=? ORDER BY id", (line["id"],))]
        for source in line["sources"]:
            try: source["detail"] = json.loads(source.get("detail_json") or "{}")
            except ValueError: source["detail"] = {}
    return result


def complete_review(draft_id, lines, user):
    with transaction(immediate=True) as c:
        draft = draft_detail(c, draft_id)
        if not draft: raise HTTPException(404, "Replenishment draft not found")
        warehouse_scope(user, draft["warehouse_id"])
        if draft["status"] in TERMINAL_DRAFT_STATUSES: raise HTTPException(409, f"Draft is {draft['status']}")
        existing = {line["id"]: line for line in draft["lines"]}
        if not isinstance(lines, list) or {x.get("id") for x in lines} != set(existing): raise HTTPException(400, "Review every replenishment line exactly once")
        for change in lines:
            line = existing[change["id"]]
            qty = decimal_value(change.get("reviewed_qty"))
            if not qty.is_finite() or qty < 0: raise HTTPException(400, "Reviewed quantity must be zero or greater")
            reason = str(change.get("adjustment_reason") or "").strip()
            if qty != decimal_value(line["system_recommended_qty"]) and not reason: raise HTTPException(400, "Adjustment reason is required when reviewed quantity differs from system recommendation")
            c.execute("UPDATE replenishment_draft_lines SET reviewed_qty=?,adjustment_reason=?,line_status='Reviewed',reviewed_by=?,reviewed_at=datetime('now'),revalidation_changes_json=NULL WHERE id=?", (float(qty), reason or None, user["id"], line["id"]))
        c.execute("UPDATE replenishment_drafts SET status='Review Complete',reviewed_by=?,reviewed_at=datetime('now') WHERE id=?", (user["id"], draft_id))
        log_audit(c, "replenishment_drafts", draft_id, "UPDATE", user["id"], before={"status": draft["status"]}, after={"status": "Review Complete"})
    return {"success": True, "status": "Review Complete"}


def revalidate_draft(c, draft):
    current = {line["item_id"]: line for line in calculate_replenishment(c, draft["warehouse_id"])}
    changes = []
    fields = ("available_qty", "active_pr_qty", "outstanding_po_qty", "inspection_putaway_qty", "effective_stock_qty", "system_recommended_qty", "reorder_level")
    for line in draft["lines"]:
        now = current.get(line["item_id"])
        if not now: continue
        diffs = [{"field": field, "previous": line[field], "current": now[field]} for field in fields if decimal_value(line[field]) != decimal_value(now[field])]
        if diffs:
            changes.append({"line_id": line["id"], "item_id": line["item_id"], "item_code": line["item_code_snapshot"], "description": line["description_snapshot"], "previous_recommended_qty": line["system_recommended_qty"], "current_recommended_qty": now["system_recommended_qty"], "changes": diffs})
            c.execute("""UPDATE replenishment_draft_lines SET reorder_level=?,available_qty=?,active_pr_qty=?,outstanding_po_qty=?,inspection_putaway_qty=?,effective_stock_qty=?,system_recommended_qty=?,status_labels=?,line_status='Re-Review Required',revalidated_at=datetime('now'),revalidation_changes_json=? WHERE id=?""", (now["reorder_level"], now["available_qty"], now["active_pr_qty"], now["outstanding_po_qty"], now["inspection_putaway_qty"], now["effective_stock_qty"], now["system_recommended_qty"], now["status_labels"], json.dumps(diffs), line["id"]))
    c.execute("UPDATE replenishment_drafts SET status=?,revalidated_at=datetime('now') WHERE id=?", ("Re-Review Required" if changes else draft["status"], draft["id"]))
    return changes


def create_pr_from_draft(draft_id, user):
    with transaction(immediate=True) as c:
        draft = draft_detail(c, draft_id)
        if not draft: raise HTTPException(404, "Replenishment draft not found")
        warehouse_scope(user, draft["warehouse_id"])
        if draft["status"] == "Converted to PR" and draft.get("resulting_pr_id"):
            return {"id": draft["resulting_pr_id"], "pr_number": draft["pr_number"], "status": draft["pr_status"], "idempotent": True}
        if draft["status"] != "Review Complete": raise HTTPException(409, "Complete review before creating the PR")
        changes = revalidate_draft(c, draft)
        if not changes:
            positive = [line for line in draft["lines"] if decimal_value(line["reviewed_qty"]) > 0]
            if not positive: raise HTTPException(400, "At least one reviewed quantity must be greater than zero to create a PR")
            department = c.execute("SELECT id FROM departments WHERE lower(name)='warehouse' AND deleted_at IS NULL LIMIT 1").fetchone() or c.execute("SELECT id FROM departments ORDER BY id LIMIT 1").fetchone()
            employee = c.execute("SELECT employee_id FROM users WHERE id=?", (user["id"],)).fetchone()
            pr_number = _number(c, "PR", "PR")
            pr_id = c.execute("""INSERT INTO purchase_requisitions(pr_number,requestor_id,business_requestor_employee_id,department_id,status,auto_generated,pr_source,trigger_warehouse_id,replenishment_draft_id) VALUES(?,?,?,?,'Draft',0,'WAREHOUSE_MANUAL',?,?)""", (pr_number, user["id"], employee["employee_id"] if employee else None, department["id"], draft["warehouse_id"], draft_id)).lastrowid
            for line in positive:
                item = c.execute("SELECT * FROM items WHERE id=?", (line["item_id"],)).fetchone()
                uom = item["purchase_uom"] or item["uom"]
                factor = decimal_value(item["conversion_factor"] or 1) if uom != item["uom"] else Decimal("1")
                qty = float(decimal_value(line["reviewed_qty"]) / factor)
                c.execute("""INSERT INTO pr_items(pr_id,item_id,quantity,warehouse_requested_quantity,required_date,reason,transaction_quantity,transaction_uom,conversion_factor_used,base_quantity,base_uom,source_warehouse_id,stock_quantity_snapshot,min_stock_snapshot,target_stock_snapshot,auto_replenishment,recommended_base_quantity,quantity_variance,adjustment_reason,adjusted_by,adjusted_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,datetime('now'))""", (pr_id, line["item_id"], qty, qty, (datetime.now()+timedelta(days=7)).date().isoformat(), f"Stock Replenishment Check {draft['draft_number']}", qty, uom, float(factor), line["reviewed_qty"], item["uom"], draft["warehouse_id"], line["available_qty"], line["reorder_level"], line["system_recommended_qty"], line["system_recommended_qty"], float(decimal_value(line["reviewed_qty"]) - decimal_value(line["system_recommended_qty"])), line["adjustment_reason"], user["id"]))
            c.execute("UPDATE replenishment_drafts SET status='Converted to PR',resulting_pr_id=?,converted_at=datetime('now') WHERE id=? AND resulting_pr_id IS NULL", (pr_id, draft_id))
            log_audit(c, "purchase_requisitions", pr_id, "CREATE", user["id"], after={"source": "Stock Replenishment Check", "replenishment_draft_id": draft_id})
            return {"id": pr_id, "pr_number": pr_number, "status": "Draft"}
    raise HTTPException(409, {"message": "Stock Position Changed", "changes": changes})
