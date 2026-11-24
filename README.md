# PolicyPilot

PolicyPilot is a web application for reviewing synthetic health insurance claims. A reviewer opens a case, attaches the policy schedule and claim evidence, and checks dates, identifiers and benefit limits against the original PDF pages. The reviewer records an acknowledgement after checking the evidence.

## Try a case

Open the [hosted workspace](https://policypilot-demo.onrender.com) and sign in with the shared reviewer account. Each person with this account sees the same cases. Use the fictional PDFs in [the sample cases](data/synthetic/exemplars).

For a short interview walkthrough on the PDF review release:

1. Create a case for **SYN-C003**. Enter a short description of the admission-date discrepancy.
2. Attach `04_claim_form.pdf` as **Claim form** and `05_discharge.pdf` as **Discharge summary**. Attach `01_schedule.pdf` as **Policy schedule** and `02_wording.pdf` as **Policy wording** for policy details. The hospital bill includes a page that needs a visual check.
3. Select **Review PDF fields**. Expand **Admission date** and follow both page citations. The two documents disagree, so the field has no resolved value.
4. Search a phrase from the wording or schedule to find the relevant page. Use **Download original** to inspect the PDF, then record your review.

The six fields are policy ID, member ID, admission date, discharge date, room limit and sum insured. The current web review reads labeled values from PDFs and uses Tesseract for flagged pages when OCR is available. The reviewer checks flagged pages against the original and decides how to resolve discrepancies.

## Run or deploy

The web application lives in [pilot/](pilot). Its FastAPI service uses PostgreSQL for cases and sessions and private storage for PDFs. The PDF review uses Poppler and Tesseract on the application server. It runs with the model connection disabled.

- [Deploy the API image to the existing Render service](deploy/RENDER_IMAGE_DEMO.md)
- [Synthetic documents and their intended use](docs/SYNTHETIC_DATA_SPEC.md)
- [Research and evaluation of the task-specific networks](docs/SPECIALIST_NETWORK_PLAN.md)
- [Archived local Ollama prototype](docs/LEGACY_OLLAMA_PROTOTYPE.md)

To inspect the interface offline, run `python deploy/preview_ui.py` and open `artifacts/policypilot-ui-preview.html`. The preview uses illustrative case records. For a real deployment, use the authenticated smoke command with `--case SYN-C003 --review-fields` to exercise upload, review, citations, download and deletion against that release.
# policyPilotAI
