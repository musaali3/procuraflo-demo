# Internal shift breaks

- Shift start/end boundaries no longer move when break minutes are edited. Net working time excludes breaks.
- Breaks begin at the midpoint of the shift (or earlier if needed to fit entirely inside it). 08:00-16:00 with 30 minutes closes 12:00-12:30 and provides 450 working minutes.
- Calendar generation stores working intervals and assigned-shift break intervals in employee_work_calendar.work_periods_json. Each employee receives only the break belonging to their assigned shift, including overnight boundaries. Other overlapping shifts do not add breaks or reduce that employee's working time. Location-wide holiday and weekly closures remain separate.
- Staffing coverage checks evaluate open intervals only, accounting for manual start/end overrides. A manual entry entirely within a closed break is rejected.
- Calendar grids, lists, printed output and CSV exports expose break closures; lists show net working hours.
- Standard operating schedules no longer gain extra minutes at startup. New automatic warehouse designs use eight scheduled hours including breaks. Saved warehouse multi-shift times remain unchanged; no blanket re-design is applied.
- A one-time migration corrects identifiable old procurement eight-hour-plus-break shifts and records old/new ends in the internal_shift_breaks_v1 settings entry. Historical calendar rows and locked/manual entries are not modified by this correction. Existing history is retained.

## Files
- backend-python/app/database.py: additive calendar column and startup/migration correction.
- backend-python/app/routes/workforce.py: shift validation, break-aware calendar generation, coverage and manual overrides.
- backend-python/app/routes/masters.py: automatic shift durations.
- frontend-js/src/pages/WorkforceSetupPage.js: fixed boundaries and internal break display.
- frontend-js/src/pages/WorkCalendarPage.js: closed periods, working hours and export fields.

## Validation and limits
Python syntax parsing and the production frontend build were used; no automated tests were created, modified or run. Break placement is automatic, not a configurable break-start field. This change governs workforce scheduling; it does not prohibit unrelated manual procurement or stock transactions during breaks.

## Assigned-shift display correction
Calendar generation, coverage checks, manual overrides and calendar reads now calculate breaks from the assigned shift only. A 07:00-15:00 shift with a 30-minute break shows Break 11:00-11:30; the next shift's 14:00 break is excluded. Calendar cards show Off Day / Closed once. Python syntax and frontend build checked; no automated tests run.
