"""Les routines planifiées : un département DÉCLARE (manifeste, bloc `routines_planifiees`) un travail interne
déterministe,
le planificateur durable le déclenche (docs/architecture/PLANIFICATION.md §10).

Là où un « constat » (`constats.py`) publie un résumé au bus pour M8, une routine enchaîne des outils N0 à N2 du
département
(lire, énumérer, consigner) pour que ce qui exigeait un tour d'agent se fasse sans agent : le digest de la réception,
les
alertes internes de M1, la consolidation nocturne des affaires de M10, l'audit « non-oubli », le calcul des KPI. Ce que
le
socle sait faire ici, et rien de plus :

- lire les déclarations des départements installés (`declarations`) et en tirer une `Definition` d'exécuteur par
routine :
  nom `<mN>.routine.<nom>`, niveau N2, famille « routines », intervalle PAR DÉFAUT dérivé de la cadence déclarée. Le
  socle ne contient aucun horaire ni aucun nom de département : tout vient des manifestes ;
- résoudre la cadence : `suit` reprend le cron d'une planification du même département (jamais recopié), `cron` est
  déclaré dans la routine, `intervalle_s` est un entier de secondes. Un cron se lit « minute heure * * jours » (heure
  locale de l'entreprise) : le planificateur sonde à `SONDAGE_DEFAUT_S` et la routine n'agit qu'à partir de l'heure
  déclarée, une fois par jour (jamais plus d'un retard de sondage) ;
- appeler les outils de la liste FERMÉE de la déclaration, N0 à N2, jamais une frontière humaine (`exec_departements.
  appeler_outil`) ;
- dire en `ombre` ce qu'elle ferait (lecture seule : l'écriture n'est jamais appelée) SANS rien consigner.

Idempotence : une routine à heure fixe travaille UN créneau (le jour local) ; une fois fait (ligne `ressource` du
journal
append-only, mode actif), les sondages suivants du jour ne font rien ; si le serveur s'arrête et redémarre, un seul
passage
a lieu pour le créneau courant — jamais un rattrapage des jours manqués. Les outils appelés sont eux-mêmes idempotents
(clé
d'écriture déterministe), de sorte qu'un double déclenchement (deuxième instance, réservation perdue) n'écrit rien de
plus.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .. import departements as modele
from .. import service_acteur_systeme as systeme
from .. import stockage
from ..outils import Autonomie
from ..stockage.schema import PLANIFICATEUR_JOURNAL
from . import etat, journal
from .exec_departements import NIVEAUX_AUTOMATIQUES, _ParOutils
from .planificateur import Contexte, RefusExecuteur

_LOG = logging.getLogger("opsys.connecteurs_planification.routines")
FAMILLE = "routines"
SONDAGE_DEFAUT_S = 900  # un cron est sondé toutes les 15 minutes : l'heure déclarée est tenue à ce retard près
INTERVALLE_MIN_S, INTERVALLE_MAX_S = 15, 86400
_CHAMP_CRON = re.compile(r"^[0-9]{1,2}$")
_JOURS = re.compile(r"^(?:\*|[0-7](?:-[0-7])?(?:,[0-7](?:-[0-7])?)*)$")


@dataclasses.dataclass(frozen=True)
class Declaration:
    departement: str  # identifiant du département (celui du manifeste)
    code: str  # code du département (M1 à M10)
    routine: modele.RoutinePlanifiee

    @property
    def nom(self) -> str:
        return nom_executeur(self.code, self.routine.nom)

    @property
    def cle(self) -> str:
        return f"{self.code.lower()}:{self.routine.nom}"


def nom_executeur(code: str, nom: str) -> str:
    return f"{code.lower()}.routine.{nom}"


def declarations(departements: Mapping[str, modele.Departement]) -> list[Declaration]:
    return [Declaration(d.id, d.code, r) for d in departements.values() for r in d.routines_planifiees]


# -- la cadence
# ---------------------------------------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class Planning:
    """Une heure locale et des jours de semaine (ISO : 1 = lundi … 7 = dimanche)."""

    minute: int
    heure: int
    jours: frozenset[int]

    def atteint(self, local: datetime) -> bool:
        """Vrai si l'instant local est un jour prévu, à l'heure déclarée ou après (le même jour)."""
        return local.isoweekday() in self.jours and (local.hour, local.minute) >= (self.heure, self.minute)


def analyser_cron(cron: str) -> Planning:
    """`minute heure * * jours` seulement (minute et heure fixes, jour du mois et mois à `*`, jours de semaine en `*`,
    liste ou intervalle ; 0 et 7 = dimanche). Toute autre forme est refusée (`ValueError`) : une cadence qu'on ne sait
    pas lire n'est jamais devinée."""
    champs = cron.split()
    if len(champs) != 5:
        raise ValueError(f"cron {cron!r} : 5 champs attendus")
    minute, heure, jour_mois, mois, jours = champs
    if (
        not _CHAMP_CRON.match(minute)
        or not _CHAMP_CRON.match(heure)
        or jour_mois != "*"
        or mois != "*"
        or not _JOURS.match(jours)
    ):
        raise ValueError(f"cron {cron!r} : seule la forme « minute heure * * jours » est lue")
    if int(minute) > 59 or int(heure) > 23:
        raise ValueError(f"cron {cron!r} : heure ou minute hors bornes")
    retenus: set[int] = set()
    for morceau in [] if jours == "*" else jours.split(","):
        debut, _, fin = morceau.partition("-")
        bornes = range(int(debut), int(fin or debut) + 1)
        if int(fin or debut) < int(debut):
            raise ValueError(f"cron {cron!r} : intervalle de jours à l'envers")
        retenus.update(7 if j == 0 else j for j in bornes)
    return Planning(int(minute), int(heure), frozenset(range(1, 8)) if jours == "*" else frozenset(retenus))


