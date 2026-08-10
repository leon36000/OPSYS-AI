"""C00-002 — Rejouer le stade squelette-first depuis les sources canoniques
hachées. Aucune valeur de statut n'est calculée depuis un texte libre (une
extraction fragile romprait si un document canonique était reformulé sans
changer de sens) : les statuts sont des CONSTANTES CITÉES, transcrites
verbatim depuis les sources listées dans `SOURCES_CANONIQUES`, chacune
retracée à la section exacte d'où elle vient. Seuls les hash SHA-256 des
sources sont calculés — jamais tapés à la main."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Réutilise les primitives durcies et scellées de C00-001 (revue scellée
# 6 tours, APPROVE 3/3) — confinement + ouverture atomique refusant tout
# symlink (feuille OU intermédiaire) AVANT toute création. Ne JAMAIS
# réimplémenter cette logique : c'est exactement l'erreur mesurée dans
# tools/target_probe.py (schéma incompatible, aucune protection symlink),
# signalée en limitations[] du bundle C00-001 tour 6.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import custody


class ModuleNonPartielRefuse(Exception):
    """Un module M1-M10 ne peut être reconstruit qu'à un statut reconnu de
    la vague 1 (squelette) — jamais un statut impliquant une complétion
    totale, et jamais un module manquant sur les dix attendus."""


class InterfaceFinaleNonDifferee(Exception):
    """core_status doit porter explicitement le report de l'interface
    finale (source : « INTERFACE_FINALE = DERNIER CHANTIER »)."""


class AbsenceFinaleRequalifieeEnDefaut(Exception):
    """core_status doit porter explicitement que l'absence de capacités
    finales est un état de stade attendu, pas une preuve de dérive."""


@dataclass(frozen=True)
class StageState:
    """Le stade programme reconstruit — un instantané cité, jamais recalculé
    depuis une interprétation libre du texte source."""
    program_stage: str
    modules: dict[str, str]
    core_status: str
    source_hashes: list[str]


# ---------------------------------------------------------------------------
# Constantes SOURCÉES — transcrites verbatim, jamais paraphrasées.
# ---------------------------------------------------------------------------

SOURCES_CANONIQUES = (
    "sources/audit/ANALYSE-FORENSIQUE-CORRIGEE-SQUELETTE-FIRST-v2.md",
    "sources/continuity/key/60-CORPUS-REREAD-AND-AUDIT-RECEIPT-v5.5.0.md",
    "sources/continuity/key/68-CORE-FIRST-REPRIORITIZATION-DECISION-v5.6.0.md",
    "sources/continuity/key/02-CANON-NON-NEGOCIABLE.md",
    "sources/continuity/key/OPSYS-AI-CONTINUITY-CONTROL-PLANE-v3.0.md",
)

# ANALYSE-FORENSIQUE-CORRIGEE-SQUELETTE-FIRST-v2.md §2 « Conclusion corrigée »,
# ligne STAGE_PROGRAMME_PROUVE.
PROGRAM_STAGE_SOURCE = "FIN_PREMIERE_VAGUE_DU_SQUELETTE"

# Même §2 — 4 lignes citées (Core, interface, absences finales, dérive
# globale). Les 2 marqueurs ci-dessous (MARQUEUR_INTERFACE_DIFFEREE et
# MARQUEUR_ABSENCE_PAS_DEFAUT) DOIVENT apparaître littéralement dans ce
# core_status — c'est ce que les gardes vérifient.
CORE_STATUS_SOURCE = (
    "PHASE_0_CORE=PARTIELLE_BLOQUEE_AVEC_CAUSE; "
    "INTERFACE_FINALE=DERNIER_CHANTIER; "
    "ASSEMBLAGE_FINAL_ABSENT=ETAT_DE_STAGE_PAS_PREUVE_DE_DERIVE; "
    "DERIVE_ARCHITECTURALE_GLOBALE=NON_ETABLIE"
)

# ANALYSE-FORENSIQUE-CORRIGEE-SQUELETTE-FIRST-v2.md §4 « État corrigé Core
# et M1–M10 » — les 10 lignes du tableau, transcrites une à une.
MODULES_STATUTS_SOURCE = {
    "M7": "PARTIAL_ADVANCED_IN_ORDER",
    "M1": "SKELETON_WAVE1_COMPLETE_PARTIAL_BY_DESIGN",
    "M2": "SKELETON_WAVE1_COMPLETE_PARTIAL_BY_DESIGN",
    "M4": "SKELETON_WAVE1_COMPLETE_PARTIAL_BY_DESIGN",
    "M3": "SKELETON_WAVE1_COMPLETE_DOC_STALE",
    "M6": "SKELETON_WAVE1_COMPLETE_WITH_CONFIRMED_BUGS",
    "M8": "SKELETON_WAVE1_COMPLETE_DOC_STALE",
    "M10": "SHIM_AND_WAVE1_COMPLETE_FULL_BUILD_NOT_DUE",
    "M5": "SKELETON_WAVE1_COMPLETE_WITH_CONFIRMED_BUGS",
    "M9": "SKELETON_WAVE1_COMPLETE_WITH_CONFIRMED_BUG",
}

MODULES_ATTENDUS = frozenset({"M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10"})

# Liste INDÉPENDANTE de MODULES_STATUTS_SOURCE — ne JAMAIS la dériver des
# valeurs sourcées ci-dessus (sinon la garde s'auto-justifie : une mutation
# d'un statut réel vers un autre statut réel resterait indétectable, piège
# mesuré ailleurs dans ce projet — "garde qui s'auto-justifie"). Ce sont des
# marqueurs de COMPLÉTION TOTALE, absents par construction des 10 valeurs
# sourcées ci-dessus (vérifié : aucune des 10 ne contient l'un de ces mots).
MARQUEURS_COMPLETION_INTERDITS = (
    "DONE", "SHIPPED", "PRODUCTION_READY", "_FINAL", "FINAL_", "VERIFIED_FULL",
)

MARQUEUR_INTERFACE_DIFFEREE = "INTERFACE_FINALE=DERNIER_CHANTIER"
MARQUEUR_ABSENCE_PAS_DEFAUT = "ASSEMBLAGE_FINAL_ABSENT=ETAT_DE_STAGE_PAS_PREUVE_DE_DERIVE"


def _verifier_modules_partiels(modules: dict[str, str]) -> None:
    """Cas RED obligatoire : « les dix modules doivent rester PARTIAL »."""
    manquants = MODULES_ATTENDUS - modules.keys()
    if manquants:
        raise ModuleNonPartielRefuse(
            f"modules manquants (les dix sont requis à ce stade) : {sorted(manquants)}"
        )
    for nom, statut in modules.items():
        for marqueur in MARQUEURS_COMPLETION_INTERDITS:
            if marqueur in statut:
                raise ModuleNonPartielRefuse(
                    f"module {nom} : statut {statut!r} contient le marqueur de "
                    f"complétion totale {marqueur!r} — les dix modules doivent "
                    f"rester PARTIAL à ce stade (squelette vague 1)"
                )


def _verifier_interface_differee(core_status: str) -> None:
    """Cas RED obligatoire : « l'interface finale doit rester différée »."""
    if MARQUEUR_INTERFACE_DIFFEREE not in core_status:
        raise InterfaceFinaleNonDifferee(
            f"core_status ne porte pas le report explicite de l'interface "
            f"finale ({MARQUEUR_INTERFACE_DIFFEREE!r} absent) : {core_status!r}"
        )


