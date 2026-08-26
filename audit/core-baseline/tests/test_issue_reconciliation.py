"""C00-003 — Tests RED→GREEN pour la réconciliation des 54 issues et des 12
bugs produit reproduits."""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE))
import issue_reconciliation as ir
from issue_reconciliation import (
    IssueDisposition,
    DeferredModuleBug,
    DispositionInconnueRefusee,
    IssueNonBijectiveRefusee,
    BugProduitNonBijectifRefuse,
    SkeletonPromuEnBugCoreRefuse,
    SourceHorsConfinementRefusee,
    DISPOSITIONS_VALIDES,
    NB_ISSUES_ATTENDU,
    NB_BUGS_PRODUIT_ATTENDU,
    reconcilier,
    produire_sorties_reconciliation,
    _classer,
    _charger_issues,
    _charger_matrice,
    _charger_bugs_produit,
    _construire_reason,
)

import custody

# AUD-CORE-006 : le pack d'exécution Core est un artefact externe au dépôt,
# propre à chaque poste — aucun littéral de chemin hôte ici. Si OPSYS_PACK
# est absent ou pointe vers un dossier inexistant, ce module SKIPPE
# explicitement (jamais un pass silencieux) : un test qui ne peut pas
# mesurer doit se déclarer sauté, pas vert.
_OPSYS_PACK = os.environ.get("OPSYS_PACK")
if not _OPSYS_PACK or not Path(_OPSYS_PACK).is_dir():
    pytest.skip(
        "OPSYS_PACK non défini ou introuvable — définir "
        "OPSYS_PACK=/chemin/vers/OPSYS-AI-CORE-EXECUTION-PACK-vX.Y.Z-fusion "
        "(dossier existant) pour exécuter ces tests contre le pack réel.",
        allow_module_level=True,
    )
PACK_ROOT = Path(_OPSYS_PACK)


def _lire_id_squelette_reels() -> set[str]:
    """Les issue_id que la matrice source marque EXPECTED_SKELETON_OR_NOT_DUE
    — mesurés indépendamment par lecture directe de la matrice, jamais
    dérivés de la sortie du module testé (sinon le test s'auto-justifierait)."""
    with open(PACK_ROOT / ir.MATRICE_RECLASSIFICATION_RELATIVE, encoding="utf-8", newline="") as f:
        return {
            r["issue_id"] for r in csv.DictReader(f)
            if r["skeleton_stage_classification"] == "EXPECTED_SKELETON_OR_NOT_DUE"
        }


# ---------------------------------------------------------------------------
# 3 cas RED obligatoires (noms imposés par le Task Spec)
# ---------------------------------------------------------------------------


def test_r_concilier_les_54_issues_et_les_12_bugs_reproduits_1():
    """RED obligatoire : « 54 issues doivent avoir exactement une
    disposition ». Bijection stricte entre les 54 `ISS-CAND-*.json` et les
    54 lignes de `issue_to_work`, chaque disposition dans la liste blanche."""
    issue_to_work, _, _ = reconcilier(PACK_ROOT)
    assert len(issue_to_work) == NB_ISSUES_ATTENDU == 54

    ids_resultat = [d.issue_id for d in issue_to_work]
    assert len(set(ids_resultat)) == 54, "au moins un issue_id dupliqué — pas 'exactement une' disposition"

    ids_sources = {p.stem for p in (PACK_ROOT / ir.ISSUES_DIR_RELATIF).glob("ISS-CAND-*.json")}
    assert set(ids_resultat) == ids_sources, "le jeu d'issue_id du résultat ne couvre pas exactement les 54 fichiers sources"

    for d in issue_to_work:
        assert d.disposition in DISPOSITIONS_VALIDES, f"{d.issue_id} : disposition hors liste blanche {d.disposition!r}"


def test_r_concilier_les_54_issues_et_les_12_bugs_reproduits_2():
    """RED obligatoire : « 12 bugs produit doivent rester visibles ».
    Bijection stricte avec les 12 lignes de NOUVEAUX-CONSTATS-PRODUIT.csv —
    aucun perdu, aucun dupliqué, aucun inventé."""
    _, deferred_module_bugs, _ = reconcilier(PACK_ROOT)
    assert len(deferred_module_bugs) == NB_BUGS_PRODUIT_ATTENDU == 12

    ids_resultat = {b.bug_id for b in deferred_module_bugs}
    ids_attendus = {f"NEW-PROD-{i:03d}" for i in range(1, 13)}
    assert ids_resultat == ids_attendus, f"bugs manquants={ids_attendus - ids_resultat}, en trop={ids_resultat - ids_attendus}"

    # Chaque module métier annoncé par le forensique (§6.1) doit apparaître
    # au moins une fois — aucune famille de bug totalement éclipsée.
    modules_presents = {b.module for b in deferred_module_bugs}
    assert modules_presents == {"M5", "M6", "M7", "M9", "Tests/CI"}


