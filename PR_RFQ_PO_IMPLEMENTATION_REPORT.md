> Current workflow: Stock Replenishment Check has replaced the former auto-PR workflow described in this historical report. See README.md for the current process.

Procuraflo PR / RFQ / PO implementation report

Updated 7 September 2026 against `ProcuraFlow_Combined_PR_RFQ_PO_UI_Requirements.pdf`.
The user's current Procuraflo name, supplied logo, rounded logo background and removal of visible table/page branding footers take precedence over the PDF's older product name.

Workflow implemented

- Manual Warehouse PR: Draft ? Submit to Procurement ? Procurement quantity review ? authorized approval ? RFQ or direct PO. Before submission, Warehouse drafts are inaccessible to Procurement through lists, detail/history APIs, attachments, reports, dashboard tasks, notifications and selectors. Warehouse retains scoped read access after submission; draft editing is then locked.
- Manual Procurement PR: Draft ? Submit for Review ? Procurement review ? authorized approval. Creation never approves a PR. Self-approval requires an active explicit delegation; ordinary employee limits and approval routing remain enforced.
- Auto PR: warehouse-owned Draft with preserved system recommendation, requested quantity, variance and adjustment reason. Warehouse can edit, submit, or close/reject when no purchase is required. An active company/warehouse/item replenishment cycle prevents duplicate recommendations after quantity reduction.
- Replenishment defaults to Monday/Thursday, configurable per warehouse. Normal sites use local operating start/end and operating days; 24-hour sites use local midnight. Current eligible stock at/below minimum (or reorder level) triggers a recommendation of maximum minus eligible stock. SCM manual runs share the same cycle rules and are audited.
- Procurement review stores approved quantity separately from the request, including variance, reason, reviewer and time. Approval writes the real approval log and PR approval metadata. A zero-quantity line is allowed; if nothing is needed, the PR must be rejected instead of approved.

One purchasing balance

`app/pr_workflow.py` provides shared access, approval validity, eligibility, line balances, PO allocation and lifecycle reconciliation. Both RFQ and direct PO use the same approved-with-remaining-quantity rule.

Each PR line balance is approved quantity minus PO allocations in valid commitment statuses: PendingApproval, Approved, Printed and Closed. Draft, Rejected, Cancelled and Voided POs do not consume the balance. Allocations convert between PR and PO units using quantity snapshots and prevent over-allocation, including repeated PO lines.

A partially purchased PR stays Partially Ordered. It closes only when every approved line has no remaining quantity. Cancellation/rejection restores availability and reopens the PR as appropriate. The manager-only Cancel PO action requires a reason and blocks cancellation when receipts or invoices exist.

RFQ creation does not consume the balance. New RFQs snapshot the remaining approved quantity and purchasing unit conversion; issued quantities remain stable after later purchasing or Item Master changes. Quotations, comparisons and awards use that RFQ snapshot. Award-to-PO conversion checks the current shared PR balance again. Originating delivery warehouse is enforced for RFQ creation/editing and linked PO creation/revision.

UI and documents

Warehouse and Procurement dashboards reuse the SCM summary header, filters and KPI styling, while keeping their own operational cards and actions. Backend dashboard responses exclude metrics belonging to other roles. The SCM dashboard structure is preserved.

Item Master already uses the same ItemsPage/MasterDataPage/DataTable across SCM, Procurement and Warehouse. No replacement or permission expansion was needed. Browser checks confirmed matching table columns across all three roles.

The PR review modal shows the originating warehouse, requested quantities, approved quantities, variance, reasons, dates and attachments. PR documents now distinguish requested and approved quantities. Existing Procuraflo print/download branding is retained; visible page/table branding footers remain removed.

New RFQ Payment Terms come from the active company's `default_payment_terms`, falling back to existing system setting keys when the company value is unset. The company settings screen exposes this default. Each RFQ saves its own terms; later default changes do not overwrite saved RFQs. New quotation entry starts with its RFQ's terms. No commercial terms were invented: an unconfigured default stays blank until configured.

Database migration and rollout

The idempotent `app/pr_schema.py` migration runs through normal database initialization, including registered active company databases on application startup. Restart the backend to apply the updated schema and code to a running installation.

