"""Extract structured metadata from synthetic Arabic judicial text (task T-002).

Standard library only. Processing is local and deterministic: no network,
no external services, no models. A field that cannot be found, or that is
found but invalid, is returned as ``None``; nothing is guessed.
"""

import datetime
import re
import unicodedata

__all__ = ["extract_case_metadata"]

# Arabic-Indic (U+0660..U+0669) and Extended Arabic-Indic (U+06F0..U+06F9)
# digits mapped to Western digits.
_DIGIT_TABLE = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩"
    "۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)

# Patterns run on digit-normalized text and use [0-9] explicitly so that
# other Unicode digit scripts are never matched by accident. The patterns
# only locate candidates; the boundary checks below, which use Unicode
# character categories, decide whether a candidate is accepted.

# The conjunctions that may be attached to the front of a trigger phrase
# ("وصدر الحكم", "وَالدعوى رقم", "فَصدر الحكم").
_CONJUNCTIONS = "وف"

# Ordinary sentence punctuation that may directly follow a numeric token.
_PUNCT = frozenset(".,،؛;:!?؟)]}»\"'”’…")

# Arabic decimal separator (U+066B) and thousands separator (U+066C).
_NUMERIC_SEPARATORS = frozenset("٫٬")

# "الدعوى رقم 123" / "الاستئناف رقم 456".
_CASE_RE = re.compile(r"(?:الدعوى|الاستئناف)\s+رقم\s*:?\s*([0-9]+)")

# Optional "لسنة YYYY" directly after an accepted case number. A year that
# is not exactly four digits is rejected later by _valid_year.
_YEAR_RE = re.compile(r"\s+لسنة\s+([0-9]+)")

# A DD/MM/YYYY date introduced by a judgment phrase, e.g.
# "صدر الحكم بتاريخ 15/03/2025" or "صدر هذا الحكم بتاريخ ...".
# Requiring the judgment phrase avoids reporting another date in the text
# (such as a filing date) as the judgment date.
_JUDGMENT_DATE_RE = re.compile(
    r"(?:صدر(?:\s+هذا)?\s+الحكم|الحكم\s+الصادر|حكمت\s+المحكمة)"
    r"\s+بتاريخ\s*:?\s*"
    r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})"
)


def _category(char):
    return unicodedata.category(char)


def _is_mark(char):
    # Mn, Mc, Me: combining marks of any script, e.g. Arabic harakat,
    # U+08F0 ARABIC OPEN FATHATAN, U+0301 COMBINING ACUTE ACCENT.
    return _category(char).startswith("M")


def _is_format(char):
    # Cf: invisible format controls such as ZWNJ, ZWJ, LRM and RLM.
    return _category(char) == "Cf"


def _is_word_char(char):
    # Letters (including tatweel, Lm), combining marks, numbers of any kind
    # (Nd, Nl, No) and connector punctuation such as "_".
    category = _category(char)
    return category[0] in "LMN" or category == "Pc"


def _starts_word(text, start):
    """True if a trigger phrase beginning at ``start`` starts a word.

    Walking left from ``start``, invisible format characters (Cf) are
    skipped and combining marks are collected. The trigger may be preceded
    by a conjunction و/ف carrying any combining marks; apart from that, the
    nearest visible character before it must not be part of a word. A
    combining mark that does not sit on a conjunction always belongs to the
    preceding word, so it never exposes a trigger embedded inside a word.
    """
    i = start
    saw_mark = False
    while i > 0 and (_is_mark(text[i - 1]) or _is_format(text[i - 1])):
        saw_mark = saw_mark or _is_mark(text[i - 1])
        i -= 1
    if i > 0 and text[i - 1] in _CONJUNCTIONS:
        i -= 1
        while i > 0 and _is_format(text[i - 1]):
            i -= 1
    elif saw_mark:
        return False
    return i == 0 or not _is_word_char(text[i - 1])


def _is_numeric(char):
    # Nd, Nl, No: digits of any script, superscripts, fractions, roman
    # numerals, circled numbers; plus the Arabic decimal and thousands
    # separators, which only ever continue a number.
    return _category(char).startswith("N") or char in _NUMERIC_SEPARATORS


def _ends_token(text, end):
    """True if the numeric token ending at ``end`` is complete.

    Whole-token boundary policy, shared by case number, year and date.
    The token is followed by whitespace, the end of the text, or a
    separator: the characters up to the next whitespace, letter or end of
    text. A separator must start with sentence punctuation (_PUNCT) and
    must not contain any numeric character (_is_numeric).

    So punctuation separates the token from following text, with or
    without a space ("١٢٣،ثم", "2025).", "2025.(انتهى)"), while a numeric
    continuation anywhere in the separator ("123.5", "123..5", "2025.²",
    "123./4") rejects the whole token. Anything else attached directly to
    the token (letters, digits of other scripts, "/", "-", "_", combining
    marks) also rejects it. A token is never shortened to a valid-looking
    prefix.
    """
    size = len(text)
    if end == size or text[end].isspace():
        return True
    if text[end] not in _PUNCT:
        return False
    i = end
    while i < size and not (text[i].isspace() or _category(text[i]).startswith("L")):
        if _is_numeric(text[i]):
            return False
        i += 1
    return True


def _accepted_matches(pattern, text):
    for match in pattern.finditer(text):
        if _starts_word(text, match.start()) and _ends_token(text, match.end()):
            yield match


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
    for case_match in _accepted_matches(_CASE_RE, normalized):
        case_number = case_match.group(1)
        year_match = _YEAR_RE.match(normalized, case_match.end())
        if year_match is not None and _ends_token(normalized, year_match.end()):
            year = year_match.group(1)
            if _valid_year(year):
                case_year = year
        break

    judgment_date = None
    for match in _accepted_matches(_JUDGMENT_DATE_RE, normalized):
        judgment_date = _iso_date(*match.groups())
        if judgment_date is not None:
            break

    return {
        "case_number": case_number,
        "case_year": case_year,
        "judgment_date": judgment_date,
    }
