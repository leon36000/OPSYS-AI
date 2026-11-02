"""Manifeste d'un département (`departments/<id>/department.yaml`) et son chargement.

Un département est un organe de l'entreprise. Il octroie à ses agents des capacités :
- des outils déterministes ;
- des skills (procédures) ;
- des politiques d'autonomie ;
- des planifications ;
- des constats planifiés (résumés de routine publiés au bus par un outil N0 à N2, déclenchés par le planificateur
  durable : bloc `constats_planifies`) ;
- des routines planifiées (travail interne déterministe fait d'outils N0 à N2 qu'un exécuteur du planificateur durable
  enchaîne sans agent : bloc `routines_planifiees`) ;
- des budgets de tokens et des KPIs.
Le manifeste est la source unique : le serveur MCP, les profils Hermes et le dashboard en
dérivent.
"""

from __future__ import annotations

import dataclasses
import importlib
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from .appareils import ROLES_APPAREIL
from .avatars import Avatar, normaliser_avatar
from .canaux import CANAUX
from .identite import ROLES, Role
from .outils import Niveau, Outil
from .politiques import valider_mode

SCHEMA = "opsys.departement/v1"
PALIERS = ("local", "rapide", "standard", "fort")
_ID = re.compile(r"^m(0[1-9]|10)-[a-z][a-z0-9-]+$")
_CODE = re.compile(r"^M(10|[1-9])$")
_CRON = re.compile(r"^(\S+\s+){4}\S+$")
_SKILL = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
# Niveaux qu'un département peut configurer dans son bloc `approbations` (ADR-0009 §5). N3 et N4
# seulement : en dessous de N3, une action est automatique et ne crée jamais de demande (ADR-0009
# §4) ; N5 est une frontière FIXE de l'ADR (« la signature de nathan_owner », jamais automatique,
# jamais déléguée) — `DEFAUT_ROLES_NIVEAU` s'applique toujours à N5, aucun manifeste ne peut
# l'élargir ni le restreindre (voir `_politique_approbation`).
_CLES_POLITIQUE = {"n3": Niveau.N3, "n4": Niveau.N4}
# Politique par défaut, fail-closed (ADR-0009 §5) : absente du manifeste, ou un niveau non déclaré,
# retombe sur le rôle le plus restrictif seul.
DEFAUT_ROLES_NIVEAU: frozenset[str] = frozenset({Role.NATHAN_OWNER.value})


@dataclasses.dataclass(frozen=True)
class Planification:
    nom: str
    cron: str
    consigne: str
    # Nom d'une routine du MÊME département (bloc `routines_planifiees`) qui fait désormais ce travail de façon
    # déterministe : l'agent n'est alors plus déclenché (pas de double déclenchement), et `opsys-metier verifier`
    # contrôle que la routine existe et suit bien cette planification.
    remplacee_par: str | None = None


# Le calcul d'un argument d'outil d'un constat planifié (bloc `constats_planifies`), fermé : un instant du créneau, un
# jour, le début ou la fin d'un mois, un lundi, avec un décalage en jours, en mois ou en semaines. Rien d'autre n'est
# évalué : aucun texte du manifeste n'est interprété comme du code.
CALCUL_CONSTAT = re.compile(r"^(?:instant|jour|debut_mois|fin_mois|lundi)(?:[+-][0-9]{1,3})?$")
_NOM_CONSTAT = re.compile(r"^[a-z][a-z0-9-]{1,23}$")
_MESURE_M8 = re.compile(r"^m8_[a-z0-9_]{2,80}$")
_ARGUMENT_OUTIL = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
APPELS_PAR_CONSTAT_MAX = 4
OFFSET_CALCUL_MAX = 366


@dataclasses.dataclass(frozen=True)
class ConstatPlanifie:
    """Un constat de routine que le planificateur durable déclenche (docs/architecture/PLANIFICATION.md §9).

    `outil` : un outil du département (N0 à N2, agent seulement) qui calcule et publie un résumé. `mesures` : les
    mesures du catalogue de M8 qu'il alimente — c'est d'elles, jamais d'une constante, que vient la cadence par
    défaut. `appels` : un ou plusieurs jeux d'arguments, chacun `((argument, genre, valeur), ...)` où le genre est
    `calcul` (`CALCUL_CONSTAT`) ou `valeur` (littéral). Le constat ne porte aucun secret ni aucune donnée
    personnelle : il ne décrit que QUEL outil appeler avec quelles bornes de dates."""

    nom: str
    outil: str
    mesures: tuple[str, ...]
    appels: tuple[tuple[tuple[str, str, Any], ...], ...]
    description: str = ""


