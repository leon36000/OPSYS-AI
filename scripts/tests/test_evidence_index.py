# Tests de scripts/evidence_index.py (R4-S11, issue #593) — la methode se teste elle-meme.
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/
SCRIPT = os.path.join(HERE, "evidence_index.py")

sys.path.insert(0, HERE)
import evidence_index as ei  # noqa: E402 — import après ajustement de sys.path, requis pour le résoudre


def run(args, cwd=None):
    return subprocess.run([sys.executable] + args, capture_output=True, text=True, cwd=cwd)


def _git(cwd, *args):
    r = subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, f"git {args} a échoué : {r.stderr}"
    return r.stdout


def _init_repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    # Dépôt jetable de test, pas le projet réel : neutralise localement le hook
    # GLOBAL (core.hooksPath, gitleaks + policy DOCS-DRIFT de CE dépôt) qui
    # s'appliquerait sinon à toute écriture ici. Override de config LOCALE,
    # jamais --no-verify (règle AGENTS.md : ne s'applique qu'aux commits réels).
    hooks_vides = tmp_path / ".empty-hooks-for-tests"
    hooks_vides.mkdir()
    _git(tmp_path, "config", "core.hooksPath", str(hooks_vides))
    sdir = tmp_path / "scripts"
    sdir.mkdir()
    shutil.copy(SCRIPT, sdir / "evidence_index.py")
    return tmp_path


def _commit_all(tmp_path, message):
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", message)
    return _git(tmp_path, "rev-parse", "HEAD").strip()


def _index_de(repo):
    return json.loads((repo / "docs" / "audit" / "evidence-link-index.json").read_text(encoding="utf-8"))


def _entree(repo, chemin):
    return {e["chemin"]: e for e in _index_de(repo)["entrees"]}[chemin]


# ---------------------------------------------------------------------------
# fonctions pures
# ---------------------------------------------------------------------------
def test_extract_hex_candidates_bornes_longueur():
    assert ei.extract_hex_candidates("abc123") == []             # 6 car. : trop court
    assert ei.extract_hex_candidates("abcdef1") == ["abcdef1"]     # 7 car. : borne basse OK
    s40 = "a" * 40
    assert ei.extract_hex_candidates(s40) == [s40]                # 40 car. : borne haute OK
    assert ei.extract_hex_candidates("a" * 41) == []               # 41 car. d'un seul tenant : rejeté


def test_extract_hex_candidates_ignore_la_prose_sans_hex():
    # "commit", "diff", "arbre" : aucun n'est un motif hexadécimal — 0 candidat,
    # exactement le risque de faux positif documenté par #591 sur les MOTS.
    assert ei.extract_hex_candidates("la revue porte sur le diff et l'arbre, cf. ce commit") == []


def test_groupe_bundle_rattache_les_sous_dossiers_collecteurs():
    assert ei.groupe_bundle("evidence/tasks/X/evidence.json") == "evidence/tasks/X"
    assert ei.groupe_bundle("evidence/tasks/X/reviews/a.json") == "evidence/tasks/X"
    assert ei.groupe_bundle("evidence/tasks/X/reviews-context/a.json") == "evidence/tasks/X"
    assert ei.groupe_bundle("registries/verdicts/G/raw/a.txt") == "registries/verdicts/G"
    assert ei.groupe_bundle("registries/modules.yaml") == "registries"