def test_r_concilier_les_54_issues_et_les_12_bugs_reproduits_3():
    """RED obligatoire : « aucun EXPECTED_SKELETON ne doit être transformé en
    bug Core ». Vérifié sur les 12 issues réellement marquées
    EXPECTED_SKELETON_OR_NOT_DUE par la matrice source (mesurées ici de façon
    indépendante, pas depuis la sortie du module) ET sur les 6 candidats
    nommément documentés par ANALYSE-FORENSIQUE-CORRIGEE-SQUELETTE-FIRST-v2.md
    §5 (absences retirées comme preuves de dérive)."""
    issue_to_work, _, _ = reconcilier(PACK_ROOT)
    par_id = {d.issue_id: d for d in issue_to_work}

    attendues = _lire_id_squelette_reels()
    assert len(attendues) == 12, "la matrice source elle-même a changé de forme — pré-condition du test invalidée"
    for issue_id in attendues:
        assert par_id[issue_id].disposition == "EXPECTED_SKELETON", (
            f"{issue_id} est EXPECTED_SKELETON_OR_NOT_DUE en matrice mais "
            f"ressort {par_id[issue_id].disposition!r} — promotion refusée"
        )
        assert par_id[issue_id].disposition not in ("CORE_DUE", "PROOF_DUE"), issue_id

    # §5 nomme explicitement : Capability&Model Fabric (CA14-0001), Business
    # World Model (CA15-0001), Mémoire Long Terme (CA15-0002), persistance
    # des registres (CA10-0001), zéro-appelant des 10 modules (CA17-0001),
    # flux bout-en-bout absent (CA18-0001).
    for issue_id in (
        "ISS-CAND-CA14-0001", "ISS-CAND-CA15-0001", "ISS-CAND-CA15-0002",
        "ISS-CAND-CA10-0001", "ISS-CAND-CA17-0001", "ISS-CAND-CA18-0001",
    ):
        assert par_id[issue_id].disposition == "EXPECTED_SKELETON", issue_id


# ---------------------------------------------------------------------------
# IssueDisposition / DeferredModuleBug — gel + gardes à l'instanciation
# directe (pas seulement via reconcilier())
# ---------------------------------------------------------------------------


def test_issue_disposition_est_gelee():
    d = IssueDisposition("X", "CORE_DUE", "CA24", None, "motif")
    with pytest.raises(AttributeError):
        d.disposition = "PROOF_DUE"


def test_issue_disposition_instanciation_directe_est_aussi_gardee():
    """Une disposition hors liste blanche doit être refusée même en
    contournant reconcilier() — la garde vit dans __post_init__, pas
    seulement dans le chemin normal d'appel."""
    with pytest.raises(DispositionInconnueRefusee):
        IssueDisposition("X", "BUG_INVENTE_QUI_N_EXISTE_PAS", None, None, "motif")


def test_issue_disposition_refuse_issue_id_vide():
    with pytest.raises(ValueError):
        IssueDisposition("", "CORE_DUE", None, None, "motif")


def test_issue_disposition_refuse_reason_vide():
    with pytest.raises(ValueError):
        IssueDisposition("X", "CORE_DUE", None, None, "   ")


def test_issue_disposition_refuse_target_phase_non_str():
    with pytest.raises(TypeError):
        IssueDisposition("X", "CORE_DUE", 123, None, "motif")


def test_deferred_module_bug_est_gelee_et_gardee():
    b = DeferredModuleBug("NEW-PROD-001", "M5", "HIGH", "titre", "CONFIRMED_REPLAYED", "motif")
    with pytest.raises(AttributeError):
        b.module = "M6"
    with pytest.raises(ValueError):
        DeferredModuleBug("NEW-PROD-001", "", "HIGH", "titre", "CONFIRMED_REPLAYED", "motif")