_NOM_ROUTINE = re.compile(r"^[a-z][a-z0-9-]{1,23}$")
# La cadence d'une routine est DÉCLARÉE (un cron ou un intervalle) ou SUIVIE (le cron d'une planification du même
# département, jamais recopié). Un seul genre par routine.
GENRES_CADENCE_ROUTINE = ("suit", "cron", "intervalle_s")
OUTILS_PAR_ROUTINE_MAX = 4
INTERVALLE_ROUTINE_MIN_S, INTERVALLE_ROUTINE_MAX_S = 15, 86400


@dataclasses.dataclass(frozen=True)
class RoutinePlanifiee:
    """Une routine interne que le planificateur durable déclenche (docs/architecture/PLANIFICATION.md §10).

    `outils` : la liste FERMÉE des outils du département que l'exécuteur peut appeler (N0 à N2, agent seulement) ; un
    outil hors de cette liste n'est jamais appelé. `cadence` : `(genre, valeur)` où le genre est `suit` (le nom d'une
    planification du département dont la routine reprend le cron), `cron` (un cron de 5 champs, minute et heure fixes,
    jours de semaine seulement) ou `intervalle_s` (un entier de secondes). La routine ne porte aucun secret ni aucune
    donnée personnelle."""

    nom: str
    outils: tuple[str, ...]
    cadence: tuple[str, Any]
    description: str = ""


@dataclasses.dataclass(frozen=True)
class Budget:
    tokens_jour: int
    tokens_mois: int
    alerte_pct: int = 80


@dataclasses.dataclass(frozen=True)
class Kpi:
    id: str
    description: str


@dataclasses.dataclass(frozen=True)
class PolitiqueApprobation:
    """Rôles autorisés à décider (approuver ou refuser) une demande, par niveau N3/N4/N5
    (ADR-0009 §5). `approbations.decider` exige une personne active dont un rôle figure dans
    `roles_pour(niveau)` de SON département ; sinon, refus nommé, rien exécuté.

    Un niveau non couvert par `roles` (bloc absent du manifeste, ou niveau non déclaré dans le
    bloc) retombe sur `DEFAUT_ROLES_NIVEAU` — le rôle le plus restrictif seul (fail-closed).
    """

    roles: Mapping[Niveau, frozenset[str]] = dataclasses.field(default_factory=dict)

    def roles_pour(self, niveau: Niveau) -> frozenset[str]:
        return self.roles.get(niveau, DEFAUT_ROLES_NIVEAU)


POLITIQUE_PAR_DEFAUT = PolitiqueApprobation()


