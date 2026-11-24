"""Exercise holdout integrity and release metrics without importing PyTorch."""

from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from specialists.artifacts import package_directory, write_manifest
from specialists.contracts import SPAN_LABELS
from specialists.evaluate import load_verified_checkpoint
from specialists.evaluate_quality_run import _read_holdout, _require_host, _target_failures, evaluate, summarize
from specialists.models import parameter_estimate
from specialists.runtime import ARCHITECTURES, _feature_spec


def _fixture():
    span_rows = []
    for index, label in enumerate(SPAN_LABELS):
        text = f"Value: TX-{index}"
        family = "one" if index % 2 == 0 else "two"
        span_rows.append({
            "id": f"span-{index}", "case_id": f"case-{index}", "family": family,
            "kind": "claim_form", "synthetic": True, "task": "span", "text": text,
            "spans": [{"label": label, "start": 7, "end": len(text), "value": text[7:]}],
        })
    rank_rows = [
        {
            "id": f"rank-{group}-{side}", "case_id": f"group-{group}", "family": family,
            "kind": "policy", "synthetic": True, "task": "rank", "text": f"Passage {group}:{side}",
            "query": "Relevant evidence?", "relevant": side == 0,
        }
        for group, family in enumerate(("one", "two", "two"))
        for side in (0, 1)
    ]
    return {"span": span_rows, "rank": rank_rows}


def _perfect_report(rows):
    return {
        "span": {"predictions": [{"id": row["id"], "spans": row["spans"]} for row in rows["span"]]},
        "rank": {"predictions": [{"id": row["id"], "score": float(row["relevant"])} for row in rows["rank"]]},
    }


class QualitySummaryTests(unittest.TestCase):
    def test_counts_missing_spans_tied_and_incomplete_queries(self):
        rows = _fixture()
        report = _perfect_report(rows)
        report["span"]["predictions"].pop(0)
        report["span"]["predictions"][0]["spans"] = [{**rows["span"][1]["spans"][0], "end": 9}]
        report["rank"]["predictions"][2]["score"] = 0
        report["rank"]["predictions"].pop(-1)
        report["rank"]["predictions"].reverse()
        result = summarize(rows, report, {"one": "source-a", "two": "source-b"})
        self.assertEqual(result["span"]["unscored_rows"], 1)
        self.assertEqual(result["span"]["exact_span"]["false_positives"], 1)
        self.assertEqual(result["span"]["exact_span"]["false_negatives"], 2)
        self.assertEqual(result["rank"]["strict_group_top1_accuracy"], 1 / 3)
        self.assertEqual(result["rank"]["tied_top_groups"], 1)
        self.assertEqual(result["rank"]["incomplete_groups"], 1)
        self.assertEqual(result["by_family"]["two"]["rank"]["missed_groups"], 2)
        self.assertEqual(result["by_source"]["source-a"]["rank"]["groups"], 1)
        self.assertFalse(result["synthetic_target_met"])

    def test_target_checks_each_field_and_counts_99_as_a_pass(self):
        rows = _fixture()
        result = summarize(rows, _perfect_report(rows), {"one": "fixture", "two": "fixture"})
        self.assertTrue(result["synthetic_target_met"])
        spans = {label: {"support": 100, "precision": 0.99, "recall": 0.99} for label in SPAN_LABELS}
        ranking = {"strict_group_top1_accuracy": 0.99}
        metrics = {"exact_span_by_label": spans}
        self.assertEqual(_target_failures(metrics, ranking), {})
        spans["POLICY_ID"]["recall"] = 0.9899
        del spans["ADMISSION_DATE"]
        self.assertEqual(_target_failures(metrics, ranking),
                         {"POLICY_ID": ["recall"], "ADMISSION_DATE": ["missing_support"]})


