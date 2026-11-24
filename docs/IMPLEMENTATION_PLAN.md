# PolicyPilot: persistent model storage transition

Current direction (2026-11-18): a small specialist neural pipeline without an SLM
or LLM. See [SPECIALIST_NETWORK_PLAN.md](SPECIALIST_NETWORK_PLAN.md) for the proposed
field/span extractor, evidence relevance network, rule/template layer and training
gates. The earlier pretrained-language-encoder/head proposal is superseded by the
user's explicit no-SLM/LLM clarification. Source preparation now lives in
`specialists/`: original labels/splits, small network definitions, remote-only
bounded stages and verified source packaging. No specialist network is trained yet.

The completed parsing/retrieval improvements remain useful shared infrastructure;
see [PRETRAINED_PARSER_PLAN.md](PRETRAINED_PARSER_PLAN.md) for their verification.
Earlier generative fine-tuning preparation below is historical, not the next step.

The first parser/retrieval increment is implemented in source: quality-aware OCR
routing, source-preserving chunks/offsets, priority policy/schedule selection,
explicit coverage reporting and stricter schema/literal quotation checks. Worker
and review UI carry extraction warnings. It is not deployed: real OCR/PDF tools
are absent from this shell and API dependency skips keep the release gate blocked.

The user definitively removes the Serverless approach on 2026-11-15. No retry,
replacement queue endpoint or worker image is part of this implementation.
The pre-removal source snapshot and all billing/run reports remain in artifacts.
The snapshot is historical evidence, not an active deployment path.

## Current application

- Preserve browser sessions, authentication, PostgreSQL cases, R2/PDF storage,
  source downloads, acknowledgements, conversation history and physical cleanup.
- Remove compute-management routes, worker handlers, provider job control,
  reservation-management tooling, GPU image and browser Start/Stop/cost controls.
- Keep an honest model connection indicator and Canvas2D presentation. Default
  inference is disabled; processing is not queued until a model and worker exist.
- Preserve immutable database migrations and historical accounting records.
  Migration 007 disables the retired local controller without claiming provider
  shutdown. New application code never reads or dispatches those retired jobs.
- Support provider-independent authenticated OpenAI-compatible inference or
  private Ollama for the future service. Neither transport provisions compute.

## Release and cleanup

Build/test/publish only the application image, update the existing Render service,
remove retired environment variables, and run the synthetic web smoke. Do not
replace the existing database, bucket or session secrets. See deploy/RENDER_IMAGE_DEMO.md.
Use deploy/remove_serverless.py --apply in the owner's normal terminal to remove
only the recorded dedicated endpoint, generated templates and unused dedicated
registry credential, with shutdown/absence read-back. Direct provider access from
the authoring session failed; no cloud deletion is claimed. Never delete volumes,
buckets, PostgreSQL, unrelated resources or historical financial records.

## Persistent storage direction

See PERSISTENT_STORAGE_PLAN.md. Keep model/checkpoint files on a persistent volume
attached to a separately managed GPU Pod. Storage alone cannot run inference.
Do not provision a volume/Pod until actual prices, ongoing storage lifetime,
remaining budget, region/GPU compatibility and stop/delete behavior are reviewed.
The experiment authorization adds exactly USD 1 to the original plan: combined
experiment ceiling USD 2.99. The user subsequently authorized separate recurring
model storage up to USD 3/month. Count all past spend; do not reset old reservations or
assume a lagging billing report is a final balance. No new paid resources are
created by this cleanup. The live authenticated web application remains priority.

For fine-tuning, use only synthetic cases, independent family splits, a frozen
base-model comparison and held-out citation/factuality/abstention evaluation.
No extreme-accuracy claim is justified by the three existing development cases.
The user clarified that RAM protection applies to the local computer only.
Model execution/downloads stay on the remote Pod; cloud RAM is measured for
capacity planning without an arbitrary 2 GB ceiling. Compute allowances are unchanged.
Save/hash/independently reload trained artifacts before deleting dedicated training
compute and temporary storage. No trained model has been verified yet.

The approved local preparation stage now lives in training/ and
FINETUNING_PREPARATION.md. It does not provision resources or enable app inference.
