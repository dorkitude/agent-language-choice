import importlib.util
import pathlib
import sqlite3
import json
import tempfile
import unittest
import hashlib
from unittest.mock import patch

P = pathlib.Path(__file__).with_name('build_report.py')
SPEC = importlib.util.spec_from_file_location('build_report', P)
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)

class SnapshotTests(unittest.TestCase):
    def test_retryable_failure_and_snapshot_mismatch_are_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp)/'result.json'
            path.write_text('{}')
            row = dict(status='fail', result_path=str(path),
                       json_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            with patch.object(b.harness, 'needs_reclassified_agent_retry', return_value=True):
                self.assertEqual(b.reconciled_failure_status(row), 'blocked')
            with patch.object(b.harness, 'needs_reclassified_agent_retry', return_value=False), patch.object(b.harness, 'run_status', return_value='fail'):
                self.assertEqual(b.reconciled_failure_status(row), 'fail')
            path.write_text('{"changed":true}')
            self.assertEqual(b.reconciled_failure_status(row), 'partial')
            path.unlink()
            self.assertEqual(b.reconciled_failure_status(row), 'partial')

    def test_latest_attempt_missing_cells_and_unknown_costs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = pathlib.Path(tmp)/'state.sqlite3'
            with sqlite3.connect(db) as c:
                b.harness.init_state_db(c)
                for run_id, created, status, completed in [('old','2026-01-01','pass',100),('new','2026-01-02','partial',3)]:
                    c.execute('''INSERT INTO runs (run_id,kind,status,passed,provider,model,target,language,framework,stage_count,completed_stages,total_shots,run_dir,result_path,json_sha256,created_at_utc,updated_at_utc)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (run_id,'lifecycle',status,int(status=='pass'),'codex','gpt-5.6-terra','go-stdlib','go','stdlib',100,completed,1,tmp,str(pathlib.Path(tmp)/'missing.json'),'hash',created,created))
                c.execute('''INSERT INTO shots (run_id,shot,status,passed,setup_ok,agent_exit_class,agent_timed_out,eval_passed,eval_timed_out)
                    VALUES ('new',1,'timeout',0,1,'ok',0,0,1)''')
            (db.parent/"operator-events.jsonl").write_text(json.dumps({"run_id":"new","event":"test-intervention"})+"\n")
            d=b.snapshot(db)
            self.assertEqual(len(d['cells']),85)
            cell=next(c for c in d['cells'] if c['model']=='gpt-5.6-terra' and c['target']=='go-stdlib')
            self.assertEqual(cell['run_id'],'new')
            self.assertEqual(cell['status'],'partial')
            self.assertEqual(cell['operator_events'][0]['event'],'test-intervention')
            self.assertEqual(len(cell['history']),2)
            self.assertFalse(cell['artifact_present'])
            self.assertEqual(cell['shots'][0]['eval_timed_out'],1)
            self.assertIsNone(cell['shots'][0]['cost_usd'])
            self.assertEqual(sum(c['status']=='missing' for c in d['cells']),84)

if __name__=='__main__': unittest.main()
