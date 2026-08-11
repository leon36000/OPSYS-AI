"""Tests pour core/scripts/verify_proof_sealed.py (chantier CI-hardening,
remplace le placeholder BLOCKED du job CI `proof-sealed`, C02-005).

RÉVISION 2 — réécrit après revue scellée indépendante à 4 voix
(GPT-5.6-Terra-Pro, Muse-Spark-1.2, Qwen3.8-Max, Claude Opus 5 natif ;
3 REJECT/1 APPROVE-avec-réserves sur le mécanisme de revision 1). Les 4
ont trouvé, indépendamment, que la revision 1 ne liait jamais l'evidence
au code réellement modifié — n'importe quel evidence bundle valide
satisfaisait n'importe quel diff core/. Corrigé par un manifeste
cryptographique (code_diff_sha256 + reviews{nom:sha256}) ; les tests
ci-dessous couvrent maintenant CETTE liaison en positif ET en négatif
(cf. `test_verifier_task_echoue_si_code_diff_sha256_ne_correspond_pas`,
`test_verifier_task_echoue_si_verdict_supprime_apres_scellement`,
`test_verifier_task_echoue_si_verdict_ajoute_apres_scellement`).

Fixtures SYNTHÉTIQUES (tmp_path) — jamais le vrai evidence/tasks/ du
dépôt pour la logique de détection elle-même. `_diff_sha256_actuel` est
monkeypatché (jamais un vrai `git diff` sur des fixtures qui ne sont pas
de vrais commits) — la preuve d'intégration RÉELLE (git diff réel,
evidence réellement committée) est distincte, cf. Evidence Bundle du
chantier CI-hardening lui-même.

SCHÉMA DES FIXTURES : aligné sur la sortie RÉELLE de civ_review.py
(reviewer_model, objections[].severite en français) — vérifié contre
~/proof-method/scripts/civ_review.py et
reviews/TEMPLATE-prompt-revue-neutre.md, PAS un schéma inventé pour le
test (cf. discipline « donnée de test aveugle ne prouve rien »).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import verify_proof_sealed as vps  # noqa: E402

_DIFF_HASH_FICTIF = "diff" + "a" * 60  # 64 car., forme d'un sha256, jamais un vrai hash


def _verdict(
    *, reviewer_model: str, verdict: str, prompt_sha256: str, objections: list | None = None
) -> dict:
    return {
        "verdict": verdict,
        "objections": objections or [],
        "reviewer_model": reviewer_model,
        "modele_servi": reviewer_model,
        "prompt_sha256": prompt_sha256,
        "date_heure": "2026-08-11T00:00:00Z",
    }


def _ecrire_task(
    root: Path,
    task_id: str,
    *,
    verdicts: list[dict],
    evidence_json: dict | None | object = "auto",
    code_diff_sha256: str | None = _DIFF_HASH_FICTIF,
    manifeste_reviews: dict | None | object = "auto",
) -> Path:
    """`evidence_json="auto"` (défaut) construit un manifeste COHÉRENT
    (code_diff_sha256 + reviews{nom:sha256} exact) — les tests négatifs
    passent explicitement une valeur pour casser UN SEUL aspect à la
    fois. `evidence_json=None` n'écrit aucun fichier (cas "absent")."""
    dossier = root / "evidence" / "tasks" / task_id
    dossier.mkdir(parents=True)

    noms_fichiers = {}
    if verdicts:
        dossier_reviews = dossier / "reviews"
        dossier_reviews.mkdir()
        for v in verdicts:
            nom = f"{v['reviewer_model']}.json"
            contenu = json.dumps(v).encode("utf-8")
            (dossier_reviews / nom).write_bytes(contenu)
            noms_fichiers[nom] = hashlib.sha256(contenu).hexdigest()

    if manifeste_reviews == "auto":
        manifeste_reviews = noms_fichiers

    if evidence_json == "auto":
        evidence_json = {
            "task_id": task_id,
            "code_diff_sha256": code_diff_sha256,
            "reviews": manifeste_reviews,
        }

    if evidence_json is not None:
        (dossier / "evidence.json").write_text(json.dumps(evidence_json), encoding="utf-8")
    return dossier


