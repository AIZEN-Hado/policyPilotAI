# Neural-assisted claim review and reviewer tools

Date: 2026-11-24

## Approved direction

Integrate the existing span network and evidence ranker into the PDF review workflow alongside the current field rules. Add reviewer corrections, a document checklist, a claim timeline, an evidence-linked export, and a performance dashboard. Preserve the current human review authority and synthetic-demo scope.

## Architecture and inference

Keep PDF extraction and the existing six-field rule results. Add a specialist adapter with disabled, ready, and unavailable states independent of the optional generative-model connection. An explicitly configured checkpoint archive must pass the existing archive, configuration, training-manifest, architecture, and weight verification before loading. Do not use randomly initialized weights or substitute rules while reporting neural inference.

Use a separately deployable CPU inference service to keep PyTorch outside the existing web application's memory budget. It receives only the bounded extracted passages needed for a case, over an authenticated connection, and returns span predictions and ranking scores. The application validates every returned document/page identifier, field label, offset, literal source text, and finite score against the submitted input. Requests have time and input-size limits. Service failures retain the rule review and clearly report unavailable neural assistance. No paid infrastructure is provisioned by implementing the code.

The service reuses the trained model architecture and preprocessing. Use the joint decoder only with its matching structured checkpoint. Preserve offsets while splitting long pages into bounded overlapping windows; deduplicate identical predictions without hiding conflicting values. Rank evidence only for the six supported field questions, using the checkpoint's feature specification. Scores are ordering signals, not calibrated probabilities.

Persist rule results and neural suggestions separately in the case result, with checkpoint identity and inference status. Rules and models agreeing does not establish coverage. Disagreement remains visible and unresolved until reviewed. Existing page citations and OCR warnings remain available.

## Reviewer corrections

Add an append-only correction table linked to case, review revision, field, reviewer, and timestamp. A correction records the previous suggestion, accepted/corrected value, reason, and supporting document/page/offset citation. Validate the citation against stored case pages. Distinguish accepting a suggestion from entering a different value.

Require the current review revision on writes and lock the case to reject stale requests. Corrections invalidate prior acknowledgements and produce a new revision while retaining correction history. Uploading new documents makes previous corrections historical rather than automatically applying them to new evidence. Corrections are not automatically used to retrain models.

## Document checklist

Provide a clearly labeled synthetic hospitalization reimbursement checklist: policy schedule, policy wording, claim form, discharge summary, and hospital bill. Show present and missing document types using existing upload metadata. Endorsements and receipts are optional items. This is a demonstration checklist, not a claim that every insurer requires the same documents. It guides upload without blocking the existing review action.

## Claim timeline

Display cited admission and discharge date candidates, along with current reviewer-confirmed values. Sort valid normalized dates chronologically, keep conflicting dates visible, and put ambiguous or invalid dates in an unresolved section. Show discharge-before-admission warnings. Do not invent additional events from document timestamps or infer treatment history.

## Evidence-linked report

Provide an authenticated downloadable HTML report suitable for browser printing. Escape all user and document text. Include case identity, document inventory, checklist, rule findings, neural suggestions and availability, cited sources, timeline, correction history, and acknowledgement status. Link original downloads through existing authenticated case-scoped routes. Record generation time and review revision. Explain that links require access to the application and that the report records review, not coverage authorization.

## Performance dashboard

Show reviewed field counts, accepted/corrected suggestions, rule/model disagreements, unavailable inference runs, and correction rates with explicit denominators. Group model-specific metrics by checkpoint and field. Count the latest reviewed field outcome per evidence revision rather than every edit as another prediction. Separate historical synthetic benchmark metrics from application review statistics. Reviewer agreement is not ground-truth accuracy; unreviewed fields must not count as correct. Empty datasets display no data rather than 0% accuracy.

## API and interface

Add focused modules for specialist transport, review tools, and reports. Extend the current case detail UI with neural suggestions, correction controls, checklist, timeline, and report download. Add a workspace performance view. Use the existing visual styling, authentication boundary, case lookup, and source-citation interactions. Update readiness to distinguish specialist availability from the generative backend. Add a database migration for corrections and any durable inference-run metrics required by the dashboard; case deletion removes associated records.

## Verification and acceptance

- Test invalid checkpoint hashes, incompatible configuration, invalid citations, nonfinite scores, service timeout, and unavailable inference fallback.
- Test source offsets through long-page windows, duplicate predictions, and rule/model conflicts.
- Test correction validation, stale revisions, acknowledgement invalidation, upload invalidation, case isolation, and deletion.
- Test checklist states, ambiguous dates, conflicting timelines, escaped report content, and authenticated report access.
- Test dashboard denominators, repeat corrections, checkpoint grouping, and no-data states.
- Run existing API, PDF review, and interface checks plus targeted new tests.
- Run a real verified checkpoint against a synthetic PDF case before describing neural inference as verified. Measure inference latency and service peak memory separately from weight size.

## Delivery constraints

Trained weights have not yet been located locally. Research archives and evaluation reports are present; these do not replace the trained checkpoint. The implementation can be built and tested with isolated transport fixtures, but real-model acceptance requires the verified checkpoint and a permitted execution environment. Existing research guards prohibit casually running remote-only training/evaluation scripts locally; serving must use its own explicit entrypoint. Deployment and the live service configuration remain separate from repository implementation.

Implement in this order: inference contract and adapter; correction persistence and review revision handling; checklist/timeline/report; dashboard; interface integration; regression checks and real-checkpoint verification.
