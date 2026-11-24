# CPU specialist service

This optional service runs the existing trained span network and evidence ranker.
It never trains, changes research execution guards, or uses random weights as predictions.
Real-checkpoint inference has **not** been verified locally: no trained checkpoint is available.
Transport and loader tests do not establish model quality, latency, or peak memory.

Use a separate CPU environment with `requirements-serving.txt`; do not install torch
in the web application's environment. No provisioning or deployment is part of this change.
The operator must supply a trusted trained checkpoint archive and independently verify
its SHA256 from the training release. The archive needs the standard manifest,
`metadata.json`, `validation.json`, `reload.json`, `span.pt`, and `rank.pt` at its root.
Research/source bundles are not trained checkpoints. Archive verification, metadata,
feature versions, architecture, training fingerprints/updates, validation identity,
weight hashes and sizes, finite tensors and strict state dictionaries are required.
A bad checkpoint prevents startup. Archive SHA256 is the returned checkpoint identity.

Set on the service:

```
SPECIALIST_ARCHIVE=/absolute/path/to/trained-checkpoint.tar.gz
SPECIALIST_CHECKPOINT_SHA256=<64 lowercase hex archive digest>
SPECIALIST_TOKEN=<random secret, 16-512 printable nonspace ASCII characters>
```

Run from the repository root in that environment:

```
uvicorn specialists.serving:create_app --factory --host 127.0.0.1 --port 8091 --workers 1 --no-access-log --limit-concurrency 4
```

Set on the web application:

```
SPECIALIST_URL=http://127.0.0.1:8091
SPECIALIST_TOKEN=<same secret>
SPECIALIST_CHECKPOINT_SHA256=<same independently trusted digest>
```

For separate hosts use HTTPS and a private network with appropriate proxy request/body
and connection limits. Plain HTTP is accepted only on loopback. Redirects are refused.
Never log request bodies or authorization headers. Keep proxy access logs disabled or
sanitized. `/review` is authenticated; there is no unauthenticated inference endpoint.
The existing application readiness reports configuration separately; a ready result is
only persisted after successful inference and client validation.

Limits: 60 pages/documents, 160,000 text characters, 1 MB request/response, 192 overlapping
token windows, 250 suggestions per field, top 10 evidence passages per field. A service
request uses one inference worker and checks a 10-second budget between windows; the
client has a 12-second socket timeout. This is not a hard process CPU deadline: supervise
the service with process memory/CPU limits appropriate to its measured footprint.
Concurrent work gets 503. Oversized cases fail as unavailable instead of silently
truncating input. Policy, schedule, claim form, discharge, bill and receipt are supported;
other kinds, including endorsements, are excluded explicitly in the result detail.
Empty text yields no suggestions. Offsets remain relative to the original extracted page.

The joint decoder is used only for structured-objective checkpoints; BIO checkpoints
use argmax. Span preprocessing follows the checkpoint's recorded settings;
rank feature versions and contextual span feature versions must match the current code.
Each of the six supported field questions gets ranked passages. Scores order evidence
and are not probabilities or coverage determinations. The service emits literal source spans; the client normalizes dates, identifiers and
amounts with the rule normalizer (invalid values remain null and flagged). Duplicate coordinates are removed while
conflicting spans remain. Every returned citation and score is validated by the client.

Unset SPECIALIST_URL to roll back to disabled assistance. Authentication, transport,
configuration, bounds, or model failures produce unavailable assistance and retain the
rule review. No service exception or document text is exposed in fallback messages.
Before enabling for reviewers, test a verified archive against synthetic PDFs, record
latency and process peak memory separately from weight size, and inspect cited offsets
through long windows, field conflicts, and OCR pages.
