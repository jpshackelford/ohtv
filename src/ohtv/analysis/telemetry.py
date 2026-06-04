"""Session telemetry for ``ohtv ask`` (Issue #162).

Captures each ``ohtv ask`` invocation as a self-contained, replay-friendly
JSON blob under ``~/.ohtv/telemetry/sessions/`` plus a one-line summary in
``~/.ohtv/telemetry/sessions.jsonl``.

The recorder lives at the CLI handler layer; the agent investigators
(:class:`ohtv.analysis.investigator.InvestigationAgent` and
:class:`ohtv.analysis.investigator_cli.InvestigationAgentCli`) take an
optional ``recorder`` keyword and call :meth:`SessionRecorder.begin_step`
once per loop iteration as a context manager. If ``recorder is None`` the
agents are unchanged (pass-through, no overhead beyond a single
``nullcontext`` per iteration).

Writes are best-effort: a failure inside :meth:`SessionRecorder.finalize`
must never propagate to the user. The CLI handler swallows the exception
with a ``log.warning`` so ``ohtv ask`` still prints its answer.

Schema version 1 is documented in ``docs/reference/telemetry.md``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import platform
import socket
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import-time only
    from ohtv.analysis.investigator import InvestigationResult
    from ohtv.analysis.rag import RAGAnswer

log = logging.getLogger("ohtv")

SCHEMA_VERSION = 1

# Per-field truncation caps. Each truncated field carries a paired
# ``*_truncated`` flag and an ``observation_size_bytes``-style counter so
# readers can detect what was dropped (#162 AC).
OBSERVATION_CAP_BYTES = 8 * 1024  # 8 KB per step observation
CHUNK_TEXT_CAP_BYTES = 2 * 1024  # 2 KB per retrieved chunk

ENV_DISABLED = "OHTV_TELEMETRY_ENABLED"
ENV_DIR_OVERRIDE = "OHTV_TELEMETRY_DIR"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_enabled() -> bool:
    """Return ``True`` unless ``OHTV_TELEMETRY_ENABLED=0`` is set."""
    return os.environ.get(ENV_DISABLED, "1") != "0"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _format_iso8601_z(dt: datetime) -> str:
    """Format ``dt`` as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC, no fractional)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_filename_timestamp(dt: datetime) -> str:
    """Format ``dt`` for the session filename grammar.

    Hyphens replace colons because ``:`` is reserved on Windows and some
    cloud sync clients (Dropbox, OneDrive) misbehave with it. Locked
    down by the filename-regex test.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H-%M-%SZ")


def _truncate_bytes(text: str, cap_bytes: int) -> tuple[str, int, bool]:
    """Truncate ``text`` to at most ``cap_bytes`` UTF-8 bytes.

    Returns ``(possibly-truncated text, original-size-bytes,
    truncated_flag)``. Encoding errors are replaced (lossy) so we never
    crash on weird tool output.
    """
    encoded = text.encode("utf-8", errors="replace")
    size = len(encoded)
    if size <= cap_bytes:
        return text, size, False
    # Decode the prefix, dropping any incomplete trailing code point so
    # the resulting string is still valid UTF-8.
    truncated = encoded[:cap_bytes].decode("utf-8", errors="ignore")
    return truncated, size, True


def _git_sha() -> str | None:
    """Best-effort current commit SHA — never raises.

    Used in the ``environment.ohtv_git_sha`` field; ``None`` when ohtv is
    installed from a wheel (no ``.git`` directory) or git is unavailable.
    """
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
            return sha or None
    except Exception:  # noqa: BLE001 - best-effort
        pass
    return None


# ---------------------------------------------------------------------------
# Environment + corpus snapshot
# ---------------------------------------------------------------------------


def _safe_count(fn: Any, default: int = 0) -> int:
    try:
        return int(fn())
    except Exception:  # noqa: BLE001 - best-effort
        return default


def build_environment_record(
    *,
    embed_store: Any | None = None,
    conv_store: Any | None = None,
    conn: Any | None = None,
) -> dict:
    """Snapshot the corpus + tool versions at session start.

    All inputs are optional so the recorder can run even before stores
    are wired (e.g. early-exit error paths). Missing values surface as
    ``None`` or ``0``.
    """
    from ohtv import __version__ as ohtv_version
    from ohtv.analysis.embeddings import (
        DEFAULT_EMBEDDING_MODEL,
        get_embedding_dimension,
    )

    # ``get_effective_embedding_model`` lives in the ``config`` submodule
    # and is not re-exported from ``ohtv.analysis.embeddings.__init__``;
    # fall back to env / default when it's not available.
    try:
        from ohtv.analysis.embeddings.config import get_effective_embedding_model

        embedding_model = get_effective_embedding_model() or DEFAULT_EMBEDDING_MODEL
    except ImportError:  # pragma: no cover - belt-and-braces
        embedding_model = (
            os.environ.get("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL
        )
    try:
        embedding_dim: int | None = get_embedding_dimension(embedding_model)
    except Exception:  # noqa: BLE001 - best-effort
        embedding_dim = None

    db_schema_version: int | None = None
    if conn is not None:
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM _migrations")
            row = cursor.fetchone()
            if row is not None:
                db_schema_version = int(row[0])
        except Exception:  # noqa: BLE001 - best-effort
            db_schema_version = None

    total_conversations = (
        _safe_count(conv_store.count) if conv_store is not None else 0
    )
    total_embeddings = (
        _safe_count(embed_store.count) if embed_store is not None else 0
    )

    newest_conversation_at: str | None = None
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT created_at FROM conversations "
                "WHERE created_at IS NOT NULL "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row and row[0]:
                # Stored as ISO string; pass through verbatim.
                newest_conversation_at = str(row[0])
        except Exception:  # noqa: BLE001 - best-effort
            newest_conversation_at = None

    return {
        "ohtv_version": ohtv_version,
        "ohtv_git_sha": _git_sha(),
        "python": ".".join(str(p) for p in sys.version_info[:3]),
        "platform": f"{platform.system().lower()}-{platform.machine()}",
        "hostname": socket.gethostname(),
        "embedding_model": embedding_model,
        "embedding_dim": embedding_dim,
        "db_schema_version": db_schema_version,
        "corpus": {
            "total_conversations": total_conversations,
            "total_embeddings": total_embeddings,
            "newest_conversation_at": newest_conversation_at,
        },
    }


def build_invocation_record(
    *,
    question: str,
    flags: dict[str, Any],
) -> dict:
    """Shape the ``invocation`` block.

    ``flags`` must already be a JSON-serialisable dict. The CLI handler
    is the right place to build it because that's where the resolved
    flag values live; this helper just stamps the command name.
    """
    return {
        "command": "ohtv ask",
        "question": question,
        "flags": dict(flags),
    }


def build_rag_record(rag_answer: "RAGAnswer") -> dict:
    """Convert a :class:`RAGAnswer` into the ``rag`` block.

    Chunk text is capped at :data:`CHUNK_TEXT_CAP_BYTES`; ``cost`` and
    ``tokens`` come straight off the dataclass. Token split (prompt /
    completion) is approximated from the available fields:
    ``context_tokens`` ≈ prompt, ``total_tokens - context_tokens`` ≈
    completion. That's not exact but it's the best the existing
    ``RAGAnswer`` shape exposes without widening it for this issue.
    """
    chunks: list[dict] = []
    for chunk in rag_answer.context_chunks:
        text = chunk.source_text or ""
        text_trunc, size, truncated = _truncate_bytes(text, CHUNK_TEXT_CAP_BYTES)
        chunks.append(
            {
                "conversation_id": chunk.conversation_id,
                "root_conversation_id": chunk.root_conversation_id,
                "chunk_type": chunk.embed_type,
                "score": float(chunk.score),
                "chunk_text": text_trunc,
                "chunk_text_size_bytes": size,
                "chunk_text_truncated": truncated,
            }
        )

    date_range: list[str | None] | None = None
    if rag_answer.date_range is not None:
        start, end = rag_answer.date_range
        date_range = [
            start.isoformat() if start is not None else None,
            end.isoformat() if end is not None else None,
        ]

    context_tokens = int(rag_answer.context_tokens or 0)
    total_tokens = int(rag_answer.total_tokens or 0)
    completion = max(0, total_tokens - context_tokens)

    elapsed = float(rag_answer.search_time_seconds or 0.0) + float(
        rag_answer.generation_time_seconds or 0.0
    )

    return {
        "elapsed_seconds": elapsed,
        "search_seconds": float(rag_answer.search_time_seconds or 0.0),
        "generation_seconds": float(rag_answer.generation_time_seconds or 0.0),
        "temporal_filter_applied": bool(rag_answer.temporal_filter_applied),
        "date_range": date_range,
        "retrieved_chunks": chunks,
        "initial_answer": rag_answer.answer,
        "source_conversation_ids": sorted(rag_answer.source_conversation_ids),
        "model": rag_answer.model,
        "tokens": {"prompt": context_tokens, "completion": completion},
        "cost": float(rag_answer.cost or 0.0),
    }


def build_agent_record(result: "InvestigationResult", steps: list[dict]) -> dict:
    """Shape the ``agent`` block from an :class:`InvestigationResult`.

    ``steps`` is the list accumulated by the recorder during the loop;
    the caller passes it explicitly so this helper stays a pure
    serializer.
    """
    return {
        "mode": result.mode,
        "iterations": int(result.total_iterations),
        "finished_normally": bool(result.finished_normally),
        "error": result.error,
        "elapsed_seconds": float(result.elapsed_seconds or 0.0),
        "model": result.model,
        "total_cost": float(result.total_cost or 0.0),
        "total_tokens": int(result.total_tokens or 0),
        "conversations_examined": sorted(result.conversations_examined),
        "final_answer": result.final_answer,
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# StepRecorder — per-iteration context manager
# ---------------------------------------------------------------------------


@dataclass
class StepRecorder:
    """One agent-loop iteration; used as a context manager.

    Token + cost values reported via :meth:`set_metrics` are *cumulative*
    (the SDK exposes them as ``response.metrics.accumulated_*``). The
    step computes its delta against a baseline snapshot taken in
    ``__enter__`` so the on-disk step record reads naturally
    ("this step cost N, used M tokens"). Summed deltas across all
    steps in a session reconcile to ``totals.cost`` minus ``rag.cost``
    within float epsilon (asserted by tests).
    """

    iteration: int
    _parent: "SessionRecorder"
    _t0: float = 0.0
    _cost_baseline: float = 0.0
    _prompt_baseline: int = 0
    _completion_baseline: int = 0
    _tool_name: str | None = None
    _arguments: dict[str, Any] | None = None
    _kind: str = "tool_call"
    _observation: str | None = None
    _observation_size: int = 0
    _observation_truncated: bool = False
    _accumulated_cost: float = 0.0
    _accumulated_prompt: int = 0
    _accumulated_completion: int = 0
    _metrics_seen: bool = False

    def __enter__(self) -> "StepRecorder":
        self._t0 = time.perf_counter()
        # Baselines snapshot the recorder's running totals (so the
        # first step's deltas equal the SDK's first read).
        self._cost_baseline = self._parent._last_cost
        self._prompt_baseline = self._parent._last_prompt
        self._completion_baseline = self._parent._last_completion
        return self

    def set_tool_call(self, name: str, arguments: Any) -> None:
        """Record the tool the LLM picked this iteration.

        ``arguments`` is whatever the SDK reports — a dict for tools
        mode, ``{"argv": [...]}``-shape for cli mode (#161). Stored
        verbatim; the cross-mode comparison surface is the
        ``arguments`` payload shape.
        """
        self._tool_name = name
        # Normalise to a dict for JSON serialisation. The SDK
        # sometimes hands us a string (raw JSON) when the tool call
        # arguments failed to parse; round-trip that through json.loads
        # so the on-disk record is always a structured value.
        if isinstance(arguments, dict):
            self._arguments = dict(arguments)
        elif isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError:
                parsed = {"_raw": arguments}
            self._arguments = parsed if isinstance(parsed, dict) else {"_raw": parsed}
        elif arguments is None:
            self._arguments = {}
        else:
            self._arguments = {"_raw": repr(arguments)}

        if name == "think":
            self._kind = "think"
        elif name == "finish":
            self._kind = "finish"
        else:
            self._kind = "tool_call"

    def set_observation(
        self, text: str, *, cap_bytes: int = OBSERVATION_CAP_BYTES
    ) -> None:
        """Record the tool's text observation, truncated to ``cap_bytes``."""
        truncated, size, was_truncated = _truncate_bytes(text or "", cap_bytes)
        self._observation = truncated
        self._observation_size = size
        self._observation_truncated = was_truncated

    def set_metrics(
        self,
        accumulated_cost: float,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """Record the SDK's cumulative cost/token counters for this iteration.

        Safe to call multiple times — only the last call wins. The
        recorder turns these into deltas on ``__exit__`` and propagates
        the running totals to the parent recorder for the next step's
        baseline.
        """
        self._accumulated_cost = float(accumulated_cost or 0.0)
        self._accumulated_prompt = int(prompt_tokens or 0)
        self._accumulated_completion = int(completion_tokens or 0)
        self._metrics_seen = True

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        elapsed = time.perf_counter() - self._t0

        if self._metrics_seen:
            cost_delta = max(0.0, self._accumulated_cost - self._cost_baseline)
            prompt_delta = max(0, self._accumulated_prompt - self._prompt_baseline)
            completion_delta = max(
                0, self._accumulated_completion - self._completion_baseline
            )
            # Propagate so the next step's baseline reflects this step's
            # observed cumulative totals.
            self._parent._last_cost = self._accumulated_cost
            self._parent._last_prompt = self._accumulated_prompt
            self._parent._last_completion = self._accumulated_completion
        else:
            cost_delta = 0.0
            prompt_delta = 0
            completion_delta = 0

        record: dict[str, Any] = {
            "iteration": self.iteration,
            "kind": self._kind,
            "tool_name": self._tool_name,
            "arguments": self._arguments if self._arguments is not None else {},
            "elapsed_seconds": elapsed,
            "tokens": {"prompt": prompt_delta, "completion": completion_delta},
            "cost": cost_delta,
        }
        if self._observation is not None:
            record["observation_truncated_text"] = self._observation
            record["observation_size_bytes"] = self._observation_size
            record["observation_truncated"] = self._observation_truncated

        if exc_type is not None:
            record["error"] = f"{exc_type.__name__}: {exc_val}"

        self._parent._steps.append(record)
        # Never suppress the underlying exception.
        return None


# ---------------------------------------------------------------------------
# SessionRecorder — one ohtv ask invocation
# ---------------------------------------------------------------------------


@dataclass
class SessionRecorder:
    """Accumulates one ``ohtv ask`` invocation's telemetry.

    Constructed at the top of the ``ask`` handler via :meth:`start`,
    handed off to the investigator (if any), and finalised in a
    ``finally`` block. Write failures inside :meth:`finalize` raise so
    the CLI can log + swallow them; in-memory accumulation is exception
    free.
    """

    session_id: str
    started_at: datetime
    invocation: dict
    environment: dict
    telemetry_dir: Path
    _rag: dict | None = None
    _agent: dict | None = None
    _steps: list[dict] = field(default_factory=list)
    # Running cumulative counters used by StepRecorder baselines.
    _last_cost: float = 0.0
    _last_prompt: int = 0
    _last_completion: int = 0
    _agent_recorded: bool = False
    _t0: float = field(default_factory=time.perf_counter)

    @classmethod
    def start(
        cls,
        *,
        invocation: dict,
        environment: dict,
        telemetry_dir: Path | None = None,
    ) -> "SessionRecorder":
        """Create a fresh recorder. Does not touch disk."""
        from ohtv.config import get_telemetry_dir

        return cls(
            session_id=uuid.uuid4().hex,
            started_at=_utcnow(),
            invocation=invocation,
            environment=environment,
            telemetry_dir=telemetry_dir or get_telemetry_dir(),
        )

    # ------------------------------------------------------------------
    # Mutation API
    # ------------------------------------------------------------------

    def record_rag(self, rag_answer: "RAGAnswer") -> None:
        """Capture the initial RAG answer (best-effort, never raises)."""
        try:
            self._rag = build_rag_record(rag_answer)
        except Exception:  # noqa: BLE001 - best-effort
            log.warning("telemetry: failed to record RAG block", exc_info=True)
            self._rag = None

    def begin_step(self, iteration: int) -> StepRecorder:
        """Context manager for a single agent-loop iteration."""
        return StepRecorder(iteration=iteration, _parent=self)

    def record_agent(self, result: "InvestigationResult | None") -> None:
        """Capture the investigator result.

        ``None`` is a legal value — for plain RAG sessions (no agent
        flag), the ``agent`` block lands as explicit ``null`` so JSON
        consumers see a stable key set (#162 schema lock-in: ``agent:
        null``, not key omission).
        """
        self._agent_recorded = True
        if result is None:
            self._agent = None
            return
        try:
            self._agent = build_agent_record(result, self._steps)
        except Exception:  # noqa: BLE001 - best-effort
            log.warning("telemetry: failed to record agent block", exc_info=True)
            # Fall back to a minimal block so the agent_mode is still
            # discoverable.
            self._agent = {
                "mode": getattr(result, "mode", None),
                "iterations": 0,
                "finished_normally": False,
                "error": "telemetry: failed to serialize agent block",
                "steps": [],
            }

    # ------------------------------------------------------------------
    # Finalize
    # ------------------------------------------------------------------

    def finalize(self) -> Path:
        """Write the session blob + index line to disk.

        Returns the path of the session blob. Raises on I/O errors —
        callers should catch + log without propagating, per the
        graceful-degradation AC.
        """
        ended = _utcnow()
        wall_seconds = time.perf_counter() - self._t0

        rag_cost = float((self._rag or {}).get("cost", 0.0) or 0.0)
        rag_tokens = (self._rag or {}).get("tokens") or {
            "prompt": 0,
            "completion": 0,
        }
        agent_cost = float((self._agent or {}).get("total_cost", 0.0) or 0.0) if self._agent else 0.0
        # Per-step tokens sum reconciles to agent.total_tokens within
        # SDK rounding; here we want the totals envelope so we use the
        # parent's running deltas.
        agent_prompt = int(self._last_prompt or 0)
        agent_completion = int(self._last_completion or 0)

        # If we never observed metrics (e.g. recorder ran without an
        # agent), fall back to the agent block's totals.
        if not agent_prompt and not agent_completion and self._agent:
            agent_total = int(self._agent.get("total_tokens", 0) or 0)
            # Best-effort 50/50 split — exact split is recoverable from
            # the per-step records.
            agent_prompt = agent_total
            agent_completion = 0

        totals = {
            "tokens": {
                "prompt": int(rag_tokens.get("prompt", 0)) + agent_prompt,
                "completion": int(rag_tokens.get("completion", 0)) + agent_completion,
            },
            "cost": rag_cost + agent_cost,
            "wall_seconds": wall_seconds,
        }

        blob: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "started_at": _format_iso8601_z(self.started_at),
            "ended_at": _format_iso8601_z(ended),
            "invocation": self.invocation,
            "environment": self.environment,
            "rag": self._rag,
            "agent": self._agent,  # explicit ``None`` if no agent ran
            "totals": totals,
        }

        sessions_dir = self.telemetry_dir / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        filename = (
            f"{_format_filename_timestamp(self.started_at)}_{self.session_id[:8]}.json"
        )
        target = sessions_dir / filename

        # Atomic write: NamedTemporaryFile in the same directory +
        # os.replace (POSIX-atomic + Windows-safe).
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(sessions_dir),
            prefix=f".{self.session_id[:8]}_",
            suffix=".json.tmp",
            delete=False,
        ) as tmp:
            json.dump(blob, tmp, default=_json_default, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, target)

        # Append the index line. Single ``write()`` of <PIPE_BUF bytes
        # is atomic under POSIX O_APPEND — no locking needed (see
        # docs/reference/telemetry.md for the concurrency contract).
        index_line = {
            "session_id": self.session_id,
            "started_at": _format_iso8601_z(self.started_at),
            "ended_at": _format_iso8601_z(ended),
            "question": self.invocation.get("question"),
            "agent_mode": self.invocation.get("flags", {}).get("agent_mode"),
            "model": self.invocation.get("flags", {}).get("model"),
            "total_cost": totals["cost"],
            "total_tokens": totals["tokens"]["prompt"] + totals["tokens"]["completion"],
            "iterations": (self._agent or {}).get("iterations", 0) if self._agent else 0,
            "finished_normally": (
                (self._agent or {}).get("finished_normally", True)
                if self._agent
                else True
            ),
            "blob": filename,
        }
        index_path = self.telemetry_dir / "sessions.jsonl"
        # ``a`` opens with O_APPEND; the single write below stays well
        # under PIPE_BUF (4096 bytes) so concurrent writers from two
        # processes interleave at line boundaries only.
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(index_line, default=_json_default) + "\n")

        return target


