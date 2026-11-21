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


class MalformedNumberTokenTests(unittest.TestCase):
    """Revision round 1, defect 1: whole case-number and year tokens."""

    def test_malformed_case_number_rejected_not_truncated(self):
        for token in ("123.5", "١٢٣٫٥", "123,5", "123أ", "123abc", "123_",
                      "123५", "123٨x", "123/4", "123-ب", "123ً"):
            with self.subTest(token=token):
                result = extract_case_metadata(
                    "الدعوى رقم " + token + " لسنة ٢٠٢٤")
                self.assertEqual(result, EMPTY)

    def test_malformed_year_rejected_not_truncated(self):
        for token in ("2024.5", "٢٠٢٤٫٥", "2024x", "٢٠٢٤هـ", "2024५",
                      "2024/1", "2024-ب"):
            with self.subTest(token=token):
                result = extract_case_metadata(
                    "الاستئناف رقم ٧٧ لسنة " + token)
                self.assertEqual(result["case_number"], "77")
                self.assertIsNone(result["case_year"])

    def test_sentence_punctuation_after_tokens_accepted(self):
        cases = [
            ("الدعوى رقم ١٢٣ لسنة ٢٠٢٤.", "123", "2024"),
            ("الدعوى رقم ١٢٣ لسنة ٢٠٢٤، وقد", "123", "2024"),
            ("(الاستئناف رقم 45 لسنة 2025)", "45", "2025"),
            ("(الاستئناف رقم 45 لسنة 2025).", "45", "2025"),
            ("الدعوى رقم ٩، المنظورة", "9", None),
            ("الدعوى رقم: ٩ لسنة ٢٠٢٢؛", "9", "2022"),
            ("هل نظرت الدعوى رقم 8 لسنة 2021؟", "8", "2021"),
        ]
        for text, number, year in cases:
            with self.subTest(text=text):
                result = extract_case_metadata(text)
                self.assertEqual(result["case_number"], number)
                self.assertEqual(result["case_year"], year)

    def test_later_well_formed_reference_still_found(self):
        text = "الدعوى رقم 12.5 خطأ، والصحيح الدعوى رقم 12 لسنة 2024"
        result = extract_case_metadata(text)
        self.assertEqual(result["case_number"], "12")
        self.assertEqual(result["case_year"], "2024")


class MalformedDateTokenTests(unittest.TestCase):
    """Revision round 1, defect 2: the whole judgment-date token."""

    def test_attached_suffix_rejects_date(self):
        for date in ("15/03/2025x", "15/03/2025أ", "١٥/٠٣/٢٠٢٥م",
                     "15/03/2025.5", "١٥/٠٣/٢٠٢٥٫٥", "15/03/2025५",
                     "15/03/2025_", "15/03/2025-1", "15/03/2025َ"):
            with self.subTest(date=date):
                result = extract_case_metadata("صدر الحكم بتاريخ " + date)
                self.assertIsNone(result["judgment_date"])

    def test_unsupported_digits_inside_date_rejected(self):
        for date in ("1५/03/2025", "15/0३/2025", "15/03/202५"):
            with self.subTest(date=date):
                result = extract_case_metadata("صدر الحكم بتاريخ " + date)
                self.assertIsNone(result["judgment_date"])

    def test_sentence_punctuation_after_date_accepted(self):
        for suffix in (".", "،", "؛", ":", "!", "؟", ")", ").", "، وبه",
                       ". ", "\n", "»"):
            with self.subTest(suffix=suffix):
                result = extract_case_metadata(
                    "صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥" + suffix)
                self.assertEqual(result["judgment_date"], "2025-03-15")

    def test_malformed_then_valid_date_uses_valid(self):
        text = ("صدر الحكم بتاريخ 15/03/2025x ثم صدر الحكم بتاريخ "
                "16/03/2025.")
        self.assertEqual(extract_case_metadata(text)["judgment_date"],
                         "2025-03-16")


class TriggerBoundaryTests(unittest.TestCase):
    """Revision round 1, defect 3: triggers must not match inside words."""

    def test_judgment_trigger_inside_word_ignored(self):
        for text in ("مصدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
                     "مُصدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
                     "مـصدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
                     "أحكمت المحكمة بتاريخ ١٥/٠٣/٢٠٢٥",
                     "xصدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
                     "1صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
                     "والمصدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥"):
            with self.subTest(text=text):
                self.assertIsNone(extract_case_metadata(text)["judgment_date"])

    def test_case_trigger_inside_word_ignored(self):
        for text in ("كالدعوى رقم ٥ لسنة ٢٠٢٤",
                     "مالاستئناف رقم ٥ لسنة ٢٠٢٤",
                     "اللدعوى رقم ٥",
                     "ـالدعوى رقم ٥",
                     "xالاستئناف رقم ٥"):
            with self.subTest(text=text):
                self.assertEqual(extract_case_metadata(text), EMPTY)

    def test_standalone_and_conjunction_phrases_preserved(self):
        cases = [
            ("وصدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥", "judgment_date", "2025-03-15"),
            ("فصدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥", "judgment_date", "2025-03-15"),
            ("بعد المداولة، حكمت المحكمة بتاريخ 1/2/2024",
             "judgment_date", "2024-02-01"),
            ("الحكم الصادر بتاريخ ٠٩/١٢/٢٠٢٣", "judgment_date", "2023-12-09"),
            ("(صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥)", "judgment_date", "2025-03-15"),
            ("والدعوى رقم ٥ لسنة ٢٠٢٤", "case_number", "5"),
            ("في الاستئناف رقم ٦ لسنة ٢٠٢٤", "case_number", "6"),
            ("«الاستئناف رقم ٦»", "case_number", "6"),
        ]
        for text, key, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(extract_case_metadata(text)[key], expected)