@dataclasses.dataclass(frozen=True)
class Departement:
    id: str
    code: str
    nom: str
    mission: str
    module_outils: str
    mode: str
    dependances: tuple[str, ...]
    modeles: Mapping[str, str]
    skills: tuple[str, ...]
    planifications: tuple[Planification, ...]
    budget: Budget
    memoire_lecture: tuple[str, ...]
    memoire_ecriture: tuple[str, ...]
    kpis: tuple[Kpi, ...]
    racine: Path
    evenements_publie: tuple[str, ...] = ()
    evenements_consomme: tuple[str, ...] = ()
    politique_approbation: PolitiqueApprobation = POLITIQUE_PAR_DEFAUT
    # Canaux du core (`opsys.canaux`) par lesquels ce département reçoit le public (PLAN T2.1-a).
    canaux: tuple[str, ...] = ()
    # Avatar par défaut du département (`opsys.avatars`) : nom, rôle, voix et visage logiques, canaux et leur état.
    # Optionnel à la lecture d'un manifeste ; `opsys-metier verifier` l'exige de chaque département installé.
    avatar: Avatar | None = None
    # Constats de routine déclarés par le département et déclenchés par le planificateur durable (jamais par le socle).
    constats_planifies: tuple[ConstatPlanifie, ...] = ()
    # Routines internes déclarées par le département et déclenchées par le planificateur durable (jamais par un agent).
    routines_planifiees: tuple[RoutinePlanifiee, ...] = ()

    @property
    def prefixe_outils(self) -> str:
        """'m3' pour M3 : préfixe obligatoire des noms d'outils du département."""
        return self.code.lower()

    def roles_autorises(self, niveau: Niveau) -> frozenset[str]:
        """Rôles pouvant décider une demande de ce niveau N dans ce département (ADR-0009 §5)."""
        return self.politique_approbation.roles_pour(niveau)

    @property
    def numero(self) -> int:
        return int(self.code[1:])

    def charger_outils(
        self, *, ports_prives: Mapping[str, Any] | None = None
    ) -> tuple[Outil, ...]:
        """Importe les outils et vérifie le préfixe et l'unicité des noms.

        `ports_prives` est un raccord interne M4/M7→M5, jamais lu dans un manifeste.
        Le port M7 projette trois outils privés absents du catalogue par défaut/MCP.
        """
        module = importlib.import_module(self.module_outils)
        fabrique = getattr(module, "outils", None)
        ports = dict(ports_prives or {})
        # Raccord M9 : un seul port, la lecture des producteurs (`opsys.lecteurs_m9`), pour la fabrique d'outils M9.
        port_m9 = (
            self.id == "m09-strategic-intelligence"
            and self.module_outils == "m9_strategic_intelligence.outils"
            and bool(ports)
            and set(ports) <= {"lecteur_producteurs_m9", "proposeur_actions_m9"}
            and all(callable(port) for port in ports.values())
        )
        port_m1 = (
            self.id == "m01-front-office"
            and self.module_outils == "m1_front_office.outils"
            and bool(ports)
            and set(ports) <= {"lecteur_capacite_m4"}
            and all(callable(port) for port in ports.values())
        )
        if ports and not port_m9 and not port_m1 and (
            self.id != "m05-financecore"
            or self.module_outils != "m5_financecore.outils"
            or not set(ports) <= {"lecteur_heures_m4", "lecteur_campagne_m7"}
            or not all(callable(port) for port in ports.values())
        ):
            raise ValueError(f"{self.id} : port privé non autorisé")
        if callable(fabrique):
            outils = tuple(fabrique(**ports) if ports else fabrique())
        else:
            if ports:
                raise ValueError(f"{self.id} : une fabrique outils() est requise pour un port privé")
            outils = tuple(getattr(module, "OUTILS", ()))
        if not outils:
            raise ValueError(f"{self.id} : {self.module_outils} n'expose ni outils() ni OUTILS")
        vus: set[str] = set()
        for outil in outils:
            if not isinstance(outil, Outil):
                raise TypeError(f"{self.id} : {outil!r} n'est pas un opsys.outils.Outil")
            if outil.departement_code != self.prefixe_outils:
                raise ValueError(
                    f"{self.id} : l'outil {outil.nom} doit commencer par {self.prefixe_outils}_"
                )
            if outil.nom in vus:
                raise ValueError(f"{self.id} : outil en double {outil.nom}")
            vus.add(outil.nom)
        return outils

    def charger_consommateurs(self) -> dict[str, Callable[[Mapping[str, Any]], Any]]:
        """Importe `module_outils.consommateurs()` (fonctions d'événements, ADR-0009 §3).

        Même module que `charger_outils()` (`docs/architecture/DEPARTEMENTS.md`) : un département
        qui ne consomme aucun événement n'a pas besoin de définir `consommateurs`. Absence de la
        fonction : dict vide, jamais une erreur — `evenements.verifier_coherence` signale l'écart
        pour un département qui *déclare* consommer un type sans fournir sa fonction.
        """
        module = importlib.import_module(self.module_outils)
        fabrique = getattr(module, "consommateurs", None)
        if fabrique is None:
            return {}
        consommateurs = fabrique()
        if not isinstance(consommateurs, Mapping):
            raise TypeError(f"{self.id} : {self.module_outils}.consommateurs() doit renvoyer un dict")
        for type_evenement, fonction in consommateurs.items():
            if not isinstance(type_evenement, str) or not callable(fonction):
                raise TypeError(
                    f"{self.id} : consommateurs() doit associer un type (str) à une fonction appelable"
                )
        return dict(consommateurs)

    def charger_attentes(self) -> Callable[[], Sequence[Mapping[str, Any]]] | None:
        """Importe `module_outils.attentes` s'il existe (ADR-0009 §5, PLAN T1.3-a) ; None sinon.

        Même mécanisme que `charger_consommateurs` : fonction optionnelle exposée par le module qui
        définit `outils()`, découverte par `getattr`, jamais déclarée dans le manifeste. Elle n'est
        PAS appelée ici (aucune connexion disponible à ce point) : `approbations.file_proprietaire`
        l'appelle dans la transaction courante, pour que le département puisse lire ses propres
        registres (`opsys.stockage.maillons`). Aucun département de production ne l'implémente
        encore (PLAN T1.3-b/c) ; le mécanisme est exercé par les départements de démonstration des
        tests du socle.
        """
        module = importlib.import_module(self.module_outils)
        fonction = getattr(module, "attentes", None)
        if fonction is not None and not callable(fonction):
            raise TypeError(f"{self.id} : {self.module_outils}.attentes doit être appelable")
        return fonction


