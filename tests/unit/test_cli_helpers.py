"""Unit tests for CLI helper functions."""

from pathlib import Path

import click
import pytest

from ohtv.cli import _normalize_context_level, _format_path_for_display, CONTEXT_LEVEL_MAP
from ohtv.db.utils import generate_unique_source_names


class TestNormalizeContextLevel:
    """Tests for _normalize_context_level helper (5 levels, Issue #149)."""

    def test_numeric_1_returns_minimal(self):
        assert _normalize_context_level("1") == "minimal"

    def test_numeric_2_returns_outcome(self):
        assert _normalize_context_level("2") == "outcome"

    def test_numeric_3_returns_dialogue(self):
        assert _normalize_context_level("3") == "dialogue"

    def test_numeric_4_returns_actions(self):
        assert _normalize_context_level("4") == "actions"

    def test_numeric_5_returns_observations(self):
        assert _normalize_context_level("5") == "observations"

    def test_minimal_returns_minimal(self):
        assert _normalize_context_level("minimal") == "minimal"

    def test_outcome_returns_outcome(self):
        assert _normalize_context_level("outcome") == "outcome"

    def test_dialogue_returns_dialogue(self):
        assert _normalize_context_level("dialogue") == "dialogue"

    def test_actions_returns_actions(self):
        assert _normalize_context_level("actions") == "actions"

    def test_observations_returns_observations(self):
        assert _normalize_context_level("observations") == "observations"

    def test_none_returns_default_minimal(self):
        assert _normalize_context_level(None) == "minimal"

    def test_none_with_custom_default(self):
        assert _normalize_context_level(None, default="actions") == "actions"

    def test_unknown_value_raises_bad_parameter(self):
        """Issue #149: unknown context levels now raise click.BadParameter
        instead of silently degrading. This prevents typos from masquerading
        as `minimal`."""
        with pytest.raises(click.BadParameter, match="invalid context level"):
            _normalize_context_level("unknown")

    def test_unknown_value_ignores_custom_default(self):
        """The ``default`` arg is only consulted when ``context is None``; an
        explicit invalid value always raises."""
        with pytest.raises(click.BadParameter):
            _normalize_context_level("invalid", default="actions")

    def test_empty_string_raises_bad_parameter(self):
        """Empty string is not None — it represents user-supplied gibberish."""
        with pytest.raises(click.BadParameter):
            _normalize_context_level("")

    def test_old_default_name_raises_with_migration_hint(self):
        """Issue #149: legacy ``default`` is intentionally NOT aliased. A user
        who passes it gets a migration hint pointing at the closest new level."""
        with pytest.raises(click.BadParameter, match=r"retired in #149.*'outcome'"):
            _normalize_context_level("default")

    def test_old_full_name_raises_with_migration_hint(self):
        """Issue #149: legacy ``full`` is intentionally NOT aliased."""
        with pytest.raises(click.BadParameter, match=r"retired in #149.*'observations'"):
            _normalize_context_level("full")

    def test_context_level_map_completeness(self):
        """Verify CONTEXT_LEVEL_MAP has all expected entries (5 levels, #149)."""
        expected_names = {"minimal", "outcome", "dialogue", "actions", "observations"}
        assert set(CONTEXT_LEVEL_MAP.keys()) == {"1", "2", "3", "4", "5"} | expected_names
        assert set(CONTEXT_LEVEL_MAP.values()) == expected_names


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
