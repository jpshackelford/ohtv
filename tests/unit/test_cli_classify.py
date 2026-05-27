"""CLI smoke tests for ``ohtv classify`` (issue #83).

Test plan mapping (numbering matches the technical-approach comment on
issue #83):

* test  #9 — :func:`test_classify_help`
* test #10 — :func:`test_classify_invalid_source_rejected`
* test #11 — :func:`test_classify_bulk_requires_confirm`
* test #12 — :func:`test_classify_bulk_with_confirm_writes`
* test #13 — :func:`test_classify_single_conversation_no_confirm_needed`
* test #14 — :func:`test_classify_list_unknown_machine_readable`

Acceptance criterion mapping:

* AC1 (single-conv override, no --confirm) → test #13
* AC3 (--list-unknown + machine-readable) → test #14
* AC4 (bulk preview, no writes) → test #11
* AC5 (bulk apply --confirm) → test #12
* AC9 (invalid --source rejected) → test #10
* All others — covered by the unit suite in test_classify.py.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from ohtv.cli import main
from ohtv.db.migrations import migrate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the CLI at a fresh tmp DB with the full migration chain.

    Mirrors the pattern from tests/unit/test_cli_fetch_loc.py — same
    OHTV_DIR + OHTV_DB_PATH + HOME setup the test_cli_fetch_loc suite
    uses to keep CLI tests hermetic.
    """
    ohtv_dir = tmp_path / "ohtv"
    ohtv_dir.mkdir()
    db_path = ohtv_dir / "index.db"

    monkeypatch.setenv("OHTV_DIR", str(ohtv_dir))
    monkeypatch.setenv("OHTV_DB_PATH", str(db_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    conn.close()
    return db_path


def _seed_three_unknown_no_fu(db_path: Path) -> list[str]:
    """Insert 3 conversations with 0 followups, all 'unknown'.

    Returns the list of conversation IDs (without dashes).
    """
    ids: list[str] = []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    created = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    for i in range(3):
        cid = f"convnofu{i:024d}"
        ids.append(cid)
        conn.execute(
            "INSERT INTO conversations (id, location, event_count, title, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (cid, "/tmp/fake", 1, f"row {i}", created),
        )
        conn.execute(
            """
            INSERT INTO conversation_human_input (
                conversation_id, initial_prompt_words, initial_prompt_source,
                followup_word_count, followup_message_count, processed_at, event_count
            ) VALUES (?, ?, 'unknown', ?, ?, ?, ?)
            """,
            (cid, 5, 0, 0, "2024-06-01T12:00:00+00:00", 1),
        )
    conn.commit()
    conn.close()
    return ids


def _read_source(db_path: Path, cid: str) -> str | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT initial_prompt_source FROM conversation_human_input "
        "WHERE conversation_id = ?",
        (cid,),
    ).fetchone()
    conn.close()
    return row["initial_prompt_source"] if row else None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_classify_help(runner: CliRunner) -> None:
    """Test #9: --help exits 0 and mentions the headline options.

    This is the spec-compliance smoke. The set of options is the public
    contract; breaking any of these names would silently break the
    documented `ohtv classify` workflows in the README.
    """
    result = runner.invoke(main, ["classify", "--help"])
    assert result.exit_code == 0, result.output
    for needle in (
        "--source",
        "--no-followups",
        "--has-followups",
        "--list-unknown",
        "--confirm",
        "--repo",
    ):
        assert needle in result.output, f"missing {needle!r} in help text"


def test_classify_invalid_source_rejected(runner: CliRunner) -> None:
    """Test #10 / AC9: --source foo is rejected by Click.

    No isolated_db needed — Click rejects this before we ever touch
    the DB.
    """
    result = runner.invoke(main, ["classify", "--no-followups", "--source", "foo"])
    assert result.exit_code != 0
    # Click renders the choice error in combined output (mix_stderr=True default).
    assert "foo" in result.output
    assert (
        "Invalid value for '--source'" in result.output
        or "invalid choice" in result.output.lower()
    )


def test_classify_bulk_requires_confirm(
    runner: CliRunner, isolated_db: Path
) -> None:
    """Test #11 / AC4: bulk without --confirm is a preview only (no DB writes)."""
    ids = _seed_three_unknown_no_fu(isolated_db)

    result = runner.invoke(
        main, ["classify", "--no-followups", "--source", "automation"]
    )
    assert result.exit_code == 0, result.output
    assert "Would classify" in result.output
    assert "3" in result.output
    assert "--confirm" in result.output

    # Crucially: nothing was actually changed.
    for cid in ids:
        assert _read_source(isolated_db, cid) == "unknown"


def test_classify_bulk_with_confirm_writes(
    runner: CliRunner, isolated_db: Path
) -> None:
    """Test #12 / AC5: bulk --confirm actually writes."""
    ids = _seed_three_unknown_no_fu(isolated_db)

    result = runner.invoke(
        main, ["classify", "--no-followups", "--source", "automation", "--confirm"]
    )
    assert result.exit_code == 0, result.output
    assert "Classified" in result.output and "3" in result.output

    for cid in ids:
        assert _read_source(isolated_db, cid) == "automation"


def test_classify_single_conversation_no_confirm_needed(
    runner: CliRunner, isolated_db: Path
) -> None:
    """Test #13 / AC1: single-conv mode does not need --confirm."""
    ids = _seed_three_unknown_no_fu(isolated_db)
    target = ids[0]

    result = runner.invoke(main, ["classify", target, "--source", "human"])
    assert result.exit_code == 0, result.output
    assert "Set" in result.output or "->" in result.output

    assert _read_source(isolated_db, target) == "human"
    # Other rows untouched.
    assert _read_source(isolated_db, ids[1]) == "unknown"
    assert _read_source(isolated_db, ids[2]) == "unknown"


def test_classify_list_unknown_machine_readable(
    runner: CliRunner, isolated_db: Path
) -> None:
    """Test #14 / AC3: --list-unknown -1 is one short_id per line, no Rich decoration."""
    ids = _seed_three_unknown_no_fu(isolated_db)

    result = runner.invoke(main, ["classify", "--list-unknown", "-1"])
    assert result.exit_code == 0, result.output

    # One short_id per line, no extras.
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert sorted(lines) == sorted(cid[:8] for cid in ids)

    # No Rich color codes, table borders, or headers in the output.
    assert "[" not in result.output  # no [bold] or [dim] markup
    assert "─" not in result.output  # no box-drawing characters
    assert "short_id" not in result.output  # no header row


# ---------------------------------------------------------------------------
# Additional smoke tests for the mutual-exclusion + missing-row paths
# (not numbered 9-14 but they pin the friendly-error behaviour the
# technical comment locks in).
# ---------------------------------------------------------------------------


def test_classify_mutex_no_followups_and_has_followups(
    runner: CliRunner, isolated_db: Path
) -> None:
    result = runner.invoke(
        main,
        [
            "classify",
            "--no-followups",
            "--has-followups",
            "--source",
            "human",
            "--confirm",
        ],
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_classify_mutex_single_and_bulk(
    runner: CliRunner, isolated_db: Path
) -> None:
    result = runner.invoke(
        main,
        [
            "classify",
            "deadbeef" * 4,
            "--no-followups",
            "--source",
            "automation",
        ],
    )
    assert result.exit_code != 0
    assert "CONVERSATION_ID" in result.output


def test_classify_single_refuses_when_no_human_input_row(
    runner: CliRunner, isolated_db: Path
) -> None:
    """AC8 single-conv path: refuse with a clear actionable message."""
    # Insert a conversation but NO conversation_human_input row.
    cid = "abcdef01" + "0" * 24
    conn = sqlite3.connect(isolated_db)
    conn.execute(
        "INSERT INTO conversations (id, location, event_count) VALUES (?, ?, ?)",
        (cid, "/tmp/fake", 1),
    )
    conn.commit()
    conn.close()

    result = runner.invoke(main, ["classify", cid, "--source", "human"])
    assert result.exit_code != 0
    assert "ohtv db process human_input" in result.output


# ---------------------------------------------------------------------------
# Short-ID prefix resolution + B-2 error distinction (PR #99 review round)
# ---------------------------------------------------------------------------


def _seed_distinct_short_ids(db_path: Path) -> list[str]:
    """Seed three conversations whose first 8 chars are unique.

    ``_seed_three_unknown_no_fu`` deliberately uses near-identical IDs
    (they differ only in the last digit) to exercise other code paths,
    so it's unsuitable for short-prefix tests. This helper seeds
    ``aaaa****`` / ``bbbb****`` / ``cccc****`` so an 8-char prefix is
    unique by construction.
    """
    ids: list[str] = []
    created = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    for prefix in ("aaaa1111", "bbbb2222", "cccc3333"):
        cid = prefix + "0" * 24
        ids.append(cid)
        conn.execute(
            "INSERT INTO conversations (id, location, event_count, title, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (cid, "/tmp/fake", 1, f"row {prefix}", created),
        )
        conn.execute(
            """
            INSERT INTO conversation_human_input (
                conversation_id, initial_prompt_words, initial_prompt_source,
                followup_word_count, followup_message_count, processed_at, event_count
            ) VALUES (?, ?, 'unknown', ?, ?, ?, ?)
            """,
            (cid, 5, 0, 0, "2024-06-01T12:00:00+00:00", 1),
        )
    conn.commit()
    conn.close()
    return ids


def test_classify_single_accepts_short_id_prefix(
    runner: CliRunner, isolated_db: Path
) -> None:
    """B-1: README example #5 (``--list-unknown -1 | xargs classify``).

    ``-1`` emits 8-char short IDs. The pipeline must succeed: a unique
    short prefix resolves to the full row instead of erroring out.
    """
    ids = _seed_distinct_short_ids(isolated_db)
    # First 8 chars uniquely identify each row by construction.
    short_target = ids[0][:8]
    assert short_target == "aaaa1111"

    result = runner.invoke(main, ["classify", short_target, "--source", "human"])
    assert result.exit_code == 0, result.output
    assert _read_source(isolated_db, ids[0]) == "human"
    assert _read_source(isolated_db, ids[1]) == "unknown"
    assert _read_source(isolated_db, ids[2]) == "unknown"


def test_classify_single_rejects_ambiguous_short_id(
    runner: CliRunner, isolated_db: Path
) -> None:
    """B-1: ambiguous prefix must be rejected, not silently target one row."""
    ids = _seed_three_unknown_no_fu(isolated_db)
    # First 8 chars (``convnofu``) match all three seeded conversations.
    ambiguous = ids[0][:8]

    result = runner.invoke(main, ["classify", ambiguous, "--source", "human"])
    assert result.exit_code == 2
    assert "Ambiguous" in result.output
    assert "3 matches" in result.output
    # No row was touched.
    for cid in ids:
        assert _read_source(isolated_db, cid) == "unknown"


def test_classify_single_no_such_conversation_distinct_error(
    runner: CliRunner, isolated_db: Path
) -> None:
    """B-2: a fabricated ID must NOT blame the human_input stage.

    Before the fix, every fabricated/typoed ID produced
    ``No conversation_human_input row for conversation '...'. Run 'ohtv
    db process human_input' first.`` — which is misleading because the
    real problem is that the conversation isn't indexed at all.
    """
    # DB has no conversations at all.
    result = runner.invoke(
        main, ["classify", "deadbeef", "--source", "human"]
    )
    assert result.exit_code == 2
    assert "No such conversation" in result.output
    # The error must NOT pretend the human_input stage is to blame.
    assert "conversation_human_input" not in result.output
    assert "ohtv db process human_input" not in result.output
    # And it should point at the real remediation.
    assert "ohtv db scan" in result.output
