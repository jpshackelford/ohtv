"""Unit tests for the filters module."""

import sqlite3
from dataclasses import dataclass

import pytest

from ohtv.filters import (
    filter_conversations_by_ids,
    normalize_conversation_id,
    normalize_ref_pattern,
    parse_pr_filter,
    search_refs_precise,
)
from ohtv.db import RefType, migrate


class TestNormalizeRefPattern:
    def test_removes_space_before_hash(self):
        assert normalize_ref_pattern("repo #123") == "repo#123"

    def test_removes_space_after_hash(self):
        assert normalize_ref_pattern("repo# 123") == "repo#123"

    def test_removes_spaces_around_hash(self):
        assert normalize_ref_pattern("repo # 123") == "repo#123"

    def test_preserves_pattern_without_spaces(self):
        assert normalize_ref_pattern("owner/repo#123") == "owner/repo#123"

    def test_preserves_leading_trailing_spaces(self):
        # We strip in parse_pr_filter, not here
        assert normalize_ref_pattern("  repo#123  ") == "  repo#123  "


class TestParsePrFilter:
    def test_recognizes_github_url(self):
        url = "https://github.com/owner/repo/pull/123"
        search_type, pattern = parse_pr_filter(url)
        assert search_type == "url"
        assert pattern == url

    def test_recognizes_http_url(self):
        url = "http://example.com/pr/123"
        search_type, pattern = parse_pr_filter(url)
        assert search_type == "url"
        assert pattern == url

    def test_recognizes_fqn_pattern(self):
        search_type, pattern = parse_pr_filter("owner/repo#123")
        assert search_type == "fqn"
        assert pattern == "owner/repo#123"

    def test_normalizes_fqn_with_space(self):
        search_type, pattern = parse_pr_filter("repo #123")
        assert search_type == "fqn"
        assert pattern == "repo#123"

    def test_strips_whitespace(self):
        search_type, pattern = parse_pr_filter("  repo#123  ")
        assert search_type == "fqn"
        assert pattern == "repo#123"


class TestNormalizeConversationId:
    def test_removes_dashes(self):
        uuid_with_dashes = "c00dfd80-5402-4d08-b4d4-0d648e33031f"
        assert normalize_conversation_id(uuid_with_dashes) == "c00dfd8054024d08b4d40d648e33031f"

    def test_preserves_id_without_dashes(self):
        uuid_without_dashes = "c00dfd8054024d08b4d40d648e33031f"
        assert normalize_conversation_id(uuid_without_dashes) == "c00dfd8054024d08b4d40d648e33031f"

    def test_handles_empty_string(self):
        assert normalize_conversation_id("") == ""


@dataclass
class FakeConversation:
    id: str


class TestFilterConversationsByIds:
    def test_filters_matching_ids(self):
        conversations = [
            FakeConversation(id="abc123"),
            FakeConversation(id="def456"),
            FakeConversation(id="ghi789"),
        ]
        allowed = {"abc123", "ghi789"}
        result = filter_conversations_by_ids(conversations, allowed)
        assert len(result) == 2
        assert result[0].id == "abc123"
        assert result[1].id == "ghi789"

    def test_normalizes_ids_with_dashes(self):
        # Conversation has dashes, allowed set doesn't
        conversations = [
            FakeConversation(id="c00dfd80-5402-4d08-b4d4-0d648e33031f"),
        ]
        allowed = {"c00dfd8054024d08b4d40d648e33031f"}
        result = filter_conversations_by_ids(conversations, allowed)
        assert len(result) == 1

    def test_normalizes_allowed_ids_with_dashes(self):
        # Conversation doesn't have dashes, allowed set does
        conversations = [
            FakeConversation(id="c00dfd8054024d08b4d40d648e33031f"),
        ]
        allowed = {"c00dfd80-5402-4d08-b4d4-0d648e33031f"}
        result = filter_conversations_by_ids(conversations, allowed)
        assert len(result) == 1

    def test_returns_empty_when_no_matches(self):
        conversations = [FakeConversation(id="abc123")]
        allowed = {"xyz789"}
        result = filter_conversations_by_ids(conversations, allowed)
        assert len(result) == 0

    def test_handles_empty_conversations(self):
        result = filter_conversations_by_ids([], {"abc123"})
        assert len(result) == 0

    def test_handles_empty_allowed_set(self):
        conversations = [FakeConversation(id="abc123")]
        result = filter_conversations_by_ids(conversations, set())
        assert len(result) == 0


