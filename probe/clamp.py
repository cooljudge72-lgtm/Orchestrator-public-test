"""PROBE - DO NOT MERGE. Synthetic code for the Codex auto-review integration test.

This file exists only to give the automatic reviewer something concrete to
review. It is never meant to reach main.
"""


def clamp(value, low, high):
    """Return ``value`` limited to the closed range [low, high].

    Raises ValueError if ``low`` is greater than ``high`` or if any argument
    is not a finite int or float (bool is rejected).
    """
    if value < low:
        return low
    if value > high:
        return high
    return value
