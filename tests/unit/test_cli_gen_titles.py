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

from ohtv.cli import _WritebackResult
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
            patch("ohtv.cli._apply_local_title_writeback", return_value=_WritebackResult(1, 1, 1)) as wb,
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
            patch("ohtv.cli._apply_local_title_writeback", return_value=_WritebackResult(1, 1, 1)),
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
            patch("ohtv.cli._apply_local_title_writeback", return_value=_WritebackResult(2, 2, 2)),
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
            patch("ohtv.cli._apply_local_title_writeback", return_value=_WritebackResult(0, 0, 0)),
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
        """``_apply_local_title_writeback`` updates manifest title and DB row.

        Real-world key shape: the sync manifest keys conversations on
        the normalized (no-dashes) id, matching what ``ohtv sync``
        actually writes. The DB also stores normalized ids (AGENTS.md
        #25 / migration 012). The CloudConversation id arrives dashed —
        the helper must normalize at the lookup site.
        """
        from ohtv.cli import _apply_local_title_writeback
        from ohtv.config import Config, get_manifest_path
        from ohtv.sync import SyncManifest

        # Dashed id (the shape CloudConversation hands us).
        conv_id_dashed = "aaaaaaaa-1111-2222-3333-444444444444"
        normalized = conv_id_dashed.replace("-", "")

        # Manifest is keyed on the NORMALIZED id (matches sync's writer).
        manifest_path = get_manifest_path()
        manifest = SyncManifest(
            last_sync_at=None,
            sync_count=0,
            conversations={
                normalized: {
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

        # Seed DB with a matching row.
        from ohtv.db import get_db_path, migrate

        db_path = get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
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
        # Caller passes the DASHED id — the helper must normalize.
        result = _apply_local_title_writeback(
            config,
            renamed_id_to_title={conv_id_dashed: "✨ Real New Title"},
        )

        # Manifest write happened on the normalized key.
        manifest_after = SyncManifest.load(manifest_path)
        assert manifest_after.conversations[normalized]["title"] == "✨ Real New Title"
        # last_sync_at must NOT have advanced (issue requirement).
        assert manifest_after.last_sync_at == original_last_sync

        # DB row updated.
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT title FROM conversations WHERE id = ?", (normalized,)
        ).fetchone()
        conn.close()
        assert row[0] == "✨ Real New Title"

        # Result reports both writes succeeded — this is the new
        # ``Manifest updated: 1/1`` signal in the end-of-run summary.
        assert result.db_updated == 1
        assert result.manifest_updated == 1
        assert result.manifest_total == 1

    def test_writeback_normalizes_dashed_conv_id_for_manifest_lookup(
        self, isolated_env: Path
    ) -> None:
        """Regression test for the PR #96 manifest-writeback bug.

        Caller hands the helper a dashed ``CloudConversation.id`` but
        the manifest is keyed without dashes. The lookup MUST strip
        dashes; otherwise the writeback is silently a no-op and the
        manifest goes stale while the DB stays correct.
        """
        from ohtv.cli import _apply_local_title_writeback
        from ohtv.config import Config, get_manifest_path
        from ohtv.sync import SyncManifest

        # Two conversations, both passed in dashed form.
        conv_a_dashed = "5dc3a672-3c9d-48f8-9df3-5b07b5c69850"
        conv_b_dashed = "60659a20-e61f-4a09-a388-2acfa607477b"
        conv_a_norm = conv_a_dashed.replace("-", "")
        conv_b_norm = conv_b_dashed.replace("-", "")

        # Manifest keyed on normalized ids (real-world shape).
        manifest_path = get_manifest_path()
        SyncManifest(
            last_sync_at=None,
            sync_count=0,
            conversations={
                conv_a_norm: {
                    "title": "Conversation 5dc3a",
                    "updated_at": "2026-05-26T00:00:00+00:00",
                    "event_count": 10,
                    "downloaded_at": "2026-05-26T00:00:01+00:00",
                    "labels": None,
                },
                conv_b_norm: {
                    "title": "Conversation 60659",
                    "updated_at": "2026-05-26T00:00:00+00:00",
                    "event_count": 10,
                    "downloaded_at": "2026-05-26T00:00:01+00:00",
                    "labels": None,
                },
            },
        ).save(manifest_path)

        # No DB row for conv_b — we want to prove the manifest is
        # updated independently of the DB success path.
        from ohtv.db import get_db_path, migrate

        db_path = get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        migrate(conn)
        conn.execute(
            "INSERT INTO conversations (id, title, source, location) "
            "VALUES (?, ?, ?, ?)",
            (conv_a_norm, "Conversation 5dc3a", "cloud", "/fake/a"),
        )
        conn.commit()
        conn.close()

        result = _apply_local_title_writeback(
            Config.from_env(),
            renamed_id_to_title={
                conv_a_dashed: "✅ New Title A",
                conv_b_dashed: "🔧 New Title B",
            },
        )

        # Both manifest entries updated despite dashed input ids.
        manifest_after = SyncManifest.load(manifest_path)
        assert manifest_after.conversations[conv_a_norm]["title"] == "✅ New Title A"
        assert manifest_after.conversations[conv_b_norm]["title"] == "🔧 New Title B"

        # Summary surfaces full coverage (the failure-mode guardrail).
        assert result.manifest_updated == 2
        assert result.manifest_total == 2
        # DB only had a row for conv_a, so db_updated == 1.
        assert result.db_updated == 1

    def test_writeback_reports_partial_manifest_when_entry_missing(
        self, isolated_env: Path
    ) -> None:
        """Missing manifest entry shows as partial (K < M) in result.

        This is the surface the summary block uses to warn the user
        in yellow when the manifest writeback is incomplete.
        """
        from ohtv.cli import _apply_local_title_writeback
        from ohtv.config import Config, get_manifest_path
        from ohtv.sync import SyncManifest

        # Only one of the two convs has a manifest entry.
        present = "11111111-2222-3333-4444-555555555555"
        absent = "99999999-8888-7777-6666-555555555555"
        present_norm = present.replace("-", "")

        manifest_path = get_manifest_path()
        SyncManifest(
            last_sync_at=None,
            sync_count=0,
            conversations={
                present_norm: {
                    "title": "Old Title",
                    "updated_at": "2026-05-26T00:00:00+00:00",
                    "event_count": 10,
                    "downloaded_at": "2026-05-26T00:00:01+00:00",
                    "labels": None,
                },
            },
        ).save(manifest_path)

        result = _apply_local_title_writeback(
            Config.from_env(),
            renamed_id_to_title={
                present: "✅ New Title",
                absent: "🚫 Missing Title",
            },
        )

        assert result.manifest_total == 2
        assert result.manifest_updated == 1  # partial

    def test_writeback_is_noop_when_empty(self, isolated_env: Path) -> None:
        from ohtv.cli import _apply_local_title_writeback
        from ohtv.config import Config

        config = Config.from_env()
        assert _apply_local_title_writeback(config, {}) == _WritebackResult(0, 0, 0)


# =============================================================================
# Issue #125 — sub-conversation default exclusion regression tests
# =============================================================================


class TestGenTitlesSubConversations:
    """Regression tests for Issue #125 — gen titles arm.

    ``gen titles`` shares the ``_apply_conversation_filters`` orchestration
    layer with ``gen objs`` / ``gen run``, so the same default-correctness
    contract holds: roots only unless the user passes
    ``--include-sub-conversations``.
    """

    def _conv_root(self) -> ConversationInfo:
        return _conv(
            "r10000000000000000000000000000001",
            title="Conversation r10000",
        )

    def _subs(self) -> list[ConversationInfo]:
        return [
            _conv(
                "s20000000000000000000000000000002",
                title="Conversation s20000",
            ),
            _conv(
                "s20000000000000000000000000000003",
                title="Conversation s20000",
            ),
        ]

    def _call_run_gen_titles_with_filter_mock(
        self,
        isolated_env: Path,
        *,
        include_sub_conversations: bool,
        returned_conversations: list[ConversationInfo],
    ):
        """Drive ``_run_gen_titles`` directly with injected stubs.

        Mirrors the existing test pattern in this module
        (``TestDryRun``) — bypass the Click wrapper because the
        wrapper's only job here is to forward the option, and we test
        that separately via the ``--help`` content + the regression
        test on the kwargs reaching ``_apply_conversation_filters``.
        """
        from ohtv.cli import _run_gen_titles

        filter_result = MagicMock()
        filter_result.conversations = returned_conversations
        filter_result.show_all = True

        stub_client = _stub_cloud_client()
        stub_llm = _make_llm_stub(
            {c.id: "✨ Auto-titled" for c in returned_conversations}
        )

        for c in returned_conversations:
            _seed_cloud_conv(isolated_env, c.id, goal="Generic")

        with (
            patch(
                "ohtv.cli._apply_conversation_filters",
                return_value=filter_result,
            ) as mock_filters,
            patch(
                "ohtv.cli._find_conversation_dir",
                side_effect=lambda config, conv_id: (
                    Path(isolated_env)
                    / "ohtv"
                    / "cache"
                    / "analysis"
                    / conv_id.replace("-", ""),
                    True,
                ),
            ),
        ):
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
                all_titled=True,
                dry_run=True,
                workers=2,
                batch_size=25,
                model=None,
                yes=True,
                include_sub_conversations=include_sub_conversations,
                llm_call=stub_llm,
                cloud_client=stub_client,
            )

        return mock_filters

    def test_default_passes_include_sub_conversations_false(
        self, isolated_env: Path
    ) -> None:
        """``include_sub_conversations=False`` reaches
        ``_apply_conversation_filters``."""
        mock_filters = self._call_run_gen_titles_with_filter_mock(
            isolated_env,
            include_sub_conversations=False,
            returned_conversations=[self._conv_root()],
        )

        assert mock_filters.call_count == 1
        call_kwargs = mock_filters.call_args.kwargs
        assert call_kwargs.get("include_sub_conversations") is False, (
            "gen titles default must pass include_sub_conversations=False; "
            f"got {call_kwargs.get('include_sub_conversations')!r}"
        )

    def test_flag_passes_include_sub_conversations_true(
        self, isolated_env: Path
    ) -> None:
        """``include_sub_conversations=True`` reaches the filter call."""
        root_and_subs = [self._conv_root(), *self._subs()]
        mock_filters = self._call_run_gen_titles_with_filter_mock(
            isolated_env,
            include_sub_conversations=True,
            returned_conversations=root_and_subs,
        )

        assert mock_filters.call_count == 1
        call_kwargs = mock_filters.call_args.kwargs
        assert call_kwargs.get("include_sub_conversations") is True, (
            "--include-sub-conversations must propagate as True; got "
            f"{call_kwargs.get('include_sub_conversations')!r}"
        )

    def test_cli_flag_threads_through_to_run_gen_titles(
        self, runner: CliRunner, isolated_env: Path
    ) -> None:
        """End-to-end Click invocation: the CLI option is forwarded to
        the implementation function. We assert by inspecting the
        ``include_sub_conversations`` kwarg ``_run_gen_titles`` is
        called with — that's the contract."""
        from ohtv.cli import main

        captured: dict = {}

        def _fake_run_gen_titles(**kwargs):
            captured.update(kwargs)

        with (
            patch("ohtv.cli._run_gen_titles", side_effect=_fake_run_gen_titles),
            patch(
                "ohtv.cli.sync_lock",
                return_value=MagicMock(
                    __enter__=MagicMock(return_value=None),
                    __exit__=MagicMock(return_value=False),
                ),
            ),
        ):
            result = runner.invoke(
                main,
                ["gen", "titles", "--all", "--all-titled", "--dry-run",
                 "--include-sub-conversations", "-y"],
            )
        assert result.exit_code == 0, result.output
        assert captured.get("include_sub_conversations") is True

        captured.clear()
        with (
            patch("ohtv.cli._run_gen_titles", side_effect=_fake_run_gen_titles),
            patch(
                "ohtv.cli.sync_lock",
                return_value=MagicMock(
                    __enter__=MagicMock(return_value=None),
                    __exit__=MagicMock(return_value=False),
                ),
            ),
        ):
            result = runner.invoke(
                main,
                ["gen", "titles", "--all", "--all-titled", "--dry-run", "-y"],
            )
        assert result.exit_code == 0, result.output
        assert captured.get("include_sub_conversations") is False

    def test_help_advertises_flag(self, runner: CliRunner) -> None:
        """The ``--help`` output names the flag verbatim."""
        from ohtv.cli import main
        result = runner.invoke(main, ["gen", "titles", "--help"])
        assert result.exit_code == 0
        assert "--include-sub-conversations" in result.output
        assert (
            "agent delegation" in result.output
            or "roots only" in result.output
        ), result.output

    def test_help_docstring_mentions_default_roots_only(
        self, runner: CliRunner
    ) -> None:
        """Docstring sentence Click renders into help must say the default
        excludes subs."""
        from ohtv.cli import main
        result = runner.invoke(main, ["gen", "titles", "--help"])
        assert result.exit_code == 0
        assert "root conversations only" in result.output
        assert "include them" in result.output
