# Synthetic fixture tooling

`generate.py` constructs three consistent cases, writes PDFs with a standard-library
PDF writer, and uses Poppler/ImageMagick for a deterministic image-only scan.
`validate.py` checks financial consistency, dates, hashes, page counts, extractable
text, source-region bounds, expected outcomes and intentional missing evidence.
`preview.py` renders every page and produces case contact sheets for visual review.

Runtime documents: `data/synthetic/exemplars/`.
Evaluation-only records: `evaluation/synthetic/`.

See `data/synthetic/README.md` and `docs/SYNTHETIC_DATA_SPEC.md` for scope and limitations.
Generation does not call an LLM or external API and does not modify application data.