# ---------------------------------------------------------------------------
# _classer — liste blanche stricte
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stade,attendu", [
    ("EXPECTED_SKELETON_OR_NOT_DUE", "EXPECTED_SKELETON"),
    ("AUDIT_OR_PROOF_DEFECT_UNCHANGED", "PROOF_DUE"),
    ("STAGE_INDEPENDENT_DEFECT_OR_DEBT", "CORE_DUE"),
    ("DUE_ARCHITECTURAL_DEBT", "CORE_DUE"),
    ("MIXED_SCOPE_REQUIRES_ATOMIC_SPLIT", "DECISION_REQUIRED"),
])
def test_classer_mappe_les_5_stades_connus(stade, attendu):
    assert _classer(stade, "CONFIRMED") == attendu


def test_classer_refuse_un_stade_inconnu():
    with pytest.raises(DispositionInconnueRefusee, match="STADE_JAMAIS_VU"):
        _classer("STADE_JAMAIS_VU", "CONFIRMED")


@pytest.mark.parametrize("stade", [
    "STAGE_INDEPENDENT_DEFECT_OR_DEBT", "AUDIT_OR_PROOF_DEFECT_UNCHANGED",
    "EXPECTED_SKELETON_OR_NOT_DUE", "DUE_ARCHITECTURAL_DEBT",
])
def test_classer_le_marqueur_decision_requise_gagne_toujours(stade):
    """CONFIRMED_DECISION_REQUIRED doit l'emporter sur N'IMPORTE QUEL stade —
    reproduit le cas réel ISS-CAND-CA21-0001 (STAGE_INDEPENDENT_DEFECT_OR_DEBT
    + CONFIRMED_DECISION_REQUIRED -> DECISION_REQUIRED, pas CORE_DUE)."""
    assert _classer(stade, "CONFIRMED_DECISION_REQUIRED") == "DECISION_REQUIRED"


def test_classer_le_marqueur_decision_requise_ne_masque_pas_un_stade_inconnu():
    """DeepSeek-V4-Pro, mineure, C00-003 tour 1 (mesurée fondée) : la version
    tour 1 retournait DECISION_REQUIRED pour un stade totalement inconnu dès
    lors que corrected_disposition portait CONFIRMED_DECISION_REQUIRED — la
    garde liste blanche du stade était contournée par l'override. Un stade
    jamais vu doit lever, MÊME avec le marqueur présent."""
    with pytest.raises(DispositionInconnueRefusee, match="STADE_JAMAIS_VU"):
        _classer("STADE_JAMAIS_VU", "CONFIRMED_DECISION_REQUIRED")


def test_classer_ca21_0001_reel_est_decision_required():
    """Cas réel exact : la LICENSE Apache vs décision T3 PROPRIÉTAIRE."""
    matrice = _charger_matrice(PACK_ROOT)
    ligne = next(r for r in matrice if r["issue_id"] == "ISS-CAND-CA21-0001")
    assert ligne["skeleton_stage_classification"] == "STAGE_INDEPENDENT_DEFECT_OR_DEBT"
    assert ligne["corrected_disposition"] == "CONFIRMED_DECISION_REQUIRED"
    assert _classer(ligne["skeleton_stage_classification"], ligne["corrected_disposition"]) == "DECISION_REQUIRED"


# ---------------------------------------------------------------------------
# Garde indépendante SkeletonPromuEnBugCoreRefuse — preuve par mutation du
# mapping (monkeypatch, restauré automatiquement par pytest après le test)
# ---------------------------------------------------------------------------


def test_garde_skeleton_promu_mord_si_le_mapping_est_corrompu(monkeypatch):
    """Preuve que `_verifier_aucun_skeleton_promu` est une garde
    INDÉPENDANTE de `_classer` : on corrompt le mapping pour qu'il route
    EXPECTED_SKELETON_OR_NOT_DUE vers CORE_DUE (exactement le défaut que le
    cas RED 3 interdit), et on exige un rouge NOMMÉ (pas un plantage
    générique)."""
    monkeypatch.setitem(ir._MAPPING_STADE_VERS_DISPOSITION, "EXPECTED_SKELETON_OR_NOT_DUE", "CORE_DUE")
    with pytest.raises(SkeletonPromuEnBugCoreRefuse, match="EXPECTED_SKELETON_OR_NOT_DUE"):
        reconcilier(PACK_ROOT)


# ---------------------------------------------------------------------------
# reconcilier() bout en bout — sur les vraies sources
# ---------------------------------------------------------------------------