class RevisionTwoExampleTests(unittest.TestCase):
    """Revision round 2: the eight confirmed examples, verbatim."""

    def test_punctuation_then_arabic_keeps_case_number(self):
        result = extract_case_metadata("الدعوى رقم ١٢٣،ثم نُظرت")
        self.assertEqual(result["case_number"], "123")

    def test_punctuation_then_arabic_keeps_case_year(self):
        result = extract_case_metadata("الدعوى رقم ١٢٣ لسنة ٢٠٢٤،ثم نُظرت")
        self.assertEqual(result["case_number"], "123")
        self.assertEqual(result["case_year"], "2024")

    def test_punctuation_then_arabic_keeps_judgment_date(self):
        result = extract_case_metadata("صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥،ثم أُعلن")
        self.assertEqual(result["judgment_date"], "2025-03-15")

    def test_repeated_punctuation_numeric_case_number_rejected(self):
        result = extract_case_metadata("الدعوى رقم 123..5 لسنة 2024")
        self.assertEqual(result, EMPTY)

    def test_repeated_punctuation_numeric_year_rejected(self):
        result = extract_case_metadata("الاستئناف رقم 123 لسنة 2024,,5")
        self.assertEqual(result["case_number"], "123")
        self.assertIsNone(result["case_year"])

    def test_repeated_punctuation_numeric_date_rejected(self):
        result = extract_case_metadata("صدر الحكم بتاريخ 15/03/2025..5")
        self.assertIsNone(result["judgment_date"])

    def test_vowelled_conjunction_case(self):
        result = extract_case_metadata("وَالدعوى رقم ٩ لسنة ٢٠٢٤")
        self.assertEqual(result["case_number"], "9")
        self.assertEqual(result["case_year"], "2024")

    def test_vowelled_conjunction_judgment(self):
        result = extract_case_metadata("فَصدر الحكم بتاريخ 15/03/2025")
        self.assertEqual(result["judgment_date"], "2025-03-15")


class TokenBoundaryPolicyTests(unittest.TestCase):
    """Revision round 2: one whole-token policy for every numeric field."""

    # Text after the token that must be accepted.
    VALID_TAILS = ("", " ", "\n", ".", "،", "؛", "؟", "!", ":", ")", ").",
                   "»", "...", "؛؛", "،ثم", ".ثم", ")،وبعد", "، وبعد",
                   ".ً", "،x")
    # Text after the token that must reject the whole token.
    INVALID_TAILS = (".5", "..5", ",,5", "،5", "،،٥", ")5", ").5", "...٣",
                     ".५", ",٫", "٫5", "٬000", "x", "أ", "५", "/1", "-1",
                     "_", "َ", "ـ")

    def _check(self, build, key, expected):
        for tail in self.VALID_TAILS:
            with self.subTest(tail=tail, valid=True):
                self.assertEqual(extract_case_metadata(build(tail))[key],
                                 expected)
        for tail in self.INVALID_TAILS:
            with self.subTest(tail=tail, valid=False):
                self.assertIsNone(extract_case_metadata(build(tail))[key])

    def test_case_number_policy(self):
        self._check(lambda t: "الدعوى رقم ١2٣" + t, "case_number", "123")

    def test_case_year_policy(self):
        self._check(lambda t: "الاستئناف رقم 7 لسنة ٢0٢4" + t,
                    "case_year", "2024")

    def test_judgment_date_policy(self):
        self._check(lambda t: "صدر الحكم بتاريخ ١5/0٣/٢٠25" + t,
                    "judgment_date", "2025-03-15")

    def test_malformed_case_number_never_yields_year(self):
        for tail in self.INVALID_TAILS:
            with self.subTest(tail=tail):
                text = "الدعوى رقم ١٢٣" + tail + " لسنة ٢٠٢٤"
                self.assertEqual(extract_case_metadata(text), EMPTY)


class ConjunctionDiacriticTests(unittest.TestCase):
    """Revision round 2: vowelled و/ف prefixes; embedded triggers still fail."""

    def test_conjunction_with_marks_accepted(self):
        for prefix in ("و", "ف", "وَ", "فَ", "وُ", "وِ", "وْ", "فَّ"):
            with self.subTest(prefix=prefix):
                result = extract_case_metadata(
                    prefix + "الاستئناف رقم ٤ لسنة ٢٠٢٣ "
                    + prefix + "صدر الحكم بتاريخ ٠١/٠٢/٢٠٢٤")
                self.assertEqual(
                    result, {"case_number": "4", "case_year": "2023",
                             "judgment_date": "2024-02-01"})

    def test_embedded_triggers_still_rejected_with_marks(self):
        for text in ("مَصدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
                     "وَمصدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
                     "أَحكمت المحكمة بتاريخ ١٥/٠٣/٢٠٢٥",
                     "xوَصدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
                     "مَوَصدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
                     "ـوَصدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
                     "بَالدعوى رقم ٥ لسنة ٢٠٢٤",
                     "كَالدعوى رقم ٥ لسنة ٢٠٢٤",
                     "مَوَالدعوى رقم ٥ لسنة ٢٠٢٤"):
            with self.subTest(text=text):
                self.assertEqual(extract_case_metadata(text), EMPTY)


class InputValidationTests(unittest.TestCase):
    def test_non_string_raises_value_error(self):
        for value in (None, 123, b"\xd8\xa7", ["الدعوى رقم ١"], 12.5, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    extract_case_metadata(value)


if __name__ == "__main__":
    unittest.main()
