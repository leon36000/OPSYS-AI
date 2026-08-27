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
from types import MappingProxyType

# Réutilise l'API PUBLIQUE de C00-001 (custody.py — revue scellée 6 tours,
# APPROVE 3/3), pas ses fonctions privées. DeepSeek-V4-Pro, CRITIQUE, C00-002
# tour 1 (mesurée fondée) : importer des noms préfixés `_` d'un autre module
# rompt le contrat d'encapsulation Python implicite (API privée = instable,
# aucun engagement de stabilité), même si la logique sous-jacente est
# durcie. custody.py expose désormais verifier_confinement /
# ouverture_atomique_confinee / ecrire_sans_suivre_symlink comme alias
# PUBLICS explicites — mêmes primitives, contrat stable. Ne JAMAIS
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


class SourceHorsConfinementRefusee(Exception):
    """Une source canonique doit résider sous pack_root — jamais suivre un
    lien symbolique vers un fichier hors périmètre."""


@dataclass(frozen=True)
class StageState:
    """Le stade programme reconstruit — un instantané cité, jamais recalculé
    depuis une interprétation libre du texte source.

    Les 3 gardes des cas RED de la spec s'exécutent dans `__post_init__` —
    PAS seulement dans une fonction-usine à part. Gemini-3.1-Pro (CRITIQUE)
    + Qwen3.7-Max (MAJEURE), C00-002 tour 1, convergentes, mesurées fondées :
    `StageState(program_stage='', modules={'M1': 'DONE'}, ...)` réussissait
    silencieusement en instanciant le dataclass directement, contournant
    TOTALEMENT les gardes qui n'existaient que dans `construire_stage_state`
    — un commentaire affirmant « point de validation unique » n'empêche rien
    en Python, `__init__` généré par `@dataclass` reste public. Fermé en
    déplaçant les 3 gardes ici, au seul endroit qu'AUCUN site d'appel ne
    peut éviter — `construire_stage_state` reste une façade nommée, mais
    n'est plus le mécanisme d'enforcement.

    `modules` (Mapping, pas dict) et `source_hashes` (tuple, pas list) :
    Gemini-3.1-Pro, MAJEURE, C00-002 tour 1, mesurée fondée —
    `frozen=True` empêche la RÉASSIGNATION d'un champ (`etat.x = y` lève),
    mais ne gèle PAS le contenu d'un conteneur mutable qu'il référence
    (`etat.modules['M1'] = 'DONE'` réussissait silencieusement après
    construction, ré-ouvrant exactement le trou que les gardes venaient de
    fermer). `MappingProxyType`/`tuple` ferment ce trou : toute mutation
    post-construction lève désormais `TypeError`. Conversion explicite en
    dict/list ordinaires au point de sérialisation JSON
    (`_produire_sorties_stage`), jamais exposée telle quelle à `json.dumps`
    (qui ne sait pas sérialiser un `MappingProxyType`, mesuré).

    Gemini-3.1-Pro, MAJEURE, C00-002 tour 2 (mesurée fondée) : la version
    tour 1 de cette docstring affirmait à tort garder le type hint de
    l'interface INCHANGÉ (« dict[str,str]/list[str] ») — en réalité le hint
    de `source_hashes` avait été PERDU sur `construire_stage_state`. Les
    champs de CE dataclass sont typés `MappingProxyType[str, str]` /
    `tuple[str, ...]` (classes concrètes réelles, pas de mensonge de type
    hint) ; `construire_stage_state` restaure `list[str] | tuple[str, ...]`.
    Un type hint seul ne protège RIEN à l'exécution (Python ne les impose
    pas) : `__post_init__` exige une LISTE BLANCHE stricte
    (`isinstance(..., (list, tuple))`) pour `source_hashes` AVANT la
    conversion `tuple(...)` — Gemini-3.1-Pro + Qwen3.7-Max, MAJEURE
    CONVERGENTE, C00-002 tour 3 (mesurée fondée) : une première version en
    LISTE NOIRE (`str`/`bytes` seuls refusés) ne fermait pas la classe —
    bytearray/memoryview (réduits en tuple d'entiers), set (ordre non
    déterministe) et générateur épuisé (réduit en `()`) traversaient tous
    silencieusement. La liste blanche ferme la classe entière ; chaque
    élément est en plus vérifié `str`."""
    program_stage: str
    modules: "MappingProxyType[str, str]"
    core_status: str
    source_hashes: "tuple[str, ...]"

    def __post_init__(self) -> None:
        # Gemini-3.1-Pro + Qwen3.7-Max, MAJEURE CONVERGENTE, C00-002 tour 3
        # (mesurée fondée) : une liste NOIRE (`isinstance(..., (str,
        # bytes))`) ne ferme pas la classe du défaut — `tuple(x)` accepte
        # SILENCIEUSEMENT n'importe quel itérable, et plusieurs AUTRES types
        # dégénérés le traversent avec la même corruption muette que la
        # chaîne d'origine :
        #   - bytearray/memoryview : réduits en tuple d'ENTIERS, mesuré
        #     `tuple(bytearray(b'hash'))` -> `(104, 97, 115, 104)`.
        #   - set : ordre NON DÉTERMINISTE, mesuré `tuple({'h1','h2'})` peut
        #     donner `('h2','h1')` — casse la reproductibilité du JSON/CSV.
        #   - générateur déjà épuisé : `tuple(gen_vide)` -> `()`, silencieux.
        # Fermé en LISTE BLANCHE stricte : seuls `list`/`tuple` sont
        # acceptés, tout le reste refusé nommément — ferme la CLASSE du
        # défaut, pas seulement le cas str/bytes déjà signalé. Chaque
        # ÉLÉMENT doit aussi être une str (une séquence de hash SHA-256 ne
        # contient que des chaînes ; un `[123, 456]` passerait la liste
        # blanche de conteneur sans cette 2e garde).
        if not isinstance(self.source_hashes, (list, tuple)):
            raise TypeError(
                f"source_hashes doit être une list ou un tuple (liste blanche "
                f"stricte — tout autre itérable, y compris str/bytes/"
                f"bytearray/set/générateur, est refusé pour éviter une "
                f"réduction silencieuse via tuple(...)) : "
                f"{type(self.source_hashes).__name__} reçu"
            )
        # Gemini-3.1-Pro, MAJEURE, C00-002 tour 4 (mesurée fondée) : TOCTOU
        # entre la validation et la conversion. La version tour 4 validait
        # `all(isinstance(h, str) for h in self.source_hashes)` PUIS
        # convertissait `tuple(self.source_hashes)` séparément — DEUX
        # itérations distinctes sur la MÊME source. `isinstance(x, (list,
        # tuple))` accepte les SOUS-CLASSES ; une sous-classe de `list` à
        # `__iter__` AVEC ÉTAT peut renvoyer des str au 1er appel (pour
        # `all()`, qui passe) puis des entiers au 2e appel (pour `tuple()`),
        # contournant la garde. Reproduit et mesuré : `SneakyList.__iter__`
        # renvoyant `('a'*64,)` puis `(123,)` selon le compteur d'appel ->
        # `all()` voit une str (passe), `tuple()` produit `(123,)` (corrompu,
        # jamais détecté). Fermé en INVERSANT l'ordre : UNE SEULE conversion
        # `tuple(...)` en premier (matérialise un instantané figé, un seul
        # appel à `__iter__`), la validation `all(isinstance(...))` porte
        # ensuite sur ce TUPLE DÉJÀ FIGÉ — plus aucune fenêtre entre
        # « vérifié » et « utilisé », le tuple final ne peut plus diverger
        # de ce qui a été validé (il EST ce qui a été validé).
        source_hashes_fige = tuple(self.source_hashes)
        if not all(isinstance(h, str) for h in source_hashes_fige):
            raise TypeError(
                f"chaque élément de source_hashes doit être une str : {source_hashes_fige!r}"
            )
        _verifier_modules_partiels(self.modules)
        _verifier_interface_differee(self.core_status)
        _verifier_absence_non_qualifiee_en_defaut(self.core_status)
        # object.__setattr__ : seule façon de fixer un champ dans
        # __post_init__ d'un dataclass frozen (son __setattr__ normal lève).
        object.__setattr__(self, "modules", MappingProxyType(dict(self.modules)))
        object.__setattr__(self, "source_hashes", source_hashes_fige)


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


