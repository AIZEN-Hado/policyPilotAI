from collections import Counter, defaultdict
import unittest

from specialists.contracts import SPAN_LABELS, validate_row
from specialists.joint_holdout_cases import holdout_rows


class JointHoldoutTests(unittest.TestCase):
    def test_exact_field_support_and_deterministic_rows(self):
        rows = holdout_rows()
        self.assertEqual(rows, holdout_rows())
        self.assertEqual(len(rows["span"]), 512)
        self.assertEqual(len({row["family"] for row in rows["span"]}), 8)
        self.assertEqual(Counter(span["label"] for row in rows["span"] for span in row["spans"]),
                         dict.fromkeys(SPAN_LABELS, 128))
        for row in rows["span"]:
            validate_row(row)

    def test_rank_groups_do_not_repeat_identical_passages(self):
        rows = holdout_rows()["rank"]
        groups = defaultdict(list)
        for row in rows:
            validate_row(row)
            groups[row["case_id"], row["query"]].append(row)
        self.assertEqual(len({query for _, query in groups}), 8)
        signatures = set()
        for (_, query), group in groups.items():
            self.assertEqual(sorted(row["relevant"] for row in group), [False, False, True])
            signature = (query, tuple(sorted((row["text"], row["relevant"]) for row in group)))
            self.assertNotIn(signature, signatures)
            signatures.add(signature)
