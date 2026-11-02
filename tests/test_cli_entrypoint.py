"""The `python -m emporio` entry point must work before any epic implements a command."""

from __future__ import annotations

import pytest

from emporio.__main__ import build_parser, main


def test_help_lists_the_planned_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for command in ("build-data", "chat", "tool", "eval"):
        assert command in out


def test_no_command_prints_help_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: emporio" in capsys.readouterr().out


def test_unknown_command_is_rejected() -> None:
    """Every declared command is wired up now, so there is no placeholder left to test.

    The earlier version of this test named a command that had not been built yet. Twice, the
    epic that built it turned this into a test that really ran the thing — the second time it
    fired all nineteen live evaluation scenarios. A test must never depend on a command
    staying unimplemented.
    """
    with pytest.raises(SystemExit) as exc:
        main(["teleport"])
    assert exc.value.code == 2  # argparse's "invalid choice"


def test_every_declared_command_is_wired_up() -> None:
    """Guards the AssertionError branch in main(): declaring a command is not enough."""
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    )
    assert set(subparsers.choices) == {"build-data", "chat", "tool", "eval", "sessions"}
