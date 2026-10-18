"""M2.2 offline API compatibility, parsing, error handling and session contract tests."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from sala.core import Action, SalaError, initialize, read_state
from sala.planner import (
    PlannerClarification, PlannerUnsupported, chat_url, diagnose_llm,
    interpret_plan, plan_with_llm,
)
from sala.session import chat_turn


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def completion(content):
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


class EndpointTests(unittest.TestCase):
    def test_base_and_full_urls(self):
        self.assertEqual(
            chat_url("https://example.invalid/v1"),
            "https://example.invalid/v1/chat/completions",
        )
        self.assertEqual(
            chat_url("https://example.invalid/v1/chat/completions/"),
            "https://example.invalid/v1/chat/completions",
        )
        self.assertEqual(
            chat_url("http://localhost:8010/v1"),
            "http://localhost:8010/v1/chat/completions",
        )

    def test_reject_insecure_remote_or_embedded_secret(self):
        for url in ("http://other.example/v1",
                    "https://user:secret@other.example/v1",
                    "https://other.example/v1?token=secret",
                    "ftp://other.example/v1", ""):
            with self.subTest(url=url), self.assertRaises(SalaError):
                chat_url(url)

    def test_json_and_fenced_json(self):
        self.assertEqual(interpret_plan('{"action":"frame","at_seconds":1}'), Action("frame", 1))
        self.assertEqual(
            interpret_plan(chr(96) * 3 + 'json\n{"action":"frame","at_seconds":2}\n' + chr(96) * 3),
            Action("frame", 2),
        )

    def test_clarification_and_unsupported_are_distinct(self):
        with self.assertRaises(PlannerClarification):
            interpret_plan('{"action":"clarify","question":"哪个时间段？"}')
        with self.assertRaises(PlannerUnsupported):
            interpret_plan('{"action":"unsupported","reason":"尚未接入视频模型"}')

    def test_extra_actions_and_parameters_rejected(self):
        for content in (
            '{"action":"frame","at_seconds":1,"command":"echo secret"}',
            '{"action":"shell","command":"echo secret"}',
            '{"action":"trim","start_seconds":1,"end_seconds":1}',
            '{"action":"frame","at_seconds":true}',
            '{"action":"frame","at_seconds":-2}',
        ):
            with self.subTest(content=content), self.assertRaises(SalaError):
                interpret_plan(content)


class ProviderTests(unittest.TestCase):
    def env(self):
        return patch.dict(os.environ, {
            "SALA_LLM_CHAT_URL": "https://gateway.example/v1",
            "SALA_LLM_MODEL": "test-model",
            "SALA_LLM_API_KEY": "test-only-secret-never-print",
        })

    def test_request_payload_and_base_url_and_doctor(self):
        def endpoint(request, timeout):
            self.assertEqual(timeout, 40)
            self.assertEqual(request.full_url, "https://gateway.example/v1/chat/completions")
            body = json.loads(request.data)
            self.assertEqual(body["model"], "test-model")
            self.assertEqual(len(body["messages"]), 2)
            self.assertNotIn("temperature", body)
            self.assertNotIn("test-only-secret-never-print", request.data.decode())
            self.assertEqual(request.get_header("Authorization"), "Bearer test-only-secret-never-print")
            self.assertNotIn("/private/test.mp4", request.data.decode())
            return FakeResponse(completion('{"action":"frame","at_seconds":1}'))
        with self.env(), patch("sala.planner.urllib.request.urlopen", side_effect=endpoint):
            data = diagnose_llm()
        self.assertEqual(data["status"], "ok")
        self.assertNotIn("test-only-secret-never-print", str(data))

    def test_content_parts_and_dict(self):
        for value in (
            [{"type": "text", "text": '{"action":"frame","at_seconds":1}'}],
            {"action": "frame", "at_seconds": 1},
        ):
            with self.env(), patch("sala.planner.urllib.request.urlopen", return_value=FakeResponse(completion(value))):
                self.assertEqual(plan_with_llm("提取第 1 秒的画面",
                    {"source_duration": 3, "history": []}), Action("frame", 1))

    def test_auth_error_is_sanitized(self):
        error = urllib.error.HTTPError(
            "https://gateway.example/v1/chat/completions", 401,
            "test-only-secret-never-print", hdrs={}, fp=None
        )
        with self.env(), patch("sala.planner.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(SalaError) as caught:
                plan_with_llm("提取第 1 秒的画面", {"source_duration": 3, "history": []})
        self.assertIn("鉴权", str(caught.exception))
        self.assertNotIn("test-only-secret-never-print", str(caught.exception))

    def test_rate_limit(self):
        error = urllib.error.HTTPError(
            "https://gateway.example/v1/chat/completions", 429, "rate", hdrs={}, fp=None
        )
        with self.env(), patch("sala.planner.urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(SalaError, "429"):
                plan_with_llm("提取第 1 秒的画面", {"source_duration": 3, "history": []})

    def test_invalid_response(self):
        with self.env(), patch("sala.planner.urllib.request.urlopen", return_value=FakeResponse(b"not json")):
            with self.assertRaises(SalaError):
                plan_with_llm("提取第 1 秒的画面", {"source_duration": 3, "history": []})

    def test_wrong_doctor_answer_fails(self):
        with self.env(), patch("sala.planner.urllib.request.urlopen",
                               return_value=FakeResponse(completion('{"action":"trim","start_seconds":0,"end_seconds":2}'))):
            with self.assertRaisesRegex(SalaError, "未正确理解"):
                diagnose_llm()


class SessionModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "project"
        # No media needed for this integration: patch the duration probe.
        state_file = self.project / ".sala" / "project.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text(json.dumps({
            "schema": 1, "revision": 0, "original_media": "fake.mp4",
            "active_media": "fake.mp4", "history": [],
        }), encoding="utf-8")

    def test_llm_clarification_persists(self):
        with patch("sala.session.probe_video", return_value=3):
            outcome = chat_turn(
                self.project, "截取一段你觉得合适的视频",
                planner=lambda *args: (_ for _ in ()).throw(PlannerClarification("从几秒开始？")),
            )
        self.assertEqual(outcome["status"], "needs_clarification")
        self.assertIn("几秒", outcome["question"])
        self.assertEqual(read_state(self.project)["conversation"][0]["status"], "needs_clarification")

    def test_llm_unsupported_persists(self):
        with patch("sala.session.probe_video", return_value=3):
            outcome = chat_turn(
                self.project, "把视频重新生成",
                planner=lambda *args: (_ for _ in ()).throw(PlannerUnsupported("不支持")),
            )
        # Proactive content guard also prevents unsupported creative edits.
        self.assertEqual(outcome["status"], "needs_clarification")
        self.assertEqual(read_state(self.project)["history"], [])


if __name__ == "__main__":
    unittest.main()