def _texte(donnees: Mapping[str, Any], cle: str, contexte: str) -> str:
    valeur = donnees.get(cle)
    if not isinstance(valeur, str) or not valeur.strip():
        raise ValueError(f"{contexte} : champ texte requis manquant ou vide : {cle}")
    return valeur.strip()


def _liste(donnees: Mapping[str, Any], cle: str, contexte: str) -> tuple[str, ...]:
    valeur = donnees.get(cle, [])
    if valeur is None:
        return ()
    if not isinstance(valeur, list) or not all(isinstance(v, str) and v for v in valeur):
        raise ValueError(f"{contexte} : {cle} doit être une liste de chaînes non vides")
    return tuple(valeur)


def _entier_positif(donnees: Mapping[str, Any], cle: str, contexte: str) -> int:
    valeur = donnees.get(cle)
    if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur <= 0:
        raise ValueError(f"{contexte} : {cle} doit être un entier strictement positif")
    return valeur


def _politique_approbation(donnees: Mapping[str, Any], ctx: str) -> PolitiqueApprobation:
    """`approbations: {n3, n4}` (ADR-0009 §5) : rôles autorisés à décider par niveau N.

    Bloc entièrement optionnel ; absent, ou un niveau qu'il ne couvre pas, retombe sur
    `DEFAUT_ROLES_NIVEAU` (fail-closed, ADR-0009 §5). N5 ne se déclare PAS ici : c'est une
    frontière fixe de l'ADR (« la signature de nathan_owner », en plus de l'attestation du
    professionnel, jamais automatique, jamais déléguée) — elle retombe donc toujours sur
    `DEFAUT_ROLES_NIVEAU` (nathan_owner seul), sans exception possible depuis un manifeste.
    """
    brut = donnees.get("approbations")
    if brut is None:
        return POLITIQUE_PAR_DEFAUT
    if not isinstance(brut, Mapping):
        raise ValueError(f"{ctx} : approbations doit être un objet ({{n3, n4}})")
    if "n5" in brut:
        raise ValueError(
            f"{ctx} : approbations.n5 ne se déclare pas dans un manifeste : N5 est fixé système à "
            "nathan_owner seul (ADR-0009 §5 — jamais automatique, jamais délégué à un autre rôle)"
        )
    inconnues = sorted(set(brut) - set(_CLES_POLITIQUE))
    if inconnues:
        raise ValueError(f"{ctx} : approbations : clé(s) inconnue(s) {inconnues} (attendu : n3, n4)")
    roles: dict[Niveau, frozenset[str]] = {}
    for cle, niveau in _CLES_POLITIQUE.items():
        if cle not in brut:
            continue
        valeur = brut[cle]
        if not isinstance(valeur, list) or not valeur or not all(isinstance(r, str) and r for r in valeur):
            raise ValueError(f"{ctx} : approbations.{cle} doit être une liste non vide de rôles")
        ensemble = frozenset(valeur)
        inconnus = sorted(ensemble - ROLES)
        if inconnus:
            raise ValueError(
                f"{ctx} : approbations.{cle} : rôle(s) inconnu(s) {inconnus} (ADR-0009 §5 : {sorted(ROLES)})"
            )
        roles[niveau] = ensemble
    return PolitiqueApprobation(roles=roles)


