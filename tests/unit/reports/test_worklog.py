"""Unit tests for worklog report generation."""

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ohtv.reports.worklog import (
    WorklogEntry,
    WorklogReport,
    format_outcomes,
    generate_worklog,
    query_conversations_for_worklog,
    query_refs_for_conversation,
    render_html,
    render_markdown,
    render_text,
    synthesize_worklog_entries,
    _format_batch_input,
    _format_date_range,
    _parse_synthesis_response,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create an in-memory database with test schema."""
    conn = sqlite3.connect(":memory:")
    
    # Create conversations table
    conn.execute("""
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TEXT,
            selected_repository TEXT,
            source TEXT
        )
    """)
    
    # Create conversation_engagement table
    conn.execute("""
        CREATE TABLE conversation_engagement (
            conversation_id TEXT PRIMARY KEY,
            engaged_seconds INTEGER NOT NULL DEFAULT 0,
            attention_periods INTEGER NOT NULL DEFAULT 0,
            first_event_ts TEXT,
            last_event_ts TEXT,
            threshold_seconds INTEGER NOT NULL,
            processed_at TEXT NOT NULL,
            event_count INTEGER NOT NULL,
            FOREIGN KEY (conversation_id)
                REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)
    
    # Create change_refs table
    conn.execute("""
        CREATE TABLE change_refs (
            id INTEGER PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            change_type TEXT NOT NULL,
            pr_or_issue_number INTEGER NOT NULL,
            title TEXT,
            state TEXT,
            repo_full_name TEXT,
            url TEXT,
            first_mention_idx INTEGER,
            FOREIGN KEY (conversation_id)
                REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)
    
    return conn


@pytest.fixture
def sample_conversations(db_conn: sqlite3.Connection) -> None:
    """Insert sample conversations into the database."""
    # Conversation 1: engaged
    db_conn.execute("""
        INSERT INTO conversations (id, title, created_at, selected_repository, source)
        VALUES (?, ?, ?, ?, ?)
    """, ("conv001", "Fix auth bug", "2026-07-01T09:00:00+00:00", "owner/repo1", "cloud"))
    
    db_conn.execute("""
        INSERT INTO conversation_engagement 
        (conversation_id, engaged_seconds, attention_periods, first_event_ts, last_event_ts, 
         threshold_seconds, processed_at, event_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, ("conv001", 1680, 3, "2026-07-01T09:00:00+00:00", "2026-07-01T09:28:00+00:00", 
          720, datetime.now(timezone.utc).isoformat(), 50))
    
    # Conversation 2: minimal engagement
    db_conn.execute("""
        INSERT INTO conversations (id, title, created_at, selected_repository, source)
        VALUES (?, ?, ?, ?, ?)
    """, ("conv002", "Update docs", "2026-07-01T14:00:00+00:00", "owner/repo2", "local"))
    
    db_conn.execute("""
        INSERT INTO conversation_engagement 
        (conversation_id, engaged_seconds, attention_periods, first_event_ts, last_event_ts,
         threshold_seconds, processed_at, event_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, ("conv002", 30, 1, "2026-07-01T14:00:00+00:00", "2026-07-01T14:00:30+00:00",
          720, datetime.now(timezone.utc).isoformat(), 5))
    
    # Conversation 3: no engagement data
    db_conn.execute("""
        INSERT INTO conversations (id, title, created_at, selected_repository, source)
        VALUES (?, ?, ?, ?, ?)
    """, ("conv003", "Fire and forget", "2026-07-01T16:00:00+00:00", "owner/repo1", "cloud"))
    
    # Add some refs
    db_conn.execute("""
        INSERT INTO change_refs 
        (conversation_id, change_type, pr_or_issue_number, title, state, repo_full_name, url, first_mention_idx)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, ("conv001", "pull_request", 123, "Fix authentication redirect", "merged", "owner/repo1",
          "https://github.com/owner/repo1/pull/123", 10))
    
    db_conn.execute("""
        INSERT INTO change_refs 
        (conversation_id, change_type, pr_or_issue_number, title, state, repo_full_name, url, first_mention_idx)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, ("conv001", "issue", 45, "Auth redirect loop", "closed", "owner/repo1",
          "https://github.com/owner/repo1/issues/45", 5))
    
    db_conn.commit()


# =============================================================================
# Test query_conversations_for_worklog
# =============================================================================


def test_query_conversations_basic(db_conn: sqlite3.Connection, sample_conversations: None) -> None:
    """Test basic conversation query."""
    conversations = query_conversations_for_worklog(
        db_conn,
        since=date(2026, 7, 1),
        until=date(2026, 7, 1),
    )
    
    assert len(conversations) == 3
    assert conversations[0]["id"] == "conv001"
    assert conversations[1]["id"] == "conv002"
    assert conversations[2]["id"] == "conv003"


def test_query_conversations_engaged_only(db_conn: sqlite3.Connection, sample_conversations: None) -> None:
    """Test filtering to engaged conversations only."""
    conversations = query_conversations_for_worklog(
        db_conn,
        since=date(2026, 7, 1),
        until=date(2026, 7, 1),
        engaged_only=True,
    )
    
    assert len(conversations) == 2  # conv001 and conv002 have engagement
    assert conversations[0]["id"] == "conv001"
    assert conversations[1]["id"] == "conv002"


def test_query_conversations_min_engaged(db_conn: sqlite3.Connection, sample_conversations: None) -> None:
    """Test filtering by minimum engagement threshold."""
    conversations = query_conversations_for_worklog(
        db_conn,
        since=date(2026, 7, 1),
        until=date(2026, 7, 1),
        min_engaged_seconds=300,  # 5 minutes
    )
    
    assert len(conversations) == 1  # Only conv001 has >= 5 min
    assert conversations[0]["id"] == "conv001"
    assert conversations[0]["engaged_seconds"] == 1680


def test_query_conversations_by_repo(db_conn: sqlite3.Connection, sample_conversations: None) -> None:
    """Test filtering by repository."""
    conversations = query_conversations_for_worklog(
        db_conn,
        since=date(2026, 7, 1),
        until=date(2026, 7, 1),
        selected_repository="owner/repo1",
    )
    
    assert len(conversations) == 2  # conv001 and conv003
    assert conversations[0]["id"] == "conv001"
    assert conversations[1]["id"] == "conv003"


# =============================================================================
# Test query_refs_for_conversation
# =============================================================================


def test_query_refs_for_conversation(db_conn: sqlite3.Connection, sample_conversations: None) -> None:
    """Test querying refs for a conversation."""
    refs = query_refs_for_conversation(db_conn, "conv001")
    
    assert len(refs) == 2
    # Should be ordered by first_mention_idx
    assert refs[0][0] == "issue"  # change_type
    assert refs[0][1] == 45  # number
    assert refs[1][0] == "pull_request"
    assert refs[1][1] == 123


def test_query_refs_no_results(db_conn: sqlite3.Connection, sample_conversations: None) -> None:
    """Test querying refs for conversation with no refs."""
    refs = query_refs_for_conversation(db_conn, "conv002")
    assert len(refs) == 0


# =============================================================================
# Test format_outcomes
# =============================================================================


def test_format_outcomes_pr_merged() -> None:
    """Test formatting PR outcomes."""
    refs = [
        ("pull_request", 123, "Fix auth bug", "merged", "owner/repo", "https://github.com/owner/repo/pull/123"),
    ]
    outcomes = format_outcomes(refs)
    
    assert len(outcomes) == 1
    assert "✓" in outcomes[0]
    assert "PR #123" in outcomes[0]
    assert "Fix auth bug" in outcomes[0]
    assert "https://github.com/owner/repo/pull/123" in outcomes[0]


def test_format_outcomes_pr_open() -> None:
    """Test formatting open PR."""
    refs = [
        ("pull_request", 456, "Add feature", "open", "owner/repo", "https://github.com/owner/repo/pull/456"),
    ]
    outcomes = format_outcomes(refs)
    
    assert len(outcomes) == 1
    assert "→" in outcomes[0]
    assert "PR #456" in outcomes[0]


def test_format_outcomes_issue_closed() -> None:
    """Test formatting closed issue."""
    refs = [
        ("issue", 789, "Bug report", "closed", "owner/repo", "https://github.com/owner/repo/issues/789"),
    ]
    outcomes = format_outcomes(refs)
    
    assert len(outcomes) == 1
    assert "✓" in outcomes[0]
    assert "Issue #789" in outcomes[0]


def test_format_outcomes_title_truncation() -> None:
    """Test truncating long titles."""
    long_title = "A" * 100
    refs = [
        ("pull_request", 1, long_title, "open", "owner/repo", "https://github.com/owner/repo/pull/1"),
    ]
    outcomes = format_outcomes(refs)
    
    assert len(outcomes) == 1
    assert len(outcomes[0]) < len(long_title) + 50  # Should be truncated


# =============================================================================
# Test LLM synthesis
# =============================================================================


def test_parse_synthesis_response() -> None:
    """Test parsing LLM synthesis response."""
    response = json.dumps([
        {
            "id": "conv001",
            "title": "Fix Authentication Bug",
            "purpose": "Resolved redirect loop in SSO. Implemented fix and added tests."
        },
        {
            "id": "conv002",
            "title": "Update Documentation",
            "purpose": "Updated API docs with new endpoints."
        }
    ])
    
    results = _parse_synthesis_response(response)
    
    assert len(results) == 2
    assert results["conv001"]["title"] == "Fix Authentication Bug"
    assert "Resolved redirect loop" in results["conv001"]["purpose"]
    assert results["conv002"]["title"] == "Update Documentation"


def test_parse_synthesis_response_with_markdown_fences() -> None:
    """Test parsing response with markdown code fences."""
    response = """```json
{
  "id": "conv001",
  "title": "Test",
  "purpose": "Test purpose"
}
```"""
    
    # Should handle single object (will be parsed as dict, not list)
    # This will raise ValueError as we expect a list
    with pytest.raises(ValueError, match="Expected JSON array"):
        _parse_synthesis_response(response)
    
    # Test with proper array
    response = """```json
[
  {
    "id": "conv001",
    "title": "Test",
    "purpose": "Test purpose"
  }
]
```"""
    
    results = _parse_synthesis_response(response)
    assert len(results) == 1
    assert results["conv001"]["title"] == "Test"


def test_parse_synthesis_response_malformed() -> None:
    """Test parsing malformed JSON."""
    with pytest.raises(ValueError, match="not valid JSON"):
        _parse_synthesis_response("not json")


def test_format_batch_input() -> None:
    """Test formatting batch input for LLM."""
    entry = WorklogEntry(
        conversation_id="conv001",
        title="Original title",
        created_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        user_messages=["User message 1", "User message 2", "User message 3", "User message 4"],
        finish_message="Agent finished successfully",
    )
    
    contexts = {
        "conv001": {
            "user_messages": ["User message 1", "User message 2", "User message 3", "User message 4"],
            "finish_message": "Agent finished successfully",
            "refs": [
                ("pull_request", 123, "PR title", "merged", "owner/repo", "url"),
            ],
        }
    }
    
    batch_input = _format_batch_input([entry], contexts)
    
    assert "conv001" in batch_input
    assert "User message 1" in batch_input
    # Should only include first 3 messages
    assert "User message 3" in batch_input
    assert "User message 4" not in batch_input
    assert "PR title" in batch_input


def test_synthesize_worklog_entries_mock() -> None:
    """Test synthesis with mocked LLM."""
    def mock_llm(system_prompt: str, user_prompt: str) -> tuple[str, float]:
        # Return mock synthesis
        response = json.dumps([
            {
                "id": "conv001",
                "title": "Synthesized Title",
                "purpose": "Synthesized purpose goes here."
            }
        ])
        return response, 0.001
    
    entry = WorklogEntry(
        conversation_id="conv001",
        title="Original title",
        created_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
    )
    
    contexts = {
        "conv001": {
            "user_messages": ["Message 1"],
            "finish_message": None,
            "refs": [],
        }
    }
    
    results, cost = synthesize_worklog_entries(
        [entry],
        contexts,
        model="test-model",
        llm_call=mock_llm,
    )
    
    assert len(results) == 1
    assert results["conv001"]["title"] == "Synthesized Title"
    assert results["conv001"]["purpose"] == "Synthesized purpose goes here."
    assert cost == 0.001


def test_synthesize_worklog_entries_batching() -> None:
    """Test that synthesis batches correctly."""
    call_count = 0
    
    def mock_llm(system_prompt: str, user_prompt: str) -> tuple[str, float]:
        nonlocal call_count
        call_count += 1
        # Parse input to return appropriate ids
        data = json.loads(user_prompt.split("\n\n")[1])
        response = [
            {"id": item["id"], "title": f"Title {item['id']}", "purpose": "Purpose"}
            for item in data
        ]
        return json.dumps(response), 0.001
    
    # Create 25 entries (1 full batch)
    entries = [
        WorklogEntry(
            conversation_id=f"conv{i:03d}",
            title=f"Title {i}",
            created_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        )
        for i in range(25)
    ]
    
    contexts = {
        f"conv{i:03d}": {"user_messages": [], "finish_message": None, "refs": []}
        for i in range(25)
    }
    
    results, cost = synthesize_worklog_entries(
        entries,
        contexts,
        model="test-model",
        batch_size=20,
        llm_call=mock_llm,
    )
    
    assert call_count == 2  # Should batch into 20 + 5
    assert len(results) == 25
    assert cost == 0.002  # 2 calls * 0.001


# =============================================================================
# Test renderers
# =============================================================================


def test_render_text() -> None:
    """Test text renderer."""
    report = WorklogReport(
        date_range="2026-07-01 Wednesday",
        since=date(2026, 7, 1),
        until=date(2026, 7, 1),
        entries=[
            WorklogEntry(
                conversation_id="conv001",
                title="Fix auth bug",
                created_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
                engaged_seconds=1680,
                synthesized_title="Fix Authentication Redirect Loop",
                purpose="Resolved redirect issue affecting SSO users.",
                outcomes=["✓ <a href=\"url\">PR #123</a>: Fix auth"],
            ),
        ],
        total_count=1,
        engaged_count=1,
        generated_at=datetime(2026, 7, 1, 17, 0, tzinfo=timezone.utc),
        synthesis_cost=0.005,
    )
    
    output = render_text(report)
    
    assert "📋 Worklog for 2026-07-01 Wednesday" in output
    assert "1 conversations (1 with meaningful engagement)" in output
    assert "Fix Authentication Redirect Loop" in output
    assert "28 min" in output  # 1680 / 60
    assert "Resolved redirect issue" in output
    assert "PR #123" in output
    assert "$0.0050" in output


def test_render_markdown() -> None:
    """Test markdown renderer."""
    report = WorklogReport(
        date_range="2026-07-01 Wednesday",
        since=date(2026, 7, 1),
        until=date(2026, 7, 1),
        entries=[
            WorklogEntry(
                conversation_id="conv001",
                title="Fix auth bug",
                created_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
                engaged_seconds=300,
                synthesized_title="Fix Auth Bug",
                purpose="Fixed the bug.",
            ),
        ],
        total_count=1,
        engaged_count=0,
        generated_at=datetime(2026, 7, 1, 17, 0, tzinfo=timezone.utc),
    )
    
    output = render_markdown(report)
    
    assert "# 📋 Worklog for 2026-07-01 Wednesday" in output
    assert "## 1. Fix Auth Bug" in output
    assert "**1 conversations**" in output
    assert "Fixed the bug." in output


def test_render_html() -> None:
    """Test HTML renderer."""
    report = WorklogReport(
        date_range="2026-07-01 Wednesday",
        since=date(2026, 7, 1),
        until=date(2026, 7, 1),
        entries=[
            WorklogEntry(
                conversation_id="conv001",
                title="Fix auth bug",
                created_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
                engaged_seconds=900,  # 15 min
                synthesized_title="Fix Auth Bug",
                purpose="Fixed the bug.",
                outcomes=["✓ <a href=\"url\">PR #123</a>: Fixed"],
            ),
        ],
        total_count=1,
        engaged_count=1,
        generated_at=datetime(2026, 7, 1, 17, 0, tzinfo=timezone.utc),
    )
    
    output = render_html(report)
    
    assert "<!DOCTYPE html>" in output
    assert "📋 Worklog for 2026-07-01 Wednesday" in output
    assert "1. Fix Auth Bug" in output
    assert "15 min" in output
    assert "engagement-high" in output  # >= 15 min
    assert "Fixed the bug." in output
    assert "PR #123" in output


def test_render_html_engagement_badges() -> None:
    """Test HTML engagement badge colors."""
    report = WorklogReport(
        date_range="2026-07-01",
        since=date(2026, 7, 1),
        until=date(2026, 7, 1),
        entries=[
            WorklogEntry(
                conversation_id="conv001",
                title="Low engagement",
                created_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
                engaged_seconds=120,  # 2 min
            ),
            WorklogEntry(
                conversation_id="conv002",
                title="Medium engagement",
                created_at=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
                engaged_seconds=480,  # 8 min
            ),
            WorklogEntry(
                conversation_id="conv003",
                title="High engagement",
                created_at=datetime(2026, 7, 1, 11, 0, tzinfo=timezone.utc),
                engaged_seconds=1200,  # 20 min
            ),
        ],
        total_count=3,
        engaged_count=3,
        generated_at=datetime(2026, 7, 1, 17, 0, tzinfo=timezone.utc),
    )
    
    output = render_html(report)
    
    assert "engagement-low" in output  # < 5 min
    assert "engagement-medium" in output  # 5-15 min
    assert "engagement-high" in output  # >= 15 min


# =============================================================================
# Test helpers
# =============================================================================


def test_format_date_range_single_day() -> None:
    """Test formatting a single day."""
    result = _format_date_range(date(2026, 7, 1), date(2026, 7, 1))
    assert "2026-07-01" in result
    assert "Wednesday" in result  # 2026-07-01 is a Wednesday


def test_format_date_range_multiple_days() -> None:
    """Test formatting a date range."""
    result = _format_date_range(date(2026, 7, 1), date(2026, 7, 7))
    assert "2026-07-01 to 2026-07-07" in result


# =============================================================================
# Test integration (generate_worklog)
# =============================================================================


def test_generate_worklog_no_synthesis(db_conn: sqlite3.Connection, sample_conversations: None) -> None:
    """Test generating worklog without synthesis."""
    report = generate_worklog(
        conn=db_conn,
        since=date(2026, 7, 1),
        until=date(2026, 7, 1),
        enable_synthesis=False,
    )
    
    assert report.total_count == 3
    assert report.engaged_count == 1  # Only conv001 has > 60s
    assert len(report.entries) == 3
    assert report.synthesis_cost == 0.0
    
    # Check entries
    assert report.entries[0].conversation_id == "conv001"
    assert report.entries[0].title == "Fix auth bug"
    assert report.entries[0].synthesized_title is None
    assert report.entries[0].purpose is None


def test_generate_worklog_with_engagement_filter(db_conn: sqlite3.Connection, sample_conversations: None) -> None:
    """Test generating worklog with engagement filter."""
    report = generate_worklog(
        conn=db_conn,
        since=date(2026, 7, 1),
        until=date(2026, 7, 1),
        engaged_only=True,
        enable_synthesis=False,
    )
    
    assert report.total_count == 2  # conv001 and conv002 have engagement
    assert report.engaged_count == 1  # Only conv001 has > 60s


def test_generate_worklog_empty(db_conn: sqlite3.Connection) -> None:
    """Test generating worklog with no conversations."""
    report = generate_worklog(
        conn=db_conn,
        since=date(2026, 7, 1),
        until=date(2026, 7, 1),
        enable_synthesis=False,
    )
    
    assert report.total_count == 0
    assert report.engaged_count == 0
    assert len(report.entries) == 0
