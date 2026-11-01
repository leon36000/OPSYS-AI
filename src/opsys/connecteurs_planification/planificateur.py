"""Un tour du planificateur des connecteurs : borné, sous l'acteur système, un exécuteur après l'autre.

Pour chaque exécuteur connu (`etat.DEFINITIONS`) :

1. le mode est relu EN BASE (`inactif` par défaut, par expiration, par ligne absente ou par coupe-circuit
   `OPSYS_PLANIFICATEUR_CONNECTEURS=0`) : un exécuteur inactif ne fait rien, pas même une lecture chez un fournisseur ;
2. la plage horaire est RÉSERVÉE par comparaison-échange (`prochain_passage`) : deux processus ne se partagent jamais
   le même créneau ;
3. `ombre` : l'exécuteur CONSTATE ce qu'il ferait (lecture de la base d'OPSYS seulement), le tour le journalise ;
   `actif` : pour chaque ressource, un BAIL (un seul exécuteur à la fois) puis `traiter`, bail libéré dans tous
   les cas ;
4. le résultat est journalisé (append-only) et le dernier passage retenu.

Arrêt propre : `demander_arret()` pose un drapeau lu entre deux ressources et avant chaque page ; le tour s'arrête,
libère ses baux et rend la main. L'acteur système (`service_acteur_systeme.contexte_planificateur`) n'existe que
pendant le tour, hors requête ; il ne signe jamais une approbation et n'exécute une action de niveau N3 ou plus que
par l'approbation humaine consommée que chaque exécuteur exige (envoi : jeton lié à l'empreinte ; publication :
approbation consignée, non expirée, à usage unique).

Ce module n'appelle JAMAIS un fournisseur lui-même : il n'orchestre que.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import update

from .. import service_acteur_systeme as systeme
from .. import stockage
from ..courriel_connecteurs.erreurs import ErreurCourriel
from ..courriel_connecteurs.ingestion import LimiteurDebit
from ..courriel_connecteurs.reception import Recepteur
from ..stockage.schema import PLANIFICATEUR_EXECUTEURS as EXECUTEURS_T
from . import bail as baux
from . import etat, journal

_LOG = logging.getLogger("opsys.connecteurs_planification")
BAIL_DUREE_S = 120
RESSOURCES_PAR_PASSAGE = 50
DUREE_MAX_TOUR_S = 240
_ARRET = threading.Event()


def demander_arret() -> None:
    """Arrêt propre : le tour en cours s'interrompt entre deux ressources, libère ses baux et rend la main."""
    _ARRET.set()


def reinitialiser_arret() -> None:
    _ARRET.clear()


class RefusExecuteur(Exception):
    """Un exécuteur ne peut pas travailler (source illisible, journal altéré, port absent) : code typé, aucun
    contenu."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclasses.dataclass
class Ports:
    """Les points d'entrée vers l'extérieur, INJECTÉS : en production `hote.ports_par_defaut()`, en test des doubles.
    Un port absent veut dire « non raccordé » : l'exécuteur concerné ne fait rien et le dit."""

    service_courriel: Callable[[], Any] | None = None  # -> ServiceCourriel
    recepteur_m1: Recepteur | None = None
    client_wordpress: Callable[[Any], Any] | None = None  # SiteWordPress -> ClientWordPress | None
    adaptateurs_sociaux: Callable[[], Mapping[str, Any]] | None = None  # reseau -> AdaptateurReseau
    secret_social: Callable[[str], Callable[[], Any]] | None = None  # nom du secret -> FournisseurSecret
    politique_sociale: Any = None  # PolitiqueSas (défaut de prudence si None)
    horloge: Callable[[], float] = time.time
    validite_envoi_s: int | None = None
    taille_page: int = 50
    pages_par_passage: int = 5
    messages_par_minute: int = 120
    limiteurs: dict[str, LimiteurDebit] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class Contexte:
    ports: Ports
    acteur: Any
    porteur: str
    departements: Mapping[str, Any] | None
    debut: float

    def maintenant(self) -> float:
        return self.ports.horloge()

    def maintenant_dt(self) -> datetime:
        return datetime.fromtimestamp(self.maintenant(), UTC)

    def arret_demande(self) -> bool:
        return _ARRET.is_set() or self.maintenant() - self.debut > DUREE_MAX_TOUR_S

    def exiger_actif(self, bail: baux.Bail | None) -> baux.Bail | None:
        """À appeler avant chaque geste durable : arrêt demandé ou bail perdu = interruption typée."""
        if _ARRET.is_set():
            raise ErreurCourriel("REJ-COURRIEL-ARRET-DEMANDE", "arrêt propre demandé", 503, reprenable=True)
        if bail is None:
            return None
        renouvele = baux.renouveler(bail, BAIL_DUREE_S, horloge=self.ports.horloge)
        if renouvele is None:
            raise ErreurCourriel("REJ-COURRIEL-BAIL-PERDU", "bail repris par un autre exécuteur", 503, reprenable=True)
        return renouvele


