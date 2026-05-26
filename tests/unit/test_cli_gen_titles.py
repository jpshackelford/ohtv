"""Integration-ish tests for ``ohtv gen titles`` (Issue #89).

The full pipeline (filter → cache probe → LLM → PATCH → writeback) is
exercised end-to-end with stubs at the two real-world boundaries: the
LLM (callable injected via ``llm_call``) and the cloud HTTP client
(stub injected via ``cloud_client``). Everything else — the filter
plumbing, cache probing, manifest rewrite, DB write — runs on real
code paths against tmp-path filesystems.

What we verify:

* `--dry-run` performs NO PATCH calls and NO manifest / DB writes.
* The apply path PATCHes the cloud and writes back to manifest + DB.
* The placeholder predicate is the default selector.
* `--all-titled` overrides the placeholder predicate.
* Local CLI conversations are silently skipped.
* `update_metadata` writeback is invoked exactly once per renamed conv.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ohtv.sources.base import ConversationInfo


# =============================================================================
# Helpers
# =============================================================================


def _conv(
    conv_id: str,
    *,
    title: str | None,
    source: str = "cloud",
    created_at: datetime | None = None,
) -> ConversationInfo:
    return ConversationInfo(
        id=conv_id,
        title=title,
        created_at=created_at or datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
        updated_at=datetime(2024, 6, 1, 13, 0, tzinfo=timezone.utc),
        event_count=10,
        source=source,
        dir_name=conv_id.replace("-", ""),
    )


def _write_cache(conv_dir: Path, *, goal: str, cache_key: str | None = None) -> None:
    """Drop a minimal valid analysis cache file for ``conv_dir``."""
    conv_dir.mkdir(parents=True, exist_ok=True)
    if cache_key is None:
        cache_key = "assess=False,context_level=minimal,detail_level=brief"
    payload = {
        "version": 1,
        "analyses": {
            cache_key: {
                "conversation_id": conv_dir.name,
                "analyzed_at": "2024-06-01T12:30:00+00:00",
                "model_used": "test/model",
                "event_count": 10,
                "content_hash": "deadbeefcafebabe",
                "prompt_hash": "0123456789abcdef",
                "context_level": "minimal",
                "detail_level": "brief",
                "assess": False,
                "goal": goal,
                "primary_outcomes": [],
                "secondary_outcomes": [],
                "primary_objectives": [],
                "summary": None,
            }
        },
    }
    cache_file = conv_dir / "objective_analysis.json"
    cache_file.write_text(json.dumps(payload))


def _make_llm_stub(titles_by_id: dict[str, str]):
    """Build a deterministic LLM stub that always returns the canned titles."""
    def _call(_system: str, user_prompt: str) -> tuple[str, float]:
        payload = json.loads(user_prompt.split("\n\n", 1)[1])
        out = [
            {"id": item["id"], "title": titles_by_id.get(item["id"], "✨ Generic")}
            for item in payload
        ]
        return json.dumps(out), 0.0001
    return _call


# =============================================================================
# Pipeline tests — go through the real ``_run_gen_titles`` entry point
# =============================================================================


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Force OHTV_DIR and ~/.openhands to live inside tmp_path."""
    ohtv_dir = tmp_path / "ohtv"
    ohtv_dir.mkdir()
    monkeypatch.setenv("OHTV_DIR", str(ohtv_dir))
    monkeypatch.setenv("HOME", str(tmp_path))

    # Synced cloud conversations dir (where analysis caches live)
    (tmp_path / ".openhands" / "cloud" / "conversations").mkdir(parents=True)
    (tmp_path / ".openhands" / "conversations").mkdir(parents=True)

    # API key is required by the command's preflight check.
    monkeypatch.setenv("OPENHANDS_API_KEY", "test-key")
    monkeypatch.setenv("OH_API_KEY", "test-key")
    return tmp_path


def _stub_cloud_client() -> MagicMock:
    """A CloudClient stub whose ``update_conversation`` is observable."""
    client = MagicMock()
    client.update_conversation = MagicMock(return_value=None)
    client.close = MagicMock()
    return client


