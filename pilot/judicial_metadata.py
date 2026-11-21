"""Extract structured metadata from synthetic Arabic judicial text (task T-002).

Standard library only. Processing is local and deterministic: no network,
no external services, no models. A field that cannot be found, or that is
found but invalid, is returned as ``None``; nothing is guessed and a value
is never shortened to a valid-looking prefix.

Design (closed allowlists, whole-unit validation):

1. Lexer. The text is split into units on an explicit whitespace set
   (space, tab, LF, CR, NBSP) and each unit keeps its original offsets.
   Bidi controls are dropped only at the outer edges of an original unit.
2. Triggers. A trigger phrase starts at the beginning of a unit, optionally
   after one opening wrapper and one و/ف conjunction carrying harakat. Its
   words must be whole units, except that the last word (رقم / بتاريخ) may
   carry the value directly, with at most one ":".
3. Values. The whole value unit is validated: a numeric core followed by a
   tail accepted by a deterministic single-pass state machine. Any
   character or transition not listed is a rejection.
4. Selection. The first valid case number wins; its year is linked only
   from a following standalone "لسنة" unit. The judgment date is chosen
   independently: the first valid calendar date.
"""

import datetime

__all__ = ["extract_case_metadata"]

# --- Character classes (closed sets; no Unicode category lookups) ---------

# Unit separators. Other Unicode spaces (e.g. U+2003) are not separators.
_WHITESPACE = frozenset(" \t\n\r ")

# Bidi controls ignored only at the outer edges of an original unit.
_EDGE_BIDI = frozenset("‎‏؜⁦⁧⁨⁩")

# Digits of the numeric core, mapped to ASCII.
_DIGIT_VALUES = {}
for _base in (0x30, 0x660, 0x6F0):
    for _offset in range(10):
        _DIGIT_VALUES[chr(_base + _offset)] = str(_offset)
del _base, _offset

# Arabic letters allowed in a tail word: U+0621..U+063A, U+0641..U+064A.
# Tatweel (U+0640) is deliberately excluded.
_TAIL_LETTERS = frozenset(
    [chr(c) for c in range(0x621, 0x63B)] + [chr(c) for c in range(0x641, 0x64B)]
)

# Harakat: U+064B..U+0652 and U+0670.
_HARAKAT = frozenset([chr(c) for c in range(0x64B, 0x653)] + ["ٰ"])

_CONJUNCTIONS = frozenset("وف")

# Ordinary punctuation allowed in a tail.
_PUNCT = frozenset("،,؛;.!?؟…")

# Wrappers. Straight quotes may open or close depending on position.
_OPENERS = frozenset("(«“\"'")
_CLOSERS = frozenset(")»”\"'")
_UNIT_START_OPENERS = _OPENERS

# --- Triggers ------------------------------------------------------------

_CASE_TRIGGERS = (
    ("الدعوى", "رقم"),
    ("الاستئناف", "رقم"),
)

_DATE_TRIGGERS = (
    ("صدر", "الحكم", "بتاريخ"),
    ("صدر", "هذا", "الحكم", "بتاريخ"),
    ("الحكم", "الصادر", "بتاريخ"),
    ("حكمت", "المحكمة", "بتاريخ"),
)

_YEAR_KEYWORD = "لسنة"


def _units(text):
    """Split ``text`` into units of non-whitespace characters.

    Returns a list of ``(start, end)`` offsets into ``text``, with edge bidi
    controls already excluded from each unit. A unit made only of bidi
    controls is dropped.
    """
    units = []
    size = len(text)
    i = 0
    while i < size:
        while i < size and text[i] in _WHITESPACE:
            i += 1
        start = i
        while i < size and text[i] not in _WHITESPACE:
            i += 1
        end = i
        while start < end and text[start] in _EDGE_BIDI:
            start += 1
        while end > start and text[end - 1] in _EDGE_BIDI:
            end -= 1
        if start < end:
            units.append((start, end))
    return units


def _first_word_matches(unit, word):
    """True if ``unit`` is ``word``, optionally after one opening wrapper
    and then one و/ف conjunction carrying zero or more harakat."""
    i = 0
    if i < len(unit) and unit[i] in _UNIT_START_OPENERS:
        i += 1
    if unit[i:] == word:
        return True
    if i < len(unit) and unit[i] in _CONJUNCTIONS:
        i += 1
        while i < len(unit) and unit[i] in _HARAKAT:
            i += 1
        return unit[i:] == word
    return False


def _value_after_trigger(words, index, trigger):
    """Return the value string introduced by ``trigger`` at unit ``index``.

    Returns ``(value, next_index)`` where ``next_index`` is the index of the
    unit after the value, or ``(None, None)`` if the trigger does not match
    or no value follows.
    """
    if not _first_word_matches(words[index], trigger[0]):
        return None, None
    last = len(trigger) - 1
    for k in range(1, last):
        j = index + k
        if j >= len(words) or words[j] != trigger[k]:
            return None, None
    j = index + last
    if j >= len(words):
        return None, None
    unit = words[j]
    keyword = trigger[last]
    if not unit.startswith(keyword):
        return None, None
    rest = unit[len(keyword):]
    if rest == "":
        j += 1
        if j >= len(words):
            return None, None
        following = words[j]
        if following == ":":
            j += 1
            if j >= len(words):
                return None, None
            return words[j], j + 1
        if following.startswith(":"):
            return following[1:], j + 1
        return following, j + 1
    if rest == ":":
        j += 1
        if j >= len(words):
            return None, None
        return words[j], j + 1
    if rest.startswith(":"):
        return rest[1:], j + 1
    return rest, j + 1


