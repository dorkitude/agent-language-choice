#!/usr/bin/env python3
"""Build an offline Chart.js report from a consistent, read-only SQLite snapshot."""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('report_harness', HERE.parent / 'rest_harness.py')
harness = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = harness
spec.loader.exec_module(harness)


def snapshot(db):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    con.execute('BEGIN')
    rows = [dict(r) for r in con.execute('SELECT * FROM runs WHERE kind = ? AND stage_count = ? ORDER BY created_at_utc, updated_at_utc, run_id', ('lifecycle', 100))]
    if not rows:
        # Historical stores may call lifecycle rows by another kind; never silently export empty data.
        kinds = list(con.execute('SELECT DISTINCT kind FROM runs'))
        raise ValueError(f'No 100-stage lifecycle rows; available kinds: {kinds}')
    shots = {}
    for row in con.execute('SELECT s.* FROM shots s JOIN runs r USING(run_id) WHERE r.stage_count=100 ORDER BY s.shot'):
        item = dict(row)
        shots.setdefault(item['run_id'], []).append(item)
    con.rollback()
    con.close()
    latest = {}
    histories = {}
    for row in rows:
        key = (row['provider'], row['model'], row['target'])
        latest[key] = row
        histories.setdefault(key, []).append(row)
    stage_ids = [s.id for s in harness.STAGES] if hasattr(harness, 'STAGES') else [s.id for s in harness.selected_stages(None)]
    event_path = db.parent / "operator-events.jsonl"
    events = [json.loads(line) for line in event_path.read_text().splitlines() if line.strip()] if event_path.exists() else []
    cells = []
    for model in harness.MODELS:
        for target_id, target in harness.targets().items():
            key = (model['provider'], model['model'], target_id)
            row = latest.get(key)
            cell = {'provider': key[0], 'model': key[1], 'target': key[2], 'language': target.language,
                    'framework': target.framework, 'status': 'missing', 'completed_stages': 0,
                    'stage_count': len(stage_ids), 'shots': [], 'history': []}
            if row:
                cell.update({k: row[k] for k in ('run_id', 'status', 'completed_stages', 'stage_count',
                    'total_shots', 'failed_stage', 'created_at_utc', 'completed_at_utc', 'updated_at_utc')})
                cell['artifact_present'] = Path(row['result_path']).exists()
                cell['artifact_path'] = str(Path(row['result_path']).relative_to(ROOT)) if Path(row['result_path']).is_relative_to(ROOT) else None
                fields = ('shot', 'stage', 'kind', 'attempt', 'status', 'passed', 'agent_exit_class',
                    'eval_timed_out', 'passed_count', 'total_count', 'input_tokens', 'cached_input_tokens',
                    'output_tokens', 'cost_usd')
                cell['shots'] = [{k: s.get(k) for k in fields} for s in shots.get(row['run_id'], [])]
                cell['history'] = [{k: r[k] for k in ('run_id', 'status', 'completed_stages', 'total_shots', 'created_at_utc')}
                                   for r in histories[key]]
            cell['operator_events'] = [event for event in events if event['run_id'] == cell.get('run_id')]
            cells.append(cell)
    return {'schema_version': 1, 'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'source': 'results/dnd-rest-benchmark/experiment-state.sqlite3',
        'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'selection': 'Latest created attempt per provider/model/target; ties use updated time, then run ID.',
        'model_order': [m['model'] for m in harness.MODELS], 'target_order': list(harness.targets()),
        'stages': stage_ids, 'planned_cells': len(cells), 'historical_run_count': len(rows), 'cells': cells,
        'notes': [
            'A snapshot, not a live monitor. Rebuild to include new results.',
            'Completion means a terminal pass or deterministic failure, not that every model passed every stage.',
            'Blocked, partial, timeout, and missing cells are unresolved and excluded from terminal pass-rate denominators.',
            'Valid attempt counts exclude infrastructure-classified shots and evaluator-only deadlines. Unknown historical timeout flags remain unknown.',
            'Before September 9, undrained server log pipes could cause evaluator timeouts. Those outcomes are not evidence of model inability.',
            'Model and harness versions span multiple dates. This is an observational benchmark, not a causal language ranking.',
            'Costs show only metered values; missing costs are not zero. No inferred token prices are used.',
            'Operator interventions are flagged on affected cells and detailed in Run evidence. Annotated continuations must not be described as wholly unattended trials.',
        ], 'infra_classes': sorted(harness.INFRA_EXIT_CLASSES)}


def build(db, output):
    data = snapshot(db)
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    chart = (HERE / 'vendor/chart.umd.min.js').read_text()
    chart = '\n'.join(line for line in chart.splitlines() if 'sourceMappingURL=' not in line)
    template = (HERE / 'report.html').read_text()
    import html as html_escape
    html = template.replace('__CHART_JS__', chart).replace('__REPORT_DATA__', payload).replace('__CHART_LICENSE__', html_escape.escape((HERE / 'vendor/Chart.js-LICENSE.md').read_text()))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)
    # A small build receipt makes the single-file artifact auditable without parsing its JavaScript.
    receipt = {'generated_at': data['generated_at'], 'planned_cells': data['planned_cells'],
        'unresolved_cells': sum(c['status'] not in ('pass', 'fail') for c in data['cells']),
        'sha256': hashlib.sha256(html.encode()).hexdigest(), 'source_revision': data['source_revision']}
    output.with_suffix('.receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'output': str(output), **receipt}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, default=ROOT/'results/dnd-rest-benchmark/experiment-state.sqlite3')
    parser.add_argument('--output', type=Path, default=ROOT/'results/dnd-rest-benchmark/dnd-rest-findings.html')
    args = parser.parse_args()
    build(args.db.resolve(), args.output.resolve())
