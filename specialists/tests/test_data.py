from collections import defaultdict
from copy import deepcopy
import re
import unittest

from specialists.contracts import SPAN_LABELS, TOKEN_PATTERN, validate_corpus, validate_row
from specialists.data import DEFAULT_SEED, generate_corpus


class SyntheticCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = generate_corpus()

    def test_generation_is_deterministic_and_seeded(self):
        self.assertEqual(self.corpus, generate_corpus(DEFAULT_SEED))
        alternative = generate_corpus(DEFAULT_SEED + 1)
        self.assertNotEqual(self.corpus, alternative)
        self.assertEqual(
            [row["id"] for row in self.corpus["train"]["span"]],
            [row["id"] for row in alternative["train"]["span"]],
        )
        with self.assertRaisesRegex(ValueError, "integer"):
            generate_corpus(True)

    def test_spans_align_to_tokens_and_reproduce_source_text(self):
        for split, tasks in self.corpus.items():
            coverage = set()
            for row in tasks["span"]:
                tokens = list(TOKEN_PATTERN.finditer(row["text"]))
                for span in row["spans"]:
                    start, end = span["start"], span["end"]
                    with self.subTest(split=split, row_id=row["id"], label=span["label"]):
                        enclosed = [token for token in tokens if start <= token.start() < end]
                        self.assertEqual(enclosed[0].start(), start)
                        self.assertEqual(enclosed[-1].end(), end)
                        self.assertEqual(row["text"][start:end], span["value"])
                        self.assertNotIn(span["label"], row["text"])
                    coverage.add(span["label"])
                if row["kind"] == "receipt":
                    self.assertEqual(row["spans"], [])
            self.assertEqual(coverage, set(SPAN_LABELS))

    def test_split_case_family_and_text_isolation(self):
        seen = {key: set() for key in ("id", "case_id", "family", "text")}
        expected = {
            "train": (4, 768, 512),
            "validation": (2, 384, 256),
            "test": (2, 384, 256),
        }
        for split, tasks in self.corpus.items():
            rows = tasks["span"] + tasks["rank"]
            split_values = {key: {row[key] for row in rows} for key in seen}
            self.assertEqual(
                (len(split_values["family"]), len(tasks["span"]), len(tasks["rank"])),
                expected[split],
            )
            self.assertEqual(len(split_values["id"]), len(rows))
            for key, values in split_values.items():
                self.assertFalse(seen[key] & values, (split, key))
                seen[key].update(values)

    def test_explicit_rank_negatives_and_format_distractors(self):
        groups = defaultdict(list)
        for tasks in self.corpus.values():
            for row in tasks["rank"]:
                groups[row["case_id"], row["query"]].append(row)
        comparisons = set()
        for rows in groups.values():
            self.assertCountEqual([row["relevant"] for row in rows], [True, False])
            self.assertEqual(len({row["kind"] for row in rows}), 1)
            if rows[0]["kind"] == "policy":
                amounts = {
                    row["relevant"]: int(re.search(r"INR ([\d,]+)", row["text"])[1].replace(",", ""))
                    for row in rows
                }
                comparisons.add(amounts[True] > amounts[False])
        self.assertEqual(comparisons, {True, False})
        negated = [row for row in self.corpus["train"]["rank"] if "does not set the limit" in row["text"]]
        self.assertTrue(negated)
        self.assertTrue(all(row["relevant"] is False for row in negated))

        claim_forms = [row for row in self.corpus["train"]["span"] if row["kind"] == "claim_form"]
        self.assertTrue(any(row["text"].count("MB-") > 1 for row in claim_forms))
        for row in claim_forms:
            self.assertEqual(sum(span["label"].endswith("_DATE") for span in row["spans"]), 2)

    def test_rejects_invalid_rank_relevance_or_missing_class(self):
        row = deepcopy(self.corpus["train"]["rank"][0])
        row["relevant"] = 0
        with self.assertRaisesRegex(ValueError, "explicit boolean"):
            validate_row(row)
        del row["relevant"]
        with self.assertRaisesRegex(ValueError, "fields"):
            validate_row(row)

        data = deepcopy(self.corpus)
        first, second = data["train"]["rank"][:2]
        second["relevant"] = first["relevant"]
        with self.assertRaisesRegex(ValueError, "both relevance labels"):
            validate_corpus(data)

    def test_rejects_malformed_spans_and_non_synthetic_rows(self):
        row = self.corpus["train"]["span"][0]
        span = row["spans"][0]
        invalid = (
            ({**row, "synthetic": False}, "marked synthetic"),
            ({**row, "synthetic": 1}, "marked synthetic"),
            ({**row, "text": row["text"] + " ROOM_LIMIT"}, "annotation label"),
            ({**row, "spans": [{**span, "label": "unknown"}]}, "Unknown span label"),
            ({**row, "spans": [{**span, "start": True}]}, "offsets must be integers"),
            ({**row, "spans": [{**span, "end": len(row["text"]) + 1}]}, "within the source text"),
            ({**row, "spans": [{**span, "start": span["start"] + 1}]}, "token boundaries"),
            ({**row, "spans": [{**span, "value": "different"}]}, "exact source slice"),
            ({**row, "spans": [span, span]}, "Repeated span label"),
            ({**row, "spans": [span, {**span, "label": "SUM_INSURED"}]}, "nonoverlapping"),
        )
        for candidate, message in invalid:
            with self.subTest(error=message), self.assertRaisesRegex(ValueError, message):
                validate_row(candidate)

    def test_rejects_duplicate_ids_and_split_leakage(self):
        for field, message in (
            ("id", "Repeated row ID"),
            ("family", "multiple splits"),
            ("case_id", "multiple splits or families"),
        ):
            with self.subTest(field=field):
                data = deepcopy(self.corpus)
                data["test"]["span"][0][field] = data["train"]["span"][0][field]
                with self.assertRaisesRegex(ValueError, message):
                    validate_corpus(data)


if __name__ == "__main__":
    unittest.main()
