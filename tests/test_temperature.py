"""Tests for pilot.temperature (task T-001). Synthetic values only."""

import decimal
import unittest
from decimal import Decimal
from fractions import Fraction

from pilot import celsius_to_fahrenheit as package_export
from pilot.temperature import celsius_to_fahrenheit


class ConversionTests(unittest.TestCase):
    def test_reference_points(self):
        cases = [
            (0, "32.00"),
            (100, "212.00"),
            (-40, "-40.00"),
            (37, "98.60"),
            (Decimal("-273.15"), "-459.67"),
            ("-17.7777", "0.00"),  # +0.00014
            ("-17.78", "0.00"),  # -0.004, no negative zero
        ]
        for celsius, expected in cases:
            with self.subTest(celsius=celsius):
                self.assertEqual(str(celsius_to_fahrenheit(celsius)), expected)

    def test_returns_decimal_with_two_places(self):
        for celsius in (0, 1.5, Decimal("12.3456"), "20", "1e3"):
            with self.subTest(celsius=celsius):
                result = celsius_to_fahrenheit(celsius)
                self.assertIs(type(result), Decimal)
                self.assertEqual(result.as_tuple().exponent, -2)

    def test_all_accepted_types_agree(self):
        expected = Decimal("98.24")
        for celsius in (36.8, Decimal("36.8"), "36.8", "+3.68e1", "36.80"):
            with self.subTest(celsius=celsius):
                self.assertEqual(celsius_to_fahrenheit(celsius), expected)
        self.assertEqual(celsius_to_fahrenheit(25), Decimal("77.00"))

    def test_absolute_zero_is_accepted(self):
        for celsius in (-273.15, "-273.15", Decimal("-273.1500")):
            with self.subTest(celsius=celsius):
                self.assertEqual(celsius_to_fahrenheit(celsius), Decimal("-459.67"))

    def test_large_value_converted_exactly(self):
        self.assertEqual(
            celsius_to_fahrenheit("1e30"), Decimal("1800000000000000000000000000032.00")
        )

    def test_package_exports_function(self):
        self.assertIs(package_export, celsius_to_fahrenheit)


class RoundingTests(unittest.TestCase):
    def test_round_half_even(self):
        cases = [
            ("0.025", "32.04"),  # 32.045 -> down to the even 4
            ("0.075", "32.14"),  # 32.135 -> up to the even 4
            ("-0.025", "31.96"),  # 31.955 -> up to the even 6
            ("0.0251", "32.05"),  # just above the midpoint
            ("0.0249", "32.04"),  # just below the midpoint
        ]
        for celsius, expected in cases:
            with self.subTest(celsius=celsius):
                self.assertEqual(str(celsius_to_fahrenheit(celsius)), expected)
                self.assertEqual(str(celsius_to_fahrenheit(Decimal(celsius))), expected)

    def test_float_uses_shortest_repr(self):
        # The binary value of 0.025 is slightly above 0.025 and would round to 32.05.
        self.assertEqual(celsius_to_fahrenheit(0.025), Decimal("32.04"))
        self.assertEqual(celsius_to_fahrenheit(0.1), Decimal("32.18"))

    def test_no_intermediate_rounding(self):
        # 28+ significant digits: rounding before the final step would change the result.
        celsius = "0.0250000000000000000000000000000001"
        self.assertEqual(celsius_to_fahrenheit(celsius), Decimal("32.05"))

    def test_caller_decimal_context_ignored_and_unchanged(self):
        with decimal.localcontext() as ctx:
            ctx.prec = 3
            ctx.rounding = decimal.ROUND_UP
            ctx.traps[decimal.Inexact] = True
            self.assertEqual(celsius_to_fahrenheit("123.456"), Decimal("254.22"))
            self.assertEqual(celsius_to_fahrenheit("0.025"), Decimal("32.04"))
            self.assertEqual(ctx.prec, 3)
            self.assertEqual(ctx.rounding, decimal.ROUND_UP)
            self.assertTrue(ctx.traps[decimal.Inexact])


