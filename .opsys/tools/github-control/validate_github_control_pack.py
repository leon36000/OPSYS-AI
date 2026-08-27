#!/usr/bin/env python3
from __future__ import annotations
import csv,hashlib,json,re
try:
    from tools.common import PACK, EXPECTED_REPO, EXPECTED_OWNER, canonical_bytes, load_tasks, load_phases
except ImportError:
    from common import PACK, EXPECTED_REPO, EXPECTED_OWNER, canonical_bytes, load_tasks, load_phases
CAT=PACK/'github/catalog'
def jl(path):return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]
def markers(text):return re.findall(r'<!-- (OPSYS_(?:META|PHASE|TASK|DEFERRED_BUG)_ID:[^ ]+) -->',text)
def main()->int:
    errors=[];tasks=load_tasks();phases=load_phases();phase_records=jl(CAT/'phase-epics.jsonl');issues=jl(CAT/'task-issues.jsonl');bugs=jl(CAT/'deferred-bugs.jsonl')
    labels=json.loads((CAT/'labels.json').read_text(encoding='utf-8'));milestones=json.loads((CAT/'milestones.json').read_text(encoding='utf-8'))
    if (len(tasks),len(phases),len(phase_records),len(issues),len(bugs),len(labels),len(milestones))!=(148,25,25,148,12,51,25):errors.append('catalog counts invalid')
    tids={t['task_id'] for t in tasks};by_issue={x['key']:x for x in issues}
    for t in tasks:
        if t.get('repository_full_name')!=EXPECTED_REPO or t.get('required_owner_login')!=EXPECTED_OWNER:errors.append('repo drift '+t['task_id'])
        if t.get('ratification_policy')!='NONE':errors.append('construction ratification '+t['task_id'])
        rec=by_issue.get(t['task_id']);spec=hashlib.sha256(canonical_bytes(t)).hexdigest()
        if not rec or rec.get('spec_sha256')!=spec:errors.append('spec hash '+t['task_id'])
        if not all(d in tids for d in t['dependencies']):errors.append('unknown dep '+t['task_id'])
    if [t['task_id'] for t in tasks if t['initial_status']=='READY']!=['C00-001']:errors.append('initial READY invalid')
    if any(p.get('ratification_policy')!='NONE' for p in phases):errors.append('phase construction ratification remains')
    deps={t['task_id']:t['dependencies'] for t in tasks};temp=set();done=set()
    def visit(n):
        if n in temp:raise RuntimeError('cycle '+n)
        if n in done:return
        temp.add(n)
        for d in deps[n]:visit(d)
        temp.remove(n);done.add(n)
    try:
        for n in deps:visit(n)
    except Exception as e:errors.append(str(e))
    records=[{'key':'CORE-GITHUB-CONTROL','body_file':'github/issue-bodies/META-CORE-GITHUB-CONTROL.md','marker':'OPSYS_META_ID:CORE-GITHUB-CONTROL'}]+phase_records+issues+bugs
    seen=set()
    for rec in records:
        p=PACK/rec['body_file']
        if not p.is_file():errors.append('missing body '+rec['key']);continue
        text=p.read_text(encoding='utf-8');ms=markers(text)
        if ms!=[rec['marker']]:errors.append('marker '+rec['key'])
        if rec['marker'] in seen:errors.append('duplicate marker '+rec['marker'])
        seen.add(rec['marker'])
        h=hashlib.sha256(p.read_bytes()).hexdigest()
        if rec.get('body_sha256') and rec['body_sha256']!=h:errors.append('body hash '+rec['key'])
    rows=list(csv.DictReader((CAT/'issue-creation-manifest.csv').open(encoding='utf-8',newline='')))
    if len(rows)!=186 or len({r['key'] for r in rows})!=186:errors.append('issue creation manifest')
    active=list((PACK/'github/workflows').glob('*.yml'))+list((PACK/'github/workflows').glob('*.yaml'))
    if active:errors.append('active GitHub workflow shipped before C02-005')
    result={'ok':not errors,'errors':errors,'version':'2.3.0','repository':EXPECTED_REPO,'tasks':len(tasks),'phases':len(phases),'issues':len(records),'labels':len(labels),'milestones':len(milestones),'active_workflows':len(active)}
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if not errors else 1
if __name__=='__main__':raise SystemExit(main())