def planning_de(declaration: Declaration, departements: Mapping[str, modele.Departement] | None) -> Planning | None:
    """Le planning d'une routine à heure fixe, ou `None` si elle est sondée à intervalle (pas d'heure)."""
    genre, valeur = declaration.routine.cadence
    if genre == "intervalle_s":
        return None
    if genre == "cron":
        return analyser_cron(valeur)
    departement = (departements or {}).get(declaration.departement)
    suivie = next((p for p in getattr(departement, "planifications", ()) if p.nom == valeur), None)
    if suivie is None:
        raise RefusExecuteur("REJ-PLAN-ROUTINE-CADENCE-ABSENTE")
    return analyser_cron(suivie.cron)


def _cadence_lisible(declaration: Declaration, departements: Mapping[str, modele.Departement]) -> str:
    genre, valeur = declaration.routine.cadence
    if genre == "intervalle_s":
        return f"toutes les {valeur} s"
    planning = planning_de(declaration, departements)
    jours = "tous les jours" if len(planning.jours) == 7 else "jours ISO " + ",".join(map(str, sorted(planning.jours)))
    origine = f"cron de la planification « {valeur} »" if genre == "suit" else f"cron déclaré « {valeur} »"
    return (
        f"{jours} à {planning.heure:02d} h {planning.minute:02d} (heure locale de l'entreprise ; {origine}), "
        f"sondé toutes les {SONDAGE_DEFAUT_S} s"
    )


# -- les définitions dérivées des manifestes --------------------------------------------------------------------------
_CACHE: dict[str, Any] = {"empreinte": None, "valeur": ()}


def _empreinte(racine: Path) -> tuple[Any, ...]:
    sortie: list[Any] = [str(racine)]
    for fichier in sorted(racine.glob("*/department.yaml")):
        try:
            info = fichier.stat()
            sortie.append((str(fichier), info.st_mtime_ns, info.st_size))
        except OSError:
            sortie.append((str(fichier), None, None))
    return tuple(sortie)


def _construire(racine: Path) -> tuple[tuple[Declaration, etat.Definition], ...]:
    deps = modele.charger_departements(racine)
    resultat: list[tuple[Declaration, etat.Definition]] = []
    for declaration in declarations(deps):
        genre, valeur = declaration.routine.cadence
        intervalle = valeur if genre == "intervalle_s" else SONDAGE_DEFAUT_S
        intervalle = min(max(intervalle, INTERVALLE_MIN_S), INTERVALLE_MAX_S)
        description = (
            f"{declaration.routine.description + ' ' if declaration.routine.description else ''}"
            f"Routine interne de {declaration.code} (outils : {', '.join(declaration.routine.outils)}). Cadence : "
            f"{_cadence_lisible(declaration, deps)}. Niveau N2, sans droit d'appareil ; aucun contact externe ; "
            "en ombre, rien n'est consigné."
        )
        definition = etat.Definition(
            declaration.nom,
            f"{declaration.code} : routine « {declaration.routine.nom} »",
            intervalle,
            "N2",
            description,
            famille=FAMILLE,
        )
        resultat.append((declaration, definition))
    return tuple(resultat)


