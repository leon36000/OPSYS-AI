"""C00-004 — Ratifier la carte des chemins canoniques et des autorités.

Inventorie les chemins RÉELS de `core/src/` et des 10 modules M1-M10
(`registries/modules.yaml`, transcrit) — jamais recalculés depuis une
supposition. Réserve `core/src/opsys_core` pour le nouveau Core SI aucun
conflit avec l'existant (`core/src/auth`, `core/src/authz`,
`core/src/config` — tous trois réellement peuplés, vérifiés par inventaire
avant écriture de ce module) ; définit des shims de compatibilité pour ces
3 services existants ; refuse toute résolution de chemin non reconnue
plutôt que de l'adapter en silence ; refuse toute autorité Core en
écriture sur une vérité M1-M10.

Réutilise l'API PUBLIQUE de custody.py (C00-001) pour toute écriture
(atomique, anti-symlink) — jamais de réimplémentation."""
from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import custody


class ConflitCheminRefuse(Exception):
    """Cas RED obligatoire : un chemin RÉELLEMENT peuplé (core/src/auth,
    core/src/authz, core/src/config) ne peut jamais être déclaré
    `RESERVED_NEW` — ce serait prétendre qu'il est libre alors qu'il est
    déjà un service réel. Le conflit doit être BLOQUÉ, jamais silencieusement
    accepté avec un statut faux."""


class WriterCoreSurModulesRefuse(Exception):
    """Cas RED obligatoire : aucune `Authority` dont `owner` est le Core ne
    peut porter un `write_port` référençant la racine `src/` d'un module
    M1-M10 — le Core ne réécrit jamais la vérité d'un module."""


class AdaptationSilencieuseRefusee(Exception):
    """Cas RED obligatoire : résoudre un `logical_path` inconnu de la liste
    blanche doit REFUSER, jamais deviner/adapter un chemin proche en
    silence."""


class IncoherenceStatutChemin(Exception):
    """Un statut EXISTING_* déclaré sur un chemin qui n'existe PAS
    réellement (d'après l'inventaire) est une incohérence — ni un conflit
    (rien de peuplé n'est usurpé), ni une adaptation silencieuse (le
    logical_path est reconnu), mais une déclaration fausse sur l'état du
    disque. Refusée nommément plutôt que journalisée comme un cas normal."""


class InventaireDeriveRefuse(Exception):
    """L'inventaire codé en dur (CHEMINS_CORE_EXISTANTS_PEUPLES,
    CHEMIN_CORE_NOUVEAU, MODULES_SRC_ROOTS) DOIT correspondre à l'état RÉEL
    du disque au moment de l'exécution — vérifié à chaque appel de
    `construire_carte_chemins`, jamais supposé une fois pour toutes. Si le
    disque a dérivé depuis l'écriture de ce module (un service Core
    existant supprimé, `opsys_core` créé entre-temps, un module renommé),
    la carte produite serait fausse — refusée plutôt que publiée périmée."""


# ---------------------------------------------------------------------------
# Inventaire SOURCÉ — mesuré par `find` sur le worktree avant d'écrire ce
# module (jamais une supposition). Constantes INDÉPENDANTES du code qui les
# vérifie (même motif que MODULES_ATTENDUS en C00-002 : si dérivées de la
# même source qu'elles vérifient, une régression resterait indétectable).
# ---------------------------------------------------------------------------

# `core/src/{auth,authz,config}` — vérifié peuplés (au moins un fichier .py
# réel, hors .gitkeep) au commit de base de cette tâche.
CHEMINS_CORE_EXISTANTS_PEUPLES = frozenset({
    "core/src/auth",
    "core/src/authz",
    "core/src/config",
})

# Le nouveau namespace réservé au Core — vérifié ABSENT du disque au commit
# de base (aucun conflit possible aujourd'hui).
CHEMIN_CORE_NOUVEAU = "core/src/opsys_core"

