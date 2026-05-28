"""Regression tests for issue #129.

`ohtv gen objs` (multi-conversation mode) was re-reporting the same worker
conversations as "needs analysis" on every run because the write path stored
results under the *auto-promoted* ``context_level`` key while the read path
looked them up under the originally-*requested* level. The fix writes an
alias cache_key entry under the requested level pointing at the same
analysis content, so subsequent lookups at the requested level hit the cache.

These tests pin the two behaviors called out in the issue's Acceptance
Criteria:

* A second ``analyze_objectives(..., context="minimal")`` call against a
  worker-style fixture (no user messages, finish action present) hits the
  cache (``from_cache=True``) and does NOT invoke the LLM.
* ``_count_uncached_conversations_fast`` reports 0 uncached conversations
  after a single analyze run on the same fixture.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ohtv_dir(monkeypatch, tmp_path):
    """Redirect all ohtv-generated state (cache, DB, logs) into ``tmp_path``."""

    ohtv_root = tmp_path / "ohtv_home"
    ohtv_root.mkdir()
    monkeypatch.setenv("OHTV_DIR", str(ohtv_root))
    return ohtv_root


@pytest.fixture
def worker_conv_dir(tmp_path):
    """Build a worker-style conversation fixture on disk.

    Worker conversations (orchestrator-spawned) have NO user MessageEvent but
    DO have at least one agent ActionEvent. This is the exact shape that
    triggers the ``minimal`` -> ``default`` auto-promotion inside
    ``analyze_objectives``: the legacy transcript builder emits zero items at
    ``minimal`` (user messages only) but emits the ``finish`` action at
    ``default``/``full``, so the loop in objectives.py promotes the context.
    """

    # Use a hex name (no dashes) so the database normalization is a no-op.
    conv_dir = tmp_path / "conversations" / "abcdef0123456789abcdef0123456789"
    events_dir = conv_dir / "events"
    events_dir.mkdir(parents=True)

    # Single ActionEvent: agent finish call. Only included at default+ levels.
    finish_event = {
        "id": "evt-0001",
        "timestamp": "2024-01-01T00:00:00Z",
        "source": "agent",
        "kind": "ActionEvent",
        "tool_name": "finish",
        "tool_call_id": "call-0001",
        "action": {
            "message": "Done.",
        },
    }
    (events_dir / "event-00001-finish.json").write_text(json.dumps(finish_event))
    return conv_dir


@pytest.fixture
def mock_llm():
    """Patch the OpenHands SDK LLM with a recording mock.

    Returns the ``completion`` MagicMock so tests can assert call counts.
    """

    completion_mock = MagicMock()

    # Build a stable JSON response that satisfies the brief/no-assess prompt.
    response_text = MagicMock()
    response_text.text = json.dumps({"goal": "Test worker objective"})

    response = MagicMock()
    response.message.content = [response_text]
    response.metrics.accumulated_cost = 0.0012
    completion_mock.return_value = response

    llm_instance = MagicMock()
    llm_instance.model = "test-model"
    llm_instance.api_key = "test-key"
    llm_instance.base_url = None
    llm_instance.timeout = 60
    llm_instance.completion = completion_mock

    # ``openhands.sdk.LLM`` is imported lazily INSIDE
    # ``analyze_objectives``; patching at ``openhands.sdk.LLM`` therefore
    # covers both ``LLM.load_from_env()`` and the ``LLM(...)`` re-init branch.
    with patch("openhands.sdk.LLM") as llm_class:
        llm_class.load_from_env.return_value = llm_instance
        # If model arg is passed, the code does ``LLM(model=model, ...)``;
        # route that to the same instance so the recording stays accurate.
        llm_class.return_value = llm_instance
        yield completion_mock


# ---------------------------------------------------------------------------
# Test A — cache hit after auto-promotion
# ---------------------------------------------------------------------------


def test_minimal_request_hits_cache_after_auto_promotion(
    ohtv_dir, worker_conv_dir, mock_llm
):
    """AC4: a worker conversation analyzed at ``context="minimal"`` once must
    hit the cache on the second call with the same args (no second LLM call).

    The internal promotion takes the effective level to ``default`` (or
    higher). Before the fix, the second call would compute a ``minimal``
    cache key, miss the (``default``-keyed) stored entry, and re-invoke the
    LLM.
    """

    from ohtv.analysis.objectives import analyze_objectives

    # First call — promotes minimal -> default, calls LLM once, caches result.
    result1 = analyze_objectives(
        worker_conv_dir,
        model="test-model",
        context="minimal",
        detail="brief",
        assess=False,
    )

    assert result1.from_cache is False, "first call should be a cache miss"
    assert mock_llm.call_count == 1, (
        "first analyze should invoke the LLM exactly once"
    )
    # Sanity: auto-promotion happened (effective context is not 'minimal').
    assert result1.analysis.context_level != "minimal", (
        "fixture is expected to trigger auto-promotion; effective level must "
        "differ from the requested 'minimal' to exercise the alias write"
    )

    # Second call — must hit the cache via the alias key, NOT invoke the LLM.
    result2 = analyze_objectives(
        worker_conv_dir,
        model="test-model",
        context="minimal",
        detail="brief",
        assess=False,
    )

    assert result2.from_cache is True, (
        "second call at the same requested context must hit the cache "
        "(the alias write under the requested level enables this; see #129)"
    )
    assert mock_llm.call_count == 1, (
        "LLM must not be invoked a second time when the alias cache hit fires"
    )

    # The returned analysis should carry the TRUE effective context (not the
    # requested one) — per AC: "stored analysis must retain its true
    # effective_context — only the cache_key mapping is duplicated".
    assert result2.analysis.context_level == result1.analysis.context_level


# ---------------------------------------------------------------------------
# Test B — _count_uncached_conversations_fast returns 0 post-analyze
# ---------------------------------------------------------------------------


def test_count_uncached_conversations_fast_zero_after_analyze(
    ohtv_dir, worker_conv_dir, mock_llm
):
    """AC5: ``_count_uncached_conversations_fast`` must report 0 uncached
    after a single ``analyze_objectives(..., context="minimal")`` run.

    This is the user-visible symptom from the issue: ``ohtv gen objs -D``
    reporting the same N conversations as needing analysis on every run.
    """

    from ohtv.analysis.objectives import analyze_objectives
    from ohtv.cli import _count_uncached_conversations_fast
    from ohtv.config import Config
    from ohtv.db import get_connection, migrate
    from ohtv.db.models import Conversation
    from ohtv.db.stores import ConversationStore
    from ohtv.sources.base import ConversationInfo

    # 1. Pre-register the conversation in the DB. We have to do this BEFORE
    #    invoking analyze_objectives because the analysis_cache table has a
    #    foreign key on conversations.id (ON DELETE CASCADE). The FK is
    #    enforced (PRAGMA foreign_keys = ON), so attempting to insert a
    #    cache row for a non-existent conversation_id would fail silently
    #    inside ``_sync_cache_to_db``'s broad except handler — and nothing
    #    would land in the DB. In production this is fine because the
    #    scanner registers conversations long before ``gen objs`` runs.
    with get_connection() as conn:
        migrate(conn)
        ConversationStore(conn).upsert(
            Conversation(
                id=worker_conv_dir.name,
                location=str(worker_conv_dir),
                registered_at=datetime.now(timezone.utc),
                events_mtime=0,
                event_count=1,  # matches the single ActionEvent fixture
                source="local",
            )
        )
        conn.commit()

    # 2. Analyze once at the requested ('minimal') level. This auto-promotes
    #    internally to 'default' and writes the analysis_cache row under the
    #    promoted key PLUS the alias row under 'minimal' (the fix for #129).
    analyze_objectives(
        worker_conv_dir,
        model="test-model",
        context="minimal",
        detail="brief",
        assess=False,
    )

    # 3. Build the ConversationInfo the CLI would pass in.
    info = ConversationInfo(
        id=worker_conv_dir.name,
        title=None,
        created_at=None,
        updated_at=None,
        event_count=1,
        source="local",
    )

    # 4. Fast-path count at the originally-requested minimal level. Before
    # the fix, this returned 1; after the fix, the alias cache row at the
    # 'minimal' key resolves to a hit.
    uncached = _count_uncached_conversations_fast(
        [info], Config.from_env(), context="minimal", detail="brief", assess=False
    )

    assert uncached == 0, (
        "post-analyze, the conversation must register as cached at the "
        "originally-requested context level (issue #129); got "
        f"{uncached} uncached"
    )
