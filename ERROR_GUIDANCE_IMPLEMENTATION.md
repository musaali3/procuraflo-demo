# System-wide error guidance

The shared API client, native browser validation, and marked local error banners now feed one error guide. The guide highlights identified editable fields and line-item rows, supplies Go to field/row buttons, and scrolls/focuses the affected input. Field highlights include aria-invalid and links to the error description; the summary is announced as an alert. Editing a field clears its own error while preserving other field errors.

Structured field paths, including indexed line items, take priority. Existing plain-language validation messages can identify a uniquely matching field label or field identifier. Ambiguous messages do not mark arbitrary fields: the affected action is highlighted when available, with the original error and guidance. Permission, server and network failures do not falsely mark inputs as invalid. Closed dialogs and stale routes are ignored. Required-field browser validation works without an API call.

Import failures identify the relevant source-file upload control and retain the row number from the server, explaining that the source file must be corrected and selected again. Error responses returned as JSON blobs during downloads are decoded for readable guidance. Error indicators and the error guide are excluded from document output.

## Integration

- `src/utils/errorGuidance.js`: shared field/row resolution, focus/scroll links, summary, lifecycle and accessibility.
- `src/main.js`: installs the shared listeners once on application startup.
- `src/api/client.js`: captures request context, normalizes structured validation and download errors, and publishes errors to the guide.
- `src/index.css`: field, row and action highlights and compact guidance panel.
- Shared master-data forms, search selects, document attachments and page error boundary carry field/error metadata. Existing procurement, warehouse, inventory, administration, employee and settings forms carry field identifiers and local-error markers.
- Existing blocking error alerts in PO, material issue, stock adjustment and document-output flows use the shared guide. Success notifications remain success notifications.

## Validation

Production build and route-integrity validation passed. Browser regression checks cover unique-field matching, exact indexed line items, multiple errors, field-specific clearing, native required fields, keyboard focus, portal error updates, ambiguous fields, closed dialogs, API validation, permissions, network errors, correct import control selection and JSON-blob download errors. The automated suite is `npm run validate:errors`; it expects a dedicated Chrome debugging instance at port 9223 and test frontend at port 5175 (overridable with CHROME_DEBUG_URL and ERROR_GUIDANCE_TEST_URL). It uses isolated DOM/API fixtures without creating business records.

No approval, inventory, financial or permission rules were changed. Where the server supplies no identifiable editable field, the guide preserves the message and identifies the relevant action rather than claiming to know which value is wrong.

Final verification: 24 browser assertions passed (14 DOM/lifecycle checks and 10 API/import/download checks), including removal of a line item with an active error. Route integrity passed for 39 lazy imports, 43 routes and 88 navigation targets. Shared field metadata is present across 36 source files; existing local error banners are marked across the application.
