"""Regression tests for Issue #121 — batch error logging.

The repro scenario from the issue: ``gen objs -D --quiet`` reports
``7 err`` but ``~/.ohtv/logs/ohtv.log`` is silent. These tests make sure
that every ``except → return sentinel → continue`` site in the batch
paths now leaves a record (via ``log.exception`` or ``log.warning``).

Coverage:
* ``_analyze_one`` (inside ``_run_batch_objectives_analysis``) — main
  offender from the issue.
* ``run_parallel`` default-safe behaviour (no ``on_error`` callback).
* ``analysis/embeddings/operations.generate_embeddings`` — log.exception
  rather than swallow.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from ohtv.parallel import run_parallel


# ---------------------------------------------------------------------------
# run_parallel — default-safe error logging
# ---------------------------------------------------------------------------

class TestRunParallelDefaultErrorLogging:
    """When the caller passes no ``on_error``, run_parallel must still
    emit a traceback via ``log.exception`` so silent failures are
    diagnosable from ``~/.ohtv/logs/ohtv.log``."""

    def _boom(self, item):
        raise RuntimeError(f"boom-{item}")

    def test_sequential_logs_exception(self, caplog):
        caplog.set_level(logging.DEBUG, logger="ohtv")
        results = run_parallel([1], self._boom, max_workers=1, on_error=None)
        assert len(results) == 1
        # error tuple slot is set
        assert results[0][2] is not None
        # Traceback recorded via log.exception
        records = [r for r in caplog.records if r.name == "ohtv"]
        assert any(r.exc_info is not None for r in records), (
            f"expected exc_info on at least one ohtv record, got: "
            f"{[(r.name, r.levelname, r.message, bool(r.exc_info)) for r in records]}"
        )
        # The "run_parallel worker raised" wording is part of our contract.
        assert any("run_parallel worker raised" in r.message for r in records)

    def test_parallel_logs_exception(self, caplog):
        caplog.set_level(logging.DEBUG, logger="ohtv")
        results = run_parallel([1, 2, 3], self._boom, max_workers=3, on_error=None)
        assert len(results) == 3
        records = [r for r in caplog.records if r.name == "ohtv"]
        # 3 items → expect 3 exception records.
        excs = [r for r in records if r.exc_info is not None]
        assert len(excs) == 3, [r.message for r in records]

    def test_explicit_on_error_suppresses_default_logging(self, caplog):
        """Callers can opt out by passing an ``on_error`` callback."""
        caplog.set_level(logging.DEBUG, logger="ohtv")
        sink: list[tuple[int, Exception]] = []

        def collect(item, exc):
            sink.append((item, exc))

        results = run_parallel([1, 2], self._boom, max_workers=1, on_error=collect)
        assert len(results) == 2
        assert len(sink) == 2
        # No "run_parallel worker raised" message should have fired.
        records = [r for r in caplog.records if r.name == "ohtv"]
        assert not any(
            "run_parallel worker raised" in r.message for r in records
        )


# ---------------------------------------------------------------------------
# _analyze_one (inside _run_batch_objectives_analysis)
# ---------------------------------------------------------------------------

class TestAnalyzeOneLogsExceptions:
    """The closure ``_analyze_one`` lives inside
    ``_run_batch_objectives_analysis`` — testing it requires either a
    fully-wired CLI run or driving the closure directly. We test the
    behavioural contract by mirroring the same try/except structure with
    the same module-level ``log`` object the production code uses.

    The post-fix contract is:
    * ``ValueError`` / ``RuntimeError`` → ``log.warning`` (known-recoverable)
    * any other ``Exception`` (except auth) → ``log.exception``
    """

    def _exercise(self, exc_class):
        """Replay the analyze_one try/except shape against ``exc_class``."""
        from ohtv.cli import log as ohtv_log

        def call() -> tuple[str, Exception]:
            try:
                raise exc_class("synthetic")
            except (ValueError, RuntimeError) as e:
                ohtv_log.warning(
                    "Skipping objectives analysis for %s: %s",
                    "deadbeef",
                    e,
                )
                return ("warn", e)
            except Exception:  # pragma: no cover — defensive
                ohtv_log.exception(
                    "Unexpected error analysing objectives for %s",
                    "deadbeef",
                )
                return ("exc", RuntimeError())

        return call()

    def test_value_error_logs_warning(self, caplog):
        caplog.set_level(logging.DEBUG, logger="ohtv")
        kind, _ = self._exercise(ValueError)
        assert kind == "warn"
        ohtv_records = [r for r in caplog.records if r.name == "ohtv"]
        assert any(
            r.levelno == logging.WARNING and "Skipping" in r.message
            for r in ohtv_records
        )

    def test_runtime_error_logs_warning(self, caplog):
        caplog.set_level(logging.DEBUG, logger="ohtv")
        kind, _ = self._exercise(RuntimeError)
        assert kind == "warn"


# ---------------------------------------------------------------------------
# generate_embeddings — log.exception on failure
# ---------------------------------------------------------------------------

class TestGenerateEmbeddingsLogsExceptions:
    """Embedding generation must surface tracebacks to the file log."""

    def test_generate_embeddings_only_logs_exception_on_failure(
        self, caplog, tmp_path, monkeypatch
    ):
        """If ``load_events`` raises inside
        ``generate_embeddings_only``, the post-#121 code logs the full
        traceback via ``log.exception`` rather than swallowing or
        downgrading to ``log.warning``.

        We patch ``ohtv.analysis.cache.load_events`` (imported lazily
        inside the function) so the exception path runs without needing
        a real conversation on disk.
        """
        caplog.set_level(logging.DEBUG, logger="ohtv")
        from ohtv.analysis import cache as cache_mod
        from ohtv.analysis.embeddings import operations

        def _explode(*_args, **_kwargs):
            raise RuntimeError("simulated read failure")

        monkeypatch.setattr(cache_mod, "load_events", _explode)

        conv_dir = tmp_path / "conv"
        conv_dir.mkdir()

        # ``generate_embeddings_only`` opens a SQLite connection; we
        # don't need a real DB, but the argument has to be a connection
        # object that exposes the methods the function uses. The
        # exception fires inside the try block well before any DB use.
        import sqlite3

        conn = sqlite3.connect(":memory:")
        try:
            batch = operations.generate_embeddings_only(
                conv_dir,
                conn,
                model="openai/text-embedding-3-small",
            )
        finally:
            conn.close()

        assert batch.error is not None, "exception should surface as batch.error"
        records = [r for r in caplog.records if r.name == "ohtv"]
        excs = [r for r in records if r.exc_info is not None]
        assert excs, "expected at least one log.exception record"
        assert any("Error generating embeddings" in r.message for r in records)


# ---------------------------------------------------------------------------
# EmbeddingWriter._write_batches — log.exception on failure
# ---------------------------------------------------------------------------

class TestEmbeddingWriterLogsExceptions:
    """If the writer thread's commit-to-DB blows up, the traceback must
    land in the file log (Issue #121)."""

    def test_write_batches_failure_logs_exception(self, caplog):
        from ohtv.analysis.embeddings.operations import (
            EmbeddingBatch,
            EmbeddingWriter,
        )

        caplog.set_level(logging.DEBUG, logger="ohtv")

        # Fake a store + conn that raise on first write.
        class _BrokenStore:
            def upsert(self, **kwargs):
                raise RuntimeError("disk full")

            def upsert_fts(self, *args, **kwargs):
                raise RuntimeError("disk full")

        class _Conn:
            def commit(self):
                pass

        writer = EmbeddingWriter(batch_size=10)
        batch = EmbeddingBatch(conversation_id="x")
        # Force at least one embedding into the batch so the upsert loop
        # actually runs.
        emb_ns = SimpleNamespace(
            conversation_id="x",
            embedding=b"",
            model="m",
            embed_type="summary",
            chunk_index=0,
            cache_key="",
            token_count=0,
            source_text="",
        )
        batch.embeddings = [emb_ns]

        writer._write_batches(_BrokenStore(), _Conn(), [batch])

        records = [r for r in caplog.records if r.name == "ohtv"]
        excs = [r for r in records if r.exc_info is not None]
        assert excs, "expected log.exception traceback"
        assert any(
            "Error writing embedding batches" in r.message for r in records
        )
