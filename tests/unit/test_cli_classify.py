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


def _seed_root_and_sub(db_path: Path) -> tuple[str, str]:
    """Seed 1 root + 1 sub-conversation, both ``initial_prompt_source='unknown'``.

    Used by the issue #126 auto-classification smoke tests. Returns
    ``(root_id, sub_id)`` (normalised, no dashes).
    """
    root_id = "rootcli" + "0".zfill(25)
    sub_id = "subcli0" + "0".zfill(25)
    created = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Root: parent_conversation_id IS NULL.
    conn.execute(
        "INSERT INTO conversations "
        "(id, location, event_count, title, created_at, parent_conversation_id) "
        "VALUES (?, ?, ?, ?, ?, NULL)",
        (root_id, "/tmp/fake/root", 1, "root", created),
    )
    # Sub: parent_conversation_id = root_id.
    conn.execute(
        "INSERT INTO conversations "
        "(id, location, event_count, title, created_at, parent_conversation_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (sub_id, "/tmp/fake/sub", 1, "sub", created, root_id),
    )
    for cid in (root_id, sub_id):
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
    return root_id, sub_id


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


# ---------------------------------------------------------------------------
# Issue #126 — sub-conversation auto-classification, end-to-end
# ---------------------------------------------------------------------------


def test_classify_list_unknown_auto_classifies_subs(
    runner: CliRunner, isolated_db: Path
) -> None:
    """T-F (--list-unknown): auto-step runs ahead of mode dispatch.

    Seeds 1 root + 1 sub (both ``'unknown'``). Runs
    ``ohtv classify --list-unknown``. After the auto-step the sub is
    ``'sub_agent'``, so --list-unknown only shows the root.
    """
    root_id, sub_id = _seed_root_and_sub(isolated_db)

    result = runner.invoke(main, ["classify", "--list-unknown"])

    assert result.exit_code == 0, result.output
    # Auto-step notice fires (1 sub flipped).
    assert "Auto-classified 1 sub-conversation(s) as 'sub_agent'" in result.output
    # Sub is now 'sub_agent'; root is unchanged.
    assert _read_source(isolated_db, sub_id) == "sub_agent"
    assert _read_source(isolated_db, root_id) == "unknown"
    # --list-unknown output mentions the root's short_id but NOT the sub's.
    assert root_id[:8] in result.output
    assert sub_id[:8] not in result.output


def test_classify_bulk_auto_classifies_subs(
    runner: CliRunner, isolated_db: Path
) -> None:
    """T-F (bulk): auto-step runs ahead of the bulk apply path.

    Even on the bulk path that only touches 'unknown' rows for roots,
    the auto-step has already moved subs to 'sub_agent' first — so the
    subsequent ``--source automation`` heuristic only flips the root.
    """
    root_id, sub_id = _seed_root_and_sub(isolated_db)

    result = runner.invoke(
        main,
        ["classify", "--no-followups", "--source", "automation", "--confirm"],
    )

    assert result.exit_code == 0, result.output
    assert "Auto-classified 1 sub-conversation(s) as 'sub_agent'" in result.output
    # Sub is 'sub_agent' (auto-step); the bulk heuristic only touches
    # 'unknown' rows so it does NOT clobber the sub back to 'automation'.
    assert _read_source(isolated_db, sub_id) == "sub_agent"
    # The bulk apply flipped the root (no followups, --source automation).
    assert _read_source(isolated_db, root_id) == "automation"


def test_classify_single_auto_classifies_subs(
    runner: CliRunner, isolated_db: Path
) -> None:
    """T-F (single): auto-step runs ahead of ``set_single``.

    The single-conversation override path is the only one where the
    operator's intent can outlive the auto-step within a single
    invocation — set_single runs after the auto-step and is allowed to
    flip already-classified rows (AC5). Target the root here to keep
    the assertion clean: the auto-step touched the sub, then
    set_single touched the root.
    """
    root_id, sub_id = _seed_root_and_sub(isolated_db)

    result = runner.invoke(
        main, ["classify", root_id, "--source", "human"]
    )

    assert result.exit_code == 0, result.output
    assert "Auto-classified 1 sub-conversation(s) as 'sub_agent'" in result.output
    # Sub flipped by auto-step.
    assert _read_source(isolated_db, sub_id) == "sub_agent"
    # Root flipped by set_single (operator override).
    assert _read_source(isolated_db, root_id) == "human"


def test_classify_auto_step_is_idempotent_across_invocations(
    runner: CliRunner, isolated_db: Path
) -> None:
    """Running classify twice in a row only changes rows on the first call.

    Models AC2 + AC3 idempotency at the CLI surface: invocation #1
    flips the sub and emits the "Auto-classified 1 sub-conversation(s)"
    notice; invocation #2 finds nothing to change and emits no notice.
    """
    _seed_root_and_sub(isolated_db)

    first = runner.invoke(main, ["classify", "--list-unknown"])
    second = runner.invoke(main, ["classify", "--list-unknown"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    # First call: notice present.
    assert "Auto-classified 1 sub-conversation(s)" in first.output
    # Second call: no rows changed -> no notice.
    assert "Auto-classified" not in second.output


def test_classify_guardrail_missing_migration_019(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-G (AC7): pre-019 schema raises a clear migration error.

    Builds a tmp DB with just a minimal ``conversations`` table missing
    ``parent_conversation_id``. Any classify mode must surface the
    guardrail message before doing any DB work.
    """
    ohtv_dir = tmp_path / "ohtv"
    ohtv_dir.mkdir()
    db_path = ohtv_dir / "index.db"

    monkeypatch.setenv("OHTV_DIR", str(ohtv_dir))
    monkeypatch.setenv("OHTV_DB_PATH", str(db_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    # Pre-migration-019 shape: conversations table without
    # parent_conversation_id. conversation_human_input table present so
    # the CLI doesn't fail earlier on a different missing-table error.
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT)")
    conn.execute(
        "CREATE TABLE conversation_human_input ("
        "conversation_id TEXT PRIMARY KEY, "
        "initial_prompt_source TEXT NOT NULL DEFAULT 'unknown', "
        "followup_message_count INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    conn.commit()
    conn.close()

    result = runner.invoke(main, ["classify", "--list-unknown"])

    assert result.exit_code == 1, result.output
    assert "migration 019" in result.output
    # Rich may wrap "ohtv db scan" mid-string with a soft newline; collapse
    # whitespace before asserting on the remediation hint.
    normalized = " ".join(result.output.split())
    assert "ohtv db scan" in normalized
