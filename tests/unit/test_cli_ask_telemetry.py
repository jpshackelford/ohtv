"""CLI integration tests for ``ohtv ask`` telemetry (Issue #162).

Drives the ``ask`` Click handler end-to-end with a real (but minimal)
sqlite DB and a stubbed ``RAGAnswerer`` so the LLM is never called.
Verifies that the recorder hookup lands a session blob + index line on
disk, and that the env-var contracts (``OHTV_TELEMETRY_DIR``,
``OHTV_TELEMETRY_ENABLED=0``) are honoured by the handler.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from click.testing import CliRunner

from ohtv.cli import main


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeChunk:
    conversation_id: str = "abc12345"
    root_conversation_id: str = "abc12345"
    title: str = "t"
    embed_type: str = "summary"
    source_text: str = "hello"
    score: float = 0.6
    chunk_index: int = 0
    summary: str | None = None
    cloud_url: str | None = None
    created_at = None
    conv_source: str = "local"
    source: object | None = None


@dataclass
class FakeRAGAnswer:
    answer: str = "stub answer"
    context_chunks: list = field(default_factory=lambda: [FakeChunk()])
    source_conversation_ids: set = field(default_factory=lambda: {"abc12345"})
    search_time_seconds: float = 0.01
    generation_time_seconds: float = 0.02
    model: str = "openai/gpt-4o-mini"
    temporal_filter_applied: bool = False
    date_range = None
    related_repos = None
    related_prs = None
    related_issues = None
    context_tokens: int = 100
    total_tokens: int = 150
    cost: float = 0.001


class FakeRAGAnswerer:
    """Drop-in for ``ohtv.cli.RAGAnswerer`` — never calls an LLM."""

    def __init__(self, *args, **kwargs):
        self.model = kwargs.get("model") or "openai/gpt-4o-mini"

    def answer_question(self, question, **_kwargs):
        return FakeRAGAnswer(answer=f"answer for: {question}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ohtv_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated $OHTV_DIR + $OHTV_TELEMETRY_DIR per test.

    Creates a fresh DB, inserts one dummy embedding row so the
    ``embed_store.count() == 0`` early-exit in the ``ask`` handler
    doesn't fire, and points telemetry at ``tmp_path/telemetry``.
    """
    ohtv_dir = tmp_path / "ohtv"
    ohtv_dir.mkdir()
    telemetry_dir = tmp_path / "telemetry"

    monkeypatch.setenv("OHTV_DIR", str(ohtv_dir))
    monkeypatch.setenv("OHTV_TELEMETRY_DIR", str(telemetry_dir))
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    # Avoid hitting LiteLLM with a real model.
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    # Initialise the DB schema via the public entry point.
    from ohtv.db import get_ready_connection

    with get_ready_connection() as _conn:
        pass  # just trigger migrations; no rows needed

    # Patch ``EmbeddingStore.count`` so the ask handler's
    # ``if embed_count == 0`` early-exit doesn't fire. Inserting a
    # real row would violate the FK on conversations and isn't worth
    # the bookkeeping for a telemetry-focused test.
    from ohtv.db.stores import EmbeddingStore

    monkeypatch.setattr(EmbeddingStore, "count", lambda self: 1)

    return telemetry_dir