def test_reconcilier_unresolved_questions_est_le_sous_ensemble_exact():
    issue_to_work, _, unresolved_questions = reconcilier(PACK_ROOT)
    attendu = {d.issue_id for d in issue_to_work if d.disposition == "DECISION_REQUIRED"}
    assert {d.issue_id for d in unresolved_questions} == attendu
    assert attendu == {
        "ISS-CAND-CA21-0001", "ISS-CAND-CA07-0002",
        "ISS-CAND-CA21-0004", "ISS-CAND-CA21-0005",
    }


def test_reconcilier_est_deterministe():
    a = reconcilier(PACK_ROOT)
    b = reconcilier(PACK_ROOT)
    assert a == b


def test_reconcilier_target_phase_est_transcrit_verbatim():
    issue_to_work, _, _ = reconcilier(PACK_ROOT)
    par_id = {d.issue_id: d for d in issue_to_work}
    assert par_id["ISS-CAND-CA21-0001"].target_phase == "T3 — Nathan"
    assert par_id["ISS-CAND-CA00-0001"].target_phase == "CA02 (canon) puis CA21 (documentation) ou CA20 (release)"
    # target_task n'est jamais inventé : aucun identifiant de tâche concret
    # (phase C00-C24) n'est déductible des seules sources disponibles ici.
    assert all(d.target_task is None for d in issue_to_work)


def test_charger_matrice_tolere_un_champ_multiligne_cite(tmp_path):
    """`io.StringIO`, jamais `texte.splitlines()` : un champ CSV entre
    guillemets peut contenir un saut de ligne littéral — splitlines() le
    couperait avant que csv sache qu'il est cité, corrompant la ligne en 2.
    Reproduit ici avec un stage_reason multi-paragraphe."""
    faux_pack = tmp_path / "faux_pack5"
    (faux_pack / "sources/audit/matrices").mkdir(parents=True)
    contenu = (
        "candidate_id,issue_id,root_cause,audit_severity,title,reassessment,scope_note,"
        "skeleton_stage_classification,corrected_disposition,stage_reason,completion_priority\n"
        'CAND-X-0001,ISS-CAND-X-0001,CA-X,faible,t,CONFIRMED,note,'
        'STAGE_INDEPENDENT_DEFECT_OR_DEBT,CONFIRMED,"ligne 1\nligne 2",P1\n'
    )
    (faux_pack / ir.MATRICE_RECLASSIFICATION_RELATIVE).write_text(contenu, encoding="utf-8")
    lignes = _charger_matrice(faux_pack)
    assert len(lignes) == 1, "un champ multiligne cité a changé le nombre de lignes logiques"
    # Mesuré : splitlines() ne scinde pas la ligne logique en deux lignes
    # csv distinctes ici (csv.reader relit un item suivant sur quote non
    # fermée) — la corruption RÉELLE est plus sournoise : le \n littéral est
    # perdu silencieusement ('ligne 1ligne 2' au lieu de 'ligne 1\nligne 2'),
    # sans erreur ni changement de nombre de lignes. C'est PRÉCISÉMENT le
    # danger d'un splitlines() prématuré : aucun signal visible, contenu
    # altéré.
    assert lignes[0]["stage_reason"] == "ligne 1\nligne 2"


def test_construire_reason_concatene_la_reserve_quand_presente():
    assert _construire_reason("motif stade", "") == "motif stade"
    assert _construire_reason("motif stade", "une réserve") == "motif stade [réserve source : une réserve]"


# ---------------------------------------------------------------------------
# Confinement — refus de symlink (mêmes primitives que C00-001/C00-002)
# ---------------------------------------------------------------------------


def test_charger_issues_refuse_un_symlink(tmp_path):
    faux_pack = tmp_path / "faux_pack"
    (faux_pack / "sources" / "audit" / "issues").mkdir(parents=True)
    cible = tmp_path / "hors_perimetre.json"
    cible.write_text(json.dumps({"issue_id": "ISS-CAND-EVIL-0001"}), encoding="utf-8")
    lien = faux_pack / "sources" / "audit" / "issues" / "ISS-CAND-EVIL-0001.json"
    lien.symlink_to(cible)
    with pytest.raises(SourceHorsConfinementRefusee):
        _charger_issues(faux_pack)


