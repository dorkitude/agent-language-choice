"""Regression tests for the benchmark instrument, not generated solutions."""
import importlib.util
import json
import pathlib
import socket
import sys
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("rest_harness", pathlib.Path(__file__).with_name("rest_harness.py"))
h = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = h
SPEC.loader.exec_module(h)

class ServerLogTests(unittest.TestCase):
    def test_chatty_server_does_not_block_health_or_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "server.py").write_text("""import os,sys
from http.server import BaseHTTPRequestHandler,HTTPServer
sys.stdout.write('o'*262144);sys.stdout.flush()
sys.stderr.write('e'*262144);sys.stderr.flush()
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  sys.stderr.write('r'*262144);sys.stderr.flush()
  self.send_response(200);self.end_headers();self.wfile.write(b'{}')
HTTPServer(('127.0.0.1',int(os.environ['PORT'])),Handler).serve_forever()
""")
            (root / "run.sh").write_text('#!/bin/sh\nexec '+sys.executable+' -u server.py\n')
            evaluator = root / "evaluate"
            evaluator.write_text('#!'+sys.executable+'\n'+"""import sys,json,urllib.request
args=sys.argv
url=args[args.index('--base-url')+1]
with urllib.request.urlopen(url+'/probe',timeout=3) as response:
 assert response.status==200
open(args[args.index('--json-out')+1],'w').write(json.dumps({'passed':True,'results':[]}))
""")
            evaluator.chmod(0o755)
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port=sock.getsockname()[1]
            result=h.evaluate_exclusive(root,evaluator,port,3)
            self.assertTrue(result['passed'], result)
            self.assertGreater((root/'server_stdout.txt').stat().st_size,65536)
            self.assertGreater((root/'server_stderr.txt').stat().st_size,524288)

class LatestAttemptTests(unittest.TestCase):
    def test_old_success_does_not_hide_new_partial_and_new_success_does_not_resume_old_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            stages=h.selected_stages(None)
            def write(name, date, complete):
                folder=root/name;folder.mkdir(exist_ok=True)
                (folder/'lifecycle-result.json').write_text(json.dumps({
                    'metadata': {'provider':'codex','model':'gpt-5.6-terra','target':'go-stdlib',
                        'created_at_utc':date,'stages':[s.id for s in stages]},
                    'completed_at_utc':date if complete else None,
                    'passed':complete,'shots':[], 'stage_results':[]}))
                return folder
            old=write('old','2026-01-01',True)
            new=write('new','2026-01-02',False)
            with mock.patch.object(h,'LIFECYCLE_RUNS_DIR',root):
                self.assertFalse(h.completed_lifecycle_exists('codex','gpt-5.6-terra','go-stdlib',None))
                self.assertEqual(h.find_resumable_lifecycle_run('codex','gpt-5.6-terra','go-stdlib',stages)[0],new)
                write('old','2026-01-01',False)
                write('new','2026-01-02',True)
                self.assertTrue(h.completed_lifecycle_exists('codex','gpt-5.6-terra','go-stdlib',None))
                self.assertIsNone(h.find_resumable_lifecycle_run('codex','gpt-5.6-terra','go-stdlib',stages))

class ProviderCapacityTests(unittest.TestCase):
    def test_capacity_error_is_infrastructure_but_quoted_content_is_not(self):
        error=json.dumps({'type':'turn.failed','error':{'message':'Selected model is at capacity. Please try a different model.'}})
        self.assertEqual(h.classify_agent_exit(error,'',False,1),'provider_capacity')
        self.assertIn('provider_capacity',h.INFRA_EXIT_CLASSES)
        content=json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'Selected model is at capacity.'}})
        self.assertEqual(h.classify_agent_exit(content,'',False,0),'ok')

    def test_expired_claude_oauth_is_auth_infrastructure(self):
        error=json.dumps({'type':'result','is_error':True,'result':'Failed to authenticate: OAuth session expired and could not be refreshed'})
        self.assertEqual(h.classify_agent_exit(error,'',False,1),'auth_error')

    def test_reclassified_capacity_error_preserves_exhausted_stage_retry(self):
        error=json.dumps({'type':'turn.failed','error':{'message':'Selected model is at capacity.'}})
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            logs=root/'shots'/'01_s_maintenance';logs.mkdir(parents=True)
            (logs/'agent_stdout.txt').write_text(error)
            capacity={'shot':1,'kind':'maintenance','stage':'s','agent':{'exit_class':'agent_error','returncode':1},'passed':False}
            feature={'stage':'s','agent':{'exit_class':'ok','returncode':0},'passed':False}
            data={'metadata':{'max_fix_shots':5},'failed_stage':'s','shots':[capacity]+[feature]*5}
            self.assertTrue(h.needs_reclassified_agent_retry(data,root))
            data['shots'].append(feature)
            self.assertFalse(h.needs_reclassified_agent_retry(data,root))
            data['shots']=[feature]*6
            self.assertFalse(h.needs_reclassified_agent_retry(data,root))

if __name__ == '__main__':
    unittest.main()
