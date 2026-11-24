# Specialist neural pipeline without an SLM or LLM

Date: 2026-11-18. Both specialist networks were trained and backed up to R2.
The first checkpoint completed hosted CPU evaluation on held-out synthetic
English cases. No live inference deployment is enabled.

## First checkpoint results

On the frozen English test split, the span extractor scored 17.7% exact-span
F1 versus 0% for the rules, and the evidence ranker scored 75% top-1 accuracy
versus 25% for the rules. This is enough to justify further ranking tests.
Field extraction needs substantial improvement before use in the app.
The Colab evaluation completed in 5.893 seconds with a process peak of
372,158,464 bytes. Render fit remains untested because the OCR, web service
and worker loads differ from the evaluation notebook.

Use development and validation examples for follow-up diagnosis. Freeze a
fresh holdout for decisions about any model or baseline changed in response
to the reported test results.

## Preparation checkpoint

- Implemented the two network definitions, exact source-span/BIO encodings,
  deterministic relevance features and a default estimate of 621,806 combined
  parameters (2,487,224 raw FP32 weight bytes). These are metadata calculations,
  not instantiated/trained weights or runtime-memory measurements.
- Generated original English labels: train 768 span/512 rank rows; validation
  384/256; final test 384/256. Case IDs and eight authored wording/layout families
  are split. Shared semantic generation rules limit generalization claims.
- Runtime bundle contains only the bounded source, config, train and validation
  data. Final labels and their reconstructing generator remain outside training.
  Source manifests, exact input fingerprints, independent reload/prediction parity,
  weight-size checks and archive read-back are required for remote completion.
- Training is plan-only by default, with remote execution guards and a shared
  child deadline. No source model runs locally, provider changes, dependency
  downloads or live deployment are performed. Cleanup still requires actual
  provider shutdown and verified independent remote artifact backup.
- Existing Render service read-back confirms Free plan. R2 Standard capacity is
  suitable for the small target files if account allowances remain; 512 MB Render
  runtime fit and the web/worker/OCR lifecycle still need measurement. No inference
  export, private model bucket upload or free hosting guarantee is established.

See `specialists/README.md` for source preparation, remote-only commands and
deployment limitations. New source is outside the already-frozen commit queue.

The current runtime archive is `artifacts/policypilot-specialists-v3-runtime.tar.gz`.
It initializes CUDA in each training and reload process before resetting GPU
memory statistics. The v2 attempt on the Blackwell MIG Pod passed the baseline
and failed at that reset before training. The v3 fix has a local regression test
and succeeded on the remote retry. The bundle includes a Pod-side R2 backup command that checks the training receipt, uses a
conditional write and verifies the full object by SHA-256 read-back. Local tests
used an S3 test double. A live backup requires the dedicated private bucket and
its scoped credentials.

