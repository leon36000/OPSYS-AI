#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess
from pathlib import Path
try:
    from tools.common import PACK, EXPECTED_REPO, EXPECTED_OWNER, write_json
    from tools.repo_guard import inspect
except ImportError:
    from common import PACK, EXPECTED_REPO, EXPECTED_OWNER, write_json
    from repo_guard import inspect

CAT=PACK/'github/catalog'; ISSUE_MAP=PACK/'execution/github/issue-map.json'
IDENTITY_PREFIXES=('OPSYS_META_ID:','OPSYS_PHASE_ID:','OPSYS_TASK_ID:','OPSYS_DEFERRED_BUG_ID:')
MANAGED_PREFIXES=('area:','type:','status:','risk:','review:','proof:','gate:','phase:','module:')

def jl(path): return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]
def run(argv,input_obj=None):
    cp=subprocess.run(argv,text=True,input=json.dumps(input_obj,ensure_ascii=False) if input_obj is not None else None,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if cp.returncode: raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or 'commande échouée: '+' '.join(argv))
    return cp.stdout.strip()
def api(method,path,payload=None):
    argv=['gh','api','-X',method,path]
    if payload is not None: argv+=['--input','-']
    out=run(argv,payload);return json.loads(out) if out else {}
def marker_lines(body):
    out=[]
    for line in (body or '').splitlines():
        if line.startswith('<!-- OPSYS_') and line.endswith(' -->'):
            value=line[5:-4].strip()
            if value.startswith(IDENTITY_PREFIXES): out.append(value)
    return out
def records():
    meta={'kind':'meta','key':'CORE-GITHUB-CONTROL','title':'[META] Initialiser le contrôle GitHub du Core OPSYS-AI','marker':'OPSYS_META_ID:CORE-GITHUB-CONTROL','labels':['opsys-ai','area:core','type:meta','status:ready','proof:required'],'milestone_key':None,'body_file':'github/issue-bodies/META-CORE-GITHUB-CONTROL.md'}
    return [meta]+jl(CAT/'phase-epics.jsonl')+jl(CAT/'task-issues.jsonl')+jl(CAT/'deferred-bugs.jsonl')
def existing_issues():
    pages=json.loads(run(['gh','api','--paginate','--slurp',f'repos/{EXPECTED_REPO}/issues?state=all&per_page=100']))
    return [x for page in pages for x in page if 'pull_request' not in x]
def marker_map(items):
    result={}
    for item in items:
        for marker in marker_lines(item.get('body','')):
            if marker in result: raise RuntimeError(f'BLOCKED_DUPLICATE_GITHUB_MARKER: {marker}')
            result[marker]=item
    return result
def label_name(x): return x.get('name') if isinstance(x,dict) else str(x)
def managed(name): return name=='opsys-ai' or name.startswith(MANAGED_PREFIXES)
def merge_labels(required,existing=None):
    if not existing:return list(dict.fromkeys(required))
    current=[label_name(x) for x in existing.get('labels',[])]
    statuses=[x for x in current if x.startswith('status:')]
    if len(statuses)>1: raise RuntimeError(f'BLOCKED_MULTIPLE_STATUS_LABELS: issue #{existing.get("number")} has {statuses}')
    merged=[x for x in required if not x.startswith('status:')]
    merged+=statuses or [x for x in required if x.startswith('status:')]
    merged += [x for x in current if not managed(x)]
    return list(dict.fromkeys(merged))
def ensure_labels(dry):
    labels=json.loads((CAT/'labels.json').read_text(encoding='utf-8'))
    if not dry:
        for x in labels: run(['gh','label','create',x['name'],'--repo',EXPECTED_REPO,'--color',x['color'],'--description',x['description'],'--force'])
    return len(labels)
def ensure_milestones(dry):
    milestones=json.loads((CAT/'milestones.json').read_text(encoding='utf-8'))
    current=[] if dry else api('GET',f'repos/{EXPECTED_REPO}/milestones?state=all&per_page=100')
    by={x['title']:x for x in current};result={}
    for m in milestones:
        if m['title'] in by: result[m['key']]=by[m['title']]['number']
        elif dry: result[m['key']]=None
        else: result[m['key']]=api('POST',f'repos/{EXPECTED_REPO}/milestones',{'title':m['title'],'description':m['description'],'state':'open'})['number']
    return result
