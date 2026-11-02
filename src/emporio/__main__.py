"""Command line entry point: python -m emporio <command>.

Each subcommand imports its module lazily, so `--help` and `--version` work even when the
database has not been built or no API key is set.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from emporio import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="emporio",
        description="Customer service agent for Empório da Música.",
    )
    parser.add_argument("--version", action="version", version=f"emporio {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("build-data", help="Build data/processed/emporio.db from data/raw (E1)")

    chat = sub.add_parser("chat", help="Interactive chat with the agent")
    chat.add_argument("--session", help="Resume an existing session id")
    chat.add_argument(
        "--debug", action="store_true", help="Start with tool calls visible (toggle with /debug)"
    )

    sub.add_parser("sessions", help="List recent chat sessions")

    tool = sub.add_parser("tool", help="Call a tool directly, for debugging (E3)")
    tool.add_argument("name", help="Tool name, e.g. search_products")
    tool.add_argument("arguments", nargs="?", default="{}", help="JSON object with the arguments")

    evaluation = sub.add_parser("eval", help="Run the behavioural scenario evaluation")
    evaluation.add_argument(
        "--only", nargs="*", metavar="ID", help="Run only these scenarios, e.g. --only S01 S07"
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "build-data":
        return _build_data()

    if args.command == "tool":
        return _call_tool(args.name, args.arguments)

    if args.command == "chat":
        from emporio.cli import run

        return run(session_id=args.session, debug=args.debug)

    if args.command == "sessions":
        return _list_sessions()

    if args.command == "eval":
        from emporio.eval import main as run_eval

        return run_eval(only=args.only)

    raise AssertionError(f"command {args.command!r} is declared but not wired up")


def _build_data() -> int:
    from emporio.data_loader import build
    from emporio.policies import dump_raw_text

    result = build()
    total = sum(result.row_counts.values())
    print(f"Built {result.db_path} ({total} rows)")
    for table, count in result.row_counts.items():
        print(f"  {table:<13} {count:>4}")
    print(f"Found {len(result.issues)} data quality issues -> {result.report_path}")

    # The curated policies.md is committed; this dump only exists so it can be diffed
    # against the PDF (DECISIONS D5).
    print(f"Refreshed the raw policy extraction -> {dump_raw_text()}")
    return 0


def _list_sessions() -> int:
    from emporio.memory import list_sessions

    rows = list_sessions()
    if not rows:
        print("No sessions yet. Start one with: python -m emporio chat")
        return 0
    print(f"{'session':<14} {'messages':>8}  last message")
    for row in rows:
        print(f"{row['session_id']:<14} {row['messages']:>8}  {row['last_at']}")
    return 0


def _call_tool(name: str, raw_arguments: str) -> int:
    """Run one tool straight from the shell, exactly as the agent loop would see it."""
    import json

    from emporio.tools import dispatch

    result = dispatch(name, raw_arguments, session_id="cli-debug")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
