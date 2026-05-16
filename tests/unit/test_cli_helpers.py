"""Unit tests for CLI helper functions."""

from pathlib import Path
from unittest.mock import patch

import pytest

from ohtv.cli import _normalize_context_level, _format_path_for_display, CONTEXT_LEVEL_MAP
from ohtv.db.utils import generate_unique_source_names


class TestNormalizeContextLevel:
    """Tests for _normalize_context_level helper."""

    def test_numeric_1_returns_minimal(self):
        assert _normalize_context_level("1") == "minimal"

    def test_numeric_2_returns_default(self):
        assert _normalize_context_level("2") == "default"

    def test_numeric_3_returns_full(self):
        assert _normalize_context_level("3") == "full"

    def test_minimal_returns_minimal(self):
        assert _normalize_context_level("minimal") == "minimal"

    def test_default_returns_default(self):
        assert _normalize_context_level("default") == "default"

    def test_full_returns_full(self):
        assert _normalize_context_level("full") == "full"

    def test_none_returns_default_minimal(self):
        assert _normalize_context_level(None) == "minimal"

    def test_none_with_custom_default(self):
        assert _normalize_context_level(None, default="full") == "full"

    def test_unknown_value_returns_default(self):
        assert _normalize_context_level("unknown") == "minimal"

    def test_unknown_value_with_custom_default(self):
        assert _normalize_context_level("invalid", default="full") == "full"

    def test_empty_string_returns_default(self):
        assert _normalize_context_level("") == "minimal"

    def test_context_level_map_completeness(self):
        """Verify CONTEXT_LEVEL_MAP has all expected entries."""
        assert set(CONTEXT_LEVEL_MAP.keys()) == {"1", "2", "3", "minimal", "default", "full"}
        assert set(CONTEXT_LEVEL_MAP.values()) == {"minimal", "default", "full"}


class TestGenerateUniqueSourceNames:
    def test_empty_list_returns_empty_list(self):
        assert generate_unique_source_names([]) == []

    def test_single_path_returns_sanitized_name(self):
        paths = [Path("/data/my-experiments")]
        result = generate_unique_source_names(paths)
        assert result == ["my_experiments"]

    def test_multiple_unique_paths_no_collisions(self):
        paths = [
            Path("/data/experiments"),
            Path("/data/archive"),
            Path("/data/test-data"),
        ]
        result = generate_unique_source_names(paths)
        assert result == ["experiments", "archive", "test_data"]

    def test_collision_adds_numeric_suffix(self):
        paths = [
            Path("/data/experiments"),
            Path("/other/experiments"),
        ]
        result = generate_unique_source_names(paths)
        assert result == ["experiments", "experiments_1"]

    def test_multiple_collisions(self):
        paths = [
            Path("/a/test"),
            Path("/b/test"),
            Path("/c/test"),
        ]
        result = generate_unique_source_names(paths)
        assert result == ["test", "test_1", "test_2"]

    def test_spaces_replaced_with_underscores(self):
        paths = [Path("/data/my experiments")]
        result = generate_unique_source_names(paths)
        assert result == ["my_experiments"]

    def test_hyphens_replaced_with_underscores(self):
        paths = [Path("/data/my-experiments")]
        result = generate_unique_source_names(paths)
        assert result == ["my_experiments"]

    def test_case_normalization_to_lowercase(self):
        paths = [Path("/data/MyExperiments")]
        result = generate_unique_source_names(paths)
        assert result == ["myexperiments"]

    def test_collision_with_mixed_case_and_separators(self):
        paths = [
            Path("/data/My-Experiments"),
            Path("/other/my experiments"),
        ]
        result = generate_unique_source_names(paths)
        assert result == ["my_experiments", "my_experiments_1"]

    def test_reserved_names_get_suffix(self):
        """Reserved names ('local', 'cloud') get _1 suffix to avoid collision"""
        paths = [Path("/data/local"), Path("/data/cloud")]
        result = generate_unique_source_names(paths)
        assert result == ["local_1", "cloud_1"]


class TestFormatPathForDisplay:
    """Tests for _format_path_for_display helper."""

    def test_replaces_home_with_tilde(self):
        home = str(Path.home())
        path = f"{home}/.openhands/conversations"
        assert _format_path_for_display(path) == "~/.openhands/conversations"

    def test_preserves_path_not_in_home(self):
        path = "/var/data/conversations"
        assert _format_path_for_display(path) == "/var/data/conversations"

    def test_preserves_relative_path(self):
        path = "data/conversations"
        assert _format_path_for_display(path) == "data/conversations"

    def test_exact_home_directory(self):
        home = str(Path.home())
        assert _format_path_for_display(home) == "~"

    def test_path_similar_to_home_not_replaced(self):
        """Path that starts with same chars but isn't under home."""
        home = str(Path.home())
        # Create a path that starts with home's characters but has more before /
        fake_path = home + "_extra/data"
        # This should NOT be replaced since it's not actually under home
        assert _format_path_for_display(fake_path) == fake_path
