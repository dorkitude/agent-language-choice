"""Regression tests for the benchmark instrument, not generated solutions."""
import importlib.util
import json
import pathlib
import socket
import sys
import tempfile
import unittest

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

if __name__ == '__main__':
    unittest.main()
