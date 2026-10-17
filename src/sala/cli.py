"""sala command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import SalaError, execute, initialize, read_state
from .planner import plan_with_llm


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sala", description="sala: a small, conservative media-agent development slice")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Initialize a local project and reference an input video")
    init.add_argument("--project", type=Path, required=True)
    init.add_argument("--source", type=Path, required=True)
    run = commands.add_parser("run", help="Interpret one bounded media instruction")
    run.add_argument("--project", type=Path, required=True)
    run.add_argument("--dry-run", action="store_true", help="Show plan without making an output")
    run.add_argument("--planner", choices=("rules", "llm"), default="rules",
                     help="Optional OpenAI-compatible LLM planning with SALA_LLM_* env vars")
    run.add_argument("instruction", help="Example: 截取 1 到 3 秒片段")
    status = commands.add_parser("status", help="Show active media and project history")
    status.add_argument("--project", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            result = initialize(args.project.resolve(), args.source)
        elif args.command == "status":
            result = read_state(args.project.resolve())
        else:
            result = execute(args.project.resolve(), args.instruction, dry_run=args.dry_run,
                             planner=plan_with_llm if args.planner == "llm" else None)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (SalaError, FileNotFoundError) as exc:
        print(f"sala: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