For the first session, review the unsubmitted deployment form in the Runpod
console. Record the GPU, data center, PyTorch template and CUDA version, hourly
quote including billed disk, and recent account spend. Count startup through
shutdown and retain historical reservations. Prepare the private model bucket
before starting billed compute. For browser file transfer, select a PyTorch
template with JupyterLab, upload the source archive under `/workspace`, and
verify it before extraction. [Runpod Pod connections](https://docs.runpod.io/pods/connect-to-a-pod)

```sh
cd /workspace
sha256sum -c <<'EOF'
616df13b7dc1a2851bc64cf79343301d01fbd96f7237732dcc8ccd9132db06fa  policypilot-specialists-v3-runtime.tar.gz
EOF
```

After the checksum returns OK, extract into a new directory and run the
preparation check in the Pod terminal.

```sh
mkdir /workspace/PolicyPilot &&
  tar -xzf /workspace/policypilot-specialists-v3-runtime.tar.gz -C /workspace/PolicyPilot &&
  cd /workspace/PolicyPilot &&
  python -B -m specialists.run
```

The user's latest clarification is: train a connected set of small task-specific
neural networks instead of any SLM or LLM. Consequently, Qwen, BERT, MiniLM and
other pretrained language-model backbones are outside this proposed path. The
earlier frozen-language-encoder/head recommendation is superseded. Existing OCR
may remain an established component; we do not propose training an OCR engine.

## Proposed architecture

PDF -> existing Poppler/Tesseract extraction -> small neural specialist modules ->
explicit validation and rule checks -> fixed, source-linked review report.

Start with two specialist networks, served together in one cloud worker:

1. **Field/span extractor:** a small character-feature CNN plus a bidirectional
   LSTM token tagger, with task-specific token labels. Start with policy/member
   identifiers and relevant dates, then add limits and amounts only with explicit
   field definitions. Return original text values, page numbers and character
   offsets. Tokenization must retain its exact mapping to stored source text.
   Training uses field labels, not a next-token language-model objective.
2. **Evidence relevance network:** a small MLP over query/clause word and character
   features, document kind, section cues and extracted field features. It ranks
   supplied policy/schedule/endorsement chunks for a defined review question.
   A high relevance score does not establish applicability, coverage or entailment.
   Preserve policy/schedule reservations and the hard evidence budget from core.py.

A document-kind classifier is an optional third specialist; the current upload
flow already supplies this label, so it is not required for the first experiment.
Separate specialist models need not mean separate servers or GPU allocations.

The first two models can learn their task weights from random initialization.
Use deterministic character/word/geometry features or small learned embeddings,
without a pretrained text-language backbone. Reconsider a more complex architecture
only after a baseline identifies a concrete failure that the change addresses.

## Explicit code and reviewer responsibilities

Keep arithmetic, normalized identifier comparisons, date ordering, evidence
coverage, exact quote checks and missing-field checks in code. Policy-specific
rules require explicit versioned definitions, verified extracted facts and cited
clauses; a model's class label must not silently become a coverage rule. Conflicting
endorsement dates or unrecognized wording require clarification and human review.

Generate the report from defined templates and validated structured facts. This
does not provide unrestricted chat or general policy interpretation. The existing
pilot/worker.py still calls the generative adapter; a new reviewed processing mode
must replace that call and the connection/readiness checks before the application
can be described as operating without a generative model. Live processing remains
disabled until the replacement is tested. Preserve the live authenticated document
workspace and existing storage cleanup during this change.

## First training experiment

Use synthetic data only. Define field-span labels and evidence-relevance labels
before training. Include wrong identifiers, admission/discharge confusion, dates
in receipts, unrelated limits, negated clauses, outdated endorsements, and absent
evidence. Unlabeled passages are not automatically negative examples.

Split by whole case and independently authored layout/policy families before
rendering or producing degradations. Keep near-duplicate variants in the same
split, and keep held-out labels out of the worker. Start with native extracted
text and known offsets. Scanned-page evaluation needs independently annotated
post-transform source spans; canonical pre-transform boxes do not supply them.

Compare the field extractor to a regex/context baseline, and the relevance network
to the current lexical selector, using identical inputs and evidence budgets.
Record exact field/value/span matches, required-evidence recall, wrong-source
selections, missing/conflicting-evidence detection, abstention, invalid citations,
latency, remote RAM/VRAM and cost. Report per-family failures. Promote each network
only if held-out results justify replacing its baseline. Multiple networks do not
automatically improve accuracy; their errors can compound.

The current three English development cases (24 PDFs, 29 pages, one scan) are
engineering fixtures, not enough to establish generalization. The separate
144/72/72 text-review examples are not an entity-tagging or PDF/OCR benchmark.
The first synthetic checkpoint results are recorded above. No serving-memory
or hosted application cost has been measured.

## Public synthetic research data

- **CMS DE-SynPUF Inpatient Claims, Sample 1 (2008–2010).** CMS makes the synthetic
  claims available in the public domain for research and software development.
  Use the inpatient admission and discharge dates to seed fictional claim
  forms, then label spans against the rendered text. Split by synthetic
  beneficiary before rendering. The CSV provides structured values and needs
  rendering and span annotation before it can train the extractor. Its payment
  and deductible amounts are Medicare variables. Keep PolicyPilot's policy
  limits and Indian insurance terminology in the authored fixtures.
  [CMS dataset](https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files/cms-2008-2010-data-entrepreneurs-synthetic-public-use-file-de-synpuf)
  · [Sample 1 inpatient ZIP](https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/de1_0_2008_to_2010_inpatient_claims_sample_1.zip)
  · [Data users guide](https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/synpuf_dug.pdf)
- **FieldBench v0.4.2, synthetic insurance claims and policies.** Retain only
  documents whose manifests explicitly identify them as synthetic and CC0.
  Keep each selected document's provenance manifest and expected-field JSON.
  Use matching fields as a separate held-out text extraction benchmark. Ground
  truth is primarily field values in Markdown, so report value accuracy
  separately from PDF OCR, exact-span F1, and evidence ranking. The release
  archive also includes material with other terms.
  [Pinned release](https://zenodo.org/records/23065721)
  · [Data licensing](https://github.com/fieldbench/corpus/blob/main/DATA_LICENSE.md)
  · [Datasheet](https://github.com/fieldbench/corpus/blob/main/DATASHEET.md)

Both publisher archives were acquired in the owner terminal. The prepared
manifests and archive SHA-256 checks passed on 20 November 2026. CMS Sample 1
contains 66,773 source rows and produced 512 training, 128 validation and 128
held-out span examples. FieldBench matched the published MD5
`d4ceea03251584f0c8196472dd1efac6`. Its filtered holdout has 140 synthetic claims
and 80 synthetic policies.

`policy_number` is comparable to PolicyPilot's policy ID. Loss dates and
occurrence limits have different meanings from hospital admission dates and
room limits. On the original FieldBench Markdown, the current production
field rules resolved zero of 220 policy IDs. All expected IDs occurred in
the input text, and 184 documents exceeded the specialist's 256-token
window. Compare all scorers on the same defined input and report truncation
or windowing separately from results on PDF pages.

## Second checkpoint experiment

Train the same two architectures on the original train and validation inputs,
augmented with the corresponding CMS date rows and fresh relevance groups.
Each relevance group pairs one supported passage with plausible alternatives
that share vocabulary or numeric formats. Keep the CMS test rows, fresh
authored holdout, and FieldBench inputs outside the training archive.

Compare the rules, first checkpoint and candidate on the same new test inputs.
Report exact-span F1 by source and field, evidence top-1 accuracy by query
group, and FieldBench policy-number value accuracy separately. The earlier
17.7% exact-span F1 and 75% ranking accuracy refer to the first experiment's
test set. The new comparison needs new scores for the first checkpoint too.

Freeze and verify the runtime archive and independent holdout before a paid
run. Reconcile the current Runpod quote and remaining allowance with startup,
idle and shutdown time before approving training. Evaluate a verified export
in hosted Colab. The demo uses its currently deployed field rules while the
candidate is evaluated.

## Execution, storage and artifacts

Training, weights, model inference and model artifact verification stay in the
cloud. No model or neural runtime download/execution on the user's computer.
Serverless remains retired. Persistent storage retains files but cannot execute
them. CPU serving may be evaluated later; no free always-on deployment or memory
fit is assumed. Existing budgets, historical spend and reservations are unchanged.

Before paid training, verify current Runpod access, an actual compatible Pod quote
below the approved hourly limit, remaining allowance, data split checks and a
bounded runtime/shutdown plan. Save architecture, tokenizer/feature mappings,
trained weights, label definitions, dataset hashes, evaluation results and file
hashes. Independently reload and verify artifacts on remote compute before deleting
dedicated training compute and temporary storage. Preserve the designated model
volume and independently verified backup according to its retention policy.

No paid job, provisioning, source commit or push is performed by this design.
The frozen 500-commit queue retains its original snapshot and is not modified.

## Technical references

- [PyTorch LSTM](https://docs.pytorch.org/docs/stable/generated/torch.nn.LSTM.html)
  provides sequence outputs and bidirectional configuration for the proposed tagger.
- [PyTorch Conv1d](https://docs.pytorch.org/docs/stable/generated/torch.nn.Conv1d.html)
  provides the proposed character-feature convolution building block.

These APIs establish available implementation components, not PolicyPilot accuracy.