def _avec_racine_et_diff_fictif(tmp_path, monkeypatch, *, diff_reel: str = _DIFF_HASH_FICTIF):
    monkeypatch.setattr(vps, "_EVIDENCE_ROOT", tmp_path / "evidence" / "tasks")
    monkeypatch.setattr(vps, "_diff_sha256_actuel", lambda base="origin/main": diff_reel)


# ---------------------------------------------------------------------------
# _vendor_of — dérivation vendor depuis reviewer_model
# ---------------------------------------------------------------------------


def test_vendor_of_modeles_connus():
    assert vps._vendor_of("gpt-5.6-terra-pro") == "openai"
    assert vps._vendor_of("qwen3.8-max") == "alibaba"
    assert vps._vendor_of("deepseek-v4-pro") == "deepseek"
    assert vps._vendor_of("glm52") == "zhipu"
    assert vps._vendor_of("memory-quality") == "zhipu"


def test_vendor_of_insensible_a_la_casse():
    assert vps._vendor_of("GPT-5.6-Terra-Pro") == vps._vendor_of("gpt-5.6-terra-pro")


def test_vendor_of_modele_inconnu_repli_sur_lui_meme():
    """Fail-closed sur l'inconnu : jamais fusionné à tort avec un vendor
    existant — un modèle absent du tableau reste son propre singleton."""
    assert vps._vendor_of("muse-spark-1.2") == "muse-spark-1.2"


# ---------------------------------------------------------------------------
# verifier_task — liaison cryptographique evidence <-> code (révision 2)
# ---------------------------------------------------------------------------


def test_verifier_task_ok_avec_sceau_diff_et_manifeste_coherents(tmp_path, monkeypatch):
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-001",
        verdicts=[_verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x")],
    )
    ok, rapport = vps.verifier_task("T-001", diff_sha256_attendu=_DIFF_HASH_FICTIF)
    assert ok, rapport


def test_verifier_task_echoue_si_evidence_json_absent(tmp_path, monkeypatch):
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    (tmp_path / "evidence" / "tasks" / "T-002").mkdir(parents=True)
    ok, rapport = vps.verifier_task("T-002", diff_sha256_attendu=_DIFF_HASH_FICTIF)
    assert not ok
    assert "evidence.json absent" in rapport


def test_verifier_task_echoue_si_code_diff_sha256_absent_du_manifeste(tmp_path, monkeypatch):
    """RÉGRESSION vers la faille de la revision 1 : evidence.json sans
    code_diff_sha256 du tout doit bloquer, jamais passer par défaut."""
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-002B",
        verdicts=[_verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x")],
        code_diff_sha256=None,
    )
    ok, rapport = vps.verifier_task("T-002B", diff_sha256_attendu=_DIFF_HASH_FICTIF)
    assert not ok
    assert "code_diff_sha256" in rapport