def _verifier_modules_partiels(modules) -> None:
    """Cas RED obligatoire : « les dix modules doivent rester PARTIAL »."""
    manquants = MODULES_ATTENDUS - set(modules.keys())
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
    program_stage: str, modules: dict[str, str], core_status: str,
    source_hashes: list[str] | tuple[str, ...],
) -> StageState:
    """Façade nommée — l'enforcement réel des 3 gardes vit dans
    `StageState.__post_init__`, qu'on arrive ici ou par instanciation
    directe (les deux chemins sont désormais gardés, mesuré par
    `test_instanciation_directe_est_aussi_gardee`)."""
    return StageState(
        program_stage=program_stage, modules=modules,
        core_status=core_status, source_hashes=source_hashes,
    )


def _sha256_source_confinee(chemin: Path, pack_root: Path) -> str:
    """Hache une source canonique — refuse tout lien symbolique (feuille OU
    intermédiaire) et tout chemin hors `pack_root` AVANT lecture.

    Qwen3.7-Max, MAJEURE, C00-002 tour 1, mesurée fondée (CWE-59) : la
    version précédente (`chemin.open('rb')` nu) suivait aveuglément un
    symlink placé sur un chemin de source canonique — un attaquant capable
    d'en planter un force la lecture et le hachage d'un fichier hors
    périmètre (ex. une clé privée), dont le hash apparaîtrait ensuite dans
    STAGE-EVIDENCE.csv comme si c'était la source légitime. Fermé en
    réutilisant `custody.verifier_confinement` (résolution complète de la
    chaîne, pas seulement `is_symlink()` sur la feuille — même garde que
    C00-001, API publique désormais).

    `custody.EcritureViaSymlinkRefusee` est traduite en
    `SourceHorsConfinementRefusee` : le nom custody est pensé pour un
    chemin d'ÉCRITURE (« Ecriture... »), sémantiquement inexact pour ce
    chemin de LECTURE — même mécanisme de confinement, nom de domaine
    approprié côté appelant."""
    try:
        reel = custody.verifier_confinement(chemin, pack_root)
    except custody.EcritureViaSymlinkRefusee as e:
        raise SourceHorsConfinementRefusee(
            f"lecture refusée (source hors confinement ou via symlink) : {chemin} — {e}"
        ) from e
    h = hashlib.sha256()
    with reel.open("rb") as f:
        while bloc := f.read(1_048_576):
            h.update(bloc)
    return h.hexdigest()


