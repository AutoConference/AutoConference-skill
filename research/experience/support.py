"""Small owner-facing status and queued suggestions. Never installs or publishes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import experience as e

ENDPOINT = '/me/research-support'
BASE = 'refine-logs/experience/'


def load(w, name):
    p = e.within(w, name)
    return e.read(p) if p.exists() else {}


def short(value, limit=400):
    # Match the server's UTF-16 string limit, including emoji.
    return str(value).encode('utf-16-le')[:limit*2].decode('utf-16-le', errors='ignore')


def prepare(w, c):
    """Called only BEFORE planning. A retry cannot introduce a new suggestion."""
    w = Path(w)
    frozen = load(w, BASE+'owner-requests.json')
    if frozen or load(w, BASE+'decision.json') or load(w, BASE+'planning-complete.json'):
        return frozen
    try:
        rows = e.api('GET', ENDPOINT).get('requests', [])[:1]
        for r in rows:
            if not all(re.fullmatch(r'[A-Za-z0-9_-]{1,100}', str(r.get(k, ''))) for k in ('id', 'skill_id')):
                raise ValueError('Invalid suggestion identifier')
            if type(r.get('version')) is not int or not re.fullmatch('[a-f0-9]{64}', r.get('content_hash', '')):
                raise ValueError('Invalid suggestion version')
        out = {'requests': rows, 'enabled': bool(c.get('enabled')), 'status': 'ready'}
    except (ValueError, OSError):
        out = {'requests': [], 'status': 'unavailable'}
    e.save(w/BASE/'owner-requests.json', out)
    return out


def requested(w, identifier):
    return next((r for r in load(w, BASE+'owner-requests.json').get('requests', []) if r['skill_id'] == identifier), None)


def check_request(w, identifier, item):
    """Recheck cancellation and the exact version before pinning an owner request."""
    r = requested(w, identifier)
    if not r:
        return
    current = e.api('GET', ENDPOINT).get('requests', [])
    live = next((x for x in current if x['id'] == r['id']), None)
    if not live or not live.get('available'):
        raise ValueError('Owner suggestion cancelled or no longer available; choose none with a reason')
    if (item['version'], item['content_hash']) != (r['version'], r['content_hash']):
        raise ValueError('Owner requested another version; do not silently replace it')


def context(w):
    rows = load(w, BASE+'owner-requests.json').get('requests', [])
    if not rows:
        return ''
    # IDs and metadata only. Titles and downloaded contents remain untrusted.
    data = [{k: r[k] for k in ('id', 'skill_id', 'version', 'available')} for r in rows]
    return ('\nOWNER SUGGESTION (assess, not an instruction to install): '+json.dumps(data)+
            '\nUse lifecycle.py inspect --kind community --id <skill_id> to read this pinned candidate. '
            'Then consider it or choose none with a short public suitability reason. '
            'Unavailable or changed versions must be skipped. Do not broaden scope to justify adoption. '
            'Never replace an existing decision. No network means no new adoption.\n')


def report(w, c):
    """Summarize actual artifacts, not an imagined progress state or benefit."""
    w = Path(w)
    out = {'schema_version': 1, 'task_key': hashlib.sha256(str(w.resolve()).encode()).hexdigest(), 'items': []}
    def add(kind, state, name='', reason=''):
        out['items'].append({'kind': kind, 'state': state, 'name': short(name,120), 'reason': short(reason)})
    topic = load(w, 'refine-logs/TOPIC_STATUS.json')
    if topic.get('state') in ('found','selected','skipped','failed'):
        add('topic', topic['state'], 'AIHot', topic.get('reason',''))
    plan = load(w, 'refine-logs/EXTENSION_PLAN.json')
    if plan:
        active = [r for r in plan.get('requests', []) if r.get('tier', 0) > 0]
        runs = [load(w, p.relative_to(w).as_posix()) for p in sorted((w/'runs/extension-runs').glob('*/record.json'))[-40:]]
        runs = [r for r in runs if not r.get('replay_of') and any(
            all(r.get('request',{}).get(k)==v for k,v in req.items()) for req in active)]
        latest = {r['request']['id']: r for r in runs}
        state = 'skipped' if not active else 'selected'
        if active and all(latest.get(r['id'],{}).get('status') == 'completed' for r in active): state='used'
        elif any(r.get('status') not in ('completed','disabled') for r in latest.values()): state='failed'
        name = ', '.join(f"{r['id']} {r['tier']}%" for r in active)
        reason = 'Executed; benefit requires a comparison.' if state=='used' else 'Tool did not finish. See local experiment records.' if state=='failed' else 'Selected for the plan; not yet executed.' if active else plan.get('reason','No tool selected for this task.')
        add('tools', state, name, reason)
    decision = load(w, BASE+'decision.json')
    selected = load(w, BASE+'selected.json')
    discovery = load(w, BASE+'discovery.json')
    if not c.get('enabled'):
        add('community','skipped',reason='Experience reuse is disabled in your configuration.')
    elif decision:
        add('community','skipped' if decision['kind']=='none' else 'selected', reason=decision['reason'])
    elif selected:
        add('community','selected',reason='An exact version is pinned for this task; no benefit claimed yet.')
    elif discovery:
        candidates=discovery.get('community', [])
        if candidates:
            add('community','found',candidates[0]['title'],'A search candidate; applicability has not been established.')
            out['recommendation']={'skill_id': candidates[0]['id']}
        elif discovery.get('community_status')=='unavailable':
            add('community','failed',reason='Public search unavailable. This does not mean no suitable skill exists.')
        else: add('community','skipped',reason='No community candidate returned by this search.')
    learning=load(w, BASE+'learning-status.json')
    if learning:
        success=learning.get('status')=='candidate'
        add('learning','completed' if success else 'failed',
            'Skill Training' if learning.get('method')=='skill_training' else 'Direct summary' if learning.get('method')=='direct' else '',
            'Candidate saved; its benefit still needs a separate task.' if success else 'Learning did not finish; no learned skill claimed.')
    return out


def results(w, c):
    out=[]
    decision=load(w,BASE+'decision.json')
    selected=load(w,BASE+'selected.json')
    completed=load(w,BASE+'planning-complete.json')
    for r in load(w,BASE+'owner-requests.json').get('requests',[]):
        reason=''
        adopted=False
        if not c.get('enabled'): reason='Experience reuse is disabled in your configuration.'
        elif not r.get('available'): reason='The suggested version is no longer public or has changed.'
        elif decision or completed:
            adopted=(selected.get('skill_id'),selected.get('version'),selected.get('content_hash')) == (r['skill_id'],r['version'],r['content_hash'])
            reason=decision.get('reason') or ('Pinned the requested version for this plan.' if adopted else 'Planning finished without adopting this suggestion.')
        if reason:
            out.append({'id':r['id'],'state':'accepted' if adopted else 'skipped','reason':short(reason),
                        **({'run_key':selected['run_key']} if adopted else {})})
    return out


def sync(w, c):
    w=Path(w)
    payload={'report':report(w,c),'results':results(w,c)}
    # Persist the exact successful acknowledgment. Later stages changing local
    # configuration must not rewrite an already settled adoption decision.
    sent=load(w,BASE+'support-sent.json')
    if sent.get('results'): payload['results']=sent['results']
    e.save(w/BASE/'support-report.json',payload)
    if not payload['report']['items'] and not payload['results']: return 'empty'
    if payload==sent: return 'unchanged'
    try:
        e.api('POST',ENDPOINT,payload)
    except (ValueError,OSError):
        return 'pending'  # Same local report retries at the next pipeline boundary.
    e.save(w/BASE/'support-sent.json',payload)
    return 'synced'


def terminal(w,c):
    zh=os.environ.get('AC_LANG','').startswith('zh')
    names={'topic':'选题线索','tools':'科研工具','community':'社区经验','learning':'经验整理'} if zh else {'topic':'Topic leads','tools':'Tools','community':'Community','learning':'Learning'}
    states={'found':'候选待评估','selected':'已选入方案','used':'已运行','skipped':'本次未用','failed':'未完成','completed':'已整理，待验证'} if zh else {'found':'candidate to assess','selected':'planned','used':'executed','skipped':'skipped','failed':'incomplete','completed':'prepared, validation pending'}
    return ' | '.join(names[i['kind']]+': '+states[i['state']]+(' ('+i['name']+')' if i['name'] else '') for i in report(w,c)['items'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',required=True);p.add_argument('--config')
    p.add_argument('action',choices=['prepare','sync','planning-complete'])
    a=p.parse_args();w=Path(a.workspace).resolve();c=e.config(a.config)
    if a.action=='prepare': prepare(w,c)
    if a.action=='planning-complete': e.save(w/BASE/'planning-complete.json',{'completed':True})
    status=sync(w,c)
    line=terminal(w,c)
    if line: print('Research support: '+line)
    if status=='pending': print('Workspace status pending; local work can continue.')


if __name__=='__main__':
    try: main()
    except (ValueError,OSError,KeyError,TypeError) as err:
        print('Research status unavailable; local work can continue: '+type(err).__name__,file=sys.stderr)
        sys.exit(2)