def issue_payload(rec,milestones,body,existing=None):
    payload={'title':rec['title'],'body':body,'labels':merge_labels(rec['labels'],existing),'assignees':[EXPECTED_OWNER]}
    if rec.get('milestone_key') and milestones.get(rec['milestone_key']): payload['milestone']=milestones[rec['milestone_key']]
    return payload
def sync_one(rec,milestones,markers,dry):
    body=(PACK/rec['body_file']).read_text(encoding='utf-8');old=markers.get(rec['marker'])
    if dry:return {'number':old.get('number') if old else None,'action':'would_update' if old else 'would_create'}
    payload=issue_payload(rec,milestones,body,old)
    obj=api('PATCH',f'repos/{EXPECTED_REPO}/issues/{old["number"]}',payload) if old else api('POST',f'repos/{EXPECTED_REPO}/issues',payload)
    return {'number':obj['number'],'url':obj['html_url'],'action':'updated' if old else 'created'}
def render_task(rec,imap):
    body=(PACK/rec['body_file']).read_text(encoding='utf-8');deps=rec.get('dependencies',[])
    lines='Aucune' if not deps else '\n'.join(f'- #{imap[d]["number"]} — `{d}`' for d in deps)
    a,b=body.split('<!-- OPSYS_DEPENDENCIES_BEGIN -->',1);_,c=b.split('<!-- OPSYS_DEPENDENCIES_END -->',1)
    return a+'<!-- OPSYS_DEPENDENCIES_BEGIN -->\n'+lines+'\n<!-- OPSYS_DEPENDENCIES_END -->'+c
def render_phase(rec,imap,tasks):
    body=(PACK/rec['body_file']).read_text(encoding='utf-8')
    lines='\n'.join(f'- [ ] #{imap[t]["number"]} — `{t}` — {tasks[t]["title"].split("] ",1)[-1]}' for t in rec['task_ids'])
    a,b=body.split('<!-- OPSYS_PHASE_TASK_CHECKLIST_BEGIN -->',1);_,c=b.split('<!-- OPSYS_PHASE_TASK_CHECKLIST_END -->',1)
    return a+'<!-- OPSYS_PHASE_TASK_CHECKLIST_BEGIN -->\n'+lines+'\n<!-- OPSYS_PHASE_TASK_CHECKLIST_END -->'+c
def main()->int:
    p=argparse.ArgumentParser();sp=p.add_subparsers(dest='cmd',required=True)
    for n in ('preflight','plan','apply','verify'):
        x=sp.add_parser(n);x.add_argument('--repo-path')
    a=p.parse_args(); recs=records()
    if a.cmd=='plan':
        print(json.dumps({'version':'2.3.0','repository':EXPECTED_REPO,'owner':EXPECTED_OWNER,'issues_total':len(recs),'meta':1,'phases':25,'tasks':148,'deferred_bugs':12,'milestones':25,'labels':ensure_labels(True)},indent=2));return 0
    if not a.repo_path: raise SystemExit('--repo-path requis')
    print(json.dumps(inspect(Path(a.repo_path)),ensure_ascii=False,indent=2))
    if a.cmd=='preflight':return 0
    items=existing_issues();markers=marker_map(items)
    if a.cmd=='verify':
        missing=[r['marker'] for r in recs if r['marker'] not in markers]
        out={'ok':not missing,'missing':missing,'found':len(recs)-len(missing),'expected':len(recs)}
        print(json.dumps(out,ensure_ascii=False,indent=2));return 0 if out['ok'] else 1
    ensure_labels(False);milestones=ensure_milestones(False);imap={}
    for rec in recs: imap[rec['key']]=sync_one(rec,milestones,markers,False)
    tasks={x['key']:x for x in jl(CAT/'task-issues.jsonl')}
    phases={x['key']:x for x in jl(CAT/'phase-epics.jsonl')}
    for key,rec in tasks.items(): api('PATCH',f'repos/{EXPECTED_REPO}/issues/{imap[key]["number"]}',{'body':render_task(rec,imap)})
    for key,rec in phases.items(): api('PATCH',f'repos/{EXPECTED_REPO}/issues/{imap[key]["number"]}',{'body':render_phase(rec,imap,tasks)})
    write_json(ISSUE_MAP,{k:{'number':v['number'],'url':v.get('url'),'marker':next(r['marker'] for r in recs if r['key']==k)} for k,v in imap.items()})
    print(json.dumps({'ok':True,'repository':EXPECTED_REPO,'issues':len(imap),'issue_map':str(ISSUE_MAP)},ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
