"""No network or external API needed; FFmpeg tests run when tools are installed."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sala.core import (Action, SalaError, _save_if_unchanged, execute,
                       initialize, parse_instruction, read_state)


class IntentTests(unittest.TestCase):
    def test_supported_chinese(self):
        self.assertEqual(parse_instruction("截取 1 到 3 秒片段"), Action("trim", 1.0, 3.0))
        self.assertEqual(parse_instruction("提取第 2 秒的画面"), Action("frame", 2.0))

    def test_supported_english(self):
        self.assertEqual(parse_instruction("trim from 1 to 3 seconds"), Action("trim", 1.0, 3.0))
        self.assertEqual(parse_instruction("extract frame at 2s"), Action("frame", 2.0))

    def test_reject_ambiguous_or_unsupported(self):
        for instruction in ["再快一点", "让转身更快", "截取 3 到 1 秒片段", ""]:
            with self.subTest(instruction=instruction), self.assertRaises(SalaError):
                parse_instruction(instruction)

    def test_preserve_constraint_blocks_unsupported_edit(self):
        with self.assertRaisesRegex(SalaError, "保留约束"):
            parse_instruction("转身快一点，其他镜头保持不变")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg unavailable")
class MediaIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / "input.mp4"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", "testsrc2=size=160x90:rate=10", "-t", "4", "-c:v", "mpeg4",
            "-y", str(self.video),
        ], check=True)
        self.project = self.root / "project"
        initialize(self.project, self.video)

    def test_trim_then_extract_then_status(self):
        plan = execute(self.project, "截取 1 到 3 秒片段", dry_run=True)
        self.assertTrue(plan["dry_run"])
        self.assertEqual(read_state(self.project)["revision"], 0)
        trim = execute(self.project, "截取 1 到 3 秒片段")
        self.assertTrue(Path(trim["output"]).is_file())
        self.assertEqual(read_state(self.project)["revision"], 1)
        self.assertEqual(read_state(self.project)["active_media"], trim["output"])
        frame = execute(self.project, "提取第 1 秒的画面")
        self.assertTrue(Path(frame["output"]).is_file())
        state = read_state(self.project)
        self.assertEqual(state["revision"], 2)
        self.assertEqual(state["active_media"], trim["output"])
        self.assertEqual(len(state["history"]), 2)
        self.assertTrue(self.video.is_file())

    def test_rejected_request_keeps_state(self):
        initial = read_state(self.project)
        with self.assertRaises(SalaError):
            execute(self.project, "人物转身更快，其他镜头保持不变")
        self.assertEqual(read_state(self.project), initial)
        self.assertFalse((self.project / "renders").exists())

    def test_range_validation(self):
        with self.assertRaises(SalaError):
            execute(self.project, "截取 2 到 10 秒片段")
        self.assertEqual(read_state(self.project)["revision"], 0)

    def test_stale_state_rejected(self):
        old = read_state(self.project)
        updated = dict(old)
        updated["revision"] = 1
        with patch("sala.core.read_state", return_value={**old, "revision": 7}):
            with self.assertRaisesRegex(SalaError, "过期"):
                _save_if_unchanged(self.project, old, updated)


if __name__ == "__main__":
    unittest.main()

# Appended standalone contract tests; discovered by unittest even without FFmpeg.
class PlannerContractTests(unittest.TestCase):
    def test_allowlisted_actions_only(self):
        from sala.planner import interpret_plan
        self.assertEqual(interpret_plan('{"action":"trim","start_seconds":1,"end_seconds":2}'),
                         Action("trim", 1.0, 2.0))
        with self.assertRaisesRegex(SalaError, "允许"):
            interpret_plan('{"action":"shell","command":"rm -rf /"}')
        with self.assertRaises(SalaError):
            interpret_plan('{"action":"frame","at_seconds":true}')
        with self.assertRaisesRegex(SalaError, "澄清"):
            interpret_plan('{"action":"clarify","question":"哪个镜头？"}')

    def test_provider_payload_and_response(self):
        from io import BytesIO
        from sala.planner import plan_with_llm
        from unittest.mock import patch
        response = {"choices": [{"message": {"content": '{"action":"frame","at_seconds":1}'}}]}
        class FakeResponse(BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): return None
        def fake_urlopen(request, timeout):
            payload = json.loads(request.data)
            self.assertEqual(payload["model"], "fake-model")
            self.assertEqual(len(payload["messages"]), 2)
            self.assertNotIn("/private/video.mp4", request.data.decode())
            self.assertEqual(timeout, 40)
            return FakeResponse(json.dumps(response).encode())
        with patch.dict("os.environ", {"SALA_LLM_CHAT_URL":"http://localhost:1234/v1/chat/completions",
                                       "SALA_LLM_MODEL":"fake-model", "SALA_LLM_API_KEY":"test-key"}), \
             patch("sala.planner.urllib.request.urlopen", side_effect=fake_urlopen):
            action = plan_with_llm("提取第一秒", {"source_duration": 4, "history": [{"instruction": "hello"}]})
            self.assertEqual(action, Action("frame", 1.0))
