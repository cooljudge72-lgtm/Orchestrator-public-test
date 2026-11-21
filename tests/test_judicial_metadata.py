"""Tests for pilot.judicial_metadata (task T-002).

All Arabic text below is synthetic. No real cases, courts or parties.

Compatibility register (Issue #7). The 63 original test methods are kept.
Where the closed T-002 specification changes an original expectation, the
original case is not deleted: it stays next to the original data in a
``REVISED_*`` collection, labelled with a register ID (``REG-...``), and is
asserted with its new expectation. ``CompatibilityRegisterTests`` lists
every changed subcase (249) with its original expectation, its new
expectation and the reason, and checks the count. New acceptance cases
from the handoff package are in ``AcceptanceTableTests`` (``ACC-...``).
"""

import time
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

    # REG-C01: "٠٢٤٥" was expected to give year None (round 1 rejected a
    # leading zero). The closed spec requires exactly four digits and
    # allows a leading zero, so it now gives "0245".
    REVISED_YEARS = {"الدعوى رقم ٥ لسنة ٠٢٤٥": "0245"}

    def test_year_not_four_digits_is_none(self):
        for text in ("الدعوى رقم ٥ لسنة ٢٤", "الدعوى رقم ٥ لسنة ٢٠٢٤٥"):
            with self.subTest(text=text):
                result = extract_case_metadata(text)
                self.assertEqual(result["case_number"], "5")
                self.assertIsNone(result["case_year"])
        for text, year in self.REVISED_YEARS.items():
            with self.subTest(text=text, register="REG-C01"):
                result = extract_case_metadata(text)
                self.assertEqual(result["case_number"], "5")
                self.assertEqual(result["case_year"], year)

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

    # Text after the token that was accepted in round 2 (original data).
    ORIGINAL_VALID_TAILS = ("", " ", "\n", ".", "،", "؛", "؟", "!", ":", ")",
                            ").", "»", "...", "؛؛", "،ثم", ".ثم", ")،وبعد",
                            "، وبعد", ".ً", "،x")
    # REG-T01..T06: originally valid. Under the closed tail grammar a
    # haraka must follow an Arabic letter and Latin letters are not tail
    # letters, so these now reject the tested field.
    REVISED_TO_INVALID = (".ً", "،x")
    VALID_TAILS = ORIGINAL_VALID_TAILS[:-2]
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
        for tail in self.REVISED_TO_INVALID:
            with self.subTest(tail=tail, register="REG-T"):
                self.assertIsNone(extract_case_metadata(build(tail))[key])

    def test_case_number_policy(self):
        self._check(lambda t: "الدعوى رقم ١2٣" + t, "case_number", "123")

    def test_case_year_policy(self):
        self._check(lambda t: "الاستئناف رقم 7 لسنة ٢0٢4" + t,
                    "case_year", "2024")
        for tail in self.REVISED_TO_INVALID:
            with self.subTest(tail=tail, register="REG-T", keeps="number"):
                self.assertEqual(extract_case_metadata(
                    "الاستئناف رقم 7 لسنة ٢0٢4" + tail)["case_number"], "7")

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


class RevisionThreeExampleTests(unittest.TestCase):
    """Exceptional revision round 3: the seven confirmed failures, verbatim."""

    def test_superscript_after_punctuation_rejects_case_number(self):
        result = extract_case_metadata("الدعوى رقم 123.² لسنة 2024")
        self.assertIsNone(result["case_number"])
        self.assertEqual(result, EMPTY)

    def test_superscript_after_punctuation_rejects_case_year(self):
        result = extract_case_metadata("الدعوى رقم 123 لسنة 2024.²")
        self.assertEqual(result["case_number"], "123")
        self.assertIsNone(result["case_year"])

    def test_superscript_after_punctuation_rejects_date(self):
        result = extract_case_metadata("صدر الحكم بتاريخ 15/03/2025.²")
        self.assertIsNone(result["judgment_date"])

    def test_slash_after_punctuation_rejects_case_number(self):
        result = extract_case_metadata("الاستئناف رقم 123./4 لسنة 2024")
        self.assertIsNone(result["case_number"])
        self.assertEqual(result, EMPTY)

    def test_slash_after_punctuation_rejects_date(self):
        result = extract_case_metadata("صدر الحكم بتاريخ 15/03/2025./1")
        self.assertIsNone(result["judgment_date"])

    def test_open_fathatan_hides_no_embedded_judgment_trigger(self):
        result = extract_case_metadata("مࣰصدر الحكم بتاريخ 15/03/2025")
        self.assertEqual(result, EMPTY)

    def test_open_fathatan_hides_no_embedded_case_trigger(self):
        result = extract_case_metadata("نصࣰالدعوى رقم 123 لسنة 2024")
        self.assertEqual(result, EMPTY)


