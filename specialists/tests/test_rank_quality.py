from collections import Counter, defaultdict
import unittest

from specialists.contracts import validate_row
from specialists.features import RANK_V2_MIN_FEATURES, RANK_V2_SCALAR_NAMES, feature_spec, ranking_features
from specialists.rank_quality_cases import rank_training_rows


class RankingQualityTests(unittest.TestCase):
    def test_legacy_feature_contract_remains_default(self):
        kind = "policy"
        query = "Which ward payments apply?"
        text = "The accepted payment for a covered hospital stay is INR 500."
        config = {"features": 96}
        self.assertEqual(feature_spec(), feature_spec({"feature_version": 1}))
        self.assertEqual(
            ranking_features(query, text, kind, config),
            ranking_features(query, text, kind, {**config, "feature_version": 1}),
        )
        self.assertNotIn("rank_feature_version", feature_spec())

    def test_version_two_tracks_concepts_and_scope_changes(self):
        query = "Which ceiling is payable for a ward room overnight?"
        active = "Under this policy the covered inpatient bed charge is capped at INR 500 per night."
        old = "An obsolete policy named a room ceiling for inpatient rooms at INR 500 per night."
        config = {"feature_version": 2, "features": 384}
        active_values = ranking_features(query, active, "policy", config)
        old_values = ranking_features(query, old, "policy", config)
        self.assertEqual(len(active_values), 384)
        self.assertEqual(len(old_values), 384)
        self.assertEqual(active_values, ranking_features(query, active, "policy", config))
        active_fields = dict(zip(RANK_V2_SCALAR_NAMES, active_values))
        old_fields = dict(zip(RANK_V2_SCALAR_NAMES, old_values))
        self.assertEqual(active_fields["both_meaning_ward_room"], 1.0)
        self.assertEqual(active_fields["covered_daily_room_cap"], 1.0)
        self.assertEqual(active_fields["document_context_governing"], 1.0)
        self.assertEqual(old_fields["mismatch_context_outdated"], 1.0)
        historical_values = ranking_features("What did the expired policies cover?", old, "policy", config)
        historical_fields = dict(zip(RANK_V2_SCALAR_NAMES, historical_values))
        self.assertEqual(historical_fields["mismatch_context_outdated"], 0.0)
        self.assertEqual(feature_spec(config)["rank_scalar_features"], list(RANK_V2_SCALAR_NAMES))
        with self.assertRaises(ValueError):
            ranking_features(query, active, "policy", {**config, "features": RANK_V2_MIN_FEATURES - 1})

    def test_additional_groups_have_explicit_hard_negatives(self):
        rows = rank_training_rows()
        self.assertEqual(rows, rank_training_rows())
        self.assertEqual(len(rows), len({row["id"] for row in rows}))
        self.assertEqual(len({row["query"] for row in rows}), 36)
        groups = defaultdict(list)
        for row in rows:
            validate_row(row)
            groups[row["case_id"], row["query"]].append(row)
        self.assertEqual(len(groups), 216)
        self.assertEqual({len(items) for items in groups.values()}, {4})
        for items in groups.values():
            self.assertEqual(Counter(row["relevant"] for row in items), {True: 1, False: 3})
            self.assertEqual(len({row["kind"] for row in items}), 1)
            self.assertEqual(len({row["text"] for row in items}), 4)