# ---------------------------------------------------------------------------
# Public helpers used by the CLI ask handler
# ---------------------------------------------------------------------------


def _json_default(value: Any) -> Any:
    """JSON encoder fallback for datetime/set/Path values."""
    if isinstance(value, datetime):
        return _format_iso8601_z(value)
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"telemetry: cannot serialise {type(value).__name__}")


@contextlib.contextmanager
def maybe_step(recorder: SessionRecorder | None, iteration: int):
    """Convenience for the investigator loop bodies.

    ``with maybe_step(recorder, iteration) as step:`` yields the
    :class:`StepRecorder` when ``recorder`` is set, or ``None`` when
    telemetry is disabled. Lets the loop be written once instead of
    two branches per call site.
    """
    if recorder is None:
        yield None
        return
    with recorder.begin_step(iteration) as step:
        yield step


__all__ = [
    "SCHEMA_VERSION",
    "OBSERVATION_CAP_BYTES",
    "CHUNK_TEXT_CAP_BYTES",
    "ENV_DISABLED",
    "ENV_DIR_OVERRIDE",
    "SessionRecorder",
    "StepRecorder",
    "build_environment_record",
    "build_invocation_record",
    "build_rag_record",
    "build_agent_record",
    "is_enabled",
    "maybe_step",
]
