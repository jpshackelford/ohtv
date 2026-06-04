"""CLI integration smoke tests for the engagement filter flags on the
``gen objs`` / ``gen titles`` / ``gen run`` commands (Issue #170).

These exercises lock in two things:

* The four flags are wired into all three gen subcommands' Click
  layers and threaded through to ``_apply_conversation_filters`` so
  the filter actually shrinks the candidate set.
* Mutual-exclusion / parse-error paths exit code 2 with a helpful
  message at every call site (not just ``ohtv list``).

The behavioural matrix (which row survives which flag) is covered
exhaustively in ``test_cli_engagement_filter.py`` and
``test_cli_list_engagement_filter.py``. Here we only need
smoke-level "the wiring works" and "errors propagate" coverage.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ohtv.cli import main


# ---------------------------------------------------------------------------
# Fixture: real DB with two cloud conversations, only one engaged
# ---------------------------------------------------------------------------

ID_ENGAGED = "a" * 32
ID_UNENGAGED = "b" * 32


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """Seed a DB with two conversations: A engaged 600s, B engaged 0s."""
    monkeypatch.setenv("OHTV_DIR", str(tmp_path / "ohtv"))
    monkeypatch.setenv("OPENHANDS_BASE_DIR", str(tmp_path / "oh"))

    from ohtv.db import get_ready_connection
    from ohtv.db.models.conversation import Conversation
    from ohtv.db.stores import ConversationStore

    base = datetime(2026, 5, 30, 14, 0, tzinfo=timezone.utc)
    with get_ready_connection(show_progress=False) as conn:
        store = ConversationStore(conn)
        for cid, title, created in [
            (ID_ENGAGED, "Engaged conv", base),
            (ID_UNENGAGED, "Un-engaged conv", base - timedelta(hours=1)),
        ]:
            store.upsert(
                Conversation(
                    id=cid,
                    location=str(tmp_path / "conv" / cid),
                    event_count=5,
                    title=title,
                    created_at=created,
                    updated_at=created + timedelta(minutes=30),
                    source="cloud",
                )
            )

        for cid, engaged in [(ID_ENGAGED, 600), (ID_UNENGAGED, 0)]:
            conn.execute(
                "INSERT OR REPLACE INTO conversation_engagement "
                "(conversation_id, threshold_seconds, first_event_ts, "
                "last_event_ts, total_duration_seconds, engaged_seconds, "
                "attention_periods, follow_up_user_message_count, "
                "attended_user_message_count, processed_at, event_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 1)",
                (
                    cid, 720,
                    "2026-05-30T14:00:00+00:00",
                    "2026-05-30T14:30:00+00:00",
                    1800,
                    engaged,
                    1 if engaged > 0 else 0,
                    "2026-05-30T15:00:00+00:00",
                ),
            )
        conn.commit()
    yield tmp_path


def _invoke(*args) -> tuple[int, str, str]:
    runner = CliRunner()
    result = runner.invoke(main, list(args))
    try:
        err = result.stderr
    except (ValueError, AttributeError):
        err = ""
    return result.exit_code, result.output, err


# ---------------------------------------------------------------------------
# gen objs — the engagement filter reduces the analysis batch
# ---------------------------------------------------------------------------


class TestGenObjsEngagementFilter:
    def test_engaged_filter_excludes_unengaged_from_analysis(
        self, seeded_db, monkeypatch
    ):
        """``gen objs --min-engaged 5m`` should shrink the analysis batch."""
        # We mock ``analyze_objectives`` so we don't need a real LLM, but
        # leave ``_apply_conversation_filters`` real so the engagement
        # filter runs end-to-end.
        from ohtv.analysis.objectives import AnalysisResult, ObjectiveAnalysis

        analyzed_dirs: list[str] = []

        def fake_analyze(conv_dir, *args, **kwargs):  # noqa: ANN001 — test stub
            # conv_dir's basename is the conversation id (we control it
            # below via the ``_find_conversation_dir`` patch).
            analyzed_dirs.append(Path(conv_dir).name)
            return AnalysisResult(
                analysis=ObjectiveAnalysis(
                    conversation_id=Path(conv_dir).name,
                    context_level="minimal",
                    detail_level="brief",
                    goal="stub",
                    analyzed_at=datetime(2026, 5, 30, 15, 0, tzinfo=timezone.utc),
                    model_used="test",
                    event_count=5,
                    content_hash="abc",
                ),
                cost=0.0,
                from_cache=True,
            )

        def fake_find_dir(config, conv_id):  # noqa: ANN001 — test stub
            # Return a unique path per conversation id so the analyser
            # can recover the id from ``conv_dir.name``.
            return (Path("/tmp/conv") / str(conv_id), None)

        with patch("ohtv.analysis.analyze_objectives", side_effect=fake_analyze), \
             patch("ohtv.cli._find_conversation_dir", side_effect=fake_find_dir), \
             patch("ohtv.cli._count_uncached_conversations_fast", return_value=0), \
             patch("ohtv.cli._get_conversation_labels", return_value={}), \
             patch("ohtv.cli._get_conversation_outputs", return_value=None):
            exit_code, out, _ = _invoke(
                "gen", "objs", "--min-engaged", "5m", "-F", "json", "-A", "-y"
            )

        assert exit_code == 0, out
        # Only the engaged conversation should have made it to the analyser.
        analyzed_set = {d.replace("-", "") for d in analyzed_dirs}
        assert ID_ENGAGED in analyzed_set
        assert ID_UNENGAGED not in analyzed_set

    def test_help_text_contains_all_four_flags(self):
        exit_code, out, _ = _invoke("gen", "objs", "--help")
        assert exit_code == 0
        for flag in (
            "--engaged",
            "--no-engaged",
            "--min-engaged",
            "--min-engagement-ratio",
        ):
            assert flag in out, f"missing {flag}"

    def test_mutual_exclusion_exits_2(self, seeded_db):
        exit_code, _out, err = _invoke(
            "gen", "objs", "--engaged", "--no-engaged"
        )
        assert exit_code == 2
        assert "mutually exclusive" in err

    def test_min_engaged_with_conversation_id_is_usage_error(self, seeded_db):
        # AC adjacency: engagement flags are multi-conv only; combining
        # with a single conversation_id should raise UsageError (exit 2).
        exit_code, _out, err = _invoke(
            "gen", "objs", "abc123def", "--min-engaged", "5m"
        )
        assert exit_code == 2
        assert "filter" in err.lower() or "conversation_id" in err.lower()


# ---------------------------------------------------------------------------
# gen titles — wiring smoke
# ---------------------------------------------------------------------------


class TestGenTitlesEngagementFilter:
    def test_help_text_contains_all_four_flags(self):
        exit_code, out, _ = _invoke("gen", "titles", "--help")
        assert exit_code == 0
        for flag in (
            "--engaged",
            "--no-engaged",
            "--min-engaged",
            "--min-engagement-ratio",
        ):
            assert flag in out, f"missing {flag}"

    def test_mutual_exclusion_exits_2(self, seeded_db, monkeypatch):
        # gen titles requires an API key — set a dummy so we get past
        # the early-exit check before reaching the filter validation.
        monkeypatch.setenv("OPENHANDS_API_KEY", "dummy-key-for-test")
        exit_code, _out, err = _invoke(
            "gen", "titles", "--engaged", "--no-engaged", "--dry-run"
        )
        assert exit_code == 2
        assert "mutually exclusive" in err

    def test_invalid_duration_exits_2(self, seeded_db):
        # Even without an API key set, the Click callback fires first.
        exit_code, _out, err = _invoke(
            "gen", "titles", "--min-engaged", "abc", "--dry-run"
        )
        assert exit_code == 2
        # Click formats the BadParameter message with the param name.
        assert "min-engaged" in err.lower() or "abc" in err.lower()


# ---------------------------------------------------------------------------
# gen run — wiring smoke
# ---------------------------------------------------------------------------


class TestGenRunEngagementFilter:
    def test_help_text_contains_all_four_flags(self):
        exit_code, out, _ = _invoke("gen", "run", "--help")
        assert exit_code == 0
        for flag in (
            "--engaged",
            "--no-engaged",
            "--min-engaged",
            "--min-engagement-ratio",
        ):
            assert flag in out, f"missing {flag}"

    def test_mutual_exclusion_exits_2(self, seeded_db):
        # Use an aggregate job (``themes.discover``) so the path actually
        # reaches ``_apply_conversation_filters`` (single-trajectory job
        # ids bail out earlier with exit 1).
        exit_code, _out, err = _invoke(
            "gen", "run", "themes.discover", "--engaged", "--no-engaged"
        )
        assert exit_code == 2
        assert "mutually exclusive" in err

    def test_invalid_duration_exits_2(self, seeded_db):
        # The Click callback fires before job-id resolution, so a bad
        # ``--min-engaged`` value rejects regardless of the job kind.
        exit_code, _out, err = _invoke(
            "gen", "run", "objs.brief", "--min-engaged", "abc"
        )
        assert exit_code == 2
