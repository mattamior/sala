# sala prototype 0.1 — first executable slice

**Status:** runnable engineering spike; not a usable end-user desktop app and not a full autonomous generative Agent.

## Why this slice

This closes the planning-only phase with the smallest complete feedback loop we can test without a media-generation provider: parse **bounded** natural-language intent → validate against source duration and preservation limits → execute real FFmpeg operation → validate output → retain new version and history. Python 3.11+ and FFmpeg/ffprobe are the only runtime requirements. This **does not** lock the production language, UI, Agent runtime, or video-model provider.

## Run

Install FFmpeg (on macOS: `brew install ffmpeg`), then from the repository root:

```bash
PYTHONPATH=src python -m sala init --project ./demo --source /absolute/path/to/input.mp4
PYTHONPATH=src python -m sala run --project ./demo --dry-run "截取 1 到 3 秒片段"
PYTHONPATH=src python -m sala run --project ./demo "截取 1 到 3 秒片段"
PYTHONPATH=src python -m sala run --project ./demo "提取第 1 秒的画面"
PYTHONPATH=src python -m sala status --project ./demo
PYTHONPATH=src python -m unittest discover -s tests -v
```

Operations create new outputs in `./demo/renders/` and never overwrite imported media or earlier outputs. Video trims update the project's active media; frame extraction keeps the active video unchanged. Project state lives in `./demo/.sala/project.json` with a revision and traceable operation history. Initialization links to the input file on disk rather than copying its bytes; keep the input file available.

With `--planner llm`, an optional OpenAI-compatible chat-completions endpoint can interpret freer text while still being restricted to the two allowlisted actions. Set `SALA_LLM_CHAT_URL` (full chat-completions endpoint), `SALA_LLM_MODEL`, and optionally `SALA_LLM_API_KEY`. This sends the instruction, source duration, and last two instructions to the configured provider—not video bytes or local paths. Do not use untrusted providers with private prompts. The LLM pathway has mocked contract tests but has **not** been validated against a live provider.

Supported default rule-based instructions are intentionally narrow, including `截取 1 到 3 秒片段`, `提取第 2 秒的画面`, `trim from 1 to 3 seconds`, and `extract frame at 2s`. Unsupported or ambiguous instructions return a nonzero exit code without changing project state. It deliberately refuses requests that include strict preservation requirements it cannot verify, such as `人物转身更快，其他镜头保持不变`.

## Not yet implemented

- No autonomous multi-step planner, semantic frame/shot/object understanding, reference matching, video generation, UI or plugins. The optional LLM planner is only a constrained, unverified single-action interpreter.
- No localized edits, preservation guarantees beyond not altering the input files, or creative quality assessment.
- No robust multi-writer project locking. Run one `sala` process per project at a time.
- Output verification covers existence and approximate duration (for trims), not motion, identity, or aesthetic quality.
- No distribution package / license decision / production security review yet.

## Next code milestone

Evaluate the optional LLM planner against a real configured provider, then implement a two-turn constraint-aware plan/clarify/execute loop (with tests) before wiring in an independent media-generation backend. UI comes after the loop is useful.
