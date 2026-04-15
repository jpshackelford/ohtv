"""Unit tests for config module."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ohtv.config import _get_extra_conversation_paths


class TestGetExtraConversationPaths:
    def test_empty_config_returns_empty_list(self):
        paths, source = _get_extra_conversation_paths({})
        assert paths == []
        assert source == "default"

    def test_env_var_colon_separated(self):
        with patch.dict(os.environ, {"OHTV_EXTRA_CONVERSATION_PATHS": "/path1:/path2:/path3"}):
            paths, source = _get_extra_conversation_paths({})
            assert len(paths) == 3
            assert paths[0] == Path("/path1")
            assert paths[1] == Path("/path2")
            assert paths[2] == Path("/path3")
            assert source == "env"

    def test_env_var_with_spaces_stripped(self):
        with patch.dict(os.environ, {"OHTV_EXTRA_CONVERSATION_PATHS": " /path1 : /path2 "}):
            paths, source = _get_extra_conversation_paths({})
            assert len(paths) == 2
            assert paths[0] == Path("/path1")
            assert paths[1] == Path("/path2")
            assert source == "env"

    def test_env_var_with_empty_entries_skipped(self):
        with patch.dict(os.environ, {"OHTV_EXTRA_CONVERSATION_PATHS": "/path1::/path2"}):
            paths, source = _get_extra_conversation_paths({})
            assert len(paths) == 2
            assert paths[0] == Path("/path1")
            assert paths[1] == Path("/path2")

    def test_env_var_with_tilde_expansion(self):
        with patch.dict(os.environ, {"OHTV_EXTRA_CONVERSATION_PATHS": "~/experiments"}):
            paths, source = _get_extra_conversation_paths({})
            assert len(paths) == 1
            assert paths[0] == Path.home() / "experiments"
            assert source == "env"

    def test_file_config_string_format(self):
        file_config = {"extra_conversation_paths": "/path1:/path2"}
        paths, source = _get_extra_conversation_paths(file_config)
        assert len(paths) == 2
        assert paths[0] == Path("/path1")
        assert paths[1] == Path("/path2")
        assert source == "file"

    def test_file_config_list_format(self):
        file_config = {"extra_conversation_paths": ["/path1", "/path2", "/path3"]}
        paths, source = _get_extra_conversation_paths(file_config)
        assert len(paths) == 3
        assert paths[0] == Path("/path1")
        assert paths[1] == Path("/path2")
        assert paths[2] == Path("/path3")
        assert source == "file"

    def test_file_config_list_with_tilde_expansion(self):
        file_config = {"extra_conversation_paths": ["~/experiments", "~/archive"]}
        paths, source = _get_extra_conversation_paths(file_config)
        assert len(paths) == 2
        assert paths[0] == Path.home() / "experiments"
        assert paths[1] == Path.home() / "archive"
        assert source == "file"

    def test_env_var_takes_precedence_over_file(self):
        with patch.dict(os.environ, {"OHTV_EXTRA_CONVERSATION_PATHS": "/env/path"}):
            file_config = {"extra_conversation_paths": "/file/path"}
            paths, source = _get_extra_conversation_paths(file_config)
            assert len(paths) == 1
            assert paths[0] == Path("/env/path")
            assert source == "env"

    def test_file_config_invalid_type_returns_empty(self):
        # Test graceful handling of unexpected config types
        file_config = {"extra_conversation_paths": 123}
        paths, source = _get_extra_conversation_paths(file_config)
        assert paths == []
        assert source == "file"
