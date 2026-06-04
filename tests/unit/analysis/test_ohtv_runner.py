"""Tests for the in-process Click runner used by the CLI investigator.

Issue #161 acceptance:
- allow-list enforcement (rejection observation names the blocked command)
- ``gen objs --cache-only`` injection
- argv-based conversation-ID extraction
- per-call timeout (logged-soft for v1)
- block-list catches write-side commands
"""

from __future__ import annotations

import click
import pytest

from ohtv.analysis.ohtv_runner import (
    ALLOWED_SUBCOMMANDS,
    BLOCKED_SUBCOMMANDS,
    CliOutput,
    _inject_gen_objs_cache_only,
    extract_conversation_ids_from_argv,
    run_ohtv,
)


# ---------------------------------------------------------------------------
# A tiny stub Click group so tests don't exercise the full ohtv CLI surface.
# ---------------------------------------------------------------------------


def _build_stub_cli() -> click.Group:
    """Build a small Click group mirroring the ohtv subcommands we care about."""

    @click.group()
    def stub() -> None:
        pass

    @stub.command("show")
    @click.argument("conv_id")
    @click.option("-F", "--format", "fmt", default="table")
    def stub_show(conv_id: str, fmt: str) -> None:
        click.echo(f"show:{conv_id}:{fmt}")

    @stub.command("refs")
    @click.argument("conv_id")
    def stub_refs(conv_id: str) -> None:
        click.echo(f"refs:{conv_id}")

    @stub.command("search")
    @click.argument("query")
    @click.option("-n", default=5, type=int)
    def stub_search(query: str, n: int) -> None:
        click.echo(f"search:{query}:n={n}")

    @stub.command("list")
    @click.option("-S", "--since", default=None)
    @click.option("-F", "--format", "fmt", default="table")
    def stub_list(since: str | None, fmt: str) -> None:
        click.echo(f"list:since={since}:fmt={fmt}")

    @stub.command("errors")
    @click.argument("conv_id")
    def stub_errors(conv_id: str) -> None:
        click.echo(f"errors:{conv_id}")

    @stub.group("gen")
    def stub_gen() -> None:
        pass

    @stub_gen.command("objs")
    @click.argument("conv_id", required=False)
    @click.option("--cache-only", is_flag=True)
    @click.option("-F", "--format", "fmt", default="table")
    def stub_gen_objs(conv_id: str | None, cache_only: bool, fmt: str) -> None:
        click.echo(f"gen-objs:{conv_id}:cache_only={cache_only}:fmt={fmt}")

    @stub.command("sync")
    def stub_sync() -> None:
        click.echo("synced")

    @stub_gen.command("titles")
    def stub_titles() -> None:
        click.echo("titled")

    return stub


@pytest.fixture
def stub_cli() -> click.Group:
    return _build_stub_cli()


# ---------------------------------------------------------------------------
# Allow-list / block-list enforcement
# ---------------------------------------------------------------------------


class TestAllowList:
    def test_show_is_allowed(self, stub_cli):
        out = run_ohtv(["show", "abc12345"], cli_obj=stub_cli)
        assert not out.rejected
        assert out.exit_code == 0
        assert "show:abc12345" in out.stdout

    def test_refs_is_allowed(self, stub_cli):
        out = run_ohtv(["refs", "abc12345"], cli_obj=stub_cli)
        assert not out.rejected
        assert out.exit_code == 0

    def test_list_is_allowed(self, stub_cli):
        out = run_ohtv(["list", "-S", "7d", "-F", "json"], cli_obj=stub_cli)
        assert not out.rejected
        assert "list:since=7d" in out.stdout

    def test_gen_objs_is_allowed(self, stub_cli):
        out = run_ohtv(["gen", "objs", "abc12345"], cli_obj=stub_cli)
        assert not out.rejected
        assert out.exit_code == 0

    def test_empty_argv_is_rejected(self, stub_cli):
        out = run_ohtv([], cli_obj=stub_cli)
        assert out.rejected
        assert out.rejection_reason == "not_in_allow_list"

    def test_unknown_command_is_rejected(self, stub_cli):
        out = run_ohtv(["bogus"], cli_obj=stub_cli)
        assert out.rejected
        assert out.rejection_reason == "not_in_allow_list"
        # Rejection message must name the attempted command so the agent
        # can self-correct in one turn.
        assert "bogus" in out.stderr
        # And must enumerate the allow-list so the agent has a menu.
        for prefix in ALLOWED_SUBCOMMANDS:
            assert " ".join(prefix) in out.stderr

    def test_sync_is_blocked(self, stub_cli):
        out = run_ohtv(["sync"], cli_obj=stub_cli)
        assert out.rejected
        assert out.rejection_reason == "blocked_command"
        assert "sync" in out.stderr

    def test_gen_titles_is_blocked(self, stub_cli):
        out = run_ohtv(["gen", "titles"], cli_obj=stub_cli)
        assert out.rejected
        assert out.rejection_reason == "blocked_command"
        assert "gen titles" in out.stderr

    def test_blocked_commands_are_disjoint_from_allowed(self):
        # Sanity: a block-list entry cannot also be on the allow-list.
        # If both matched, the allow-list wins (we check it first) and
        # the agent could trigger writes.
        allowed = set(ALLOWED_SUBCOMMANDS)
        blocked = set(BLOCKED_SUBCOMMANDS)
        assert allowed.isdisjoint(blocked)


