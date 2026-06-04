"""Unit tests for :func:`ohtv.filters.parse_duration_to_seconds` (Issue #170).

Covers the duration string parser that backs ``--min-engaged``: tokenised
``Ns`` / ``Nm`` / ``Nh`` / combinations, bare-number-is-minutes, case
insensitivity, rejection of negatives and nonsense.
"""

from __future__ import annotations

import pytest

from ohtv.filters import parse_duration_to_seconds


class TestParseDurationBasicUnits:
    def test_seconds(self):
        assert parse_duration_to_seconds("30s") == 30

    def test_minutes(self):
        assert parse_duration_to_seconds("5m") == 300

    def test_hours(self):
        assert parse_duration_to_seconds("1h") == 3600

    def test_two_hours(self):
        assert parse_duration_to_seconds("2h") == 7200

    def test_zero_seconds(self):
        # AC: ``--min-engaged 0s`` is a no-op (every engaged row meets the
        # threshold). Documented but not rejected.
        assert parse_duration_to_seconds("0s") == 0


class TestParseDurationCombinations:
    def test_hours_and_minutes(self):
        assert parse_duration_to_seconds("1h30m") == 5400

    def test_hours_minutes_and_seconds(self):
        assert parse_duration_to_seconds("1h30m45s") == 5445

    def test_minutes_and_seconds(self):
        assert parse_duration_to_seconds("2m30s") == 150

    def test_ninety_seconds_does_not_normalize(self):
        # "90s" is just 90 seconds — no normalization happens at parse time.
        assert parse_duration_to_seconds("90s") == 90


class TestParseDurationBareNumber:
    """Bare numbers are interpreted as **minutes** — that's the UX rule."""

    def test_bare_integer_is_minutes(self):
        # "5" == "5m" == 300 seconds.
        assert parse_duration_to_seconds("5") == 300

    def test_bare_float_is_minutes(self):
        # 2.5 minutes == 150 seconds.
        assert parse_duration_to_seconds("2.5") == 150

    def test_bare_zero_is_zero_seconds(self):
        # AC: ``--min-engaged 0`` is documented as a no-op (every row passes).
        assert parse_duration_to_seconds("0") == 0

    def test_bare_zero_dot_zero(self):
        assert parse_duration_to_seconds("0.0") == 0


class TestParseDurationCaseInsensitive:
    def test_uppercase_minutes(self):
        assert parse_duration_to_seconds("5M") == 300

    def test_uppercase_seconds(self):
        assert parse_duration_to_seconds("30S") == 30

    def test_uppercase_hours(self):
        assert parse_duration_to_seconds("1H") == 3600

    def test_mixed_case_combination(self):
        assert parse_duration_to_seconds("1H30M") == 5400

    def test_mixed_case_combination_lower_h(self):
        assert parse_duration_to_seconds("1h30M") == 5400


class TestParseDurationWhitespace:
    def test_leading_whitespace_stripped(self):
        assert parse_duration_to_seconds("  5m") == 300

    def test_trailing_whitespace_stripped(self):
        assert parse_duration_to_seconds("5m  ") == 300

    def test_both_sides_stripped(self):
        assert parse_duration_to_seconds("  1h30m  ") == 5400


class TestParseDurationRejection:
    @pytest.mark.parametrize("value", ["", "   ", "\t"])
    def test_empty_rejected(self, value):
        with pytest.raises(ValueError):
            parse_duration_to_seconds(value)

    def test_negative_seconds_rejected(self):
        with pytest.raises(ValueError, match="negative"):
            parse_duration_to_seconds("-5s")

    def test_negative_minutes_rejected(self):
        with pytest.raises(ValueError, match="negative"):
            parse_duration_to_seconds("-5m")

    def test_negative_bare_number_rejected(self):
        # Issue #170 AC: ``--min-engaged -5m`` and ``-5`` are both invalid.
        with pytest.raises(ValueError, match="negative"):
            parse_duration_to_seconds("-5")

    @pytest.mark.parametrize(
        "value",
        [
            "abc",
            "5x",        # unknown unit
            "5m garbage",  # trailing garbage
            "garbage 5m",  # leading garbage
            "5m5",         # trailing number with no unit
            "m",           # unit with no number
            "h30m",        # unit with no number at start
            "5..5m",       # malformed number
            "5m5h-",       # malformed suffix
        ],
    )
    def test_invalid_input_rejected(self, value):
        with pytest.raises(ValueError):
            parse_duration_to_seconds(value)

    def test_non_string_rejected(self):
        with pytest.raises(ValueError):
            parse_duration_to_seconds(300)  # type: ignore[arg-type]


class TestParseDurationReturnType:
    def test_returns_int(self):
        result = parse_duration_to_seconds("5m")
        assert isinstance(result, int)

    def test_float_minutes_truncates_to_int(self):
        # 1.5 minutes == 90 seconds (exact). 0.1 minutes == 6 seconds (exact).
        # Pick a value with a non-exact float to make sure we don't blow up.
        assert parse_duration_to_seconds("0.1") == 6
        assert isinstance(parse_duration_to_seconds("0.1"), int)
