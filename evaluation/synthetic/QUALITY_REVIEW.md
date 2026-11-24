# Exemplar checkpoint — 2026-11-07

Result: three development bundles generated; 24 PDFs, 29 pages. This is not the full
48-bundle corpus or a domain-approved clinical dataset.

## Performed

- 897 automated fixture checks passed; see `validation_report.json`.
- Checked source-region bounds, extracted text, document hashes, page counts,
  chronology, financial reconciliation, independent reference calculations and
  deliberate absent/conflicting evidence.
- Rendered every page and inspected all three contact sheets. Inspected individual
  bill/discharge pages, including the image-only bill, at larger resolution.
- Corrected a header rule overlapping the first field and zero-width blank-line
  annotation regions before final generation.
- Removed narrative that directly disclosed the intentional cross-document date
  discrepancy: the application must discover it from the dates themselves.
- Confirmed scanned bill has an embedded JPEG and no extractable hidden text.
- Validated ZIP integrity: 24 PDFs, no ground-truth manifests in the archive.

## Reference expectations

SYN-C001: draft eligible amount INR 76,800.00; reviewer authorization still required.
SYN-C002: draft eligible amount INR 1,02,150.00 using the applicable room endorsement;
reviewer authorization still required.
SYN-C003: no definitive amount; missing continuation, contradictory admission dates,
and unavailable utilization require clarification.

## Remaining work before broader claims

Actual OCR execution/measurement; exact post-transform scan coordinate annotation;
clinical/domain review; Hindi generation with language review; independent fourth
layout family; realistic hospital-format research; additional degradation types;
held-out layouts/cases; broader scenario coverage. Public references establish document
categories, not clinical or pricing realism. These simplified English examples are
engineering fixtures, not production acceptance evidence.
