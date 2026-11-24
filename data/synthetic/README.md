# PolicyPilot synthetic exemplars v1.0

**Fictional engineering fixtures. Not valid for claim submission.**

Three complete case bundles (24 PDFs / 29 pages) are in `exemplars/`.
Only those PDFs should be passed to a document-processing pipeline. Do not ingest the
`evaluation/synthetic/` directory: it contains canonical facts and expected answers.
These files have not been added to the application's `data/policies/` directory.

| Case | Documents | Purpose |
|---|---:|---|
| SYN-C001 | 8 | Individual policy, hospitalization, reconciled invoice and receipts |
| SYN-C002 | 9 | Family policy with a dated room-benefit endorsement |
| SYN-C003 | 7 | Incomplete scanned bill, conflicting dates and unavailable utilization |

Each includes a schedule, two-page fictional wording, claim form, discharge summary,
itemized bill, receipt ledger and investigation narrative. Cases 1 and 2 also include
utilization statements; case 2 includes an endorsement. Case 3 intentionally has only
sheet 1 of a two-sheet bill. Its absent sheet and utilization statement are **not**
silently reconstructed for the application.

## Generation and checks

Requires Python 3 standard library, Poppler tools and ImageMagick on PATH. The scripts
also discover installed Nix-store executables. No Python packages or model downloads
are needed. Run from the repository root:

```sh
python scripts/synthetic/generate.py
python scripts/synthetic/validate.py
python scripts/synthetic/preview.py
```

Generation overwrites only these named exemplar artifacts. Geometry is deterministic;
exact raster bytes can vary with renderer versions. Document hashes are recorded in
per-case evaluation manifests. No random patient data is downloaded or used.

## Dataset card

- **Use:** pipeline development, evidence-linking demonstrations, rule/abstention regression checks.
- **Population:** invented cases, not a statistically representative Indian claims sample.
- **Language:** English only in this initial checkpoint. Hindi remains future work.
- **Layouts:** three fictional hospital header/table arrangements and one fictional insurer style;
  not yet the four independent layout families required for the larger corpus.
- **Policy families:** individual and family floater, explicitly original fictional rules.
- **PDFs:** 23 native-text documents, 1 image-only bill scan. Scan uses 120 DPI, 0.65-degree
  rotation, mild Gaussian blur and JPEG quality 62; no hidden text layer.
- **Ground truth:** separate manifests with canonical facts, visible text regions,
  intended contradictions/omissions, expected review state and calculation traces.
- **Coordinates:** native-text regions are approximate authored rectangles. The scanned
  bill stores pre-transform canonical rectangles explicitly labeled as such; they must
  not be used to score precise scan localization. Exact post-transform annotation is
  required before a localization benchmark.
- **Split:** all three are development exemplars. No held-out accuracy claim is possible.
- **Privacy:** fictional names/organizations; SYN identifiers; reserved `example.invalid`
  contact addresses; no real signatures, bank accounts, registration numbers or branding.
- **Clinical review:** not performed. Clinical narratives are simplified and contain no
  dosing recommendations. No diagnostic images or numerical lab results are provided.
- **OCR smoke test:** the existing Poppler extraction path read all 28 native pages.
  On the image-only SYN-C003 bill, the assessment extractor used Poppler 22.12.0 and
  Tesseract 5.3.0 with `eng+hin`. The OCR text retained the member and policy IDs,
  both service dates, the invoice total, and the reference to sheet 2. The page
  was flagged for source verification. This fixture checks an English scan and
  is insufficient for estimating OCR accuracy on other documents or in Hindi.
- **Price realism:** invoice structures are plausible fixtures; prices and policy benefits
  are invented and must not be interpreted as market rates or actual coverage terms.
- **Current milestone:** the first three exemplars, not the planned 48-bundle corpus.

Public references informed document structure only; no insurer wording or form design
was reproduced. See `evaluation/synthetic/SOURCES.md` for provenance and limitations.
