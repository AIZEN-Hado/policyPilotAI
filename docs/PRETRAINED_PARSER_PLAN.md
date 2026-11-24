# Pretrained model and parser improvement plan

Date: 2026-11-17. Status: first source implementation completed; real PDF/OCR and
remote model quality evaluation pending. This is the preferred direction over fine-tuning.
The existing training preparation remains available as historical/optional work.

## Review assignments

| Role | Model | Reasoning effort |
| --- | --- | --- |
| Parser, retrieval and validation audit | GPT-6.1 Sol | High |
| Official model and parser research | GPT-6.1 Sol | Medium |
| Evaluation and regression audit | GPT-6 Luna | High |

The initial three review tasks were read-only. No dependencies or model weights were downloaded,
paid compute started, production configuration changed, or secrets accessed.

## First implementation checkpoint

Two implementation agents (GPT-6.1 Sol High for evidence selection, Sol Medium for
extraction) completed the bounded changes; extraction also cross-reviewed worker
integration. No agent exceeded High effort.

- `pilot/extract.py` now records versioned heuristic quality reasons, checks
  Unicode alphanumeric content and suspicious font/control/replacement characters,
  and retains native text separately when OCR is selected. It does not detect all
  mixed image/text pages or reconstruct tables.
- `pilot/core.py` preserves paragraph/line boundaries when they fit, with bounded
  overlap fallback for oversized runs. Page and exact quotation offsets refer to
  stored extraction text, not original PDF coordinates. Unicode search
  normalization leaves quoted source text unchanged.
- Selection reserves policy/schedule representatives before other documents,
  prioritizes supplied endorsements and reports omitted/partial extracted
  documents. It does not establish endorsement applicability. The 12,000-unit
  limit is explicitly text characters, not tokens or full serialized prompt size.
- Strict response keys/types and literal quotation membership are validated;
  whitespace-altered quotations are rejected. Statement entailment remains
  unverified even when its quote is valid.
- Worker input, saved findings and review UI carry warnings. Empty optional
  documents are identified separately because they have no selectable chunks.
  Required policy/schedule pages must meet the same alphanumeric readability
  criterion as extraction; punctuation-only OCR cannot start inference.

Application checks: 80 pass and 27 API checks skip for missing dependencies;
the release gate remains blocked. The 24 existing lightweight training preparation
regressions and JavaScript syntax check pass. Model transport, storage/database
integration in new worker tests and extraction subprocesses use test doubles.
Poppler/Tesseract are not on this shell's PATH, so actual PDF/OCR quality was not
measured. No parser/model library, GPU, Pod, volume or cloud charge was introduced.
The frozen 500-commit import queue is untouched and does not include these later
source changes; it continues to describe its original preparation snapshot.

## Proposed approach

Keep the existing Render application, sessions, database, document bucket, case
queue and authenticated HTTPS inference interface. Improve the information sent
to the model before considering training. The pipeline is:

PDF extraction with page quality metadata -> source-preserving chunks ->
case-scoped evidence selection -> pretrained model -> schema and quotation
validation -> human-reviewed draft with explicit uncertainty.

The worker, any learned parser, model weights, caches and inference execute in
the cloud. No model execution or weight downloads on the user's computer.
Serverless remains retired. Persistent storage cannot execute the model when
compute is off. Existing financial limits, prior spend and reservations remain
unchanged; this review does not authorize a budget reset or claim current stock.

## Model comparison, not a claimed winner

Evaluate [Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B) first and compare
[Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B) on the same frozen synthetic inputs.
Both official model cards list Apache-2.0 and vLLM serving examples. Start with
thinking disabled for bounded review output; measure quality rather than assuming
this setting or either size is sufficient. Pin the selected revision and serving
image after compatibility review. Model-card runtime minimums do not establish
Blackwell driver/CUDA compatibility or a suitable production image.

[Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) is an optional later challenger
if visual reasoning improves measured failures. Its newer architecture requires
its own compatible stack; do not reuse the old Qwen2.5 training environment.
No model has been loaded or benchmarked by this review, and 24 GB GPU capacity is
a candidate evaluation environment, not a verified context/concurrency fit.

