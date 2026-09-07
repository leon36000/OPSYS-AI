"""Contrats du mode de reçus sans trio ; fixtures synthétiques explicites."""
from __future__ import annotations
import hashlib
import importlib
import json
from pathlib import Path
import sys
import zlib
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
SOURCE = Path(__file__).resolve().parents[2] / 'scripts/proof_execution_receipts.py'
TASK = 'SONAR-DIAGNOSTICS-182'
HASH = 'a' * 64
FILES = (
    'scripts/sonar_diagnostics.py', 'scripts/tests/test_sonar_diagnostics.py',
    'core/scripts/verify_proof_sealed.py', 'core/scripts/proof_execution_receipts.py',
    'core/tests/bootstrap/test_proof_execution_receipts.py',
    'core/tests/bootstrap/test_proof_sealed.py',
)
TARGETS = {'exporter': (FILES[1], 112), 'policy': (FILES[4], 58), 'legacy': (FILES[5], 28)}

def subject():
    assert SOURCE.is_file(), 'Mode de preuve par reçus absent'
    return importlib.import_module('proof_execution_receipts')

def digest(data):
    return hashlib.sha256(data).hexdigest()

@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / 'repo'
    task = root / 'evidence/tasks' / TASK
    folder = task / 'execution'
    folder.mkdir(parents=True)
    inputs = {}
    for path in FILES:
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('fixture explicitement synthetique\n')
        inputs[path] = digest(file.read_bytes())
    manifest = {'task_id':TASK, 'code_diff_sha256':HASH, 'reviews':{},
                'proof_policy':'EXECUTION_RECEIPTS_V1',
                'execution':{'input_files':inputs, 'artifacts':{}}}
    for label,(target,count) in TARGETS.items():
        data = {'schema_version':1, 'code_diff_sha256':HASH, 'input_files':inputs,
                'argv':['-q','-p','no:cacheprovider',target], 'returncode':0,
                'collection_errors':0, 'deselected':0,
                'environment':{'python':'3.13.5','pytest':'9.0.2'},
                'events':[{'nodeid':target+'::test_fixture_'+str(i),'when':stage,'outcome':'passed'}
                          for i in range(count) for stage in ('setup','call','teardown')]}
        (folder / (label+'.json.zlib')).write_bytes(zlib.compress(json.dumps(data).encode()))
        (folder / (label+'.stdout.txt')).write_text('fixture stdout\n')
        (folder / (label+'.stderr.txt')).write_text('')
    def reseal():
        manifest['execution']['artifacts'] = {p.name:digest(p.read_bytes()) for p in folder.iterdir() if p.is_file()}
        return manifest
    reseal()
    return root, task, manifest, reseal

def verify(bundle):
    mod=subject();root,task,m,_=bundle
    return mod.verify_execution(TASK,root,task,m,HASH,set(FILES))

def alter(bundle,label,operation):
    path=bundle[1]/'execution'/(label+'.json.zlib')
    data=json.loads(zlib.decompress(path.read_bytes()));operation(data);path.write_bytes(zlib.compress(json.dumps(data).encode()));bundle[3]()

def test_valid_receipts_do_not_claim_review_or_reexecution(bundle):
    ok,report=verify(bundle)
    assert ok
    assert 'NOT_PERFORMED' in report and 'integrity' in report
    assert 'APPROVE' not in report

@pytest.mark.parametrize('label',list(TARGETS))
@pytest.mark.parametrize('field,value',[('returncode',1),('returncode',True),('collection_errors',1),('deselected',1),('schema_version',2)])
def test_failure_in_any_suite_refused(bundle,label,field,value):
    alter(bundle,label,lambda d:d.update({field:value}))
    assert not verify(bundle)[0]

@pytest.mark.parametrize('outcome',['failed','skipped','xfailed','xpassed','unknown'])
def test_non_passing_outcome_refused(bundle,outcome):
    alter(bundle,'exporter',lambda d:d['events'][1].update(outcome=outcome))
    assert not verify(bundle)[0]

@pytest.mark.parametrize('case',['empty','missing_teardown','duplicate','wrong_target','lower_count'])
def test_missing_or_duplicate_tests_refused(bundle,case):
    def change(d):
        if case=='empty': d['events']=[]
        elif case=='missing_teardown':d['events'].pop()
        elif case=='duplicate':d['events'].append(d['events'][0])
        elif case=='wrong_target':d['events'][0]['nodeid']='another::test'
        else:d['events']=d['events'][:-3]
    alter(bundle,'exporter',change)
    assert not verify(bundle)[0]

@pytest.mark.parametrize('kind',['source','test','receipt','stdout','stderr','input_omitted','artifact_omitted','extra_artifact','stale_diff','stale_input','extra_json_key','wrong_args'])
def test_tampering_and_staleness_refused(bundle,kind):
    root,task,m,reseal=bundle
    if kind in ('source','test'):(root/FILES[0 if kind=='source' else 1]).write_text('changed')
    elif kind in ('receipt','stdout','stderr'):
        filename={'receipt':'exporter.json.zlib','stdout':'exporter.stdout.txt','stderr':'exporter.stderr.txt'}[kind]
        with (task/'execution'/filename).open('a') as f:f.write('changed')
    elif kind=='input_omitted':m['execution']['input_files'].pop(FILES[0])
    elif kind=='artifact_omitted':m['execution']['artifacts'].pop('exporter.json.zlib')
    elif kind=='extra_artifact':(task/'execution'/'extra.json').write_text('{}');reseal()
    elif kind=='stale_diff':alter(bundle,'exporter',lambda d:d.update(code_diff_sha256='b'*64))
    elif kind=='stale_input':alter(bundle,'exporter',lambda d:d.update(input_files={}))
    elif kind=='extra_json_key':alter(bundle,'exporter',lambda d:d.update(quality_verified=True))
    elif kind=='wrong_args':alter(bundle,'exporter',lambda d:d.update(argv=['--ignore=all']))
    assert not verify(bundle)[0]

