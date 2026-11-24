# Small task networks: remote execution only

This module prepares and trains a character-CNN/BiLSTM source-span tagger and an
MLP evidence relevance scorer using task-specific labels, without a pretrained
language backbone. Both networks completed their first remote training run and
held-out synthetic text evaluation. Neither is deployed for live inference.
[Experiment results](../docs/SPECIALIST_NETWORK_PLAN.md#first-checkpoint-results)

The standard-library preparation and checks do not import a neural runtime,
download weights or run models on the user's computer. Actual training, model
reload, inference and memory profiling are restricted to the remote Pod. The live
app still has processing disabled and is not automatically changed by these tools.

## Preparation and custody

From the project source:

```sh
python -B -m specialists.prepare --version v4
python -m specialists.run
python -m unittest discover -s specialists/tests -v
```

Preparation writes:

- `data/synthetic/specialists-v1/`: synthetic train/validation span and rank labels,
  with hashes, split metadata and explicit limitations.
- `evaluation/specialists-v1/`: final held-out labels. Keep separate from training.
- `artifacts/policypilot-specialists-v4-runtime.tar.gz` (use `--version v4`):
  verified source plus only
  train/validation data. It excludes the reconstructing generator, tests and final
  held-out labels, all secrets and the earlier language-model training pipeline.

Existing outputs are verified and reused when identical. The v4 command packages
the current source, including this README. The first run used the archived v3
source bundle. Dataset generation changes require a separately versioned dataset
location and code change.
No archive is extracted by the verifier. Archive contents and hashes are checked
by read-back; this is source packaging, not model accuracy or model execution.

The original English synthetic text has eight authored layout/wording families,
split 4 train / 2 validation / 2 final test, with disjoint case IDs. The families
still share synthetic semantics and generation logic. Case variants are not
independent real examples. This does not test PDF extraction, OCR or real claims.
Labels define relevant versus irrelevant evidence explicitly; a relevant clause
does not establish that it applies or authorizes coverage.

## Prepare public synthetic research inputs

From a network-enabled terminal, `sh deploy/closeout.sh` can run the existing
Render operator cleanup and both dataset imports in one invocation. It prompts
once for the reviewer password and writes validated archives and prepared data
under `data/outputs/research/`. Use the individual import commands below if you
only need research data or already have the archives.

The import commands use Python 3.11 or newer and accept local archive paths.
Download the source files on a network-enabled machine, then run the imports from
the project root. The first CMS import records the archive SHA-256 in its manifest.
Supply that independently recorded digest with `--sha256` when repeating the import
from another copy. [CMS Sample 1](https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files/cms-2008-2010-data-entrepreneurs-synthetic-public-use-file-de-synpuf/de10-sample-1)

```sh
research_input=$(mktemp -d)
curl --fail --location --output "$research_input/cms.zip" \
  'https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/de1_0_2008_to_2010_inpatient_claims_sample_1.zip' &&
python -B -m specialists.research_data cms "$research_input/cms.zip" \
  data/outputs/research/cms-inpatient-sample1-v1
```

The CMS import checks the inpatient CSV schema and published 66,773-row count.
It keeps valid admission/discharge date pairs, deduplicates stays within a
synthetic beneficiary, and assigns the beneficiary to one of three splits before
rendering. It writes up to 512 train, 128 validation, and 128 test span rows with
split-specific fictional claim wording and exact offsets into the resulting text.
Separate lineage files track the hashed synthetic beneficiary for each case.
These date-only examples are suitable for a versioned span-training experiment.
The current specialist runtime bundle uses the original synthetic corpus.
[CMS data users guide](https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/synpuf_dug.pdf)

For FieldBench, select the file with the pinned checksum in the Zenodo record.
The example uses `jq` to resolve the file name. An archive downloaded manually
from the same record can be passed to the same import command.
[FieldBench v0.4.2 release](https://zenodo.org/records/23065721)

```sh
research_input=$(mktemp -d)
curl --fail --location --output "$research_input/fieldbench-record.json" \
  'https://zenodo.org/api/records/23065721' &&
fieldbench_file=$(jq -er 'first(.files[] | select(.checksum == "md5:d4ceea03251584f0c8196472dd1efac6")) | .key | @uri' \
  "$research_input/fieldbench-record.json") &&
curl --fail --location --output "$research_input/fieldbench-archive" \
  "https://zenodo.org/records/23065721/files/$fieldbench_file?download=1" &&
python -B -m specialists.research_data fieldbench "$research_input/fieldbench-archive" \
  data/outputs/research/fieldbench-v0.4.2
```

The FieldBench import verifies the release checksum and retains only claims and
policies with synthetic and CC0 provenance. Its held-out JSONL retains the
original Markdown, gold field values and per-document manifest. Keep this output
outside training. Use reviewed field mappings for any later value-accuracy
comparison and report it separately from source-span accuracy and PDF OCR.
Both publisher archives and their prepared manifests were verified in the
PolicyPilot workspace on 20 November 2026. Local importer tests also cover
generated fixtures. [FieldBench data licensing](https://github.com/fieldbench/corpus/blob/main/DATA_LICENSE.md)

## Remote run after provider/budget checks

For the second checkpoint, prepare the frozen experiment from the imported
CMS and FieldBench data:

```sh
python -B -m specialists.prepare_research_run
```

The generated directory is `artifacts/research/specialists-research-v1/`. Its
`preparation.json` records the runtime archive hash, the training and test
manifest hashes, and the split sizes. Upload only the runtime archive to the
training Pod. Keep the independent `holdout/` directory and FieldBench
prepared files with the hosted evaluation inputs. The archive uses the
same runtime and model configuration as the first training run.

After copying the archive to the Pod, check its SHA-256 against
`preparation.json`. Extract it in a fresh directory under the mounted
`/workspace`, switch to that directory, and run
`python -B -m specialists.run` to confirm the planned dataset fingerprint
before enabling execution.

The second checkpoint's separate Colab evaluation archive is at
`artifacts/research/specialists-research-v1-evaluation.tar.gz`. Extract it in
a fresh directory on the hosted Colab CPU runtime. Supply the first checkpoint
archive from its verified R2 backup, the candidate archive, and the candidate's
verified run SHA-256.

```sh
python -B -m specialists.evaluate_research_run \
  --first /content/first.tar.gz \
  --candidate /content/candidate.tar.gz \
  --candidate-sha256 VERIFIED_CANDIDATE_SHA256 \
  --holdout holdout --fieldbench fieldbench > comparison.json
```

The report compares the three methods on the same source-span and relevance
holdout. It also checks FieldBench policy-number value accuracy with separate
reporting. Keep the evaluation archive and its labels off the training Pod.

Before a paid run, verify current Runpod access, a fresh compatible GPU quote
strictly below USD 1/hour and the remaining experiment allowance after historical
spend, retained reservations, startup/idle, storage/tax and shutdown overhead.
Existing experiment and recurring storage authorizations are unchanged. No new
Pod, network volume or subscription is provisioned by this package.

Use the verified source bundle on an existing Pod with the project and data under
a mounted `/workspace`. The provider's `RUNPOD_POD_ID` must be present. These guards
prevent accidental local execution; they are not cryptographic cloud attestation.
Review the Pod's PyTorch/CUDA/driver compatibility before installing anything.
If a reviewed compatible environment is unavailable, stop instead of repeatedly
burning paid startup time. The provided CUDA 12.8 requirements are a candidate
stack, not a verified installation on a particular provider GPU.

Commands below belong in the **remote Pod's terminal**, after copying/verifying
the runtime bundle and its checksum. Do not run the installation locally:

```sh
cd /workspace/PolicyPilot
python -c "import os; from pathlib import Path; assert os.environ.get('RUNPOD_POD_ID') and os.path.ismount('/workspace') and Path.cwd().is_relative_to('/workspace')"
# Only if the reviewed Pod environment needs this stack:
python -m pip install -r specialists/requirements-cu128.txt
python -B -m specialists.run
```

After reviewing the plan, use the actual quoted rate and reconciled remaining
compute-only allowance. These values are deliberately not copied from stale bills:

```sh
python -B -m specialists.run --stage train --execute \
  --hourly-rate-usd ACTUAL_RATE_BELOW_ONE \
  --remaining-compute-usd ACTUAL_RECONCILED_ALLOWANCE \
  --max-seconds 300
```

Use only the freshly extracted runtime bundle as `/workspace/PolicyPilot`, with
no unrelated files, virtual environment or bytecode cache inside it. `-B` preserves
that frozen inventory. Config and dataset paths are bound to the verified bundle,
and each stage records the fingerprints of the exact bytes it consumes.

The single working deadline covers baseline, neural training and independent fresh-process
reload, with up to three seconds of child-stop grace also reserved in the compute
estimate. Children receive a restricted environment without provider API keys,
database, R2, GitHub or Hugging Face credentials. There are no retries. The launcher
stops its child process on timeout; **it does not stop or terminate the billed Pod**.
Do not leave paid compute running after the run or rely on this as a dollar cap.

Reports and state dicts stay under `/workspace/specialist-runs/run-*`, outside the
frozen source. A sibling `run-*.receipt.json` records completion only after archive
verification succeeds. A successful
training run requires both weight files within the byte target and independent
reload/prediction parity before manifest/package export. It does not establish
held-out quality, robust abstention or suitability for deployment. Validation
metrics are not production accuracy. Final testing must happen only after weights
and configuration are frozen, with the separate final labels kept out of training.

## Render and R2 deployment direction

The current existing Render web app was read back on 2026-11-18 as a Free service.
Its free instance has 512 MB RAM, sleeps after 15 idle minutes, and has ephemeral
local storage. Separate Render background workers do not have a free instance.
The existing deployment is web-only; enabling a queue does not create a worker.

R2 Standard includes 10 GB-month storage and operation allowances, shared with
other account usage. Small weights fit in that storage allowance when space
remains. R2 retains objects; it cannot execute the networks. Use a dedicated
private model-artifact bucket and bucket-scoped credentials, separate from source
PDFs and their cleanup lifecycle. No bucket is created or used by preparation.

Before starting the Pod, create or select a dedicated private Standard R2 model
bucket and prepare its bucket-scoped Object Read & Write key. Confirm the current
Pod quote, billed storage, and remaining experiment allowance in Runpod. Allow
time for startup, verification and backup in addition to training.

From the Pod terminal, after the launcher reports a completed run, run the backup
with the exact run archive path. The command uses the Pod's boto3 installation.
If the environment lacks it, install it on the Pod with
`python -m pip install boto3==1.43.127`.

```sh
python -B -m specialists.backup /workspace/specialist-runs/run-RUN_ID.tar.gz \
  --account-id YOUR_R2_ACCOUNT_ID --bucket YOUR_PRIVATE_MODEL_BUCKET
```

The command prompts for the two S3 keys without echoing them. It verifies the
completed training receipt, the archive and both weight members before uploading.
The R2 object key includes the archive's SHA-256, and the upload is conditional on
the key being absent. It reads the complete object back and compares its size and
checksum, then saves an `.r2.json` receipt beside the archive. Save the receipt
or its object key and SHA-256 before terminating the dedicated Pod and removing
temporary storage. Check the Pod and temporary volume are gone in the dashboard.
Keep the verified private R2 copy.

An inference deployment may download a pinned, checksum-verified artifact from R2
into an ephemeral cache on Render. Full runtime RAM, CPU latency and the combined
web/worker/OCR lifecycle must be measured on the intended instance. Weight size is
not runtime RAM. Do not add PyTorch to the live API or promise free-instance fit
from the parameter estimate. A lean CPU export may be evaluated after remote
reload works; no ONNX export/runtime has been verified here. No hosted mode or
generative worker has been replaced yet.

References: [R2 pricing](https://developers.cloudflare.com/r2/pricing/),
[R2 bucket-scoped credentials](https://developers.cloudflare.com/r2/get-started/s3/),
[R2 conditional writes](https://developers.cloudflare.com/r2/api/s3/api/),
[Render Free limits](https://render.com/docs/free),
[Render Docker instance sizes](https://render.com/hosting/docker).