def test_verifier_task_echoue_si_code_diff_sha256_ne_correspond_pas(tmp_path, monkeypatch):
    """Cas CENTRAL trouvé par les 4 reviewers indépendants : une evidence
    valide mais dont le code_diff_sha256 déclaré NE correspond PAS au
    diff réel de la PR (evidence recyclée/sans rapport) doit bloquer."""
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch, diff_reel="diff" + "b" * 60)
    _ecrire_task(
        tmp_path,
        "T-003",
        verdicts=[_verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x")],
        code_diff_sha256=_DIFF_HASH_FICTIF,  # ne correspondra pas à "diff"+"b"*60
    )
    ok, rapport = vps.verifier_task("T-003", diff_sha256_attendu="diff" + "b" * 60)
    assert not ok
    assert "NE CORRESPOND PAS" in rapport


def test_verifier_task_echoue_si_verdict_supprime_apres_scellement(tmp_path, monkeypatch):
    """Trouvé par revue architecte : supprimer un verdict REJECT gênant
    APRÈS scellement, en laissant le manifeste evidence.json intact
    (donc en désaccord avec les fichiers réellement présents), doit
    bloquer — jamais un pass silencieux sur un dossier reviews/ appauvri."""
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    dossier = _ecrire_task(
        tmp_path,
        "T-004",
        verdicts=[
            _verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x"),
            _verdict(reviewer_model="gpt-5.6-terra-pro", verdict="REJECT", prompt_sha256="sha-x"),
        ],
    )
    # Suppression a posteriori du verdict REJECT gênant, SANS mettre à jour evidence.json.
    (dossier / "reviews" / "gpt-5.6-terra-pro.json").unlink()
    ok, rapport = vps.verifier_task("T-004", diff_sha256_attendu=_DIFF_HASH_FICTIF)
    assert not ok
    assert "ABSENT du disque" in rapport


def test_verifier_task_echoue_si_verdict_ajoute_apres_scellement(tmp_path, monkeypatch):
    """Symétrique : ajouter un FAUX verdict APPROVE après coup, sans
    qu'il soit déclaré dans le manifeste, doit aussi bloquer — sinon on
    pourrait gonfler artificiellement le nombre de vendors APPROVE."""
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    dossier = _ecrire_task(
        tmp_path,
        "T-005",
        verdicts=[_verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x")],
    )
    faux = _verdict(reviewer_model="qwen3.8-max", verdict="APPROVE", prompt_sha256="sha-x")
    (dossier / "reviews" / "qwen3.8-max.json").write_text(json.dumps(faux), encoding="utf-8")
    ok, rapport = vps.verifier_task("T-005", diff_sha256_attendu=_DIFF_HASH_FICTIF)
    assert not ok
    assert "NON déclaré" in rapport


def test_verifier_task_echoue_si_hash_verdict_altere_apres_scellement(tmp_path, monkeypatch):
    """Un verdict présent, déclaré, mais dont le CONTENU a changé après
    scellement (hash différent du manifeste) doit bloquer — détecte une
    altération, pas seulement un ajout/suppression."""
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    dossier = _ecrire_task(
        tmp_path,
        "T-006",
        verdicts=[_verdict(reviewer_model="deepseek-v4-pro", verdict="REJECT", prompt_sha256="sha-x")],
    )
    # Altération a posteriori : REJECT -> APPROVE, sans re-sceller.
    altere = _verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x")
    (dossier / "reviews" / "deepseek-v4-pro.json").write_text(json.dumps(altere), encoding="utf-8")
    ok, rapport = vps.verifier_task("T-006", diff_sha256_attendu=_DIFF_HASH_FICTIF)
    assert not ok
    assert "NE CORRESPOND PAS" in rapport


# ---------------------------------------------------------------------------
# verifier_task — cas déjà couverts en revision 1, réexprimés sur le nouveau schéma
# ---------------------------------------------------------------------------


def test_verifier_task_echoue_si_aucun_verdict(tmp_path, monkeypatch):
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    _ecrire_task(tmp_path, "T-007", verdicts=[], manifeste_reviews={})
    ok, rapport = vps.verifier_task("T-007", diff_sha256_attendu=_DIFF_HASH_FICTIF)
    assert not ok
    assert "aucun verdict" in rapport


def test_verifier_task_echoue_si_sceau_prompt_sha256_incoherent(tmp_path, monkeypatch):
    """Cas RED central : 2 verdicts prétendant approuver la MÊME tâche
    mais avec des prompt_sha256 DIFFÉRENTS — preuve qu'ils n'ont PAS vu
    le même pack byte-identique, sceau rompu."""
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-008",
        verdicts=[
            _verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-a"),
            _verdict(reviewer_model="gemini-3.1-pro", verdict="APPROVE", prompt_sha256="sha-b"),
        ],
    )
    ok, rapport = vps.verifier_task("T-008", diff_sha256_attendu=_DIFF_HASH_FICTIF)
    assert not ok
    assert "INCOHÉRENT" in rapport


def test_verifier_task_echoue_si_objection_critique_presente(tmp_path, monkeypatch):
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-009",
        verdicts=[
            _verdict(
                reviewer_model="deepseek-v4-pro",
                verdict="REJECT",
                prompt_sha256="sha-x",
                objections=[{"severite": "critique", "fichier": "x.py", "description": "faille réelle", "preuve": "L12"}],
            )
        ],
    )
    ok, rapport = vps.verifier_task("T-009", diff_sha256_attendu=_DIFF_HASH_FICTIF)
    assert not ok
    assert "CRITIQUE" in rapport