def test_charger_matrice_refuse_un_symlink(tmp_path):
    faux_pack = tmp_path / "faux_pack2"
    (faux_pack / "sources" / "audit" / "matrices").mkdir(parents=True)
    cible = tmp_path / "hors_perimetre.csv"
    cible.write_text("a,b\n1,2\n", encoding="utf-8")
    lien = faux_pack / ir.MATRICE_RECLASSIFICATION_RELATIVE
    lien.symlink_to(cible)
    with pytest.raises(SourceHorsConfinementRefusee):
        _charger_matrice(faux_pack)


def test_produire_sorties_refuse_sortie_dir_symlinke(tmp_path):
    faux_worktree = tmp_path / "faux_worktree"
    faux_worktree.mkdir()
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    lien = faux_worktree / "sortie"
    lien.symlink_to(ailleurs)
    with pytest.raises(custody.EcritureViaSymlinkRefusee):
        produire_sorties_reconciliation(faux_worktree, lien, PACK_ROOT)


# ---------------------------------------------------------------------------
# Bijection — jeux de données synthétiques divergents (tmp_path)
# ---------------------------------------------------------------------------


def _ecrire_issue_json(chemin: Path, issue_id: str, **extra) -> None:
    base = {
        "issue_id": issue_id, "titre": "t", "cause_racine": "CA-X", "severite": "faible",
        "mesure": "m", "reserve": "", "reproduction": [], "renvoi": "CA99",
        "publication_github": "INTERDITE",
    }
    base.update(extra)
    chemin.write_text(json.dumps(base), encoding="utf-8")


def _ecrire_12_bugs_valides(chemin: Path) -> None:
    """Fixture bugs produit COMPLÈTE et valide (bijective avec
    ID_BUGS_PRODUIT_ATTENDUS) — isole les tests de bijection d'issues du
    garde-fou bugs produit, pour qu'un seul mécanisme soit exercé à la fois."""
    lignes = "\n".join(
        f"NEW-PROD-{i:03d},HIGH,M5,titre,evidence,impact,CONFIRMED_REPLAYED" for i in range(1, 13)
    )
    chemin.write_text("id,severity,module,title,evidence,impact,status\n" + lignes + "\n", encoding="utf-8")


def test_reconcilier_refuse_jeu_non_bijectif(tmp_path):
    """Une issue présente en JSON mais absente de la matrice (ou l'inverse)
    doit lever IssueNonBijectiveRefusee — jamais une reconciliation
    partielle silencieuse."""
    faux_pack = tmp_path / "faux_pack3"
    (faux_pack / ir.ISSUES_DIR_RELATIF).mkdir(parents=True)
    (faux_pack / "sources/audit/matrices").mkdir(parents=True)
    _ecrire_issue_json(faux_pack / ir.ISSUES_DIR_RELATIF / "ISS-CAND-X-0001.json", "ISS-CAND-X-0001")
    # La matrice ne contient PAS ISS-CAND-X-0001 — jeu non bijectif.
    (faux_pack / ir.MATRICE_RECLASSIFICATION_RELATIVE).write_text(
        "candidate_id,issue_id,root_cause,audit_severity,title,reassessment,scope_note,"
        "skeleton_stage_classification,corrected_disposition,stage_reason,completion_priority\n",
        encoding="utf-8",
    )
    _ecrire_12_bugs_valides(faux_pack / ir.BUGS_PRODUIT_RELATIF)
    with pytest.raises(IssueNonBijectiveRefusee, match="ISS-CAND-X-0001"):
        reconcilier(faux_pack)


def test_reconcilier_refuse_bugs_produit_incomplets(tmp_path):
    """11 bugs au lieu de 12 (un manquant) doit lever
    BugProduitNonBijectifRefuse — jamais une liste tronquée silencieuse."""
    faux_pack = tmp_path / "faux_pack4"
    (faux_pack / ir.ISSUES_DIR_RELATIF).mkdir(parents=True)
    (faux_pack / "sources/audit/matrices").mkdir(parents=True)
    _ecrire_issue_json(
        faux_pack / ir.ISSUES_DIR_RELATIF / "ISS-CAND-X-0001.json", "ISS-CAND-X-0001",
    )
    (faux_pack / ir.MATRICE_RECLASSIFICATION_RELATIVE).write_text(
        "candidate_id,issue_id,root_cause,audit_severity,title,reassessment,scope_note,"
        "skeleton_stage_classification,corrected_disposition,stage_reason,completion_priority\n"
        "CAND-X-0001,ISS-CAND-X-0001,CA-X,faible,t,CONFIRMED,note,"
        "STAGE_INDEPENDENT_DEFECT_OR_DEBT,CONFIRMED,motif,P1\n",
        encoding="utf-8",
    )
    lignes_bugs = "\n".join(
        f"NEW-PROD-{i:03d},HIGH,M5,titre,evidence,impact,CONFIRMED_REPLAYED" for i in range(1, 12)
    )  # 11 seulement
    (faux_pack / ir.BUGS_PRODUIT_RELATIF).write_text(
        "id,severity,module,title,evidence,impact,status\n" + lignes_bugs + "\n", encoding="utf-8",
    )
    with pytest.raises(BugProduitNonBijectifRefuse, match="NEW-PROD-012"):
        reconcilier(faux_pack)


