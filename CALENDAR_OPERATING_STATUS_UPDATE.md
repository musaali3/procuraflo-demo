# Calendar operating status

## Behaviour
- Weekly operating days are authoritative for each warehouse, including 24-hour warehouses. Procurement uses its own configured weekdays.
- Closed days show Off Day / Closed with no shift hours. Applicable holidays show their name and type; Emergency Closure shows Closed with the entered notes/reason.
- New manual holidays default to All locations, filtered by country and optional region. The holiday form also supports Warehouse, a specific warehouse, or Procurement scope. Existing explicit applicability values are retained.
- Manual holiday creation and edits regenerate affected calendar dates, including the old date when moved or deactivated.
- Procurement holiday operation requires an explicit checkbox and reason. Warehouses retain the existing approved holiday-work exception route. A normal manual calendar override cannot bypass a closure.
- Working intervals are clipped at midnight when the next day is closed or a holiday. Calendar coverage and net working time exclude those intervals.
- Calendar views, print output, and CSV expose operating status and holiday information rather than stale shift hours on non-working days.
- Applying a closure removes stale manual shift times, records the prior entry in audit, and retains lock status. No employee, holiday, or history records are deleted.

## Files and database
- backend-python/app/routes/workforce.py: holiday applicability, holiday work validation, regeneration, operating-day enforcement, overnight closures, and calendar display fields.
- backend-python/app/routes/masters.py: selected weekdays govern 24-hour operation.
- backend-python/app/database.py: corrected default operating-day initialization; additive holiday columns warehouse_id, procurement_work_required, procurement_work_reason.
- frontend-js/src/pages/WorkforceSetupPage.js: holiday scope and procurement holiday-work controls.
- frontend-js/src/pages/WorkCalendarPage.js: closed/holiday labels and hours display/export.
- frontend-js/src/pages/masters/WarehousesPage.jsx: weekday edits discard stale per-day schedule values.

## Validation
Python syntax parsing and frontend production build. No automated tests created, modified, or run. Read-only inspection found Factory Warehouse currently configured for Monday-Thursday and Sunday (Friday/Saturday closed); those configured weekdays were not changed. No sample holidays or operational calendar records were created for verification.

Procurement currently has one company-level office calendar; this change uses that existing model. Holiday/closure enforcement applies to workforce scheduling, not a prohibition on entering manual procurement/stock transactions.

## Multi-day holidays
- Added nullable holidays.holiday_end_date. Start and end are inclusive; a blank end retains existing single-day behaviour. If an observed date is provided, it is the effective start, and the end must not precede it.
- Holiday entry and editing now accept date ranges. The backend rejects reversed or invalid dates.
- Holiday matching, overnight closures, manual-work restrictions, holiday-work exceptions, reports and the upcoming-holiday lookup now use the full range.
- Editing/deactivating a holiday refreshes both its old and new ranges, in bounded batches, including the preceding date for overnight shifts. Lock status is retained while affected holiday calendar content is refreshed.
- Existing records and provider-synchronized single-day holidays remain compatible. No data reset and no automated tests.