def test_verifier_task_echoue_si_objection_majeure_presente(tmp_path, monkeypatch):
    """Durci en révision 2 (3/4 reviewers) : "majeure" bloque désormais
    aussi, plus seulement surfacée en avertissement."""
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-010",
        verdicts=[
            _verdict(
                reviewer_model="deepseek-v4-pro",
                verdict="APPROVE",
                prompt_sha256="sha-x",
                objections=[{"severite": "majeure", "fichier": "x.py", "description": "à surveiller", "preuve": "L5"}],
            )
        ],
    )
    ok, rapport = vps.verifier_task("T-010", diff_sha256_attendu=_DIFF_HASH_FICTIF)
    assert not ok
    assert "MAJEURE" in rapport


def test_verifier_task_objection_mineure_ne_bloque_pas(tmp_path, monkeypatch):
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-011",
        verdicts=[
            _verdict(
                reviewer_model="deepseek-v4-pro",
                verdict="APPROVE",
                prompt_sha256="sha-x",
                objections=[{"severite": "mineure", "fichier": "x.py", "description": "style", "preuve": "L1"}],
            )
        ],
    )
    ok, rapport = vps.verifier_task("T-011", diff_sha256_attendu=_DIFF_HASH_FICTIF)
    assert ok, rapport


def test_verifier_task_echoue_si_un_seul_reject_meme_parmi_plusieurs_approve(tmp_path, monkeypatch):
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-012",
        verdicts=[
            _verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x"),
            _verdict(reviewer_model="gpt-5.6-terra-pro", verdict="REJECT", prompt_sha256="sha-x"),
        ],
    )
    ok, rapport = vps.verifier_task("T-012", diff_sha256_attendu=_DIFF_HASH_FICTIF)
    assert not ok
    assert "consensus non atteint" in rapport


def test_verifier_task_echoue_si_vendors_distincts_insuffisants(tmp_path, monkeypatch):
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path,
        "T-013",
        verdicts=[
            _verdict(reviewer_model="composer-2.5", verdict="APPROVE", prompt_sha256="sha-x"),
            _verdict(reviewer_model="grok-4.5", verdict="APPROVE", prompt_sha256="sha-x"),
        ],
    )
    ok, rapport = vps.verifier_task("T-013", min_vendors_approve=2, diff_sha256_attendu=_DIFF_HASH_FICTIF)
    assert not ok
    assert "insuffisant" in rapport


# ---------------------------------------------------------------------------
# main() — sélection des cibles, --min-vendors, --diff-base, options inconnues
# ---------------------------------------------------------------------------


def test_main_avec_task_explicite_ne_verifie_que_celle_la(tmp_path, monkeypatch):
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path, "T-OK",
        verdicts=[_verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x")],
    )
    _ecrire_task(tmp_path, "T-CASSEE", evidence_json=None, verdicts=[])
    rc = vps.main(["--task", "T-OK"])
    assert rc == 0


