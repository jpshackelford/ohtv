"""Tests for session telemetry (Issue #162).

Covers:
- Filename grammar lockdown
- Schema serialisation (top-level keys, schema_version, agent: null for
  plain-RAG, agent dict for both modes)
- Truncation flag pairing (observation, chunk_text)
- Index-line shape
- Per-step cost/token deltas reconcile to agent totals
- Recorder write-failure raises (the CLI swallows it elsewhere)
- Two-process concurrent writes produce two distinct lines, no
  interleaving (the AC concurrency invariant)
- OHTV_TELEMETRY_DIR override is honoured
- OHTV_TELEMETRY_ENABLED=0 disables capture
"""

from __future__ import annotations

import json
import multiprocessing
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from ohtv.analysis.telemetry import (
    CHUNK_TEXT_CAP_BYTES,
    OBSERVATION_CAP_BYTES,
    SCHEMA_VERSION,
    SessionRecorder,
    _truncate_bytes,
    build_agent_record,
    build_invocation_record,
    build_rag_record,
    is_enabled,
)
from ohtv.analysis.investigator import InvestigationResult


# ---------------------------------------------------------------------------
# Small fakes — avoid importing the real RAGAnswer (it transitively pulls
# litellm, which adds ~2s to test collection).
# ---------------------------------------------------------------------------


@dataclass
class FakeChunk:
    conversation_id: str = "abc12345"
    root_conversation_id: str = "abc12345"
    title: str = "t"
    embed_type: str = "summary"
    source_text: str = "hello"
    score: float = 0.5
    chunk_index: int = 0
    summary: str | None = None
    cloud_url: str | None = None
    created_at: datetime | None = None
    conv_source: str = "local"
    source: object | None = None


@dataclass
class FakeRAGAnswer:
    answer: str = "an answer"
    context_chunks: list = field(default_factory=list)
    source_conversation_ids: set = field(default_factory=set)
    search_time_seconds: float = 0.12
    generation_time_seconds: float = 0.34
    model: str = "openai/gpt-4o-mini"
    temporal_filter_applied: bool = False
    date_range: tuple | None = None
    related_repos: list | None = None
    related_prs: list | None = None
    related_issues: list | None = None
    context_tokens: int = 1234
    total_tokens: int = 1690  # 1234 + 456
    cost: float = 0.0023


def _make_result(**overrides) -> InvestigationResult:
    defaults = dict(
        final_answer="final",
        initial_answer="initial",
        investigation_steps=["Called finish: ..."],
        conversations_examined={"abc12345", "def67890"},
        total_iterations=2,
        total_cost=0.012,
        total_tokens=2000,
        model="openai/gpt-4o-mini",
        elapsed_seconds=3.4,
        finished_normally=True,
        error=None,
        mode="cli",
    )
    defaults.update(overrides)
    return InvestigationResult(**defaults)


# ---------------------------------------------------------------------------
# Truncation helper
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_under_cap(self):
        text, size, truncated = _truncate_bytes("hello", 100)
        assert text == "hello"
        assert size == 5
        assert truncated is False

    def test_over_cap(self):
        big = "x" * 10_000
        text, size, truncated = _truncate_bytes(big, 1024)
        assert size == 10_000
        assert truncated is True
        assert len(text.encode("utf-8")) <= 1024

    def test_multi_byte_boundary(self):
        # Emoji is 4 bytes in UTF-8 — cap that lands mid-emoji must not
        # produce invalid UTF-8.
        text = "🙂" * 10  # 40 UTF-8 bytes
        result, size, truncated = _truncate_bytes(text, 3)
        assert truncated is True
        assert size == 40
        # ``ignore`` errors policy → cleanly truncates to "" since one
        # full code point is 4 bytes; the important invariant is that
        # the result encodes back without crashing.
        result.encode("utf-8")


# ---------------------------------------------------------------------------
# build_* helpers
# ---------------------------------------------------------------------------


