"""Celsius to Fahrenheit conversion with strict input validation (task T-001)."""

import re
from decimal import Context, Decimal, Inexact, InvalidOperation, ROUND_HALF_EVEN

ABSOLUTE_ZERO_C = Decimal("-273.15")
_TWO_PLACES = Decimal("0.01")
# Inputs that would need more digits than this to convert exactly are refused.
_MAX_PRECISION = 1000
# Plain decimal or scientific notation, ASCII digits only, no surrounding whitespace.
_NUMERIC_STR = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", re.ASCII)


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
        if not _NUMERIC_STR.fullmatch(value):
            raise ValueError(f"not a numeric string: {value!r}")
        result = Decimal(value)
    else:
        raise ValueError(f"unsupported type: {type(value).__name__}")
    if not result.is_finite():
        raise ValueError(f"not a finite number: {value!r}")
    return result


def celsius_to_fahrenheit(value):
    """Return ``value`` (degrees Celsius) in degrees Fahrenheit as a ``Decimal``.

    ``F = C * 9 / 5 + 32`` is computed exactly in ``Decimal`` and then rounded once to two
    decimal places with ``ROUND_HALF_EVEN``. Accepts ``int``, ``float``, ``Decimal`` and
    numeric ``str``. Raises ``ValueError`` for ``bool``, NaN, infinities, non-numeric values,
    values below absolute zero (-273.15 °C) and values too large or too finely specified to
    convert exactly. A result that rounds to zero is returned as ``0.00``, never ``-0.00``.
    The caller's decimal context is neither used nor changed.
    """
    celsius = _to_decimal(value)
    if celsius < ABSOLUTE_ZERO_C:
        raise ValueError(f"below absolute zero: {value!r}")

    # Enough digits for the exact result (integer part, input scale and two decimal places).
    precision = max(celsius.adjusted(), 2) - min(celsius.as_tuple().exponent, -2) + 4
    if precision > _MAX_PRECISION:
        raise ValueError(f"value out of supported range: {value!r}")

    exact = Context(prec=precision, traps=[Inexact, InvalidOperation])
    fahrenheit = exact.add(exact.divide(exact.multiply(celsius, 9), 5), 32)

    rounding = Context(prec=precision, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation])
    result = rounding.quantize(fahrenheit, _TWO_PLACES)
    # Report a result that rounds to zero as 0.00, not -0.00.
    return result.copy_abs() if result.is_zero() else result
