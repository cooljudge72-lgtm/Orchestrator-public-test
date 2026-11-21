"""Celsius to Fahrenheit conversion with strict input validation (task T-001)."""

import re
from decimal import (
    MAX_EMAX,
    MAX_PREC,
    MIN_EMIN,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    Inexact,
    InvalidOperation,
    localcontext,
)

ABSOLUTE_ZERO_C = Decimal("-273.15")
_TWO_PLACES = Decimal("0.01")
_FREEZING_F = Decimal("32.00")
# Largest supported adjusted exponent: |C| < 10**995. The exactly rounded result of a larger
# value has more than ~1000 digits (about log10(|C|) + 3), so some magnitude limit is needed to
# bound memory and time. This boundary is unchanged from the first revision and is a proposed
# specification decision for the owner (see the PR), not part of tasks/T-001.md.
_MAX_ADJUSTED = 994
# Plain decimal or scientific notation, ASCII digits only, no surrounding whitespace.
_NUMERIC_STR = re.compile(
    r"([+-]?)([0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE]([+-]?)[0-9]+)?", re.ASCII
)
# Representatives for numeric strings whose exponent is outside Decimal's range. Each gives the
# same result as the exact value: a tiny |C| converts to exactly 32.00, a huge one is refused.
_TINY = Decimal("1E-999999")
_HUGE = Decimal("1E+999999")


def _show(value):
    # Bounded repr for error messages, so a huge input does not produce a huge message.
    text = repr(value)
    return text if len(text) <= 60 else f"{text[:40]}...({len(text)} chars)"


def _context(prec, traps):
    # Widest exponent range, so no operand or result is clamped, subnormal or overflowing.
    return Context(prec=prec, Emin=MIN_EMIN, Emax=MAX_EMAX, traps=traps)


def _str_to_decimal(value):
    match = _NUMERIC_STR.fullmatch(value)
    if match is None:
        raise ValueError(f"not a numeric string: {_show(value)}")
    sign, mantissa, exponent_sign = match.groups()
    try:
        # A private context, so a caller's disabled InvalidOperation trap cannot turn this
        # into NaN. Conversion from a string is exact and does not round.
        with localcontext(_context(MAX_PREC, [InvalidOperation])):
            return Decimal(value)
    except InvalidOperation:
        pass
    # The syntax is valid, so the exponent is outside Decimal's range (|exponent| ~ 10**18).
    if not mantissa.strip("0."):
        return Decimal(0)
    if exponent_sign == "-":
        return _TINY.copy_negate() if sign == "-" else _TINY
    return _HUGE.copy_negate() if sign == "-" else _HUGE


def _to_decimal(value):
    # bool is a subclass of int, so it must be refused before the int case.
    if isinstance(value, bool):
        raise ValueError("bool is not a temperature")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        # Use the shortest repr, so 0.1 means 0.1 and not its binary approximation.
        result = Decimal(repr(value))
    elif isinstance(value, str):
        result = _str_to_decimal(value)
    else:
        raise ValueError(f"unsupported type: {type(value).__name__}")
    if not result.is_finite():
        raise ValueError(f"not a finite number: {_show(value)}")
    return result


def celsius_to_fahrenheit(value):
    """Return ``value`` (degrees Celsius) in degrees Fahrenheit as a ``Decimal``.

    ``F = C * 9 / 5 + 32`` is computed exactly in ``Decimal`` and then rounded once to two
    decimal places with ``ROUND_HALF_EVEN``. Accepts ``int``, ``float``, ``Decimal`` and
    numeric ``str``, with any exponent and any number of digits. Raises ``ValueError`` for
    ``bool``, NaN, infinities, non-numeric values and values below absolute zero (-273.15 °C).
    Also raises ``ValueError`` for magnitudes of 10**995 °C or more (a proposed limit; see
    ``_MAX_ADJUSTED``). A result that rounds to zero is returned as ``0.00``, never ``-0.00``.
    The caller's decimal context is neither used nor changed.
    """
    celsius = _to_decimal(value)
    if celsius < ABSOLUTE_ZERO_C:
        raise ValueError(f"below absolute zero: {_show(value)}")
    # |C| < 0.001 means |F - 32| < 0.0018, which always rounds to exactly 32.00. This covers
    # every zero (whatever its exponent) and tiny values, without arithmetic on the exponent.
    if celsius.is_zero() or celsius.adjusted() < -3:
        return _FREEZING_F
    if celsius.adjusted() > _MAX_ADJUSTED:
        raise ValueError(f"value out of supported range (|C| >= 1e995): {_show(value)}")

    # Enough digits for the exact result: the integer part (at most ~1000 digits), the input's
    # own fractional digits and two decimal places. This is linear in the input's digit count.
    precision = max(celsius.adjusted(), 2) - min(celsius.as_tuple().exponent, -2) + 4
    exact = _context(precision, [Inexact, InvalidOperation])
    fahrenheit = exact.add(exact.divide(exact.multiply(celsius, 9), 5), 32)

    result = fahrenheit.quantize(
        _TWO_PLACES, rounding=ROUND_HALF_EVEN, context=_context(precision, [InvalidOperation])
    )
    # Report a result that rounds to zero as 0.00, not -0.00.
    return result.copy_abs() if result.is_zero() else result
