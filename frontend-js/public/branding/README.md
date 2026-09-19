# Procuraflo brand assets

The original supplied logo is the authoritative product identity. Its white and cyan foreground is unchanged. Shared navy brand surfaces and CSS lighten blending match its background to the application while retaining readable white lettering.

Product registration: src/config/brand.js and /api/settings/branding product_brand.
Offline export data: src/config/brandAsset.js, embedded from procuraflo-logo.png.
Backend workbook asset: backend-python/app/assets/procuraflo-logo.png.

Background-only edits were evaluated using the built-in image tool with the prompt: "Change only the navy background; preserve the exact white and cyan logo and lettering." These were rejected because they did not preserve the original reliably. The shipped logo is the supplied original.

Internal database paths, session keys, and deployment identifiers retain compatibility with existing installations. Previously downloaded documents are not rewritten.