class QualityHoldoutTests(unittest.TestCase):
    def _write_holdout(self, path, rows, **metadata):
        files = {}
        for task, examples in rows.items():
            name = f"test-{task}.jsonl"
            data = "".join(json.dumps(row) + "\n" for row in examples).encode()
            (path / name).write_bytes(data)
            files[name] = {"rows": len(examples), "bytes": len(data), "sha256": sha256(data).hexdigest()}
        manifest = {"schema_version": 1, "split": "test", "synthetic_only": True, "files": files, **metadata}
        stamp = json.dumps(manifest).encode()
        (path / "manifest.json").write_bytes(stamp)
        return sha256(stamp).hexdigest()

    def test_verifies_pinned_manifest_and_jsonl_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            rows = _fixture()
            digest = self._write_holdout(path, rows, source_by_family={"one": "source-a", "two": "source-b"})
            self.assertEqual(_read_holdout(path, digest), (rows, {"one": "source-a", "two": "source-b"}))
            with self.assertRaisesRegex(ValueError, "pinned SHA-256"):
                _read_holdout(path, "f" * 64)
            (path / "test-rank.jsonl").write_text("{}\n")
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                _read_holdout(path, digest)

    def test_rejects_groups_without_a_challenging_candidate(self):
        rows = _fixture()
        rows["rank"][1]["relevant"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            digest = self._write_holdout(path, rows)
            with self.assertRaisesRegex(ValueError, "relevant and an irrelevant"):
                _read_holdout(path, digest)


class HostedEvaluationTests(unittest.TestCase):
    def test_runpod_guard_checks_workspace_and_provider_id(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "hosted CPU Pod"):
                _require_host("runpod-cpu", ["/workspace/checkpoint"], "/tmp/holdout")
        with patch.dict(os.environ, {"RUNPOD_POD_ID": "test-pod"}), patch("os.path.ismount", return_value=True):
            _require_host("runpod-cpu", ["/workspace/checkpoint"], "/tmp/holdout")
            with self.assertRaisesRegex(RuntimeError, "inside the mounted"):
                _require_host("runpod-cpu", ["/tmp/checkpoint"], "/tmp/holdout")
            with self.assertRaisesRegex(RuntimeError, "Extract the holdout"):
                _require_host("runpod-cpu", ["/workspace/checkpoint"], "/workspace/holdout")

    def test_rejects_a_visible_gpu_before_opening_a_checkpoint(self):
        fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False, device_count=lambda: 1))
        module = "specialists.evaluate_quality_run"
        with patch.dict(sys.modules, {"torch": fake_torch}), patch(f"{module}._require_host"), \
                patch(f"{module}._read_holdout", return_value=({}, {})), patch(
                    f"{module}.load_verified_checkpoint") as loader:
            with self.assertRaisesRegex(RuntimeError, "CPU-only"):
                evaluate("candidate", "a" * 64, "b" * 64, "holdout", "c" * 64)
            loader.assert_not_called()

    def test_each_checkpoint_gets_its_own_training_provenance_and_config(self):
        rows = _fixture()
        candidate = {"training": {"batch_size": 2, "structured_objectives": True}}
        prior = {"training": {"batch_size": 3}}
        fake_torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: False, device_count=lambda: 0),
            __version__="fake", device=lambda value: value, set_num_threads=Mock(),
        )
        module = "specialists.evaluate_quality_run"
        result = _perfect_report(rows)
        with patch.dict(sys.modules, {"torch": fake_torch}), patch(f"{module}._require_host"), \
                patch(f"{module}._read_holdout", return_value=(rows, {"one": "s", "two": "s"})), \
                patch(f"{module}._encode_rows", return_value="encoded"), \
                patch(f"{module}._run_baseline", return_value=result), \
                patch(f"{module}.load_verified_checkpoint", side_effect=[(candidate, {}), (prior, {})]) as load, \
                patch(f"{module}.restore_models", side_effect=["candidate", "reference"]), \
                patch(f"{module}._evaluate", return_value=result) as score:
            report = evaluate(
                "candidate", "a" * 64, "b" * 64, "holdout", "c" * 64,
                reference="prior", reference_sha256="d" * 64, reference_train_manifest_sha256="e" * 64,
                candidate_config_sha256="f" * 64,
            )
        self.assertEqual([call.args[2] for call in load.call_args_list], ["b" * 64, "e" * 64])
        self.assertEqual([call.kwargs["config_sha256"] for call in load.call_args_list], ["f" * 64, None])
        self.assertEqual([call.args[3] for call in score.call_args_list], [2, 3])
        self.assertEqual([call.kwargs["structured"] for call in score.call_args_list], [True, False])
        self.assertTrue(report["reports"]["candidate"]["synthetic_target_met"])
        self.assertFalse(report["production_accuracy_established"])


class CheckpointProvenanceTests(unittest.TestCase):
    def test_versioned_feature_spec_and_independent_config_pin(self):
        cfg_path = Path(__file__).resolve().parents[1] / "config.json"
        config = json.loads(cfg_path.read_text())
        config["rank"].update(features=256, feature_version=2)
        config["span"]["contextual_values"] = True
        fingerprints = {"config_sha256": "a" * 64, "dataset_manifest_sha256": "b" * 64}
        weights = {task: f"{task}-test-bytes".encode() for task in ("span", "rank")}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            run = path / "run"
            run.mkdir()
            entries = {}
            for task, data in weights.items():
                name = f"{task}.pt"
                (run / name).write_bytes(data)
                entries[task] = {"path": name, "bytes": len(data), "sha256": sha256(data).hexdigest()}
            metadata = {
                "schema_version": 1, "config": config, "architectures": ARCHITECTURES,
                "features": _feature_spec(config), "parameters": parameter_estimate(config),
                "input_fingerprints": fingerprints, "weights": entries,
            }
            (run / "metadata.json").write_text(json.dumps(metadata))
            (run / "reload.json").write_text(json.dumps(
                {"passed": True, "predictions_match": True, "input_fingerprints": fingerprints}))
            write_manifest(run, metadata={
                "kind": "remote_specialist_run", "trained": True,
                "dataset_manifest_sha256": fingerprints["dataset_manifest_sha256"],
            })
            archive = path / "fixture.tar.gz"
            digest = package_directory(run, archive)["sha256"]
            self.assertEqual(load_verified_checkpoint(
                archive, digest, "b" * 64, config_sha256="a" * 64), (config, weights))
            with self.assertRaisesRegex(ValueError, "provenance"):
                load_verified_checkpoint(archive, digest, "b" * 64, config_sha256="c" * 64)
