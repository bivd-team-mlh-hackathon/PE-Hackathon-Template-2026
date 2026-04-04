"""
Unit tests for app/utils.py — pure Python, no database or network required.
These run in the 'unit' CI job with zero service dependencies.
"""

import pytest

from app.utils import RESERVED, is_valid_custom_code, to_base62


class TestBase62:
    def test_zero(self):
        assert to_base62(0) == "0"

    def test_single_digit(self):
        assert to_base62(9) == "9"

    def test_letter_range(self):
        # Index 10 maps to 'a'
        assert to_base62(10) == "a"
        # Index 35 maps to 'z'
        assert to_base62(35) == "z"
        # Index 36 maps to 'A'
        assert to_base62(36) == "A"
        # Index 61 maps to 'Z'
        assert to_base62(61) == "Z"

    def test_two_digit(self):
        # 62 = 1×62 + 0 → "10"
        assert to_base62(62) == "10"

    def test_known_value(self):
        # 11157 = 2×62² + 55×62 + 59 → "2TX"  (from system design plan §Base 62)
        # 2×3844 + 55×62 + 59 = 7688 + 3410 + 59 = 11157
        assert to_base62(11157) == "2TX"

    def test_uniqueness(self):
        # Different IDs must produce different codes
        codes = {to_base62(i) for i in range(1, 200)}
        assert len(codes) == 199

    def test_monotonically_longer(self):
        # Codes grow in length as ID grows (property of base conversion)
        code_62 = to_base62(62)  # 2 chars
        code_3844 = to_base62(3844)  # 3 chars (62^2)
        assert len(code_62) <= len(code_3844)

    def test_large_id(self):
        # 7-char codes handle ~3.5 trillion URLs (plan §Hash value length)
        code = to_base62(3_521_614_606_207)
        assert len(code) == 7

    def test_only_valid_chars(self):
        valid = set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
        for i in [1, 62, 500, 99999, 2_009_215_674_938]:
            assert all(c in valid for c in to_base62(i))


class TestIsValidCustomCode:
    def test_valid_alphanumeric(self):
        ok, err = is_valid_custom_code("mylink")
        assert ok is True
        assert err == ""

    def test_valid_with_hyphen_underscore(self):
        ok, _ = is_valid_custom_code("my-link_2026")
        assert ok is True

    def test_empty_code_rejected(self):
        ok, err = is_valid_custom_code("")
        assert ok is False
        assert "empty" in err.lower()

    def test_too_long_rejected(self):
        ok, err = is_valid_custom_code("a" * 21)
        assert ok is False
        assert "20" in err

    def test_exactly_20_chars_accepted(self):
        ok, _ = is_valid_custom_code("a" * 20)
        assert ok is True

    def test_special_chars_rejected(self):
        for bad in ["my link", "link!", "link@here", "link/path"]:
            ok, err = is_valid_custom_code(bad)
            assert ok is False, f"Expected rejection for: {bad}"
            assert "only contain" in err

    @pytest.mark.parametrize("reserved", list(RESERVED))
    def test_reserved_paths_rejected(self, reserved):
        ok, err = is_valid_custom_code(reserved)
        assert ok is False
        assert "reserved" in err.lower()

    def test_case_insensitive_reserved_check(self):
        ok, _ = is_valid_custom_code("URLs")
        assert ok is False

    def test_numbers_only_valid(self):
        ok, _ = is_valid_custom_code("12345")
        assert ok is True
