from itertools import combinations
from random import Random
import unittest

from specialists.contracts import SPAN_LABELS
from specialists.features import BIO_IDS, BIO_TAGS
from specialists.joint_selection import best_assignments, joint_tags
from specialists.structured import select_tags


class JointSelectionTests(unittest.TestCase):
    def test_joint_assignment_uses_two_compatible_alternatives(self):
        labels = {"POLICY_ID": [(0, 1), (3, 3)], "MEMBER_ID": [(1, 2)]}
        logits = [[0.0] * len(BIO_TAGS) for _ in range(4)]
        logits[0][BIO_IDS["B-POLICY_ID"]] = 16
        logits[3][BIO_IDS["B-POLICY_ID"]] = 5
        logits[1][BIO_IDS["B-MEMBER_ID"]] = 12
        naive = select_tags(logits, labels)
        tags, score = joint_tags(logits, labels)
        self.assertEqual(naive[0], BIO_IDS["B-POLICY_ID"])
        self.assertEqual(tags, [0, BIO_IDS["B-MEMBER_ID"], BIO_IDS["I-MEMBER_ID"], BIO_IDS["B-POLICY_ID"]])
        self.assertEqual(score, 11)

    def test_solver_matches_brute_force_on_varied_small_inputs(self):
        rng = Random(20261122)
        for _ in range(32):
            scored = []
            for _ in range(7):
                left = rng.randrange(5)
                scored.append((left, left + rng.randrange(3), rng.choice(SPAN_LABELS[:3]), rng.randrange(-1, 7)))
            objective, assignment = best_assignments(scored)
            expected = 0
            for size in range(1, len(scored) + 1):
                for group in combinations(scored, size):
                    labels = {label for _, _, label, _ in group}
                    ordered = sorted(group)
                    if len(labels) != size or any(a[1] >= b[0] for a, b in zip(ordered, ordered[1:])):
                        continue
                    expected = max(expected, sum(item[-1] for item in group))
            self.assertEqual(objective, expected)
            self.assertEqual(len({field for _, _, field in assignment}), len(assignment))
            self.assertTrue(all(a[1] < b[0] for a, b in zip(assignment, assignment[1:])))

    def test_zero_and_nonpositive_scores_remain_unassigned(self):
        self.assertEqual(best_assignments([(0, 0, "POLICY_ID", 0), (1, 1, "MEMBER_ID", -1)]), (0.0, ()))
