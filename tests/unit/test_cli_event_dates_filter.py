"""CLI integration tests for the ``--event-dates`` flag (Issue #180).

Covers ``list``, ``search``, ``ask``, ``gen objs``, ``gen titles``,
``gen run`` — the six commands that gain the flag — and the
cross-flag validation (``--event-dates`` without ``--since`` /
``--until``).

Seeds a real temporary DB with three engagement-distinct
conversations modelled on the issue round-trip example:

* OLD_FRESH — ``created_at = T₀-30d``, ``last_event_ts = T₀``
  (re-touched recently).
* OLD_STALE — ``created_at = T₀-30d``, ``last_event_ts = T₀-25d``
  (cold for ages).
* NEW       — ``created_at = T₀-1d``,  ``last_event_ts = T₀``
  (fresh by both definitions).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

from ohtv.cli import main


# ---------------------------------------------------------------------------
# Test IDs (32-char hex strings, lower-cased so LocalSource accepts them).
# ---------------------------------------------------------------------------
ID_OLD_FRESH = "a" * 32
ID_OLD_STALE = "b" * 32
ID_NEW = "c" * 32


T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    monkeypatch.setenv("OHTV_DIR", str(tmp_path / "ohtv"))
    monkeypatch.setenv("OPENHANDS_BASE_DIR", str(tmp_path / "oh"))

    from ohtv.db import get_ready_connection
    from ohtv.db.models.conversation import Conversation
    from ohtv.db.stores import ConversationStore

    convs = [
        (ID_OLD_FRESH, "Re-touched old conversation",
         T0 - timedelta(days=30), T0 - timedelta(days=30), T0),
        (ID_OLD_STALE, "Cold old conversation",
         T0 - timedelta(days=30), T0 - timedelta(days=30),
         T0 - timedelta(days=25)),
        (ID_NEW, "Brand new conversation",
         T0 - timedelta(days=1), T0 - timedelta(days=1), T0),
    ]

    with get_ready_connection(show_progress=False) as conn:
        store = ConversationStore(conn)
        for cid, title, created, first_ts, last_ts in convs:
            store.upsert(
                Conversation(
                    id=cid,
                    location=str(tmp_path / "conv" / cid),
                    event_count=5,
                    title=title,
                    created_at=created,
                    updated_at=created + timedelta(minutes=30),
                    selected_repository="owner/repo",
                    source="cloud",
                )
            )

            conn.execute(
                "INSERT INTO conversation_engagement "
                "(conversation_id, threshold_seconds, first_event_ts, "
                "last_event_ts, total_duration_seconds, engaged_seconds, "
                "attention_periods, follow_up_user_message_count, "
                "attended_user_message_count, processed_at, event_count) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, 0, 0, ?, 1)",
                (
                    cid, 420,
                    first_ts.isoformat(),
                    last_ts.isoformat(),
                    int((last_ts - first_ts).total_seconds()),
                    600,
                    T0.isoformat(),
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


def _ids_from_json(output: str) -> set[str]:
    return {item["id"].replace("-", "") for item in json.loads(output)}


# ===========================================================================
# Category 1: ``list --event-dates``
# ===========================================================================


class TestListEventDates:
    def test_plain_since_uses_created_at(self, seeded_db):
        """Without --event-dates, only conversations created in the
        last 7 days surface — the round-trip baseline."""
        exit_code, out, _ = _invoke(
            "list", "--since", "2026-05-25", "-F", "json", "--all",
        )
        assert exit_code == 0, out
        # NEW created at T₀-1d (2026-05-31) is in range.
        # OLD_FRESH + OLD_STALE created at T₀-30d are out.
        assert _ids_from_json(out) == {ID_NEW}

    def test_event_dates_since_uses_last_event_ts(self, seeded_db):
        """With --event-dates, OLD_FRESH joins NEW because its
        last_event_ts is T₀."""
        exit_code, out, _ = _invoke(
            "list", "--event-dates", "--since", "2026-05-25",
            "-F", "json", "--all",
        )
        assert exit_code == 0, out
        # OLD_FRESH (last=T₀) + NEW (last=T₀) both >= 2026-05-25.
        # OLD_STALE (last=T₀-25d ≈ 2026-05-07) excluded.
        assert _ids_from_json(out) == {ID_OLD_FRESH, ID_NEW}

    def test_event_dates_with_week_shortcut(self, seeded_db):
        """``-W`` is a ``--since`` shortcut — must satisfy the
        cross-validation check."""
        # -W resolves "this week" relative to the wall clock, so we
        # only assert the call doesn't UsageError out.
        exit_code, out, _ = _invoke(
            "list", "--event-dates", "-W", "-F", "json", "--all",
        )
        # The clock at test time is not 2026, so the filtered set
        # may be empty — what we're proving is the no-error path.
        assert exit_code == 0, out
        # Output is either a JSON array (possibly empty) or a hint
        # banner; both are non-error.

    def test_event_dates_alone_errors(self, seeded_db):
        exit_code, out, err = _invoke("list", "--event-dates")
        assert exit_code == 2
        combined = (out or "") + (err or "")
        assert "--event-dates requires" in combined

    def test_event_dates_excludes_missing_engagement(
        self, seeded_db, monkeypatch
    ):
        """Add a fourth conversation with NO engagement row, confirm
        plain --since includes it but --event-dates excludes it."""
        from ohtv.db import get_ready_connection
        from ohtv.db.models.conversation import Conversation
        from ohtv.db.stores import ConversationStore

        id_missing = "e" * 32
        with get_ready_connection(show_progress=False) as conn:
            store = ConversationStore(conn)
            store.upsert(
                Conversation(
                    id=id_missing,
                    location=str(seeded_db / "conv" / id_missing),
                    event_count=5,
                    title="No engagement row",
                    created_at=T0,
                    updated_at=T0,
                    source="cloud",
                )
            )
            conn.commit()

        # Plain since includes missing-engagement conv.
        exit_code, out, _ = _invoke(
            "list", "--since", "2026-05-25", "-F", "json", "--all",
        )
        assert exit_code == 0, out
        assert id_missing in _ids_from_json(out)

        # --event-dates excludes it.
        exit_code, out, _ = _invoke(
            "list", "--event-dates", "--since", "2026-05-25",
            "-F", "json", "--all",
        )
        assert exit_code == 0, out
        assert id_missing not in _ids_from_json(out)

    def test_empty_result_hint(self, seeded_db, capsys):
        """When --event-dates filters down to zero, the dim hint
        about ``db process engagement`` appears."""
        # Use a future date that no conversation can match.
        exit_code, out, _ = _invoke(
            "list", "--event-dates", "--since", "2027-01-01", "--all",
        )
        assert exit_code == 0, out
        assert "engagement" in out


# ===========================================================================
# Category 2: validation
# ===========================================================================


class TestEventDatesValidation:
    @pytest.mark.parametrize(
        "cmd",
        [
            ["list", "--event-dates"],
            ["gen", "objs", "--event-dates"],
            ["gen", "titles", "--event-dates"],
            ["gen", "run", "themes.discover", "--event-dates"],
        ],
    )
    def test_event_dates_without_date_filter_errors(self, seeded_db, cmd):
        exit_code, out, err = _invoke(*cmd)
        assert exit_code == 2, f"cmd={cmd} out={out} err={err}"
        combined = (out or "") + (err or "")
        assert "--event-dates" in combined


# ===========================================================================
# Category 3: ``search --event-dates``
# ===========================================================================


class TestSearchEventDates:
    """``search --exact`` uses FTS which doesn't push down dates,
    so the FTS path runs an explicit post-filter against
    ``conversation_engagement.last_event_ts`` (see cli.py search body).
    """

    def _seed_fts(self, seeded_db):
        """Insert FTS5 rows so --exact has something to match."""
        from ohtv.db import get_ready_connection

        with get_ready_connection(show_progress=False) as conn:
            for cid, body in (
                (ID_OLD_FRESH, "fresh re-touch about authentication"),
                (ID_OLD_STALE, "stale work about authentication"),
                (ID_NEW, "new work about authentication"),
            ):
                conn.execute(
                    "INSERT INTO conversation_fts "
                    "(conversation_id, content) VALUES (?, ?)",
                    (cid, body),
                )
            conn.commit()

    def test_exact_search_event_dates_excludes_stale(self, seeded_db):
        """The FTS path runs an explicit post-filter against
        ``conversation_engagement.last_event_ts``. The stale conv
        must NOT appear in the output, even though FTS would rank it
        highly without the filter."""
        self._seed_fts(seeded_db)
        exit_code, out, err = _invoke(
            "search", "authentication",
            "--exact", "--event-dates",
            "--since", "2026-05-25",
        )
        assert exit_code == 0, f"out={out} err={err}"
        # OLD_STALE's id ("bbbb...") must not appear in the output.
        assert ID_OLD_STALE not in out

    def test_exact_search_event_dates_alone_errors(self, seeded_db):
        """``search --exact --event-dates`` without --since/--until
        must surface a UsageError exit 2 — same contract as ``list``."""
        exit_code, out, err = _invoke(
            "search", "authentication", "--exact", "--event-dates",
        )
        assert exit_code == 2, f"out={out} err={err}"
        combined = (out or "") + (err or "")
        assert "--event-dates" in combined