class Executeur(Protocol):
    nom: str

    def ressources(self, ctx: Contexte) -> list[str]: ...

    def cle_bail(self, ressource: str) -> str: ...

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]: ...

    def traiter(self, ressource: str, ctx: Contexte, bail: baux.Bail) -> dict[str, Any]: ...


def executeurs_par_defaut() -> list[Executeur]:
    from .exec_courriel import Envoi, Synchro
    from .exec_m7 import PublicationSociale, PublicationWordPress, TransmissionWordPress

    return [Synchro(), Envoi(), TransmissionWordPress(), PublicationWordPress(), PublicationSociale()]


def _reserver_creneau(nom: str, maintenant: float) -> tuple[str, int]:
    """`(mode, intervalle)` si ce tour a le droit de passer ; `("inactif"|"pas_echu"|"deja_pris", 0)` sinon."""
    with stockage.transaction() as cnx:
        ligne = etat.ligne(cnx, nom)
        mode = etat.mode_effectif(ligne, maintenant)
        if mode == "inactif":
            return "inactif", 0
        if ligne["prochain_passage"] > maintenant:
            return "pas_echu", 0
        pris = cnx.execute(update(EXECUTEURS_T).where(
            EXECUTEURS_T.c.executeur == nom, EXECUTEURS_T.c.prochain_passage == ligne["prochain_passage"],
            EXECUTEURS_T.c.revision == ligne["revision"],
        ).values(prochain_passage=int(maintenant) + ligne["intervalle_s"]))
        if pris.rowcount != 1:
            return "deja_pris", 0
        return mode, ligne["intervalle_s"]


def _fin_de_passage(nom: str, maintenant: float, statut: str, code: str | None) -> None:
    with stockage.transaction() as cnx:
        cnx.execute(update(EXECUTEURS_T).where(EXECUTEURS_T.c.executeur == nom).values(
            dernier_passage=int(maintenant), dernier_statut=statut[:24], dernier_code=code))


def _cumuler(total: dict[str, int], partiel: Mapping[str, Any]) -> None:
    for cle, valeur in partiel.items():
        if type(valeur) is int:
            total[cle] = total.get(cle, 0) + valeur


