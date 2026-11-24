# Specialist precision experiment

The next checkpoint uses the existing field extractor and evidence ranker with
complete-value and query-group supervision. The previous checkpoint stopped
after 60 updates per network. This experiment schedules ten complete epochs,
with 800 extraction updates and 240 ranking updates over the same frozen
training inputs. It exports the best validation epoch for each network and
checks prediction parity in a fresh process.

The extractor scores complete dates, identifiers and amounts against an
explicit missing-field choice. Predictions keep the exact offsets in the
source text. The ranker trains over all candidate passages for a question
together and outputs ordering scores.

## Measure the 99% target

The evaluator requires at least 99% exact-span precision and recall for each
of the six fields, and at least 99% strict top-1 evidence accuracy. Missing
required spans reduce recall. Unsupported or incorrectly bounded spans reduce
precision. A tied first place counts as a rank miss.

The fresh holdout contains four synthetic English text families and 128
answerable ranking groups. The report includes ranking by family, exact-span
metrics by field, and results for the rules and an optional prior checkpoint.
The cases reuse fictional value generators. A pass applies to this synthetic
test only. Document scans, OCR errors, unanswered questions and real-policy
performance require independent evaluation.

## Run the experiment

1. Generate the two archives with `python -B -m specialists.prepare_precision_run`.
   The preparation receipt under `artifacts/research/specialists-precision-v1/`
   records both archive hashes and the holdout manifest hash.