def _constats_planifies(donnees: Mapping[str, Any], ctx: str, code: str) -> tuple[ConstatPlanifie, ...]:
    """`constats_planifies:` (optionnel) : les résumés de routine du département, déclenchés par le planificateur
    durable. Schéma fermé, fail-closed : une clé inconnue, un outil d'un autre département, un calcul hors grammaire ou
    un doublon est un refus, jamais ignoré."""
    brut = donnees.get("constats_planifies")
    if brut is None:
        return ()
    if not isinstance(brut, list):
        raise ValueError(f"{ctx} : constats_planifies doit être une liste")
    prefixe = code.lower() + "_"
    vus: set[str] = set()
    constats: list[ConstatPlanifie] = []
    for entree in brut:
        if not isinstance(entree, dict):
            raise ValueError(f"{ctx} : chaque constat planifié doit être un objet")
        inconnues = sorted(set(entree) - {"nom", "outil", "mesures", "appels", "description"})
        if inconnues:
            raise ValueError(f"{ctx} : constats_planifies : clé(s) inconnue(s) {inconnues}")
        nom = _texte(entree, "nom", ctx)
        if not _NOM_CONSTAT.match(nom) or nom in vus:
            raise ValueError(f"{ctx} : constat planifié {nom!r} : nom invalide ou en double (a-z, 0-9, tiret, 24 max)")
        vus.add(nom)
        outil = _texte(entree, "outil", ctx)
        if not outil.startswith(prefixe):
            raise ValueError(f"{ctx} : constat {nom!r} : l'outil {outil!r} doit commencer par {prefixe}")
        mesures = _liste(entree, "mesures", ctx)
        if not mesures or len(set(mesures)) != len(mesures) or not all(_MESURE_M8.match(m) for m in mesures):
            raise ValueError(f"{ctx} : constat {nom!r} : mesures M8 requises (m8_…, sans doublon)")
        appels_bruts = entree.get("appels")
        if (not isinstance(appels_bruts, list) or not 1 <= len(appels_bruts) <= APPELS_PAR_CONSTAT_MAX
                or not all(isinstance(a, dict) and a for a in appels_bruts)):
            raise ValueError(f"{ctx} : constat {nom!r} : 1 à {APPELS_PAR_CONSTAT_MAX} appels (objets non vides)")
        appels = tuple(_arguments_constat(a, ctx, nom) for a in appels_bruts)
        description = entree.get("description", "")
        if not isinstance(description, str) or len(description) > 400:
            raise ValueError(f"{ctx} : constat {nom!r} : description de 400 caractères au plus")
        constats.append(ConstatPlanifie(nom=nom, outil=outil, mesures=mesures, appels=appels,
                                        description=" ".join(description.split())))
    return tuple(constats)


def _routines_planifiees(donnees: Mapping[str, Any], ctx: str, code: str) -> tuple[RoutinePlanifiee, ...]:
    """`routines_planifiees:` (optionnel) : le travail interne déterministe du département que le planificateur durable
    déclenche. Schéma fermé, fail-closed : une clé inconnue, un outil d'un autre département, une cadence double ou hors
    forme, un doublon est un refus, jamais ignoré."""
    brut = donnees.get("routines_planifiees")
    if brut is None:
        return ()
    if not isinstance(brut, list):
        raise ValueError(f"{ctx} : routines_planifiees doit être une liste")
    prefixe = code.lower() + "_"
    vus: set[str] = set()
    routines: list[RoutinePlanifiee] = []
    for entree in brut:
        if not isinstance(entree, dict):
            raise ValueError(f"{ctx} : chaque routine planifiée doit être un objet")
        inconnues = sorted(set(entree) - {"nom", "outils", "cadence", "description"})
        if inconnues:
            raise ValueError(f"{ctx} : routines_planifiees : clé(s) inconnue(s) {inconnues}")
        nom = _texte(entree, "nom", ctx)
        if not _NOM_ROUTINE.match(nom) or nom in vus:
            raise ValueError(f"{ctx} : routine planifiée {nom!r} : nom invalide ou en double (a-z, 0-9, tiret, 24 max)")
        vus.add(nom)
        outils = _liste(entree, "outils", ctx)
        if (not outils or len(outils) > OUTILS_PAR_ROUTINE_MAX or len(set(outils)) != len(outils)
                or not all(o.startswith(prefixe) for o in outils)):
            raise ValueError(f"{ctx} : routine {nom!r} : 1 à {OUTILS_PAR_ROUTINE_MAX} outils distincts du département "
                             f"(préfixe {prefixe})")
        cadence_brute = entree.get("cadence")
        if not isinstance(cadence_brute, dict) or len(cadence_brute) != 1:
            raise ValueError(f"{ctx} : routine {nom!r} : cadence = un seul de {list(GENRES_CADENCE_ROUTINE)}")
        genre, valeur = next(iter(cadence_brute.items()))
        if genre not in GENRES_CADENCE_ROUTINE:
            raise ValueError(
                f"{ctx} : routine {nom!r} : cadence {genre!r} inconnue (attendu {list(GENRES_CADENCE_ROUTINE)})"
            )
        if genre == "intervalle_s":
            if (isinstance(valeur, bool) or not isinstance(valeur, int)
                    or not INTERVALLE_ROUTINE_MIN_S <= valeur <= INTERVALLE_ROUTINE_MAX_S):
                raise ValueError(f"{ctx} : routine {nom!r} : intervalle_s de {INTERVALLE_ROUTINE_MIN_S} à "
                                 f"{INTERVALLE_ROUTINE_MAX_S} secondes")
        elif not isinstance(valeur, str) or not valeur.strip():
            raise ValueError(f"{ctx} : routine {nom!r} : cadence {genre} : texte requis")
        elif genre == "cron" and not _CRON.match(valeur.strip()):
            raise ValueError(f"{ctx} : routine {nom!r} : expression cron invalide {valeur!r} (5 champs)")
        description = entree.get("description", "")
        if not isinstance(description, str) or len(description) > 400:
            raise ValueError(f"{ctx} : routine {nom!r} : description de 400 caractères au plus")
        routines.append(RoutinePlanifiee(nom=nom, outils=outils,
                                         cadence=(genre, valeur if genre == "intervalle_s" else valeur.strip()),
                                         description=" ".join(description.split())))
    return tuple(routines)


