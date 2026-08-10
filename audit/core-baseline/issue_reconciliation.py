"""C00-003 — Réconcilier les 54 issues candidates (`ISS-CAND-*.json`) et les
12 bugs produit reproduits (`NEW-PROD-*`, `NOUVEAUX-CONSTATS-PRODUIT.csv`) en
une disposition unique par issue. Aucune sévérité, aucune cause racine et
aucun routage n'est recalculé depuis une lecture libre : `disposition` est
dérivée d'un MAPPING EXPLICITE (liste blanche) depuis
`skeleton_stage_classification`/`corrected_disposition`, déjà produits par
l'audit dans `SKELETON-54-ISSUES-RECLASSEES-SKELETON-FIRST.csv` — cette
tâche RECONCILIE et VÉRIFIE, elle ne réévalue pas le fond des 54 issues.

Réutilise l'API PUBLIQUE de custody.py (C00-001, APPROVE 3/3) pour toute
lecture (confinement anti-symlink) et toute écriture (atomique, anti-
symlink) — jamais de réimplémentation (cf. target_probe.py, signalé en
limitations du bundle C00-001)."""
from __future__ import annotations

import csv
import io
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import custody


class DispositionInconnueRefusee(Exception):
    """`_classer` ne connaît que 5 valeurs de `skeleton_stage_classification`
    (liste blanche) — toute autre valeur est un signal que la matrice source
    a changé de vocabulaire sans que ce module soit mis à jour ; on refuse
    plutôt que d'inventer un classement par défaut."""


class IssueNonBijectiveRefusee(Exception):
    """Le jeu des 54 `issue_id` lus depuis `sources/audit/issues/*.json` et
    celui lu depuis la matrice de reclassification DOIVENT être identiques
    (bijection stricte) — sinon une issue serait classée sans existence
    réelle, ou une issue réelle resterait sans disposition (cas RED)."""


class BugProduitNonBijectifRefuse(Exception):
    """Les 12 bugs produit transcrits DOIVENT correspondre exactement aux 12
    lignes de `NOUVEAUX-CONSTATS-PRODUIT.csv` — aucun perdu, aucun inventé
    (cas RED : « 12 bugs produit doivent rester visibles »)."""


class SkeletonPromuEnBugCoreRefuse(Exception):
    """Garde indépendante (cas RED) : aucune issue dont la matrice source
    marque `EXPECTED_SKELETON_OR_NOT_DUE` ne doit ressortir avec une
    disposition autre que `EXPECTED_SKELETON` — recalculée ici depuis la
    matrice brute, jamais depuis la sortie du classeur lui-même (sinon la
    garde s'auto-justifierait)."""


class SourceHorsConfinementRefusee(Exception):
    """Une source (issue JSON, matrice CSV) doit résider sous `pack_root` —
    jamais suivre un lien symbolique vers un fichier hors périmètre. Même
    motif que C00-002 (`custody.EcritureViaSymlinkRefusee`, nom de domaine
    adapté au sens LECTURE ici)."""


# ---------------------------------------------------------------------------
# Interface — IssueDisposition(issue_id, disposition, target_phase,
# target_task, reason), telle que déclarée par le Task Spec C00-003.
# ---------------------------------------------------------------------------

DISPOSITIONS_VALIDES = frozenset({
    "CORE_DUE", "PROOF_DUE", "MODULE_DEFERRED", "EXPECTED_SKELETON", "DECISION_REQUIRED",
})


@dataclass(frozen=True)
class IssueDisposition:
    """La garde de validation vit dans `__post_init__` — PAS seulement dans
    une fonction-usine à part. Leçon C00-002 tour 1 (Gemini-3.1-Pro CRITIQUE
    + Qwen3.7-Max MAJEURE, convergentes, mesurées fondées) : un dataclass
    n'empêche jamais l'instanciation directe qui contournerait une garde
    logée uniquement dans une factory — `IssueDisposition(...)` doit être
    aussi sûr que n'importe quelle façade qui l'appelle."""
    issue_id: str
    disposition: str
    target_phase: str | None
    target_task: str | None
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.issue_id, str) or not self.issue_id.strip():
            raise ValueError(f"issue_id doit être une str non vide : {self.issue_id!r}")
        if self.disposition not in DISPOSITIONS_VALIDES:
            raise DispositionInconnueRefusee(
                f"disposition {self.disposition!r} hors liste blanche "
                f"{sorted(DISPOSITIONS_VALIDES)} pour {self.issue_id}"
            )
        if self.target_phase is not None and not isinstance(self.target_phase, str):
            raise TypeError(f"target_phase doit être str ou None : {self.target_phase!r}")
        if self.target_task is not None and not isinstance(self.target_task, str):
            raise TypeError(f"target_task doit être str ou None : {self.target_task!r}")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError(f"reason doit être une str non vide pour {self.issue_id}")