class TestBuildHelpers:
    def test_build_invocation_record(self):
        rec = build_invocation_record(
            question="q?", flags={"context": 5, "agent_mode": "cli"}
        )
        assert rec == {
            "command": "ohtv ask",
            "question": "q?",
            "flags": {"context": 5, "agent_mode": "cli"},
        }
        # Defensive copy: mutating the caller's dict must not bleed in.
        flags = {"a": 1}
        rec = build_invocation_record(question="x", flags=flags)
        flags["a"] = 99
        assert rec["flags"]["a"] == 1

    def test_build_rag_record_chunks_truncated(self):
        big_chunk = FakeChunk(source_text="x" * (CHUNK_TEXT_CAP_BYTES + 500))
        small_chunk = FakeChunk(source_text="small", embed_type="content")
        rag = FakeRAGAnswer(
            context_chunks=[big_chunk, small_chunk],
            source_conversation_ids={"a", "b"},
        )
        rec = build_rag_record(rag)  # type: ignore[arg-type]
        assert len(rec["retrieved_chunks"]) == 2
        big_rec, small_rec = rec["retrieved_chunks"]
        assert big_rec["chunk_text_truncated"] is True
        assert big_rec["chunk_text_size_bytes"] == CHUNK_TEXT_CAP_BYTES + 500
        assert small_rec["chunk_text_truncated"] is False
        assert small_rec["chunk_text_size_bytes"] == 5
        # Token split derived from context_tokens / total_tokens.
        assert rec["tokens"] == {"prompt": 1234, "completion": 456}
        # Sorted, deterministic.
        assert rec["source_conversation_ids"] == ["a", "b"]
        # Elapsed is search + generation summed.
        assert rec["elapsed_seconds"] == pytest.approx(0.46)

    def test_build_rag_record_with_date_range(self):
        rag = FakeRAGAnswer(
            temporal_filter_applied=True,
            date_range=(
                datetime(2026, 5, 1, tzinfo=timezone.utc),
                datetime(2026, 5, 8, tzinfo=timezone.utc),
            ),
        )
        rec = build_rag_record(rag)  # type: ignore[arg-type]
        assert rec["temporal_filter_applied"] is True
        assert rec["date_range"][0].startswith("2026-05-01")
        assert rec["date_range"][1].startswith("2026-05-08")

    def test_build_agent_record_sorts_conversations(self):
        result = _make_result(conversations_examined={"zzz", "aaa", "mmm"})
        rec = build_agent_record(result, steps=[])
        assert rec["conversations_examined"] == ["aaa", "mmm", "zzz"]
        assert rec["mode"] == "cli"
        assert rec["steps"] == []


# ---------------------------------------------------------------------------
# is_enabled
# ---------------------------------------------------------------------------


class TestEnvToggles:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("OHTV_TELEMETRY_ENABLED", raising=False)
        assert is_enabled() is True

    def test_opt_out(self, monkeypatch):
        monkeypatch.setenv("OHTV_TELEMETRY_ENABLED", "0")
        assert is_enabled() is False

    def test_any_other_value_still_enabled(self, monkeypatch):
        monkeypatch.setenv("OHTV_TELEMETRY_ENABLED", "1")
        assert is_enabled() is True
        monkeypatch.setenv("OHTV_TELEMETRY_ENABLED", "true")
        assert is_enabled() is True

    def test_telemetry_dir_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OHTV_TELEMETRY_DIR", str(tmp_path / "custom"))
        from ohtv.config import get_telemetry_dir

        assert get_telemetry_dir() == tmp_path / "custom"

    def test_telemetry_dir_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv("OHTV_TELEMETRY_DIR", raising=False)
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        from ohtv.config import get_telemetry_dir

        assert get_telemetry_dir() == tmp_path / "telemetry"


# ---------------------------------------------------------------------------
# StepRecorder deltas
# ---------------------------------------------------------------------------