def _arguments_constat(appel: Mapping[str, Any], ctx: str, nom: str) -> tuple[tuple[str, str, Any], ...]:
    sortie: list[tuple[str, str, Any]] = []
    for argument in sorted(appel):
        spec = appel[argument]
        if not isinstance(argument, str) or not _ARGUMENT_OUTIL.match(argument):
            raise ValueError(f"{ctx} : constat {nom!r} : nom d'argument invalide {argument!r}")
        if not isinstance(spec, dict) or len(spec) != 1 or next(iter(spec)) not in ("calcul", "valeur"):
            raise ValueError(f"{ctx} : constat {nom!r} : argument {argument!r} : {{calcul: …}} ou {{valeur: …}}")
        genre, valeur = next(iter(spec.items()))
        if genre == "calcul":
            if not isinstance(valeur, str) or not CALCUL_CONSTAT.match(valeur):
                raise ValueError(f"{ctx} : constat {nom!r} : calcul {valeur!r} hors grammaire "
                                 "(instant, jour, debut_mois, fin_mois, lundi, avec décalage ±N)")
            decalage = valeur.lstrip("abcdefghijklmnopqrstuvwxyz_")
            if decalage and abs(int(decalage)) > OFFSET_CALCUL_MAX:
                raise ValueError(f"{ctx} : constat {nom!r} : décalage de {valeur!r} au-delà de {OFFSET_CALCUL_MAX}")
        elif isinstance(valeur, bool) or not isinstance(valeur, (str, int)) or (
                isinstance(valeur, str) and not 1 <= len(valeur) <= 80):
            raise ValueError(f"{ctx} : constat {nom!r} : valeur de {argument!r} : texte court ou entier")
        sortie.append((argument, genre, valeur))
    return tuple(sortie)