def declarees(racine: Path | None = None) -> tuple[tuple[Declaration, etat.Definition], ...]:
    """Les routines déclarées par les manifestes des départements installés, avec leur définition. Fail-closed : si les
    manifestes sont illisibles, AUCUNE routine n'est exposée ; une cadence qui ne se lit pas est signalée par
    `problemes()`
    (la routine déclarée mais illisible n'est jamais planifiée avec une valeur supposée)."""
    racine = racine or modele.racine_departements()
    empreinte = _empreinte(racine)
    if _CACHE["empreinte"] != empreinte:
        try:
            valeur = _construire(racine)
        except Exception:  # noqa: BLE001 — la console et le tour ne doivent pas tomber pour une déclaration illisible
            _LOG.exception("routines planifiées : déclarations illisibles, aucune routine exposée")
            valeur = ()
        _CACHE["empreinte"], _CACHE["valeur"] = empreinte, valeur
    return _CACHE["valeur"]


def definitions_declarees(racine: Path | None = None) -> tuple[etat.Definition, ...]:
    return tuple(d for _, d in declarees(racine))


def implementations() -> dict[str, type]:
    """Les exécuteurs livrés, par `<mN>:<nom de la routine>`. Une déclaration sans classe n'est pas exécutée (et
    `problemes()` le dit) ; une classe sans déclaration n'est jamais instanciée."""
    from . import exec_m1, exec_m10

    return {**exec_m1.ROUTINES, **exec_m10.ROUTINES}


def executeurs(racine: Path | None = None) -> list[Any]:
    classes = implementations()
    return [classes[d.cle](d) for d, _ in declarees(racine) if d.cle in classes]


def problemes(departements: Mapping[str, modele.Departement] | None = None) -> list[str]:
    """Contrôle de cohérence (`opsys-metier verifier`) : chaque routine déclarée a une cadence lisible, des outils du
    département de niveau N0 à N2, autonomie T0 ou T1, sans frontière humaine ni droit d'appareil ; son exécuteur est
    livré ; les noms d'exécuteurs sont uniques et tiennent dans la table (40 caractères) ; une planification
    `remplacee_par` nomme une routine qui la suit réellement."""
    deps = departements if departements is not None else modele.charger_departements()
    trouves: list[str] = []
    classes = implementations()
    vus: set[str] = set()
    for declaration in declarations(deps):
        routine = declaration.routine
        etiquette = f"{declaration.departement} : routine {routine.nom!r}"
        if declaration.nom in vus or len(declaration.nom) > 40:
            trouves.append(f"{etiquette} : nom d'exécuteur {declaration.nom!r} en double ou trop long")
        vus.add(declaration.nom)
        if declaration.cle not in classes:
            trouves.append(f"{etiquette} : aucun exécuteur livré pour cette routine")
        try:
            planning_de(declaration, deps)
        except (ValueError, RefusExecuteur) as exc:
            trouves.append(f"{etiquette} : cadence illisible ({exc})")
        outils = {o.nom: o for o in deps[declaration.departement].charger_outils()}
        for nom in routine.outils:
            outil = outils.get(nom)
            if outil is None:
                trouves.append(f"{etiquette} : outil {nom!r} absent du département")
                continue
            if outil.niveau_effectif not in NIVEAUX_AUTOMATIQUES or outil.frontiere_humaine:
                trouves.append(
                    f"{etiquette} : outil {nom!r} de niveau {outil.niveau_effectif.value} "
                    "(N0 à N2 sans frontière humaine exigé)"
                )
            if outil.autonomie not in (Autonomie.T0, Autonomie.T1) or outil.roles_appareil:
                trouves.append(
                    f"{etiquette} : outil {nom!r} doit être agent seulement (T0 ou T1, aucun droit d'appareil)"
                )
    for dep in deps.values():
        noms = {r.nom: r for r in dep.routines_planifiees}
        for planification in dep.planifications:
            if planification.remplacee_par is None:
                continue
            routine = noms.get(planification.remplacee_par)
            if routine is None or routine.cadence != ("suit", planification.nom):
                trouves.append(
                    f"{dep.id} : planification {planification.nom!r} « remplacée » par "
                    f"{planification.remplacee_par!r}, qui n'existe pas ou ne la suit pas"
                )
    return trouves


