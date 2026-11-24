# Synthetic fine-tuning preparation

Historical generative experiment preparation. The current no-SLM/LLM direction
is documented in [specialists/README.md](../specialists/README.md); use that path
for new work. Existing archives and financial records are retained unchanged.

This toolkit prepares a **candidate experiment**, not a trained or deployable model.
It never creates a Pod, volume, endpoint or cloud credential. The live application
stays disconnected. Runpod MCP is optional; the eventual Pod can be managed through
the console. No real claims, original development PDFs, database or R2 data are
read by these tools. The user clarified that their computer must be browser-only
for model work. All model downloads, training, serving, caches and artifact reloads
belong on remote compute. Cloud RAM has no arbitrary 2 GB cap; the selected Pod's
physical capacity and existing financial limits still apply.

## Small preparation tools (no model downloads or GPU)

These standard-library tools were originally prepared locally; no model weights
were downloaded. For the browser-only workflow, run future preparation/evaluation
from a cloud project workspace and keep held-out labels in a separate private
cloud evaluation workspace. Existing local scripts/fixtures are not automatically
deleted before verified remote copies exist. From the project root:

```sh
python -m unittest discover -s training/tests -v
python -m training.prepare
python -m training.artifacts --archive artifacts/policypilot-training-v3.tar.gz
```

Preparation creates 288 original fictional text-review records: 144 training,
72 validation and 72 final test. Eight training policy families, four validation
families and four test families are disjoint. Tasks cover quoted benefit terms,
missing bill pages, conflicting dates, unavailable utilization, identity matching,
dated endorsements, document prompt injection, insufficient evidence and uncertain
OCR transcription. These are controlled fictional rules, not insurer wording.

Training assistants use the same system prompt, JSON schema and quote validator
as `pilot.worker`. Loss applies only to assistant tokens; examples exceeding the
token context are rejected, never silently clipped. Validation/test rows contain
prompts only. Reference outputs/checks live separately in `evaluation/finetune-v1`.
Those labels, the final test prompts, the generator and the scorer are **excluded
from the GPU bundle**. The source code naturally knows the scenario templates;
the split tests new fictional product families, not wholly new task/layout types.

Preparation verifies each reference against the checker. That is a checker
self-test using authored answers, **not model accuracy**. All cases are English
text fixtures, not PDFs or OCR outputs. The old three PDF bundles remain untouched.

The archive contains only runtime source, the pinned experiment config, minimal
app prompt/validator source, training examples and validation prompts. Its SHA-256,
member hashes and preparation receipt are saved alongside it. Repeating preparation
verifies an unchanged bundle; if source/data changed, preserve the old bundle and
choose a new `--output` name. Current v3 retains the Blackwell CUDA-build gate and
applies the clarified cloud-only RAM policy. Earlier versions are preserved as
historical preparation checkpoints; do not use their superseded 2 GB cloud gate.

## Before renting a GPU

1. Check current provider inventory/billing and retained reservations. The existing
   USD 2.99 experiment ceiling is unchanged. The separate user-approved model-storage
   allowance is USD 3/month; a proposed 30 GB Standard volume lists at USD 2.10/month
   before tax. Do not treat an old account report as current available funds.
2. Read the actual on-demand GPU quote and find a 24 GB class GPU compatible with
   a network volume in the same data center. Choose Standard storage and verify
   its complete monthly quote. Create no duplicate service/database/document bucket.
3. Use an existing trusted PyTorch **development** environment with one exposed
   GPU, C compiler, C/Python development headers and Python 3.12. The candidate stack
   is pinned in `requirements.txt`, separate from the API requirements. Imports and
   GPU kernels for this new toolkit have **not** been verified. Do dependency work
   before any long model run, and include installation/startup time in the budget.
4. Mount the network volume at `/workspace`; transfer and verify the small runtime
   archive there. Extraction is an owner action, into a new empty project directory.
   Model cache, adapter and receipts must live on the volume. Original base weights
   are about 15.23 GB; allow space for cache metadata, adapters, exports and temporary
   files. The script requires at least 18 GB free before initial staging.
5. Set a provider/session teardown deadline outside the model process. Arrange
   provider-side termination even if your browser, SSH or model process disconnects.
   **The scripts do not implement provider shutdown or a provider dollar cap.**

Execution also requires Runpod's automatically provided `RUNPOD_POD_ID` metadata,
in addition to the volume mount and CUDA checks. A local `/workspace` directory
alone does not allow the launcher to start a model. This metadata is not an API key.