# CA07-0002 (sources/audit/issues/ISS-CAND-CA07-0002.json, réconciliée
# DECISION_REQUIRED par C00-003/ISSUE-TO-WORK.csv) : « Trois services
# transversaux exigés par le canon sont totalement absents » (policy
# kernel, lifecycle, backup/export) — 0 fichier de code, portée mixte,
# échéances différentes. Tant que cette décision reste ouverte, AUCUN
# chemin canonique ne peut leur être assigné de bonne foi : ce serait
# inventer une décision qui n'a pas été prise. Marqués AMENDMENT_REQUIRED,
# jamais un chemin devinable.
_MOTIF_AMENDEMENT_CA07_0002 = (
    "UNRESOLVED — dépend de la décision C00-003 sur ISS-CAND-CA07-0002 "
    "(DECISION_REQUIRED, ISSUE-TO-WORK.csv) : portée mixte, échéances "
    "différentes, aucun chemin ne peut être ratifié avant cette décision."
)
SERVICES_TRANSVERSAUX_EN_ATTENTE = ("policy_kernel", "lifecycle", "backup_export")

# registries/modules.yaml, transcrit verbatim (10 noms, jamais recalculés) ;
# racine src RÉELLE de chaque module, vérifiée par inventaire (`find`).
MODULES_SRC_ROOTS = {
    "M1-front-office": "Modules M/M1-front-office/src",
    "M2-revenue-crm": "Modules M/M2-revenue-crm/src",
    "M3-estimation": "Modules M/M3-estimation/src",
    "M4-field-ops": "Modules M/M4-field-ops/src",
    "M5-financecore": "Modules M/M5-financecore/src",
    "M6-material-control": "Modules M/M6-material-control/src",
    "M7-marketing": "Modules M/M7-marketing/src",
    "M8-analytics": "Modules M/M8-analytics/src",
    "M9-strategic-intelligence": "Modules M/M9-strategic-intelligence/src",
    "M10-memoire": "Modules M/M10-memoire/src",
}
MODULES_ATTENDUS = frozenset(MODULES_SRC_ROOTS)

STATUTS_VALIDES = frozenset({
    "RESERVED_NEW", "EXISTING_SHIM_REQUIRED", "EXISTING_MODULE_OWNED", "AMENDMENT_REQUIRED",
})


def _chemin_egal_ou_sous_chemin_de(candidat: str, reference: str) -> bool:
    """Compare deux chemins par COMPOSANTS APRÈS normalisation LEXICALE,
    jamais par égalité de chaîne brute ni par composants bruts non
    normalisés.

    Gemini-3.1-Pro, mineure, C00-004 tour 1 (mesurée fondée, 4
    contournements reproduits) : une comparaison de chaîne exacte laisse
    passer un slash final (`'core/src/authz/'` != `'core/src/authz'`) ou
    un sous-dossier direct (`'core/src/authz/x'`).

    DeepSeek-V4-Pro + Gemini-3.1-Pro + Qwen3.7-Max, MAJEURE CONVERGENTE,
    C00-004 tour 2 (mesurée fondée sur 2 des 3 exemples — celui de DeepSeek
    ne se reproduisait PAS, sa préoccupation sous-jacente était néanmoins
    fondée) : la version tour 2 comparait des `PurePosixPath(...).parts`
    NON normalisés — `'..'` n'est jamais résolu lexicalement par
    `PurePosixPath`. Mesuré : `PurePosixPath('core/src/unprotected/../authz').parts`
    -> `('core','src','unprotected','..','authz')`, dont le préfixe de
    longueur 3 est `('core','src','unprotected')` != `('core','src','authz')`
    — la garde ne reconnaissait PAS ce chemin comme visant `core/src/authz`
    alors qu'il y résout lexicalement, contournant silencieusement
    `ConflitCheminRefuse`/`WriterCoreSurModulesRefuse`. Fermé en normalisant
    `candidat` ET `reference` via `os.path.normpath` (collapse LEXICAL de
    `.`/`..`/séparateurs redondants, AUCUN accès disque, ne dépend pas de
    l'existence du chemin) AVANT de découper en composants — `os.path.normpath`
    ne collapse QUE ce qui peut l'être sans information externe (un `..`
    menant hors de la racine relative reste tel quel, ce qui ne matche de
    toute façon aucun chemin Core/module connu).

    `.parts` (après normalisation) reste nécessaire pour la comparaison de
    PRÉFIXE DE COMPOSANTS (pas de préfixe de chaîne : `'core/src/authzz'`
    ne matche PAS `'core/src/authz'`, contrairement à `str.startswith`) —
    reconnaît correctement un sous-dossier comme faisant partie du même
    chemin peuplé. Portée volontairement limitée aux 2 gardes de REFUS
    (élargir ce qu'elles bloquent est sûr) — les gardes de COHÉRENCE
    (`IncoherenceStatutChemin`) gardent une égalité stricte : elles
    valident une représentation canonique produite par CE module lui-même,
    pas une entrée à tolérer."""
    parts_candidat = PurePosixPath(os.path.normpath(candidat)).parts
    parts_reference = PurePosixPath(os.path.normpath(reference)).parts
    return parts_candidat[: len(parts_reference)] == parts_reference


