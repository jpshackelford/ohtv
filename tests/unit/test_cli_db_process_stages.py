"""Pin the invariant: every stage in the STAGES registry must be a valid
``ohtv db process <stage>`` choice.

This guards against the click ``Choice`` allowlist drifting from the
``STAGES`` registry (which is what caused the ``human_input`` regression
discovered during manual testing of PR #85).
"""

import json
import shutil
import sqlite3

from click.testing import CliRunner

from ohtv.cli import _run_post_sync_processing, main
from ohtv.db.stages import STAGES


def create_action_conversation(root, conv_id):
    conv = root / conv_id
    events = conv / "events"
    events.mkdir(parents=True)
    (conv / "base_state.json").write_text(json.dumps({
        "id": conv_id,
        "title": f"Conversation {conv_id}",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }))
    (events / "event-00000.json").write_text(json.dumps({
        "id": "event-00000",
        "kind": "ActionEvent",
        "tool_name": "file_editor",
        "action": {"command": "create", "path": "/tmp/example.py"},
    }))
    return conv


def test_every_registered_stage_is_a_valid_db_process_choice() -> None:
    """Each registered stage name must be accepted by ``ohtv db process``."""
    runner = CliRunner()
    for name in STAGES:
        result = runner.invoke(main, ["db", "process", name, "--help"])
        assert result.exit_code == 0, (
            f"stage {name!r} rejected by `ohtv db process`:\n{result.output}"
        )


def test_db_process_all_is_a_valid_choice() -> None:
    """The ``all`` sentinel must remain a valid choice."""
    runner = CliRunner()
    result = runner.invoke(main, ["db", "process", "all", "--help"])
    assert result.exit_code == 0, result.output


def test_db_process_rejects_unknown_stage() -> None:
    """A name not in STAGES (and not ``all``) must be rejected by click."""
    runner = CliRunner()
    result = runner.invoke(main, ["db", "process", "definitely_not_a_stage"])
    assert result.exit_code != 0
    assert "definitely_not_a_stage" in result.output


def test_missing_conversation_directory_is_not_marked_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OHTV_DIR", str(tmp_path / "ohtv"))
    local = tmp_path / "local"
    cloud = tmp_path / "cloud"
    local.mkdir()
    cloud.mkdir()
    monkeypatch.setenv("OHTV_CONVERSATIONS_DIR", str(local))
    monkeypatch.setenv("OHTV_SYNCED_CONVERSATIONS_DIR", str(cloud))
    events = local / "example" / "events"
    events.mkdir(parents=True)
    (events / "event-00000.json").write_text(json.dumps({"kind": "MessageEvent", "content": "hello"}))

    runner = CliRunner()
    assert runner.invoke(main, ["db", "scan"]).exit_code == 0
    shutil.rmtree(local / "example")

    for stage in ("actions", "human_input"):
        result = runner.invoke(main, ["db", "process", stage])
        assert result.exit_code == 0, result.output
        assert "Skipped 1" in result.output

    with sqlite3.connect(tmp_path / "ohtv" / "index.db") as conn:
        assert conn.execute("SELECT count(*) FROM conversation_stages WHERE conversation_id = 'example'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM conversation_human_input WHERE conversation_id = 'example'").fetchone()[0] == 0

    events.mkdir(parents=True)
    (events / "event-00000.json").write_text(json.dumps({"kind": "MessageEvent", "content": "hello"}))
    result = runner.invoke(main, ["db", "process", "actions"])
    assert result.exit_code == 0, result.output
    assert "Processed 1" in result.output


def test_relocated_cloud_conversation_is_reindexed_and_reprocessed(tmp_path, monkeypatch):

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OHTV_DIR", str(tmp_path / "ohtv"))
    local = tmp_path / "local"
    original = tmp_path / "original-cloud"
    relocated = tmp_path / "relocated-cloud"
    local.mkdir()
    monkeypatch.setenv("OHTV_CONVERSATIONS_DIR", str(local))
    monkeypatch.setenv("OHTV_SYNCED_CONVERSATIONS_DIR", str(original))
    old_conv = create_action_conversation(original, "moved")

    runner = CliRunner()
    scan = runner.invoke(main, ["db", "scan", "--remove-missing"])
    assert scan.exit_code == 0, scan.output
    listed = runner.invoke(main, ["list"])
    assert listed.exit_code == 0, listed.output
    assert "Showing 1 of 1 conversations" in listed.output
    status = runner.invoke(main, ["db", "status"])
    assert status.exit_code == 0, status.output
    assert "Conversations: 1" in status.output

    processed = runner.invoke(main, ["db", "process", "actions"])
    assert processed.exit_code == 0, processed.output
    db_path = tmp_path / "ohtv" / "index.db"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT count(*) FROM actions WHERE conversation_id = 'moved'").fetchone()[0] == 1
        conn.execute("DELETE FROM actions WHERE conversation_id = 'moved'")

    old_mtime = (old_conv / "events").stat().st_mtime
    relocated.mkdir()
    shutil.move(str(old_conv), str(relocated / "moved"))
    assert (relocated / "moved" / "events").stat().st_mtime == old_mtime
    monkeypatch.setenv("OHTV_SYNCED_CONVERSATIONS_DIR", str(relocated))
    scan = runner.invoke(main, ["db", "scan"])
    assert scan.exit_code == 0, scan.output
    assert "Updated 1" in scan.output

    fresh = create_action_conversation(relocated, "fresh")
    result = runner.invoke(main, ["db", "process", "all"])
    assert result.exit_code == 0, result.output
    with sqlite3.connect(db_path) as conn:
        paths = conn.execute("SELECT id, location FROM conversations ORDER BY id").fetchall()
        assert paths == [("fresh", str(fresh)), ("moved", str(relocated / "moved"))]
        actions = conn.execute(
            "SELECT conversation_id, action_type, target FROM actions ORDER BY conversation_id"
        ).fetchall()
        assert len(actions) == 2
        assert len({(kind, target) for _, kind, target in actions}) == 1
        assert {conv_id for conv_id, _, _ in actions} == {"fresh", "moved"}

    synced = create_action_conversation(relocated, "synced")
    _run_post_sync_processing(quiet=True, verbose=False, no_llm=True, no_embed=True)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT location FROM conversations WHERE id = 'synced'").fetchone()[0] == str(synced)
        assert conn.execute("SELECT count(*) FROM actions WHERE conversation_id = 'synced'").fetchone()[0] == 1
