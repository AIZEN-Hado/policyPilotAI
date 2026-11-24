import json
from pathlib import Path
import unittest

from specialists.features import encode_span
from specialists.runtime import _encode_span
from specialists.span_context import encode_contextual_span


class ContextualSpanTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((Path(__file__).parents[1] / "config.json").read_bytes())["span"]

    def test_context_features_do_not_depend_on_annotations(self):
        text = "Present stay. Inpatient entry: 2034-02-01. Left: 2034-02-03."
        start = text.index("2034")
        row = {"kind": "claim_form", "text": text, "spans": []}
        labeled = {**row, "spans": [{"start": start, "end": start + 10, "label": "ADMISSION_DATE"}]}
        base = encode_contextual_span(row, self.config)
        gold = encode_contextual_span(labeled, self.config)
        for field in ("word_ids", "char_ids", "offsets"):
            self.assertEqual(base[field], gold[field])
        self.assertNotEqual(base["tags"], gold["tags"])
        self.assertEqual(gold["offsets"], encode_span(labeled, self.config)["offsets"])

    def test_equivalent_date_values_and_cues_have_stable_features(self):
        entry = {"kind": "discharge", "text": "Arrival 2034-02-01.", "spans": []}
        alternative = {"kind": "discharge", "text": "Entered 2036-03-11.", "spans": []}
        encoded = encode_contextual_span(entry, self.config)
        equivalent = encode_contextual_span(alternative, self.config)
        self.assertEqual(encoded["word_ids"], equivalent["word_ids"])
        self.assertEqual(encoded["char_ids"][1:], equivalent["char_ids"][1:])
        departure = {**entry, "text": "Discharge 2034-02-01."}
        self.assertNotEqual(encoded["char_ids"][1], encode_contextual_span(departure, self.config)["char_ids"][1])

    def test_runtime_uses_legacy_features_until_opted_in(self):
        row = {"kind": "discharge", "text": "Departure 2034-02-01.", "spans": []}
        self.assertEqual(_encode_span(row, self.config), encode_span(row, self.config))
        context = {**self.config, "contextual_values": True, "max_chars_per_token": 10}
        encoded = _encode_span(row, context)
        self.assertNotEqual(encoded["word_ids"], encode_span(row, self.config)["word_ids"])
        self.assertTrue(all(0 < len(value) <= 10 for value in encoded["char_ids"]))