2. Upload the runtime archive to the Runpod training Pod. Verify its hash,
   extract it into a fresh directory under mounted `/workspace`, and run the
   plan-only check with `python -B -m specialists.run`. Use the existing
   [remote training and backup procedure](../specialists/README.md#remote-run-after-providerbudget-checks)
   for the bounded GPU run and verified checkpoint backup.
3. Extract the evaluation archive separately on a hosted Colab CPU runtime.
   From the extracted directory, run the command below with the read-back
   SHA-256 from the candidate backup and the holdout SHA-256 from preparation.

```bash
python -B -m specialists.evaluate_precision_run \
  --candidate /content/candidate.tar.gz \
  --candidate-sha256 "$candidate_sha256" \
  --holdout holdout \
  --holdout-sha256 "$holdout_sha256" > precision-comparison.json
```

To compare the most recent original-objective checkpoint on the same holdout,
also supply its archive path and verified SHA-256 using `--reference` and
`--reference-sha256`. Model execution and weights stay on hosted services.

## Date wording and layout follow-up

The first structured checkpoint reached 39.3% exact-span F1 on validation.
Admission dates reached 39.3% F1 and discharge dates reached 15.6% F1. The
extractor's best validation epoch was 2. Its training loss fell as validation
F1 declined in later epochs.

Run `python -B -m specialists.prepare_date_run` to build the follow-up runtime
under `artifacts/research/specialists-date-diversity-v1/`. It adds 384 synthetic
training documents across 12 layouts, including planned, cancelled and
historical dates. The examples vary date order, labels and formatting. Sixty-four
documents have distractor dates and no current-stay date labels.

The runtime reuses the verified structured-training code and the same
ranking data and validation files. The manifest records the hashes. The
candidate trains for ten epochs with the step ceiling raised to cover 1,040
extraction updates. Follow the existing remote training and backup procedure
using the new archive path and its manifest hash. Use a fresh output directory
on the mounted workspace.

Compare validation exact-span precision, recall and F1 for admission and
discharge dates against the previous receipt. Check the other fields and ranker
for regressions. The frozen holdout remains reserved for the final tuned
candidate.

## Quality candidate and held-out decision

`python -B -m specialists.prepare_quality_run` packages the contextual field
encoder, versioned ranking features, and additional synthetic training rows.
The original validation files retain their original hashes. The existing
four-family holdout is packaged with the evaluator and kept off the training
Pod.

The quality candidate trained on a temporary Runpod GPU Pod. Both weights
reloaded in a fresh process with matching validation predictions. A separate
CPU Pod read the candidate and previous checkpoints from the network volume
and verified the reserved holdout before scoring both. The evaluator supports
hosted Colab and Runpod CPU and verifies the checkpoint, configuration, dataset
and holdout SHA-256 fingerprints.

On the same held-out synthetic text, overall exact-span F1 rose from 40.1% to
90.9%, and strict evidence top-1 rose from 58.6% to 87.5%. The candidate returned
320 correct spans out of 384 required spans, with zero false positives in this
sample. It missed 16 member IDs, 16 discharge dates, 32 room limits and 16
ranking groups. The 99% gate failed. A later tuned candidate needs an independent
holdout to make a new release decision.

Both temporary Pods were removed. The verified checkpoint is on Runpod volume
`c9iaje0u23`. The private R2 copy remains pending. See the
[run receipt](../artifacts/research/specialists-quality-v1-candidate-run.json)
and [held-out comparison](../artifacts/research/specialists-quality-v1-heldout-evaluation.json).

## Diagnose the next improvement on development data

Build a validation-only bundle with `python -B -m specialists.prepare_quality_diagnostic`.
It preserves the previous validation files and includes eight additional
development ranking questions with close distractors. It carries no holdout
rows or model weights. The preparation receipt reports how many gold spans
the candidate generator can represent before applying model scores.

Extract the verified diagnostic archive under `/tmp` on a Runpod CPU Pod
with the existing checkpoint volume mounted. From the extracted directory,
run the diagnostic with the four hashes from the preparation and candidate
receipts:

```bash
python -B -m specialists.diagnose_quality_validation \
  --checkpoint "$checkpoint_archive" \
  --checkpoint-sha256 "$checkpoint_sha256" \
  --config-sha256 "$config_sha256" \
  --training-manifest-sha256 "$training_manifest_sha256" \
  --validation validation \
  --rank-probe-sha256 "$rank_probe_sha256"
```

Use the field and family counts to distinguish missing complete candidates,
rejection by the null score, competing values, and overlapping predictions.
The ranking probe reports strict top-1 and miss counts on a small development
sample. Keep subsequent decisions on development data until a new independent
holdout is frozen.

The hosted CPU diagnostic verified that all 960 required validation spans had a
complete candidate. Of the 388 misses, 168 lost to the null score, 138 overlapped
another field output, and 82 lost to another value for the same field. The
extractor also emitted 360 false positives on these validation examples.
Ranking scored 192 of 192 on the original validation groups and 4 of 8 on the
additional development probe. See the
[diagnostic result](../artifacts/research/specialists-quality-v1-validation-diagnostic.json).

## Compare joint field selection

Run `python -B -m specialists.prepare_joint_selection` to package the
development comparison. Both decoders use the same verified checkpoint,
validation rows, complete candidates and score threshold. The joint decoder
chooses the highest-scoring set of nonoverlapping spans with at most one
assignment per field. It leaves scores at or below zero unassigned.

On a CPU Pod with the checkpoint volume attached, extract the archive under
`/tmp` and run `python -B -m specialists.joint_selection`. Supply the checkpoint
path and the three fingerprints using the same flags as the diagnostic, plus
`--validation validation`. The comparison reports correct spans gained and
lost, false positives, and precision and recall by field. It records whether
joint selection finds more exact spans while holding false positives at or
below the greedy decoder's count. This experiment scores development data
only and leaves the existing runtime decoder unchanged.

The hosted comparison recovered 32 admission dates and 32 discharge dates
without losing any previously correct span. Exact-span F1 rose from 60.5% to
66.5%. False positives fell from 360 to 318, so joint selection met the
development comparison criterion. The other fields produced identical
counts. See the [joint selection result](../artifacts/research/specialists-joint-selection-v1-comparison.json).

## Test the joint decoder on a fresh holdout

Run `python -B -m specialists.prepare_joint_release` to package the accepted
development decoder and freeze a new eight-family synthetic holdout. The
package records the existing checkpoint and config fingerprints. It carries
neither model weights nor development rows.

Extract the package under `/tmp` on a Runpod CPU Pod with the checkpoint
volume mounted. Run `python -B -m specialists.evaluate_joint_release` with the
checkpoint path and its three fingerprints using the same flags as the
development comparison, and replace `--validation validation` with
`--holdout holdout --holdout-sha256 "$holdout_manifest_sha256"`. The evaluator
scores both decoders with the same model and scores the unchanged ranker once.
It reports per-field precision and recall, strict ranking accuracy and the 99%
gate for each decoder. Synthetic template variants cannot establish real-world
performance.

The hosted comparison used 768 labeled spans and 53 ranking groups. Joint
selection recovered 16 correct spans and lost none. Exact-span F1 rose from
70.7% to 73.0%, and false positives fell from 128 to 112. Room-limit recall
was 34.4%. The unchanged ranker placed the right clause first in 37 of 53
groups. Neither decoder passed the 99% gate on this sample.

Runpod removed the first CPU Pod after a startup timeout. The second Pod
completed evaluation and was also removed. The estimated compute cost was
$0.00353 across both attempts. See the
[paired held-out report](../artifacts/research/specialists-joint-release-v1-evaluation.json).

## Public policy and room-limit experiment

The [MIT-licensed Insurance Document RAG dataset](https://github.com/ahmedabuzaid15-git/insurance-document-rag)
contains 20 synthetic policies. Individual and student policies supplied
training passages, family policies supplied validation passages, and senior
and expatriate policies supplied five publisher-labeled ranking questions
for the holdout. Independently authored synthetic examples supplied room-limit
annotations and additional ranking groups.

Run `python -B -m specialists.prepare_public_policy_run --cpu` to build the
separate training and evaluation bundles. The Runpod CPU run froze its
checkpoint before transferring the holdout to temporary storage. On 864
labeled spans and 149 ranking groups, room-limit recall rose from 50.0% to
84.0% at 100% precision. Strict ranking accuracy rose from 48.3% to 65.8%,
and overall exact-span F1 fell from 46.2% to 43.8%. The candidate failed the
99% release gate. See the [held-out report](../artifacts/research/specialists-public-policy-v1-cpu-heldout-evaluation.json)
and the [training receipt](../artifacts/research/specialists-public-policy-v1-cpu-candidate-run.json).

## Balanced field extraction on development data

Both checkpoints missed every policy identifier and sum-insured span in the
public-policy experiment. Run `python -B -m specialists.prepare_balanced_run`
to build the follow-up bundle. It adds 384 synthetic training documents and
120 development documents with distinct wording and layouts. The additional
development data has 72 exact labels per field and includes cases with only
illustrative values. Ranking inputs retain their original file hashes.

Run the bounded `specialists.run` launcher on a Runpod CPU Pod. After the
independent reload verifies the candidate, run
`python -B -m specialists.compare_balanced_validation` in the extracted runtime.
Supply each archive path and its archive, training-manifest and config SHA-256
fingerprints, together with the balanced dataset manifest SHA-256. The report
compares both checkpoints with the joint decoder on the same development inputs.
The training Pod receives only the training and development bundle. A release
decision requires a new independent holdout.

On the 120 added development documents, exact-span F1 rose from 61.4% to
70.9%. On the previous development documents it rose from 75.1% to 77.5%.
Strict evidence ranking held at 94.5% across 256 development queries.
The candidate found all 72 admission and discharge dates in the added
development examples. Room-limit precision was 29.6%, and sum-insured
recall was 20.8%. Runpod confirmed both temporary Pods were removed and
the checkpoint volume retained. See the
[development comparison](../artifacts/research/specialists-balanced-fields-v1-development-comparison.json)
and the [training receipt](../artifacts/research/specialists-balanced-fields-v1-candidate-run.json).

## Benefit amounts and evidence on a fresh holdout

Run `python -B -m specialists.prepare_benefit_run` to seal the training and
evaluation archives. The added training examples pair binding benefit amounts
with provider charges, previous limits, pending proposals, and deposits.
Evidence groups ask separate questions about two clauses from the same set.
The runtime archive contains 480 new span documents and 482 new ranking groups
for training, plus separate development examples. The evaluator contains 192
synthetic documents and 242 ranking groups from wording families excluded
from training. The ranking groups use 12 unique question wordings.

Train with the bounded Runpod CPU launcher and verify that a separate process
reloads the weights and reproduces validation predictions. Then extract the
evaluation archive under `/tmp` and run
`python -B -m specialists.evaluate_public_policy_run` with both checkpoints and
the archive, dataset, config, and holdout hashes from the run receipts. The
same joint decoder and strict metrics apply to both checkpoints.

On the new holdout, overall exact-span F1 rose from 43.2% to 51.2%, and
strict evidence top-1 rose from 50.0% to 70.2%. Sum-insured recall rose from
25.0% to 50.0%. Room-limit precision fell from 40.0% to 39.5%, and recall
fell from 50.0% to 49.0%. The candidate failed the 99% release gate.
Runpod confirmed the temporary Pod was removed and the checkpoint volume
retained. The R2 backup requires the private model bucket credentials.
See the [held-out report](../artifacts/research/specialists-benefit-evidence-v1-heldout-evaluation.json)
and the [training receipt](../artifacts/research/specialists-benefit-evidence-v1-candidate-run.json).

## Bounded self-training experiment

Run `python -B -m specialists.prepare_self_learning` to seal the training and
evaluation bundles. The supervised round adds independently composed clause
layouts with nearby competing values, dates, and references. Versioned input
features give both networks more context about which clause and policy version
a value or passage belongs to. All generated material is synthetic English.

The bounded Runpod CPU launcher trains the supervised teacher and then runs
two self-training rounds. The unlabeled pool has no gold spans or relevance
labels. A candidate needs a softmax score of at least 0.90, a score margin of
at least 1.5, and agreement across the original and perturbed input. Each
accepted row contributes at most once and subsequent rounds retain the gold
training data. The archive includes both networks before and after
self-training, with independent validation prediction checks for both.

After the checkpoint archive is frozen, use
`python -B -m specialists.evaluate_self_learning` with the verified checkpoint
and holdout hashes. The 95% experiment target applies to each field's exact-span
precision and recall and to strict evidence top-1 accuracy. The evaluation
keeps the synthetic benchmark separate from any production accuracy claim.

On the fresh holdout, self-training increased exact-span F1 from 90.0% to
93.2% and strict evidence top-1 accuracy from 90.1% to 90.7%. The rounds added
450 pseudo-labeled extraction documents and 574 pseudo-labeled ranking groups.
On the earlier benchmark, extraction F1 moved from 78.3% to 77.4% and ranking
held at 80.2%. The self-trained checkpoint missed the 95% target. See the
[fresh held-out report](../artifacts/research/specialists-self-learning-v1-heldout.json)
and the [prior benchmark](../artifacts/research/specialists-self-learning-v1-prior-benchmark.json).

The follow-up fitted score corrections using development examples and then
evaluated a separately sealed holdout. Development extraction F1 rose from
88.8% to 95.7%. The held-out extraction result moved from 75.0% to 75.2%,
and ranking reached 312 of 312 on that holdout. The final gate still failed
because several fields remained below the target. Both temporary Pods were
removed. See the [calibration holdout report](../artifacts/research/specialists-self-learning-calibration-v1-heldout.json).

## Research data fine-tuning

Run `python -B -m specialists.prepare_research_transfer` to seal the runtime
and evaluation archives. The hosted launcher is
`python -B -m specialists.research_transfer_runtime --execute` with the usual
Runpod rate, budget, deadline, and mounted output directory arguments. It
starts from the verified self-trained checkpoint and fine-tunes both networks
for six epochs. The run retains the existing labeled training data and adds
1,440 CMS-derived claim date examples and 103 evidence groups over the
MIT-licensed policy passages.

New CMS examples use one stay per synthetic beneficiary. Beneficiaries used
in the earlier CMS preparation are excluded, and the new splits maintain
beneficiary isolation. The evaluator checks 320 new CMS stays, five existing
publisher questions from reserved plans, all 220 FieldBench documents, and
the earlier synthetic holdout as a regression check. FieldBench reports
policy-number value accuracy over overlapping text windows. Its documents
and labels stay in the evaluation archive.

The warm-start checkpoint reproduced its validation predictions in a fresh
process. On the new CMS holdout, both checkpoints found 320 of 640 exact
date spans, for 50.0% date-span F1. Both ranked the correct clause first for
all five reserved publisher questions. FieldBench policy-number accuracy
fell from 66.8% to 50.9%. On the earlier synthetic holdout, extraction F1
was 93.15% and strict ranking accuracy was 90.38%. The previous checkpoint
remains the comparison baseline. Runpod confirmed the temporary Pod was
removed. See the [held-out report](../artifacts/research/specialists-research-transfer-v1-heldout.json)
and [training receipt](../artifacts/research/specialists-research-transfer-v1-candidate-run.json).
