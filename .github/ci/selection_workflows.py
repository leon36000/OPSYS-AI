"""Select same-run reusable workflows and reject incomplete required-gate evidence.

Runtime uses only the standard library. Git evidence is local, never a remote moving ref.
Unknown diff coverage selects every workflow; unknown checkout or gate authority refuses.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

LABELS = ("core", "e2e_core", "mobile", "installateur", "dependency_audit")
PYTHON_JOBS = ("socle", "departement", "m03-preuves", "frontiere-postgresql")
SHA = re.compile(r"[0-9a-f]{40}\Z")


class ErreurSelection(Exception):
    """Closed diagnostic codes, never exception bodies, event contents or credentials."""


def _objet_unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ErreurSelection("JSON_CLE_DUPLIQUEE")
        out[key] = value
    return out


def _constante_interdite(_value):
    raise ErreurSelection("JSON_CONSTANTE_INVALIDE")


def _json(text):
    try:
        return json.loads(text, object_pairs_hook=_objet_unique, parse_constant=_constante_interdite)
    except (ValueError, TypeError, RecursionError):
        raise ErreurSelection("JSON_INVALIDE") from None


def _ferme(value, keys):
    return type(value) is dict and set(value) == set(keys)


def _glob(pattern):
    if not isinstance(pattern, str) or not pattern or len(pattern) > 1024:
        raise ErreurSelection("FILTRE_INVALIDE")
    if re.search(r"[^A-Za-z0-9_./*\-]", pattern) or pattern.startswith("/"):
        raise ErreurSelection("FILTRE_NON_SUPPORTE")
    segments = pattern.split("/")
    if any(not s or s in {".", ".."} or ("**" in s and s != "**") for s in segments):
        raise ErreurSelection("FILTRE_NON_SUPPORTE")
    regex = ""
    for i, segment in enumerate(segments):
        if segment == "**":
            regex += ".*" if i == len(segments) - 1 else "(?:[^/]+/)*"
        else:
            regex += re.escape(segment).replace(r"\*", "[^/]*")
            if i < len(segments) - 1:
                regex += "/"
    return re.compile(regex + r"\Z", re.DOTALL)


def _valider_politique(policy):
    if not _ferme(policy, {"version", "source_parent", "workflows"}):
        raise ErreurSelection("POLITIQUE_INVALIDE")
    if type(policy["version"]) is not int or policy["version"] != 1:
        raise ErreurSelection("POLITIQUE_VERSION_INVALIDE")
    if not isinstance(policy["source_parent"], str) or not SHA.fullmatch(policy["source_parent"]):
        raise ErreurSelection("POLITIQUE_SOURCE_INVALIDE")
    if not _ferme(policy["workflows"], LABELS):
        raise ErreurSelection("POLITIQUE_WORKFLOWS_INVALIDE")
    for workflow in policy["workflows"].values():
        if not _ferme(workflow, {"fichier", "evenements"}):
            raise ErreurSelection("POLITIQUE_WORKFLOW_INVALIDE")
        file = workflow["fichier"]
        if not isinstance(file, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.ya?ml", file) or file == "ci.yml":
            raise ErreurSelection("POLITIQUE_CIBLE_INVALIDE")
        if not _ferme(workflow["evenements"], {"pull_request", "push"}):
            raise ErreurSelection("POLITIQUE_EVENEMENTS_INVALIDE")
        for filters in workflow["evenements"].values():
            if type(filters) is not dict or not {"paths"} <= set(filters) <= {"paths", "branches"}:
                raise ErreurSelection("POLITIQUE_FILTRES_INVALIDE")
            for patterns in filters.values():
                if type(patterns) is not list or not patterns:
                    raise ErreurSelection("POLITIQUE_FILTRES_INVALIDE")
                for pattern in patterns:
                    _glob(pattern)
    return policy


def lire_politique(path: Path):
    try:
        text = path.read_bytes()
    except OSError:
        raise ErreurSelection("POLITIQUE_INDISPONIBLE") from None
    if len(text) > 131072:
        raise ErreurSelection("POLITIQUE_TROP_VOLUMINEUSE")
    return _valider_politique(_json(text))


def selectionner_workflows(policy, chemins, event_name, branche):
    _valider_politique(policy)
    if event_name not in {"pull_request", "push"} or not isinstance(branche, str) or not branche:
        raise ErreurSelection("EVENEMENT_INVALIDE")
    if type(chemins) is not list or any(not isinstance(p, str) or not p for p in chemins):
        raise ErreurSelection("CHEMINS_INCONNUS")
    if any(p.startswith(".github/ci/") or p == ".github/workflows/ci.yml" for p in chemins):
        return dict.fromkeys(LABELS, True)
    result = {}
    for label, workflow in policy["workflows"].items():
        filters = workflow["evenements"][event_name]
        branch = "branches" not in filters or any(_glob(p).fullmatch(branche) for p in filters["branches"])
        result[label] = bool(branch and any(_glob(p).fullmatch(path) for p in filters["paths"] for path in chemins))
    return result


def verifier_gates(needs):
    if not _ferme(needs, {"changements", *PYTHON_JOBS, *LABELS}):
        raise ErreurSelection("GATES_BESOINS_INCOMPLETS")
    for job in needs.values():
        if not _ferme(job, {"outputs", "result"}) or type(job["outputs"]) is not dict:
            raise ErreurSelection("GATES_ETAT_INVALIDE")
    if any(needs[j]["result"] != "success" for j in ("changements", *PYTHON_JOBS)):
        raise ErreurSelection("GATES_PYTHON_OU_SELECTION_NON_REUSSIE")
    flags = needs["changements"]["outputs"]
    if not _ferme(flags, LABELS) or any(type(v) is not str or v not in {"true", "false"} for v in flags.values()):
        raise ErreurSelection("GATES_SELECTION_INCONNUE")
    for label in LABELS:
        expected = "success" if flags[label] == "true" else "skipped"
        if needs[label]["result"] != expected:
            raise ErreurSelection("GATES_WORKFLOW_NON_CONFORME")


# Git commands never use a shell, a remote moving ref, a diff driver or text conversion.
class Selection(NamedTuple):
    applicables: dict[str, bool]
    mode: str
    raison: str
    nombre_chemins: int | None


def _git(repo, args):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_") and k not in {"GITHUB_TOKEN", "GH_TOKEN", "ACTIONS_RUNTIME_TOKEN"}
    }
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_LAZY_FETCH": "1",
        }
    )
    try:
        result = subprocess.run(
            ["git", "--no-pager", *args], cwd=repo, env=env, capture_output=True, timeout=20, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _sha(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _conservateur(reason):
    return Selection(dict.fromkeys(LABELS, True), "conservateur", reason, None)


def selection_git(repo, policy, event_name, event, checkout_sha, ref):
    _valider_politique(policy)
    if not _sha(checkout_sha) or type(event) is not dict:
        raise ErreurSelection("CONTEXTE_INVALIDE")
    actual = _git(repo, ["rev-parse", "--verify", "HEAD"])
    if actual is None or actual.strip() != checkout_sha.encode():
        raise ErreurSelection("CHECKOUT_NON_CONFORME")
    if event_name == "pull_request":
        pr = event.get("pull_request")
        number = event.get("number")
        if type(pr) is not dict or type(number) is not int or number < 1 or ref != f"refs/pull/{number}/merge":
            raise ErreurSelection("PR_CONTEXTE_INVALIDE")
        head = pr.get("head")
        base = pr.get("base")
        if type(head) is not dict or type(base) is not dict or not _sha(head.get("sha")) or not _sha(base.get("sha")):
            raise ErreurSelection("PR_SHA_INVALIDE")
        parents = _git(repo, ["rev-list", "--parents", "-n", "1", checkout_sha])
        if parents is None or parents.split() != [checkout_sha.encode(), base["sha"].encode(), head["sha"].encode()]:
            raise ErreurSelection("PR_MERGE_NON_CONFORME")
        ancestors = _git(repo, ["merge-base", "--all", base["sha"], head["sha"]])
        if ancestors is None or len(ancestors.split()) != 1:
            return _conservateur("ANCESTRE_INCONNU")
        comparison = base["sha"] + "..." + head["sha"]
        branch = base.get("ref")
    elif event_name == "push":
        if (
            event.get("after") != checkout_sha
            or not isinstance(ref, str)
            or not ref.startswith("refs/heads/")
            or event.get("ref") != ref
        ):
            raise ErreurSelection("PUSH_CONTEXTE_INVALIDE")
        branch = ref.removeprefix("refs/heads/")
        before = event.get("before")
        if not _sha(before) or before == "0" * 40:
            return _conservateur("PUSH_AVANT_INCONNU")
        comparison = before + ".." + checkout_sha
    else:
        raise ErreurSelection("EVENEMENT_NON_SUPPORTE")
    if not isinstance(branch, str) or not branch:
        raise ErreurSelection("BRANCHE_INCONNUE")
    raw = _git(repo, ["diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", comparison, "--"])
    if raw is None:
        return _conservateur("DIFF_INCONNU")
    try:
        paths = raw.decode("utf-8").split("\0")
    except UnicodeDecodeError:
        return _conservateur("CHEMINS_NON_DECODABLES")
    if raw and paths[-1] != "":
        return _conservateur("DIFF_NON_COMPLET")
    paths = paths[:-1] if raw else []
    return Selection(selectionner_workflows(policy, paths, event_name, branch), "diff_complet", "GIT_LOCAL", len(paths))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["selection", "gates"])
    parser.add_argument("--output-path", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.mode == "gates":
            verifier_gates(_json(os.environ.get("NEEDS_JSON", "")))
            print(json.dumps({"ok": True, "mode": "gates"}))
        else:
            policy = lire_politique(Path(__file__).with_name("workflows-applicables.json"))
            event_path = os.environ.get("GITHUB_EVENT_PATH")
            if not event_path:
                raise ErreurSelection("EVENEMENT_INDISPONIBLE")
            try:
                raw_event = Path(event_path).read_bytes()
            except OSError:
                raise ErreurSelection("EVENEMENT_INDISPONIBLE") from None
            if len(raw_event) > 2097152:
                raise ErreurSelection("EVENEMENT_TROP_VOLUMINEUX")
            result = selection_git(
                Path.cwd(),
                policy,
                os.environ.get("GITHUB_EVENT_NAME"),
                _json(raw_event),
                os.environ.get("GITHUB_SHA"),
                os.environ.get("GITHUB_REF"),
            )
            output = args.output_path or (
                Path(os.environ["GITHUB_OUTPUT"]) if os.environ.get("GITHUB_OUTPUT") else None
            )
            if output is None:
                raise ErreurSelection("SORTIE_INDISPONIBLE")
            lines = "".join(f"{label}={'true' if result.applicables[label] else 'false'}\n" for label in LABELS)
            try:
                with output.open("a", encoding="utf-8") as stream:
                    stream.write(lines)
            except OSError:
                raise ErreurSelection("SORTIE_INDISPONIBLE") from None
            print(
                json.dumps(
                    {"ok": True, "mode": result.mode, "raison": result.raison, "nombre_chemins": result.nombre_chemins}
                )
            )
        return 0
    except ErreurSelection as exc:
        print(json.dumps({"ok": False, "code": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