- Extends PR/PO status constraints without dropping business records, keys, indexes or triggers.
- Adds PR review/approval/closure metadata, original/approved line quantities and review audit fields, company RFQ defaults, and `rfq_items` quantity/UOM snapshots.
- Reconciles historical approvals only when approval history contains an approving actor and time; recalculates partial/closed states from valid allocations.
- Historical manual Warehouse records already processed by Procurement receive an explicit legacy-handoff marker, rather than fabricated submission metadata.
- Historical approved/closed statuses without verified approval are returned to Submitted for a controlled review, except explicit Warehouse no-purchase closures. Approval history is retained and reconciliation is audited.
- Historical RFQs retain the original quantities used by the previous implementation.

Existing databases were not replaced. Verification used disposable test databases and a synthetic browser test company.

Files changed for this workflow update

| Area | Files |
| --- | --- |
| Shared workflow and migrations | `backend-python/app/pr_schema.py`, `pr_workflow.py`, `database.py` |
| Workflow endpoints and replenishment | `backend-python/app/routes/procurement.py`, `backend-python/app/replenishment.py` |
| Scoped supporting access | `backend-python/app/routes/attachments.py`, `reports.py`, `dashboard.py`, `delegations.py` |
| Company defaults | `backend-python/app/routes/settings.py`, `frontend-js/src/pages/masters/SettingsPage.js` |
| PR/RFQ/PO UI | `frontend-js/src/pages/procurement/PRPage.js`, `RFQPage.jsx`, `POPage.js`, `frontend-js/src/components/ProcurementPRReview.jsx` |
| Documents and dashboard styles | `frontend-js/src/components/ProfessionalPurchaseRequisition.js`, `frontend-js/src/pages/Dashboard.js`, `frontend-js/src/index.css` |
| Tests | `backend-python/tests/test_pr_rfq_po_workflow.py`, `test_dashboard_role_audit.py`, `conftest.py` |

The workspace also contains earlier branding and application changes; those were preserved and are not all attributable to this workflow update.

Validation

- Full backend suite: 108 passed.
- After the final RFQ warehouse-edit and replenishment UOM adjustments: all 16 focused workflow/replenishment tests passed.
- Final frontend production build: passed, 422 modules.
- Route validation: passed, 39 lazy imports, 43 routes, 88 navigation targets.
- Branding validation: passed for original logo bytes, three PDF pages and offline spreadsheet logo/data.
- Headless Chrome: SCM, Procurement and Warehouse dashboards rendered without JavaScript exceptions or horizontal overflow at 1440px; shared Item Master headers matched; visible table/page branding footer was absent.
- Migration idempotence, foreign-key integrity, historical reconciliation, privacy, approval, partial purchasing, cancellation, RFQ defaults and quantity snapshots are covered by backend tests.
- `git diff --check`: passed.

Known limits

Browser validation used synthetic data at desktop size; it is not a review of every live company document or every device size. Existing FastAPI startup deprecation and Vite large-chunk notices remain. No external deployment or commercial Payment Terms selection was performed.


RFQ usability follow-up - 7 September 2026

Fixed the missing workflow entry point: DataTable accepted inlineActions but did not render the supplied buttons. RFQ registers now expose their sourcing actions directly. All four registers also connect back to an RFQ workspace, including when no quotations or awards exist yet.

New and draft RFQs support reviewing original/approved PR quantities, selecting individual lines, and setting sourcing quantities within the remaining approved balance. Selected lines and supplier changes are saved by the backend. Issuing checks current PR balances again. Issued RFQs remain protected from draft editing. Quotations and award quantities remain bounded by the saved RFQ scope; duplicate award conversion is guarded inside the transaction.

Created RFQs open their workspace immediately. The workspace shows next-step controls for issuing, quotation entry, comparison, award approval, and PO creation. Child editors no longer open behind the workspace, errors appear in the active dialog, and register counts refresh after decisions. The PO reference links to the purchase-order screen. Existing authorization and branded document output remain intact.