class RejectionTests(unittest.TestCase):
    def assertRejected(self, values):
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    celsius_to_fahrenheit(value)

    def test_rejects_bool(self):
        self.assertRejected([True, False])

    def test_rejects_nan(self):
        self.assertRejected(
            [float("nan"), Decimal("NaN"), Decimal("sNaN"), Decimal("-NaN"), "nan", "NaN", "sNaN"]
        )

    def test_rejects_infinity(self):
        self.assertRejected(
            [
                float("inf"),
                float("-inf"),
                Decimal("Infinity"),
                Decimal("-Infinity"),
                "Infinity",
                "-Infinity",
                "inf",
                "-inf",
            ]
        )

    def test_rejects_non_numeric(self):
        self.assertRejected(
            [
                None,
                "",
                " ",
                "abc",
                "12abc",
                "1,5",
                "1_000",
                "0x10",
                " 5",
                "5\n",
                "--5",
                "1e",
                ".",
                "١٢",  # Arabic-Indic digits
                b"5",
                [5],
                {"c": 5},
                complex(1, 0),
                Fraction(1, 2),
                object(),
            ]
        )

    def test_rejects_below_absolute_zero(self):
        self.assertRejected(
            [
                -273.16,
                "-273.151",
                Decimal("-273.1500000000000000000000000000001"),
                -274,
                "-1e5000",
                -1e300,
            ]
        )

    def test_rejects_magnitude_at_or_above_proposed_limit(self):
        # Proposed specification decision (see PR): |C| >= 1e995 is refused.
        self.assertRejected(
            [
                "1e995",
                "1" + "0" * 995,
                10**995,
                Decimal("1E+2000"),
                "1e5000",
                "1e999999999999999999",
            ]
        )

    def test_exponent_beyond_decimal_range_raises_value_error(self):
        # Regression (review finding 2): these used to raise decimal.InvalidOperation.
        for value in ["1e1000000000000000000", "1E+99999999999999999999", "-1e1000000000000000000"]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as caught:
                    celsius_to_fahrenheit(value)
                self.assertIs(type(caught.exception), ValueError)

    def test_exponent_beyond_decimal_range_with_caller_trap_disabled(self):
        with decimal.localcontext() as ctx:
            ctx.traps[decimal.InvalidOperation] = False
            with self.assertRaises(ValueError):
                celsius_to_fahrenheit("1e1000000000000000000")
            self.assertEqual(celsius_to_fahrenheit("0e1000000000000000000"), Decimal("32.00"))
            self.assertFalse(ctx.traps[decimal.InvalidOperation])

    def test_error_message_size_is_bounded(self):
        with self.assertRaises(ValueError) as caught:
            celsius_to_fahrenheit("1" * 100000 + "x")
        self.assertLess(len(str(caught.exception)), 200)


class ExtremeExponentTests(unittest.TestCase):
    """Regression tests for review finding 1: no precision limit on valid inputs."""

    def test_zero_with_any_exponent(self):
        for value in [
            Decimal("0E-5000"),
            "0e5000",
            "-0e-5000",
            "-0.0",
            Decimal("0E+999999999999999999"),
            Decimal("-0E-1999999999999999997"),
            "0e1000000000000000000",  # exponent beyond Decimal's range
            "0.000e-1000000000000000000",
        ]:
            with self.subTest(value=value):
                self.assertEqual(str(celsius_to_fahrenheit(value)), "32.00")

    def test_tiny_values_round_to_freezing_point(self):
        for value in [
            "1e-5000",
            "-1e-5000",
            Decimal("1E-1999999999999999997"),
            "1e-1000000000000000000",  # exponent beyond Decimal's range
            "-1e-1000000000000000000",
            "0.000999",
            "-0.00277",
        ]:
            with self.subTest(value=value):
                self.assertEqual(str(celsius_to_fahrenheit(value)), "32.00")
        # Just past the point where the result leaves 32.00.
        self.assertEqual(celsius_to_fahrenheit("0.0028"), Decimal("32.01"))
        self.assertEqual(celsius_to_fahrenheit("-0.0028"), Decimal("31.99"))

    def test_long_fractional_input_converted_exactly(self):
        zeros = "0" * 5000
        self.assertEqual(celsius_to_fahrenheit("0.025" + zeros + "1"), Decimal("32.05"))
        self.assertEqual(celsius_to_fahrenheit("0.025" + zeros), Decimal("32.04"))
        self.assertEqual(celsius_to_fahrenheit("-0.025" + zeros + "1"), Decimal("31.95"))
        self.assertEqual(celsius_to_fahrenheit(Decimal("0.075" + zeros)), Decimal("32.14"))

    def test_largest_supported_magnitude(self):
        wide = decimal.Context(prec=2000)
        expected = Decimal(18 * 10**993 + 32).quantize(Decimal("0.01"), context=wide)
        self.assertEqual(celsius_to_fahrenheit("1e994"), expected)
        self.assertEqual(celsius_to_fahrenheit(10**994), expected)
        # 9...9.5 = 10**995 - 0.5, so F = 1.8 * 10**995 + 31.1 exactly.
        result = celsius_to_fahrenheit("9" * 995 + ".5")
        self.assertEqual(result.as_tuple().exponent, -2)
        hundredths = int(result.scaleb(2, context=wide))
        self.assertEqual(hundredths, 18 * 10**996 + 3110)


if __name__ == "__main__":
    unittest.main()
