"""Les constats planifiés : un département DÉCLARE (manifeste, bloc `constats_planifies`) un résumé de routine, le
planificateur durable le déclenche (docs/architecture/PLANIFICATION.md §9).

Ce que le socle sait faire ici, et rien de plus :

- lire les déclarations des départements installés (`declarations`) et en tirer une `Definition` d'exécuteur par constat
  (`definitions_declarees`) : nom `<mN>.constat.<nom>`, niveau N2, famille « constats », intervalle PAR DÉFAUT dérivé de
  la fraîcheur du catalogue de M8 (`m8_analytics.cadence_constats` : la plus stricte des fenêtres des mesures que le
  constat alimente, divisée par le nombre de passages par fenêtre). Le socle ne contient aucun horaire ni aucun nom de
  département : tout vient des manifestes et du catalogue ;
- exécuter un constat (`ExecuteurConstat`) en appelant l'outil déclaré, par la liste fermée et le contrôle de niveau
  de `exec_departements.appeler_outil` (N0 à N2, jamais une frontière humaine) ;
- dire en `ombre` ce qu'il ferait (outil présent, niveau, créneau, arguments calculés) SANS rien publier : l'outil
  publie au bus, et l'ombre ne publie jamais.

Idempotence : les arguments sont calculés sur le CRÉNEAU (le multiple de l'intervalle, compté depuis minuit local, qui
contient l'instant), jamais sur l'horloge du moment. Deux déclenchements du même créneau (redémarrage en cours de
cycle, deuxième instance) donnent donc
les MÊMES arguments, donc le même identifiant d'événement déterministe de l'outil, que le bus absorbe : un seul constat
publié. Un créneau suivant est un constat de plus, voulu (M4, M2, M6 : « un événement par constat »).

Aucun rattrapage en rafale : le créneau est réservé par comparaison-échange sur `prochain_passage = maintenant +
intervalle` (voir `planificateur._reserver_creneau`), jamais sur les créneaux manqués.
"""

from __future__ import annotations

import calendar
import dataclasses
import logging
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .. import departements as modele
from .. import service_acteur_systeme as systeme
from .. import stockage
from ..outils import Autonomie
from . import etat, journal
from .bail import Bail
from .exec_departements import NIVEAUX_AUTOMATIQUES, _ParOutils
from .planificateur import Contexte, NiveauInterdit, RefusExecuteur

_LOG = logging.getLogger("opsys.connecteurs_planification.constats")
FAMILLE = "constats"
INTERVALLE_MIN_S, INTERVALLE_MAX_S = 15, 86400  # les bornes du planificateur (`etat.appliquer`, contrainte de table)
_CODE = re.compile(r"REJ-[A-Z0-9]+(?:-[A-Z0-9]+)+")
_CALCUL = re.compile(r"^(instant|jour|debut_mois|fin_mois|lundi)([+-][0-9]{1,3})?$")


@dataclasses.dataclass(frozen=True)
class Declaration:
    departement: str  # identifiant du département (celui du manifeste)
    code: str  # code du département (M1 à M10)
    constat: modele.ConstatPlanifie

    @property
    def nom(self) -> str:
        return nom_executeur(self.code, self.constat.nom)


def nom_executeur(code: str, nom: str) -> str:
    return f"{code.lower()}.constat.{nom}"


def declarations(departements: Mapping[str, modele.Departement]) -> list[Declaration]:
    return [Declaration(d.id, d.code, c) for d in departements.values() for c in d.constats_planifies]


