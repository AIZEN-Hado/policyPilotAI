# Approved local preparation: synthetic corpus and bounded experiment tooling

Updated preference (2026-11-17): the user's RAM concern applies only to their
computer. Current v3 scripts restrict model execution to the remote GPU Pod and
record remote RAM/VRAM without the former 2 GB cap. Model files, serving and
future artifact backup/verification should remain in the cloud. This supersedes
the earlier RAM-target details below; prior artifacts remain historical records.

The user approved the persistent-storage roadmap and instructed local preparation
to proceed. This implements that stage without another cloud-authentication loop,
paid provisioning, model download, live-app update or expansion of the GPU allowance.

Use a small QLoRA candidate with the already selected pinned Qwen2.5-7B-Instruct
base. A full-weight 7B training run does not fit this experiment's practical compute
budget; changing models would make the previous baseline incomparable. This first
candidate validates mechanics and measured behavior before any larger training.

Implementation sequence:

1. Reuse the app's exact review prompt, JSON schema and quote validator. Generate
   original fictional product-family splits, storing validation/test answer keys
   under evaluation rather than input data. Leave the old three PDFs unchanged.
2. Build dependency-free validators/scoring, checked manifests and a small explicit
   runtime allowlist archive. Exclude final test prompts/answers and generator from
   that archive. Verify every member through independent archive read-back.
3. Prepare a pinned GPU candidate environment and a plan-only default launcher.
   Require explicit execution on an existing network-mounted GPU Pod. Probe the
   compiler/headers, NF4 native GPU backward and tiny synthetic Qwen2 before loading
   the real model. Train only assistant tokens and reject overlength examples.
4. Bound subprocess duration and measure/check peak host RSS without resetting old
   reservations. Retain separate original-baseline, training, prediction, reload
   and archive receipts. Fresh-process adapter reload precedes verified export.
5. Test family separation, target provenance, lack of answer fields in prompt-only
   splits, incomplete-prediction rejection, corrupted artifacts, secret isolation,
   deadlines/RAM-stop behavior and assistant-only supervision using local small
   fixtures. Run no heavyweight library, checkpoint download or paid GPU locally.

Acceptance for this stage: reproducible synthetic corpus, passing standard-library
checks, source/data archive with verified hashes, working dry-run commands and a
documented manual Pod run/backup/termination path. Real GPU kernels, training,
accuracy, 2 GB model-process fit, serving and application integration remain
explicitly unverified until the corresponding runs actually happen.

See [training/README.md](../training/README.md) for runnable preparation commands,
measurement limitations and later owner-console steps. Source git metadata is
unavailable in this workspace; verified archives serve as reviewable checkpoints.
