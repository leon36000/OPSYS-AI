"""C00-005 — Sceller le canon Core, les non-objectifs et l'ordre des
modules. Tests RED→GREEN pour la couverture du canon.

Chaque `CanonRequirement.statement` est une citation SOURCÉE, transcrite
VERBATIM (apostrophe typographique ’ U+2019 comprise — vérifiée octet pour
octet avant écriture, jamais l'apostrophe ASCII ') depuis l'une des 5
sources à relire du Task Spec. La couverture n'est jamais déclarée : elle
est VÉRIFIÉE en lisant le fichier de sortie réel et en cherchant le
`statement` comme sous-chaîne EXACTE — un oubli d'écriture fait échouer le
test, jamais une affirmation non vérifiée."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[3]

CORE_CANON = "docs/core/CORE-CANON-v2.md"
CORE_NON_GOALS = "docs/core/CORE-NON-GOALS-v2.md"
MODULE_ORDER = "docs/core/MODULE-ORDER-AND-DEFERRED-SURFACES.md"

# Les 3 sorties exactes du Task Spec — liste blanche stricte, jamais un
# chemin inventé pour acceptance_ref.
DOCS_CONNUS = frozenset({CORE_CANON, CORE_NON_GOALS, MODULE_ORDER})


class ExigenceHorsListeBlancheRefusee(Exception):
    """`acceptance_ref` doit être l'une des 3 sorties exactes du Task Spec
    — jamais un chemin inventé qui échapperait à toute vérification."""


@dataclass(frozen=True)
class CanonRequirement:
    """La garde vit dans `__post_init__` — pas seulement dans une factory
    (même motif que C00-002/003/004 : `@dataclass` ne bride jamais
    `__init__`, un contournement par instanciation directe doit rester
    aussi gardé que le chemin normal)."""
    id: str
    statement: str
    source_ref: str
    acceptance_ref: str

    def __post_init__(self) -> None:
        for champ in ("id", "statement", "source_ref", "acceptance_ref"):
            valeur = getattr(self, champ)
            if not isinstance(valeur, str) or not valeur.strip():
                raise ValueError(f"{champ} doit être une str non vide : {valeur!r}")
        if self.acceptance_ref not in DOCS_CONNUS:
            raise ExigenceHorsListeBlancheRefusee(
                f"acceptance_ref {self.acceptance_ref!r} hors liste blanche "
                f"{sorted(DOCS_CONNUS)}"
            )


# ---------------------------------------------------------------------------
# Les 11 exigences atomisées du canon — chacune sourcée, jamais inventée.
# ---------------------------------------------------------------------------

EXIGENCES: tuple[CanonRequirement, ...] = (
    CanonRequirement(
        id="CORE-001",
        statement="OPSYS-AI doit maintenant produire, ratifier puis exécuter le "
                   "Core partagé avant toute complétion de département.",
        source_ref="sources/continuity/key/68-CORE-FIRST-REPRIORITIZATION-DECISION-v5.6.0.md:8",
        acceptance_ref=CORE_CANON,
    ),
    CanonRequirement(
        id="CORE-002",
        statement="M7 → M1 → M2 → M4 → M3 → M6 → M8 → M10 → M5 → M9",
        source_ref="sources/continuity/key/02-CANON-NON-NEGOCIABLE.md:11",
        acceptance_ref=MODULE_ORDER,
    ),
    CanonRequirement(
        id="CORE-003",
        statement="Aucun travail métier M1–M10 ni interface finale n’est autorisé "
                   "pendant l’exécution du Core.",
        source_ref="sources/continuity/key/68-CORE-FIRST-REPRIORITIZATION-DECISION-v5.6.0.md:25",
        acceptance_ref=CORE_NON_GOALS,
    ),
    CanonRequirement(
        id="MOBILE-001",
        statement="Surface officielle OPSYS-AI avec quatre profils : `ADMIN`, "
                   "`VENDEUR`, `EMPLOYÉ`, `CLIENT`.",
        source_ref="sources/continuity/key/02-CANON-NON-NEGOCIABLE.md:44",
        acceptance_ref=MODULE_ORDER,
    ),
    CanonRequirement(
        id="MOBILE-002",
        statement="`RF01-W12 Mobile Operations Bridge` est différé, non supprimé.",
        source_ref="sources/continuity/key/68-CORE-FIRST-REPRIORITIZATION-DECISION-v5.6.0.md:21",
        acceptance_ref=MODULE_ORDER,
    ),
    CanonRequirement(
        id="AVATAR-001",
        statement="L’avatar est une surface transversale du Core. Il route vers le "
                   "module autoritatif et ne devient jamais source de vérité.",
        source_ref="sources/continuity/key/02-CANON-NON-NEGOCIABLE.md:39",
        acceptance_ref=CORE_CANON,
    ),
    CanonRequirement(
        id="AVATAR-002",
        statement="Core contracts for `ADMIN`, `VENDEUR`, `EMPLOYÉ`, `CLIENT`, "
                   "offline sync, GPS windows, payments, notifications and avatar "
                   "routing are frozen and tested early. The complete mobile "
                   "application, 3D avatar and visual polish remain outside this "
                   "Core implementation program.",
        source_ref="sources/continuity/key/69-CORE-ARCHITECTURE-DESIGN-v1.0.0.md:107",
        acceptance_ref=MODULE_ORDER,
    ),
    CanonRequirement(
        id="VOIX-001",
        statement="avatar/voix final",
        source_ref="sources/continuity/key/19-MOBILE-APP-OPERATIONS-BRIDGE-CANON.md:225",
        acceptance_ref=MODULE_ORDER,
    ),
    CanonRequirement(
        id="JURIDIQUE-001",
        statement="tout acte juridique reste gated",
        source_ref="sources/continuity/key/02-CANON-NON-NEGOCIABLE.md:50",
        acceptance_ref=CORE_CANON,
    ),
    CanonRequirement(
        id="PAIEMENTS-001",
        statement="Paiements via fournisseurs tokenisés; aucune donnée complète de "
                   "carte dans OPSYS-AI.",
        source_ref="sources/continuity/key/02-CANON-NON-NEGOCIABLE.md:49",
        acceptance_ref=CORE_CANON,
    ),
    CanonRequirement(
        id="RECOUVREMENT-001",
        statement="D-MOB-008 : M5 possède l’AR; M1 exécute les communications de "
                   "recouvrement.",
        source_ref="sources/continuity/key/19-MOBILE-APP-OPERATIONS-BRIDGE-CANON.md:254",
        acceptance_ref=CORE_CANON,
    ),
)

ID_EXIGENCES_ATTENDUS = frozenset(e.id for e in EXIGENCES)


def _contenu(acceptance_ref: str) -> str:
    chemin = WORKTREE / acceptance_ref
    return chemin.read_text(encoding="utf-8")


def _est_couverte(exigence: CanonRequirement) -> bool:
    """Vérifie la présence RÉELLE du statement, jamais une déclaration.
    Substring EXACTE (apostrophe typographique comprise) — c'est la preuve
    mécanique, pas une lecture par un modèle."""
    return exigence.statement in _contenu(exigence.acceptance_ref)


# ---------------------------------------------------------------------------
# 3 cas RED obligatoires (noms imposés par le Task Spec)
# ---------------------------------------------------------------------------


def test_sceller_le_canon_core_les_non_objectifs_et_l_ordre_des_modul_1():
    """RED obligatoire : « inclure Core-first et
    M7→M1→M2→M4→M3→M6→M8→M10→M5→M9 »."""
    core_first = next(e for e in EXIGENCES if e.id == "CORE-001")
    ordre = next(e for e in EXIGENCES if e.id == "CORE-002")
    assert _est_couverte(core_first), f"{core_first.id} absente de {core_first.acceptance_ref}"
    assert _est_couverte(ordre), f"{ordre.id} absente de {ordre.acceptance_ref}"
    # L'ordre exact des 10 modules, sans aucune transposition ni omission.
    assert "M7 → M1 → M2 → M4 → M3 → M6 → M8 → M10 → M5 → M9" in _contenu(MODULE_ORDER)


def test_sceller_le_canon_core_les_non_objectifs_et_l_ordre_des_modul_2():
    """RED obligatoire : « préserver mobile ADMIN/VENDEUR/EMPLOYÉ/CLIENT »."""
    mobile = next(e for e in EXIGENCES if e.id == "MOBILE-001")
    differe = next(e for e in EXIGENCES if e.id == "MOBILE-002")
    assert _est_couverte(mobile), f"{mobile.id} absente de {mobile.acceptance_ref}"
    assert _est_couverte(differe), f"{differe.id} absente de {differe.acceptance_ref}"
    contenu = _contenu(MODULE_ORDER)
    for profil in ("ADMIN", "VENDEUR", "EMPLOYÉ", "CLIENT"):
        assert profil in contenu, f"profil mobile {profil} absent de {MODULE_ORDER}"


def test_sceller_le_canon_core_les_non_objectifs_et_l_ordre_des_modul_3():
    """RED obligatoire : « préserver avatar, voix, juridique, paiements et
    recouvrement comme contrats Core mais UI finale différée »."""
    for eid in ("AVATAR-001", "AVATAR-002", "VOIX-001", "JURIDIQUE-001", "PAIEMENTS-001", "RECOUVREMENT-001"):
        exigence = next(e for e in EXIGENCES if e.id == eid)
        assert _est_couverte(exigence), f"{exigence.id} absente de {exigence.acceptance_ref}"
    # La différenciation contrat-tôt / UI-différée doit être EXPLICITE, pas
    # seulement implicite dans des citations séparées.
    contenu_ordre = _contenu(MODULE_ORDER)
    assert "frozen and tested early" in contenu_ordre
    assert "remain outside this Core implementation program" in contenu_ordre


# ---------------------------------------------------------------------------
# CanonRequirement — gel + gardes à l'instanciation directe
# ---------------------------------------------------------------------------


def test_canon_requirement_est_gelee():
    r = CanonRequirement("X", "statement", "source", CORE_CANON)
    with pytest.raises(AttributeError):
        r.id = "Y"


def test_canon_requirement_refuse_champ_vide():
    with pytest.raises(ValueError):
        CanonRequirement("", "s", "src", CORE_CANON)
    with pytest.raises(ValueError):
        CanonRequirement("X", "   ", "src", CORE_CANON)


def test_canon_requirement_refuse_acceptance_ref_hors_liste_blanche():
    """Cas RED implicite mais structurel : un acceptance_ref inventé (hors
    des 3 sorties exactes) ne doit jamais pouvoir être construit — il
    échapperait à toute vérification de couverture."""
    with pytest.raises(ExigenceHorsListeBlancheRefusee):
        CanonRequirement("X", "s", "src", "docs/core/FICHIER-INVENTE.md")


# ---------------------------------------------------------------------------
# Couverture globale — les 11 exigences, une par une ET toutes ensemble.
# ---------------------------------------------------------------------------


def test_toutes_les_exigences_sont_couvertes_individuellement():
    manquantes = [e.id for e in EXIGENCES if not _est_couverte(e)]
    assert not manquantes, f"exigences non couvertes : {manquantes}"


def test_exigences_id_uniques_et_attendues():
    assert len(EXIGENCES) == len(ID_EXIGENCES_ATTENDUS) == 11


def test_chaque_sortie_est_ciblee_par_au_moins_une_exigence():
    """Aucune des 3 sorties ne doit rester une coquille vide sans exigence
    associée — sinon `_est_couverte` ne la testerait jamais."""
    cibles = {e.acceptance_ref for e in EXIGENCES}
    assert cibles == DOCS_CONNUS


def test_les_3_sorties_existent_et_sont_non_vides():
    for rel in DOCS_CONNUS:
        chemin = WORKTREE / rel
        assert chemin.is_file(), f"{rel} absent"
        assert len(chemin.read_text(encoding="utf-8").strip()) > 0, f"{rel} vide"
