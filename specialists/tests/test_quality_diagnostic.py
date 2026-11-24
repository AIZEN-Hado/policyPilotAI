from collections import defaultdict
import unittest

from specialists.contracts import validate_row
from specialists.diagnose_quality_validation import span_candidate_coverage, span_row_outcomes
from specialists.features import BIO_IDS, BIO_TAGS, tokenize_with_offsets
from specialists.validation_rank_probe import rank_probe_rows


class QualityDiagnosticTests(unittest.TestCase):
    def test_distinguishes_rejection_from_a_competing_value(self):
        text = "Plan PX-100. Prior QX-300."
        offsets = [(left, right) for _, left, right in tokenize_with_offsets(text)]
        row = {"text": text, "spans": [{"label": "POLICY_ID", "start": 5, "end": 11, "value": "PX-100"}]}
        encoded = {"offsets": offsets}
        logits = [[0.0] * len(BIO_TAGS) for _ in offsets]
        self.assertEqual(span_row_outcomes(row, encoded, logits), [("POLICY_ID", "null_score_won")])

        score = BIO_IDS["B-POLICY_ID"]
        logits[1][score] = 3.0
        logits[6][score] = 9.0
        self.assertEqual(set(span_row_outcomes(row, encoded, logits)),
                         {("POLICY_ID", "another_value_selected"), ("POLICY_ID", "false_positive")})
        self.assertEqual(span_candidate_coverage([(row, encoded)]),
                         {"POLICY_ID": {"gold": 1, "available": 1, "missing": 0}})

    def test_distinguishes_a_missing_candidate(self):
        row = {"text": "Plan ABC.", "spans": [{"label": "POLICY_ID", "start": 5, "end": 8, "value": "ABC"}]}
        encoded = {"offsets": [(0, 4), (5, 8), (8, 9)]}
        logits = [[0.0] * len(BIO_TAGS) for _ in encoded["offsets"]]
        self.assertEqual(span_row_outcomes(row, encoded, logits), [("POLICY_ID", "no_complete_candidate")])

    def test_probe_groups_have_distinct_questions_and_hard_negatives(self):
        rows = rank_probe_rows()
        groups = defaultdict(list)
        for row in rows:
            validate_row(row)
            groups[row["query"]].append(row)
        self.assertEqual(len(groups), 8)
        self.assertEqual(len({row["id"] for row in rows}), 24)
        for group in groups.values():
            self.assertEqual(sorted(row["relevant"] for row in group), [False, False, True])