class UnicodeTokenEndTests(unittest.TestCase):
    """Round 3, defect A: after a punctuation run only text may follow."""

    # Numeric characters outside [0-9] and numeric connectors, placed right
    # after a punctuation run.
    INVALID_AFTER_PUNCT = (
        "²", "³", "¹", "½", "①", "Ⅳ", "५", "٣", "۳", "/4", "-1",
        "+1", "٫", "٬", "٫5", "٬5", "ً5", "ࣰ5", "‏5",
        "‌²", "(5", "«٣", "(½", "-/²", "%1",
    )
    # Text, symbols and boundaries that may follow a punctuation run as
    # long as no numeric character appears before the next space/letter.
    PREFIXES = (".", "،", ")", ").", "..", "؛", "؟")
    # Original round-3 data: accepted after every prefix.
    ORIGINAL_VALID_AFTER_PUNCT = ("", " ", "\n", "ثم", "x", "ً", "‏",
                                  "‏ثم", "ًثم", "(انتهى)", "«نص»", "-",
                                  "/", "%", "۞", "؍", "(", "- ثم")
    # REG-U, 10 tails x 7 prefixes: originally accepted. The closed tail
    # grammar has no transition for Latin letters, a lone haraka, an
    # internal bidi control, "-", "/", "%", "۞" or "؍", so the value is now
    # rejected. A lone U+200F stays accepted: it is an edge control.
    REVISED_AFTER_ANY_PREFIX = ("x", "ً", "‏ثم", "ًثم", "-", "/", "%",
                                "۞", "؍", "- ثم")
    # REG-U, 4 tails after ")" only: after a closing wrapper only another
    # closer or ordinary punctuation may follow (W1/W3), so an Arabic
    # letter or an opener directly after ")" now rejects the value. These
    # stay accepted after the other six prefixes.
    REVISED_AFTER_CLOSE = ("ثم", "(انتهى)", "«نص»", "(")

    @classmethod
    def revised(cls, punct, tail):
        return (tail in cls.REVISED_AFTER_ANY_PREFIX
                or (punct == ")" and tail in cls.REVISED_AFTER_CLOSE))

    def _check(self, build, key, expected):
        for punct in self.PREFIXES:
            for tail in self.INVALID_AFTER_PUNCT:
                with self.subTest(punct=punct, tail=tail, valid=False):
                    self.assertIsNone(
                        extract_case_metadata(build(punct + tail))[key])
            for tail in self.ORIGINAL_VALID_AFTER_PUNCT:
                if self.revised(punct, tail):
                    with self.subTest(punct=punct, tail=tail,
                                      register="REG-U"):
                        self.assertIsNone(
                            extract_case_metadata(build(punct + tail))[key])
                    continue
                with self.subTest(punct=punct, tail=tail, valid=True):
                    self.assertEqual(
                        extract_case_metadata(build(punct + tail))[key],
                        expected)

    def test_case_number(self):
        self._check(lambda t: "الدعوى رقم ١2٣" + t, "case_number", "123")

    def test_case_year(self):
        self._check(lambda t: "الاستئناف رقم 7 لسنة ٢0٢4" + t,
                    "case_year", "2024")

    def test_judgment_date(self):
        self._check(lambda t: "صدر الحكم بتاريخ ١5/0٣/٢٠25" + t,
                    "judgment_date", "2025-03-15")

    def test_numeric_characters_attached_directly_rejected(self):
        for tail in ("²", "½", "①", "Ⅳ", "ࣰ", "́"):
            with self.subTest(tail=tail):
                self.assertEqual(
                    extract_case_metadata("الدعوى رقم ١٢٣" + tail), EMPTY)
                self.assertIsNone(extract_case_metadata(
                    "صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥" + tail)["judgment_date"])

    def test_earlier_accepted_examples_unchanged(self):
        self.assertEqual(
            extract_case_metadata("الدعوى رقم ١٢٣ لسنة ٢٠٢٤،ثم نُظرت"),
            {"case_number": "123", "case_year": "2024",
             "judgment_date": None})
        self.assertEqual(
            extract_case_metadata("صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥،ثم أُعلن")
            ["judgment_date"], "2025-03-15")
        self.assertEqual(
            extract_case_metadata("(الاستئناف رقم 45 لسنة 2025).")
            ["case_year"], "2025")