# --- Value validation ----------------------------------------------------

_CORE, _AFTER_CLOSE, _AFTER_PUNCT, _AFTER_OPEN, _IN_WORD, _COLON = range(6)


def _valid_tail(value, pos):
    """True if ``value[pos:]`` is an acceptable tail after a numeric core.

    Deterministic single pass; every state may end the unit. Any character
    not listed for the current state rejects the whole value.
    """
    state = _CORE
    for char in value[pos:]:
        if state == _CORE:
            if char in _CLOSERS:
                state = _AFTER_CLOSE
            elif char in _PUNCT:
                state = _AFTER_PUNCT
            elif char == ":":
                state = _COLON
            else:
                return False
        elif state == _AFTER_CLOSE:
            if char in _CLOSERS:
                state = _AFTER_CLOSE
            elif char in _PUNCT:
                state = _AFTER_PUNCT
            else:
                return False
        elif state == _AFTER_PUNCT:
            if char in _PUNCT:
                state = _AFTER_PUNCT
            elif char in _OPENERS:
                state = _AFTER_OPEN
            elif char in _TAIL_LETTERS:
                state = _IN_WORD
            else:
                return False
        elif state == _AFTER_OPEN:
            if char in _OPENERS:
                state = _AFTER_OPEN
            elif char in _TAIL_LETTERS:
                state = _IN_WORD
            else:
                return False
        elif state == _IN_WORD:
            if char in _TAIL_LETTERS or char in _HARAKAT:
                state = _IN_WORD
            elif char in _CLOSERS:
                state = _AFTER_CLOSE
            elif char in _PUNCT:
                state = _AFTER_PUNCT
            else:
                return False
        else:  # _COLON: a terminal ":" must end the unit.
            return False
    return True


def _digit_run(value, pos):
    """Return ``(ascii_digits, end)`` for the digit run starting at ``pos``."""
    digits = []
    size = len(value)
    while pos < size and value[pos] in _DIGIT_VALUES:
        digits.append(_DIGIT_VALUES[value[pos]])
        pos += 1
    return "".join(digits), pos


def _parse_number(value):
    """Return ``(digits, has_tail)`` for a valid number unit, else ``None``."""
    if value is None:
        return None
    digits, end = _digit_run(value, 0)
    if not digits or not _valid_tail(value, end):
        return None
    return digits, end < len(value)


def _parse_year(value):
    parsed = _parse_number(value)
    if parsed is None or len(parsed[0]) != 4:
        return None
    return parsed[0]


def _parse_date(value):
    """Return the ISO date for a valid D/M/YYYY value unit, else ``None``."""
    if value is None:
        return None
    day, pos = _digit_run(value, 0)
    if not 1 <= len(day) <= 2 or value[pos:pos + 1] != "/":
        return None
    month, pos = _digit_run(value, pos + 1)
    if not 1 <= len(month) <= 2 or value[pos:pos + 1] != "/":
        return None
    year, pos = _digit_run(value, pos + 1)
    if len(year) != 4 or not _valid_tail(value, pos):
        return None
    try:
        return datetime.date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


# --- Extraction ----------------------------------------------------------


def _find_case(words):
    for index in range(len(words)):
        for trigger in _CASE_TRIGGERS:
            value, after = _value_after_trigger(words, index, trigger)
            parsed = _parse_number(value)
            if parsed is None:
                continue
            number, has_tail = parsed
            year = None
            if (not has_tail and after + 1 < len(words)
                    and words[after] == _YEAR_KEYWORD):
                year = _parse_year(words[after + 1])
            return number, year
    return None, None


def _find_date(words):
    for index in range(len(words)):
        for trigger in _DATE_TRIGGERS:
            value, _ = _value_after_trigger(words, index, trigger)
            date = _parse_date(value)
            if date is not None:
                return date
    return None


def extract_case_metadata(text):
    """Return case metadata found in ``text``.

    The result is a dict with exactly the keys ``case_number``,
    ``case_year`` and ``judgment_date``. Values are strings using ASCII
    digits, or ``None`` when the field is missing or invalid.
    ``case_number`` keeps leading zeros; ``case_year`` is exactly four
    digits; ``judgment_date`` is ISO ``YYYY-MM-DD``.

    Raises ValueError if ``text`` is not a string.
    """
    if not isinstance(text, str):
        raise ValueError("text must be a str, got %s" % type(text).__name__)

    words = [text[start:end] for start, end in _units(text)]
    case_number, case_year = _find_case(words)
    return {
        "case_number": case_number,
        "case_year": case_year,
        "judgment_date": _find_date(words),
    }
