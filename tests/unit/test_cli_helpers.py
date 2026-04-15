"""Unit tests for CLI helper functions."""

from pathlib import Path

import pytest

from ohtv.cli import _generate_unique_source_names


class TestGenerateUniqueSourceNames:
    def test_empty_list_returns_empty_list(self):
        assert _generate_unique_source_names([]) == []

    def test_single_path_returns_sanitized_name(self):
        paths = [Path("/data/my-experiments")]
        result = _generate_unique_source_names(paths)
        assert result == ["my_experiments"]

    def test_multiple_unique_paths_no_collisions(self):
        paths = [
            Path("/data/experiments"),
            Path("/data/archive"),
            Path("/data/test-data"),
        ]
        result = _generate_unique_source_names(paths)
        assert result == ["experiments", "archive", "test_data"]

    def test_collision_adds_numeric_suffix(self):
        paths = [
            Path("/data/experiments"),
            Path("/other/experiments"),
        ]
        result = _generate_unique_source_names(paths)
        assert result == ["experiments", "experiments_1"]

    def test_multiple_collisions(self):
        paths = [
            Path("/a/test"),
            Path("/b/test"),
            Path("/c/test"),
        ]
        result = _generate_unique_source_names(paths)
        assert result == ["test", "test_1", "test_2"]

    def test_spaces_replaced_with_underscores(self):
        paths = [Path("/data/my experiments")]
        result = _generate_unique_source_names(paths)
        assert result == ["my_experiments"]

    def test_hyphens_replaced_with_underscores(self):
        paths = [Path("/data/my-experiments")]
        result = _generate_unique_source_names(paths)
        assert result == ["my_experiments"]

    def test_case_normalization_to_lowercase(self):
        paths = [Path("/data/MyExperiments")]
        result = _generate_unique_source_names(paths)
        assert result == ["myexperiments"]

    def test_collision_with_mixed_case_and_separators(self):
        paths = [
            Path("/data/My-Experiments"),
            Path("/other/my experiments"),
        ]
        result = _generate_unique_source_names(paths)
        # Both normalize to "my_experiments", so second gets suffix
        assert result == ["my_experiments", "my_experiments_1"]

    def test_reserved_names_allowed(self):
        # As per review suggestion, reserved names like 'local' and 'cloud' 
        # are now allowed since source_name is just a label
        paths = [Path("/data/local"), Path("/data/cloud")]
        result = _generate_unique_source_names(paths)
        assert result == ["local", "cloud"]