Do not put the broad Runpod setup key, R2 credentials or the Render database URL
in the training environment. Public model staging needs no Hugging Face token.
The bounded launcher forwards only basic runtime/CUDA settings to its child,
disables implicit HF tokens and telemetry, and never touches application secrets.

### RTX PRO 4000 Blackwell candidate

The user selected RTX PRO 4000, with an hourly-rate ceiling strictly below USD 1.
The exact provider quote, data center, image and available stock remain unverified.
This rate ceiling does not increase the total experiment allowance. NVIDIA lists
24 GB VRAM for RTX PRO 4000 Blackwell. For that device, use the CUDA 12.8 build of
the pinned PyTorch candidate. A generic `torch==2.7.1` installation alone does not
establish which CUDA build is installed. On the reviewed Pod, installation order is:

```sh
python -m pip install --no-cache-dir -r training/requirements-cu128.txt
python -m pip install --no-cache-dir -r training/requirements.txt
```

Do not run these heavyweight installations on the local machine. Prefer a matching
development image so setup does not consume the paid session. Preflight checks
the detected GPU capability, PyTorch CUDA build and compiled architecture list
before allocating probe tensors, then still requires the real native NF4 GPU test.
Metadata checks passing is not GPU/kernel/training verification. The current
runtime archive includes the separate CUDA-wheel requirements file.