## Bounded first implementation

1. Preserve extraction method, quality reasons and verification state through
   chunks, model evidence and result provenance. Keep verbatim text separate from
   normalized search text. Add versioned metadata without breaking the existing
   page fields or PostgreSQL JSONB storage.
2. Improve selective OCR routing. The current 50-alphanumeric-character trigger
   misses mixed image/text pages and substantial corrupt text layers. Quality
   heuristics must be labeled as heuristics; sparse legitimate text is possible.
   Preserve competing native and OCR provenance rather than concatenating them.
3. Replace fixed character slices with paragraph/clause/row-preserving chunks.
   Reserve evidence space for policy, schedule and applicable endorsements before
   additional documents. Explicitly record omitted evidence. The existing 12,000
   character budget can fit only ten full 1,200-character chunks and can omit
   required document kinds. Add a serving-token-aware context budget before
   claiming a model context limit is enforced.
4. Improve Unicode-aware lexical retrieval and neighboring-block selection before
   adding a vector database or another hosted model. All retrieval stays scoped
   to the current case.
5. Enforce the complete output schema locally, including identifier types. Add
   server-side structured output only for a verified compatible serving API.
   Exact quotation membership does not prove that a finding follows from it.
   Retain human review, uncertainty and the prohibition on final coverage/payout
   authorization; do not replace semantic evaluation with a word blacklist.

Evaluate [Docling](https://github.com/docling-project/docling) remotely as the
structured parser challenger, especially for reading order and tables. The first
code changes can improve the existing Poppler/Tesseract path without adding a
model dependency. Docling's code license is MIT; check each bundled model's
license and cache all parser weights remotely. Do not adopt both parsers by
default without a measured reason.

[PaddleOCR-VL-1.6](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6) is an
optional difficult-document alternative, not a required extra service. Its
[Blackwell compatibility guide](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PaddleOCR-VL-NVIDIA-Blackwell.html)
documents specific runtime requirements and limited tested hardware; compatibility
with the proposed RTX PRO 4000 is unverified.

## Evaluation and release evidence

Existing extraction/core/inference unit tests: **22 passed** during the review.
Extraction and transport tests use mocks; this is not an OCR/model accuracy score.
The current development corpus is three cases, 24 PDFs and 29 pages, with one
image-only PDF. Its 897 fixture consistency checks do not establish application
accuracy. The 144 training, 72 validation and 72 test text examples are separate
from a PDF/OCR benchmark.

Freeze and hash synthetic PDFs, independent expected fields and case-family splits.
Keep held-out labels out of prompts and the processing worker. Add independent
layouts, mixed image/text pages, corrupt text layers, rotated scans, Hindi/English,
table continuations, clause exceptions, conflicting dates, endorsements and
missing-evidence cases. Independently annotate transformed scans before reporting
OCR span or coordinate accuracy.

Compare current extraction/retrieval against the proposed path using the same
model, then compare models on the same selected evidence. Record per-case field
exact match, OCR CER/WER where labels exist, table/amount alignment, required
evidence recall, document/page/quote validity, supported versus unsupported
findings, required abstention, JSON validity, latency, remote RAM/VRAM and cost.
Report denominators and every failure. A valid quote alone cannot certify finding
support. Existing payable ground truth can check future explicit arithmetic code;
the current review output does not calculate or authorize a payable amount.

Require no invalid citations or unsupported final approvals in the frozen smoke
set and no regressions in required evidence/abstention. These are narrow engineering
gates, not a production accuracy claim. Expanded held-out evaluation is required
before claiming improved policy accuracy.

## Remaining remote integration

After reviewing the actual GPU quote, compatible pinned image, storage quote and
remaining experiment allowance, prepare one remote Pod and persistent cache.
Protect the model server with authenticated HTTPS and route restrictions; do not
expose the raw vLLM server assuming its API key covers every route. See the
[vLLM security guidance](https://docs.vllm.ai/en/stable/usage/security/).
Verify model revision/hashes, a real synthetic response, worker queue processing,
citations and cleanup before enabling the live application's processing settings.
Keep inference disabled until verified; no live model is claimed by this plan.
