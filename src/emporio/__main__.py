"""Command line entry point: python -m emporio <command>.

Subcommands are added by later epics (build-data in E1, tool in E3, chat in E5, eval in E6).
Each one is imported lazily so that `--help` works before those modules exist.
"""

from __future__ import annotations

import argparse
import sys
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

    chat = sub.add_parser("chat", help="Interactive chat with the agent (E5)")
    chat.add_argument("--session", help="Resume an existing session id")

    tool = sub.add_parser("tool", help="Call a tool directly, for debugging (E3)")
    tool.add_argument("name", help="Tool name, e.g. search_products")
    tool.add_argument("arguments", nargs="?", default="{}", help="JSON object with the arguments")

    sub.add_parser("eval", help="Run the behavioural scenario evaluation (E6)")

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

    # Placeholder until the owning epic lands; keeps `--help` and CI working meanwhile.
    print(f"'{args.command}' is not implemented yet.", file=sys.stderr)
    return 1


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


def _call_tool(name: str, raw_arguments: str) -> int:
    """Run one tool straight from the shell, exactly as the agent loop would see it."""
    import json

    from emporio.tools import dispatch

    result = dispatch(name, raw_arguments, session_id="cli-debug")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