def lire_manifeste(dossier: Path) -> Departement:
    chemin = dossier / "department.yaml"
    donnees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    ctx = str(chemin)
    if not isinstance(donnees, dict):
        raise ValueError(f"{ctx} : le manifeste doit être un objet YAML")
    if donnees.get("schema") != SCHEMA:
        raise ValueError(f"{ctx} : schema attendu {SCHEMA!r}")

    ident = _texte(donnees, "id", ctx)
    if not _ID.match(ident) or ident != dossier.name:
        raise ValueError(f"{ctx} : id {ident!r} invalide ou différent du dossier {dossier.name!r}")
    code = _texte(donnees, "code", ctx)
    if not _CODE.match(code) or int(code[1:]) != int(ident[1:3]):
        raise ValueError(f"{ctx} : code {code!r} incohérent avec l'id {ident!r}")

    modeles = donnees.get("modeles", {"defaut": "standard"})
    if not isinstance(modeles, dict) or "defaut" not in modeles:
        raise ValueError(f"{ctx} : modeles doit contenir au moins 'defaut'")
    for usage, palier in modeles.items():
        if palier not in PALIERS:
            raise ValueError(f"{ctx} : palier {palier!r} pour {usage!r} (attendu : {PALIERS})")

    skills = _liste(donnees, "skills", ctx)
    for skill in skills:
        if not _SKILL.match(skill):
            raise ValueError(f"{ctx} : nom de skill invalide {skill!r}")
        if not (dossier / "skills" / skill / "SKILL.md").is_file():
            raise ValueError(f"{ctx} : skills/{skill}/SKILL.md introuvable")

    planifications = []
    for brut in donnees.get("planifications", []) or []:
        if not isinstance(brut, dict):
            raise ValueError(f"{ctx} : chaque planification doit être un objet")
        cron = _texte(brut, "cron", ctx)
        if not _CRON.match(cron):
            raise ValueError(f"{ctx} : expression cron invalide {cron!r} (5 champs)")
        remplacee_par = brut.get("remplacee_par")
        if remplacee_par is not None and (not isinstance(remplacee_par, str) or not _NOM_ROUTINE.match(remplacee_par)):
            raise ValueError(f"{ctx} : planification : remplacee_par doit nommer une routine planifiée du département")
        planifications.append(
            Planification(nom=_texte(brut, "nom", ctx), cron=cron, consigne=_texte(brut, "consigne", ctx),
                          remplacee_par=remplacee_par)
        )

    budget_brut = donnees.get("budget")
    if not isinstance(budget_brut, dict):
        raise ValueError(f"{ctx} : budget requis (tokens_jour, tokens_mois)")
    alerte = budget_brut.get("alerte_pct", 80)
    if isinstance(alerte, bool) or not isinstance(alerte, int) or not 1 <= alerte <= 100:
        raise ValueError(f"{ctx} : budget.alerte_pct doit être un entier entre 1 et 100")
    budget = Budget(
        tokens_jour=_entier_positif(budget_brut, "tokens_jour", ctx),
        tokens_mois=_entier_positif(budget_brut, "tokens_mois", ctx),
        alerte_pct=alerte,
    )
    if budget.tokens_mois < budget.tokens_jour:
        raise ValueError(f"{ctx} : budget.tokens_mois doit être >= tokens_jour")

    memoire = donnees.get("memoire", {}) or {}
    evenements = donnees.get("evenements", {}) or {}
    if not isinstance(evenements, dict):
        raise ValueError(f"{ctx} : evenements doit être un objet ({{publie, consomme}})")
    evenements_publie = _liste(evenements, "publie", ctx)
    evenements_consomme = _liste(evenements, "consomme", ctx)
    canaux = _liste(donnees, "canaux", ctx)
    for id_canal in canaux:
        if id_canal not in CANAUX:
            raise ValueError(f"{ctx} : canal inconnu {id_canal!r} (canaux connus : {', '.join(sorted(CANAUX))})")
    if len(set(canaux)) != len(canaux):
        raise ValueError(f"{ctx} : canaux en double : {list(canaux)}")
    kpis = []
    for brut in donnees.get("kpis", []) or []:
        if not isinstance(brut, dict):
            raise ValueError(f"{ctx} : chaque KPI doit être un objet")
        kpis.append(Kpi(id=_texte(brut, "id", ctx), description=_texte(brut, "description", ctx)))

    if not (dossier / "SOUL.md").is_file():
        raise ValueError(f"{ctx} : SOUL.md introuvable à côté du manifeste")

    return Departement(
        id=ident,
        code=code,
        nom=_texte(donnees, "nom", ctx),
        mission=_texte(donnees, "mission", ctx),
        module_outils=_texte(donnees, "outils", ctx),
        mode=valider_mode(donnees.get("mode", "ombre")),
        dependances=_liste(donnees, "dependances", ctx),
        modeles=dict(modeles),
        skills=skills,
        planifications=tuple(planifications),
        budget=budget,
        memoire_lecture=_liste(memoire, "lecture", ctx),
        memoire_ecriture=_liste(memoire, "ecriture", ctx),
        kpis=tuple(kpis),
        racine=dossier,
        evenements_publie=evenements_publie,
        evenements_consomme=evenements_consomme,
        politique_approbation=_politique_approbation(donnees, ctx),
        canaux=canaux,
        avatar=normaliser_avatar(donnees["avatar"], ctx) if "avatar" in donnees else None,
        constats_planifies=_constats_planifies(donnees, ctx, code),
        routines_planifiees=_routines_planifiees(donnees, ctx, code),
    )


