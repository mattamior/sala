# sala prototype 0.1 — executable slice + M2.1 bounded conversation

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

Connect and evaluate the optional LLM planner against a real provider (M2.2), then wire in an independent image/video generation backend (M2.3). Continue hardening clarification and constraint tests. UI comes after the loop is useful.

## M2.1 — persistent `chat` turns (implemented, bounded)

Use the existing project from `init` (or create a fresh one). All commands are separate processes, and conversation/clarification state persists in the same `.sala/project.json` file:

```bash
PYTHONPATH=src python -m sala chat --project ./demo "截取视频第1到3秒"
PYTHONPATH=src python -m sala chat --project ./demo "把刚才那段的第1秒导出成图片"
PYTHONPATH=src python -m sala chat --project ./demo "提取画面"
# sala asks: 要提取视频的第几秒画面？
PYTHONPATH=src python -m sala chat --project ./demo "第 1 秒"
PYTHONPATH=src python -m sala status --project ./demo
```

- `completed`: executed one allowlisted FFmpeg action, saved asset and current version/history.
- `needs_clarification`: saved a short question; if the question asks for a frame time, reply in the next turn with e.g. `第 1 秒` to complete it. The source must still match; an explicit new instruction replaces the pending question.
- `blocked`: unsupported strict preservation constraint was recorded, **not** executed. For example `人物转身更快，其他镜头保持不变`.
- `--dry-run`: displays a proposed action or question without writing state or output.
- `--planner llm`: still optional. It only interprets otherwise unsupported phrasing for explicitly named, allowlisted trim/frame intents. Output is validated again before execution; unsupported creative edits and preservation-sensitive requests are intercepted before invoking the model.
- Bare times like `1到3秒` are **not** accepted as a command unless a valid pending clarification gives them an unambiguous meaning. `刚才那段` only refers to the currently active clip produced by an earlier trim.
- Existing `run` and existing project schema remain readable. `chat` adds optional `conversation`, `pending`, `last_goal` and `constraints` state fields, without changing schema version.
- Existing media is not overwritten. The history of a blocked request does **not** mean the request was satisfied.
- **Limitations:** not a general-purpose conversational or generative Agent; no automatic shot/identity analysis, general persistent constraint solver, scene edits, or multi-tool autonomous plan. No cross-process exclusive lock; use one writer per project. Real LLM provider behavior is untested.

Run all existing and new tests with:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## M2.2 — third-party chat API compatibility (offline-tested)

The provider can supply an **API base URL** such as `https://your-gateway.example/v1`; sala automatically calls its `/chat/completions` route. A full `/v1/chat/completions` endpoint remains supported. This only implements **Chat Completions**; it does not claim Responses API or native tool-call integration.

Set the values as environment variables in **your own terminal**, not in the repository or a copied script:

```bash
export SALA_LLM_CHAT_URL="https://your-gateway.example/v1"
export SALA_LLM_MODEL="gpt-6-luna"  # or the exact name your provider accepts
export SALA_LLM_API_KEY="paste-current-key-locally"
PYTHONPATH=src python -m sala doctor llm
```

The `doctor` command sends a minimal non-destructive **single** instruction to the model and validates the returned structured operation. It makes a real billable request, but **does not execute FFmpeg, read local videos, or print the API Key**. It checks only a single response, not broad model reasoning reliability.

To try the LLM with the existing safeguarded video operations:

```bash
PYTHONPATH=src python -m sala chat --project ./demo --planner llm \
  "请把第二秒截出来做截图"
```

Only allowlisted `trim` and `frame` actions may execute. Model-proposed `clarify` and `unsupported` produce saved `needs_clarification` turns instead of losing context. Reject unauthorized actions, extra parameters, invalid JSON, and out-of-range timestamps. Strict preservation-sensitive or unsupported generative requests remain blocked **before** asking the model. URLs must use HTTPS except for localhost development. For reasoning-model compatibility this adapter does not force a `temperature` parameter.

**Verification limits:** Offline mocked HTTP response tests, parsing tests, and CI exercises cover transport semantics and safety. The model label and compatibility are provider claims; this execution environment cannot resolve the configured third-party DNS name, so **no authenticated request to the actual gateway was completed here**. Run the doctor on a network that can access the provider. Do not commit secrets. If a credential was shared in a chat, rotating it after testing reduces exposure.
