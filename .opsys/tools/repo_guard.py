#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path
EXPECTED_REPO='leon36000/OPSYS-AI'
EXPECTED_OWNER='leon36000'

def normalize_remote(url:str)->str:
    u=url.strip()
    u=re.sub(r'\.git$','',u)
    if u.startswith('git@github.com:'): return u[len('git@github.com:'):]
    if u.startswith('ssh://git@github.com/'): return u[len('ssh://git@github.com/'):]
    if u.startswith('https://github.com/'): return u[len('https://github.com/'):]
    if u.startswith('http://github.com/'): return u[len('http://github.com/'):]
    return u

def run(argv,cwd=None):
    cp=subprocess.run(argv,cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if cp.returncode: raise RuntimeError(cp.stderr.strip() or 'command failed: '+' '.join(argv))
    return cp.stdout.strip()

def inspect(repo_path:Path)->dict:
    root=Path(run(['git','rev-parse','--show-toplevel'],repo_path)).resolve()
    if root!=repo_path.resolve(): raise RuntimeError(f'configured path {repo_path} != git root {root}')
    remote=run(['git','remote','get-url','origin'],repo_path)
    norm=normalize_remote(remote)
    if norm!=EXPECTED_REPO: raise RuntimeError(f'BLOCKED_WRONG_REPOSITORY: origin={norm} expected={EXPECTED_REPO}')
    login=run(['gh','api','user','--jq','.login'])
    if login!=EXPECTED_OWNER: raise RuntimeError(f'BLOCKED_GITHUB_ACCESS: login={login} expected={EXPECTED_OWNER}')
    info=json.loads(run(['gh','repo','view',EXPECTED_REPO,'--json','id,nameWithOwner,url,defaultBranchRef,visibility'],repo_path))
    if info.get('nameWithOwner')!=EXPECTED_REPO: raise RuntimeError('repository identity mismatch')
    return {'repository':info,'login':login,'origin':remote,'origin_normalized':norm,'root':str(root),'commit':run(['git','rev-parse','HEAD'],repo_path),'tree':run(['git','rev-parse','HEAD^{tree}'],repo_path),'branch':run(['git','branch','--show-current'],repo_path)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--repo-path',required=True);ap.add_argument('--receipt')
    a=ap.parse_args()
    try: obj=inspect(Path(a.repo_path))
    except Exception as e: print(str(e),file=sys.stderr);return 2
    text=json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n'
    if a.receipt: Path(a.receipt).write_text(text,encoding='utf-8')
    print(text,end='');return 0
if __name__=='__main__': raise SystemExit(main())