def _passer(executeur: Executeur, mode: str, ctx: Contexte) -> dict[str, Any]:
    total: dict[str, int] = {"ressources": 0, "ignores": 0, "erreurs": 0}
    code: str | None = None
    try:
        if mode == "actif" and hasattr(executeur, "avant"):
            executeur.avant(ctx)
        ressources = executeur.ressources(ctx)[:RESSOURCES_PAR_PASSAGE]
    except RefusExecuteur as exc:
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, executeur.nom, "passage", systeme.IDENTIFIANT, mode=mode, statut="refus",
                                code=exc.code)
        return {"statut": "refus", "code": exc.code}
    for ressource in ressources:
        if ctx.arret_demande():
            code = "ARRET"
            break
        total["ressources"] += 1
        if mode == "ombre":
            try:
                _cumuler(total, executeur.constater(ressource, ctx))
            except RefusExecuteur as exc:
                total["erreurs"] += 1
                code = exc.code
            continue
        bail = baux.acquerir(executeur.cle_bail(ressource), ctx.porteur, BAIL_DUREE_S, horloge=ctx.ports.horloge)
        if bail is None:
            total["ignores"] += 1  # un autre exécuteur travaille cette ressource
            with stockage.transaction() as cnx:
                journal.journaliser(cnx, executeur.nom, "bail_refuse", systeme.IDENTIFIANT, ressource=ressource,
                                    mode=mode, statut="occupe")
            continue
        try:
            resultat = executeur.traiter(ressource, ctx, bail)
            _cumuler(total, resultat)
            if resultat.get("code"):
                code = str(resultat["code"])
        except ErreurCourriel as exc:
            if exc.code in {"REJ-COURRIEL-ARRET-DEMANDE", "REJ-COURRIEL-BAIL-PERDU"}:
                code = exc.code
                total["ignores"] += 1
            else:
                total["erreurs"] += 1
                code = exc.code
        except RefusExecuteur as exc:
            total["erreurs"] += 1
            code = exc.code
        except Exception:  # noqa: BLE001 — un défaut d'un exécuteur ne doit jamais arrêter le tour ni le serveur
            total["erreurs"] += 1
            code = "REJ-PLAN-DEFAUT-EXECUTEUR"
            _LOG.exception("planificateur : défaut de l'exécuteur %s sur %s", executeur.nom, ressource)
        finally:
            baux.liberer(bail)
    statut = "ombre" if mode == "ombre" else ("erreur" if total["erreurs"] else "ok")
    detail = {cle: valeur for cle, valeur in total.items() if cle in journal.DETAILS_PERMIS}
    if total["ressources"] or code is not None:  # un passage à vide ne grossit pas le journal (il est sur l'exécuteur)
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, executeur.nom, "passage", systeme.IDENTIFIANT, mode=mode, statut=statut,
                                code=code, details=detail)
    return {"statut": statut, "code": code, **total}


def tour(departements: Mapping[str, Any] | None = None, *, ports: Ports | None = None,
         executeurs: list[Executeur] | None = None, porteur: str | None = None) -> dict[str, Any]:
    """Un tour. Rend un résumé par exécuteur ; ne lève jamais pour un refus d'exécuteur."""
    if not etat.planificateur_autorise():
        return {"raison": "desactive", "executeurs": {}}
    if ports is None:
        from .hote import ports_par_defaut

        ports = ports_par_defaut()
    liste = executeurs if executeurs is not None else executeurs_par_defaut()
    porteur = porteur or f"plan-{uuid.uuid4().hex[:16]}"
    resume: dict[str, Any] = {"executeurs": {}}
    with systeme.contexte_planificateur() as acteur:
        ctx = Contexte(ports, acteur, porteur, departements, ports.horloge())
        for executeur in liste:
            if _ARRET.is_set():
                resume["raison"] = "arret"
                break
            systeme.verifier_planificateur(acteur)
            maintenant = ports.horloge()
            mode, _ = _reserver_creneau(executeur.nom, maintenant)
            if mode in ("inactif", "pas_echu", "deja_pris"):
                resume["executeurs"][executeur.nom] = {"statut": mode}
                continue
            resultat = _passer(executeur, mode, ctx)
            _fin_de_passage(executeur.nom, maintenant, resultat["statut"], resultat.get("code"))
            resume["executeurs"][executeur.nom] = {"mode": mode, **resultat}
    return resume


def tour_protege(departements: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Appelé par la boucle du serveur : jamais une exception vers la boucle."""
    try:
        return tour(departements)
    except Exception:  # noqa: BLE001
        _LOG.exception("planificateur des connecteurs : tour interrompu")
        return {"raison": "defaut", "executeurs": {}}
