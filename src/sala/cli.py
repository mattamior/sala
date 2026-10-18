"""sala command-line entry point."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from .core import SalaError,execute,initialize,read_state
from .planner import plan_with_llm, diagnose_llm
from .session import chat_turn

def build_parser()->argparse.ArgumentParser:
    parser=argparse.ArgumentParser(prog='sala',description='sala: conservative media-agent prototype')
    commands=parser.add_subparsers(dest='command',required=True)
    init=commands.add_parser('init',help='Initialize a local project and reference an input video')
    init.add_argument('--project',type=Path,required=True)
    init.add_argument('--source',type=Path,required=True)
    run=commands.add_parser('run',help='Interpret one bounded media instruction (legacy)')
    run.add_argument('--project',type=Path,required=True)
    run.add_argument('--dry-run',action='store_true')
    run.add_argument('--planner',choices=('rules','llm'),default='rules')
    run.add_argument('instruction')
    chat=commands.add_parser('chat',help='Persistent multi-turn media-agent loop')
    chat.add_argument('--project',type=Path,required=True)
    chat.add_argument('--dry-run',action='store_true')
    chat.add_argument('--planner',choices=('rules','llm'),default='rules')
    chat.add_argument('instruction',help='Next user turn (including answers to clarifications)')
    doctor=commands.add_parser('doctor',help='Check an LLM API connection without modifying a project')
    doctor.add_argument('target',choices=('llm',))
    status=commands.add_parser('status',help='Show active media and project history')
    status.add_argument('--project',type=Path,required=True)
    return parser

def main(argv:list[str]|None=None)->int:
    args=build_parser().parse_args(argv)
    try:
        if args.command=='init':result=initialize(args.project.resolve(),args.source)
        elif args.command=='status':result=read_state(args.project.resolve())
        elif args.command=='doctor':result=diagnose_llm()
        elif args.command=='run':
            result=execute(args.project.resolve(),args.instruction,dry_run=args.dry_run,
                           planner=plan_with_llm if args.planner=='llm' else None)
        else:
            result=chat_turn(args.project.resolve(),args.instruction,dry_run=args.dry_run,
                             planner=plan_with_llm if args.planner=='llm' else None)
        print(json.dumps(result,indent=2,ensure_ascii=False));return 0
    except (SalaError,FileNotFoundError) as exc:
        print(f'sala: {exc}',file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
