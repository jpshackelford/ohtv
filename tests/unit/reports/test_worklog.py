"""Unit tests for worklog report generation."""

import json
import sqlite3
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

import pytest

from ohtv.reports.worklog import (
    WorklogEntry,
    WorklogReport,
    extract_worklog_context,
    generate_worklog,
    query_conversations_for_worklog,
    render_html,
    render_markdown,
    render_text,
    synthesize_worklog_entries,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_db(tmp_path):
    """Create a sample database with test data."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    
    # Create tables
    conn.execute("""
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TEXT,
            source TEXT,
            selected_repository TEXT
        )
    """)
    
    conn.execute("""
        CREATE TABLE conversation_engagement (
            conversation_id TEXT PRIMARY KEY,
            engaged_seconds INTEGER,
            engaged_count INTEGER,
            first_event_ts TEXT,
            last_event_ts TEXT
        )
    """)
    
    conn.execute("""
        CREATE TABLE change_refs (
            conversation_id TEXT,
            change_type TEXT,
            pr_or_issue_number INTEGER,
            title TEXT,
            state TEXT,
            repo_full_name TEXT,
            url TEXT,
            first_mention_idx INTEGER
        )
    """)
    
    # Insert test conversations
    conn.execute("""
        INSERT INTO conversations VALUES
        ('conv1', 'Fix bug in auth', '2026-07-01 10:00:00', 'local', 'owner/repo1'),
        ('conv2', 'Add new feature', '2026-07-01 14:00:00', 'cloud', 'owner/repo2'),
        ('conv3', 'Refactor code', '2026-06-30 16:00:00', 'local', NULL)
    """)
    
    # Insert engagement data
    conn.execute("""
        INSERT INTO conversation_engagement VALUES
        ('conv1', 1800, 3, '2026-07-01 10:00:00', '2026-07-01 10:30:00'),
        ('conv2', 300, 1, '2026-07-01 14:00:00', '2026-07-01 14:05:00'),
        ('conv3', 0, 0, '2026-06-30 16:00:00', '2026-06-30 16:00:00')
    """)
    
    # Insert refs
    conn.execute("""
        INSERT INTO change_refs VALUES
        ('conv1', 'pull_request', 123, 'Fix auth bug', 'merged', 'owner/repo1', 'https://github.com/owner/repo1/pull/123', 0),
        ('conv1', 'issue', 456, 'Auth issue', 'closed', 'owner/repo1', 'https://github.com/owner/repo1/issues/456', 1),
        ('conv2', 'pull_request', 789, 'Add feature', 'open', 'owner/repo2', 'https://github.com/owner/repo2/pull/789', 0)
    """)
    
    conn.commit()
    conn.close()
    
    return db_path


@pytest.fixture
def sample_conv_dir(tmp_path):
    """Create a sample conversation directory with events."""
    conv_dir = tmp_path / "conv1"
    events_dir = conv_dir / "events"
    events_dir.mkdir(parents=True)
    
    # Create sample events
    events = [
        {
            "kind": "MessageEvent",
            "source": "user",
            "message": "Please fix the authentication bug",
        },
        {
            "kind": "MessageEvent",
            "source": "user",
            "message": "It's causing login failures",
        },
        {
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {"command": "git status"},
        },
        {
            "kind": "MessageEvent",
            "source": "agent",
            "message": "I'll investigate the auth code",
        },
        {
            "kind": "ActionEvent",
            "tool_name": "finish",
            "action": {
                "message": "Fixed the session cookie domain mismatch that was causing the auth bug"
            },
        },
    ]
    
    for i, event in enumerate(events):
        event_file = events_dir / f"event-{i:04d}.json"
        event_file.write_text(json.dumps(event))
    
    return conv_dir


# =============================================================================
# Query tests
# =============================================================================


def test_query_conversations_basic(sample_db):
    """Test basic conversation querying."""
    conn = sqlite3.connect(sample_db)
    
    results = query_conversations_for_worklog(conn, since=None, until=None)
    
    assert len(results) == 3
    assert results[0]["id"] == "conv2"  # Sorted by created_at DESC
    assert results[1]["id"] == "conv1"
    assert results[2]["id"] == "conv3"


def test_query_conversations_date_filter(sample_db):
    """Test date filtering."""
    conn = sqlite3.connect(sample_db)
    
    results = query_conversations_for_worklog(
        conn, since=date(2026, 7, 1), until=date(2026, 7, 1)
    )
    
    assert len(results) == 2
    assert results[0]["id"] == "conv2"
    assert results[1]["id"] == "conv1"


def test_query_conversations_engaged_only(sample_db):
    """Test engaged-only filtering."""
    conn = sqlite3.connect(sample_db)
    
    results = query_conversations_for_worklog(conn, engaged_only=True)
    
    assert len(results) == 2
    assert results[0]["id"] == "conv2"
    assert results[1]["id"] == "conv1"
    # conv3 should be excluded (engaged_seconds = 0)


def test_query_conversations_min_engaged(sample_db):
    """Test minimum engaged time filtering."""
    conn = sqlite3.connect(sample_db)
    
    results = query_conversations_for_worklog(conn, min_engaged_seconds=600)
    
    assert len(results) == 1
    assert results[0]["id"] == "conv1"  # Only conv1 has 1800 seconds


def test_query_conversations_repo_filter(sample_db):
    """Test repository filtering."""
    conn = sqlite3.connect(sample_db)
    
    results = query_conversations_for_worklog(conn, repo_filter="repo1")
    
    assert len(results) == 1
    assert results[0]["id"] == "conv1"


def test_query_conversations_source_filter(sample_db):
    """Test source filtering."""
    conn = sqlite3.connect(sample_db)
    
    results = query_conversations_for_worklog(conn, source="cloud")
    
    assert len(results) == 1
    assert results[0]["id"] == "conv2"


# =============================================================================
# Context extraction tests
# =============================================================================


def test_extract_worklog_context(sample_conv_dir, sample_db):
    """Test context extraction from events and database."""
    conn = sqlite3.connect(sample_db)
    
    context = extract_worklog_context(sample_conv_dir, "conv1", conn)
    
    assert len(context["user_messages"]) == 2
    assert "authentication bug" in context["user_messages"][0]
    assert "login failures" in context["user_messages"][1]
    
    assert context["finish_message"] is not None
    assert "Fixed the session cookie domain" in context["finish_message"]
    
    assert len(context["refs"]) == 2
    assert context["refs"][0][0] == "pull_request"
    assert context["refs"][0][1] == 123
    assert context["refs"][1][0] == "issue"


def test_extract_worklog_context_no_finish(tmp_path, sample_db):
    """Test context extraction when there's no finish message."""
    conv_dir = tmp_path / "conv_no_finish"
    events_dir = conv_dir / "events"
    events_dir.mkdir(parents=True)
    
    event = {
        "kind": "MessageEvent",
        "source": "user",
        "message": "Test message",
    }
    (events_dir / "event-0000.json").write_text(json.dumps(event))
    
    conn = sqlite3.connect(sample_db)
    context = extract_worklog_context(conv_dir, "conv1", conn)
    
    assert context["finish_message"] is None
    assert len(context["user_messages"]) == 1