Sources: [NVIDIA RTX PRO 4000 specifications](https://www.nvidia.com/en-us/products/workstations/professional-desktop-gpus/rtx-pro-4000/),
[PyTorch Blackwell support](https://pytorch.org/blog/pytorch-2-7/).

## Bounded Pod commands (not executed locally)

In the extracted project directory on the existing Pod, set these nonsecret values
from the **fresh quote** and your reconciled remaining compute allowance:

```sh
GPU_RATE_USD='REPLACE_WITH_CURRENT_HOURLY_RATE'
COMPUTE_AVAILABLE_USD='REPLACE_WITH_REMAINING_AMOUNT_AFTER_SPEND_HOLDS_AND_OVERHEAD'
```

The launcher computes a shorter model-process deadline if required by those
values. It accepts at most 900 seconds per invocation; default is 300. The dollar
estimate covers model-process wall time only. Pod startup, setup, idle time,
storage, tax and time after the process exits can still bill. Invalid/nonfinite
values fail before any GPU import or model download.

Preview only (no GPU imports/downloads):

```sh
sh training/pod.sh --mode preflight --workspace /workspace/policypilot-models \
  --gpu-hourly-usd "$GPU_RATE_USD" --compute-budget-usd "$COMPUTE_AVAILABLE_USD"
```

Add `--execute` only when the provider-side session is already bounded:

```sh
sh training/pod.sh --mode preflight --execute --workspace /workspace/policypilot-models \
  --max-seconds 60 --gpu-hourly-usd "$GPU_RATE_USD" --compute-budget-usd "$COMPUTE_AVAILABLE_USD"
```

Preflight checks pinned package versions, CUDA, GPU capacity, a C/Python-header
compilation probe, bitsandbytes NF4 forward/backward and a tiny random Qwen2 CUDA
backward pass. It downloads no real model. Any failure ends this attempt. Diagnose
the saved log before another paid invocation; do not repeat attempts blindly.

Next, run the unchanged base on the first nine validation cases (one per scenario):

```sh
sh training/pod.sh --mode baseline --execute --workspace /workspace/policypilot-models \
  --max-seconds 300 --gpu-hourly-usd "$GPU_RATE_USD" --compute-budget-usd "$COMPUTE_AVAILABLE_USD"
```

This stages the pinned Qwen2.5-7B-Instruct revision using safetensors and hashes the
cached files. Cold staging/hashing may exhaust the deadline; success is not promised.
Copy the printed `run.json` and `predictions.jsonl` to the separate cloud evaluation
workspace for scoring. No laptop download is needed. Check
available compute again before each next invocation; never reuse an exhausted
allowance across successive commands. The launcher does not alter/refund the old
financial ledger.

Only after the baseline process works, run the small QLoRA candidate:

```sh
sh training/pod.sh --mode train --execute --workspace /workspace/policypilot-models \
  --baseline-report /workspace/policypilot-models/runs/BASELINE_RUN/run.json \
  --max-seconds 300 --gpu-hourly-usd "$GPU_RATE_USD" --compute-budget-usd "$COMPUTE_AVAILABLE_USD"
```

The initial candidate does 12 optimizer steps, batch size 1, accumulation 2,
NF4/double quantization, rank 8 and gradient checkpointing. It sees only 24 training
examples. This is a short mechanics experiment, not comprehensive training. No
automatic hyperparameter search, retry or model upload occurs. Long examples,
nonfinite loss/gradients or budget/time/RAM failures block acceptance.

The remote model process is sampled for peak resident RAM and writes its own Linux
peak-RSS/VRAM receipt on normal/error exit. If forced termination prevents that
write, cumulative child peak-RSS accounting is a conservative fallback that may
overestimate a later phase. The user explicitly removed the old 2 GB cloud target:
`model_process_ram_limit_bytes` is now null, so memory is recorded without that
artificial stop threshold. The Pod's actual capacity still limits the process; an
OOM remains a failed run. Optional positive-byte caps remain supported for future
remote capacity experiments. No workload is moved onto the laptop, and the local
execution/mount/CUDA guards remain in force. VRAM capacity and host RSS differ;
no real model RAM fit is claimed from unit tests.

After training, a separate fresh GPU process reopens the pinned base and saved
adapter and performs short synthetic generation. Only successful independent reload
plus byte/hash checks produces `verified-adapter.tar.gz`. That archive is an **adapter
requiring the exact base**, not merged weights, a GGUF, a running server or a quality
pass. Reload generation checks mechanics, not task correctness. Keep failed/interrupted
files and diagnose; do not mistake a partial adapter directory for a verified export.

## Evaluation and artifact backup

Freeze an adapter before prediction. Use the same nine validation prompts initially;
use `--limit 0` only for a separately budgeted full split:

```sh
sh training/pod.sh --mode predict --execute --workspace /workspace/policypilot-models \
  --adapter /workspace/policypilot-models/runs/TRAIN_RUN/adapter \
  --limit 9 --max-seconds 300 \
  --gpu-hourly-usd "$GPU_RATE_USD" --compute-budget-usd "$COMPUTE_AVAILABLE_USD"
```

Score copied predictions in the separate cloud evaluation workspace containing
the labels (the same commands work there; model weights are not needed):

```sh
python -m training.score --split validation --first 9 \
  --predictions /path/to/baseline-predictions.jsonl --output artifacts/baseline-validation.json
python -m training.score --split validation --first 9 \
  --predictions /path/to/tuned-predictions.jsonl --output artifacts/tuned-validation.json \
  --baseline artifacts/baseline-validation.json
```

The scorer refuses missing/extra/duplicate cases. It checks JSON format, literal
quote provenance, required evidence, missing-information questions, abstention and
limited unsafe-decision patterns. These do not establish full semantic correctness.
Subsets cannot pass full-split coverage. Baseline comparisons require identical case
IDs, prompt hashes and label hashes. Human review and full-split evaluation remain
necessary; do not tune on final test results. Keep final test labels in the separate
private cloud evaluation workspace and send
test prompts only once the adapter/config is frozen. `--prompts` supports that later
prompt-only evaluation file; scoring uses `--split test` in that evaluation workspace.

Before terminating dedicated training compute, copy the adapter archive **and** its
`.manifest.json`, run/reload/memory receipts and predictions directly to a separate
private cloud repository/storage service. Create an independent verification copy
on remote compute and verify the copied archive there with:

```sh
python -m training.artifacts --archive /path/to/verified-adapter.tar.gz
```

This is a cloud-to-cloud workflow: no model/adapter download to the local computer
is required. Automated private-repository backup has not yet been implemented or
verified; never claim it exists from archive unit tests alone.

Retain the persistent network volume and an independent verified cloud backup; then
terminate only the dedicated Pod and disposable temporary disks in the console.
Read back Pod absence/compute shutdown. The persistent model volume continues
billing within the approved monthly allowance. Never delete the document bucket,
Render database, existing live app, historical reservations or artifact backups.

Serving the adapter, export to another quantization format, an authenticated model
API, the PostgreSQL/R2 processing worker, live RAM measurements and end-to-end app
tests are later milestones. None are silently enabled by this toolkit.

Sources: [pinned base](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/tree/a09a35458c702b33eeacc393d103063234e8bc28),
[PEFT quantization](https://huggingface.co/docs/peft/v0.15.0/developer_guides/quantization),
[chat templates](https://huggingface.co/docs/transformers/v4.51.3/en/chat_templating),
[Runpod storage](https://docs.runpod.io/storage/network-volumes).