class TestStepDeltas:
    def _new_recorder(self, tmp_path: Path) -> SessionRecorder:
        return SessionRecorder.start(
            invocation=build_invocation_record(question="q?", flags={}),
            environment={"ohtv_version": "test"},
            telemetry_dir=tmp_path,
        )

    def test_first_step_delta_equals_first_observation(self, tmp_path):
        rec = self._new_recorder(tmp_path)
        with rec.begin_step(1) as step:
            step.set_metrics(0.01, 100, 50)
            step.set_tool_call("show_conversation", {"conversation_id": "abc"})
            step.set_observation("hi")
        assert len(rec._steps) == 1
        s = rec._steps[0]
        assert s["cost"] == pytest.approx(0.01)
        assert s["tokens"] == {"prompt": 100, "completion": 50}
        assert s["tool_name"] == "show_conversation"
        assert s["kind"] == "tool_call"
        assert s["observation_truncated"] is False

    def test_deltas_sum_to_total_cost(self, tmp_path):
        """The summed per-step deltas must equal the final cumulative cost.

        This is the reconciliation AC: ``sum(step.cost) ≈
        agent.total_cost`` because the agent.total_cost is what the LLM
        client reported as accumulated_cost after the last call.
        """
        rec = self._new_recorder(tmp_path)
        with rec.begin_step(1) as step:
            step.set_metrics(0.01, 100, 50)
        with rec.begin_step(2) as step:
            step.set_metrics(0.025, 250, 100)  # cumulative
        with rec.begin_step(3) as step:
            step.set_metrics(0.04, 400, 180)  # cumulative

        summed_cost = sum(s["cost"] for s in rec._steps)
        summed_prompt = sum(s["tokens"]["prompt"] for s in rec._steps)
        summed_completion = sum(s["tokens"]["completion"] for s in rec._steps)
        assert summed_cost == pytest.approx(0.04)
        assert summed_prompt == 400
        assert summed_completion == 180

    def test_step_with_no_metrics_records_zero_cost(self, tmp_path):
        # Errors / cap hits may produce a step that never observes
        # metrics. The delta should be 0, not negative.
        rec = self._new_recorder(tmp_path)
        with rec.begin_step(1) as step:
            step.set_tool_call("run_ohtv", {"argv": ["show", "x"]})
            step.set_observation("oops")
        assert rec._steps[0]["cost"] == 0.0
        assert rec._steps[0]["tokens"] == {"prompt": 0, "completion": 0}

    def test_observation_truncation_flag_paired(self, tmp_path):
        rec = self._new_recorder(tmp_path)
        with rec.begin_step(1) as step:
            big = "x" * (OBSERVATION_CAP_BYTES + 100)
            step.set_observation(big)
        s = rec._steps[0]
        assert s["observation_truncated"] is True
        assert s["observation_size_bytes"] == OBSERVATION_CAP_BYTES + 100
        assert len(s["observation_truncated_text"].encode()) <= OBSERVATION_CAP_BYTES

    def test_tool_kind_inference(self, tmp_path):
        rec = self._new_recorder(tmp_path)
        with rec.begin_step(1) as step:
            step.set_tool_call("think", {"thought": "..."})
        with rec.begin_step(2) as step:
            step.set_tool_call("finish", {"message": "done"})
        with rec.begin_step(3) as step:
            step.set_tool_call("run_ohtv", {"argv": ["show"]})
        assert rec._steps[0]["kind"] == "think"
        assert rec._steps[1]["kind"] == "finish"
        assert rec._steps[2]["kind"] == "tool_call"

    def test_string_arguments_normalised_to_dict(self, tmp_path):
        rec = self._new_recorder(tmp_path)
        with rec.begin_step(1) as step:
            step.set_tool_call("run_ohtv", '{"argv": ["show", "abc"]}')
        assert rec._steps[0]["arguments"] == {"argv": ["show", "abc"]}

    def test_unparseable_string_arguments_wrapped(self, tmp_path):
        rec = self._new_recorder(tmp_path)
        with rec.begin_step(1) as step:
            step.set_tool_call("run_ohtv", "{bad json")
        assert rec._steps[0]["arguments"] == {"_raw": "{bad json"}


