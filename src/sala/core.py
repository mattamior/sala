"""Conservative intent parsing and FFmpeg-backed media operations.

This is a deliberately restricted prototype, not a general-purpose LLM planner.
Unrecognized and ambiguous instructions are rejected rather than guessed.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class SalaError(Exception):
    """An expected, user-facing error that must not silently change state."""


@dataclass(frozen=True)
class Action:
    kind: str
    start: float
    end: float | None = None


_NUMBER = r"(\d+(?:\.\d+)?)"
_TRIM_PATTERNS = (
    re.compile(rf"^\s*(?:请)?(?:截取|剪出|裁剪)\s*{_NUMBER}\s*(?:秒)?\s*(?:到|至|[-~～—])\s*{_NUMBER}\s*秒?(?:的)?(?:视频|片段)?\s*[。.!！]?\s*$"),
    re.compile(rf"^\s*(?:请)?从\s*{_NUMBER}\s*秒\s*(?:到|至|[-~～—])\s*{_NUMBER}\s*秒\s*(?:截取|剪出|裁剪)(?:视频|片段)?\s*[。.!！]?\s*$"),
    re.compile(rf"^\s*(?:please\s+)?(?:trim|cut)(?:\s+video)?(?:\s+from)?\s+{_NUMBER}\s*(?:s|sec|seconds)?\s*(?:to|-)\s*{_NUMBER}\s*(?:s|sec|seconds)?\s*[.!]?\s*$", re.I),
)
_FRAME_PATTERNS = (
    re.compile(rf"^\s*(?:请)?(?:提取|导出|截取|截出)\s*第?\s*{_NUMBER}\s*秒(?:的)?(?:画面|帧|截图)\s*[。.!！]?\s*$"),
    re.compile(rf"^\s*(?:extract|capture)(?:\s+a)?\s+frame\s+(?:at\s+)?{_NUMBER}\s*(?:s|sec|seconds)?\s*[.!]?\s*$", re.I),
)
_PRESERVATION = re.compile(
    r"(?:其他|其它|其余)(?:的)?(?:镜头|片段|画面).{0,12}(?:不变|保持|不要改)|"
    r"(?:保持|不许改变|不要改变).{0,12}(?:不变|原样|镜头|画面)|"
    r"(?:keep|preserve).{0,30}(?:rest|unchanged|other shots)", re.I
)


def enforce_preservation_boundary(instruction: str) -> None:
    """Reject impossible preservation guarantees before invoking any planner."""
    if _PRESERVATION.search(instruction):
        raise SalaError(
            "检测到明确的保留约束。当前原型不能证明局部编辑后其他镜头保持不变；"
            "因此未执行。请使用独立的截取/提帧指令，或等后续接入可验证的局部编辑能力。"
        )


def parse_instruction(instruction: str) -> Action:
    """Return a bounded action; never infer unsupported creative edits."""
    enforce_preservation_boundary(instruction)
    for pattern in _TRIM_PATTERNS:
        match = pattern.fullmatch(instruction)
        if match:
            start, end = map(float, match.groups())
            if start < 0 or end <= start:
                raise SalaError("截取时间必须满足 0 ≤ 开始时间 < 结束时间。")
            return Action("trim", start=start, end=end)
    for pattern in _FRAME_PATTERNS:
        match = pattern.fullmatch(instruction)
        if match:
            start = float(match.group(1))
            if start < 0:
                raise SalaError("画面时间必须大于或等于 0。")
            return Action("frame", start=start)
    raise SalaError(
        "当前仅支持明确的指令，如「截取 1 到 3 秒片段」「提取第 2 秒的画面」。"
        "复杂创意或含糊的跟进指令不会被擅自猜测、执行。"
    )


def _tool(args: list[str], *, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, capture_output=True, text=True, check=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise SalaError(f"缺少媒体工具：{args[0]}。请安装 FFmpeg（含 ffprobe）。") from exc
    except subprocess.TimeoutExpired as exc:
        raise SalaError(f"媒体工具执行超时：{args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        # Do not expose unwieldy logs or shell commands; no shell is used.
        detail = (exc.stderr or "").strip().splitlines()
        raise SalaError(f"媒体工具执行失败：{detail[-1] if detail else '未知错误'}") from exc


def probe_video(source: Path) -> float:
    """Validate local video file and return duration in seconds."""
    if not source.is_file():
        raise SalaError(f"视频文件不存在：{source}")
    result = _tool([
        "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
        "-of", "json", str(source),
    ])
    try:
        obj = json.loads(result.stdout)
        if not any(s.get("codec_type") == "video" for s in obj.get("streams", [])):
            raise ValueError("no video stream")
        duration = float(obj["format"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("invalid duration")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SalaError("无法获取有效视频时长/视频流，当前原型不处理该素材。") from exc
    return duration


def validate_action(action: Action, duration: float) -> None:
    if action.start < 0 or action.start >= duration:
        raise SalaError(f"请求的起点超出视频时长 {duration:.3f} 秒。")
    if action.kind == "trim" and (action.end is None or action.end > duration):
        raise SalaError(f"请求的结束时间超出视频时长 {duration:.3f} 秒。")


def render(source: Path, action: Action, output_dir: Path) -> Path:
    """Create a new derived asset, never overwrite source or prior outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    extension = ".mp4" if action.kind == "trim" else ".jpg"
    output = output_dir / f"{uuid.uuid4().hex}{extension}"
    if action.kind == "trim":
        assert action.end is not None
        args = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
            "-i", str(source), "-ss", str(action.start), "-t", str(action.end - action.start),
            "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-movflags", "+faststart", str(output),
        ]
    else:
        args = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
            "-ss", str(action.start), "-i", str(source),
            "-frames:v", "1", "-q:v", "2", str(output),
        ]
    try:
        _tool(args, timeout=300)
        if not output.is_file() or output.stat().st_size == 0:
            raise SalaError("媒体操作没有生成有效的输出文件。")
        if action.kind == "trim":
            actual = probe_video(output)
            if abs(actual - (action.end - action.start)) > 0.35:
                raise SalaError("输出视频时长不符合截取请求，结果未被接纳。")
        return output
    except Exception:
        output.unlink(missing_ok=True)
        raise


