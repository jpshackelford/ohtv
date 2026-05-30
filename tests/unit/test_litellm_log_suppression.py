"""Regression tests for Issue #148: LiteLLM botocore warning suppression.

`import ohtv` must set ``LITELLM_LOG=ERROR`` via ``os.environ.setdefault``
before any submodule triggers a transitive ``import litellm``. We test this
in a subprocess because by the time the pytest test process gets here,
sibling tests have almost certainly already imported ``litellm`` (and thus
also imported ``litellm._logging``, which reads ``LITELLM_LOG`` once at
module init). A subprocess gives us a fresh interpreter where neither
``ohtv`` nor ``litellm`` has been imported yet.
"""

from __future__ import annotations

import os
import subprocess
import sys


def _child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a minimal env that still lets the child find the project's ohtv.

    We forward PATH (so the system Python can find its stdlib loaders),
    VIRTUAL_ENV (so `sys.executable` in a uv-managed venv resolves correctly),
    and PYTHONPATH (so editable installs resolve). We deliberately do NOT
    forward LITELLM_LOG unless the caller explicitly asks for it.
    """
    env: dict[str, str] = {}
    for key in ("PATH", "VIRTUAL_ENV", "PYTHONPATH", "HOME"):
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    if extra:
        env.update(extra)
    return env


def test_ohtv_sets_litellm_log_to_error_when_unset() -> None:
    """`import ohtv` sets LITELLM_LOG=ERROR when the env var was unset."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; import ohtv; print(os.environ['LITELLM_LOG'])",
        ],
        env=_child_env(),  # no LITELLM_LOG forwarded
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "ERROR", (
        f"expected ERROR, got stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_ohtv_preserves_litellm_log_when_set() -> None:
    """`import ohtv` leaves a user-provided LITELLM_LOG untouched (setdefault contract)."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; import ohtv; print(os.environ['LITELLM_LOG'])",
        ],
        env=_child_env({"LITELLM_LOG": "DEBUG"}),
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "DEBUG", (
        f"expected DEBUG (preserved), got stdout={result.stdout!r} stderr={result.stderr!r}"
    )
