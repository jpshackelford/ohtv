"""In-process Click runner for the ``ohtv ask --agent`` investigator.

Issue #161 introduces a prompt-cookbook investigator that invokes the
``ohtv`` CLI directly instead of going through a curated set of custom
tool definitions. To avoid the ~2s ``litellm`` import tax on every
subprocess fork, this module wraps ``click.testing.CliRunner`` to invoke
``ohtv`` commands in-process.

Public surface:

* :data:`ALLOWED_SUBCOMMANDS` — argv-prefix allow-list (e.g. ``("show",)``,
  ``("gen", "objs")``).
* :data:`BLOCKED_SUBCOMMANDS` — argv-prefix block-list for write-side
  commands. Informational; the allow-list is authoritative.
* :class:`CliOutput` — captured invocation result.
* :func:`run_ohtv` — the runner.
* :func:`extract_conversation_ids_from_argv` — argv → set of conv IDs
  (the agent's ``conversations_examined`` is populated from this so
  both modes report the same field shape per #161's "identical
  ``InvestigationResult`` shape" contract).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from click.testing import CliRunner

log = logging.getLogger("ohtv")

DEFAULT_TIMEOUT_S: float = 30.0

# Allow-list (argv prefixes). ``ohtv list`` is allowed even though it
# overlaps with the cookbook's ``gen objs --cache-only`` pattern — the
# duplication is intentional per #161's "Technical Considerations".
ALLOWED_SUBCOMMANDS: tuple[tuple[str, ...], ...] = (
    ("show",),
    ("refs",),
    ("search",),
    ("list",),
    ("errors",),
    ("gen", "objs"),
)

# Block-list for write-side commands. Surfaced in rejection messages so
# the agent learns *why* its argv was rejected without having to retry
# blindly. Not authoritative — anything not on the allow-list is rejected.
BLOCKED_SUBCOMMANDS: tuple[tuple[str, ...], ...] = (
    ("sync",),
    ("db", "scan"),
    ("db", "process"),
    ("db", "embed"),
    ("db", "migrate-cache"),
    ("db", "reset"),
    ("fetch-loc",),
    ("gen", "titles"),
    ("gen", "run"),
    ("classify",),
    ("config",),
)

# Matches conversation IDs that the agent might pass in argv.
# - 8-char short form: ``a711cbbc``
# - 32-char dashless form: ``a711cbbc61f04dbf9b8e5a7e8b59f8d8``
# - 36-char UUID with dashes: ``a711cbbc-61f0-4dbf-9b8e-5a7e8b59f8d8``
# We deliberately ignore SHA-style hex (40 chars) and short hex inside
# longer alphanumerics by requiring a word boundary.
_CONV_ID_RE = re.compile(
    r"\b("
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # 36-char dashed UUID
    r"|[0-9a-f]{32}"  # 32-char dashless
    r"|[0-9a-f]{8}"  # 8-char short form
    r")\b"
)


@dataclass
class CliOutput:
    """Captured result of an in-process ``ohtv`` invocation.

    Attributes:
        argv: The argv that was attempted (after any runner injections).
        stdout: Captured standard output.
        stderr: Captured standard error (separate channel; CliRunner is
            invoked with ``mix_stderr=False`` so the agent can distinguish
            content from progress chatter).
        exit_code: Click exit code (0 on success).
        elapsed_seconds: Wall-clock time including any setup.
        rejected: True if the runner refused the command (allow-list miss
            or per-investigation cap). In that case ``stdout`` is empty
            and ``stderr`` holds the rejection observation.
        rejection_reason: Short string explaining the rejection (e.g.
            ``"not_in_allow_list"``, ``"command_cap_exceeded"``,
            ``"timeout"``). ``None`` when ``rejected`` is False.
    """

    argv: list[str]
    stdout: str
    stderr: str
    exit_code: int
    elapsed_seconds: float
    rejected: bool = False
    rejection_reason: str | None = None

    def to_observation(self) -> str:
        """Render this output as the observation string handed to the LLM.

        Includes the argv, an exit-code header, and stdout/stderr. Truncates
        stdout to ~4000 chars to match the legacy investigator's tool-output
        cap, leaving headroom inside typical 8K context windows.
        """
        lines: list[str] = []
        argv_str = " ".join(self.argv)
        if self.rejected:
            lines.append(f"REJECTED: ohtv {argv_str}")
            lines.append(f"reason: {self.rejection_reason}")
            if self.stderr:
                lines.append("")
                lines.append(self.stderr)
            return "\n".join(lines)

        lines.append(f"$ ohtv {argv_str}")
        lines.append(f"exit_code: {self.exit_code}")
        lines.append(f"elapsed: {self.elapsed_seconds:.2f}s")
        if self.stdout:
            body = self.stdout
            if len(body) > 4000:
                body = body[:4000] + "\n... [stdout truncated]"
            lines.append("")
            lines.append(body)
        if self.stderr:
            lines.append("")
            lines.append("--- stderr ---")
            err = self.stderr
            if len(err) > 1000:
                err = err[:1000] + "\n... [stderr truncated]"
            lines.append(err)
        return "\n".join(lines)


def _is_prefix(prefix: tuple[str, ...], argv: list[str]) -> bool:
    """Return True iff ``argv`` begins with the tuple ``prefix``."""
    return len(argv) >= len(prefix) and tuple(argv[: len(prefix)]) == prefix


def _check_allow_list(argv: list[str]) -> tuple[str, ...] | None:
    """Return the matched allow-list prefix, or None if no match."""
    if not argv:
        return None
    for prefix in ALLOWED_SUBCOMMANDS:
        if _is_prefix(prefix, argv):
            return prefix
    return None


def _check_block_list(argv: list[str]) -> tuple[str, ...] | None:
    """Return the matched block-list prefix, or None."""
    if not argv:
        return None
    for prefix in BLOCKED_SUBCOMMANDS:
        if _is_prefix(prefix, argv):
            return prefix
    return None


def _format_allow_list() -> str:
    """Pretty-print the allow-list for the rejection observation."""
    return ", ".join(" ".join(p) for p in ALLOWED_SUBCOMMANDS)


def _inject_gen_objs_cache_only(argv: list[str]) -> list[str]:
    """Inject ``--cache-only`` into ``gen objs`` argv if not already present.

    Per Issue #161 Open Question #1 (option (a) — resolved): the agent
    must not be able to trigger fresh LLM analyses through ``gen objs``.
    The runner injects ``--cache-only`` so the agent always reads cached
    summaries; cache misses surface as ``goal: null`` in the JSON.

    Re-injection is idempotent: if the agent already supplied
    ``--cache-only``, the argv is returned unchanged.
    """
    if not _is_prefix(("gen", "objs"), argv):
        return argv
    if "--cache-only" in argv:
        return argv
    # Insert the flag immediately after the subcommand prefix so it
    # behaves like Click's own positional handling expects.
    out = list(argv[:2]) + ["--cache-only"] + list(argv[2:])
    return out


def extract_conversation_ids_from_argv(argv: list[str]) -> set[str]:
    """Parse 8-char / 32-char / 36-char conversation IDs out of an argv.

    Used by :class:`InvestigationAgentCli` to populate
    ``InvestigationResult.conversations_examined`` with the same field
    shape the legacy tools-mode agent fills in via its
    ``ShowConversationTool`` / ``GetRefsTool`` observation hooks.

    IDs are normalised to the canonical 32-char dashless form to match
    Issue #14's database convention.
    """
    found: set[str] = set()
    for arg in argv:
        for match in _CONV_ID_RE.findall(arg):
            # Strip dashes so 36-char UUIDs collapse to 32-char IDs.
            normalised = match.replace("-", "")
            found.add(normalised)
    return found


def run_ohtv(
    argv: list[str],
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    cli_obj=None,
) -> CliOutput:
    """Invoke ``ohtv`` in-process via :class:`click.testing.CliRunner`.

    Args:
        argv: The argv list, *excluding* the ``ohtv`` program name.
            E.g. ``["show", "abc123", "-F", "json"]``.
        timeout_s: Soft per-call timeout (logged but not enforced).
            Click's :class:`~click.testing.CliRunner` does not support
            interrupting a running invocation, so this value is checked
            *after* the call completes — i.e. it can detect "this took
            too long" but cannot abort an in-flight subcommand. A hard
            timeout would require running the invocation on a worker
            thread (and even then, Python code paths that don't yield
            could not be interrupted), which is deliberately avoided
            for v1 to keep the runner simple and dependency-free.
            Runaway behaviour is bounded by the session-level
            iteration cap enforced upstream in
            :class:`~ohtv.analysis.investigator_cli.InvestigationAgentCli`.
        cli_obj: Optional Click command/group to invoke. Defaults to
            the :func:`ohtv.cli.main` group. Provided as a parameter so
            tests can pass a small isolated group.

    Returns:
        :class:`CliOutput` capturing stdout, stderr, exit code, and
        elapsed time. Rejection (allow-list miss) is non-throwing —
        the caller hands the rejection observation back to the LLM
        and lets it self-correct in one turn.
    """
    if cli_obj is None:
        # Late import to avoid a module-load cycle. ``cli.py`` imports
        # heavy machinery (RAG, db, etc.) that we don't need until
        # we're actually about to invoke something.
        from ohtv.cli import main as cli_obj  # noqa: WPS433

    matched = _check_allow_list(argv)
    if matched is None:
        attempted = argv[0] if argv else "(empty)"
        blocked = _check_block_list(argv)
        reason = "blocked_command" if blocked else "not_in_allow_list"
        if blocked:
            stderr = (
                f"The command '{' '.join(blocked)}' is on the block-list (it has "
                "write-side effects or is otherwise not safe for the agent runner). "
                f"Try one of: {_format_allow_list()}."
            )
        else:
            stderr = (
                f"The argv prefix '{attempted}' is not on the allow-list. "
                f"Allowed: {_format_allow_list()}."
            )
        return CliOutput(
            argv=list(argv),
            stdout="",
            stderr=stderr,
            exit_code=2,
            elapsed_seconds=0.0,
            rejected=True,
            rejection_reason=reason,
        )

    effective_argv = _inject_gen_objs_cache_only(list(argv))

    # Click 8.3 splits stdout and stderr by default — no ``mix_stderr``
    # parameter on CliRunner. We rely on ``result.stdout`` / ``result.stderr``
    # being independently populated.
    runner = CliRunner()
    start = time.perf_counter()
    # ``catch_exceptions=False`` would re-raise inside the test; we
    # want CliRunner to swallow Click-side exceptions and surface them
    # via the result.exit_code + result.exception fields instead.
    result = runner.invoke(cli_obj, effective_argv, catch_exceptions=True)
    elapsed = time.perf_counter() - start

    # Hard-soft timeout enforcement: log a warning but don't fail.
    # The session-level cap handles runaway behaviour upstream.
    if elapsed > timeout_s:
        log.warning(
            "run_ohtv argv=%s exceeded timeout (%.2fs > %.2fs)",
            effective_argv,
            elapsed,
            timeout_s,
        )

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        # Surface the exception as stderr so the agent can see it.
        stderr = f"{stderr}\n[exception] {type(result.exception).__name__}: {result.exception}".strip()

    return CliOutput(
        argv=effective_argv,
        stdout=stdout,
        stderr=stderr,
        exit_code=result.exit_code,
        elapsed_seconds=elapsed,
        rejected=False,
        rejection_reason=None,
    )