def rejouer_stade(pack_root: str | Path) -> StageState:
    """Reconstruit le StageState : hache RÉELLEMENT les 5 sources
    canoniques (confinées, symlink refusé), construit avec les statuts
    CITÉS (jamais recalculés depuis le texte libre)."""
    pack_root = Path(pack_root).resolve()
    hashes = [_sha256_source_confinee(pack_root / rel, pack_root) for rel in SOURCES_CANONIQUES]
    return construire_stage_state(
        program_stage=PROGRAM_STAGE_SOURCE,
        modules=dict(MODULES_STATUTS_SOURCE),
        core_status=CORE_STATUS_SOURCE,
        source_hashes=hashes,
    )


def _ecrire_csv_stage_sans_suivre_symlink(chemin: Path, lignes: list[dict], racine: Path) -> None:
    """Même garde que `custody.ecrire_sans_suivre_symlink` (confinement +
    ouverture atomique refusant tout symlink, feuille ou intermédiaire,
    AVANT toute création) — réutilise LES MÊMES primitives durcies et
    scellées de C00-001, via leur API PUBLIQUE (`custody.verifier_confinement`,
    `custody.ouverture_atomique_confinee`), jamais réimplémentées.
    `custody.ecrire_csv_sans_suivre_symlink`(*) n'est pas réutilisable telle
    quelle : ses `fieldnames` sont figés à `chemin,sha256,taille` (schéma de
    C00-001), incompatible avec le schéma `source,sha256` de
    STAGE-EVIDENCE.csv. (* jamais exposée en public — usage interne à
    custody.py uniquement, contrairement aux 3 primitives ci-dessus.)"""
    custody.verifier_confinement(chemin, racine)
    fd = custody.ouverture_atomique_confinee(chemin, racine)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["source", "sha256"])
        writer.writeheader()
        writer.writerows(lignes)