# ---------------------------------------------------------------------------
# PathMap(logical_path, actual_path, status)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PathMap:
    """La garde vit dans `__post_init__` — pas seulement dans une factory
    (leçon C00-002 tour 1 : `@dataclass` ne bride jamais `__init__`)."""
    logical_path: str
    actual_path: str
    status: str

    def __post_init__(self) -> None:
        for champ in ("logical_path", "actual_path", "status"):
            valeur = getattr(self, champ)
            if not isinstance(valeur, str) or not valeur.strip():
                raise ValueError(f"{champ} doit être une str non vide : {valeur!r}")
        if self.status not in STATUTS_VALIDES:
            raise ValueError(f"status {self.status!r} hors liste blanche {sorted(STATUTS_VALIDES)}")

        # Cas RED 1 : un chemin RÉELLEMENT peuplé (ou un de ses sous-chemins,
        # ou une variante avec slash final) ne peut jamais être déclaré
        # RESERVED_NEW — ce serait prétendre qu'il est libre.
        if self.status == "RESERVED_NEW" and any(
            _chemin_egal_ou_sous_chemin_de(self.actual_path, peuple)
            for peuple in CHEMINS_CORE_EXISTANTS_PEUPLES
        ):
            raise ConflitCheminRefuse(
                f"{self.actual_path} est déjà peuplé (service Core existant) — "
                f"ne peut pas être déclaré RESERVED_NEW, un statut EXISTING_* est requis"
            )
        # Symétrique : un chemin déclaré EXISTING_* qui n'est pourtant PAS
        # dans l'inventaire des chemins peuplés (ni un module connu) est une
        # incohérence — refusée nommément, jamais journalisée comme normale.
        if (
            self.status == "EXISTING_SHIM_REQUIRED"
            and self.actual_path not in CHEMINS_CORE_EXISTANTS_PEUPLES
        ):
            raise IncoherenceStatutChemin(
                f"{self.actual_path} déclaré EXISTING_SHIM_REQUIRED mais absent de "
                f"l'inventaire des chemins Core réellement peuplés : "
                f"{sorted(CHEMINS_CORE_EXISTANTS_PEUPLES)}"
            )
        if (
            self.status == "EXISTING_MODULE_OWNED"
            and self.actual_path not in MODULES_SRC_ROOTS.values()
        ):
            raise IncoherenceStatutChemin(
                f"{self.actual_path} déclaré EXISTING_MODULE_OWNED mais absent des "
                f"racines src des 10 modules connus"
            )


# ---------------------------------------------------------------------------
# Résolution — liste blanche stricte, jamais d'adaptation silencieuse
# (cas RED 3).
# ---------------------------------------------------------------------------


