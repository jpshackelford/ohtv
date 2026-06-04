"""CLI integration tests for the engagement filter flags on ``ohtv list``
(Issue #170).

Seeds a real temporary DB with four conversations and four distinct
engagement states (high, low, zero, missing), then invokes ``ohtv list
-F json`` via :class:`click.testing.CliRunner` for each new flag and
asserts the surviving row set.

All tests use ``OHTV_DIR`` + ``OPENHANDS_BASE_DIR`` to keep state
out of the developer's real install.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

from ohtv.cli import main


# ---------------------------------------------------------------------------
# Fixture: four conversations with known engagement states
# ---------------------------------------------------------------------------

# IDs sorted by created_at descending (newest first — matches default sort).
# Lower-case 32-char hex to satisfy the LocalSource id pattern.
ID_HIGH = "a" * 32   # engaged 600s in 1800s total -> 33.3% ratio
ID_LOW = "b" * 32    # engaged 120s in 1800s total -> 6.7%
ID_ZERO = "c" * 32   # engaged 0 (engagement row present but un-engaged)
ID_MISSING = "d" * 32  # no engagement row at all


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """Seed an isolated DB with four engagement-distinct cloud conversations."""
    monkeypatch.setenv("OHTV_DIR", str(tmp_path / "ohtv"))
    monkeypatch.setenv("OPENHANDS_BASE_DIR", str(tmp_path / "oh"))

    from ohtv.db import get_ready_connection
    from ohtv.db.models.conversation import Conversation
    from ohtv.db.stores import ConversationStore

    base = datetime(2026, 5, 30, 14, 0, tzinfo=timezone.utc)

    convs = [
        (ID_HIGH, "High engagement", base, "owner/repo-a"),
        (ID_LOW, "Low engagement", base - timedelta(hours=1), "owner/repo-a"),
        (ID_ZERO, "Zero engagement", base - timedelta(hours=2), "owner/repo-b"),
        (ID_MISSING, "Missing engagement", base - timedelta(hours=3), "owner/repo-b"),
    ]

    with get_ready_connection(show_progress=False) as conn:
        store = ConversationStore(conn)
        for cid, title, created, repo in convs:
            store.upsert(
                Conversation(
                    id=cid,
                    location=str(tmp_path / "conv" / cid),
                    event_count=5,
                    title=title,
                    created_at=created,
                    updated_at=created + timedelta(minutes=30),
                    selected_repository=repo,
                    source="cloud",
                )
            )

        # Seed engagement rows for HIGH / LOW / ZERO. MISSING has none.
        engagement_rows = [
            # (id, engaged, total)
            (ID_HIGH, 600, 1800),
            (ID_LOW, 120, 1800),
            (ID_ZERO, 0, 1800),
        ]
        for cid, engaged, total in engagement_rows:
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
                    total,
                    engaged,
                    1 if engaged > 0 else 0,
                    "2026-05-30T15:00:00+00:00",
                ),
            )
        conn.commit()

    yield tmp_path


def _invoke_list(*args) -> tuple[int, str, str]:
    """Run ``ohtv list`` with the given args, return (exit_code, stdout, stderr).

    Click 8.2+ split stdout/stderr — ``result.stderr`` is available as a
    separate stream. We return both so error-path tests can introspect.
    """
    runner = CliRunner()
    result = runner.invoke(main, ["list", *args])
    # ``result.stderr`` raises if no stderr was captured; default to "".
    try:
        err = result.stderr
    except (ValueError, AttributeError):
        err = ""
    return result.exit_code, result.output, err


def _ids_from_json(output: str) -> set[str]:
    return {item["id"].replace("-", "") for item in json.loads(output)}


# ---------------------------------------------------------------------------
# Single-flag behaviour
# ---------------------------------------------------------------------------


class TestEngagedFlag:
    def test_engaged_keeps_only_positive(self, seeded_db):
        exit_code, out, _ = _invoke_list(
            "--engaged", "-F", "json", "--include-empty", "--all"
        )
        assert exit_code == 0, out
        assert _ids_from_json(out) == {ID_HIGH, ID_LOW}


class TestNoEngagedFlag:
    def test_no_engaged_keeps_zero_and_missing(self, seeded_db):
        exit_code, out, _ = _invoke_list(
            "--no-engaged", "-F", "json", "--include-empty", "--all"
        )
        assert exit_code == 0, out
        assert _ids_from_json(out) == {ID_ZERO, ID_MISSING}


class TestMinEngagedFlag:
    def test_min_engaged_three_minutes(self, seeded_db):
        # 3m == 180s -> HIGH (600s) only; LOW (120s) excluded
        exit_code, out, _ = _invoke_list(
            "--min-engaged", "3m", "-F", "json", "--all"
        )
        assert exit_code == 0, out
        assert _ids_from_json(out) == {ID_HIGH}

    def test_min_engaged_bare_minutes(self, seeded_db):
        # Bare "3" == 3 minutes == 180s. Same result as "3m".
        exit_code, out, _ = _invoke_list(
            "--min-engaged", "3", "-F", "json", "--all"
        )
        assert exit_code == 0, out
        assert _ids_from_json(out) == {ID_HIGH}

    def test_min_engaged_seconds_explicit(self, seeded_db):
        # "200s" excludes LOW (120s).
        exit_code, out, _ = _invoke_list(
            "--min-engaged", "200s", "-F", "json", "--all"
        )
        assert exit_code == 0, out
        assert _ids_from_json(out) == {ID_HIGH}


class TestMinEngagementRatioFlag:
    def test_ratio_threshold(self, seeded_db):
        # HIGH ratio: 600/1800 = 0.333 (33.3%)
        # LOW ratio: 120/1800 = 0.067 (6.7%)
        # Threshold 20% -> HIGH only.
        exit_code, out, _ = _invoke_list(
            "--min-engagement-ratio", "20", "-F", "json", "--all"
        )
        assert exit_code == 0, out
        assert _ids_from_json(out) == {ID_HIGH}


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


class TestComposition:
    def test_engaged_and_min_engaged_threshold_wins(self, seeded_db):
        # --engaged --min-engaged 3m behaves identically to --min-engaged 3m.
        exit_code, out, _ = _invoke_list(
            "--engaged", "--min-engaged", "3m", "-F", "json", "--all"
        )
        assert exit_code == 0, out
        assert _ids_from_json(out) == {ID_HIGH}

    def test_since_compose_with_engaged(self, seeded_db):
        # All four convs are anchored around 2026-05-30 14:00 (HIGH is the
        # newest; MISSING is 3h older). Restrict to "after 2026-05-30 13:00"
        # so the date filter is a no-op (all four pass), then apply --engaged
        # → {HIGH, LOW}. This exercises the AND-compose path between the
        # date filter and the engagement filter end-to-end.
        exit_code, out, _ = _invoke_list(
            "--since", "2026-05-30", "--engaged", "-F", "json", "--all"
        )
        assert exit_code == 0, out
        assert _ids_from_json(out) == {ID_HIGH, ID_LOW}

    def test_no_engaged_with_include_empty(self, seeded_db):
        # --include-empty does NOT negate --no-engaged. ZERO + MISSING
        # both still pass (and neither has zero events anyway).
        exit_code, out, _ = _invoke_list(
            "--no-engaged", "--include-empty", "-F", "json", "--all"
        )
        assert exit_code == 0, out
        assert _ids_from_json(out) == {ID_ZERO, ID_MISSING}

    def test_engaged_with_with_engagement_display(self, seeded_db):
        """``--engaged`` filters; ``--with-engagement`` displays. The two
        are orthogonal — using both must filter AND emit engagement fields."""
        exit_code, out, _ = _invoke_list(
            "--engaged", "--with-engagement", "-F", "json", "--all"
        )
        assert exit_code == 0, out
        rows = json.loads(out)
        assert {row["id"].replace("-", "") for row in rows} == {ID_HIGH, ID_LOW}
        # Every row carries the five engagement fields (PR #171 shape).
        for row in rows:
            for key in (
                "engaged_seconds",
                "attention_periods",
                "engagement_threshold_seconds",
                "total_duration_seconds",
                "engagement_ratio",
            ):
                assert key in row, f"missing {key}: {row}"

    def test_engaged_compose_with_reverse_limit(self, seeded_db):
        # --engaged keeps HIGH + LOW. --reverse + --max 1 -> oldest first
        # of the surviving set -> {LOW}.
        exit_code, out, _ = _invoke_list(
            "--engaged", "--reverse", "--max", "1", "-F", "json"
        )
        assert exit_code == 0, out
        assert _ids_from_json(out) == {ID_LOW}


# ---------------------------------------------------------------------------
# Mutual exclusion
# ---------------------------------------------------------------------------


class TestMutualExclusion:
    def test_engaged_and_no_engaged(self, seeded_db):
        exit_code, _out, err = _invoke_list("--engaged", "--no-engaged")
        assert exit_code == 2
        assert "mutually exclusive" in err

    def test_no_engaged_and_min_engaged(self, seeded_db):
        exit_code, _out, err = _invoke_list("--no-engaged", "--min-engaged", "5m")
        assert exit_code == 2
        assert "--no-engaged" in err

    def test_no_engaged_and_min_engagement_ratio(self, seeded_db):
        exit_code, _out, err = _invoke_list(
            "--no-engaged", "--min-engagement-ratio", "50"
        )
        assert exit_code == 2
        assert "--no-engaged" in err

    def test_invalid_duration(self, seeded_db):
        exit_code, _out, err = _invoke_list("--min-engaged", "abc")
        assert exit_code == 2
        # Click wraps BadParameter as "Invalid value for ..."
        assert "invalid duration" in err.lower() or "abc" in err

    def test_negative_duration(self, seeded_db):
        exit_code, _out, err = _invoke_list("--min-engaged", "-5m")
        assert exit_code == 2

    def test_ratio_out_of_range_high(self, seeded_db):
        exit_code, _out, err = _invoke_list("--min-engagement-ratio", "101")
        assert exit_code == 2

    def test_ratio_out_of_range_low(self, seeded_db):
        exit_code, _out, err = _invoke_list("--min-engagement-ratio", "-1")
        assert exit_code == 2


# ---------------------------------------------------------------------------
# Help text mentions the new flags + the engagement processing stage
# ---------------------------------------------------------------------------


class TestHelpText:
    def test_list_help_shows_all_four_flags(self):
        runner = CliRunner()
        result = runner.invoke(main, ["list", "--help"])
        assert result.exit_code == 0
        for flag in (
            "--engaged",
            "--no-engaged",
            "--min-engaged",
            "--min-engagement-ratio",
        ):
            assert flag in result.output, f"missing {flag} in --help"
        # Help text points at the engagement processing stage
        assert "engagement" in result.output.lower()
        assert "processing stage" in result.output.lower()
