#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,subprocess
from pathlib import Path
try:
    from tools.common import PACK, EXPECTED_OWNER, EXPECTED_REPO
    from tools.repo_guard import inspect
except ImportError:
    from common import PACK, EXPECTED_OWNER, EXPECTED_REPO
    from repo_guard import inspect
SPEC=PACK/'github/catalog/project-spec.json'
def run(argv):
    cp=subprocess.run(argv,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if cp.returncode: raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or 'commande échouée')
    return cp.stdout.strip()
def main()->int:
    p=argparse.ArgumentParser();sp=p.add_subparsers(dest='cmd',required=True)
    sp.add_parser('plan');x=sp.add_parser('apply');x.add_argument('--repo-path',required=True)
    a=p.parse_args();spec=json.loads(SPEC.read_text(encoding='utf-8'))
    if a.cmd=='plan':
        print(json.dumps({'version':'2.3.0','repository':EXPECTED_REPO,'owner':EXPECTED_OWNER,'title':spec['title'],'fields':len(spec['fields']),'views':len(spec['views']),'required':False},ensure_ascii=False,indent=2));return 0
    inspect(Path(a.repo_path));
    try:
        projects=json.loads(run(['gh','project','list','--owner',EXPECTED_OWNER,'--format','json','--limit','100'])).get('projects',[])
    except Exception as e:
        print(json.dumps({'status':'BLOCKED_PROJECT_SCOPE','reason':str(e),'issues_and_milestones_remain_authoritative':True},ensure_ascii=False,indent=2));return 2
    found=next((x for x in projects if x.get('title')==spec['title']),None)
    if not found:
        try: run(['gh','project','create','--owner',EXPECTED_OWNER,'--title',spec['title']])
        except Exception as e:
            print(json.dumps({'status':'BLOCKED_PROJECT_SCOPE','reason':str(e),'issues_and_milestones_remain_authoritative':True},ensure_ascii=False,indent=2));return 2
        projects=json.loads(run(['gh','project','list','--owner',EXPECTED_OWNER,'--format','json','--limit','100'])).get('projects',[])
        found=next(x for x in projects if x.get('title')==spec['title'])
    print(json.dumps({'status':'PROJECT_CREATED_OR_PRESENT','project':found,'field_spec':spec['fields'],'view_spec':spec['views'],'note':'Field/view creation must fail closed if gh lacks project scope; never create under another owner.'},ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
