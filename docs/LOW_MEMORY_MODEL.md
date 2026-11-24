# Model process below 2 GB RAM

The user confirmed that the limit applies to the model process, excluding OCR,
database, API and OS. Interpret it conservatively as 2,000,000,000 resident bytes.
Do not claim this limit is achieved until actual local measurements pass.

## Candidate design

Start with Qwen2.5-0.5B-Instruct and its official Q4_K_M GGUF baseline. Use a
llama.cpp CPU runtime, 2048-token context, one request at a time and 256 output
tokens. Small weights plus capped context make this a plausible candidate, not
a guarantee. Compare a 1.5B candidate only if memory and accuracy justify it.

The narrow model task is extracting a few facts or generating one short finding
from selected excerpts. Exact-quote validation, arithmetic and policy rules stay
in application code. A half-billion-parameter model is not presumed reliable at
general claims reasoning. Fine-tuning aims to improve task behavior; quantization
and context/concurrency limits primarily control memory.

The current worker's 12,000-character evidence budget and 1300-token output must
not be reused unchanged for this 2K runtime. A later integration needs tokenizer-
aware input budgeting, shorter per-finding requests and explicit abstention when
supporting evidence cannot fit. Do not silently truncate required policy context.

## Baseline measurement

Download only the chosen official quantized artifact once network access is
available. Record its repository revision and SHA-256. Install llama.cpp through
Nix on this host; inspect its CLI version/help before executing the benchmark.

```sh
python3 scripts/dev/benchmark_small_model.py --model /path/to/model-q4_k_m.gguf
```

This script makes one bounded local synthetic request, records Linux peak RSS and
wall time, and terminates after 180 seconds. It neither downloads weights nor calls
a provider. The result measures CLI memory, not the complete hosted service.
Before acceptance, measure startup and warmed server peaks at the full context and
output bounds, over repeated native/OCR/error/injection examples. Verify that a
second request queues instead of loading a second model context. Test the final
fine-tuned quantized artifact again; a baseline fit is not sufficient.

## Fine-tuning gate

There are only three development exemplar claims today. Build and review a varied
dataset with independent held-out claim families; split before expanding templates
to prevent near-duplicate leakage. Include missing evidence, OCR errors, competing
policy versions, prompt injection and abstention. No frontier teacher generation
or real private claims are authorized for training.

Run a baseline evaluation first, then a small LoRA/QLoRA experiment only within the
existing under-USD-2 authorization and a verified cost/deletion procedure. Track
JSON validity, factual extraction, citation accuracy and unsupported findings against
the unchanged base model. Reject training if it worsens these checks.

After training, export required tokenizer/config/weights or adapter + base revision,
convert/quantize with a compatible pinned toolchain, and verify artifact hashes in
private storage. Delete the dedicated training Pod and temporary billed storage
after successful artifact verification; terminate failed jobs as well. No GPU job
has been started for this plan.

## Interview scope

This experiment does not establish an interview-ready web deployment. Finish the
existing UI and a verifiable demo flow in parallel with dataset preparation; do not
describe untrained or unmeasured models as fine-tuned or optimized.

Sources:
- https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF
- https://huggingface.co/docs/peft/en/developer_guides/quantization