class UnicodeWordStartTests(unittest.TestCase):
    """Round 3, defect B: combining marks never expose embedded triggers."""

    # Combining marks from several Unicode blocks (Arabic, Arabic
    # Extended-A, Arabic Supplement-adjacent, Latin combining).
    MARKS = ("ࣰ", "ࣱ", "ࣲ", "ࣤ", "ٖ", "ٟ",
             "ؐ", "ۡ", "َ", "́")

    def test_marks_inside_word_before_trigger_rejected(self):
        for mark in self.MARKS:
            for text in ("م" + mark + "صدر الحكم بتاريخ 15/03/2025",
                         "نص" + mark + "الدعوى رقم 123 لسنة 2024",
                         "أ" + mark + "حكمت المحكمة بتاريخ 15/03/2025",
                         "م" + mark + mark + "صدر الحكم بتاريخ 15/03/2025",
                         " " + mark + "صدر الحكم بتاريخ 15/03/2025"):
                with self.subTest(mark=ascii(mark), text=ascii(text)):
                    self.assertEqual(extract_case_metadata(text), EMPTY)

    def test_format_characters_do_not_hide_word(self):
        for text in ("م‌صدر الحكم بتاريخ 15/03/2025",
                     "نص‍الدعوى رقم 123",
                     "مو‌الدعوى رقم 123"):
            with self.subTest(text=ascii(text)):
                self.assertEqual(extract_case_metadata(text), EMPTY)

    # REG-W01..W18: originally accepted on a conjunction. The closed spec
    # allows only harakat U+064B..U+0652 and U+0670 on و/ف, so these marks
    # (and U+0301) no longer start a trigger and the result is empty.
    REVISED_MARKS = ("\u08f0", "\u08f1", "\u08f2", "\u08e4", "\u0656",
                     "\u065f", "\u0610", "\u06e1", "\u0301")

    def test_conjunction_with_any_marks_accepted(self):
        for mark in self.MARKS + ("َّ", ""):
            for conj in ("و", "ف"):
                text = (conj + mark + "الدعوى رقم ٩ لسنة ٢٠٢٤ "
                        + conj + mark + "صدر الحكم بتاريخ 15/03/2025")
                if mark in self.REVISED_MARKS:
                    with self.subTest(conj=conj, mark=ascii(mark),
                                      register="REG-W"):
                        self.assertEqual(extract_case_metadata(text), EMPTY)
                    continue
                with self.subTest(conj=conj, mark=ascii(mark)):
                    result = extract_case_metadata(text)
                    self.assertEqual(
                        result, {"case_number": "9", "case_year": "2024",
                                 "judgment_date": "2025-03-15"})

    def test_conjunction_inside_word_rejected(self):
        for text in ("موَالدعوى رقم ٩", "نحوࣰصدر الحكم بتاريخ 15/03/2025",
                     "َوَالدعوى رقم ٩", "ـوالدعوى رقم ٩",
                     "ووالدعوى رقم ٩"):
            with self.subTest(text=ascii(text)):
                self.assertEqual(extract_case_metadata(text), EMPTY)

    # REG-S01..S02: originally accepted. No trigger may start from an
    # attached "،" or "." prefix, so the result is now empty.
    REVISED_PREFIXES = ("،", ".")

    def test_standalone_triggers_after_boundaries_accepted(self):
        for prefix in ("", " ", "\n", "(", "«", "،", ".", "‏",
                       " ‏", "‏وَ", "1. "):
            text = (prefix + "الدعوى رقم ٩ لسنة ٢٠٢٤ "
                    + prefix + "صدر الحكم بتاريخ 15/03/2025")
            if prefix in self.REVISED_PREFIXES:
                with self.subTest(prefix=ascii(prefix), register="REG-S"):
                    self.assertEqual(extract_case_metadata(text), EMPTY)
                continue
            with self.subTest(prefix=ascii(prefix)):
                result = extract_case_metadata(text)
                self.assertEqual(
                    result, {"case_number": "9", "case_year": "2024",
                             "judgment_date": "2025-03-15"})


def _triple(number=None, year=None, date=None):
    return {"case_number": number, "case_year": year, "judgment_date": date}


