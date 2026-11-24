import unittest

from specialists.contracts import SPAN_LABELS
from specialists.evaluate_precision_run import target_met
from specialists.features import BIO_IDS, BIO_TAGS, decode_spans, tokenize_with_offsets
from specialists.runtime import _rank_report
from specialists.structured import candidate_supervision, rank_groups, select_tags, value_candidates


class StructuredSpecialistTests(unittest.TestCase):
    def test_complete_dates_include_dates_before_sentence_punctuation(self):
        text = "Registered: 01.05.2034. Entry: May 2, 2034. Exit: 5 May 2034."
        value = "May 2, 2034"
        start = text.index(value)
        offsets = [(left, right) for _, left, right in tokenize_with_offsets(text)]
        row = {
            "id": "date-example", "text": text,
            "spans": [{"label": "ADMISSION_DATE", "start": start, "end": start + len(value), "value": value}],
        }
        choices, targets = candidate_supervision(row, {"offsets": offsets})
        self.assertEqual(len(choices["ADMISSION_DATE"]), 3)
        left, right = choices["ADMISSION_DATE"][targets["ADMISSION_DATE"] - 1]
        self.assertEqual(text[offsets[left][0]:offsets[right][1]], value)
        self.assertEqual(targets["DISCHARGE_DATE"], 0)

        logits = [[0.0] * len(BIO_TAGS) for _ in offsets]
        logits[left][BIO_IDS["B-ADMISSION_DATE"]] = 9.0
        # Standalone token argmax would terminate the field immediately.
        tags = select_tags(logits, choices)
        self.assertEqual(decode_spans(text, offsets, tags), row["spans"])

    def test_skips_date_fragments_and_allows_null_fields(self):
        text = "Entry: 2034-05-01. Ceiling: INR 1,20,000. Cover: P-401/M2."
        offsets = [(left, right) for _, left, right in tokenize_with_offsets(text)]
        choices = value_candidates(text, offsets)
        values = {label: [text[offsets[left][0]:offsets[right][1]] for left, right in bounds]
                  for label, bounds in choices.items()}
        self.assertEqual(values["ADMISSION_DATE"], ["2034-05-01"])
        self.assertIn("INR 1,20,000", values["ROOM_LIMIT"])
        self.assertIn("P-401/M2", values["POLICY_ID"])
        self.assertNotIn("2034-05-01", values["POLICY_ID"])
        logits = [[0.0] * len(BIO_TAGS) for _ in offsets]
        self.assertEqual(select_tags(logits, choices), [0] * len(offsets))

    def test_grouped_training_and_strict_ties(self):
        examples = [({"id": "one", "case_id": "case", "query": "same", "relevant": True}, []),
                    ({"id": "two", "case_id": "case", "query": "same", "relevant": False}, [])]
        self.assertEqual(rank_groups(examples), [examples])
        with self.assertRaises(ValueError):
            rank_groups(examples[:1])
        metrics = _rank_report(examples, [0.8, 0.8])["metrics"]
        self.assertEqual(metrics["group_top1_accuracy"], 0.5)
        self.assertEqual(metrics["strict_group_top1_accuracy"], 0.0)

    def test_target_checks_every_field_and_requires_supported_labels(self):
        exact = {label: {"support": 100, "precision": 0.99, "recall": 0.99} for label in SPAN_LABELS}
        span = {"exact_span_by_label": exact}
        rank = {"strict_group_top1_accuracy": 0.99}
        self.assertTrue(target_met(span, rank))
        exact["POLICY_ID"]["recall"] = 0.98
        self.assertFalse(target_met(span, rank))
        exact["POLICY_ID"].update(support=0, recall=0.99)
        self.assertFalse(target_met(span, rank))
