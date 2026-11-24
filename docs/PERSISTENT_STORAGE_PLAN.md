# Persistent model storage and session compute

This is the replacement direction, not a provisioned or verified deployment.

The user's clarified requirement is a browser-only local computer: model weights,
training, inference and artifact verification stay on remote services. The former
2 GB model-process limit no longer applies to cloud compute. Measure remote RAM
and size within the selected Pod's actual capacity and unchanged compute budget.
Use cloud-to-cloud verified backups instead of requiring a model download to the
laptop. Existing local preparation source/data have not yet been migrated/deleted.

Keep the existing Render web application, PostgreSQL and private document bucket.
Model weights, tokenizer files, adapters and manifests belong on a separate
persistent model volume. The document bucket remains dedicated to source PDFs;
do not mix model checkpoints with claim uploads or delete it during cleanup.

Use a GPU Pod when training or serving the model. Attach the same persistent
volume at a documented path such as /workspace/models. The model server loads a
revision-pinned artifact from that path. Connect through a private Ollama service
or an authenticated HTTPS OpenAI-compatible endpoint. An operator starts/stops
compute through the provider initially; the app no longer manages cloud resources.
A future Pod controller would require its own reviewed implementation and budget.

Persistent storage retains files after session compute is removed, subject to
provider-specific volume/Pod lifecycle rules. It does not provide CPU/GPU
execution. Storage may continue billing while compute is off. Check live prices,
region/mount compatibility, minimum sizes and exact stop-versus-delete semantics
before creating anything. The user has now authorized recurring model storage
up to USD 3/month, separately from the existing USD 2.99 experiment ceiling and
its retained prior spend/reservations. This does not increase the GPU allowance.
Propose 30 GB Standard storage: the public rate of USD 0.07/GB/month gives
USD 2.10/month before tax. Verify the actual quote including tax and compatible
GPU stock before creating the volume. Runpod account access remains unavailable
in the authoring session; no volume or Pod has been created.

Before enabling processing, validate all of the following:

1. Verified artifact revision, license, file hashes and independent reload.
2. A single authenticated model service and a document-processing worker able to
   read the existing PostgreSQL/R2 data without exposing credentials to browsers.
3. Synthetic end-to-end generation, quote/citation validation, missing-evidence
   abstention and measured process RAM/VRAM under the intended context/concurrency.
4. Read-back-verified compute shutdown and a bounded storage retention plan.

App settings remain INFERENCE_BACKEND=disabled and PROCESSING_ENABLED=0 until that
service is ready. Future worker installations can select INFERENCE_BACKEND=openai
with MODEL_BASE_URL, MODEL_NAME and MODEL_API_KEY, or INFERENCE_BACKEND=ollama with
private OLLAMA_BASE_URL/OLLAMA_MODEL. Enable PROCESSING_ENABLED=1 only where a real
worker consumes the durable case queue. Do not queue work on a web-only deployment.

Synthetic training data and final held-out labels stay separated. Baseline and
tuned model quality must be measured; training alone does not establish accuracy.
Keep exported artifacts verified before terminating training resources.

Local preparation is implemented in training/: original synthetic family splits,
offline scoring, a small runtime-only archive, bounded GPU process scripts and
independent adapter reload/export checks. See training/README.md and
FINETUNING_PREPARATION.md. This is preparation only: no real model, GPU, training,
quality result, model RAM fit, Pod or volume has been verified by these tools.
