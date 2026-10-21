"""Same-run CI selector: fictitious events/results, no network or token."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / ".github/ci/selection_workflows.py"


def helper():
    assert HELPER.is_file(), "same-run workflow selection and gate validator are absent"
    spec = importlib.util.spec_from_file_location("ci_selection_owned", HELPER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def policy():
    return {
        "version": 1,
        "source_parent": "1" * 40,
        "workflows": {
            "core": {
                "fichier": "core.yml",
                "evenements": {
                    "push": {"branches": ["main", "claude/**"], "paths": ["core/**", "departments/**"]},
                    "pull_request": {"paths": ["core/**", "departments/**"]},
                },
            },
            "e2e_core": {
                "fichier": "e2e-core.yml",
                "evenements": {
                    "push": {"paths": ["core/**", "departments/**"]},
                    "pull_request": {"paths": ["core/**", "departments/**"]},
                },
            },
            "mobile": {
                "fichier": "mobile.yml",
                "evenements": {"push": {"paths": ["mobile/**"]}, "pull_request": {"paths": ["mobile/**"]}},
            },
            "installateur": {
                "fichier": "installateur.yml",
                "evenements": {"push": {"paths": ["install/**"]}, "pull_request": {"paths": ["install/**"]}},
            },
            "dependency_audit": {
                "fichier": "dependency-audit.yml",
                "evenements": {
                    "push": {"paths": ["core/package.json"]},
                    "pull_request": {"paths": ["core/package.json"]},
                },
            },
        },
    }


def needs(selection=None):
    outputs = selection or {name: "true" for name in policy()["workflows"]}
    return {
        name: {"result": "success", "outputs": outputs if name == "changements" else {}}
        for name in [
            "changements",
            "socle",
            "departement",
            "m03-preuves",
            "frontiere-postgresql",
            *policy()["workflows"],
        ]
    }


def test_backend_contract_selects_core_and_e2e_not_static_mobile():
    h = helper()
    assert h.selectionner_workflows(
        policy(), ["departments/m06-material-control/src/outils.py"], "pull_request", "main"
    ) == {"core": True, "e2e_core": True, "mobile": False, "installateur": False, "dependency_audit": False}


def test_core_red_mobile_green_cannot_make_required_gate_green():
    h = helper()
    n = needs()
    n["core"]["result"] = "failure"
    with pytest.raises(h.ErreurSelection):
        h.verifier_gates(n)


@pytest.mark.parametrize(
    "path,want",
    [
        ("docs/notice.md", set()),
        ("core/package.json", {"core", "e2e_core", "dependency_audit"}),
        ("mobile/src/a.ts", {"mobile"}),
        ("install/a.sh", {"installateur"}),
        (".github/ci/selection_workflows.py", set(policy()["workflows"])),
        (".github/workflows/ci.yml", set(policy()["workflows"])),
    ],
)
def test_real_path_membership_and_meta_changes(path, want):
    out = helper().selectionner_workflows(policy(), [path], "pull_request", "main")
    assert {k for k, v in out.items() if v} == want


@pytest.mark.parametrize(
    "pattern,path,want",
    [
        ("tests/test_*.py", "tests/test_a.py", True),
        ("tests/test_*.py", "tests/test_nested/a.py", False),
        ("core/**", "core/src/gateway/a.ts", True),
        ("core/**", "corex/a.ts", False),
        ("a/**/b", "a/b", True),
        ("a/**/b", "a/x/y/b", True),
    ],
)
def test_supported_globs_have_no_slash_star_approximation(pattern, path, want):
    p = policy()
    p["workflows"]["mobile"]["evenements"]["pull_request"]["paths"] = [pattern]
    assert helper().selectionner_workflows(p, [path], "pull_request", "main")["mobile"] is want


@pytest.mark.parametrize("pattern", ["!a/**", "a/?", "[ab]", "a/**b", "a/***", "a\\b"])
def test_unsupported_pattern_is_not_silently_approximated(pattern):
    p = policy()
    p["workflows"]["core"]["evenements"]["pull_request"]["paths"] = [pattern]
    h = helper()
    with pytest.raises(h.ErreurSelection):
        h.selectionner_workflows(p, ["a/b"], "pull_request", "main")


def test_push_branch_filter_is_actual_branch_not_latest_remote():
    h = helper()
    assert h.selectionner_workflows(policy(), ["core/a.ts"], "push", "claude/foo")["core"] is True
    assert h.selectionner_workflows(policy(), ["core/a.ts"], "push", "other")["core"] is False


@pytest.mark.parametrize("state", ["failure", "cancelled", "skipped", "neutral", "timed_out", "pending", "UNKNOWN"])
def test_applicable_call_requires_success(state):
    h = helper()
    n = needs()
    n["core"]["result"] = state
    with pytest.raises(h.ErreurSelection):
        h.verifier_gates(n)


def test_false_selection_requires_skipped_not_success():
    h = helper()
    n = needs()
    n["changements"]["outputs"]["mobile"] = "false"
    with pytest.raises(h.ErreurSelection):
        h.verifier_gates(n)
    n["mobile"]["result"] = "skipped"
    h.verifier_gates(n)


@pytest.mark.parametrize(
    "kind", ["missing-call", "extra", "unknown-output", "missing-output", "selector-red", "python-red"]
)
def test_unknown_needs_never_defaults_to_non_applicable(kind):
    h = helper()
    n = needs()
    if kind == "missing-call":
        del n["core"]
    if kind == "extra":
        n["unrelated"] = {"result": "success", "outputs": {}}
    if kind == "unknown-output":
        n["changements"]["outputs"]["core"] = "unknown"
    if kind == "missing-output":
        del n["changements"]["outputs"]["core"]
    if kind == "selector-red":
        n["changements"]["result"] = "failure"
    if kind == "python-red":
        n["socle"]["result"] = "failure"
    with pytest.raises(h.ErreurSelection):
        h.verifier_gates(n)


# Real local Git repositories; all files/events below are fictitious, no credentials/remotes.
def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def commit(repo, files, message):
    for path, body in files.items():
        p = repo / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    git(repo, "add", "--all")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "fictif@example.invalid")
    git(tmp_path, "config", "user.name", "FICTIF")
    base = commit(tmp_path, {"docs/base.md": "fictif"}, "base fictive")
    return tmp_path, base


def pull_request(repo, base, changed=None):
    git(repo, "checkout", "-q", "-b", "feature")
    head = commit(repo, changed or {"core/new.ts": "fictif"}, "PR fictive")
    git(repo, "checkout", "-q", "main")
    tip = commit(repo, {"mobile/main-only.ts": "fictif"}, "base avancée fictive")
    git(repo, "merge", "-q", "--no-ff", "feature", "-m", "merge fictif")
    merge = git(repo, "rev-parse", "HEAD")
    event = {
        "number": 42,
        "pull_request": {"head": {"sha": head, "ref": "feature"}, "base": {"sha": tip, "ref": "main"}},
    }
    return event, merge


def test_pr_three_points_ignores_new_base_files_and_binds_merge_parents(repository):
    repo, base = repository
    event, merge = pull_request(repo, base)
    s = helper().selection_git(repo, policy(), "pull_request", event, merge, "refs/pull/42/merge")
    assert s.mode == "diff_complet"
    assert s.nombre_chemins == 1
    assert s.applicables == {
        "core": True,
        "e2e_core": True,
        "mobile": False,
        "installateur": False,
        "dependency_audit": False,
    }


@pytest.mark.parametrize("kind", ["wrong-head", "wrong-base", "wrong-checkout", "wrong-ref", "unsafe-sha"])
def test_pr_context_drift_is_not_silently_rebound(repository, kind):
    repo, base = repository
    event, merge = pull_request(repo, base)
    ref = "refs/pull/42/merge"
    if kind == "wrong-head":
        event["pull_request"]["head"]["sha"] = base
    if kind == "wrong-base":
        event["pull_request"]["base"]["sha"] = base
    if kind == "wrong-checkout":
        merge = base
    if kind == "wrong-ref":
        ref = "refs/pull/43/merge"
    if kind == "unsafe-sha":
        event["pull_request"]["head"]["sha"] = "--output=/tmp/NEVER"
    h = helper()
    with pytest.raises(h.ErreurSelection):
        h.selection_git(repo, policy(), "pull_request", event, merge, ref)


def test_push_two_points_contains_both_names_of_rename(repository):
    repo, base = repository
    old = commit(repo, {"core/old.ts": "same fictif"}, "old fictif")
    (repo / "docs").mkdir(exist_ok=True)
    git(repo, "mv", "core/old.ts", "docs/new.md")
    git(repo, "commit", "-q", "-m", "rename fictif")
    head = git(repo, "rev-parse", "HEAD")
    s = helper().selection_git(
        repo, policy(), "push", {"before": old, "after": head, "ref": "refs/heads/main"}, head, "refs/heads/main"
    )
    assert s.nombre_chemins == 2
    assert s.applicables["core"] is True


@pytest.mark.parametrize("before", [None, "0" * 40, "f" * 40])
def test_absent_zero_or_unavailable_push_before_runs_everything(repository, before):
    repo, head = repository
    s = helper().selection_git(
        repo, policy(), "push", {"before": before, "after": head, "ref": "refs/heads/main"}, head, "refs/heads/main"
    )
    assert s.mode == "conservateur"
    assert set(s.applicables.values()) == {True}


def test_more_than_three_hundred_paths_are_not_cut_off(repository):
    repo, base = repository
    head = commit(
        repo, {**{f"docs/{i:04}.md": "fictif" for i in range(350)}, "tests/late.py": "fictif"}, "many fictive paths"
    )
    p = policy()
    p["workflows"]["core"]["evenements"]["push"]["paths"] = ["tests/**"]
    s = helper().selection_git(
        repo, p, "push", {"before": base, "after": head, "ref": "refs/heads/main"}, head, "refs/heads/main"
    )
    assert s.nombre_chemins == 351
    assert s.applicables["core"] is True


def test_selector_cli_writes_closed_outputs_without_token_or_event_contents(repository, tmp_path):
    repo, base = repository
    head = commit(repo, {"mobile/new.ts": "fictif"}, "mobile fictif")
    event_path = tmp_path / "event.json"
    output = tmp_path / "output.txt"
    event_path.write_text(
        json.dumps(
            {"before": base, "after": head, "ref": "refs/heads/main", "private_unused": "SECRET-FICTIF-DO-NOT-PRINT"}
        )
    )
    env = {
        **os.environ,
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_EVENT_PATH": str(event_path),
        "GITHUB_SHA": head,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_OUTPUT": str(output),
        "GITHUB_TOKEN": "TOKEN-FICTIF-DO-NOT-PRINT",
    }
    p = subprocess.run([sys.executable, str(HELPER), "selection"], cwd=repo, env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert output.read_text().splitlines() == [
        "core=false",
        "e2e_core=false",
        "mobile=true",
        "installateur=false",
        "dependency_audit=false",
    ]
    assert "SECRET-FICTIF" not in p.stdout + p.stderr
    assert "TOKEN-FICTIF" not in p.stdout + p.stderr


def test_gates_cli_unknown_does_not_log_private_needs_body(tmp_path):
    n = needs()
    n["core"]["result"] = "PRIVATE-FICTIF-DO-NOT-PRINT"
    p = subprocess.run(
        [sys.executable, str(HELPER), "gates"],
        env={**os.environ, "NEEDS_JSON": json.dumps(n)},
        capture_output=True,
        text=True,
    )
    assert p.returncode == 1
    assert "PRIVATE-FICTIF" not in p.stdout + p.stderr


@pytest.mark.parametrize("value", [{"unknown": "SECRET-FICTIF"}, ["SECRET-FICTIF"], True, None, 1])
def test_malformed_output_value_has_closed_diagnostic(value):
    h = helper()
    n = needs()
    n["changements"]["outputs"]["core"] = value
    with pytest.raises(h.ErreurSelection):
        h.verifier_gates(n)


def test_duplicate_json_key_is_not_silently_overwritten(tmp_path):
    h = helper()
    path = tmp_path / "policy.json"
    path.write_text('{"version":1,"version":1}')
    with pytest.raises(h.ErreurSelection):
        h.lire_politique(path)


def test_output_io_failure_is_not_a_success(repository, tmp_path):
    repo, head = repository
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"before": None, "after": head, "ref": "refs/heads/main"}))
    p = subprocess.run(
        [sys.executable, str(HELPER), "selection", "--output-path", str(tmp_path / "missing" / "output")],
        cwd=repo,
        env={
            **os.environ,
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_EVENT_PATH": str(event_path),
            "GITHUB_SHA": head,
            "GITHUB_REF": "refs/heads/main",
        },
        capture_output=True,
        text=True,
    )
    assert p.returncode == 1
    assert "SORTIE_INDISPONIBLE" in p.stderr


def test_unavailable_pr_ancestor_selects_all_without_fetch(repository, monkeypatch):
    repo, base = repository
    event, merge = pull_request(repo, base)
    h = helper()
    original = h._git
    calls = []

    def reader(repo, args):
        calls.append(args)
        return None if args[0] == "merge-base" else original(repo, args)

    monkeypatch.setattr(h, "_git", reader)
    s = h.selection_git(repo, policy(), "pull_request", event, merge, "refs/pull/42/merge")
    assert s.mode == "conservateur" and set(s.applicables.values()) == {True}
    assert not any("fetch" in args for args in calls)


@pytest.mark.parametrize("kind", ["version-bool", "missing", "own-ci", "unknown-filter", "empty-patterns"])
def test_policy_unknown_schema_cannot_silently_skip_workflows(kind, tmp_path):
    h = helper()
    p = policy()
    if kind == "version-bool":
        p["version"] = True
    if kind == "missing":
        del p["workflows"]["mobile"]
    if kind == "own-ci":
        p["workflows"]["core"]["fichier"] = "ci.yml"
    if kind == "unknown-filter":
        p["workflows"]["core"]["evenements"]["push"]["paths-ignore"] = ["**"]
    if kind == "empty-patterns":
        p["workflows"]["core"]["evenements"]["push"]["paths"] = []
    path = tmp_path / "bad-policy.json"
    path.write_text(json.dumps(p))
    with pytest.raises(h.ErreurSelection):
        h.lire_politique(path)


@pytest.mark.parametrize("bad", ["{invalid", '{"changements":{},"changements":{}}', "[]", "null"])
def test_gates_cli_malformed_json_is_closed(bad):
    p = subprocess.run(
        [sys.executable, str(HELPER), "gates"], env={**os.environ, "NEEDS_JSON": bad}, capture_output=True, text=True
    )
    assert p.returncode == 1
    assert json.loads(p.stderr)["ok"] is False
    assert "Traceback" not in p.stderr


def test_diff_failure_selects_all_and_uses_read_only_git_flags(repository, monkeypatch):
    repo, base = repository
    head = commit(repo, {"docs/new.md": "fictif"}, "docs fictif")
    h = helper()
    original = h._git
    calls = []

    def reader(repo, args):
        calls.append(args)
        return None if args[0] == "diff" else original(repo, args)

    monkeypatch.setattr(h, "_git", reader)
    s = h.selection_git(
        repo, policy(), "push", {"before": base, "after": head, "ref": "refs/heads/main"}, head, "refs/heads/main"
    )
    assert s.mode == "conservateur" and set(s.applicables.values()) == {True}
    diff = next(a for a in calls if a[0] == "diff")
    assert {"--no-ext-diff", "--no-textconv", "--no-renames", "-z"} <= set(diff)


def test_secret_tokens_are_not_forwarded_to_local_git(repository, monkeypatch):
    repo, _ = repository
    h = helper()
    monkeypatch.setenv("GITHUB_TOKEN", "TOKEN-FICTIF")
    monkeypatch.setenv("GH_TOKEN", "TOKEN-FICTIF")
    original = h.subprocess.run
    observed = []

    def run(*args, **kwargs):
        observed.append(kwargs["env"])
        return original(*args, **kwargs)

    monkeypatch.setattr(h.subprocess, "run", run)
    assert h._git(repo, ["rev-parse", "HEAD"]) is not None
    forwarded = sorted(set(observed[0]) & {"GITHUB_TOKEN", "GH_TOKEN"})
    assert forwarded == []


@pytest.mark.parametrize(
    "bad", ["[" * 10000 + "]" * 10000, "NaN", "Infinity", "-Infinity"], ids=["deep", "nan", "inf", "minus-inf"]
)
def test_non_json_or_deep_json_has_closed_error_without_traceback(bad):
    p = subprocess.run(
        [sys.executable, str(HELPER), "gates"], env={**os.environ, "NEEDS_JSON": bad}, capture_output=True, text=True
    )
    assert p.returncode == 1
    assert "Traceback" not in p.stderr
    assert json.loads(p.stderr)["ok"] is False


def test_nonfinite_unused_output_is_not_valid_json_gate_evidence():
    n = needs()
    n["core"]["outputs"]["unused"] = float("nan")
    p = subprocess.run(
        [sys.executable, str(HELPER), "gates"],
        env={**os.environ, "NEEDS_JSON": json.dumps(n)},
        capture_output=True,
        text=True,
    )
    assert p.returncode == 1
    assert "Traceback" not in p.stderr