# ---------------------------------------------------------------------------
# finalize → on-disk shape
# ---------------------------------------------------------------------------


FILENAME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z_[0-9a-f]{8}\.json$"
)


class TestFinalize:
    def _new_recorder(self, tmp_path: Path) -> SessionRecorder:
        return SessionRecorder.start(
            invocation=build_invocation_record(
                question="what changed?",
                flags={
                    "context": 5,
                    "min_score": 0.3,
                    "model": None,
                    "agent_mode": "cli",
                    "max_steps": 5,
                    "since": None,
                    "until": None,
                    "no_temporal": False,
                    "explain": False,
                    "explain_only": False,
                    "show_context": False,
                },
            ),
            environment={"ohtv_version": "test", "corpus": {}},
            telemetry_dir=tmp_path,
        )

    def test_filename_grammar(self, tmp_path):
        rec = self._new_recorder(tmp_path)
        rec.record_rag(FakeRAGAnswer())  # type: ignore[arg-type]
        rec.record_agent(_make_result())
        path = rec.finalize()
        assert FILENAME_RE.match(path.name), (
            f"Filename {path.name!r} does not match the locked grammar"
        )
        # Filename's 8-char prefix matches session_id[:8]
        prefix = path.name.rsplit("_", 1)[1].split(".", 1)[0]
        assert prefix == rec.session_id[:8]

    def test_schema_keys_and_version(self, tmp_path):
        rec = self._new_recorder(tmp_path)
        rec.record_rag(FakeRAGAnswer())  # type: ignore[arg-type]
        rec.record_agent(_make_result())
        path = rec.finalize()
        blob = json.loads(path.read_text())
        assert blob["schema_version"] == SCHEMA_VERSION
        assert set(blob.keys()) >= {
            "schema_version",
            "session_id",
            "started_at",
            "ended_at",
            "invocation",
            "environment",
            "rag",
            "agent",
            "totals",
        }
        # session_id is 32 hex chars (UUID4 hex)
        assert re.fullmatch(r"[0-9a-f]{32}", blob["session_id"])
        # ISO-8601 Z (no fractional seconds)
        assert blob["started_at"].endswith("Z")
        assert blob["ended_at"].endswith("Z")
        # Agent block populated.
        assert blob["agent"]["mode"] == "cli"
        assert blob["agent"]["finished_normally"] is True

    def test_agent_null_for_plain_rag_sessions(self, tmp_path):
        """AC: plain ohtv ask (no agent flag) → ``"agent": null`` literally.

        Schema lock-in: stable key set for JSON consumers.
        """
        rec = self._new_recorder(tmp_path)
        rec.record_rag(FakeRAGAnswer())  # type: ignore[arg-type]
        rec.record_agent(None)  # explicit None — no agent ran
        path = rec.finalize()
        raw = path.read_text()
        blob = json.loads(raw)
        assert blob["agent"] is None
        # Make sure the key is *present* in the serialised JSON, not
        # just None at the dict level (matters for downstream tooling
        # that walks JSON text).
        assert '"agent": null' in raw

    def test_record_agent_not_called_still_writes_agent_null(self, tmp_path):
        """If the ask handler never calls ``record_agent``, the blob still
        has ``"agent": null`` — i.e. the default state is the same as
        "explicit None". Defensive against a future refactor."""
        rec = self._new_recorder(tmp_path)
        rec.record_rag(FakeRAGAnswer())  # type: ignore[arg-type]
        path = rec.finalize()
        blob = json.loads(path.read_text())
        assert blob["agent"] is None

    def test_index_line_shape(self, tmp_path):
        rec = self._new_recorder(tmp_path)
        rec.record_rag(FakeRAGAnswer())  # type: ignore[arg-type]
        rec.record_agent(_make_result(total_iterations=4, finished_normally=True))
        rec.finalize()
        index_path = tmp_path / "sessions.jsonl"
        assert index_path.exists()
        lines = index_path.read_text().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert set(entry.keys()) >= {
            "session_id",
            "started_at",
            "ended_at",
            "question",
            "agent_mode",
            "model",
            "total_cost",
            "total_tokens",
            "iterations",
            "finished_normally",
            "blob",
        }
        assert entry["agent_mode"] == "cli"
        assert entry["iterations"] == 4
        assert entry["question"] == "what changed?"
        # blob is the filename, not a path
        assert "/" not in entry["blob"]
        assert FILENAME_RE.match(entry["blob"])

    def test_index_line_under_pipe_buf(self, tmp_path):
        """The concurrency contract relies on the index line fitting under
        ``PIPE_BUF`` (4096 bytes). Locked down to catch a future shape
        change that would silently break the no-locking promise."""
        rec = self._new_recorder(tmp_path)
        rec.record_rag(FakeRAGAnswer())  # type: ignore[arg-type]
        rec.record_agent(_make_result())
        rec.finalize()
        line = (tmp_path / "sessions.jsonl").read_text().splitlines()[0]
        assert len(line.encode("utf-8")) < 4096

    def test_atomic_write_no_tmp_left_behind(self, tmp_path):
        rec = self._new_recorder(tmp_path)
        rec.record_rag(FakeRAGAnswer())  # type: ignore[arg-type]
        rec.record_agent(_make_result())
        rec.finalize()
        # No ``.tmp`` siblings should remain after a successful write.
        leftover = list((tmp_path / "sessions").glob("*.tmp"))
        assert leftover == []

    def test_finalize_raises_on_read_only_dir(self, tmp_path):
        """finalize() raises; the CLI swallows with log.warning. We assert
        the raise so the swallow contract is meaningful."""
        rec = self._new_recorder(tmp_path / "blocked")
        rec.record_rag(FakeRAGAnswer())  # type: ignore[arg-type]
        rec.record_agent(_make_result())
        sessions_dir = tmp_path / "blocked" / "sessions"
        sessions_dir.mkdir(parents=True)
        # Stub mkdir so finalize tries to write into a path we can
        # force-fail without root-only chmod tricks.
        with patch(
            "ohtv.analysis.telemetry.tempfile.NamedTemporaryFile",
            side_effect=OSError("disk full"),
        ):
            with pytest.raises(OSError):
                rec.finalize()


