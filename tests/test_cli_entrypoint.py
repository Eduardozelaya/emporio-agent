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


def test_unimplemented_command_fails_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    """`eval` lands in E6. Never point this at an implemented command: it would really run."""
    assert main(["eval"]) == 1
    assert "not implemented yet" in capsys.readouterr().err
