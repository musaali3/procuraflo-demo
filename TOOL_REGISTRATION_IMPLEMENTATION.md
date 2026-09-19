# GRN Tool Registration Update

## Files changed

| File | Change |
| --- | --- |
| `backend-python/app/database.py` | Additive schema migration, legacy status initialization, receipt and unit uniqueness, registration/issue/custody database guards. |
| `backend-python/app/routes/warehouse.py` | GRN retry protection and per-unit pending tools; inspection, tool transfer, receipt, and shortage integration; prevent aggregate material issue from bypassing tool registration. |
| `backend-python/app/routes/advanced.py` | Registration completion, manual issue/return, scoped history, calibration, repair release, transfer dispatch, loss, and retirement actions. |
| `backend-python/app/routes/masters.py` | Link each received tool to its confirmed put-away location. |
| `backend-python/app/stock.py` | Preserve GRN stock provenance on tool movements and block aggregate movements that bypass individual tool control. |
| `backend-python/app/routes/clearance.py` | Preserve damaged-return liability using custody history after the current employee assignment is cleared. |
| `frontend-js/src/pages/advanced/ToolsPage.jsx` | Pending registration, separate Tool Code/manufacturer serial, manual code/employee selection, return condition, history, lifecycle actions, and refresh. |
| `frontend-js/src/pages/warehouse/GRNPage.js` | Persist a receipt request key across retries, including page reloads within the same browser tab. |

## Database changes

- Extend existing `tools` with status, GRN line/unit identity, registration actor/time, calibration requirement, location, custody cost, and transfer linkage.
- Extend `grns` with unique request keys and the corresponding request payload. Extend `inventory_quarantine` with a tool reference.
- Uniqueness on `(source_grn_item_id, source_unit_number)` prevents duplicate physical units. Database triggers protect GRN identity, manufacturer serial uniqueness, registration, assignment eligibility, and custody consistency.
- Reuse existing startup migration for the default and active tenant databases. The live default database was observed with the new columns and triggers after application reload.
- No database reset or deletion of tool/history records. Existing tools receive compatible statuses; their existing codes and history remain intact.

## Backend/frontend behavior

- Item Master's existing `Returnable` classification identifies controlled tools. Consumables do not generate tools. Accepted purchase quantities are converted to whole base units; each unit gets a pending record and generated Tool Code in the GRN transaction.
- Partial receipts generate only their accepted units. Repeating the same receipt request returns its original GRN; changed content under the same key is rejected.
- Completing registration records manufacturer serial, make/model, and calibration details, then sets the tool to Available. Inspection and put-away must also be complete before issue.
- Issue and return remain explicit manual actions. The backend checks warehouse scope, permissions, active employee, registration, condition, status, custody, and required calibration under a write transaction. Stock issue/return retains GRN provenance.
- Damaged returns enter existing quarantine/repair records. Authorized repair completion restores availability. Assigned tools remain outstanding employee property; damaged returns retain clearance liability evidence.
- Tool transfers create existing warehouse transfer documents. Destination receipt, inspection when required, put-away, and shortage resolution remain separate existing controls. In-transit tools cannot be issued.
- Existing audit and custody tables preserve GRN, registration, issue, return, repair, transfer, loss, and retirement events. Existing shared refresh events and explicit reloads update Tool Management after actions.

## Verification and remaining issues

- Python source syntax checks and the frontend production build passed. The build reports large-bundle warnings.
- No automated tests were created, modified, or run. End-to-end business workflows have not been exercised with new operational records.
- Historical GRNs are not automatically matched to legacy manually registered tools: the existing data lacks reliable per-unit links, and guessing could duplicate assets. New GRNs use the new flow. Legacy stock reconciliation is required before transferring an unlinked legacy tool through the new tool transfer action.
- GRN API callers outside the updated UI must provide a stable `request_key` and reuse it for retries.
- GRN units that fail inspection remain blocked and require receipt disposition; registration cannot override a failed inspection.
