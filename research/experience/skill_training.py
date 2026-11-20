#!/usr/bin/env python3
"""Bridge to an external, research-adapted official Skill Training checkout.

Upstream is not vendored or silently installed (it has its own license).
The study adapter prepares source-only work and connects the owner's model.
This bridge runs upstream diffuse/train and exports its committed memory.
An existing completed run can be imported without spending model tokens again.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import json
from experience import config, read, save, sha, within, freeze

FOLDERS = ('00_general_rules', '01_craft_elements', '02_genre_specifics')

def checked_checkout(checkout, adapter_spec=None):
    root = Path(checkout).resolve()
    spec = adapter_spec or read(root / 'ac-research-adapter.json')
    if spec.get('domain') != 'research' or not spec.get('adaptations'):
        raise ValueError('A documented research adapter is required; stock screenplay prompts do not fit scientific experiments')
    if not isinstance(spec.get('upstream_commit'), str) or len(spec['upstream_commit']) != 40:
        raise ValueError('Pin an upstream commit')
    # The owner supplies expected hashes for the official workflow files; retain
    # those plus actual prompt/transport hashes so adaptations remain inspectable.
    for name in ['s1_diffuse.py','s2_forward.py','s3_loss.py','s4_backward.py','s5_train.py']:
        rel = 'skilltrain/workflows/' + name
        if sha(within(root, rel)) != spec.get('workflow_sha256', {}).get(rel):
            raise ValueError('Official workflow changed: ' + rel)
    return root, spec

def export_run(workspace, checkout, run, source_work, adapter_spec=None):
    w = Path(workspace).resolve(); root, spec = checked_checkout(checkout, adapter_spec)
    run = Path(run).resolve(); work = Path(source_work).resolve()
    source = read(work / 'ac-source.json')
    packet = w / 'refine-logs/experience/learning-packet.json'
    if source.get('source_packet_sha256') != sha(packet):
        raise ValueError('Training work does not match this source packet')
    # Bind the actual source material, not just a declared task name.
    for rel, expected in source.get('files', {}).items():
        if sha(within(work, rel)) != expected: raise ValueError('Source work changed: ' + rel)
    if not source.get('files'): raise ValueError('Source work needs file hashes')
    cfg = read(run/'config.json')
    if cfg.get('no_backward') or cfg.get('works') != [work.name]:
        raise ValueError('This is not a completed training run for the source work')
    if sha(run/'input'/f'{work.name}.md') != sha(work/'story.md'):
        raise ValueError('Corrupted task changed after training')
    schedule = (cfg.get('epochs'), cfg.get('steps'))
    if any(type(n) is not int or not 1 <= n <= 100 for n in schedule): raise ValueError('Invalid training schedule')
    receipts = {}
    for epoch in range(schedule[0]):
        for step in range(schedule[1]):
            relative = f'epoch_{epoch:02d}/step_{step:02d}/backward/g01/commit.txt'
            loss = run/'loss'/f'epoch_{epoch:02d}'/f'step_{step:02d}'/f'{work.name}.md'
            receipt = within(run,relative)
            if not receipt.is_file() or not loss.is_file() or not receipt.stat().st_size or not loss.stat().st_size:
                raise ValueError('Training is incomplete; a backward update or loss report is missing')
            receipts[relative] = sha(receipt)
    memory = run/'memory'
    top = subprocess.check_output(['git','-C',str(memory),'rev-parse','--show-toplevel'],text=True).strip()
    if Path(top).resolve() != memory.resolve(): raise ValueError('Memory must be its own repository')
    if subprocess.check_output(['git','-C',str(memory),'status','--porcelain'],text=True).strip():
        raise ValueError('Memory has uncommitted changes')
    count = int(subprocess.check_output(['git','-C',str(memory),'rev-list','--count','HEAD'],text=True))
    if count < 2: raise ValueError('No completed memory update')
    cards = [p for folder in FOLDERS for p in sorted((memory/folder).glob('*.md'))]
    if not cards or any(p.resolve().parent.parent != memory.resolve() for p in cards): raise ValueError('No bounded skill cards')
    text = '\n\n'.join(p.read_text(encoding='utf-8') for p in cards)
    if not 80 <= len(text.encode()) <= 24000: raise ValueError('Exported skill exceeds bounds')
    out = w/'refine-logs/experience'; out.mkdir(parents=True,exist_ok=True)
    (out/'SKILL.md').write_text(text,encoding='utf-8')
    manifest = {'method':'skill_training','upstream_commit':spec['upstream_commit'], 'adaptations':spec['adaptations'],
        'scope':spec.get('scope','domain_adapter'),
        'adapter_sha256':spec.get('adapter_sha256',{}),
        'workflow_sha256':spec['workflow_sha256'], 'memory_commit':subprocess.check_output(['git','-C',str(memory),'rev-parse','HEAD'],text=True).strip(),
        'source_packet_sha256':sha(packet),'config_sha256':sha(run/'config.json'), 'skill_sha256':sha(out/'SKILL.md'),
        'updates':receipts,'cards':{str(p.relative_to(memory)).replace('\\','/'):sha(p) for p in cards}}
    save(out/'official-run.json',manifest)
    return freeze(w,'skill_training',official_manifest='refine-logs/experience/official-run.json')

def train(w, c):
    if c.get('skill_training', {}).get('adapter') == 'protocol':
        from protocol_training import train as train_protocol
        return train_protocol(w, c)
    s = c['skill_training']; root, _ = checked_checkout(s['checkout'])
    work = Path(s['work']).resolve(); out = Path(w).resolve()/'refine-logs/experience/official-runs'
    # Validate the binding before any model call, including corrupting the work.
    if read(work/'ac-source.json')['source_packet_sha256'] != sha(Path(w)/'refine-logs/experience/learning-packet.json'):
        raise ValueError('Prepared work is for another source packet')
    timeout = s.get('timeout_seconds',7200); epochs = s.get('epochs',2)
    if type(epochs) is not int or not 1 <= epochs <= 4 or type(timeout) is not int or not 1 <= timeout <= 14400:
        raise ValueError('Training limits: 1-4 epochs and 1-14400 seconds')
    base = [s.get('python',sys.executable),'-m','skilltrain']
    model = ['--model',s['model']] if s.get('model') else []
    # Never re-diffuse an existing corruption: upstream resume retains the same
    # task, and all downstream comparisons must keep it frozen.
    if not (work/'story.md').exists():
        subprocess.run(base+['diffuse','--work',str(work),'--noise','heavy','--workers','1']+model,cwd=root,check=True,timeout=timeout)
    subprocess.run(base+['train','--work',str(work),'--runs-dir',str(out),'--run-id','research',
        '--steps','1','--episodes-per-step','1','--epochs',str(epochs),'--workers','1','--group-size','1']+model,cwd=root,check=True,timeout=timeout)
    return export_run(w,root,out/'research',work)

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--workspace',required=True); p.add_argument('--config')
    sub=p.add_subparsers(dest='action',required=True); sub.add_parser('train')
    a=sub.add_parser('import-run'); a.add_argument('--checkout',required=True); a.add_argument('--run',required=True); a.add_argument('--work',required=True)
    a=p.parse_args(); c=config(a.config)
    if not c.get('enabled',False): raise ValueError('Experience is off')
    try:
        result=train(a.workspace,c) if a.action=='train' else export_run(a.workspace,a.checkout,a.run,a.work)
    except (Exception, SystemExit):
        save(Path(a.workspace)/'refine-logs/experience/learning-status.json',
             {'status':'failed','method':'skill_training','reason':'Inspect local training log; no successful learning claimed.'})
        raise
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try: main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as e:
        print(f'skill-training: {e}',file=sys.stderr);sys.exit(2)
