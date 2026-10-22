"""Continue already authorized checkpoints; stop on any failed stage."""
import json
import subprocess
import sys
from pathlib import Path

E = Path(__file__).resolve().parents[1]
A = E / 'artifacts/workzone_03/agentic_final_review81'
C = E / 'cases/workzone_03'


def update(stage, status):
    p = C / 'stage_0_to_6_index.json'
    d = json.loads(p.read_text())
    for row in d['stages']:
        if row['stage'] == stage:
            row['status'] = status
    d['layout_selection_note'] = 'TA-19, source-review correction followed by explicit user confirmation; prior failures retained.'
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n')


def main():
    first = json.loads((A / 'stage0_1_2/result.json').read_text())
    if first['status'] != 'awaiting_stage1_stage2_evaluation':
        raise RuntimeError('Stage 1–2 not ready: ' + str(first.get('failure_reason')))
    for stage in [0, 1, 2]:
        update(stage, 'complete')
    expected = {3: 'awaiting_user_requirement_review', 4: 'awaiting_stage4_evaluation',
                5: 'awaiting_stage5_evaluation', 6: 'completed'}
    for stage in range(int(sys.argv[1]) if len(sys.argv) > 1 else 3, 7):
        update(stage, 'running')
        cfg = f'config/workzone_03/stage{stage}.json'
        with (A / f'stage{stage}.log').open('w') as log:
            for script in ['preflight_srag_bm25_v5.py', 'run_srag_bm25_v5.py']:
                cmd = [sys.executable, 'scripts/' + script, '--config', cfg]
                if script.startswith('run_'):
                    cmd.append('--execute')
                subprocess.run(cmd, cwd=E, stdout=log, stderr=subprocess.STDOUT, check=True)
        r = json.loads((A / f'stage{stage}/result.json').read_text())
        print(f'Stage {stage}: {r["status"]}', flush=True)
        if r['status'] != expected[stage]:
            update(stage, 'failed')
            raise RuntimeError(r.get('failure_reason') or r['status'])
        update(stage, 'complete')
    subprocess.run([sys.executable, 'scripts/workzone3_render_agentic_report.py'], cwd=E, check=True)


if __name__ == '__main__':
    main()