def racine_departements() -> Path:
    """Dossier `departments/` du dépôt ou de l'installation (OPSYS_DEPARTMENTS le remplace)."""
    import os

    env = os.environ.get("OPSYS_DEPARTMENTS")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "departments"


def charger_departements(racine: Path | None = None) -> dict[str, Departement]:
    """Charge tous les départements ayant un manifeste, triés par numéro (M1 → M10)."""
    base = racine or racine_departements()
    departements = [lire_manifeste(d) for d in sorted(base.iterdir()) if (d / "department.yaml").is_file()]
    departements.sort(key=lambda d: d.numero)
    return {d.id: d for d in departements}


def dependances_manquantes(departements: Mapping[str, Departement]) -> dict[str, list[str]]:
    """Départements dont une dépendance déclarée n'est pas installée (vide = cohérent)."""
    manquantes = {}
    for dep in departements.values():
        absentes = sorted(set(dep.dependances) - set(departements))
        if absentes:
            manquantes[dep.id] = absentes
    return manquantes


def tous_les_outils(
    departements: Iterable[Departement],
    *,
    ports_prives: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, tuple[Departement, Outil]]:
    """Index global nom d'outil -> (département, outil), avec contrôle d'unicité."""
    index: dict[str, tuple[Departement, Outil]] = {}
    ports = dict(ports_prives or {})
    for dep in departements:
        for outil in dep.charger_outils(ports_prives=ports.pop(dep.id, None)):
            if outil.nom in index:
                raise ValueError(f"outil {outil.nom} déclaré par deux départements")
            index[outil.nom] = (dep, outil)
    if ports:
        raise ValueError(f"ports privés pour départements absents : {sorted(ports)}")
    return index


def verifier_attentes(departements: Mapping[str, Departement]) -> list[str]:
    """`opsys-metier verifier` : chaque `attentes()` déclaré (s'il y en a un) doit au moins se charger.

    Même esprit que `evenements.verifier_coherence` : un département cassé est signalé, jamais une
    panne de la commande. `file_proprietaire` retente le même chargement (et l'appel) à l'usage ;
    cette fonction ne fait que le vérifier tôt, en CI.
    """
    problemes: list[str] = []
    for dep in departements.values():
        try:
            dep.charger_attentes()
        except Exception as exc:  # noqa: BLE001 — signalé, jamais une panne de `opsys-metier verifier`
            problemes.append(f"{dep.id} : attentes() illisible ({type(exc).__name__}: {exc})")
    return problemes


def verifier_portees(departements: Mapping[str, Departement]) -> list[str]:
    """`opsys-metier verifier` : chaque `Outil.roles_appareil` déclaré (T1.4-j) ne cite que des rôles
    d'appareil (`opsys.appareils.ROLES_APPAREIL`), et aucun outil T3/N5 n'en déclare.

    Un rôle hors de `ROLES_APPAREIL` n'accorderait rien (`openclaw.roles_outils` l'ignore) mais serait
    une déclaration trompeuse : `client` passe par un lien tokenisé et jamais par un appareil apparié
    (R12 §6), l'appareil du propriétaire est appairé `admin`. Un outil T3/N5 n'est jamais projeté non
    plus (`Outil.frontiere_humaine`) : le déclarer est refusé pour que l'erreur se voie, pas
    seulement pour qu'elle soit sans effet. Une liste vide est le défaut (fermé), jamais un problème.
    """
    problemes: list[str] = []
    for dep in departements.values():
        for outil in dep.charger_outils():
            if not outil.roles_appareil:
                continue
            declares = sorted(outil.roles_appareil)
            if outil.frontiere_humaine:
                problemes.append(
                    f"{dep.id} : {outil.nom} est T3/N5 (frontière humaine, ADR-0009 §5) et déclare "
                    f"roles_appareil {declares} : aucun rôle d'appareil ne peut l'appeler"
                )
            for role in sorted(outil.roles_appareil - ROLES_APPAREIL):
                if role in ROLES:
                    raison = (
                        "rôle OPSYS mais pas un rôle d'appareil (le client passe par un lien tokenisé, "
                        "l'appareil du propriétaire est appairé admin)"
                    )
                else:
                    raison = "rôle inconnu"
                problemes.append(
                    f"{dep.id} : {outil.nom} : roles_appareil cite {role!r}, {raison} "
                    f"(attendu : {sorted(ROLES_APPAREIL)})"
                )
    return problemes