# -- le calcul des arguments (grammaire fermée, voir `departements.CALCUL_CONSTAT`) ------------------------------------
def evaluer_calcul(expression: str, creneau: datetime, fuseau: str) -> str:
    """La valeur d'un argument calculé pour un créneau : `instant` (ISO UTC), `jour`, `debut_mois`, `fin_mois` ou
    `lundi` (dates AAAA-MM-JJ du fuseau de l'entreprise) avec un décalage ±N (jours, mois ou semaines selon le mot)."""
    trouve = _CALCUL.match(expression)
    if trouve is None:
        raise RefusExecuteur("REJ-PLAN-CALCUL-INVALIDE")
    mot, decalage = trouve.group(1), int(trouve.group(2) or 0)
    if mot == "instant":
        return creneau.astimezone(UTC).isoformat()
    jour = creneau.astimezone(ZoneInfo(fuseau)).date()
    if mot == "jour":
        return (jour + timedelta(days=decalage)).isoformat()
    if mot == "lundi":
        return (jour - timedelta(days=jour.weekday()) + timedelta(weeks=decalage)).isoformat()
    index = jour.year * 12 + (jour.month - 1) + decalage
    annee, mois = divmod(index, 12)
    mois += 1
    if mot == "debut_mois":
        return date(annee, mois, 1).isoformat()
    return date(annee, mois, calendar.monthrange(annee, mois)[1]).isoformat()


def arguments_pour(appel: tuple[tuple[str, str, Any], ...], creneau: datetime, fuseau: str) -> dict[str, Any]:
    return {argument: evaluer_calcul(valeur, creneau, fuseau) if genre == "calcul" else valeur
            for argument, genre, valeur in appel}


_EPOQUE = datetime(1970, 1, 1)


def creneau(maintenant: float, intervalle_s: int, fuseau: str) -> datetime:
    """Le début du créneau qui contient `maintenant` : un multiple de l'intervalle compté depuis minuit LOCAL (fuseau de
    l'entreprise), rendu en UTC. Aligné sur la journée locale, le créneau d'un intervalle de 12 h ou de 24 h tombe
    toujours dans le jour local de l'instant : « aujourd'hui » vaut la même date pour tous les déclenchements du
    créneau (déterminisme) ET pour l'horloge du moment (la date du constat n'est jamais celle de la veille). Le calcul
    se fait sur l'heure locale (pas sur un décalage fixe) : deux déclenchements du même créneau, de part et d'autre d'un
    changement d'heure, donnent le même instant."""
    zone = ZoneInfo(fuseau)
    local = datetime.fromtimestamp(int(maintenant), UTC).astimezone(zone).replace(tzinfo=None)
    ecoule = int((local - _EPOQUE).total_seconds())
    debut = _EPOQUE + timedelta(seconds=ecoule // intervalle_s * intervalle_s)
    return debut.replace(tzinfo=zone).astimezone(UTC)


def _code_refus(resultat: Any) -> str | None:
    """Le code d'un refus que l'outil RENDRE (`{"accepte": False, "verdict": {...}}`) au lieu de le lever."""
    if not isinstance(resultat, dict) or resultat.get("accepte") is not False:
        return None
    verdict = resultat.get("verdict")
    texte = str(verdict.get("code") if isinstance(verdict, dict) else verdict or "")
    trouve = _CODE.search(texte)
    return trouve.group(0) if trouve else "REJ-PLAN-CONSTAT-REFUSE"


# -- l'exécuteur ------------------------------------------------------------------------------------------------------
class ExecuteurConstat(_ParOutils):
    """Un constat déclaré par un département : appelle SON outil, un jeu d'arguments après l'autre. Un jeu qui échoue
    n'empêche pas les suivants ; un échec est compté, son code typé est dit au tour, à la console et au journal."""

    def __init__(self, declaration: Declaration) -> None:
        self.declaration = declaration
        self.nom = declaration.nom
        self.departement = declaration.departement
        self.outils = (declaration.constat.outil,)

    def _intervalle(self) -> int:
        with stockage.transaction() as cnx:
            ligne = etat.ligne(cnx, self.nom)
        if ligne is not None:
            return int(ligne["intervalle_s"])
        definition = etat.definition(self.nom)
        return INTERVALLE_MAX_S if definition is None else definition.intervalle_defaut_s

    def _jeux(self, ctx: Contexte) -> list[dict[str, Any]]:
        instant = creneau(ctx.maintenant(), self._intervalle(), ctx.ports.fuseau)
        return [arguments_pour(appel, instant, ctx.ports.fuseau) for appel in self.declaration.constat.appels]

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        """Ombre : l'outil existe et son niveau est automatique, les arguments du créneau se calculent ; RIEN n'est
        appelé, donc rien n'est publié."""
        self._verifier(ctx)
        jeux = self._jeux(ctx)
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "aurait", systeme.IDENTIFIANT, ressource=ressource, mode="ombre",
                                details={"aurait": len(jeux)})
        return {"aurait": len(jeux)}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        jeux = self._jeux(ctx)
        faits = erreurs = 0
        code: str | None = None
        for arguments in jeux:
            bail = ctx.exiger_actif(bail) or bail
            try:
                resultat = self._appeler(ctx, self.declaration.constat.outil, arguments)
                refus = _code_refus(resultat)
                if refus is not None:
                    raise RefusExecuteur(refus)
                faits += 1
            except NiveauInterdit:
                raise
            except RefusExecuteur as exc:
                erreurs += 1
                code = exc.code
        self._clore(ressource, code, etapes=faits, erreurs=erreurs)
        return {"etapes": faits, "erreurs": erreurs, "code": code}