@dataclass(frozen=True)
class DeferredModuleBug:
    """Un des 12 bugs produit de `NOUVEAUX-CONSTATS-PRODUIT.csv`
    (`NEW-PROD-001`..`NEW-PROD-012`) — transcrit, jamais recalculé. Reste
    hors périmètre M1-M10 de cette tâche (aucune correction, uniquement
    traçabilité de routage)."""
    bug_id: str
    module: str
    severite: str
    titre: str
    statut: str
    reason: str

    def __post_init__(self) -> None:
        for champ in ("bug_id", "module", "severite", "titre", "statut", "reason"):
            valeur = getattr(self, champ)
            if not isinstance(valeur, str) or not valeur.strip():
                raise ValueError(f"{champ} doit être une str non vide : {valeur!r}")


# ---------------------------------------------------------------------------
# Constantes SOURCÉES — chemins relatifs à pack_root, jamais absolus tapés
# ailleurs qu'ici.
# ---------------------------------------------------------------------------

ISSUES_DIR_RELATIF = "sources/audit/issues"
MATRICE_RECLASSIFICATION_RELATIVE = "sources/audit/matrices/SKELETON-54-ISSUES-RECLASSEES-SKELETON-FIRST.csv"
BUGS_PRODUIT_RELATIF = "sources/audit/matrices/NOUVEAUX-CONSTATS-PRODUIT.csv"

NB_ISSUES_ATTENDU = 54
NB_BUGS_PRODUIT_ATTENDU = 12

# Référence INDÉPENDANTE (numérotation §6.1 du forensique), jamais dérivée du
# contenu de NOUVEAUX-CONSTATS-PRODUIT.csv — même motif que MODULES_ATTENDUS
# en C00-002 : si la référence était dérivée de la même source qu'elle
# vérifie, une ligne manquante resterait indétectable (garde qui
# s'auto-justifie). C'est cette liste, pas une comparaison de longueur, qui
# fait tenir le cas RED « 12 bugs produit doivent rester visibles ».
ID_BUGS_PRODUIT_ATTENDUS = frozenset(f"NEW-PROD-{i:03d}" for i in range(1, NB_BUGS_PRODUIT_ATTENDU + 1))

# Mapping EXPLICITE (liste blanche) — `skeleton_stage_classification` (colonne
# de SKELETON-54-ISSUES-RECLASSEES-SKELETON-FIRST.csv, déjà produite par
# l'audit) vers l'une des 5 valeurs de `DISPOSITIONS_VALIDES`. Toute valeur
# absente de ce dict lève `DispositionInconnueRefusee` dans `_classer` —
# jamais un défaut silencieux (cf. "gate liste noire laisse passer inconnu",
# leçon appliquée ici en évitant précisément ce motif).
_MAPPING_STADE_VERS_DISPOSITION = {
    # 12 issues : "L'absence est ASSUMÉE"/"cohérent avec le mode ombre" —
    # jamais un bug Core (cas RED explicite de ce Task Spec).
    "EXPECTED_SKELETON_OR_NOT_DUE": "EXPECTED_SKELETON",
    # 22 issues : défaut du HARNAIS d'audit/preuve (gates, sceaux, tally),
    # PAS du produit OPSYS-AI — texte répété littéralement dans 7 des
    # `reserve` sources (CA06-AH-*, CA06-SCEAUX).
    "AUDIT_OR_PROOF_DEFECT_UNCHANGED": "PROOF_DUE",
    # 16 issues : défaut réel, indépendant du stade squelette (syntaxe,
    # sécurité, reproductibilité, documentation, comportement local),
    # aucune n'est scopée à un seul module M1-M10 — dû au Core maintenant.
    "STAGE_INDEPENDENT_DEFECT_OR_DEBT": "CORE_DUE",
    # 1 issue (CA07-0001, ledger dupliqué dans 9 modules — D-010 voulait le
    # Core) : dette architecturale due AU STADE FONDATION, pas différable.
    "DUE_ARCHITECTURAL_DEBT": "CORE_DUE",
    # 3 issues : portée mixte, échéances différentes mélangées dans un seul
    # candidat — ne peut pas recevoir une disposition automatique unique,
    # nécessite un arbitrage (architecte ou T3) avant scission.
    "MIXED_SCOPE_REQUIRES_ATOMIC_SPLIT": "DECISION_REQUIRED",
}

