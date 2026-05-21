"""Pin the invariant: every stage in the STAGES registry must be a valid
``ohtv db process <stage>`` choice.

This guards against the click ``Choice`` allowlist drifting from the
``STAGES`` registry (which is what caused the ``human_input`` regression
discovered during manual testing of PR #85).
"""

from click.testing import CliRunner

from ohtv.cli import main
from ohtv.db.stages import STAGES


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