def _seed_cloud_conv(
    home: Path, conv_id: str, *, goal: str
) -> Path:
    """Create a synced cloud conversation dir with a valid analysis cache.

    Mirrors the production layout: ``$OHTV_DIR/cache/analysis/<id>/objective_analysis.json``.
    The fixture sets ``OHTV_DIR=<tmp>/ohtv``, so we anchor on ``home/"ohtv"``.
    """
    normalized = conv_id.replace("-", "")
    ohtv_cache = Path(home) / "ohtv" / "cache" / "analysis" / normalized
    _write_cache(ohtv_cache, goal=goal)
    return ohtv_cache


class TestDryRun:
    def test_dry_run_makes_no_patch_and_no_writeback(
        self, runner: CliRunner, isolated_env: Path
    ) -> None:
        conv = _conv("aaaaaaaa1234567890abcdefabcdef00", title="Conversation a9315")
        _seed_cloud_conv(isolated_env, conv.id, goal="Add caching layer to API")

        stub_client = _stub_cloud_client()
        stub_llm = _make_llm_stub({conv.id: "✨ Add Caching Layer"})

        filter_result = MagicMock()
        filter_result.conversations = [conv]
        filter_result.show_all = True

        with (
            patch("ohtv.cli._apply_conversation_filters", return_value=filter_result),
            patch("ohtv.cli._apply_local_title_writeback") as mock_writeback,
            patch(
                "ohtv.cli._find_conversation_dir",
                return_value=(
                    isolated_env / "ohtv" / "cache" / "analysis"
                    / conv.id.replace("-", ""),
                    True,
                ),
            ),
            patch(
                "ohtv.analysis.cache.load_all_analyses",
                return_value={
                    "assess=False,context_level=minimal,detail_level=brief": {
                        "conversation_id": conv.id.replace("-", ""),
                        "analyzed_at": "2024-06-01T12:30:00+00:00",
                        "model_used": "test/model",
                        "event_count": 10,
                        "content_hash": "deadbeefcafebabe",
                        "prompt_hash": "0123456789abcdef",
                        "context_level": "minimal",
                        "detail_level": "brief",
                        "assess": False,
                        "goal": "Add caching layer to API",
                        "primary_outcomes": [],
                        "secondary_outcomes": [],
                        "primary_objectives": [],
                        "summary": None,
                    }
                },
            ),
        ):
            from ohtv.cli import _run_gen_titles
            _run_gen_titles(
                limit=None,
                show_all=True,
                offset=0,
                since_date=None,
                until_date=None,
                day_date=None,
                week_date=None,
                pr_filter=None,
                repo_filter=None,
                label_filter=None,
                reverse=False,
                all_titled=False,
                dry_run=True,
                workers=2,
                batch_size=25,
                model=None,
                yes=True,
                llm_call=stub_llm,
                cloud_client=stub_client,
            )

        # Dry-run = no PATCH and no writeback
        assert stub_client.update_conversation.call_count == 0
        assert mock_writeback.call_count == 0

    def test_dry_run_prints_diff_table(
        self, runner: CliRunner, isolated_env: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Dry-run prints the old → new diff table."""
        conv = _conv("bbbbbbbb1234567890abcdefabcdef00", title="Conversation b1234")
        stub_client = _stub_cloud_client()
        stub_llm = _make_llm_stub({conv.id: "🔧 Fix Sync Loop"})

        filter_result = MagicMock()
        filter_result.conversations = [conv]
        filter_result.show_all = True

        with (
            patch("ohtv.cli._apply_conversation_filters", return_value=filter_result),
            patch(
                "ohtv.cli._find_conversation_dir",
                return_value=(isolated_env / "fake-conv-dir", True),
            ),
            patch(
                "ohtv.analysis.cache.load_all_analyses",
                return_value={
                    "assess=False,context_level=minimal,detail_level=brief": {
                        "conversation_id": conv.id.replace("-", ""),
                        "analyzed_at": "2024-06-01T12:30:00+00:00",
                        "model_used": "test/model",
                        "event_count": 10,
                        "content_hash": "h",
                        "prompt_hash": "p",
                        "context_level": "minimal",
                        "detail_level": "brief",
                        "assess": False,
                        "goal": "Fix the sync loop.",
                        "primary_outcomes": [],
                        "secondary_outcomes": [],
                        "primary_objectives": [],
                        "summary": None,
                    }
                },
            ),
        ):
            from ohtv.cli import _run_gen_titles
            _run_gen_titles(
                limit=None,
                show_all=True,
                offset=0,
                since_date=None,
                until_date=None,
                day_date=None,
                week_date=None,
                pr_filter=None,
                repo_filter=None,
                label_filter=None,
                reverse=False,
                all_titled=False,
                dry_run=True,
                workers=2,
                batch_size=25,
                model=None,
                yes=True,
                llm_call=stub_llm,
                cloud_client=stub_client,
            )

        captured = capsys.readouterr()
        # The diff table should appear in stdout
        assert "Fix Sync Loop" in captured.out
        assert "dry-run" in captured.out.lower()


class TestApplyPath:
    def test_apply_calls_patch_and_writeback(
        self, isolated_env: Path
    ) -> None:
        conv = _conv("cccccccc1234567890abcdefabcdef00", title="Conversation c5678")
        stub_client = _stub_cloud_client()
        stub_llm = _make_llm_stub({conv.id: "🚀 Ship The Thing"})

        filter_result = MagicMock()
        filter_result.conversations = [conv]
        filter_result.show_all = True

        with (
            patch("ohtv.cli._apply_conversation_filters", return_value=filter_result),
            patch("ohtv.cli._apply_local_title_writeback", return_value=1) as wb,
            patch(
                "ohtv.cli._find_conversation_dir",
                return_value=(isolated_env / "fake-conv-dir", True),
            ),
            patch(
                "ohtv.analysis.cache.load_all_analyses",
                return_value={
                    "assess=False,context_level=minimal,detail_level=brief": {
                        "conversation_id": conv.id.replace("-", ""),
                        "analyzed_at": "2024-06-01T12:30:00+00:00",
                        "model_used": "test/model",
                        "event_count": 10,
                        "content_hash": "h",
                        "prompt_hash": "p",
                        "context_level": "minimal",
                        "detail_level": "brief",
                        "assess": False,
                        "goal": "Ship the thing.",
                        "primary_outcomes": [],
                        "secondary_outcomes": [],
                        "primary_objectives": [],
                        "summary": None,
                    }
                },
            ),
        ):
            from ohtv.cli import _run_gen_titles
            _run_gen_titles(
                limit=None,
                show_all=True,
                offset=0,
                since_date=None,
                until_date=None,
                day_date=None,
                week_date=None,
                pr_filter=None,
                repo_filter=None,
                label_filter=None,
                reverse=False,
                all_titled=False,
                dry_run=False,
                workers=2,
                batch_size=25,
                model=None,
                yes=True,
                llm_call=stub_llm,
                cloud_client=stub_client,
            )

        # Apply path: PATCH issued exactly once with the new title
        stub_client.update_conversation.assert_called_once_with(
            conv.id, title="🚀 Ship The Thing"
        )
        # Writeback invoked with the rename map (passed as keyword arg)
        wb.assert_called_once()
        kwargs = wb.call_args.kwargs
        assert kwargs["renamed_id_to_title"] == {conv.id: "🚀 Ship The Thing"}


class TestSelectorBehavior:
    def test_default_skips_well_titled_conversations(self, isolated_env: Path) -> None:
        good = _conv("ddddddddffffffff00000000eeeeeeee", title="🚀 Real Title")
        placeholder = _conv("eeeeeeee00000000ffffffffdddddddd", title="Conversation deadb")
        stub_client = _stub_cloud_client()
        stub_llm = _make_llm_stub({placeholder.id: "✨ Generated"})

        filter_result = MagicMock()
        filter_result.conversations = [good, placeholder]
        filter_result.show_all = True

        with (
            patch("ohtv.cli._apply_conversation_filters", return_value=filter_result),
            patch("ohtv.cli._apply_local_title_writeback", return_value=1),
            patch(
                "ohtv.cli._find_conversation_dir",
                return_value=(isolated_env / "fake", True),
            ),
            patch(
                "ohtv.analysis.cache.load_all_analyses",
                return_value={
                    "assess=False,context_level=minimal,detail_level=brief": {
                        "conversation_id": placeholder.id.replace("-", ""),
                        "analyzed_at": "2024-06-01T12:30:00+00:00",
                        "model_used": "test/model",
                        "event_count": 10,
                        "content_hash": "h",
                        "prompt_hash": "p",
                        "context_level": "minimal",
                        "detail_level": "brief",
                        "assess": False,
                        "goal": "Do a thing.",
                        "primary_outcomes": [],
                        "secondary_outcomes": [],
                        "primary_objectives": [],
                        "summary": None,
                    }
                },
            ),
        ):
            from ohtv.cli import _run_gen_titles
            _run_gen_titles(
                limit=None,
                show_all=True,
                offset=0,
                since_date=None,
                until_date=None,
                day_date=None,
                week_date=None,
                pr_filter=None,
                repo_filter=None,
                label_filter=None,
                reverse=False,
                all_titled=False,
                dry_run=False,
                workers=2,
                batch_size=25,
                model=None,
                yes=True,
                llm_call=stub_llm,
                cloud_client=stub_client,
            )

        # Only the placeholder-titled conversation gets PATCHed
        assert stub_client.update_conversation.call_count == 1
        called_ids = {call.args[0] for call in stub_client.update_conversation.call_args_list}
        assert called_ids == {placeholder.id}

    def test_all_titled_overrides_predicate(self, isolated_env: Path) -> None:
        good = _conv("ddddddddffffffff00000000eeeeeeee", title="🚀 Real Title")
        placeholder = _conv("eeeeeeee00000000ffffffffdddddddd", title="Conversation deadb")
        stub_client = _stub_cloud_client()
        stub_llm = _make_llm_stub({
            good.id: "✨ Updated Real Title",
            placeholder.id: "✨ Generated",
        })

        filter_result = MagicMock()
        filter_result.conversations = [good, placeholder]
        filter_result.show_all = True

        with (
            patch("ohtv.cli._apply_conversation_filters", return_value=filter_result),
            patch("ohtv.cli._apply_local_title_writeback", return_value=2),
            patch(
                "ohtv.cli._find_conversation_dir",
                return_value=(isolated_env / "fake", True),
            ),
            patch(
                "ohtv.analysis.cache.load_all_analyses",
                return_value={
                    "assess=False,context_level=minimal,detail_level=brief": {
                        "conversation_id": "x",
                        "analyzed_at": "2024-06-01T12:30:00+00:00",
                        "model_used": "test/model",
                        "event_count": 10,
                        "content_hash": "h",
                        "prompt_hash": "p",
                        "context_level": "minimal",
                        "detail_level": "brief",
                        "assess": False,
                        "goal": "Do a thing.",
                        "primary_outcomes": [],
                        "secondary_outcomes": [],
                        "primary_objectives": [],
                        "summary": None,
                    }
                },
            ),
        ):
            from ohtv.cli import _run_gen_titles
            _run_gen_titles(
                limit=None,
                show_all=True,
                offset=0,
                since_date=None,
                until_date=None,
                day_date=None,
                week_date=None,
                pr_filter=None,
                repo_filter=None,
                label_filter=None,
                reverse=False,
                all_titled=True,  # <— override predicate
                dry_run=False,
                workers=2,
                batch_size=25,
                model=None,
                yes=True,
                llm_call=stub_llm,
                cloud_client=stub_client,
            )

        assert stub_client.update_conversation.call_count == 2

    def test_local_conversations_are_silently_skipped(
        self, isolated_env: Path, capsys: pytest.CaptureFixture
    ) -> None:
        local = _conv(
            "ffffffff00000000aaaaaaaa11111111", title="Conversation aaaaa", source="local"
        )
        stub_client = _stub_cloud_client()
        stub_llm = _make_llm_stub({local.id: "Should Never See This"})

        filter_result = MagicMock()
        filter_result.conversations = [local]
        filter_result.show_all = True

        with patch("ohtv.cli._apply_conversation_filters", return_value=filter_result):
            from ohtv.cli import _run_gen_titles
            _run_gen_titles(
                limit=None,
                show_all=True,
                offset=0,
                since_date=None,
                until_date=None,
                day_date=None,
                week_date=None,
                pr_filter=None,
                repo_filter=None,
                label_filter=None,
                reverse=False,
                all_titled=False,
                dry_run=False,
                workers=2,
                batch_size=25,
                model=None,
                yes=True,
                llm_call=stub_llm,
                cloud_client=stub_client,
            )

        assert stub_client.update_conversation.call_count == 0
        # End-of-run note about skipped locals
        out = capsys.readouterr().out
        assert "local conversation" in out.lower()

    def test_no_cached_analysis_skips_conv_without_llm_call(
        self, isolated_env: Path
    ) -> None:
        conv = _conv("11111111222222223333333344444444", title="Conversation 11111")
        stub_client = _stub_cloud_client()
        llm_called: list[tuple[str, str]] = []

        def _llm(system: str, user: str) -> tuple[str, float]:
            llm_called.append((system, user))
            return "[]", 0.0

        filter_result = MagicMock()
        filter_result.conversations = [conv]
        filter_result.show_all = True

        # load_all_analyses returns empty dict → cache miss
        with (
            patch("ohtv.cli._apply_conversation_filters", return_value=filter_result),
            patch("ohtv.cli._apply_local_title_writeback", return_value=0),
            patch(
                "ohtv.cli._find_conversation_dir",
                return_value=(isolated_env / "fake", True),
            ),
            patch("ohtv.analysis.cache.load_all_analyses", return_value={}),
        ):
            from ohtv.cli import _run_gen_titles
            _run_gen_titles(
                limit=None,
                show_all=True,
                offset=0,
                since_date=None,
                until_date=None,
                day_date=None,
                week_date=None,
                pr_filter=None,
                repo_filter=None,
                label_filter=None,
                reverse=False,
                all_titled=False,
                dry_run=False,
                workers=2,
                batch_size=25,
                model=None,
                yes=True,
                llm_call=_llm,
                cloud_client=stub_client,
            )

        # LLM never invoked, no PATCH issued
        assert llm_called == []
        assert stub_client.update_conversation.call_count == 0


# =============================================================================
# Direct unit test for the local writeback helper
# =============================================================================


class TestLocalWriteback:
    def test_writeback_updates_manifest_and_db(
        self, isolated_env: Path
    ) -> None:
        """``_apply_local_title_writeback`` updates manifest title and DB row."""
        from ohtv.cli import _apply_local_title_writeback
        from ohtv.config import Config, get_manifest_path
        from ohtv.sync import SyncManifest

        # Seed manifest with a placeholder-titled conv
        conv_id = "aaaaaaaa-1111-2222-3333-444444444444"
        manifest_path = get_manifest_path()
        manifest = SyncManifest(
            last_sync_at=None,
            sync_count=0,
            conversations={
                conv_id: {
                    "title": "Conversation aaaaa",
                    "updated_at": "2024-06-01T13:00:00+00:00",
                    "event_count": 10,
                    "downloaded_at": "2024-06-01T13:00:01+00:00",
                    "labels": None,
                }
            },
        )
        manifest.save(manifest_path)
        original_last_sync = manifest.last_sync_at

        # Seed DB with a matching row
        from ohtv.db import get_db_path, migrate

        db_path = get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        normalized = conv_id.replace("-", "")
        conn = sqlite3.connect(db_path)
        migrate(conn)
        conn.execute(
            "INSERT INTO conversations (id, title, source, location) "
            "VALUES (?, ?, ?, ?)",
            (normalized, "Conversation aaaaa", "cloud", "/fake/path"),
        )
        conn.commit()
        conn.close()

        config = Config.from_env()
        updated = _apply_local_title_writeback(
            config,
            renamed_id_to_title={conv_id: "✨ Real New Title"},
        )

        # Manifest write happened
        manifest_after = SyncManifest.load(manifest_path)
        assert manifest_after.conversations[conv_id]["title"] == "✨ Real New Title"
        # last_sync_at must NOT have advanced (issue requirement)
        assert manifest_after.last_sync_at == original_last_sync

        # DB row updated
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT title FROM conversations WHERE id = ?", (normalized,)
        ).fetchone()
        conn.close()
        assert row[0] == "✨ Real New Title"
        assert updated == 1

    def test_writeback_is_noop_when_empty(self, isolated_env: Path) -> None:
        from ohtv.cli import _apply_local_title_writeback
        from ohtv.config import Config

        config = Config.from_env()
        assert _apply_local_title_writeback(config, {}) == 0