def _build_register():
    """Every original subcase whose expectation the closed spec changes.

    Each record: (register_id, source_method, text, field, original, new,
    reason). ``field`` is a result key, or None for the whole result dict.
    """
    records = []
    reason_c = "year is exactly four digits; a leading zero is allowed"
    for text, year in CaseNumberTests.REVISED_YEARS.items():
        records.append(("REG-C01",
                        "CaseNumberTests.test_year_not_four_digits_is_none",
                        text, "case_year", None, year, reason_c))

    reason_t = ("closed tail grammar: a haraka must follow an Arabic tail "
                "letter; Latin letters are not tail letters")
    builders = (
        ("test_case_number_policy", lambda t: "الدعوى رقم ١2٣" + t,
         "case_number", "123"),
        ("test_case_year_policy", lambda t: "الاستئناف رقم 7 لسنة ٢0٢4" + t,
         "case_year", "2024"),
        ("test_judgment_date_policy",
         lambda t: "صدر الحكم بتاريخ ١5/0٣/٢٠25" + t,
         "judgment_date", "2025-03-15"),
    )
    n = 0
    for method, build, key, original in builders:
        for tail in TokenBoundaryPolicyTests.REVISED_TO_INVALID:
            n += 1
            records.append(("REG-T%02d" % n,
                            "TokenBoundaryPolicyTests." + method,
                            build(tail), key, original, None, reason_t))

    reason_u_any = ("closed tail grammar: no transition for this character "
                    "after punctuation or a closer")
    reason_u_close = ("W1/W3: after a closing wrapper only a closer or "
                      "ordinary punctuation may follow")
    builders = (
        ("test_case_number", lambda t: "الدعوى رقم ١2٣" + t,
         "case_number", "123"),
        ("test_case_year", lambda t: "الاستئناف رقم 7 لسنة ٢0٢4" + t,
         "case_year", "2024"),
        ("test_judgment_date", lambda t: "صدر الحكم بتاريخ ١5/0٣/٢٠25" + t,
         "judgment_date", "2025-03-15"),
    )
    n = 0
    for method, build, key, original in builders:
        for punct in UnicodeTokenEndTests.PREFIXES:
            for tail in UnicodeTokenEndTests.ORIGINAL_VALID_AFTER_PUNCT:
                if not UnicodeTokenEndTests.revised(punct, tail):
                    continue
                n += 1
                reason = (reason_u_any
                          if tail in UnicodeTokenEndTests
                          .REVISED_AFTER_ANY_PREFIX else reason_u_close)
                records.append(("REG-U%03d" % n,
                                "UnicodeTokenEndTests." + method,
                                build(punct + tail), key, original, None,
                                reason))

    reason_w = ("only harakat U+064B..U+0652 and U+0670 may sit on a "
                "و/ف conjunction")
    full = _triple("9", "2024", "2025-03-15")
    n = 0
    for mark in UnicodeWordStartTests.REVISED_MARKS:
        for conj in ("و", "ف"):
            n += 1
            text = (conj + mark + "الدعوى رقم ٩ لسنة ٢٠٢٤ "
                    + conj + mark + "صدر الحكم بتاريخ 15/03/2025")
            records.append(("REG-W%02d" % n, "UnicodeWordStartTests."
                            "test_conjunction_with_any_marks_accepted",
                            text, None, full, EMPTY, reason_w))

    reason_s = "no trigger may start from an attached '،' or '.' prefix"
    n = 0
    for prefix in UnicodeWordStartTests.REVISED_PREFIXES:
        n += 1
        text = (prefix + "الدعوى رقم ٩ لسنة ٢٠٢٤ "
                + prefix + "صدر الحكم بتاريخ 15/03/2025")
        records.append(("REG-S%02d" % n, "UnicodeWordStartTests."
                        "test_standalone_triggers_after_boundaries_accepted",
                        text, None, full, EMPTY, reason_s))
    return records