def _construire_registre_logique() -> dict[str, tuple[str, str]]:
    """logical_path -> (actual_path, status). Construit UNE FOIS depuis les
    constantes sourcées ci-dessus — jamais recalculé par heuristique."""
    registre: dict[str, tuple[str, str]] = {
        "core.opsys_core": (CHEMIN_CORE_NOUVEAU, "RESERVED_NEW"),
        "core.auth": ("core/src/auth", "EXISTING_SHIM_REQUIRED"),
        "core.authz": ("core/src/authz", "EXISTING_SHIM_REQUIRED"),
        "core.config": ("core/src/config", "EXISTING_SHIM_REQUIRED"),
    }
    for nom_module, racine in MODULES_SRC_ROOTS.items():
        registre[f"module.{nom_module}"] = (racine, "EXISTING_MODULE_OWNED")
    for service in SERVICES_TRANSVERSAUX_EN_ATTENTE:
        registre[f"core.{service}"] = (_MOTIF_AMENDEMENT_CA07_0002, "AMENDMENT_REQUIRED")
    return registre


REGISTRE_LOGIQUE = _construire_registre_logique()


def resoudre_chemin_canonique(logical_path: str) -> PathMap:
    """Cas RED obligatoire : `logical_path` DOIT être une clé connue de la
    liste blanche — toute autre valeur lève `AdaptationSilencieuseRefusee`,
    jamais une résolution devinée/approximée."""
    if logical_path not in REGISTRE_LOGIQUE:
        raise AdaptationSilencieuseRefusee(
            f"logical_path inconnu (liste blanche {sorted(REGISTRE_LOGIQUE)}) : "
            f"{logical_path!r} — aucune adaptation silencieuse, refus explicite"
        )
    actual_path, status = REGISTRE_LOGIQUE[logical_path]
    return PathMap(logical_path=logical_path, actual_path=actual_path, status=status)


def _verifier_inventaire_coherent(worktree: Path) -> None:
    """Recoupe l'inventaire codé en dur contre le DISQUE RÉEL — jamais une
    confiance aveugle dans des constantes écrites une fois. Un service
    déclaré peuplé doit contenir au moins un fichier réel (pas seulement un
    `.gitkeep`) ; le namespace réservé doit rester absent ; chaque racine
    de module doit exister."""
    for rel in CHEMINS_CORE_EXISTANTS_PEUPLES:
        chemin = worktree / rel
        fichiers_reels = [p for p in chemin.rglob("*") if p.is_file() and p.name != ".gitkeep"]
        if not chemin.is_dir() or not fichiers_reels:
            raise InventaireDeriveRefuse(
                f"{rel} est déclaré peuplé (service Core existant) mais le disque "
                f"ne le confirme pas (dossier absent ou vide de tout fichier réel) — "
                f"inventaire périmé, carte refusée"
            )
    if (worktree / CHEMIN_CORE_NOUVEAU).exists():
        raise InventaireDeriveRefuse(
            f"{CHEMIN_CORE_NOUVEAU} est déclaré réservable (RESERVED_NEW) mais existe "
            f"déjà sur le disque — inventaire périmé, carte refusée"
        )
    for nom_module, racine in MODULES_SRC_ROOTS.items():
        if not (worktree / racine).is_dir():
            raise InventaireDeriveRefuse(
                f"module {nom_module} : racine {racine!r} absente du disque — "
                f"inventaire périmé, carte refusée"
            )


def construire_carte_chemins(worktree: Path) -> tuple[PathMap, ...]:
    """La carte complète — un PathMap par entrée du registre logique,
    chacun construit via `resoudre_chemin_canonique` (jamais construit à la
    main ailleurs, un seul point de vérité). `worktree` sert UNIQUEMENT à
    recouper l'inventaire contre le disque réel avant de faire confiance
    aux constantes codées en dur."""
    _verifier_inventaire_coherent(Path(worktree).resolve())
    return tuple(resoudre_chemin_canonique(lp) for lp in REGISTRE_LOGIQUE)