# -- les définitions dérivées des manifestes ---------------------------------------------------------------------------
_CACHE: dict[str, Any] = {"empreinte": None, "valeur": ()}


def _fichiers_sources(racine: Path) -> list[Path]:
    fichiers = sorted(racine.glob("*/department.yaml"))
    try:
        from m8_analytics import cadence_constats

        fichiers.append(cadence_constats._MANIFESTE)
        fichiers.extend(sorted((cadence_constats._MANIFESTE.parent / "definitions").glob("*.yaml")))
        fichiers.extend(sorted((cadence_constats._MANIFESTE.parent / "metrics").glob("*.yaml")))
    except ImportError:
        pass
    return fichiers


def _empreinte(racine: Path) -> tuple[Any, ...]:
    sortie: list[Any] = [str(racine)]
    for fichier in _fichiers_sources(racine):
        try:
            info = fichier.stat()
            sortie.append((str(fichier), info.st_mtime_ns, info.st_size))
        except OSError:
            sortie.append((str(fichier), None, None))
    return tuple(sortie)


def _construire(racine: Path) -> tuple[tuple[Declaration, etat.Definition], ...]:
    from m8_analytics import cadence_constats

    deps = modele.charger_departements(racine)
    resultat: list[tuple[Declaration, etat.Definition]] = []
    for declaration in declarations(deps):
        cadence = cadence_constats.cadence_par_defaut(declaration.constat.mesures)
        intervalle = min(max(cadence["intervalle_s"], INTERVALLE_MIN_S), INTERVALLE_MAX_S)
        constat = declaration.constat
        description = (
            f"Calcule et publie au bus, pour M8, le résumé de l'outil {constat.outil} (mesures alimentées : "
            f"{', '.join(constat.mesures)}). Cadence par défaut {intervalle} s : {cadence['passages_par_fenetre']} "
            f"passages par fenêtre de fraîcheur de {cadence['fenetre_s']} s (mesure la plus stricte : "
            f"{cadence['mesure_limitante']}). Niveau N2, sans droit d'appareil ; en ombre, rien n'est publié.")
        if constat.description:
            description = f"{constat.description} {description}"
        definition = etat.Definition(
            declaration.nom, f"{declaration.code} : constat « {constat.nom} »", intervalle, "N2", description,
            famille=FAMILLE)
        resultat.append((declaration, definition))
    return tuple(resultat)