class CompatibilityRegisterTests(unittest.TestCase):
    """Issue #7: the 249 approved expectation changes, case by case."""

    EXPECTED_COUNTS = {
        "CaseNumberTests.test_year_not_four_digits_is_none": 1,
        "TokenBoundaryPolicyTests.test_case_number_policy": 2,
        "TokenBoundaryPolicyTests.test_case_year_policy": 2,
        "TokenBoundaryPolicyTests.test_judgment_date_policy": 2,
        "UnicodeTokenEndTests.test_case_number": 74,
        "UnicodeTokenEndTests.test_case_year": 74,
        "UnicodeTokenEndTests.test_judgment_date": 74,
        "UnicodeWordStartTests.test_conjunction_with_any_marks_accepted": 18,
        "UnicodeWordStartTests."
        "test_standalone_triggers_after_boundaries_accepted": 2,
    }

    def test_register_size_and_distribution(self):
        records = _build_register()
        self.assertEqual(len(records), 249)
        counts = {}
        for record in records:
            counts[record[1]] = counts.get(record[1], 0) + 1
        self.assertEqual(counts, self.EXPECTED_COUNTS)
        self.assertEqual(len({(r[1], r[2]) for r in records}), 249)
        self.assertEqual(len({r[0] for r in records}), 249)

    def test_revised_cases_come_from_original_data(self):
        self.assertEqual(
            TokenBoundaryPolicyTests.VALID_TAILS
            + TokenBoundaryPolicyTests.REVISED_TO_INVALID,
            TokenBoundaryPolicyTests.ORIGINAL_VALID_TAILS)
        for tail in (UnicodeTokenEndTests.REVISED_AFTER_ANY_PREFIX
                     + UnicodeTokenEndTests.REVISED_AFTER_CLOSE):
            self.assertIn(tail, UnicodeTokenEndTests.ORIGINAL_VALID_AFTER_PUNCT)
        for mark in UnicodeWordStartTests.REVISED_MARKS:
            self.assertIn(mark, UnicodeWordStartTests.MARKS)
        # Unchanged after the edge rule: a lone RLM stays accepted.
        self.assertNotIn("‏",
                         UnicodeTokenEndTests.REVISED_AFTER_ANY_PREFIX)

    def test_every_record_has_new_expectation(self):
        for reg_id, source, text, key, original, new, reason in \
                _build_register():
            with self.subTest(id=reg_id, source=source, text=ascii(text)):
                self.assertNotEqual(original, new)
                self.assertTrue(reason)
                result = extract_case_metadata(text)
                actual = result if key is None else result[key]
                self.assertEqual(actual, new)