def test_extract_worklog_context_no_events(tmp_path, sample_db):
    """Test context extraction with no events directory."""
    conv_dir = tmp_path / "conv_no_events"
    conv_dir.mkdir()
    
    conn = sqlite3.connect(sample_db)
    context = extract_worklog_context(conv_dir, "conv1", conn)
    
    assert len(context["user_messages"]) == 0
    assert context["finish_message"] is None


# =============================================================================
# LLM synthesis tests
# =============================================================================


def test_synthesize_worklog_entries_success():
    """Test successful LLM synthesis."""
    entries = [
        {
            "id": "conv1",
            "title": "Fix auth bug",
            "context": {
                "user_messages": ["Fix the authentication bug"],
                "finish_message": "Fixed session cookie domain",
                "refs": [("pull_request", 123, "Fix auth bug")],
            },
        }
    ]
    
    mock_response = Mock()
    mock_response.choices = [
        Mock(
            message=Mock(
                content=json.dumps(
                    [
                        {
                            "id": "conv1",
                            "title": "🔧 Fix authentication session bug",
                            "purpose": "Resolved session cookie domain mismatch causing auth failures.",
                        }
                    ]
                )
            )
        )
    ]
    mock_response.metrics = Mock(accumulated_cost=0.0025)
    
    with patch("openhands.sdk.LLM") as mock_llm_class:
        mock_llm = Mock()
        mock_llm.complete.return_value = mock_response
        mock_llm_class.load_from_env.return_value = mock_llm
        
        results, cost = synthesize_worklog_entries(entries)
    
    assert len(results) == 1
    assert "conv1" in results
    assert results["conv1"][0] == "🔧 Fix authentication session bug"
    assert "session cookie domain" in results["conv1"][1]
    assert cost == 0.0025