@pytest.fixture
def db_conn():
    """Create an in-memory database with schema for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    return conn


class TestSearchRefsPrecise:
    def test_matches_exact_pr_number(self, db_conn):
        # Insert test PRs
        db_conn.execute(
            "INSERT INTO refs (ref_type, url, fqn, display_name) VALUES (?, ?, ?, ?)",
            ("pr", "https://github.com/owner/repo/pull/1", "owner/repo#1", "repo #1"),
        )
        db_conn.execute(
            "INSERT INTO refs (ref_type, url, fqn, display_name) VALUES (?, ?, ?, ?)",
            ("pr", "https://github.com/owner/repo/pull/10", "owner/repo#10", "repo #10"),
        )
        db_conn.execute(
            "INSERT INTO refs (ref_type, url, fqn, display_name) VALUES (?, ?, ?, ?)",
            ("pr", "https://github.com/owner/repo/pull/100", "owner/repo#100", "repo #100"),
        )
        db_conn.commit()
        
        # Search for #1 should only match #1, not #10 or #100
        results = search_refs_precise(db_conn, "repo#1", RefType.PR)
        assert len(results) == 1
        assert results[0].fqn == "owner/repo#1"
    
    def test_matches_exact_pr_number_with_full_fqn(self, db_conn):
        db_conn.execute(
            "INSERT INTO refs (ref_type, url, fqn, display_name) VALUES (?, ?, ?, ?)",
            ("pr", "https://github.com/owner/repo/pull/10", "owner/repo#10", "repo #10"),
        )
        db_conn.execute(
            "INSERT INTO refs (ref_type, url, fqn, display_name) VALUES (?, ?, ?, ?)",
            ("pr", "https://github.com/owner/repo/pull/100", "owner/repo#100", "repo #100"),
        )
        db_conn.commit()
        
        # Full FQN search
        results = search_refs_precise(db_conn, "owner/repo#10", RefType.PR)
        assert len(results) == 1
        assert results[0].fqn == "owner/repo#10"
    
    def test_returns_empty_for_no_match(self, db_conn):
        db_conn.execute(
            "INSERT INTO refs (ref_type, url, fqn, display_name) VALUES (?, ?, ?, ?)",
            ("pr", "https://github.com/owner/repo/pull/10", "owner/repo#10", "repo #10"),
        )
        db_conn.commit()
        
        results = search_refs_precise(db_conn, "repo#999", RefType.PR)
        assert len(results) == 0
    
    def test_filters_by_ref_type(self, db_conn):
        # Insert both PR and issue with same number
        db_conn.execute(
            "INSERT INTO refs (ref_type, url, fqn, display_name) VALUES (?, ?, ?, ?)",
            ("pr", "https://github.com/owner/repo/pull/1", "owner/repo#1", "repo #1"),
        )
        db_conn.execute(
            "INSERT INTO refs (ref_type, url, fqn, display_name) VALUES (?, ?, ?, ?)",
            ("issue", "https://github.com/owner/repo/issues/1", "owner/repo#1", "repo #1"),
        )
        db_conn.commit()
        
        # Should only find PR
        results = search_refs_precise(db_conn, "repo#1", RefType.PR)
        assert len(results) == 1
        assert results[0].ref_type == RefType.PR
        
        # Should only find issue
        results = search_refs_precise(db_conn, "repo#1", RefType.ISSUE)
        assert len(results) == 1
        assert results[0].ref_type == RefType.ISSUE