@pytest.fixture
def stub_rag(monkeypatch: pytest.MonkeyPatch):
    """Patch ``RAGAnswerer`` in ``ohtv.cli`` so no LLM is reached."""
    import ohtv.analysis.rag as rag_mod

    monkeypatch.setattr(rag_mod, "RAGAnswerer", FakeRAGAnswerer)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAskWritesTelemetry:
    def test_plain_ask_writes_session_with_agent_null(
        self, ohtv_env, stub_rag
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["ask", "what changed?"])
        # The handler may emit extra warnings on stderr (e.g. no
        # citations), but it must exit 0 and print our stub answer.
        assert result.exit_code == 0, (
            f"unexpected non-zero exit\nstdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
        assert "answer for: what changed?" in result.stdout

        # Session blob landed in the override dir.
        sessions_dir = ohtv_env / "sessions"
        index_path = ohtv_env / "sessions.jsonl"
        assert sessions_dir.exists(), "telemetry sessions dir was not created"
        assert index_path.exists(), "sessions.jsonl was not appended to"

        blobs = list(sessions_dir.glob("*.json"))
        assert len(blobs) == 1
        blob = json.loads(blobs[0].read_text())

        # Schema lock-ins.
        assert blob["schema_version"] == 1
        assert blob["agent"] is None  # plain RAG → agent: null
        assert blob["invocation"]["question"] == "what changed?"
        assert blob["invocation"]["flags"]["agent_mode"] is None
        # RAG block present + populated by record_rag.
        assert blob["rag"] is not None
        assert blob["rag"]["initial_answer"] == "answer for: what changed?"

        # Index line shape.
        index_lines = index_path.read_text().splitlines()
        assert len(index_lines) == 1
        entry = json.loads(index_lines[0])
        assert entry["question"] == "what changed?"
        assert entry["agent_mode"] is None
        assert entry["blob"] == blobs[0].name


class TestEnvOptOut:
    def test_telemetry_disabled_writes_nothing(
        self, ohtv_env, stub_rag, monkeypatch
    ):
        """``OHTV_TELEMETRY_ENABLED=0`` short-circuits recorder construction."""
        monkeypatch.setenv("OHTV_TELEMETRY_ENABLED", "0")
        runner = CliRunner()
        result = runner.invoke(main, ["ask", "anything"])
        assert result.exit_code == 0
        # No directory, no index, no blobs.
        assert not (ohtv_env / "sessions").exists()
        assert not (ohtv_env / "sessions.jsonl").exists()


class TestGracefulDegradation:
    """If finalize raises, ``ohtv ask`` MUST still succeed.

    Simulated by patching ``SessionRecorder.finalize`` to raise.
    The CLI handler catches and logs; the user's answer must still
    print and the exit code stays 0.
    """

    def test_finalize_failure_does_not_break_ask(
        self, ohtv_env, stub_rag, monkeypatch
    ):
        from ohtv.analysis import telemetry as telemetry_mod

        original_finalize = telemetry_mod.SessionRecorder.finalize

        def boom(self):
            raise OSError("simulated disk-full / readonly fs")

        monkeypatch.setattr(
            telemetry_mod.SessionRecorder, "finalize", boom
        )
        runner = CliRunner()
        result = runner.invoke(main, ["ask", "graceful?"])
        # Restore for the rest of the test session (monkeypatch handles
        # this, but be defensive).
        monkeypatch.setattr(
            telemetry_mod.SessionRecorder, "finalize", original_finalize
        )

        assert result.exit_code == 0, (
            f"finalize failure must NOT propagate.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}\n"
            f"exc={result.exception!r}"
        )
        assert "answer for: graceful?" in result.stdout
        # No blob landed (because the simulated failure was inside
        # the only path that writes one). But the answer was printed.
        assert not list((ohtv_env / "sessions").glob("*.json"))


class TestTelemetryDirOverride:
    """``OHTV_TELEMETRY_DIR=/path`` must override the storage root.

    Re-verified end-to-end (in addition to the unit test on
    ``get_telemetry_dir``) so future CLI refactors can't bypass it.
    """

    def test_override_honored_by_ask(self, ohtv_env, stub_rag):
        # The fixture already sets OHTV_TELEMETRY_DIR — assert files
        # land there and not in $OHTV_DIR/telemetry.
        runner = CliRunner()
        result = runner.invoke(main, ["ask", "where am I?"])
        assert result.exit_code == 0
        assert (ohtv_env / "sessions.jsonl").exists()
        # The default location must NOT have been created.
        from ohtv.config import get_ohtv_dir

        default_telemetry = get_ohtv_dir() / "telemetry"
        assert not default_telemetry.exists() or default_telemetry == ohtv_env