def test_synthesize_worklog_entries_failure():
    """Test LLM synthesis failure handling."""
    entries = [{"id": "conv1", "context": {}}]
    
    with patch("openhands.sdk.LLM") as mock_llm_class:
        mock_llm = Mock()
        mock_llm.complete.side_effect = Exception("API error")
        mock_llm_class.load_from_env.return_value = mock_llm
        
        results, cost = synthesize_worklog_entries(entries)
    
    assert results == {}
    assert cost == 0.0


# =============================================================================
# Rendering tests
# =============================================================================


def test_render_text():
    """Test text rendering."""
    report = WorklogReport(
        date_label="2026-07-01 Tuesday",
        entries=[
            WorklogEntry(
                conversation_id="conv1",
                title="Fix bug",
                created_at=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
                synthesized_title="🔧 Fix authentication bug",
                purpose="Fixed session cookie domain issue",
                engaged_seconds=1800,
                engagement_display="30 min",
                time_display="10:00 AM EDT",
                refs=[
                    (
                        "pull_request",
                        123,
                        "Fix auth",
                        "merged",
                        "owner/repo",
                        "https://github.com/owner/repo/pull/123",
                    )
                ],
            )
        ],
        total_count=1,
        engaged_count=1,
    )
    
    output = render_text(report)
    
    assert "📋 Worklog for 2026-07-01 Tuesday" in output
    assert "1 conversations" in output
    assert "🔧 Fix authentication bug" in output
    assert "10:00 AM EDT" in output
    assert "30 min" in output
    assert "Fixed session cookie domain issue" in output
    assert "✓ PR #123" in output


def test_render_markdown():
    """Test markdown rendering."""
    report = WorklogReport(
        date_label="2026-07-01 Tuesday",
        entries=[
            WorklogEntry(
                conversation_id="conv1",
                title="Fix bug",
                created_at=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
                synthesized_title="🔧 Fix authentication bug",
                purpose="Fixed session cookie domain issue",
                engaged_seconds=1800,
                engagement_display="30 min",
                time_display="10:00 AM EDT",
                refs=[
                    (
                        "pull_request",
                        123,
                        "Fix auth",
                        "merged",
                        "owner/repo",
                        "https://github.com/owner/repo/pull/123",
                    )
                ],
            )
        ],
        total_count=1,
        engaged_count=1,
    )
    
    output = render_markdown(report)
    
    assert "# 📋 Worklog for 2026-07-01 Tuesday" in output
    assert "**1 conversations**" in output
    assert "## 1. 🔧 Fix authentication bug" in output
    assert "**Time:** 10:00 AM EDT" in output
    assert "**Engagement:** 30 min" in output
    assert "Fixed session cookie domain issue" in output
    assert "[PR #123](https://github.com/owner/repo/pull/123)" in output


def test_render_html():
    """Test HTML rendering."""
    report = WorklogReport(
        date_label="2026-07-01 Tuesday",
        entries=[
            WorklogEntry(
                conversation_id="conv1",
                title="Fix bug",
                created_at=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
                synthesized_title="🔧 Fix authentication bug",
                purpose="Fixed session cookie domain issue",
                engaged_seconds=1800,
                engagement_display="30 min",
                time_display="10:00 AM EDT",
                refs=[
                    (
                        "pull_request",
                        123,
                        "Fix auth",
                        "merged",
                        "owner/repo",
                        "https://github.com/owner/repo/pull/123",
                    )
                ],
            )
        ],
        total_count=1,
        engaged_count=1,
    )
    
    output = render_html(report)
    
    assert "<!DOCTYPE html>" in output
    assert "📋 Worklog for 2026-07-01 Tuesday" in output
    assert "1 conversations" in output
    assert "🔧 Fix authentication bug" in output
    assert "10:00 AM EDT" in output
    assert "30 min" in output
    assert "Fixed session cookie domain issue" in output
    assert '<a href="https://github.com/owner/repo/pull/123">PR #123</a>' in output