# -- l'exécuteur
# ----------------------------------------------------------------------------------------------------------
class ExecuteurRoutine(_ParOutils):
    """Base d'une routine déclarée : sait quel est son créneau (jour local, heure déclarée), s'il est déjà fait, et
    appelle ses outils par la liste fermée de la déclaration. Les classes de `exec_m1.py` et `exec_m10.py` en
    dérivent."""

    def __init__(self, declaration: Declaration) -> None:
        self.declaration = declaration
        self.nom = declaration.nom
        self.departement = declaration.departement
        self.outils = declaration.routine.outils

    # -- le temps ----------------------------------------------------------------------------------------------------
    def echeance(self, ctx: Contexte) -> tuple[bool, str]:
        """`(dû, jour local)` : dû si l'heure déclarée du jour est atteinte (toujours dû pour une routine à
        intervalle)."""
        planning = planning_de(self.declaration, ctx.departements)
        local = ctx.maintenant_dt().astimezone(ZoneInfo(ctx.ports.fuseau))
        jour = local.date().isoformat()
        return (True if planning is None else planning.atteint(local)), jour

    def _intervalle(self) -> int:
        with stockage.transaction() as cnx:
            ligne = etat.ligne(cnx, self.nom)
        if ligne is not None:
            return int(ligne["intervalle_s"])
        definition = etat.definition(self.nom)
        return INTERVALLE_MAX_S if definition is None else definition.intervalle_defaut_s

    def deja_fait(self, ressource: str, ctx: Contexte) -> bool:
        """Vrai si ce créneau a déjà été traité : une ligne `ressource` en succès (mode actif), ou, en ombre, une ligne
        « aurait » (une seule fois par créneau : l'ombre ne répète pas son constat à chaque sondage). Les deux modes ne
        se confondent pas : un « aurait » d'hier n'empêche pas le passage actif."""
        mode = getattr(ctx, "mode", "actif")
        condition = (
            (PLANIFICATEUR_JOURNAL.c.evenement == "aurait") & (PLANIFICATEUR_JOURNAL.c.mode == "ombre")
            if mode == "ombre"
            else (PLANIFICATEUR_JOURNAL.c.evenement == "ressource")
            & (PLANIFICATEUR_JOURNAL.c.mode == "actif")
            & (PLANIFICATEUR_JOURNAL.c.statut == "ok")
        )
        with stockage.transaction() as cnx:
            ligne = cnx.execute(
                select(PLANIFICATEUR_JOURNAL.c.id)
                .where(
                    PLANIFICATEUR_JOURNAL.c.executeur == self.nom[:40],
                    PLANIFICATEUR_JOURNAL.c.ressource == ressource[:160],
                    condition,
                )
                .limit(1)
            ).first()
        return ligne is not None

    def _journaliser_aurait(self, ressource: str, **details: int) -> None:
        with stockage.transaction() as cnx:
            journal.journaliser(
                cnx, self.nom, "aurait", systeme.IDENTIFIANT, ressource=ressource, mode="ombre", details=details
            )

    @staticmethod
    def resultat(reponse: Any) -> dict[str, Any]:
        """Le contenu `resultat` d'une réponse d'outil `{"accepte": True, "resultat": {...}}` ; un refus rendu par
        l'outil devient un `RefusExecuteur` typé (le tour le journalise)."""
        if isinstance(reponse, dict) and reponse.get("accepte") is False:
            verdict = reponse.get("verdict")
            texte = str(verdict.get("code") if isinstance(verdict, dict) else verdict or "")
            trouve = re.search(r"REJ-[A-Z0-9]+(?:-[A-Z0-9]+)+", texte)
            raise RefusExecuteur(trouve.group(0) if trouve else "REJ-PLAN-ROUTINE-REFUSEE")
        if not isinstance(reponse, dict) or not isinstance(reponse.get("resultat"), dict):
            raise RefusExecuteur("REJ-PLAN-ROUTINE-REPONSE-ILLISIBLE")
        return reponse["resultat"]

    @staticmethod
    def instant_iso(ctx: Contexte) -> str:
        return ctx.maintenant_dt().astimezone(UTC).isoformat()