# ---------------------------------------------------------------------------
# Sorties CSV réelles — comptes, en-têtes, round-trip
# ---------------------------------------------------------------------------


class TestProductionSorties:
    """Écrit RÉELLEMENT les 3 CSV dans le répertoire de sortie du worktree —
    même motif anti-auto-référence que C00-001/C00-002 (conftest.py)."""

    @pytest.fixture(autouse=True)
    def _produire(self):
        sortie_dir = Path(__file__).resolve().parent.parent
        self.itw, self.dmb, self.uq = produire_sorties_reconciliation(WORKTREE, sortie_dir, PACK_ROOT)
        self.sortie_dir = sortie_dir
        yield

    def test_issue_to_work_csv_54_lignes_bon_entete(self):
        with open(self.sortie_dir / "ISSUE-TO-WORK.csv", encoding="utf-8", newline="") as f:
            lecteur = csv.DictReader(f)
            assert lecteur.fieldnames == ["issue_id", "disposition", "target_phase", "target_task", "reason"]
            lignes = list(lecteur)
        assert len(lignes) == 54
        assert len({l["issue_id"] for l in lignes}) == 54

    def test_deferred_module_bugs_csv_12_lignes_bon_entete(self):
        with open(self.sortie_dir / "DEFERRED-MODULE-BUGS.csv", encoding="utf-8", newline="") as f:
            lecteur = csv.DictReader(f)
            assert lecteur.fieldnames == ["bug_id", "module", "severite", "titre", "statut", "reason"]
            lignes = list(lecteur)
        assert len(lignes) == 12
        assert {l["bug_id"] for l in lignes} == {f"NEW-PROD-{i:03d}" for i in range(1, 13)}

    def test_unresolved_questions_csv_4_lignes(self):
        with open(self.sortie_dir / "UNRESOLVED-QUESTIONS.csv", encoding="utf-8", newline="") as f:
            lignes = list(csv.DictReader(f))
        assert len(lignes) == 4
        assert {l["issue_id"] for l in lignes} == {
            "ISS-CAND-CA21-0001", "ISS-CAND-CA07-0002",
            "ISS-CAND-CA21-0004", "ISS-CAND-CA21-0005",
        }

    def test_csv_echappe_correctement_les_virgules_et_accents(self):
        """CA08-0002 porte une reason avec virgules ET accents dans sa
        source (« 63 familles de fonctions dupliquées... ») — round-trip
        exact exigé, pas de troncature au premier séparateur."""
        with open(self.sortie_dir / "ISSUE-TO-WORK.csv", encoding="utf-8", newline="") as f:
            lignes = {l["issue_id"]: l for l in csv.DictReader(f)}
        relue = lignes["ISS-CAND-CA08-0002"]["reason"]
        attendue = next(d.reason for d in self.itw if d.issue_id == "ISS-CAND-CA08-0002")
        assert relue == attendue
        assert "," in attendue or ";" in attendue  # pré-condition : le test porte bien sur un cas à virgule

    def test_sorties_sont_deterministes_octet_pour_octet(self, tmp_path):
        # racine de confinement = autre_dir elle-même (pas WORKTREE) : on ne
        # teste ici que le déterminisme du CONTENU, la garde de confinement
        # est déjà couverte par test_produire_sorties_refuse_sortie_dir_symlinke.
        autre_dir = tmp_path / "rejeu"
        autre_dir.mkdir()
        produire_sorties_reconciliation(autre_dir, autre_dir, PACK_ROOT)
        for nom in ("ISSUE-TO-WORK.csv", "DEFERRED-MODULE-BUGS.csv", "UNRESOLVED-QUESTIONS.csv"):
            assert (self.sortie_dir / nom).read_bytes() == (autre_dir / nom).read_bytes()
