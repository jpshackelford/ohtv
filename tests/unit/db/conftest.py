"""Fixtures for database unit tests."""

import sqlite3

import pytest

from ohtv.db import migrate
from ohtv.db.stores import (
    ConversationStore,
    LinkStore,
    ReferenceStore,
    RepoStore,
    StageStore,
)


@pytest.fixture
def db_conn():
    """Fresh in-memory database with migrations applied.
    
    Each test gets an isolated database. This is slightly slower than
    sharing a connection, but ensures tests cannot affect each other.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    yield conn
    conn.close()


@pytest.fixture
def conversation_store(db_conn):
    """ConversationStore backed by the test database."""
    return ConversationStore(db_conn)


@pytest.fixture
def repo_store(db_conn):
    """RepoStore backed by the test database."""
    return RepoStore(db_conn)


@pytest.fixture
def reference_store(db_conn):
    """ReferenceStore backed by the test database."""
    return ReferenceStore(db_conn)


@pytest.fixture
def link_store(db_conn):
    """LinkStore backed by the test database."""
    return LinkStore(db_conn)


@pytest.fixture
def stage_store(db_conn):
    """StageStore backed by the test database."""
    return StageStore(db_conn)