class AcceptanceTableTests(unittest.TestCase):
    """Acceptance examples from the closed T-002 handoff package."""

    BASE = "الدعوى رقم ١٢٣ لسنة ٢٠٢٤"
    DATE = "١٥/٠٣/٢٠٢٥"

    ROWS = (
        ("ACC-01", "الدعوى رقم ١٢٣ لسنة ٢٠٢٤", _triple("123", "2024")),
        # Number introduction forms.
        ("ACC-02a", "الدعوى رقم١٢٣ لسنة ٢٠٢٤", _triple("123", "2024")),
        ("ACC-02b", "الدعوى رقم:١٢٣ لسنة ٢٠٢٤", _triple("123", "2024")),
        ("ACC-02c", "الدعوى رقم: ١٢٣ لسنة ٢٠٢٤", _triple("123", "2024")),
        ("ACC-02d", "الدعوى رقم :١٢٣ لسنة ٢٠٢٤", _triple("123", "2024")),
        ("ACC-02e", "الدعوى رقم : ١٢٣ لسنة ٢٠٢٤", _triple("123", "2024")),
        # Date introduction forms.
        ("ACC-03a", "صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥", _triple(date="2025-03-15")),
        ("ACC-03b", "صدر الحكم بتاريخ١٥/٠٣/٢٠٢٥", _triple(date="2025-03-15")),
        ("ACC-03c", "صدر الحكم بتاريخ:١٥/٠٣/٢٠٢٥", _triple(date="2025-03-15")),
        ("ACC-03d", "صدر الحكم بتاريخ: ١٥/٠٣/٢٠٢٥",
         _triple(date="2025-03-15")),
        ("ACC-03e", "صدر الحكم بتاريخ :١٥/٠٣/٢٠٢٥",
         _triple(date="2025-03-15")),
        ("ACC-03f", "صدر الحكم بتاريخ : ١٥/٠٣/٢٠٢٥",
         _triple(date="2025-03-15")),
        # Date vocabulary.
        ("ACC-04a", "صدر هذا الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
         _triple(date="2025-03-15")),
        ("ACC-04b", "الحكم الصادر بتاريخ ١٥/٠٣/٢٠٢٥",
         _triple(date="2025-03-15")),
        ("ACC-04c", "حكمت المحكمة بتاريخ ١٥/٠٣/٢٠٢٥",
         _triple(date="2025-03-15")),
        # Punctuation between trigger words breaks the trigger.
        ("ACC-05a", "الدعوى. رقم ١٢٣", EMPTY),
        ("ACC-05b", "الدعوى، رقم ١٢٣", EMPTY),
        ("ACC-05c", "الدعوى؟ رقم ١٢٣", EMPTY),
        ("ACC-05d", "صدر الحكم. بتاريخ ١٥/٠٣/٢٠٢٥", EMPTY),
        ("ACC-05e", "صدر الحكم؛ بتاريخ ١٥/٠٣/٢٠٢٥", EMPTY),
        # Double colon after the introducer.
        ("ACC-06a", "الدعوى رقم::١٢٣", EMPTY),
        ("ACC-06b", "صدر الحكم بتاريخ::١٥/٠٣/٢٠٢٥", EMPTY),
        # W2: one terminal colon keeps the value.
        ("ACC-07a", "الدعوى رقم ١٢٣:", _triple("123")),
        ("ACC-07b", "الدعوى رقم ١٢٣ لسنة ٢٠٢٤:", _triple("123", "2024")),
        ("ACC-07c", "صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥:", _triple(date="2025-03-15")),
        # W2 counterparts: that field is rejected, the others are kept.
        ("ACC-08a", "الدعوى رقم ١٢٣:: صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
         _triple(date="2025-03-15")),
        ("ACC-08b", "الدعوى رقم ١٢٣:ثم صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
         _triple(date="2025-03-15")),
        ("ACC-08c", "الدعوى رقم ١٢٣ لسنة ٢٠٢٤::", _triple("123")),
        ("ACC-08d", "الدعوى رقم ١٢٣ لسنة ٢٠٢٤:ثم", _triple("123")),
        ("ACC-08e", "الدعوى رقم ١٢٣ لسنة ٢٠٢٤ صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥::",
         _triple("123", "2024")),
        ("ACC-08f", "الدعوى رقم ١٢٣ لسنة ٢٠٢٤ صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥:ثم",
         _triple("123", "2024")),
        # W03: wrappers.
        ("ACC-09a", "(انظر: الدعوى رقم ١٢٣)", _triple("123")),
        ("ACC-09b", "(الدعوى رقم ١٢٣)", _triple("123")),
        ("ACC-09c", "الدعوى رقم ١٢٣)", _triple("123")),
        ("ACC-09d", "\"الدعوى رقم ١٢٣\"", _triple("123")),
        ("ACC-10a", "(الدعوى رقم ١٢٣ لسنة ٢٠٢٤)", _triple("123", "2024")),
        ("ACC-10b", "(الدعوى رقم ١٢٣) لسنة ٢٠٢٤", _triple("123")),
        # W3: quotes and closers.
        ("ACC-11a", "الدعوى رقم ١٢٣)ثم", EMPTY),
        ("ACC-11b", "الدعوى رقم ١٢٣،\"نص\"", _triple("123")),
        ("ACC-11c", "الدعوى رقم ١٢٣\"5", EMPTY),
        # W02: validation stops at the end of the unit.
        ("ACC-12a", "الدعوى رقم ١٢٣ لسنة ٢٠٢٥.(انتهى)", _triple("123", "2025")),
        ("ACC-12b", "الدعوى رقم ١٢٣ لسنة ٢٠٢٥.(انتهى الحكم)",
         _triple("123", "2025")),
        ("ACC-12c", "الدعوى رقم ١٢٣ لسنة ٢٠٢٥.(انتهى الحكم)5",
         _triple("123", "2025")),
        ("ACC-12d", "الدعوى رقم ١٢٣ لسنة ٢٠٢٥.(انتهى)5", _triple("123")),
        # Repeated punctuation.
        ("ACC-13a", "الدعوى رقم ١٢٣ لسنة ٢٠٢٤...", _triple("123", "2024")),
        ("ACC-13b", "الدعوى رقم ١٢٣ لسنة ٢٠٢٤؛؛", _triple("123", "2024")),
        ("ACC-13c", "الدعوى رقم ١٢٣ لسنة ٢٠٢٤؟!", _triple("123", "2024")),
        ("ACC-13d", "الدعوى رقم ١٢٣ لسنة ٢٠٢٤؟؟5", _triple("123")),
        # Arabic tail word.
        ("ACC-14a", "الدعوى رقم ١٢٣،ثم", _triple("123")),
        ("ACC-14b", "الدعوى رقم ١٢٣،ثُمَّ", _triple("123")),
        # A13 / G4: the year needs a clean number and a standalone لسنة.
        ("ACC-15a", "الدعوى رقم ١٢٣، لسنة ٢٠٢٤", _triple("123")),
        ("ACC-15b", "الدعوى رقم ١٢٣ لسنة٢٠٢٤", _triple("123")),
        ("ACC-15c", "الدعوى رقم ١٢٣ لسنة:٢٠٢٤", _triple("123")),
        ("ACC-15d", "الدعوى رقم ١٢٣ لسنة", _triple("123")),
        # A19 / D11: an attached tail is never re-scanned for a trigger.
        ("ACC-16", "الدعوى رقم ١٢٣ لسنة ٢٠٢٤،والدعوى رقم ٤٥٦ لسنة ٢٠٢٥",
         _triple("123", "2024")),
        ("ACC-17", "صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥،والدعوى رقم ١٢٣",
         _triple(date="2025-03-15")),
        # Reference order; a year is never borrowed.
        ("ACC-18a", "الدعوى رقم ١٢٣ لسنة ٢٠٢٤ ثم الاستئناف رقم ٤٥٦ لسنة ٢٠٢٥",
         _triple("123", "2024")),
        ("ACC-18b",
         "الدعوى رقم ١٢٣ لسنة ٢٠٢٤x، ثم الاستئناف رقم ٤٥٦ لسنة ٢٠٢٥",
         _triple("123")),
        ("ACC-18c",
         "الدعوى رقم 123.e5 لسنة ٢٠٢٤ ثم الاستئناف رقم ٤٥٦ لسنة ٢٠٢٥",
         _triple("456", "2025")),
        # Leading zeros and digit mixing.
        ("ACC-19a", "الدعوى رقم ٠٠١٢٣ لسنة ٠٢٤٥", _triple("00123", "0245")),
        ("ACC-19b", "الدعوى رقم ١2۳ لسنة ٢٠٢٤", _triple("123", "2024")),
        ("ACC-19c", "الدعوى رقم ١٢٣ لسنة ٠٢٤", _triple("123")),
        ("ACC-19d", "الدعوى رقم ١٢٣ لسنة ٠٢٠٢٤", _triple("123")),
        # Bad case numbers: nothing extracted, no year borrowed.
        ("ACC-20a", "الدعوى رقم 123.e5 لسنة ٢٠٢٤", EMPTY),
        ("ACC-20b", "الدعوى رقم 123.ـ5 لسنة ٢٠٢٤", EMPTY),
        ("ACC-20c", "الدعوى رقم 123.² لسنة ٢٠٢٤", EMPTY),
        ("ACC-20d", "الدعوى رقم 123./4 لسنة ٢٠٢٤", EMPTY),
        ("ACC-20e", "الدعوى رقم ١٢٣٫٥ لسنة ٢٠٢٤", EMPTY),
        ("ACC-20f", "الدعوى رقم ١٢٣أ لسنة ٢٠٢٤", EMPTY),
        ("ACC-20g", "الدعوى رقم ١٢٣،x لسنة ٢٠٢٤", EMPTY),
        ("ACC-20h", "الدعوى رقم ١٢٣،ثم5 لسنة ٢٠٢٤", EMPTY),
        ("ACC-20i", "الدعوى رقم ١٢٣/٢٠٢٤ لسنة ٢٠٢٤", EMPTY),
        ("ACC-20j", "الدعوى رقم ١٢٣،ً لسنة ٢٠٢٤", EMPTY),
        ("ACC-21", "الدعوى رقم 123 لسنة 2024.e1", _triple("123")),
        # Bad dates.
        ("ACC-22a", "صدر الحكم بتاريخ 15/03/2025.e1", EMPTY),
        ("ACC-22b", "صدر الحكم بتاريخ 15/03/2025.ـ/1", EMPTY),
        ("ACC-22c", "صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥م", EMPTY),
        ("ACC-22d", "صدر الحكم بتاريخ ١٥-٠٣-٢٠٢٥", EMPTY),
        ("ACC-22e", "صدر الحكم بتاريخ ٣١/٠٢/٢٠٢٥", EMPTY),
        # Date validity.
        ("ACC-23a", "صدر الحكم بتاريخ ١٥/٣/٢٠٢٥", _triple(date="2025-03-15")),
        ("ACC-23b", "صدر الحكم بتاريخ ٢٩/٠٢/٢٠٢٤", _triple(date="2024-02-29")),
        ("ACC-23c",
         "صدر الحكم بتاريخ ٣١/٠٢/٢٠٢٥ ثم صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
         _triple(date="2025-03-15")),
        # Trigger boundaries.
        ("ACC-24a", "،الدعوى رقم ٩", EMPTY),
        ("ACC-24b", ".الدعوى رقم ٩", EMPTY),
        ("ACC-24c", "الدعوى رقم ١٢٣", EMPTY),
        ("ACC-24d", "مࣰصدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥", EMPTY),
        ("ACC-24e", "ࣰالدعوى رقم ١٢٣", EMPTY),
        # Diacritics.
        ("ACC-25a", "وَالدعوى رقم ٩ لسنة ٢٠٢٤", _triple("9", "2024")),
        ("ACC-25b", "و́الدعوى رقم ٩", EMPTY),
        ("ACC-25c", "وࣰالدعوى رقم ٩", EMPTY),
        ("ACC-25d", "الدعوى رقم ١٢ࣰ٣", EMPTY),
        ("ACC-25e", "الدعوى رقم ١٢٣،ثࣰم", EMPTY),
        # Edge bidi controls.
        ("ACC-26a", "‏الدعوى رقم ١٢٣‏", _triple("123")),
        ("ACC-26b", "‏(الدعوى رقم ١٢٣)", _triple("123")),
        ("ACC-26c", "(‏الدعوى رقم ١٢٣)", EMPTY),
        ("ACC-26d", "الدعوى رقم:‏١٢٣", EMPTY),
        ("ACC-26e", "الدعوى رقم ١٢‏٣", EMPTY),
        # Contract.
        ("ACC-27a", "الدعوى رقم ١٢٣ لسنة ٢٠٢٤ صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥",
         _triple("123", "2024", "2025-03-15")),
        ("ACC-27b", "الدعوى رقم", EMPTY),
        ("ACC-27c", "نص تجريبي بلا أي مرجع", EMPTY),
    )

    def test_rows(self):
        ids = [row[0] for row in self.ROWS]
        self.assertEqual(len(ids), len(set(ids)))
        for row_id, text, expected in self.ROWS:
            with self.subTest(id=row_id, text=ascii(text)):
                self.assertEqual(extract_case_metadata(text), expected)

    def test_contract_rejects_non_str(self):
        for value in (None, 123, b""):
            with self.subTest(value=value, id="ACC-27d"):
                with self.assertRaises(ValueError):
                    extract_case_metadata(value)