# Recoupe indépendante : toute issue dont `corrected_disposition` porte ce
# marqueur EXACT est un point de décision humaine/gouvernance, quel que soit
# son `skeleton_stage_classification` — override le mapping ci-dessus.
# N'affecte aujourd'hui que ISS-CAND-CA21-0001 (LICENSE Apache vs décision
# T3 ratifiée PROPRIÉTAIRE), déjà classée `STAGE_INDEPENDENT_DEFECT_OR_DEBT`
# (défaut réel et indépendant du stade) mais dont la CLÔTURE exige un choix
# de gouvernance — les deux faits sont vrais simultanément, l'override
# choisit lequel gouverne la disposition finale.
_MARQUEUR_DECISION_REQUISE = "CONFIRMED_DECISION_REQUIRED"


def _classer(stade: str, disposition_corrigee: str) -> str:
    """Liste blanche stricte : `stade` doit être l'une des 5 clés connues,
    toute autre valeur lève `DispositionInconnueRefusee` — jamais un
    classement par défaut silencieux."""
    if disposition_corrigee == _MARQUEUR_DECISION_REQUISE:
        return "DECISION_REQUIRED"
    if stade not in _MAPPING_STADE_VERS_DISPOSITION:
        raise DispositionInconnueRefusee(
            f"skeleton_stage_classification inconnu (liste blanche "
            f"{sorted(_MAPPING_STADE_VERS_DISPOSITION)}) : {stade!r}"
        )
    return _MAPPING_STADE_VERS_DISPOSITION[stade]


# ---------------------------------------------------------------------------
# Lecture confinée — mêmes primitives durcies que C00-001/C00-002, API
# publique de custody.py uniquement.
# ---------------------------------------------------------------------------


def _lire_texte_confine(chemin: Path, pack_root: Path) -> str:
    try:
        reel = custody.verifier_confinement(chemin, pack_root)
    except custody.EcritureViaSymlinkRefusee as e:
        raise SourceHorsConfinementRefusee(
            f"lecture refusée (source hors confinement ou via symlink) : {chemin} — {e}"
        ) from e
    return reel.read_text(encoding="utf-8")


def _charger_issues(pack_root: Path) -> dict[str, dict]:
    """Charge les 54 `ISS-CAND-*.json`, clé = `issue_id` (champ interne du
    JSON, jamais déduit du nom de fichier). Vérifie que le nom de fichier et
    le champ `issue_id` concordent — une divergence signalerait un fichier
    renommé ou dupliqué par erreur, invisible autrement."""
    issues_dir = pack_root / ISSUES_DIR_RELATIF
    resultat: dict[str, dict] = {}
    for chemin in sorted(issues_dir.glob("ISS-CAND-*.json")):
        contenu = json.loads(_lire_texte_confine(chemin, pack_root))
        issue_id = contenu["issue_id"]
        attendu_du_nom = chemin.stem
        if issue_id != attendu_du_nom:
            raise ValueError(
                f"incohérence nom de fichier / champ issue_id : "
                f"fichier={chemin.name} champ={issue_id!r}"
            )
        resultat[issue_id] = contenu
    return resultat


def _charger_matrice(pack_root: Path) -> list[dict]:
    # io.StringIO, jamais texte.splitlines() : un champ CSV entre guillemets
    # peut contenir un saut de ligne littéral (une `reason` multi-paragraphe,
    # p. ex.) — splitlines() couperait le champ AVANT que csv sache qu'il
    # est cité, corrompant silencieusement la ligne. StringIO préserve le
    # flux brut, seul csv.DictReader interprète les guillemets.
    texte = _lire_texte_confine(pack_root / MATRICE_RECLASSIFICATION_RELATIVE, pack_root)
    return list(csv.DictReader(io.StringIO(texte)))


def _charger_bugs_produit(pack_root: Path) -> list[dict]:
    texte = _lire_texte_confine(pack_root / BUGS_PRODUIT_RELATIF, pack_root)
    return list(csv.DictReader(io.StringIO(texte)))


# ---------------------------------------------------------------------------
# Réconciliation
# ---------------------------------------------------------------------------


def _construire_reason(stage_reason: str, reserve_issue: str) -> str:
    """Concatène deux justifications SOURCÉES verbatim (jamais reformulées) :
    le motif de stade (matrice) et la réserve de l'issue d'origine (JSON),
    quand elle existe — préserve les « limites » exigées par le Task Spec
    (« Implémentation strictement bornée »)."""
    stage_reason = stage_reason.strip()
    reserve_issue = reserve_issue.strip()
    if reserve_issue:
        return f"{stage_reason} [réserve source : {reserve_issue}]"
    return stage_reason


