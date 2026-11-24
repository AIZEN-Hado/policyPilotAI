# PolicyPilot claim review

The web application gives a reviewer a shared queue of synthetic insurance claims. Reviewers attach PDFs, compare extracted dates and policy values, open cited pages, download the original files and record that they have checked the evidence.

## How a review works

1. Sign in and open a case. Choose the document type when attaching each PDF.
2. Select **Review PDF fields**. The API reads embedded text using Poppler, uses Tesseract on pages flagged as unreadable when OCR is available, and checks six labeled fields. Disagreeing values retain individual source citations. OCR text, unreadable pages, and ambiguous values call for an original-document check.
3. Follow a citation or search for a phrase in the case's readable pages. Acknowledgement records the specific version reviewed. Attaching a document requires a fresh review.

The standard demo runs with `INFERENCE_BACKEND=disabled` and `PROCESSING_ENABLED=0`. Field review works in the web service. Private PostgreSQL stores case data and browser sessions. The configured document store holds the original PDFs, and the cleanup queue tracks physical deletion. A shared reviewer login can access all cases.

The optional assessment worker supports OCR and an explicitly configured model service. Existing assessment records and conversations can be inspected. The separately trained specialist networks have [synthetic evaluation results](../docs/SPECIALIST_NETWORK_PLAN.md). The web review uses explicit field rules.

## Run the checks

From the repository root in the app's Python environment:

```sh
python -m pilot.check_tests
python deploy/preview_ui.py
python -m unittest discover -s deploy/tests -v
node deploy/tests/check_ui.mjs
node deploy/tests/check_evidence_search.mjs
```

The Docker build runs the API gate and rejects skipped tests. The [deployment guide](../deploy/RENDER_IMAGE_DEMO.md) covers building, publishing and verifying the existing Render service. The [project README](../README.md) includes an interview walkthrough.