def declarees(racine: Path | None = None) -> tuple[tuple[Declaration, etat.Definition], ...]:
    """Les constats déclarés par les manifestes des départements installés, avec leur définition. Fail-closed : si les
    manifestes ou le catalogue de M8 sont illisibles, AUCUN constat n'est exposé (et `problemes()` le dit) ; un constat
    dont la cadence ne se dérive pas n'est jamais planifié avec une valeur supposée."""
    racine = racine or modele.racine_departements()
    empreinte = _empreinte(racine)
    if _CACHE["empreinte"] != empreinte:
        try:
            valeur = _construire(racine)
        except Exception:  # noqa: BLE001 — la console et le tour ne doivent pas tomber pour une déclaration illisible
            _LOG.exception("constats planifiés : déclarations illisibles, aucun constat exposé")
            valeur = ()
        _CACHE["empreinte"], _CACHE["valeur"] = empreinte, valeur
    return _CACHE["valeur"]


def definitions_declarees(racine: Path | None = None) -> tuple[etat.Definition, ...]:
    return tuple(d for _, d in declarees(racine))


def executeurs(racine: Path | None = None) -> list[ExecuteurConstat]:
    return [ExecuteurConstat(declaration) for declaration, _ in declarees(racine)]


def problemes(departements: Mapping[str, modele.Departement] | None = None) -> list[str]:
    """Contrôle de cohérence (`opsys-metier verifier`) : chaque constat déclaré a un outil du département, de niveau
    N0 à N2, autonomie T1, sans frontière humaine ni droit d'appareil ; ses mesures sont au catalogue de M8 ; sa
    cadence se dérive ; les noms d'exécuteurs sont uniques et tiennent dans la table (40 caractères)."""
    deps = departements if departements is not None else modele.charger_departements()
    if not declarations(deps):
        return []
    try:
        from m8_analytics import cadence_constats
    except ImportError:
        return ["des constats sont déclarés mais le catalogue de M8 (m8_analytics) n'est pas installé : aucune cadence"]
    trouves: list[str] = []
    vus: set[str] = set()
    for declaration in declarations(deps):
        constat = declaration.constat
        etiquette = f"{declaration.departement} : constat {constat.nom!r}"
        if declaration.nom in vus or len(declaration.nom) > 40:
            trouves.append(f"{etiquette} : nom d'exécuteur {declaration.nom!r} en double ou trop long")
        vus.add(declaration.nom)
        outils = {o.nom: o for o in deps[declaration.departement].charger_outils()}
        outil = outils.get(constat.outil)
        if outil is None:
            trouves.append(f"{etiquette} : outil {constat.outil!r} absent du département")
        else:
            if outil.niveau_effectif not in NIVEAUX_AUTOMATIQUES or outil.frontiere_humaine:
                trouves.append(f"{etiquette} : outil {constat.outil!r} de niveau {outil.niveau_effectif.value} "
                               "(N0 à N2 sans frontière humaine exigé)")
            if outil.autonomie is not Autonomie.T1 or outil.roles_appareil:
                trouves.append(f"{etiquette} : outil {constat.outil!r} doit être agent seulement "
                               "(T1, aucun droit d'appareil)")
        for appel in constat.appels:
            for argument, genre, valeur in appel:
                if outil is not None and argument not in outil.parametres.get("properties", {}):
                    trouves.append(f"{etiquette} : argument {argument!r} inconnu de {constat.outil}")
                if genre == "calcul" and _CALCUL.match(valeur) is None:
                    trouves.append(f"{etiquette} : calcul {valeur!r} hors grammaire")
            if outil is not None:
                manquants = set(outil.parametres.get("required", [])) - {a for a, _, _ in appel}
                if manquants:
                    trouves.append(f"{etiquette} : argument(s) requis non fournis {sorted(manquants)}")
        try:
            cadence_constats.cadence_par_defaut(constat.mesures)
        except ValueError as exc:
            trouves.append(f"{etiquette} : cadence non dérivable ({exc})")
    return trouves
