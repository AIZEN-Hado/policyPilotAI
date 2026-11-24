import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from specialists.features import feature_spec, ranking_features, tokenize_with_offsets
from specialists.self_learning import confident_winner, load_pool, perturb_span


class SelfLearningTests(unittest.TestCase):
    def test_confidence_requires_margin_and_probability(self):
        self.assertEqual(confident_winner([0.0, 7.0, 1.0], 0.9, 1.5), 1)
        self.assertIsNone(confident_winner([0.0, 7.0, 7.0], 0.9, 1.5))
        self.assertIsNone(confident_winner([0.0, 2.0, 0.0, 0.0], 0.9, 1.5))
        with self.assertRaises(ValueError):
            confident_winner([0.0, float('nan')], 0.9, 1.5)

    def test_span_variation_preserves_token_coordinates(self):
        text = 'Member ID: SYN-M123; Room cap: INR 7,500. Draft amount: INR 8,500.'
        variant = perturb_span(text)
        self.assertNotEqual(text, variant)
        self.assertEqual(tokenize_with_offsets(text), tokenize_with_offsets(variant))

    def test_pool_rejects_supervision_even_when_fingerprint_is_valid(self):
        row = {"id": "u-1", "case_id": "u-1", "family": "unlabeled", "task": "span", "synthetic": True,
               "kind": "schedule", "text": "An unlabeled synthetic policy", "spans": []}
        data = (json.dumps(row) + '\n').encode()
        inventory = {"span": {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "rows": 1},
                     "rank": {}}
        settings = {"pool": inventory, "rounds": 2, "epochs": 3,
                    "span_probability": 0.9, "rank_probability": 0.9, "margin": 1.5}
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory) / 'unlabeled'
            pool.mkdir()
            (pool / 'span.jsonl').write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'contains supervision'):
                load_pool(Path(directory), settings, {}, {})

    def test_rank_authority_features_distinguish_current_and_prior(self):
        config = {'features': 448, 'feature_version': 3}
        names = feature_spec(config)['rank_scalar_features']
        feature = names.index('authority_superseded_match')
        q = 'Find the outgoing room rate.'
        prior = ranking_features(q, 'The expired room rate applies here.', 'policy', config)
        current = ranking_features(q, 'The operative room rate applies here.', 'policy', config)
        self.assertEqual(len(prior), config['features'])
        self.assertEqual((prior[feature], current[feature]), (1.0, 0.0))