def _verifier_aucun_skeleton_promu(
    issue_to_work: tuple[IssueDisposition, ...], matrice: list[dict],
) -> None:
    """Cas RED obligatoire, vérifié INDÉPENDAMMENT de `_classer` : re-dérive
    depuis la matrice BRUTE (pas depuis la sortie du classeur) l'ensemble
    des issues marquées `EXPECTED_SKELETON_OR_NOT_DUE`, puis vérifie que
    CHACUNE ressort avec `disposition == "EXPECTED_SKELETON"` dans le
    résultat final — une régression future dans `_classer` (ou un futur
    appel qui l'esquive) resterait détectée ici même si le mapping lui-même
    était corrompu."""
    attendues = {
        r["issue_id"] for r in matrice
        if r["skeleton_stage_classification"] == "EXPECTED_SKELETON_OR_NOT_DUE"
    }
    par_id = {d.issue_id: d for d in issue_to_work}
    for issue_id in attendues:
        obtenue = par_id[issue_id].disposition
        if obtenue != "EXPECTED_SKELETON":
            raise SkeletonPromuEnBugCoreRefuse(
                f"{issue_id} est EXPECTED_SKELETON_OR_NOT_DUE dans la matrice "
                f"source mais ressort en disposition {obtenue!r} — un stade "
                f"squelette attendu ne doit JAMAIS devenir un bug Core"
            )


def reconcilier(pack_root: str | Path) -> tuple[
    tuple[IssueDisposition, ...], tuple[DeferredModuleBug, ...], tuple[IssueDisposition, ...],
]:
    """Retourne (issue_to_work, deferred_module_bugs, unresolved_questions).

    `issue_to_work` porte EXACTEMENT une `IssueDisposition` par issue des 54
    (cas RED 1) ; `deferred_module_bugs` porte EXACTEMENT les 12 bugs produit
    (cas RED 2) ; `unresolved_questions` est le sous-ensemble de
    `issue_to_work` dont la disposition est `DECISION_REQUIRED` — jamais un
    ensemble séparément recalculé (pas de double source de vérité)."""
    pack_root = Path(pack_root).resolve()
    issues = _charger_issues(pack_root)
    matrice = _charger_matrice(pack_root)
    bugs_produit = _charger_bugs_produit(pack_root)

    id_issues = set(issues.keys())
    id_matrice = {r["issue_id"] for r in matrice}
    if id_issues != id_matrice:
        raise IssueNonBijectiveRefusee(
            f"jeu d'issue_id non bijectif entre {ISSUES_DIR_RELATIF} et "
            f"{MATRICE_RECLASSIFICATION_RELATIVE} — "
            f"seulement JSON: {sorted(id_issues - id_matrice)} ; "
            f"seulement matrice: {sorted(id_matrice - id_issues)}"
        )

    # Doublon d'issue_id DANS la matrice elle-même : la comparaison de sets
    # ci-dessus ne le verrait pas (deux lignes identiques s'écrasent dans un
    # set) — seule une comparaison lignes-vs-ids-uniques le révèle. Contrôle
    # STRUCTUREL (jamais un nombre en dur : reste correct que la matrice
    # source porte 54 lignes aujourd'hui ou un autre compte demain).
    if len(matrice) != len(id_matrice):
        compte = Counter(r["issue_id"] for r in matrice)
        doublons = sorted(k for k, n in compte.items() if n > 1)
        raise IssueNonBijectiveRefusee(
            f"issue_id dupliqué(s) dans {MATRICE_RECLASSIFICATION_RELATIVE} "
            f"({len(matrice)} lignes pour {len(id_matrice)} id uniques) : {doublons}"
        )

    issue_to_work = tuple(
        IssueDisposition(
            issue_id=row["issue_id"],
            disposition=_classer(row["skeleton_stage_classification"], row["corrected_disposition"]),
            target_phase=issues[row["issue_id"]].get("renvoi") or None,
            target_task=None,
            reason=_construire_reason(row["stage_reason"], issues[row["issue_id"]].get("reserve", "")),
        )
        for row in matrice
    )

    _verifier_aucun_skeleton_promu(issue_to_work, matrice)

    id_bugs_source = {r["id"] for r in bugs_produit}
    if id_bugs_source != ID_BUGS_PRODUIT_ATTENDUS:
        raise BugProduitNonBijectifRefuse(
            f"{BUGS_PRODUIT_RELATIF} ne correspond pas à la liste blanche des "
            f"{NB_BUGS_PRODUIT_ATTENDU} bugs attendus (§6.1) — "
            f"manquants={sorted(ID_BUGS_PRODUIT_ATTENDUS - id_bugs_source)}, "
            f"inattendus={sorted(id_bugs_source - ID_BUGS_PRODUIT_ATTENDUS)}"
        )
    if len(bugs_produit) != len(id_bugs_source):
        compte = Counter(r["id"] for r in bugs_produit)
        doublons = sorted(k for k, n in compte.items() if n > 1)
        raise BugProduitNonBijectifRefuse(
            f"bug_id dupliqué(s) dans {BUGS_PRODUIT_RELATIF} "
            f"({len(bugs_produit)} lignes pour {len(id_bugs_source)} id uniques) : {doublons}"
        )

    deferred_module_bugs = tuple(
        DeferredModuleBug(
            bug_id=row["id"],
            module=row["module"],
            severite=row["severity"],
            titre=row["title"],
            statut=row["status"],
            reason=f"{row['evidence']} — Impact : {row['impact']}",
        )
        for row in bugs_produit
    )

    unresolved_questions = tuple(d for d in issue_to_work if d.disposition == "DECISION_REQUIRED")

    return issue_to_work, deferred_module_bugs, unresolved_questions


