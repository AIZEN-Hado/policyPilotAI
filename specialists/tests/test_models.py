import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from specialists.features import (
    BIO_IDS, BIO_TAGS, PAD_ID, decode_spans, encode_span, ranking_features, tokenize_with_offsets,
)
from specialists.models import parameter_estimate
from specialists.runtime import _load_torch


ROOT = Path(__file__).resolve().parents[2]


def configuration():
    return json.loads((ROOT / "specialists" / "config.json").read_text(encoding="utf-8"))


class CudaStartupTests(unittest.TestCase):
    def test_fresh_worker_initializes_allocator_before_resetting_stats(self):
        initialized = False

        def init():
            nonlocal initialized
            initialized = True

        def reset_peak_memory_stats(device):
            if not initialized:
                raise RuntimeError("Invalid device argument")
            self.assertEqual(device, "cuda:0")

        torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: True, init=init,
                                 reset_peak_memory_stats=reset_peak_memory_stats),
            manual_seed=lambda seed: None,
            backends=SimpleNamespace(cudnn=SimpleNamespace()),
            device=lambda name: name,
        )
        with patch.dict(sys.modules, {"torch": torch}):
            self.assertEqual(_load_torch({"seed": 1}), (torch, "cuda:0"))


class ParameterBudgetTests(unittest.TestCase):
    def test_default_fp32_parameter_counts(self):
        estimate = parameter_estimate(configuration())
        self.assertEqual(
            estimate,
            {"span": 618_669, "rank": 3_137, "total": 621_806, "fp32_bytes": 2_487_224},
        )
        self.assertEqual(len(BIO_TAGS), 13)

    def test_rejects_configs_that_violate_padding_or_budgets(self):
        config = configuration()
        config["span"]["char_kernel"] = 2
        with self.assertRaisesRegex(ValueError, "must be odd"):
            parameter_estimate(config)

        config = configuration()
        config["max_weight_bytes"] = 1_000_000
        with self.assertRaisesRegex(ValueError, "weight budget"):
            parameter_estimate(config)

        config = configuration()
        config["span"]["word_hash_buckets"] = 100_000
        config["max_parameters"] = 10_000_000
        config["max_weight_bytes"] = 100_000_000
        with self.assertRaisesRegex(ValueError, "parameter"):
            parameter_estimate(config)


class FeatureTests(unittest.TestCase):
    def test_bio_roundtrip_preserves_unicode_and_spacing(self):
        text = "Bénéficiaire AB-009\nMaximum ₹  9,000."
        spans = []
        for name, value in (("MEMBER_ID", "AB-009"), ("ROOM_LIMIT", "₹  9,000")):
            start = text.index(value)
            spans.append({"label": name, "start": start, "end": start + len(value), "value": value})
        encoded = encode_span({"text": text, "spans": spans}, configuration()["span"])
        for token, start, end in tokenize_with_offsets(text):
            self.assertEqual(token, text[start:end])
        self.assertNotIn(PAD_ID, encoded["word_ids"])
        self.assertTrue(all(PAD_ID not in token for token in encoded["char_ids"]))
        self.assertEqual(decode_spans(text, encoded["offsets"], encoded["tags"]), spans)

    def test_invalid_bio_continuations_discard_corrupted_spans(self):
        text = "orphan AB-009 other REF"
        offsets = [(start, end) for _, start, end in tokenize_with_offsets(text)]
        tags = ["I-SUM_INSURED", "B-MEMBER_ID", "I-MEMBER_ID", "I-ROOM_LIMIT", "I-MEMBER_ID", "B-POLICY_ID"]
        self.assertEqual(
            decode_spans(text, offsets, [BIO_IDS[tag] for tag in tags]),
            [{"label": "POLICY_ID", "start": 20, "end": 23, "value": "REF"}],
        )

    def test_encode_rejects_partial_or_truncated_inputs(self):
        config = configuration()["span"]
        with self.assertRaisesRegex(ValueError, "exceeds 2 tokens"):
            encode_span({"text": "one two three", "spans": []}, {**config, "max_tokens": 2})
        with self.assertRaisesRegex(ValueError, "exceeding 2 characters"):
            encode_span({"text": "one", "spans": []}, {**config, "max_chars_per_token": 2})
        with self.assertRaisesRegex(ValueError, "token boundaries"):
            encode_span({"text": "ABC", "spans": [{"label": "MEMBER_ID", "start": 0, "end": 2}]}, config)

    def test_rank_vector_is_stable_and_uses_query_and_kind(self):
        config = configuration()["rank"]
        query = "current inpatient room limit"
        text = "The active ceiling for inpatient rooms is ₹8,000."
        features = ranking_features(query, text, "policy", config)
        self.assertEqual(len(features), config["features"])
        self.assertTrue(all(type(value) is float and math.isfinite(value) for value in features))
        self.assertEqual(features, ranking_features(query, text, "policy", config))
        self.assertNotEqual(features, ranking_features("required paperwork", text, "policy", config))
        self.assertNotEqual(features, ranking_features(query, text, "bill", config))