# ---------------------------------------------------------------------------
# Concurrency — two-process append integrity (the AC)
# ---------------------------------------------------------------------------


def _concurrent_worker(telemetry_dir_str: str, question: str) -> None:
    """Spawned in a child process; writes one session."""
    telemetry_dir = Path(telemetry_dir_str)
    rec = SessionRecorder.start(
        invocation=build_invocation_record(question=question, flags={"agent_mode": None}),
        environment={"ohtv_version": "test"},
        telemetry_dir=telemetry_dir,
    )
    rec.record_agent(None)
    rec.finalize()


class TestConcurrency:
    def test_two_processes_two_lines_no_interleave(self, tmp_path):
        ctx = multiprocessing.get_context("spawn")
        procs = [
            ctx.Process(target=_concurrent_worker, args=(str(tmp_path), f"q{i}"))
            for i in range(2)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
            assert p.exitcode == 0

        index_path = tmp_path / "sessions.jsonl"
        lines = index_path.read_text().splitlines()
        assert len(lines) == 2

        # Every line is independently valid JSON (no interleaving).
        questions = set()
        for line in lines:
            entry = json.loads(line)
            questions.add(entry["question"])
            # session_id is a full 32-char hex
            assert re.fullmatch(r"[0-9a-f]{32}", entry["session_id"])

        assert questions == {"q0", "q1"}

        # Both blobs exist on disk too.
        blobs = list((tmp_path / "sessions").glob("*.json"))
        assert len(blobs) == 2