# ---------------------------------------------------------------------------
# Authority(owner, aggregate, read_port, write_port)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Authority:
    owner: str
    aggregate: str
    read_port: str
    write_port: str

    def __post_init__(self) -> None:
        for champ in ("owner", "aggregate", "read_port", "write_port"):
            valeur = getattr(self, champ)
            if not isinstance(valeur, str) or not valeur.strip():
                raise ValueError(f"{champ} doit être une str non vide : {valeur!r}")
        # Cas RED 2 : le Core ne reçoit JAMAIS un write_port qui référence la
        # racine src d'un module M1-M10 (ni un sous-dossier, ni une variante
        # avec slash final) — vérifié ici, au seul point de construction
        # qu'aucun appelant ne peut éviter.
        if self.owner == "CORE" and any(
            _chemin_egal_ou_sous_chemin_de(self.write_port, racine)
            for racine in MODULES_SRC_ROOTS.values()
        ):
            raise WriterCoreSurModulesRefuse(
                f"Authority(owner=CORE) ne peut pas porter write_port={self.write_port!r} "
                f"— une racine src de module M1-M10 ne peut jamais être écrite par le Core"
            )


def construire_carte_autorites() -> tuple[Authority, ...]:
    """Chaque module est seul lecteur/écrivain de sa propre racine src
    (autonomie déjà actée par chore #109 — identité de paquet par module).
    Le Core est seul lecteur/écrivain de ses 3 services existants et de son
    namespace réservé — jamais d'un chemin de module."""
    autorites = [
        Authority(owner=nom_module, aggregate=nom_module, read_port=racine, write_port=racine)
        for nom_module, racine in MODULES_SRC_ROOTS.items()
    ]
    for nom_service, chemin in (
        ("auth", "core/src/auth"), ("authz", "core/src/authz"),
        ("config", "core/src/config"), ("opsys_core", CHEMIN_CORE_NOUVEAU),
    ):
        autorites.append(Authority(owner="CORE", aggregate=nom_service, read_port=chemin, write_port=chemin))
    return tuple(autorites)


# ---------------------------------------------------------------------------
# Écriture confinée — mêmes primitives que C00-001/C00-002/C00-003.
# ---------------------------------------------------------------------------


def _ecrire_json_confine(chemin: Path, obj, racine: Path) -> None:
    custody.ecrire_sans_suivre_symlink(
        chemin, json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", racine,
    )


def _ecrire_csv_confine(chemin: Path, lignes: list[dict], fieldnames: list[str], racine: Path) -> None:
    custody.verifier_confinement(chemin, racine)
    fd = custody.ouverture_atomique_confinee(chemin, racine)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(lignes)


_CHAMPS_AUTHORITY = ("owner", "aggregate", "read_port", "write_port")


def produire_sorties_carte(worktree: Path, sortie_dir: Path) -> tuple[tuple[PathMap, ...], tuple[Authority, ...]]:
    """Point d'entrée exécutable : produit `CANONICAL-PATH-MAP.json` et
    `AUTHORITY-MAP.csv` dans `sortie_dir`. `worktree` est TOUJOURS la racine
    de confinement (jamais `sortie_dir`)."""
    carte_chemins = construire_carte_chemins(worktree)
    carte_autorites = construire_carte_autorites()

    _ecrire_json_confine(
        sortie_dir / "CANONICAL-PATH-MAP.json",
        [
            {"logical_path": p.logical_path, "actual_path": p.actual_path, "status": p.status}
            for p in carte_chemins
        ],
        worktree,
    )
    _ecrire_csv_confine(
        sortie_dir / "AUTHORITY-MAP.csv",
        [{champ: getattr(a, champ) for champ in _CHAMPS_AUTHORITY} for a in carte_autorites],
        list(_CHAMPS_AUTHORITY), worktree,
    )
    return carte_chemins, carte_autorites


if __name__ == "__main__":
    worktree = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
    sortie_dir = Path(__file__).resolve().parent
    chemins, autorites = produire_sorties_carte(worktree, sortie_dir)
    print(json.dumps(
        {"chemins": len(chemins), "autorites": len(autorites),
         "statuts": sorted({p.status for p in chemins})},
        ensure_ascii=False, indent=2,
    ))