def test_render_html_engagement_colors():
    """Test HTML rendering with different engagement colors."""
    # Test gray badge for < 5 min
    entry_short = WorklogEntry(
        conversation_id="conv1",
        title="Short conversation",
        created_at=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
        engaged_seconds=200,
        engagement_display="3 min",
    )
    
    # Test yellow badge for 5-15 min
    entry_medium = WorklogEntry(
        conversation_id="conv2",
        title="Medium conversation",
        created_at=datetime(2026, 7, 1, 11, 0, tzinfo=timezone.utc),
        engaged_seconds=600,
        engagement_display="10 min",
    )
    
    # Test green badge for > 15 min
    entry_long = WorklogEntry(
        conversation_id="conv3",
        title="Long conversation",
        created_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        engaged_seconds=1800,
        engagement_display="30 min",
    )
    
    report = WorklogReport(
        date_label="2026-07-01",
        entries=[entry_short, entry_medium, entry_long],
        total_count=3,
        engaged_count=3,
    )
    
    output = render_html(report)
    
    # Gray for short
    assert "#6c757d" in output
    # Yellow for medium
    assert "#ffc107" in output
    # Green for long
    assert "#28a745" in output


# =============================================================================
# Integration tests
# =============================================================================


def test_generate_worklog_no_synthesis(sample_db, tmp_path):
    """Test worklog generation without LLM synthesis."""
    conn = sqlite3.connect(sample_db)
    conv_base = tmp_path / "conversations"
    conv_base.mkdir()
    
    report = generate_worklog(
        conn=conn,
        conversations_base_dir=conv_base,
        since=date(2026, 7, 1),
        until=date(2026, 7, 1),
        synthesis_model=None,
    )
    
    assert report.total_count == 2
    assert report.engaged_count == 2
    assert len(report.entries) == 2
    assert report.synthesis_cost == 0.0
    
    # Check entries
    assert report.entries[0].conversation_id == "conv2"
    assert report.entries[0].title == "Add new feature"
    assert report.entries[0].synthesized_title is None
    
    assert report.entries[1].conversation_id == "conv1"
    assert report.entries[1].title == "Fix bug in auth"


def test_generate_worklog_with_synthesis(sample_db, sample_conv_dir, tmp_path):
    """Test worklog generation with LLM synthesis."""
    conn = sqlite3.connect(sample_db)
    conv_base = tmp_path / "conversations"
    conv_base.mkdir()
    
    # Copy sample conv dir
    import shutil
    shutil.copytree(sample_conv_dir, conv_base / "conv1")
    
    # Mock LLM response
    mock_response = Mock()
    mock_response.choices = [
        Mock(
            message=Mock(
                content=json.dumps(
                    [
                        {
                            "id": "conv1",
                            "title": "🔧 Fix authentication bug",
                            "purpose": "Resolved session cookie domain mismatch.",
                        }
                    ]
                )
            )
        )
    ]
    mock_response.metrics = Mock(accumulated_cost=0.0025)
    
    with patch("openhands.sdk.LLM") as mock_llm_class:
        mock_llm = Mock()
        mock_llm.complete.return_value = mock_response
        mock_llm_class.load_from_env.return_value = mock_llm
        
        report = generate_worklog(
            conn=conn,
            conversations_base_dir=conv_base,
            since=date(2026, 7, 1),
            until=date(2026, 7, 1),
            synthesis_model="gpt-4o-mini",
        )
    
    assert report.synthesis_cost == 0.0025
    assert report.entries[1].synthesized_title == "🔧 Fix authentication bug"
    assert report.entries[1].purpose == "Resolved session cookie domain mismatch."


def test_generate_worklog_engagement_filters(sample_db, tmp_path):
    """Test worklog generation with engagement filters."""
    conn = sqlite3.connect(sample_db)
    conv_base = tmp_path / "conversations"
    conv_base.mkdir()
    
    # Test engaged_only
    report = generate_worklog(
        conn=conn,
        conversations_base_dir=conv_base,
        engaged_only=True,
        synthesis_model=None,
    )
    assert report.total_count == 2  # conv1 and conv2, not conv3
    
    # Test min_engaged_seconds
    report = generate_worklog(
        conn=conn,
        conversations_base_dir=conv_base,
        min_engaged_seconds=600,
        synthesis_model=None,
    )
    assert report.total_count == 1  # Only conv1
