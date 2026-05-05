"""Unit tests for config module."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ohtv.config import _get_extra_conversation_paths, _get_api_key


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


class TestGetApiKey:
    """Tests for API key lookup priority."""

    def test_openhands_api_key_takes_priority(self, tmp_path):
        """OPENHANDS_API_KEY should be checked first."""
        with patch.dict(os.environ, {
            "OPENHANDS_API_KEY": "openhands-key",
            "OH_API_KEY": "oh-key"
        }, clear=False):
            result = _get_api_key(tmp_path)
            assert result == "openhands-key"

    def test_oh_api_key_fallback(self, tmp_path):
        """OH_API_KEY should be used if OPENHANDS_API_KEY not set."""
        env = {"OH_API_KEY": "oh-key"}
        # Clear OPENHANDS_API_KEY if it exists
        with patch.dict(os.environ, env, clear=False):
            if "OPENHANDS_API_KEY" in os.environ:
                del os.environ["OPENHANDS_API_KEY"]
            result = _get_api_key(tmp_path)
            assert result == "oh-key"

    def test_file_fallback(self, tmp_path):
        """File fallback when no env vars set."""
        # Create api_key.txt file
        cloud_dir = tmp_path / ".openhands" / "cloud"
        cloud_dir.mkdir(parents=True)
        key_file = cloud_dir / "api_key.txt"
        key_file.write_text("file-key\n")
        
        with patch.dict(os.environ, {}, clear=False):
            # Remove both env vars
            for var in ["OPENHANDS_API_KEY", "OH_API_KEY"]:
                if var in os.environ:
                    del os.environ[var]
            result = _get_api_key(tmp_path)
            assert result == "file-key"

    def test_returns_none_when_nothing_available(self, tmp_path):
        """Returns None when no key source available."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove both env vars
            for var in ["OPENHANDS_API_KEY", "OH_API_KEY"]:
                if var in os.environ:
                    del os.environ[var]
            result = _get_api_key(tmp_path)
            assert result is None

    def test_env_takes_precedence_over_file(self, tmp_path):
        """Env vars should take precedence over file."""
        # Create api_key.txt file
        cloud_dir = tmp_path / ".openhands" / "cloud"
        cloud_dir.mkdir(parents=True)
        key_file = cloud_dir / "api_key.txt"
        key_file.write_text("file-key\n")
        
        with patch.dict(os.environ, {"OPENHANDS_API_KEY": "env-key"}, clear=False):
            result = _get_api_key(tmp_path)
            assert result == "env-key"
