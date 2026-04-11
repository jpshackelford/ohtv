"""Fixtures for integration tests.

Integration tests typically need:
- Sample conversation files on disk (using tmp_path)
- Pre-populated database states
- Both together for end-to-end scenarios
"""

import pytest

from fixtures.conversations import copy_conversation_to
from fixtures.database import (
    DatabaseBuilder,
    create_test_db,
    db_with_github_refs,
    db_with_multi_repo,
    empty_db,
    load_db_state,
)


# Re-export database helpers for use in tests
__all__ = [
    "DatabaseBuilder",
    "create_test_db",
    "empty_db",
    "db_with_github_refs",
    "db_with_multi_repo",
    "load_db_state",
]


@pytest.fixture
def empty_db_conn():
    """Fresh database with only migrations applied."""
    conn = empty_db()
    yield conn
    conn.close()


@pytest.fixture
def db_with_github_refs_conn():
    """Database pre-populated with GitHub repo/issue/PR data."""
    conn = db_with_github_refs()
    yield conn
    conn.close()


@pytest.fixture
def conversations_dir(tmp_path):
    """Temporary directory for conversation files.
    
    Returns the path to use as the conversations root.
    Tests can copy sample conversations here using copy_conversation_to().
    """
    convs = tmp_path / "conversations"
    convs.mkdir()
    return convs


@pytest.fixture
def sample_conversation_with_refs(conversations_dir):
    """Sample conversation with GitHub references, copied to tmp_path.
    
    Returns the path to the conversation directory.
    """
    return copy_conversation_to("conv-with-github-refs", conversations_dir)