class RemoteGuardTests(unittest.TestCase):
    def test_local_runtime_stops_before_importing_torch_or_reading_data(self):
        code = """
import sys
from importlib.abc import MetaPathFinder

class BlockTorch(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'torch' or fullname.startswith('torch.'):
            raise AssertionError('Local runtime attempted a torch import')

sys.meta_path.insert(0, BlockTorch())
from specialists.runtime import STAGES, run_stage
for stage in STAGES:
    try:
        run_stage(stage, None, 'absent-data', 'absent-output')
    except ValueError as exc:
        assert 'remote' in str(exc).lower(), exc
    else:
        raise AssertionError(f'Local runtime let {stage} execute')
assert 'torch' not in sys.modules
"""
        environment = {name: os.environ[name] for name in ("PATH", "LANG", "LC_ALL") if name in os.environ}
        result = subprocess.run(
            [sys.executable, "-B", "-c", code], cwd=ROOT,
            env=environment, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class InputBindingTests(unittest.TestCase):
    def test_source_and_dataset_fingerprints_bind_the_verified_bundle(self):
        from specialists.artifacts import write_manifest
        from specialists.runtime import (
            CONFIG_FINGERPRINT_ENV, CONFIG_PATH, DATA_FILES, DATA_FINGERPRINT_ENV, DATA_PATH, _load_inputs,
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / CONFIG_PATH
            config_path.parent.mkdir(parents=True)
            config_bytes = json.dumps(configuration()).encode()
            config_path.write_bytes(config_bytes)
            data = root / DATA_PATH
            data.mkdir(parents=True)
            row = b'{}\n'
            row_hash = hashlib.sha256(row).hexdigest()
            for name in DATA_FILES:
                (data / name).write_bytes(row)
            files = {name: {"rows": 1, "sha256": row_hash, "bytes": len(row)} for name in DATA_FILES}
            manifest = {"schema_version": 1, "synthetic_only": True, "files": files}
            manifest_bytes = json.dumps(manifest).encode()
            (data / "manifest.json").write_bytes(manifest_bytes)
            write_manifest(root)
            config_hash = hashlib.sha256(config_bytes).hexdigest()
            manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
            fingerprints = {CONFIG_FINGERPRINT_ENV: config_hash, DATA_FINGERPRINT_ENV: manifest_hash}
            with patch.dict(os.environ, fingerprints):
                parsed, _, receipt = _load_inputs(root, config_path, data)
                self.assertEqual(parsed, configuration())
                self.assertEqual(receipt, {
                    "config_sha256": config_hash,
                    "dataset_manifest_sha256": manifest_hash,
                    "files": {name: row_hash for name in DATA_FILES},
                })
                with self.assertRaisesRegex(ValueError, "verified runtime source"):
                    _load_inputs(root, root / "other.json", data)
                config_path.write_bytes(config_bytes + b"\n")
                write_manifest(root)
                with self.assertRaisesRegex(ValueError, "launcher fingerprints"):
                    _load_inputs(root, config_path, data)

    def test_rejects_changed_row_bytes_before_json_parsing(self):
        from specialists.runtime import _read_rows

        original = b'{"a":0}\n'
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "train-span.jsonl"
            path.write_bytes(b"invalid\n")
            expected = {"sha256": hashlib.sha256(original).hexdigest(), "bytes": len(original), "rows": 1}
            with self.assertRaisesRegex(ValueError, "fingerprint or size changed"):
                _read_rows(path, "span", expected)


if __name__ == "__main__":
    unittest.main()