Additional files: backend-python/app/rfq_workflow.py; frontend-js/src/components/RfqItemSelection.jsx. Updated procurement endpoints, RFQPage, DataTable, SearchSelect and workflow tests. Corrected an intermittent authentication test to change actual signature bytes instead of potentially unused base64 padding bits; authentication behavior was unchanged.

Validation: 110 backend tests passed; production build, route integrity and branding validation passed. Headless Chrome completed item selection, draft editing, issuance, supplier quotation, comparison, recommendation, separate-manager approval and linked PO creation on disposable data, with zero JavaScript exceptions. The local backend was restarted with automatic reload to serve the fixes.


RFQ purchase order approval-limit follow-up

Removed the separate SCM generation-limit rejection from RFQ award conversion. RFQ-generated POs remain PendingApproval. The shared employee-authority engine now routes over-limit values to PENDING_EXTERNAL_APPROVAL, assigns a management approval request number, and records approval value, currency, limit, approver and authority reference. Direct and RFQ-generated POs share the company-currency conversion used for the approval threshold. Award approval does not substitute for the PO's own external approval evidence.

SCM can upload signed PO management approval and use Record External Approval with the management reference/person. Approval remains blocked without the required attachment. RFQ conversion feedback explicitly identifies pending external approval. Added tests for below/above-limit generation, foreign-currency threshold comparison, printable PO documents, evidence enforcement, subsequent approval and duplicate conversion prevention.


Item Master, RFQ defaults and A4 output follow-up

Standardized Item Master column widths, wrapping and numeric alignment through the shared table used by SCM, Procurement and Warehouse. Browser checks confirmed identical dimensions for all thirteen columns across the three roles. New RFQs display the company payment-term default with a clear label and preserve existing RFQ snapshots. No default is configured in the active company; set the desired wording in Company Settings.

RFQs now use the shared company document header and footer, including company identity/contact/registration details, supplier, selected quantities and saved commercial terms. The detail endpoint supplies company and delivery warehouse information. Shared header spacing prevents overlapping contact details.

All application print commands now use the common isolated document output utility. PDF export uses an A4-width clone, waits for assets, wraps table content, preserves rows and repeats table headings. Documents use portrait; wide reports/calendars use landscape. Errors are surfaced explicitly and document authorization remains enforced where required. Print page numbering uses page-margin counters. Spreadsheet print styles and XLSX templates specify A4 landscape; CSV remains a data format without paper dimensions.

Validation: 22 focused backend workflow/branding tests passed; production build and branding validation passed. Headless Chrome generated print and downloaded PDFs for PR, PO, GRN, RFQ and a wide report using 80-row fixtures. All generated pages measured A4; printed documents included company identity and the final item without zero page numbers. RFQ was checked visually and regenerated successfully after improving shared header/row spacing. Browser role checks reported no JavaScript exceptions. Physical printer output was not exercised.


Supplier document identity follow-up - 8 September 2026

Root cause: the PO detail/document endpoint selected purchase-order and creator fields but did not resolve supplier identity; the document expected supplier_name/address/contact fields. GRN detail returned only the supplier name, RFQ supplier records omitted address/phone/country, and finance display did not show full supplier contact details.

Added app/supplier_documents.py to resolve tenant-scoped supplier identity consistently for PO details/documents, GRNs, and invoice/three-way-match and finance responses. Reads include inactive/soft-deleted master suppliers so existing documents retain identity. This is current supplier-master enrichment, not a new historical snapshot migration. No fabricated addresses or contact data are stored. RFQ supplier responses now include address, phone and country.

Added shared SupplierDetails.jsx for PO, GRN, RFQ, external management approval and finance handoff output. It displays name, supplier code, address, contact person, phone, email and country when recorded. Existing report queries for quotation comparison, PO registers and three-way-match already join supplier identity. Internal employee/material documents remain supplier-free where no supplier is involved.

Validation: 21 procurement workflow tests passed, including a new real-route regression that checks all supplier fields across PO detail/document, GRN, RFQ, payment pack and three-way-match responses, and checks existing PO reads after supplier deactivation. Production build passed.

Browser verification: PO, GRN, RFQ, management approval and finance templates each rendered the supplier code, name, address, contact, telephone, email and country, generated downloads successfully, and retained those values in A4 print PDFs. The downloaded PO was inspected visually. Zero JavaScript exceptions in the isolated document run.