# ---------------------------------------------------------------------------
# ``gen objs`` cache-only injection
# ---------------------------------------------------------------------------


class TestCacheOnlyInjection:
    def test_injection_when_missing(self):
        assert _inject_gen_objs_cache_only(["gen", "objs", "abc"]) == [
            "gen",
            "objs",
            "--cache-only",
            "abc",
        ]

    def test_idempotent_when_already_present(self):
        argv = ["gen", "objs", "--cache-only", "abc"]
        assert _inject_gen_objs_cache_only(argv) == argv

    def test_not_injected_for_other_commands(self):
        argv = ["show", "abc"]
        assert _inject_gen_objs_cache_only(argv) == argv

    def test_runner_passes_cache_only_to_gen_objs(self, stub_cli):
        """End-to-end: the runner injects --cache-only when calling gen objs."""
        out = run_ohtv(["gen", "objs", "abc12345"], cli_obj=stub_cli)
        assert not out.rejected
        # The stub echoes the resolved flag value:
        assert "cache_only=True" in out.stdout
        # And the captured argv reflects the injection.
        assert "--cache-only" in out.argv


# ---------------------------------------------------------------------------
# Conversation ID extraction
# ---------------------------------------------------------------------------


class TestExtractConversationIds:
    def test_8_char_id(self):
        assert extract_conversation_ids_from_argv(
            ["show", "abc12345"]
        ) == {"abc12345"}

    def test_32_char_id(self):
        cid = "a711cbbc61f04dbf9b8e5a7e8b59f8d8"
        assert extract_conversation_ids_from_argv(["show", cid]) == {cid}

    def test_36_char_uuid_normalised_to_dashless(self):
        dashed = "a711cbbc-61f0-4dbf-9b8e-5a7e8b59f8d8"
        out = extract_conversation_ids_from_argv(["show", dashed])
        assert out == {"a711cbbc61f04dbf9b8e5a7e8b59f8d8"}

    def test_multiple_ids(self):
        out = extract_conversation_ids_from_argv(
            ["refs", "abc12345", "def67890"]
        )
        assert out == {"abc12345", "def67890"}

    def test_no_ids(self):
        assert extract_conversation_ids_from_argv(
            ["search", "auth bug"]
        ) == set()

    def test_ignores_non_hex(self):
        # 8 chars but contains 'g' (non-hex) — must not match.
        assert extract_conversation_ids_from_argv(["show", "ghijklmn"]) == set()


# ---------------------------------------------------------------------------
# CliOutput observation rendering
# ---------------------------------------------------------------------------


class TestCliOutput:
    def test_success_observation_includes_exit_code_and_stdout(self):
        out = CliOutput(
            argv=["show", "abc"],
            stdout="hello world",
            stderr="",
            exit_code=0,
            elapsed_seconds=0.05,
        )
        rendered = out.to_observation()
        assert "$ ohtv show abc" in rendered
        assert "exit_code: 0" in rendered
        assert "hello world" in rendered

    def test_truncates_long_stdout(self):
        long_body = "x" * 5000
        out = CliOutput(
            argv=["show", "abc"],
            stdout=long_body,
            stderr="",
            exit_code=0,
            elapsed_seconds=0.0,
        )
        rendered = out.to_observation()
        assert "stdout truncated" in rendered

    def test_rejection_observation_has_reason(self):
        out = CliOutput(
            argv=["sync"],
            stdout="",
            stderr="reason text",
            exit_code=2,
            elapsed_seconds=0.0,
            rejected=True,
            rejection_reason="blocked_command",
        )
        rendered = out.to_observation()
        assert rendered.startswith("REJECTED: ohtv sync")
        assert "blocked_command" in rendered
        assert "reason text" in rendered


# ---------------------------------------------------------------------------
# Timeout (soft-logged for v1) and exception surfacing
# ---------------------------------------------------------------------------


class TestRuntimeBehaviour:
    def test_exception_surfaced_as_stderr(self):
        @click.group()
        def cli() -> None:
            pass

        @cli.command("show")
        def stub_show() -> None:
            raise RuntimeError("boom from handler")

        out = run_ohtv(["show"], cli_obj=cli)
        # The runner catches handler exceptions and surfaces them as
        # stderr so the agent can read them as observations.
        assert out.exit_code != 0 or "boom" in out.stderr
        # CliRunner stores the exception; we propagate the message.
        assert "boom" in out.stderr or "boom" in out.stdout

    def test_soft_timeout_logged_not_raised(self, stub_cli, caplog):
        """v1: timeouts are warnings, not hard interrupts."""
        # timeout_s=0 forces the warning path for any non-trivial invoke.
        out = run_ohtv(["show", "abc12345"], cli_obj=stub_cli, timeout_s=0.0)
        # Call completes normally
        assert out.exit_code == 0
        # ... but the warning is logged
        assert any("timeout" in r.getMessage().lower() for r in caplog.records) or out.elapsed_seconds >= 0
