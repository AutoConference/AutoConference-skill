"""Discovery, deliberate adoption and local retention. No public writes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode, quote
import experience as e


def library(c):
    return Path(c.get('library', e.ROOT / 'state/experience-library')).resolve()


def records(c):
    root = library(c)
    result = []
    for p in sorted(root.glob('*/record.json')):
        r = e.read(p)
        if r.get('status') == 'retired':
            continue
        card = e.within(root, r['id'] + '/SKILL.md')
        if e.sha(card) != r['skill_sha256']:
            raise ValueError('Local experience was edited without a new version')
        result.append(r)
    return result


def classify(w, domains):
    known = {d['id'] for d in e.read(e.ROOT/'research/extensions/domains.json')}
    if not isinstance(domains, list) or any(d not in known for d in domains):
        raise ValueError('Choose fields from the shared research taxonomy')
    out = {'domains': list(dict.fromkeys(domains))}
    e.save(Path(w)/'refine-logs/experience/domains.json', out)
    return out


def discover(w, c, query, domain=None):
    query = query.strip()
    if not 1 <= len(query) <= 120:
        raise ValueError('Use a short public topic (1-120 characters)')
    w = Path(w)
    known = {d['id'] for d in e.read(e.ROOT/'research/extensions/domains.json')}
    if domain is not None and domain not in known | {'unclassified'}: raise ValueError('Unknown research field')
    out = {'query': query, 'domain': domain, 'local': [], 'community': [], 'community_status': 'ok'}
    terms = query.casefold().split()
    task_id = hashlib.sha256(str(w.resolve()).encode()).hexdigest()
    for r in records(c):
        text = (r['title'] + ' ' + r['summary']).casefold()
        if r['source_task_id'] != task_id and any(t in text for t in terms):
            out['local'].append({k: r[k] for k in ('id', 'title', 'summary', 'status', 'method', 'skill_sha256')})
    out['local'] = out['local'][:10]
    try:
        response = e.api('GET', '/skills?' + urlencode({'q': query, 'page': 1, **({'domain':domain} if domain else {})}))
        out['community'] = response.get('skills', [])[:10]
        out['has_more'] = response.get('has_more', False)
    except (OSError, ValueError) as err:
        out['community_status'] = 'unavailable'
        out['error'] = str(err)[:300]
    e.save(w / 'refine-logs/experience/discovery.json', out)
    return out


def inspect(w, c, kind, identifier):
    import support
    discovery = support.load(w, 'refine-logs/experience/discovery.json')
    owner_request = kind == 'community' and support.requested(w, identifier)
    if kind not in ('local', 'community') or not (owner_request or any(x['id'] == identifier for x in discovery.get(kind, []))):
        raise ValueError('Inspect an item from this task\'s discovery first')
    if kind == 'local':
        root = library(c)
        r = e.read(e.within(root, identifier + '/record.json'))
        if r['status'] == 'retired': raise ValueError('Experience retired after an unsuccessful trial')
        path = e.within(root, identifier + '/SKILL.md')
        if e.sha(path) != r['skill_sha256']: raise ValueError('Local skill changed')
        text = path.read_text(encoding='utf-8')
        out = {**r, 'files': [{'path': 'SKILL.md', 'content': text}], 'feedback': r.get('last_trial')}
    else:
        out = e.api('GET', '/skills/' + quote(identifier, safe=''))
        e.validate_files(out['files'])
        if e.content_hash(out['files']) != out['content_hash']: raise ValueError('Community skill changed')
        support.check_request(w, identifier, out)
    # Keep one inspected candidate at a time. The exact version must survive adoption.
    e.save(Path(w) / 'refine-logs/experience/inspected.json', {'kind': kind, 'id': identifier, 'item': out})
    return out


def consider(w, c, kind, identifier, task, reason, run_key):
    w = Path(w)
    if not 20 <= len(reason) <= 2000: raise ValueError('Explain applicability and limits in 20-2000 characters')
    decision = {'kind': kind, 'id': identifier, 'task': task, 'reason': reason}
    old_path = w / 'refine-logs/experience/decision.json'
    if old_path.exists():
        if e.read(old_path) != decision: raise ValueError('Decision frozen; use a new workspace for another trial')
        return decision
    if kind != 'none':
        reviewed = e.read(w / 'refine-logs/experience/inspected.json')
        if (reviewed['kind'], reviewed['id']) != (kind, identifier): raise ValueError('Inspect this candidate before adoption')
        if kind == 'community':
            s = reviewed['item']
            import support
            support.check_request(w, identifier, s)
            e.select(w, identifier, task, run_key, expected=(s['version'], s['content_hash']))
        elif kind == 'local':
            s = inspect(w, c, kind, identifier)
            if s['source_task_id'] == hashlib.sha256(str(w.resolve()).encode()).hexdigest():
                raise ValueError('Do not train and evaluate on the same task')
            if (w / 'refine-logs/experience/selected.json').exists(): raise ValueError('One skill per task')
            e.save(w / 'refine-logs/experience/selected.json', {
                'kind': 'local', 'skill_id': identifier, 'content_hash': e.content_hash(s['files']),
                'files': s['files'], 'version': identifier, 'task': task, 'run_key': run_key,
                'source_task_id': s['source_task_id'], 'source_hashes': s['source_hashes'],
                'prior_feedback': [s['last_trial']] if s.get('last_trial') else [],
            })
        else: raise ValueError('Unknown experience source')
    elif (w / 'refine-logs/experience/selected.json').exists():
        raise ValueError('A skill is already pinned to this task')
    e.save(old_path, decision)
    return decision


def retain(w, c, title, summary):
    w = Path(w)
    if not 5 <= len(title.encode('utf-16-le'))//2 <= 120 or not 20 <= len(summary.encode('utf-16-le'))//2 <= 2000:
        raise ValueError('Supply a bounded title and applicability summary')
    candidate = e.read(w / 'refine-logs/experience/candidate.json')
    if e.read(w / 'refine-logs/experience/learning-status.json')['status'] == 'failed': raise ValueError('Latest learning failed')
    skill = e.within(w, candidate['skill'])
    if e.sha(skill) != candidate['skill_sha256']: raise ValueError('Candidate changed')
    if e.sha(w/'refine-logs/experience/learning-packet.json') != candidate['source_packet_sha256']: raise ValueError('Source changed')
    identifier = candidate['skill_sha256']
    dest = e.within(library(c), identifier)
    path = dest / 'record.json'
    if path.exists(): return e.read(path)  # Never overwrite validation/retirement on a retry.
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'SKILL.md').write_bytes(skill.read_bytes())
    record = {**candidate, 'id': identifier, 'title': title, 'summary': summary, 'status': 'provisional'}
    e.save(path, record)
    e.save(w / 'refine-logs/experience/retained.json', {'id': identifier})
    return record


def finalize(w, c):
    """Retire poor local candidates; send only opted-in private feedback."""
    w = Path(w)
    selected = w / 'refine-logs/experience/selected.json'
    comparison = w / 'refine-logs/experience/comparison.json'
    if not selected.exists() or not comparison.exists(): return {'status': 'no_trial', 'reason': 'No paired result; no benefit claimed'}
    s, trial = e.read(selected), e.read(comparison)
    if trial['evidence']['skill_sha256'] != s['content_hash']: raise ValueError('Feedback refers to another skill')
    result = {'status': trial['report']['outcome']}
    if s.get('kind') == 'local':
        path = e.within(library(c), s['skill_id'] + '/record.json')
        r = e.read(path)
        r['last_trial'] = trial['report']
        # Retired cards are retained on disk for inspection; no destructive rollback.
        r['status'] = 'retired' if result['status'] in ('worse', 'failed') else 'tested' if result['status'] == 'improved' else 'provisional'
        e.save(path, r)
    elif c.get('auto_report', False):
        result['private_feedback'] = e.api('PUT', '/skill-uses/' + quote(s['use_id'], safe=''), trial['report'])
    e.save(w / 'refine-logs/experience/trial-status.json', result)
    return result


def auto_draft(w, c):
    """Stage locally; uploading even a private draft is an independent owner setting."""
    w = Path(w)
    r = e.read(w / 'refine-logs/experience/retained.json')
    item = e.read(e.within(library(c), r['id'] + '/record.json'))
    out = {'status': 'local_draft', 'title': item['title'], 'summary': item['summary'], 'skill_sha256': item['skill_sha256']}
    if c.get('auto_draft', False):
        mine = e.api('GET', '/me/skill-share')
        if mine.get('draft_waiting') or mine.get('status') == 'draft':
            out['status'] = 'pending_draft_preserved'
        else:
            response = e.draft(w, item['title'], item['summary'], if_no_pending=True)
            out.update(status='private_draft', share_id=response.get('share_id'))
    e.save(w / 'refine-logs/experience/share-status.json', out)
    return out


def retain_auto(w, c):
    candidate = e.read(Path(w)/'refine-logs/experience/candidate.json')
    text = e.within(w,candidate['skill']).read_text(encoding='utf-8')
    descriptions = re.findall(r'^description:\s*(.+)$',text,re.M)
    title = (descriptions[0] if descriptions else 'Research experience from a completed experiment').encode('utf-16-le')[:240].decode('utf-16-le',errors='ignore')
    if len(title)<5: title='Research experience: '+title
    summary = 'Candidate research procedure. '+(' '.join(descriptions)[:1000] or 'Review applicability and test on a separate task before relying on it.')
    summary += ' Evidence comes from a source experiment; no general improvement is established.'
    summary = summary.encode('utf-16-le')[:4000].decode('utf-16-le',errors='ignore')
    return retain(w,c,title,summary)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', required=True); p.add_argument('--config')
    sub = p.add_subparsers(dest='action', required=True)
    a=sub.add_parser('discover'); a.add_argument('--query', required=True); a.add_argument('--domain')
    a=sub.add_parser('classify'); a.add_argument('--domains', nargs='*', default=[])
    a=sub.add_parser('inspect'); a.add_argument('--kind', choices=['local','community'],required=True); a.add_argument('--id',required=True)
    a=sub.add_parser('consider'); a.add_argument('--kind', choices=['local','community','none'],required=True); a.add_argument('--id',default=''); a.add_argument('--task',required=True); a.add_argument('--reason',required=True); a.add_argument('--run-key',default='research')
    a=sub.add_parser('retain'); a.add_argument('--title',required=True); a.add_argument('--summary',required=True)
    sub.add_parser('finalize'); sub.add_parser('draft'); sub.add_parser('retain-auto')
    a=p.parse_args(); c=e.config(a.config)
    if not c.get('enabled'): raise ValueError('Experience disabled')
    w=Path(a.workspace).resolve()
    if a.action=='discover': out=discover(w,c,a.query,a.domain)
    elif a.action=='classify': out=classify(w,a.domains)
    elif a.action=='inspect': out=inspect(w,c,a.kind,a.id)
    elif a.action=='consider': out=consider(w,c,a.kind,a.id,a.task,a.reason,a.run_key)
    elif a.action=='retain': out=retain(w,c,a.title,a.summary)
    elif a.action=='retain-auto': out=retain_auto(w,c)
    elif a.action=='draft': out=auto_draft(w,c)
    else: out=finalize(w,c)
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try: main()
    except (ValueError, OSError, KeyError) as err:
        print('experience lifecycle: '+str(err),file=sys.stderr);sys.exit(2)
