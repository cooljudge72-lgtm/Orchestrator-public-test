"""Extract structured metadata from synthetic Arabic judicial text (task T-002).

Standard library only. Processing is local and deterministic: no network,
no external services, no models. A field that cannot be found, or that is
found but invalid, is returned as ``None``; nothing is guessed.
"""

import datetime
import re

__all__ = ["extract_case_metadata"]

# Arabic-Indic (U+0660..U+0669) and Extended Arabic-Indic (U+06F0..U+06F9)
# digits mapped to Western digits.
_DIGIT_TABLE = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩"
    "۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)

# Patterns run on digit-normalized text and use [0-9] explicitly so that
# other Unicode digit scripts are never matched by accident.

# Arabic diacritics (harakat, tanween, shadda, sukun, dagger alif).
_MARKS = r"ً-ٰٟ"

# Trigger phrases must start a word. They may not follow a letter, digit,
# underscore, Arabic diacritic or tatweel, so "صدر" inside "مصدر" or
# "حكمت" inside "أحكمت" never matches. The only allowed attached prefix is
# the conjunction و or ف, optionally carrying diacritics ("وصدر الحكم",
# "وَالدعوى رقم", "فَصدر الحكم").
_WORD_START = (
    r"(?<![\wؐ-ؚـۖ-ۭ" + _MARKS + r"])"
    r"(?:[وف][" + _MARKS + r"]*)?"
)

# Ordinary sentence punctuation that may directly follow a token.
_PUNCT = r"\.,،؛;:!?؟)\]}»\"'”’…"

# Whole-token boundary policy for every numeric token (case number, year,
# judgment date). Right after the token there must be one of:
#   * whitespace or the end of the text; or
#   * a run of sentence punctuation, taken as a whole (the longest run),
#     that is NOT followed by a digit of any script or by an Arabic decimal
#     or thousands separator (U+066B, U+066C).
# So punctuation separates the token from what follows, including Arabic
# text written without a space ("١٢٣،ثم", "2025)."), but a numeric
# continuation after punctuation ("123.5", "123..5", "2024,,5", "2025).5")
# rejects the whole token. Anything else attached directly (letters,
# digits of other scripts, Arabic decimal separator, slash, hyphen,
# underscore, diacritics) also rejects the whole token. A token is never
# shortened to a valid-looking prefix.
_TOKEN_END = (
    r"(?=\s|$|[%s]+(?![%s\d٫٬]))" % (_PUNCT, _PUNCT)
)

# "الدعوى رقم 123" / "الاستئناف رقم 456", optionally followed by
# "لسنة YYYY". The year group is optional so a case number without a year
# is still recognized. A malformed year token is not captured, and a year
# that is not exactly four digits is rejected later by _valid_year.
_CASE_RE = re.compile(
    _WORD_START
    + r"(?:الدعوى|الاستئناف)\s+رقم\s*:?\s*([0-9]+)"
    + _TOKEN_END
    + r"(?:\s+لسنة\s+([0-9]+)" + _TOKEN_END + r")?"
)

# A DD/MM/YYYY date introduced by a judgment phrase, e.g.
# "صدر الحكم بتاريخ 15/03/2025" or "صدر هذا الحكم بتاريخ ...".
# Requiring the judgment phrase avoids reporting another date in the text
# (such as a filing date) as the judgment date. The whole date token must
# be well formed: nothing may be attached after the year except sentence
# punctuation.
_JUDGMENT_DATE_RE = re.compile(
    _WORD_START
    + r"(?:صدر(?:\s+هذا)?\s+الحكم|الحكم\s+الصادر|حكمت\s+المحكمة)"
    + r"\s+بتاريخ\s*:?\s*"
    + r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})"
    + _TOKEN_END
)


def _normalize_digits(text):
    return text.translate(_DIGIT_TABLE)


def _valid_year(value):
    return value is not None and len(value) == 4 and value[0] != "0"


def _iso_date(day, month, year):
    try:
        return datetime.date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def extract_case_metadata(text):
    """Return case metadata found in ``text``.

    The result is a dict with keys ``case_number``, ``case_year`` and
    ``judgment_date``. Values are strings using Western digits, or ``None``
    when the field is missing or invalid. ``judgment_date`` is ISO
    ``YYYY-MM-DD``; the first judgment date that is a real calendar date is
    used.

    Raises ValueError if ``text`` is not a string.
    """
    if not isinstance(text, str):
        raise ValueError("text must be a str, got %s" % type(text).__name__)

    normalized = _normalize_digits(text)

    case_number = None
    case_year = None
    case_match = _CASE_RE.search(normalized)
    if case_match is not None:
        case_number = case_match.group(1)
        year = case_match.group(2)
        if _valid_year(year):
            case_year = year

    judgment_date = None
    for match in _JUDGMENT_DATE_RE.finditer(normalized):
        judgment_date = _iso_date(*match.groups())
        if judgment_date is not None:
            break

    return {
        "case_number": case_number,
        "case_year": case_year,
        "judgment_date": judgment_date,
    }