def _produire_sorties_stage(worktree: Path, sortie_dir: Path, pack_root: str | Path) -> StageState:
    """Point d'entrée exécutable : produit STAGE.json et STAGE-EVIDENCE.csv
    dans `sortie_dir`. `worktree` est TOUJOURS la racine de confinement
    (jamais `sortie_dir` — même tautologie fermée qu'en C00-001 tour 1/2)."""
    etat = rejouer_stade(pack_root)
    custody.ecrire_sans_suivre_symlink(
        sortie_dir / "STAGE.json",
        json.dumps(
            {
                "program_stage": etat.program_stage,
                # dict(...) : etat.modules est un MappingProxyType (immuable
                # par construction) — json.dumps ne sait PAS le sérialiser
                # directement (mesuré : TypeError), seul un dict ordinaire
                # convient. La conversion ne réintroduit aucune mutabilité
                # côté etat lui-même (etat.modules reste un MappingProxyType
                # après cet appel).
                "modules": dict(etat.modules),
                "core_status": etat.core_status,
                "source_hashes": list(etat.source_hashes),
            },
            ensure_ascii=False, indent=2, sort_keys=True,
        ) + "\n",
        worktree,
    )
    lignes = [{"source": rel, "sha256": h} for rel, h in zip(SOURCES_CANONIQUES, etat.source_hashes)]
    _ecrire_csv_stage_sans_suivre_symlink(sortie_dir / "STAGE-EVIDENCE.csv", lignes, worktree)
    return etat


if __name__ == "__main__":
    # AUD-CORE-006 : aucun défaut plausible n'est inventé ici. Le pack
    # d'exécution Core est un artefact EXTERNE au dépôt (versionné hors
    # Git, propre à chaque poste) ; il n'existe aucun sous-répertoire du
    # dépôt qui puisse en tenir lieu par défaut. Un chemin absolu propre à
    # un seul poste présenté comme valeur par défaut générale est
    # exactement le défaut mesuré par l'issue #570. Erreur explicite
    # plutôt que deviner.
    _opsys_pack_env = os.environ.get("OPSYS_PACK")
    if not _opsys_pack_env:
        sys.exit(
            "OPSYS_PACK n'est pas défini. Ce script a besoin du chemin vers le "
            "pack d'exécution Core (ex. OPSYS_PACK=/chemin/vers/"
            "OPSYS-AI-CORE-EXECUTION-PACK-vX.Y.Z-fusion) ; ce pack est un "
            "artefact externe au dépôt, il n'a pas de valeur par défaut."
        )
    pack_root_defaut = Path(_opsys_pack_env)
    worktree = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
    sortie_dir = Path(__file__).resolve().parent
    garde = _produire_sorties_stage(worktree, sortie_dir, pack_root_defaut)
    print(json.dumps(
        {"program_stage": garde.program_stage, "core_status": garde.core_status,
         "modules": dict(garde.modules), "source_hashes": list(garde.source_hashes)},
        ensure_ascii=False, indent=2,
    ))