STATE_DIR = ".sala"
STATE_FILE = "project.json"


def state_path(project: Path) -> Path:
    return project / STATE_DIR / STATE_FILE


def initialize(project: Path, source: Path) -> dict[str, Any]:
    """Create a persistent project without copying or modifying the source."""
    source = source.resolve(strict=True)
    duration = probe_video(source)
    state_file = state_path(project)
    if state_file.exists():
        raise SalaError(f"项目已存在，不会覆盖：{state_file}")
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state = {"schema": 1, "revision": 0, "original_media": str(source),
             "active_media": str(source), "history": []}
    # Exclusive creation; avoid clobber on concurrent init.
    try:
        with state_file.open("x", encoding="utf-8") as fp:
            json.dump(state, fp, ensure_ascii=False, indent=2)
    except FileExistsError as exc:
        raise SalaError("项目已存在，初始化已取消。") from exc
    return {**state, "source_duration": duration}


def read_state(project: Path) -> dict[str, Any]:
    path = state_path(project)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SalaError("未找到有效项目；先执行 init。") from exc
    if not isinstance(state, dict) or state.get("schema") != 1:
        raise SalaError("项目版本不受支持，已停止执行。")
    if not isinstance(state.get("revision"), int) or not isinstance(state.get("history"), list):
        raise SalaError("项目状态无效。")
    return state


def _save_if_unchanged(project: Path, before: dict[str, Any], updated: dict[str, Any]) -> None:
    """Reject late outputs when a separate operation advanced the project."""
    if read_state(project) != before:
        raise SalaError("创作状态已被其他操作更新，拒绝用过期结果覆盖。")
    path = state_path(project)
    fd, tmp_path = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(updated, fp, ensure_ascii=False, indent=2)
            fp.flush()
            os.fsync(fp.fileno())
        # This single-process prototype checks baseline but does NOT support
        # robust multi-writer locking. Concurrent writers are unsupported.
        os.replace(tmp_path, path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def execute(project: Path, instruction: str, *, dry_run: bool = False,
            planner: Callable[[str, dict[str, Any]], Action] | None = None) -> dict[str, Any]:
    before = read_state(project)
    enforce_preservation_boundary(instruction)
    source = Path(before["active_media"])
    duration = probe_video(source)
    context = {"source_duration": duration, "history": before["history"]}
    action = planner(instruction, context) if planner else parse_instruction(instruction)
    validate_action(action, duration)
    preview = {
        "operation": action.kind, "source": str(source),
        "start_seconds": action.start, "end_seconds": action.end,
        "source_duration": duration,
        "will_modify_original": False, "dry_run": dry_run,
    }
    if dry_run:
        return preview
    output = render(source, action, project / "renders")
    next_state = dict(before)
    next_state["revision"] = before["revision"] + 1
    entry = {
        "revision": next_state["revision"], "instruction": instruction,
        "operation": action.kind, "source": str(source), "result": str(output),
        "start_seconds": action.start, "end_seconds": action.end,
        "verified": "file-and-duration" if action.kind == "trim" else "nonempty-image",
    }
    next_state["history"] = [*before["history"], entry]
    if action.kind == "trim":
        next_state["active_media"] = str(output)
    try:
        _save_if_unchanged(project, before, next_state)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return {**preview, "dry_run": False, "output": str(output),
            "revision": next_state["revision"], "verification": entry["verified"]}
