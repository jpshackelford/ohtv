"""Tests for database utility functions."""

from pathlib import Path

import pytest

from ohtv.db.utils import generate_unique_source_names, RESERVED_SOURCES


class TestGenerateUniqueSourceNames:
    """Tests for generate_unique_source_names function."""

    def test_empty_list(self):
        """Should return empty list for empty input."""
        assert generate_unique_source_names([]) == []

    def test_single_path(self, tmp_path):
        """Should generate single name without suffix."""
        path = tmp_path / "my_project"
        result = generate_unique_source_names([path])
        assert result == ["my_project"]

    def test_unique_paths(self, tmp_path):
        """Should generate names without suffixes for unique paths."""
        paths = [
            tmp_path / "project1",
            tmp_path / "project2",
            tmp_path / "project3",
        ]
        result = generate_unique_source_names(paths)
        assert result == ["project1", "project2", "project3"]

    def test_collision_within_paths(self, tmp_path):
        """Should add suffix for duplicate names."""
        paths = [
            tmp_path / "proj1" / "conversations",
            tmp_path / "proj2" / "conversations",
            tmp_path / "proj3" / "conversations",
        ]
        result = generate_unique_source_names(paths)
        assert len(result) == 3
        assert len(set(result)) == 3  # All unique
        assert result[0] == "conversations"
        assert result[1] == "conversations_1"
        assert result[2] == "conversations_2"

    def test_collision_with_reserved_local(self, tmp_path):
        """Should add suffix when path name collides with 'local' reserved source."""
        path = tmp_path / "local"
        result = generate_unique_source_names([path])
        assert result == ["local_1"]
        assert result[0] not in RESERVED_SOURCES

    def test_collision_with_reserved_cloud(self, tmp_path):
        """Should add suffix when path name collides with 'cloud' reserved source."""
        path = tmp_path / "cloud"
        result = generate_unique_source_names([path])
        assert result == ["cloud_1"]
        assert result[0] not in RESERVED_SOURCES

    def test_multiple_collisions_with_reserved(self, tmp_path):
        """Should handle multiple paths with reserved names."""
        paths = [
            tmp_path / "local",
            tmp_path / "cloud",
            tmp_path / "other",
        ]
        result = generate_unique_source_names(paths)
        assert len(result) == 3
        assert len(set(result)) == 3  # All unique
        # Reserved names should get suffixes
        assert "local" not in result
        assert "cloud" not in result
        assert "local_1" in result
        assert "cloud_1" in result
        assert "other" in result

    def test_normalizes_spaces_and_hyphens(self, tmp_path):
        """Should normalize spaces and hyphens to underscores."""
        paths = [
            tmp_path / "my project",
            tmp_path / "my-project",
        ]
        result = generate_unique_source_names(paths)
        assert len(result) == 2
        assert len(set(result)) == 2  # All unique
        # Both should normalize to "my_project" but get different suffixes
        assert result[0] == "my_project"
        assert result[1] == "my_project_1"

    def test_case_insensitive_collision(self, tmp_path):
        """Should treat names case-insensitively."""
        paths = [
            tmp_path / "Project",
            tmp_path / "PROJECT",
        ]
        result = generate_unique_source_names(paths)
        assert len(result) == 2
        assert len(set(result)) == 2  # All unique
        # Both should normalize to lowercase and get different suffixes
        assert result[0] == "project"
        assert result[1] == "project_1"

    def test_complex_collision_scenario(self, tmp_path):
        """Should handle complex scenario with multiple collision types."""
        paths = [
            tmp_path / "local",  # Reserved
            tmp_path / "cloud",  # Reserved
            tmp_path / "conversations",  # Normal
            tmp_path / "other" / "conversations",  # Collision with #2
            tmp_path / "LOCAL",  # Collision with #0 (case-insensitive)
        ]
        result = generate_unique_source_names(paths)
        assert len(result) == 5
        assert len(set(result)) == 5  # All unique
        # No result should match reserved sources
        assert "local" not in result
        assert "cloud" not in result
        # Should have suffixes to avoid collisions
        assert "local_1" in result
        assert "local_2" in result
        assert "cloud_1" in result
        assert "conversations" in result
        assert "conversations_1" in result