# ---------------------------------------------------------------------------
# Écriture confinée — mêmes primitives que C00-002 (`custody.verifier_confinement`
# + `custody.ouverture_atomique_confinee`), fieldnames paramétrés (schémas
# distincts par fichier de sortie).
# ---------------------------------------------------------------------------


def _ecrire_csv_confine(chemin: Path, lignes: list[dict], fieldnames: list[str], racine: Path) -> None:
    custody.verifier_confinement(chemin, racine)
    fd = custody.ouverture_atomique_confinee(chemin, racine)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(lignes)


_CHAMPS_ISSUE = ("issue_id", "disposition", "target_phase", "target_task", "reason")
_CHAMPS_BUG = ("bug_id", "module", "severite", "titre", "statut", "reason")


def _ligne_issue(d: IssueDisposition) -> dict:
    return {champ: getattr(d, champ) for champ in _CHAMPS_ISSUE}


def _ligne_bug(b: DeferredModuleBug) -> dict:
    return {champ: getattr(b, champ) for champ in _CHAMPS_BUG}


def produire_sorties_reconciliation(worktree: Path, sortie_dir: Path, pack_root: str | Path) -> tuple[
    tuple[IssueDisposition, ...], tuple[DeferredModuleBug, ...], tuple[IssueDisposition, ...],
]:
    """Point d'entrée exécutable : produit les 3 CSV exacts du Task Spec
    dans `sortie_dir`. `worktree` est TOUJOURS la racine de confinement
    (jamais `sortie_dir`) — même motif que C00-001/C00-002."""
    issue_to_work, deferred_module_bugs, unresolved_questions = reconcilier(pack_root)

    _ecrire_csv_confine(
        sortie_dir / "ISSUE-TO-WORK.csv",
        [_ligne_issue(d) for d in issue_to_work], list(_CHAMPS_ISSUE), worktree,
    )
    _ecrire_csv_confine(
        sortie_dir / "DEFERRED-MODULE-BUGS.csv",
        [_ligne_bug(b) for b in deferred_module_bugs], list(_CHAMPS_BUG), worktree,
    )
    _ecrire_csv_confine(
        sortie_dir / "UNRESOLVED-QUESTIONS.csv",
        [_ligne_issue(d) for d in unresolved_questions], list(_CHAMPS_ISSUE), worktree,
    )
    return issue_to_work, deferred_module_bugs, unresolved_questions


if __name__ == "__main__":
    pack_root_defaut = Path(
        os.environ.get(
            "OPSYS_PACK", "/home/pc1/core-pack/OPSYS-AI-CORE-EXECUTION-PACK-v2.3.1-fusion"
        )
    )
    worktree = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
    sortie_dir = Path(__file__).resolve().parent
    itw, dmb, uq = produire_sorties_reconciliation(worktree, sortie_dir, pack_root_defaut)
    print(json.dumps(
        {
            "issue_to_work": len(itw), "deferred_module_bugs": len(dmb),
            "unresolved_questions": len(uq),
            "dispositions": sorted({d.disposition for d in itw}),
        },
        ensure_ascii=False, indent=2,
    ))
