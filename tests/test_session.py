"""M2.1 contract and real FFmpeg integration tests."""
from __future__ import annotations
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sala.core import Action, SalaError, initialize, read_state, execute
from sala.session import chat_turn
from sala.cli import main

class GrammarTests(unittest.TestCase):
    def setUp(self):
        self.project=Path('/dummy')
    def test_invalid_planner_action_rejected(self):
        from sala.session import _safe_action
        for action in [Action('delete', 0),Action('trim',float('nan'),2),Action('trim',1,float('inf')),
                       Action('frame',0,4),Action('frame',True)]:
            with self.subTest(action=action), self.assertRaises(SalaError):
                _safe_action(action,4)

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'requires ffmpeg')
class SessionMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.media=self.root/'original.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
                        'testsrc2=size=160x90:rate=10','-t','4','-c:v','mpeg4','-y',str(self.media)],check=True)
        self.project=self.root/'p'
        initialize(self.project,self.media)
    def test_two_turn_context_reference_and_provenance(self):
        trim=chat_turn(self.project,'截取视频第1到3秒')
        self.assertEqual(trim['status'],'completed')
        self.assertEqual(trim['operation'],'trim')
        self.assertEqual(read_state(self.project)['active_media'],trim['output'])
        shot=chat_turn(self.project,'把刚才那段的第1秒导出成图片')
        self.assertEqual(shot['status'],'completed')
        self.assertEqual(shot['operation'],'frame')
        self.assertEqual(shot['source'],trim['output'])
        self.assertTrue(Path(shot['output']).is_file())
        state=read_state(self.project)
        self.assertEqual([h['operation'] for h in state['history']],['trim','frame'])
        self.assertEqual(state['revision'],2)
        self.assertEqual(state['last_goal']['source'],trim['output'])
        self.assertTrue(self.media.is_file())
    def test_persistent_clarification_then_continue(self):
        initial=read_state(self.project)
        reply=chat_turn(self.project,'提取画面')
        self.assertEqual(reply['status'],'needs_clarification')
        self.assertEqual(read_state(self.project)['pending']['kind'],'frame_time')
        self.assertEqual(len(read_state(self.project)['history']),0)
        final=chat_turn(self.project,'第 2 秒')
        self.assertEqual(final['status'],'completed')
        self.assertTrue(Path(final['output']).exists())
        self.assertIsNone(read_state(self.project)['pending'])
        self.assertEqual([c['status'] for c in read_state(self.project)['conversation']],
                         ['needs_clarification','completed'])
    def test_clarification_dry_run_does_not_persist(self):
        start=read_state(self.project)
        planned=chat_turn(self.project,'导出画面',dry_run=True)
        self.assertEqual(planned['status'],'needs_clarification')
        self.assertEqual(read_state(self.project),start)
        with self.assertRaises(SalaError):
            chat_turn(self.project,'',dry_run=False)
        self.assertEqual(read_state(self.project),start)
    def test_preserve_refusal_persists_without_creating_output(self):
        old=read_state(self.project)
        blocked=chat_turn(self.project,'人物转身更快，其他镜头保持不变')
        self.assertEqual(blocked['status'],'blocked')
        state=read_state(self.project)
        self.assertEqual(state['active_media'],old['active_media'])
        self.assertEqual(state['history'],[])
        self.assertEqual(state['constraints'][0]['status'],'blocked_unfulfilled')
        self.assertFalse((self.project/'renders').exists())
        follow=chat_turn(self.project,'再快一点')
        self.assertEqual(follow['status'],'needs_clarification')
        self.assertEqual(read_state(self.project)['history'],[])
    def test_no_unjustified_reference_to_nonexistent_clip(self):
        result=chat_turn(self.project,'把刚才那段的第1秒导出成图片')
        self.assertEqual(result['status'],'needs_clarification')
        self.assertIsNone(read_state(self.project)['pending'])
        self.assertFalse((self.project/'renders').exists())
    def test_dry_run_avoids_output(self):
        initial=read_state(self.project)
        preview=chat_turn(self.project,'截取 1 到 3 秒片段',dry_run=True)
        self.assertEqual(preview['status'],'planned')
        self.assertEqual(read_state(self.project),initial)
        self.assertFalse((self.project/'renders').exists())
    def test_out_of_range_rejected_without_state_changes(self):
        initial=read_state(self.project)
        with self.assertRaises(SalaError):
            chat_turn(self.project,'截取视频第2到10秒')
        self.assertEqual(read_state(self.project),initial)
    def test_pending_is_not_misread_as_new_action(self):
        chat_turn(self.project,'提取画面')
        second=chat_turn(self.project,'截取 1 到 3 秒片段')
        self.assertEqual(second['status'],'completed')
        self.assertIsNone(read_state(self.project)['pending'])
        self.assertEqual(second['operation'],'trim')
    def test_llm_mock_and_action_whitelist(self):
        planned=chat_turn(self.project,'请把第二秒截出来做截图',planner=lambda *args: Action('frame',2))
        self.assertEqual(planned['status'],'completed')
        old=read_state(self.project)
        with self.assertRaises(SalaError):
            chat_turn(self.project,'请把第二秒截出来做截图',planner=lambda *args: Action('shell',0))
        self.assertEqual(old,read_state(self.project))
        with self.assertRaises(SalaError):
            chat_turn(self.project,'请把第二秒截出来做截图',planner=lambda *args: Action('trim',0, float('nan')))
    def test_no_implicit_action_on_bare_time_reference(self):
        for instruction in ['1到3秒', '刚才那段的第1秒']:
            old=read_state(self.project)
            outcome=chat_turn(self.project,instruction)
            self.assertEqual(outcome['status'],'needs_clarification')
            self.assertEqual(read_state(self.project)['history'],old['history'])

    def test_llm_cannot_ignore_unsupported_creative_request(self):
        called=[]
        reply=chat_turn(self.project,'请截取一秒并重新生成背景',planner=lambda *args: called.append(True))
        self.assertEqual(reply['status'],'needs_clarification')
        self.assertFalse(called)
        self.assertEqual(read_state(self.project)['history'],[])

    def test_alternate_strict_preserve_refused(self):
        reply=chat_turn(self.project,'人物转身快点，其他镜头别动')
        self.assertEqual(reply['status'],'blocked')
        self.assertFalse((self.project/'renders').exists())

    def test_legacy_execute_remains_supported(self):
        result=execute(self.project,'截取 1 到 3 秒片段')
        self.assertEqual(read_state(self.project)['active_media'],result['output'])
        result2=chat_turn(self.project,'把刚才那段的第1秒导出成图片')
        self.assertEqual(result2['source'],result['output'])
    def test_cli_chat_command(self):
        import io
        with patch('sys.stdout',new_callable=io.StringIO) as buf:
            rc=main(['chat','--project',str(self.project),'提取画面'])
            result=json.loads(buf.getvalue())
        self.assertEqual(rc,0)
        self.assertEqual(result['status'],'needs_clarification')
        with patch('sys.stdout',new_callable=io.StringIO) as buf:
            rc=main(['chat','--project',str(self.project),'第 1 秒'])
            result=json.loads(buf.getvalue())
        self.assertEqual(rc,0)
        self.assertEqual(result['status'],'completed')
    def test_no_pending_after_existing_video_changes(self):
        chat_turn(self.project,'提取画面')
        execute(self.project,'截取 1 到 3 秒片段')
        answer=chat_turn(self.project,'第 1 秒')
        self.assertEqual(answer['status'],'needs_clarification')
        self.assertIsNone(read_state(self.project)['pending'])
        self.assertEqual(len(read_state(self.project)['history']),1)

if __name__=='__main__':unittest.main()
