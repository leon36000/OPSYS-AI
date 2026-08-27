#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess
try:
    from tools.common import EXPECTED_REPO, load_config, issue_map, inspect_repository
except ImportError:
    from common import EXPECTED_REPO, load_config, issue_map, inspect_repository

STATUS_LABELS={
    'backlog':'status:backlog','ready':'status:ready','blocked':'status:blocked',
    'in-progress':'status:in-progress','in-review':'status:in-review',
    'verified':'status:verified','closed':'status:verified','deferred':'status:deferred',
}

def run(argv):
    cp=subprocess.run(argv,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if cp.returncode: raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or 'commande GitHub échouée')
    return cp.stdout.strip()

def transition(task_id:str,status:str,comment:str|None=None)->dict:
    if status not in STATUS_LABELS: raise RuntimeError(f'statut inconnu: {status}')
    cfg=load_config(); inspect_repository(cfg,require_github=True)
    rec=issue_map().get(task_id)
    if not rec or not rec.get('number'): raise RuntimeError(f'issue absente pour {task_id}')
    n=str(rec['number'])
    raw=run(['gh','issue','view',n,'--repo',EXPECTED_REPO,'--json','labels,state,url'])
    issue=json.loads(raw); current=[x['name'] for x in issue.get('labels',[])]
    for label in [x for x in current if x.startswith('status:') and x!=STATUS_LABELS[status]]:
        run(['gh','issue','edit',n,'--repo',EXPECTED_REPO,'--remove-label',label])
    if STATUS_LABELS[status] not in current:
        run(['gh','issue','edit',n,'--repo',EXPECTED_REPO,'--add-label',STATUS_LABELS[status]])
    if comment: run(['gh','issue','comment',n,'--repo',EXPECTED_REPO,'--body',comment])
    if status=='closed' and issue.get('state')!='CLOSED': run(['gh','issue','close',n,'--repo',EXPECTED_REPO,'--reason','completed'])
    if status!='closed' and issue.get('state')=='CLOSED': run(['gh','issue','reopen',n,'--repo',EXPECTED_REPO])
    return {'task_id':task_id,'issue':int(n),'status':status,'url':issue.get('url')}

def main()->int:
    p=argparse.ArgumentParser();sp=p.add_subparsers(dest='cmd',required=True)
    x=sp.add_parser('transition');x.add_argument('task_id');x.add_argument('status');x.add_argument('--comment')
    a=p.parse_args(); print(json.dumps(transition(a.task_id,a.status,a.comment),ensure_ascii=False,indent=2));return 0
if __name__=='__main__': raise SystemExit(main())
