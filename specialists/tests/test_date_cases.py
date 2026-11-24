from collections import Counter
import unittest

from specialists.contracts import validate_row
from specialists.date_cases import date_training_rows
from specialists.features import tokenize_with_offsets
from specialists.structured import candidate_supervision


class DateTrainingRowsTests(unittest.TestCase):
    def test_current_stays_have_exact_candidates_and_decoys(self):
        rows = date_training_rows()
        self.assertEqual(rows, date_training_rows())
        self.assertEqual(len({row["id"] for row in rows}), 384)
        self.assertEqual(len({row["family"] for row in rows}), 12)
        self.assertEqual(Counter(span["label"] for row in rows for span in row["spans"]),
                         {"ADMISSION_DATE": 288, "DISCHARGE_DATE": 256})
        self.assertEqual(sum(not row["spans"] for row in rows), 64)
        for row in rows:
            with self.subTest(row=row["id"]):
                validate_row(row)
                offsets = [(start, end) for _, start, end in tokenize_with_offsets(row["text"])]
                choices, targets = candidate_supervision(row, {"offsets": offsets})
                self.assertGreater(len(choices["ADMISSION_DATE"]), len(row["spans"]))
                for label in ("ADMISSION_DATE", "DISCHARGE_DATE"):
                    self.assertEqual(bool(targets[label]), any(span["label"] == label for span in row["spans"]))