# ---------------------------------------------------------------------------
# bout-en-bout sur dépôt synthétique
# ---------------------------------------------------------------------------
def test_regression_citation_hors_sujet_non_retenue(tmp_path):
    """Régression du faux positif mesuré en session : un commit fourre-tout qui
    touche DEUX bundles et cite un hash sans rapport avec l'un d'eux ne doit
    JAMAIS produire de liaison PROUVE pour ce bundle (cas réel : commit
    fbe2c813b87f, cf. docstring de groupe_bundle)."""
    repo = _init_repo(tmp_path)
    (repo / "registries" / "verdicts" / "A").mkdir(parents=True)
    (repo / "registries" / "verdicts" / "B").mkdir(parents=True)
    (repo / "unrelated.txt").write_text("x")
    hash_sans_rapport = _commit_all(repo, "commit non lié, existe juste pour être cité en aparté")
    (repo / "registries" / "verdicts" / "A" / "v.json").write_text(json.dumps({"verdict": "APPROVE"}))
    (repo / "registries" / "verdicts" / "B" / "v.json").write_text(json.dumps({"verdict": "APPROVE"}))
    _commit_all(repo, f"fourre-tout touchant A et B ; mentionne en passant {hash_sans_rapport} sans rapport avec A ni B")

    r = run([str(repo / "scripts" / "evidence_index.py")], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    assert _entree(repo, "registries/verdicts/A/v.json")["statut"] == "NON_PROUVE"
    assert _entree(repo, "registries/verdicts/B/v.json")["statut"] == "NON_PROUVE"


def test_champ_explicite_base_verifie_et_base_inventee_rejetee(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "evidence" / "tasks" / "T1").mkdir(parents=True)
    base_reel = _commit_all(repo, "commit de base réel")
    (repo / "evidence" / "tasks" / "T1" / "evidence.json").write_text(
        json.dumps({"task_id": "T1", "base": f"origin/main @ {base_reel}"}))
    (repo / "evidence" / "tasks" / "T1" / "evidence-invente.json").write_text(
        json.dumps({"task_id": "T1bis", "base": "origin/main @ " + "f" * 40}))
    _commit_all(repo, "proof(T1): sceller, un vrai lien et un lien inventé")

    r = run([str(repo / "scripts" / "evidence_index.py")], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    assert _entree(repo, "evidence/tasks/T1/evidence.json")["statut"] == "PROUVE"
    assert _entree(repo, "evidence/tasks/T1/evidence-invente.json")["statut"] == "NON_PROUVE"


def test_export_diff_recalcule_compte_prompt_seul_ne_compte_jamais(tmp_path):
    repo = _init_repo(tmp_path)
    d = repo / "evidence" / "tasks" / "T2"
    d.mkdir(parents=True)
    (d / "full.diff").write_text("diff --git a b\n+x\n")
    (d / "prompt.txt").write_text("le prompt soumis aux voix")
    diff_sha = hashlib.sha256((d / "full.diff").read_bytes()).hexdigest()
    prompt_sha = hashlib.sha256((d / "prompt.txt").read_bytes()).hexdigest()
    (d / "evidence.json").write_text(json.dumps({
        "task_id": "T2", "code_diff_sha256": diff_sha,
        "preuves_jointes": {"full.diff": diff_sha, "prompt.txt": prompt_sha},
    }))
    d2 = repo / "evidence" / "tasks" / "T3"
    d2.mkdir(parents=True)
    (d2 / "prompt.txt").write_text("texte du prompt, seul export de ce bundle")
    prompt_sha_2 = hashlib.sha256((d2 / "prompt.txt").read_bytes()).hexdigest()
    (d2 / "evidence.json").write_text(json.dumps({
        "task_id": "T3", "preuves_jointes": {"prompt.txt": prompt_sha_2},
    }))
    _commit_all(repo, "proof(T2,T3): T2 a un export diff, T3 seulement un prompt")

    r = run([str(repo / "scripts" / "evidence_index.py")], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    e2 = _entree(repo, "evidence/tasks/T2/evidence.json")
    assert e2["statut"] == "PROUVE"
    assert "diff" in {l["type"] for l in e2["liaisons"] if l["verifie"] is True}
    e3 = _entree(repo, "evidence/tasks/T3/evidence.json")
    assert e3["statut"] == "NON_PROUVE", "un export de PROMPT seul ne doit jamais suffire (cf. #591 : scelle le prompt, pas le code)"


def test_exclusion_ext_aud_001_jamais_indexee(tmp_path):
    repo = _init_repo(tmp_path)
    d = repo / "evidence" / "tasks" / "EXT-AUD-001-A1-R12-CANDIDATE"
    d.mkdir(parents=True)
    (d / "evidence.json").write_text(json.dumps({"task_id": "R12"}))
    (repo / "evidence" / "tasks" / "AUTRE").mkdir(parents=True)
    (repo / "evidence" / "tasks" / "AUTRE" / "evidence.json").write_text(json.dumps({"task_id": "AUTRE"}))
    _commit_all(repo, "territoire PR #566 + un bundle normal")

    r = run([str(repo / "scripts" / "evidence_index.py")], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    chemins = {e["chemin"] for e in _index_de(repo)["entrees"]}
    assert not any(c.startswith("evidence/tasks/EXT-AUD-001-A1-R12-CANDIDATE/") for c in chemins)
    assert "evidence/tasks/AUTRE/evidence.json" in chemins


def test_check_flag_detecte_la_derive_puis_verifie_vert(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "registries").mkdir()
    (repo / "registries" / "modules.yaml").write_text("modules: []\n")
    _commit_all(repo, "init registre")

    assert run([str(repo / "scripts" / "evidence_index.py"), "--check"], cwd=str(repo)).returncode == 1
    assert run([str(repo / "scripts" / "evidence_index.py")], cwd=str(repo)).returncode == 0
    assert run([str(repo / "scripts" / "evidence_index.py"), "--check"], cwd=str(repo)).returncode == 0


def test_regression_check_reste_vert_apres_avoir_committe_lindex(tmp_path):
    """Régression du deuxième bug mesuré en session : `mesure_a_commit` ancré sur
    `git rev-parse HEAD` inclut, dès que ce commit existe, le commit qui ajoute
    l'index lui-même — un fichier ne peut pas contenir son propre hash. `--check`
    sortait ROUGE juste après le premier commit du PR, sur un dépôt pourtant
    propre. Le commit qui ajoute l'index ne doit PAS faire dériver --check, tant
    qu'il ne touche pas evidence/registries/Registres."""
    repo = _init_repo(tmp_path)
    (repo / "evidence" / "tasks" / "T5").mkdir(parents=True)
    (repo / "evidence" / "tasks" / "T5" / "evidence.json").write_text(json.dumps({"task_id": "T5"}))
    _commit_all(repo, "proof(T5): ajoute une entrée réelle au périmètre indexé")

    assert run([str(repo / "scripts" / "evidence_index.py")], cwd=str(repo)).returncode == 0
    # committer l'index généré (docs/audit/ uniquement à ce stade), comme le fait réellement le PR
    _commit_all(repo, "feat: committer l'index généré, ne touche pas evidence/registries/Registres")

    assert run([str(repo / "scripts" / "evidence_index.py"), "--check"], cwd=str(repo)).returncode == 0, (
        "committer l'index ne doit pas le faire dériver : ce commit ne touche pas "
        "evidence/registries/Registres"
    )


def test_regression_clone_superficiel_ne_fausse_pas_lancrage(tmp_path):
    """Régression d'un troisième bug mesuré en session, distinct des deux
    précédents : sur un clone à profondeur 1 (défaut d'`actions/checkout` sans
    `fetch-depth` explicite — la forme réelle du checkout CI, mesurée sur PR #596),
    `git log -1 --format=%H -- <pathspec>` peut rendre le commit de TÊTE même s'il
    ne touche PAS ce pathspec, au lieu de rien. Reproduit ici sur un cas minimal :
    un commit ajoute evidence/a.json, un second n'ajoute QUE scripts/marqueur.py.
    Un clone superficiel du second rend pourtant ce second commit pour
    `-- evidence`, qui ne le contient pas — `dernier_commit_perimetre()` aurait
    donc ancré l'index sur le mauvais commit, silencieusement (pas d'échec, un
    résultat qui a l'air correct)."""
    repo = _init_repo(tmp_path)
    (repo / "evidence").mkdir()
    (repo / "evidence" / "a.json").write_text("{}\n")
    ajout_evidence = _commit_all(repo, "ajoute evidence/a.json")
    (repo / "scripts" / "marqueur.py").write_text("# ne touche pas evidence/\n")
    tip = _commit_all(repo, "ajoute scripts/marqueur.py, ne touche pas evidence/")

    clone = tmp_path / "clone-superficiel"
    r = subprocess.run(
        ["git", "clone", "--depth", "1", "--no-local", f"file://{repo}", str(clone)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    est_superficiel = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"], cwd=str(clone),
        capture_output=True, text=True,
    ).stdout.strip()
    assert est_superficiel == "true", "clone pas superficiel -- fixture à revoir, le bug ne serait pas exercé"

    # Bug caractérisé AVANT correctif, sur CE clone précis (pas affirmé, mesuré) :
    # sans assurer_historique_complet(), git rend le tip au lieu de rien.
    brut = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", "evidence"], cwd=str(clone),
        capture_output=True, text=True,
    ).stdout.strip()
    assert brut == tip, "le bug attendu ne s'est pas reproduit sur ce clone -- fixture à revoir"

    r = run([str(clone / "scripts" / "evidence_index.py")], cwd=str(clone))
    assert r.returncode == 0, r.stderr
    idx = _index_de(clone)
    assert idx["mesure_a_commit"] == ajout_evidence, (
        f"ancré sur {idx['mesure_a_commit']!r} au lieu du vrai dernier commit du "
        f"périmètre ({ajout_evidence!r}) — le correctif clone superficiel n'a pas fermé le cas"
    )
    assert run([str(clone / "scripts" / "evidence_index.py"), "--check"], cwd=str(clone)).returncode == 0


def test_regeneration_idempotente_a_etat_de_depot_inchange(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "evidence" / "tasks" / "T4").mkdir(parents=True)
    (repo / "evidence" / "tasks" / "T4" / "evidence.json").write_text(json.dumps({"task_id": "T4"}))
    _commit_all(repo, "proof(T4)")
    run([str(repo / "scripts" / "evidence_index.py")], cwd=str(repo))
    j1 = (repo / "docs" / "audit" / "evidence-link-index.json").read_text()
    m1 = (repo / "docs" / "audit" / "EVIDENCE-LINK-INDEX.md").read_text()
    run([str(repo / "scripts" / "evidence_index.py")], cwd=str(repo))
    j2 = (repo / "docs" / "audit" / "evidence-link-index.json").read_text()
    m2 = (repo / "docs" / "audit" / "EVIDENCE-LINK-INDEX.md").read_text()
    assert j1 == j2, "régénérer sans changement de dépôt doit produire un JSON byte-identique"
    assert m1 == m2, "régénérer sans changement de dépôt doit produire un MD byte-identique"


# ---------------------------------------------------------------------------
# sur le VRAI dépôt : le comité doit déjà être le résultat d'une exécution du
# script (même convention que test_structure_lint_green_here)
# ---------------------------------------------------------------------------
def test_index_reel_est_a_jour():
    assert run([SCRIPT, "--check"]).returncode == 0


def test_index_reel_n_indexe_jamais_reviews_ni_le_territoire_pr566():
    idx = json.load(open(os.path.join(HERE, "..", "docs", "audit", "evidence-link-index.json"), encoding="utf-8"))
    chemins = [e["chemin"] for e in idx["entrees"]]
    assert not any(c.startswith("reviews/") for c in chemins)
    assert not any(c.startswith("evidence/tasks/EXT-AUD-001-A1-R12-CANDIDATE/") for c in chemins)


def test_index_reel_coherence_statut_liaisons():
    idx = json.load(open(os.path.join(HERE, "..", "docs", "audit", "evidence-link-index.json"), encoding="utf-8"))
    for e in idx["entrees"]:
        verifs_code = [l for l in e["liaisons"] if l.get("verifie") is True and l.get("type") in ei.CODE_LINK_TYPES]
        if e["statut"] == "PROUVE":
            assert verifs_code, f"{e['chemin']} PROUVE sans liaison vérifiée de type code"
        else:
            assert not verifs_code, f"{e['chemin']} NON_PROUVE mais porte une liaison vérifiée de type code"
            assert e.get("non_preuve_raison"), f"{e['chemin']} NON_PROUVE sans raison consignée"