Company-wide PR access follow-up - 9 September 2026

The latest user requirement supersedes earlier draft-privacy requirements. All authenticated users in the same company can now read all PR sources and statuses, including manual warehouse/procurement drafts and automatic low-stock drafts across warehouses. The shared access predicate covers details, approval history and attachment reads; PR reports and executive counts now include automatic drafts. Tenant boundaries remain unchanged. Personal warehouse-review tasks remain assigned to the responsible warehouse.

All login roles have the PR navigation entry, protected route and New PR action. Creation requires an authenticated active account and valid requesting employee, department, items and permitted destination warehouse. Explicit draft-management checks prevent broader read access from granting edits, submissions, attachment writes or draft closure to unrelated users. Automatic drafts remain under authorized warehouse management. Procurement review, approval authority, self-approval restrictions, submitted quantity locking and RFQ/PO eligibility remain enforced.

Validation: all 116 backend tests passed, including company-wide creation/read coverage for all six supported roles, automatic drafts in PR reports, cross-warehouse reads and unauthorized mutation checks. Updated two stale branding test expectations to the already-approved Supply Chain Control System tagline. Production build and route validation passed (39 imports, 43 routes, 88 navigation targets). Isolated headless Chrome checks confirmed all six roles see the same PR, have the PR menu and can open New PR, with no JavaScript exceptions. No live business records were created during validation.


Print footer follow-up - 9 September 2026

Controlled copy labels now print in the bottom margin before the branding/page footer, rather than above the document. Downloaded PDFs use the same bottom placement. The shared physical-print footer now embeds a directly rendered PNG of the original rounded Procuraflo logo, replacing the nested SVG image that did not reliably appear in print. Print preparation waits for the logo. Shared A4 rules apply to the isolated document content.

Validation: production build passed. A two-page headless Chrome print with background graphics disabled included exactly one logo image on each page, the product tagline and page counters. PDF text coordinates confirmed the Vendor Issue Copy label sits in the bottom margin on both pages (62.67 points above the page bottom), with no top copy marker. Physical printer output was not exercised.

## Partial PO receiving and exception details (2026-09-09)

- PO status now remains Partially Received until all ordered quantities have completed usable receipt. Physical delivery, inspection/put-away reservations, usable acceptance and outstanding quantities are calculated separately.
- Damaged/rejected quantities do not fulfil the order. Direct GRN rejections remain quarantined; failed inspections retain existing restricted-stock controls. Pending inspection/put-away reserves delivery capacity to prevent duplicate receipts.
- PO details include expandable Receiving Issues / Partial Receipt Details with item totals and GRN/date/warehouse exception history. GRN and inspection forms capture damage, shortages (GRN), reasons and notes. Damage is a subset of rejection, and historical short-delivery reports do not cancel outstanding quantities.
- Partial status is supported by PO registers, printing, invoices, warehouse eligibility, reporting, dashboards and replenishment. Printing preserves the partial status. Existing amendment/cancellation restrictions remain enforced.
- An idempotent audited migration reconciles historical receipt status. Applied to the current default and RPC databases after creating SQLite backups; foreign-key checks passed.
- Targeted tests cover direct damage, inspection rejection, TON/KG conversion, short delivery, replacement receipt, historical status reconciliation, partial-PO printing, and continued completion after inventory consumption. All four parameterized scenarios passed. Browser validation passed for the expandable details, 22 table columns and eight exception reasons. Frontend production build and route integrity checks passed.
- Final backend regression run: 121 passed (four existing FastAPI lifecycle deprecation warnings). The expanded partial-receipt scenarios were also rerun separately: 4 passed.

### Receiving report follow-up
- Corrected Open PO Commitments, PO versus GRN and PO Delivery Performance to count usable receipts after put-away, including conversion from base units and legacy direct-stock receipt support.
- PO versus GRN now distinguishes physically delivered quantity, accepted usable quantity and usable receipt value. Open PO reports exclude cancelled and voided orders.
- Extended all four partial-receipt regression scenarios to exercise the three report endpoints and verify received quantity, outstanding quantity and commitment value against PO details: 4 passed.