class LongInputTests(unittest.TestCase):
    """Malformed inputs of about 40,000 characters finish in linear time."""

    SIZE = 40000
    LIMIT_SECONDS = 2.0

    def _timed(self, text):
        start = time.perf_counter()
        result = extract_case_metadata(text)
        return result, time.perf_counter() - start

    def test_long_malformed_tails(self):
        n = self.SIZE
        cases = (
            ("word tail then digit", "الدعوى رقم ١٢٣،" + "ثم" * (n // 2) + "5",
             EMPTY),
            ("quotes", "الدعوى رقم ١٢٣" + "\"" * n + "5", EMPTY),
            ("quote/letter alternation",
             "الدعوى رقم ١٢٣،" + "\"ن" * (n // 2) + "5", EMPTY),
            ("punctuation run", "الدعوى رقم ١٢٣" + "." * n + "5", EMPTY),
            ("openers", "الدعوى رقم ١٢٣." + "(" * n + "5", EMPTY),
            ("closers", "الدعوى رقم ١٢٣" + ")" * n + "x", EMPTY),
            ("digits", "الدعوى رقم " + "١" * n + "x", EMPTY),
            ("date tail", "صدر الحكم بتاريخ ١٥/٠٣/٢٠٢٥،" + "ثم" * (n // 2)
             + "5", EMPTY),
            ("long valid tail", "الدعوى رقم ١٢٣،" + "ثم" * (n // 2),
             _triple("123")),
        )
        for name, text, expected in cases:
            with self.subTest(case=name):
                self.assertGreaterEqual(len(text), n)
                result, elapsed = self._timed(text)
                self.assertEqual(result, expected)
                self.assertLess(elapsed, self.LIMIT_SECONDS)

    def test_many_trigger_candidates(self):
        cases = (
            ("bare case triggers", "الدعوى رقم " * 4000, EMPTY),
            ("bare date triggers", "صدر هذا الحكم بتاريخ " * 2000, EMPTY),
            ("invalid values", "الدعوى رقم ١٢٣x " * 3000, EMPTY),
            ("year keywords", "الدعوى رقم ١ " + "لسنة " * 8000,
             _triple("1")),
        )
        for name, text, expected in cases:
            with self.subTest(case=name):
                self.assertGreaterEqual(len(text), self.SIZE)
                result, elapsed = self._timed(text)
                self.assertEqual(result, expected)
                self.assertLess(elapsed, self.LIMIT_SECONDS)


class InputValidationTests(unittest.TestCase):
    def test_non_string_raises_value_error(self):
        for value in (None, 123, b"\xd8\xa7", ["الدعوى رقم ١"], 12.5, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    extract_case_metadata(value)


if __name__ == "__main__":
    unittest.main()
