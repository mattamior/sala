"""M2.1: persistent, bounded conversational media-editing turns.

This is a deterministic orchestration layer, not an unrestricted AI agent.
It recognizes explicit source references and one missing-time clarification.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Callable

from .core import (
    Action, SalaError, _save_if_unchanged, enforce_preservation_boundary,
    parse_instruction, probe_video, read_state, render, validate_action,
)

Planner = Callable[[str, dict[str, Any]], Action]
_NUMBER = r"(\d+(?:\.\d+)?)"
# A deliberately small, anchored grammar prevents interpreting unsupported editing
# language as authorization for FFmpeg operations.
_CLIP = re.compile(
    rf"^\s*(?:请)?(?:把)?(?:视频)?(?:第)?\s*{_NUMBER}\s*(?:秒)?\s*(?:到|至|[-~～—])\s*"
    rf"{_NUMBER}\s*秒\s*(?:截取|剪出|裁剪)\s*(?:为|成)?\s*(?:视频|片段)?\s*[。.!！]?\s*$"
)
_CLIP_PREFIX = re.compile(
    rf"^\s*(?:请)?(?:截取|剪出|裁剪)\s*(?:视频)?\s*第?\s*{_NUMBER}\s*"
    rf"(?:秒)?\s*(?:到|至|[-~～—])\s*{_NUMBER}\s*秒\s*(?:片段)?\s*[。.!！]?\s*$"
)
_FRAME_FROM_CLIP = re.compile(
    rf"^\s*(?:请)?(?:把)?(?:刚才|上一次|之前)(?:的|那)?(?:段|个)?(?:视频|片段)?(?:的)?\s*"
    rf"第?\s*{_NUMBER}\s*秒(?:的)?\s*(?:画面|帧|截图)?\s*"
    rf"(?:导出|提取|截取|保存)(?:成|为)?\s*(?:图片|画面|帧|截图)?\s*[。.!！]?\s*$"
)
_FRAME_FROM_CLIP_REVERSED = re.compile(
    rf"^\s*(?:请)?(?:将|把)?(?:刚才|上一次|之前)(?:的|那)?(?:段|个)?(?:视频|片段)?(?:的)?\s*"
    rf"第?\s*{_NUMBER}\s*秒(?:的)?\s*(?:画面|帧|截图)?\s*(?:导出|提取|截取|保存)\s*"
    rf"(?:成|为)?\s*(?:图片|画面|帧|截图)\s*[。.!！]?\s*$"
)
# No silent interpretation of unsupported edits as normal trimming.
_MISSING_TIME = re.compile(
    r"^\s*(?:请)?(?:把)?(?:(?:刚才|上一次)(?:的|那)?(?:段|个)?(?:视频|片段)?(?:的)?)?\s*"
    r"(?:提取|导出|截取|保存)\s*(?:一张)?(?:画面|帧|截图|图片)\s*[。.!！]?\s*$"
)
_MISSING_TIME_ALT = re.compile(
    r"^\s*(?:请)?(?:把)?(?:刚才|上一次)(?:的|那)?(?:段|个)?(?:视频|片段)?(?:的)?\s*"
    r"(?:画面|帧|截图)\s*(?:导出|提取|保存)(?:成|为)?\s*(?:图片|截图)?\s*[。.!！]?\s*$"
)
_TIME_ONLY = re.compile(rf"^\s*第?\s*{_NUMBER}\s*秒\s*[。.!！]?\s*$")
_REFER_PAST = re.compile(r"(?:刚才|上一轮|上一次|之前)(?:的|那)?(?:段|个)?(?:视频|片段)")
_EDIT_TERMS = re.compile(r"(?:截取|剪出|裁剪|提取|导出|截图|画面|帧|trim|cut|extract|frame)", re.I)
_UNSUPPORTED_EDIT = re.compile(r"(?:转身|换脸|人物动作|重新生成|改背景|改运镜|改变风格|生成视频|retime|generate video|replace face)", re.I)
_EXTRA_PRESERVE = re.compile(r"(?:其他|其它|其余)(?:的)?(?:镜头|片段|画面).{0,12}(?:别动|不能动|不许动|不准改|维持原状)")


def _safe_action(action: Action, duration: float) -> None:
    """Check planner output independently, including NaN and unauthorized kinds."""
    if not isinstance(action, Action) or action.kind not in {"trim", "frame"}:
        raise SalaError("规划器返回未授权的媒体操作，未执行。")
    if isinstance(action.start, bool) or not isinstance(action.start, (int, float)) or not math.isfinite(action.start):
        raise SalaError("规划器返回无效时间，未执行。")
    if action.kind == "trim":
        if (isinstance(action.end, bool) or not isinstance(action.end, (int, float))
                or not math.isfinite(action.end) or action.end <= action.start):
            raise SalaError("规划器返回无效截取区间，未执行。")
    elif action.end is not None:
        raise SalaError("提帧操作包含额外的剪辑参数，未执行。")
    validate_action(action, duration)


def _last_clip(state: dict[str, Any]) -> str | None:
    """Only trust the latest generated clip if it is still the active video."""
    for entry in reversed(state.get("history", [])):
        if entry.get("operation") == "trim":
            path = entry.get("result")
            return path if isinstance(path, str) and path == state.get("active_media") else None
    return None


def _resolve(state: dict[str, Any], instruction: str,
             planner: Planner | None, duration: float) -> tuple[Action | None, str | None, dict[str, Any] | None]:
    """Resolve one turn into (action, question, pending)."""
    pending = state.get("pending")
    # A reply to an outstanding question may fill one missing time. It must
    # reference the same source asset as when the question was asked.
    if isinstance(pending, dict) and pending.get("kind") == "frame_time":
        answer = _TIME_ONLY.fullmatch(instruction)
        if answer:
            if state["active_media"] != pending.get("source"):
                return None, "正在编辑的视频已变更，请重新说明要提取哪段视频的哪一秒。", None
            return Action("frame", float(answer.group(1))), None, None

    # Existing exact rules continue working unchanged.
    try:
        return parse_instruction(instruction), None, None
    except SalaError:
        pass

    for pattern in (_CLIP, _CLIP_PREFIX):
        match = pattern.fullmatch(instruction)
        if match:
            start, end = map(float, match.groups())
            if start >= end:
                raise SalaError("截取时间必须满足开始时间小于结束时间。")
            return Action("trim", start, end), None, None

    for pattern in (_FRAME_FROM_CLIP_REVERSED, _FRAME_FROM_CLIP):
        match = pattern.fullmatch(instruction)
        if match:
            if not _last_clip(state):
                return None, "目前没有可引用的刚才截取片段，请先截取视频，或明确指定操作目标。", None
            return Action("frame", float(match.group(1))), None, None

    if _MISSING_TIME.fullmatch(instruction) or _MISSING_TIME_ALT.fullmatch(instruction):
        if _REFER_PAST.search(instruction) and not _last_clip(state):
            return None, "目前没有可引用的刚才截取片段；请先截取视频。", None
        return (None, "要提取视频的第几秒画面？例如回复「第 1 秒」。",
                {"kind": "frame_time", "source": state["active_media"], "original_instruction": instruction})

    # LLM may interpret alternate phrasing only for an explicitly named
    # allowlisted media action. A bare "再快一点" must never invent an action.
    if planner is not None and _EDIT_TERMS.search(instruction):
        history = [*state.get("history", [])]
        for turn in state.get("conversation", [])[-2:]:
            history.append({"instruction": turn.get("instruction", "")})
        action = planner(instruction, {"source_duration": duration, "history": history})
        return action, None, None

    return None, "目前只能截取视频或提取画面。请给出明确操作和时间范围。", None


def _persist(project: Path, before: dict[str, Any], *, instruction: str,
             status: str, result: dict[str, Any], pending: dict[str, Any] | None = None,
             output: Path | None = None, action: Action | None = None) -> dict[str, Any]:
    new = dict(before)
    new["revision"] = before["revision"] + 1
    turn = {"turn": len(before.get("conversation", [])) + 1,
            "revision": new["revision"], "instruction": instruction, "status": status,
            **result}
    new["conversation"] = [*before.get("conversation", []), turn]
    new["pending"] = pending
    if status == "blocked" and "preservation" in result:
        new["constraints"] = [*before.get("constraints", []),
                              {"source_turn": turn["turn"], "preservation": result["preservation"],
                               "status": "blocked_unfulfilled"}]
    if output is not None and action is not None:
        entry = {"revision": new["revision"], "instruction": instruction,
                 "operation": action.kind, "source": result["source"], "result": str(output),
                 "start_seconds": action.start, "end_seconds": action.end,
                 "verified": "file-and-duration" if action.kind == "trim" else "nonempty-image"}
        new["history"] = [*before["history"], entry]
        if action.kind == "trim":
            new["active_media"] = str(output)
        new["last_goal"] = {"instruction": instruction, "operation": action.kind,
                            "source": result["source"], "result": str(output),
                            "status": "executed"}
    try:
        _save_if_unchanged(project, before, new)
    except Exception:
        if output is not None:
            output.unlink(missing_ok=True)
        raise
    return {"status": status, "turn": turn["turn"], "revision": new["revision"], **result}


def chat_turn(project: Path, instruction: str, *, dry_run: bool = False,
              planner: Planner | None = None) -> dict[str, Any]:
    """Perform or clarify one turn, preserving a compact conversation history."""
    before = read_state(project)
    if not instruction.strip():
        raise SalaError("请输入创作指令。")

    # A strict preservation request may only be recorded as blocked, NEVER
    # routed into a model that can reinterpret it as an allowlisted operation.
    try:
        enforce_preservation_boundary(instruction)
        if _EXTRA_PRESERVE.search(instruction):
            raise SalaError("检测到明确的保留约束。当前原型不能验证其他镜头不变，未执行。")
    except SalaError as exc:
        result = {"reason": str(exc), "preservation": instruction}
        return ({"status": "blocked", **result, "dry_run": True} if dry_run else
                _persist(project, before, instruction=instruction, status="blocked", result=result))

    if _UNSUPPORTED_EDIT.search(instruction):
        result = {"question": "当前只支持截取视频和提取画面，暂不支持动作、背景或生成式修改。请明确可执行的单独操作。"}
        return ({"status": "needs_clarification", **result, "dry_run": True} if dry_run else
                _persist(project, before, instruction=instruction, status="needs_clarification", result=result))

    source = Path(before["active_media"])
    duration = probe_video(source)
    action, question, pending = _resolve(before, instruction, planner, duration)
    if question is not None:
        result = {"question": question}
        return ({"status": "needs_clarification", **result, "dry_run": True} if dry_run else
                _persist(project, before, instruction=instruction, status="needs_clarification",
                         result=result, pending=pending))
    assert action is not None
    _safe_action(action, duration)
    summary = {"operation": action.kind, "source": str(source),
               "start_seconds": action.start, "end_seconds": action.end,
               "will_modify_original": False}
    if dry_run:
        return {"status": "planned", **summary, "dry_run": True}

    output = render(source, action, project / "renders")
    return _persist(project, before, instruction=instruction, status="completed",
                    result={**summary, "output": str(output),
                            "verification": "file-and-duration" if action.kind == "trim" else "nonempty-image"},
                    output=output, action=action)