def _verifier_absence_non_qualifiee_en_defaut(core_status: str) -> None:
    """Cas RED obligatoire : « une capacité finale absente ne devient pas
    automatiquement un défaut »."""
    if MARQUEUR_ABSENCE_PAS_DEFAUT not in core_status:
        raise AbsenceFinaleRequalifieeEnDefaut(
            f"core_status ne porte pas la requalification explicite de "
            f"l'absence de capacités finales ({MARQUEUR_ABSENCE_PAS_DEFAUT!r} "
            f"absent) : {core_status!r}"
        )


def construire_stage_state(
    program_stage: str, modules: dict[str, str], core_status: str, source_hashes: list[str],
) -> StageState:
    """Point de validation UNIQUE — les 3 gardes des cas RED s'exécutent
    ici, jamais ailleurs, pour qu'aucun site d'appel ne puisse les
    contourner en construisant StageState(...) directement."""
    _verifier_modules_partiels(modules)
    _verifier_interface_differee(core_status)
    _verifier_absence_non_qualifiee_en_defaut(core_status)
    return StageState(
        program_stage=program_stage, modules=dict(modules),
        core_status=core_status, source_hashes=list(source_hashes),
    )


def _sha256(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        while bloc := f.read(1_048_576):
            h.update(bloc)
    return h.hexdigest()


def rejouer_stade(pack_root: str | Path) -> StageState:
    """Reconstruit le StageState : hache RÉELLEMENT les 5 sources
    canoniques, construit avec les statuts CITÉS (jamais recalculés depuis
    le texte libre)."""
    pack_root = Path(pack_root)
    hashes = [_sha256(pack_root / rel) for rel in SOURCES_CANONIQUES]
    return construire_stage_state(
        program_stage=PROGRAM_STAGE_SOURCE,
        modules=dict(MODULES_STATUTS_SOURCE),
        core_status=CORE_STATUS_SOURCE,
        source_hashes=hashes,
    )


def _ecrire_csv_stage_sans_suivre_symlink(chemin: Path, lignes: list[dict], racine: Path) -> None:
    """Même garde que `custody._ecrire_sans_suivre_symlink` (confinement +
    ouverture atomique refusant tout symlink, feuille ou intermédiaire,
    AVANT toute création) — réutilise LES MÊMES primitives durcies et
    scellées de C00-001 (`custody._verifier_confinement`,
    `custody._ouverture_atomique_confinee`), jamais réimplémentées.
    `custody._ecrire_csv_sans_suivre_symlink` n'est pas réutilisable telle
    quelle : ses `fieldnames` sont figés à `chemin,sha256,taille` (schéma de
    C00-001), incompatible avec le schéma `source,sha256` de
    STAGE-EVIDENCE.csv."""
    custody._verifier_confinement(chemin, racine)
    fd = custody._ouverture_atomique_confinee(chemin, racine)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["source", "sha256"])
        writer.writeheader()
        writer.writerows(lignes)


