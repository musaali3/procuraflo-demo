# Stock Replenishment Check replaces auto PR

## Removed from active use

- Idle auto-PR scheduler and its application startup/shutdown hooks.
- Former `/api/procurement/replenishment/run-now` endpoint and obsolete scheduling helpers.
- Warehouse auto-generation settings and scheduled-day configuration in the UI/API.
- Auto-PR editor mode, fixed recommendation items, special zero-quantity editing, dashboard counters, and outdated help text.
- Former report keys `automatic-replenishment-prs` and `replenishment-run-history`.

## Current process

**Warehouse > Stock Replenishment Check → Run Check → Review → Revalidate → Create PR → Submit to Procurement.**

Running a check creates a review record only when stock is below the minimum and existing supply does not cover the shortage; it never creates a PR automatically. The calculation includes available stock, active PR coverage, outstanding POs, and receipts awaiting inspection/put-away. Creating a PR requires explicit action after review; the result is a normal draft with its check reference and recommendation/adjustment evidence retained.

Revalidation now persists changed stock positions as **Re-Review Required** before refusing PR creation. Retry of a converted check returns the existing PR and its current status. Ordinary draft editing requires positive quantities; zero requirements can be excluded during the replenishment review.

## Database and history

- Startup migration disables all legacy warehouse auto-generation flags.
- Database triggers prevent new automatically generated PRs, re-enabling scheduling, and new legacy automatic run/cycle records.
- Historical PRs, recommendations, cycles, runs, and audit records are retained. Legacy tables/columns remain for existing references; they no longer drive an active workflow.
- Historical PRs remain accessible through normal PR review, approval, and purchasing controls. Their origin is shown as **Historical Replenishment**; new check-linked PRs show **Stock Replenishment Check**.

## System-wide updates

- Backend: `main.py`, `replenishment.py`, `database.py`, `pr_workflow.py`, and routes `procurement.py`, `warehouse.py`, `masters.py`, `dashboard.py`, `reports.py`.
- Frontend: `PRPage.js`, `Dashboard.js`, `WarehousesPage.jsx`, `ItemsPage.js`, `ReportsPage.js`, `HelpPage.js`, and `ProfessionalPurchaseRequisition.js`.
- Reports now use `stock-replenishment-lines` and `stock-replenishment-history`. Warehouse users see their authorized warehouse scope; Procurement retains reporting access.
- Existing Stock Replenishment Check page, route, and sidebar entry are reused. README documents the current process; the earlier PR implementation report is marked as historical.

## Verification and limitations

- Changed Python files passed syntax parsing. Frontend production build passed with large-bundle warnings.
- Final source scan found no obsolete scheduler, run endpoint helper, auto editor mode, or old report/dashboard keys in active application code.
- Read-only inspection confirmed retirement triggers in the live default database and zero warehouses with legacy auto-generation enabled.
- No automated tests were created, modified, or run. No operational PRs were created for verification; the complete business flow still needs manual acceptance review.
- Old integrations or bookmarks using the removed endpoint/report keys must use the manual check workflow and new report keys.

## Low-stock selection and empty-check correction

- Items already stocked in the selected warehouse are included even without a default warehouse or item/warehouse setup row. Zero-balance stock rows remain eligible.
- A positive Item Master minimum stock takes priority over reorder level. Reorder level is retained as a fallback for older items without a positive minimum.
- Drafts contain below-minimum items, showing active PR, outstanding PO, and inspection/put-away coverage. A record is saved only if at least one line still requires additional supply.
- When no items are below minimum, Run Check returns a clear no-replenishment message without allocating a draft number or inserting a draft, lines, sources, or audit entry. If all low-stock items are covered, the screen shows their coverage without saving a record.
- Partially inspected quantities are deducted from the original inspection hold to avoid counting them again alongside the resulting put-away hold.
- Read-only inspection of the active RPC data found ITM-0001 at 1/minimum 20, ITM-0002 at 0/minimum 20, and ITM-0008 at 3/minimum 5. At inspection time, additional requirements after existing supply were 2, 0, and 0 units respectively.
- Existing empty historical checks were preserved. No operational check or PR was created during diagnosis, and no automated tests were created, modified, or run.
