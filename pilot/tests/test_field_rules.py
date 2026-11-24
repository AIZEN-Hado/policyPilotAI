import unittest

from pilot.field_rules import extract_review_fields


def doc(kind, text, **page_data):
    return {
        "id": kind, "filename": f"{kind}.pdf", "kind": kind,
        "pages": [{"page": 2, "text": text, **page_data}],
    }


class ReviewFieldTests(unittest.TestCase):
    def test_schedule_extracts_indian_amount_and_exact_source_offsets(self):
        text = "Member / policy: SYN-M303-A / SYN-P303\nSum insured: INR 10,00,000.00"
        fields = extract_review_fields([doc("schedule", text)])["fields"]
        self.assertEqual(fields["POLICY_ID"]["value"], "SYN-P303")
        self.assertEqual(fields["MEMBER_ID"]["value"], "SYN-M303-A")
        self.assertEqual(fields["SUM_INSURED"]["value"], "1000000.00")
        item = fields["SUM_INSURED"]["candidates"][0]
        self.assertEqual(item["page"], 2)
        self.assertEqual(item["filename"], "schedule.pdf")
        self.assertEqual(text[item["start_offset"]:item["end_offset"]], item["source_text"])

    def test_date_formats_agree_across_documents(self):
        result = extract_review_fields([
            doc("claim_form", "Admission: 2026-10-13; discharge date: 16/10/2026"),
            doc("discharge", "Date of admission: 13 Oct 2026\nDischarged: October 16, 2026"),
        ])
        self.assertEqual(result["fields"]["ADMISSION_DATE"]["value"], "2026-10-13")
        self.assertEqual(result["fields"]["DISCHARGE_DATE"]["value"], "2026-10-16")
        self.assertEqual(len(result["fields"]["ADMISSION_DATE"]["candidates"]), 2)

    def test_conflicting_dates_remain_cited_without_picking_a_value(self):
        fields = extract_review_fields([
            doc("claim_form", "Admission: 2026-10-02"),
            doc("discharge", "Admission: 2026-10-03"),
        ])["fields"]
        field = fields["ADMISSION_DATE"]
        self.assertEqual(field["status"], "conflicting")
        self.assertIsNone(field["value"])
        self.assertEqual([c["source_text"] for c in field["candidates"]], ["2026-10-02", "2026-10-03"])

    def test_invalid_ambiguous_and_ocr_dates_need_verification(self):
        for raw, extra, reason in [
            ("2026-02-30", {}, "invalid_calendar_date"),
            ("02/03/2026", {}, "ambiguous_numeric_date"),
            ("2026-10-02", {"method": "ocr"}, "check_against_original"),
        ]:
            with self.subTest(raw=raw, extra=extra):
                fields = extract_review_fields([doc("discharge", f"Admission: {raw}", **extra)])["fields"]
                field = fields["ADMISSION_DATE"]
                self.assertEqual(field["status"], "needs_verification")
                self.assertIsNone(field["value"])
                self.assertIn(reason, field["candidates"][0]["review_reasons"])

    def test_unrelated_dates_and_amounts_do_not_fill_fields(self):
        fields = extract_review_fields([
            doc("bill", "Printing date: 2026-10-13\nRoom charge: INR 5,000\nTotal: INR 12,500"),
            doc("policy", "Old room limit: INR 8,000\nSum insured: INR 9,99"),
        ])["fields"]
        self.assertTrue(all(field["status"] == "missing" for field in fields.values()))

    def test_endorsement_is_a_candidate_for_review(self):
        fields = extract_review_fields([
            doc("endorsement", "Room limit: Rs. 4,500.25 per day"),
        ])["fields"]
        field = fields["ROOM_LIMIT"]
        self.assertEqual(field["status"], "needs_verification")
        self.assertEqual(field["candidates"][0]["value"], "4500.25")
        self.assertIsNone(field["value"])

    def test_inconsistent_date_order_requires_review(self):
        report = extract_review_fields([
            doc("discharge", "Admission: 2026-10-03\nDischarge: 2026-10-02"),
        ])
        self.assertIn("discharge_before_admission", report["issues"])
        for label in ("ADMISSION_DATE", "DISCHARGE_DATE"):
            self.assertEqual(report["fields"][label]["status"], "needs_verification")
            self.assertIsNone(report["fields"][label]["value"])
