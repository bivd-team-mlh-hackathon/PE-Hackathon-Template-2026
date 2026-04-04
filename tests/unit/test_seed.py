"""
Unit tests for app/seed.py helpers — pure Python, no database required.
"""

import pytest

from app.seed import _parse_bool


class TestParseBool:
    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "YES"])
    def test_truthy_values(self, value):
        assert _parse_bool(value) is True

    @pytest.mark.parametrize(
        "value", ["false", "False", "FALSE", "0", "no", "NO", "", "maybe", "2"]
    )
    def test_falsy_values(self, value):
        assert _parse_bool(value) is False

    def test_strips_whitespace(self):
        assert _parse_bool("  true  ") is True
        assert _parse_bool("  false  ") is False

    def test_returns_bool_type(self):
        assert type(_parse_bool("true")) is bool
        assert type(_parse_bool("false")) is bool
