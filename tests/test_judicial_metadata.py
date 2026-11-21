"""Tests for pilot.judicial_metadata (task T-002).

All Arabic text below is synthetic. No real cases, courts or parties.
"""

import unittest

from pilot import extract_case_metadata as package_export
from pilot.judicial_metadata import extract_case_metadata

EMPTY = {"case_number": None, "case_year": None, "judgment_date": None}


class CaseNumberTests(unittest.TestCase):
    def test_lawsuit_arabic_indic_digits(self):
        result = extract_case_metadata("الدعوى رقم ١٢٣ لسنة ٢٠٢٤")
        self.assertEqual(result["case_number"], "123")
        self.assertEqual(result["case_year"], "2024")

    def test_appeal_western_digits(self):
        result = extract_case_metadata("الاستئناف رقم 456 لسنة 2025")
        self.assertEqual(result["case_number"], "456")
        self.assertEqual(result["case_year"], "2025")

    def test_extended_arabic_indic_digits(self):
        result = extract_case_metadata("الدعوى رقم ۷۸۹ لسنة ۲۰۲۳")
        self.assertEqual(result["case_number"], "789")
        self.assertEqual(result["case_year"], "2023")

    def test_mixed_digit_scripts_normalized(self):
        result = extract_case_metadata("الاستئناف رقم ١0٢ لسنة 2٠٢٥")
        self.assertEqual(result["case_number"], "102")
        self.assertEqual(result["case_year"], "2025")

    def test_case_number_without_year(self):
        result = extract_case_metadata("نظرت المحكمة الدعوى رقم ٣١ في جلستها")
        self.assertEqual(result["case_number"], "31")
        self.assertIsNone(result["case_year"])

    def test_year_not_four_digits_is_none(self):
        for text in ("الدعوى رقم ٥ لسنة ٢٤", "الدعوى رقم ٥ لسنة ٢٠٢٤٥",
                     "الدعوى رقم ٥ لسنة ٠٢٤٥"):
            with self.subTest(text=text):
                result = extract_case_metadata(text)
                self.assertEqual(result["case_number"], "5")
                self.assertIsNone(result["case_year"])

    def test_number_without_case_keyword_ignored(self):
        result = extract_case_metadata("القرار رقم ٩٩ لسنة ٢٠٢٠")
        self.assertEqual(result, EMPTY)

    def test_leading_zeros_preserved(self):
        result = extract_case_metadata("الدعوى رقم ٠٠٧ لسنة ٢٠٢١")
        self.assertEqual(result["case_number"], "007")


class JudgmentDateTests(unittest.TestCase):
    def test_arabic_indic_date_to_iso(self):
        result = extract_case_metadata("صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥")
        self.assertEqual(result["judgment_date"], "2025-03-15")

    def test_western_single_digit_day_and_month(self):
        result = extract_case_metadata("صدر هذا الحكم بتاريخ 5/7/2024")
        self.assertEqual(result["judgment_date"], "2024-07-05")

    def test_invalid_calendar_dates_are_none(self):
        for date in ("٣١/٠٢/٢٠٢٥", "29/02/2023", "00/01/2024", "15/13/2024",
                     "15/03/0000"):
            with self.subTest(date=date):
                result = extract_case_metadata("صدر الحكم بتاريخ " + date)
                self.assertIsNone(result["judgment_date"])

    def test_leap_day_valid(self):
        result = extract_case_metadata("صدر الحكم بتاريخ ٢٩/٠٢/٢٠٢٤")
        self.assertEqual(result["judgment_date"], "2024-02-29")

    def test_date_without_judgment_phrase_ignored(self):
        result = extract_case_metadata("قيدت الدعوى رقم ١ لسنة ٢٠٢٤ بتاريخ ٠١/٠١/٢٠٢٤")
        self.assertIsNone(result["judgment_date"])

    def test_malformed_date_ignored(self):
        for date in ("15/03/25", "15-03-2025", "123/03/2025", "15/03/2025/1"):
            with self.subTest(date=date):
                result = extract_case_metadata("صدر الحكم بتاريخ " + date)
                self.assertIsNone(result["judgment_date"])

    def test_first_valid_judgment_date_used(self):
        text = ("صدر الحكم بتاريخ ٣٠/٠٢/٢٠٢٥ ثم صحح: "
                "صدر الحكم بتاريخ ٠١/٠٣/٢٠٢٥")
        self.assertEqual(extract_case_metadata(text)["judgment_date"], "2025-03-01")


class WholeDocumentTests(unittest.TestCase):
    def test_full_synthetic_judgment(self):
        text = (
            "باسم الشعب\n"
            "محكمة الاستئناف التجريبية\n"
            "في الاستئناف رقم ٤٥٦ لسنة ٢٠٢٥\n"
            "المقام من: الطرف الأول (اسم افتراضي)\n"
            "ضد: الطرف الثاني (اسم افتراضي)\n"
            "قيد الاستئناف بتاريخ ١٠/٠١/٢٠٢٥\n"
            "صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥\n"
        )
        self.assertEqual(
            extract_case_metadata(text),
            {"case_number": "456", "case_year": "2025",
             "judgment_date": "2025-03-15"},
        )

    def test_empty_and_irrelevant_text(self):
        for text in ("", "   ", "نص تجريبي لا يحتوي على بيانات القضية"):
            with self.subTest(text=text):
                self.assertEqual(extract_case_metadata(text), EMPTY)

    def test_result_keys_exact(self):
        self.assertEqual(
            set(extract_case_metadata("الدعوى رقم ١ لسنة ٢٠٢٤")),
            {"case_number", "case_year", "judgment_date"},
        )

    def test_deterministic(self):
        text = "الدعوى رقم ١٢٣ لسنة ٢٠٢٤ صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥"
        self.assertEqual(extract_case_metadata(text), extract_case_metadata(text))

    def test_package_export(self):
        self.assertIs(package_export, extract_case_metadata)


class InputValidationTests(unittest.TestCase):
    def test_non_string_raises_value_error(self):
        for value in (None, 123, b"\xd8\xa7", ["الدعوى رقم ١"], 12.5, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    extract_case_metadata(value)


if __name__ == "__main__":
    unittest.main()
