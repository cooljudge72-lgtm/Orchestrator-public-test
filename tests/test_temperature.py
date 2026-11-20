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

    def test_rejects_values_needing_unbounded_precision(self):
        self.assertRejected(["1e5000", "1e-5000", Decimal("1E+2000")])


if __name__ == "__main__":
    unittest.main()