def test_main_sans_argument_verifie_tout_et_echoue_si_une_tache_cassee(tmp_path, monkeypatch):
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path, "T-OK2",
        verdicts=[_verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x")],
    )
    _ecrire_task(tmp_path, "T-CASSEE2", evidence_json=None, verdicts=[])
    rc = vps.main([])
    assert rc == 1


def test_main_task_id_absent_du_disque_echoue_explicitement(tmp_path, monkeypatch):
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    (tmp_path / "evidence" / "tasks").mkdir(parents=True)
    rc = vps.main(["--task", "T-FANTOME"])
    assert rc == 1


def test_main_evidence_root_absent_echoue_explicitement(tmp_path, monkeypatch):
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    rc = vps.main([])
    assert rc == 1


def test_main_min_vendors_propage_a_verifier_task(tmp_path, monkeypatch):
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    _ecrire_task(
        tmp_path, "T-MV",
        verdicts=[
            _verdict(reviewer_model="deepseek-v4-pro", verdict="APPROVE", prompt_sha256="sha-x"),
            _verdict(reviewer_model="gpt-5.6-terra-pro", verdict="APPROVE", prompt_sha256="sha-x"),
        ],
    )
    rc = vps.main(["--task", "T-MV", "--min-vendors", "3"])
    assert rc == 1


def test_main_option_inconnue_echoue_explicitement(tmp_path, monkeypatch):
    """Trouvé par revue architecte : la revision 1 ignorait silencieusement
    toute option inconnue (repli sur le seuil le plus permissif). --min-vendor
    (faute de frappe, singulier) doit maintenant échouer bruyamment, jamais
    retomber sur min_vendors=1 sans le dire."""
    _avec_racine_et_diff_fictif(tmp_path, monkeypatch)
    rc = vps.main(["--min-vendor", "3"])
    assert rc == 3


def test_main_emit_code_diff_sha256_seul(tmp_path, monkeypatch):
    """--emit-code-diff-sha256 imprime le hash et quitte, sans toucher à
    evidence/tasks/ (mode utilitaire pour peupler evidence.json)."""
    monkeypatch.setattr(vps, "_diff_sha256_actuel", lambda base="origin/main": _DIFF_HASH_FICTIF)
    rc = vps.main(["--emit-code-diff-sha256"])
    assert rc == 0


def test_diff_sha256_actuel_git_indisponible_echoue_explicitement(tmp_path, monkeypatch):
    monkeypatch.setattr(vps, "_REPO_ROOT", tmp_path)  # pas un repo git -> git diff échoue
    try:
        vps._diff_sha256_actuel(base="origin/main")
        raise AssertionError("devait lever GitIndisponible")
    except vps.GitIndisponible:
        pass


def test_diff_sha256_actuel_rejette_une_ref_commencant_par_un_tiret():
    """Trouvé par SonarCloud Code Analysis (Security Rating, "LLMs running
    this code with faulty CLI arguments can escape from shell sandboxes") :
    --diff-base est CLI-contrôlable et atteint subprocess.run comme un
    argument séparé — sans shell=True l'injection de COMMANDE est
    impossible, mais l'injection d'OPTION git (ex. --upload-pack=...) ne
    l'est pas. Fail-closed : tout ce qui commence par '-' est rejeté avant
    d'atteindre subprocess, jamais une liste noire de motifs spécifiques."""
    try:
        vps._diff_sha256_actuel(base="--upload-pack=/bin/sh")
        raise AssertionError("devait lever RefGitInvalide")
    except vps.RefGitInvalide as exc:
        assert "--upload-pack=/bin/sh" in str(exc)


def test_main_diff_base_dangereux_echoue_explicitement_pas_de_pass_silencieux():
    """Même garde, exercée via l'entrée CLI réelle (--emit-code-diff-sha256
    --diff-base <valeur dangereuse>) — pas seulement au niveau de la
    fonction interne."""
    rc = vps.main(["--emit-code-diff-sha256", "--diff-base", "--upload-pack=/bin/sh"])
    assert rc == 1