@pytest.mark.parametrize('kind',['task','mode','reviews','scope','absolute','traversal','symlink','dir_symlink','missing','oversized','duplicate_json'])
def test_scope_paths_and_schema_refused(bundle,kind):
    mod=subject();root,task,m,reseal=bundle
    paths=set(FILES);task_id=TASK
    if kind=='task':task_id='OTHER'
    elif kind=='mode':m['proof_policy']='BYPASS'
    elif kind=='reviews':m['reviews']={'ignored-reject.json':'c'*64}
    elif kind=='scope':paths.add('core/src/unrelated.py')
    elif kind in ('absolute','traversal'):m['execution']['input_files']['/etc/passwd' if kind=='absolute' else '../x']='c'*64
    elif kind=='symlink':
        file=root/FILES[0];file.unlink();file.symlink_to(root/FILES[1])
    elif kind=='dir_symlink':
        folder=task/'execution';folder.rename(task/'moved');folder.symlink_to(task/'moved',target_is_directory=True)
    elif kind=='missing':(task/'execution/exporter.json.zlib').unlink()
    elif kind=='oversized':(task/'execution/exporter.stdout.txt').write_bytes(b'x'*(2*1024*1024+1));reseal()
    else:
        file=task/'execution/exporter.json.zlib';file.write_bytes(zlib.compress(b'{"schema_version":1,"schema_version":1}'));reseal()
    ok,_=mod.verify_execution(task_id,root,task,m,HASH,paths)
    assert not ok

def test_receipt_is_never_executed(bundle):
    root,task,m,seal=bundle
    marker=root/'executed'
    alter(bundle,'exporter',lambda d:d.update(argv=['touch',str(marker)]))
    assert not verify(bundle)[0]
    assert not marker.exists()


def _git_fixture(root):
    import subprocess
    def run(*args):
        subprocess.run(['git',*args],cwd=root,check=True,capture_output=True)
    run('init','-q')
    run('config','user.name','Fixture')
    run('config','user.email','fixture@example.invalid')
    run('commit','--allow-empty','-qm','empty baseline')
    run('branch','origin/main')
    run('add','.')
    run('commit','-qm','synthetic evidence fixture')
    return run


def test_integration_new_mode_succeeds_without_review(bundle,monkeypatch):
    import verify_proof_sealed as gate
    root,task,m,_=bundle
    (task/'evidence.json').write_text(json.dumps(m))
    _git_fixture(root)
    monkeypatch.setattr(gate,'_REPO_ROOT',root)
    monkeypatch.setattr(gate,'_EVIDENCE_ROOT',root/'evidence/tasks')
    ok,report=gate.verifier_task(TASK,min_vendors_approve=3,diff_sha256_attendu=HASH)
    assert ok, report
    assert 'NOT_PERFORMED' in report


def test_integration_other_code_not_covered_by_receipts_refused(bundle,monkeypatch):
    import verify_proof_sealed as gate
    root,task,m,_=bundle
    (task/'evidence.json').write_text(json.dumps(m))
    run=_git_fixture(root)
    (root/'core/unrelated.py').write_text('print("unexpected")\n')
    run('add','.');run('commit','-qm','unrelated code')
    monkeypatch.setattr(gate,'_REPO_ROOT',root)
    monkeypatch.setattr(gate,'_EVIDENCE_ROOT',root/'evidence/tasks')
    assert not gate.verifier_task(TASK,min_vendors_approve=3,diff_sha256_attendu=HASH)[0]


def test_integration_legacy_still_requires_reviews(bundle,monkeypatch):
    import verify_proof_sealed as gate
    root,task,m,_=bundle
    m.pop('proof_policy')
    (task/'evidence.json').write_text(json.dumps(m))
    monkeypatch.setattr(gate,'_REPO_ROOT',root)
    monkeypatch.setattr(gate,'_EVIDENCE_ROOT',root/'evidence/tasks')
    ok,report=gate.verifier_task(TASK,min_vendors_approve=0,diff_sha256_attendu=HASH)
    assert not ok and 'aucun verdict' in report


@pytest.mark.parametrize('kind',['truncated','trailing','bomb','plain'])
def test_compressed_receipts_are_bounded_and_unambiguous(bundle,kind):
    path=bundle[1]/'execution/exporter.json.zlib'
    data=path.read_bytes()
    if kind=='truncated':data=data[:-1]
    elif kind=='trailing':data+=b'ignored'
    elif kind=='bomb':data=zlib.compress(b'x'*(2*1024*1024+1))
    else:data=b'{}'
    path.write_bytes(data);bundle[3]()
    assert not verify(bundle)[0]


def test_top_level_input_manifest_is_bound_independently(bundle):
    import copy
    root, task, manifest, _ = bundle
    # Change only the top-level declaration: all source bytes and nested
    # receipts remain valid, so no other guard can hide this discrepancy.
    manifest['execution']['input_files'] = copy.deepcopy(manifest['execution']['input_files'])
    manifest['execution']['input_files'][FILES[0]] = 'b' * 64
    assert not verify(bundle)[0]