def _produire_sorties_stage(worktree: Path, sortie_dir: Path, pack_root: str | Path) -> StageState:
    """Point d'entrée exécutable : produit STAGE.json et STAGE-EVIDENCE.csv
    dans `sortie_dir`. `worktree` est TOUJOURS la racine de confinement
    (jamais `sortie_dir` — même tautologie fermée qu'en C00-001 tour 1/2)."""
    etat = rejouer_stade(pack_root)
    custody._ecrire_sans_suivre_symlink(
        sortie_dir / "STAGE.json",
        json.dumps(
            {
                "program_stage": etat.program_stage,
                "modules": etat.modules,
                "core_status": etat.core_status,
                "source_hashes": etat.source_hashes,
            },
            ensure_ascii=False, indent=2, sort_keys=True,
        ) + "\n",
        worktree,
    )
    lignes = [{"source": rel, "sha256": h} for rel, h in zip(SOURCES_CANONIQUES, etat.source_hashes)]
    _ecrire_csv_stage_sans_suivre_symlink(sortie_dir / "STAGE-EVIDENCE.csv", lignes, worktree)
    return etat


if __name__ == "__main__":
    pack_root_defaut = Path(
        os.environ.get(
            "OPSYS_PACK", "/home/pc1/core-pack/OPSYS-AI-CORE-EXECUTION-PACK-v2.3.1-fusion"
        )
    )
    worktree = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
    sortie_dir = Path(__file__).resolve().parent
    garde = _produire_sorties_stage(worktree, sortie_dir, pack_root_defaut)
    print(json.dumps(
        {"program_stage": garde.program_stage, "core_status": garde.core_status,
         "modules": garde.modules, "source_hashes": garde.source_hashes},
        ensure_ascii=False, indent=2,
    ))
