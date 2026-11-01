"""États d'une publication sociale, calculés du journal append-only (jamais stockés ailleurs).

    brouillon -> en_attente_approbation -> approuve -> planifie -> publie
                                                              \\-> echec -> planifie (reprise bornée)
    (brouillon, en_attente_approbation, approuve, planifie, echec) -> annule

`publie` et `annule` sont terminaux (sauf une annulation posée pendant une tentative d'envoi ouverte : le message
peut sortir après elle, et le registre le dit : `publie`).
Seul `brouillon` se modifie (une révision d'une publication en attente la ramène
d'abord en brouillon : l'approbation demandée ne vaut plus rien pour un autre contenu). L'état d'une publication est le
PLIAGE de ses maillons ; un maillon qui n'est pas permis depuis l'état courant rend le journal incohérent (refus
`REJ-SOCIAL-JOURNAL-INCOHERENT`), jamais un état deviné.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from typing import Any

BROUILLON = "brouillon"
EN_ATTENTE = "en_attente_approbation"
APPROUVE = "approuve"
PLANIFIE = "planifie"
PUBLIE = "publie"
ECHEC = "echec"
ANNULE = "annule"
ETATS = (BROUILLON, EN_ATTENTE, APPROUVE, PLANIFIE, PUBLIE, ECHEC, ANNULE)

TRANSITIONS: Mapping[str, frozenset[str]] = {
    BROUILLON: frozenset({EN_ATTENTE, ANNULE}),
    EN_ATTENTE: frozenset({APPROUVE, BROUILLON, ANNULE}),
    APPROUVE: frozenset({PLANIFIE, ANNULE}),
    PLANIFIE: frozenset({PUBLIE, ECHEC, ANNULE}),
    ECHEC: frozenset({PLANIFIE, ANNULE}),
    PUBLIE: frozenset(),
    ANNULE: frozenset(),
}

# type de maillon -> état d'arrivée (le maillon `brouillon_revise` et `tentative` laissent l'état où il est, ou le
# ramènent en brouillon : voir `_appliquer`).
MAILLON_CREE = "brouillon_cree"
MAILLON_REVISE = "brouillon_revise"
MAILLON_SOUMISE = "soumise"
MAILLON_APPROUVEE = "approuvee"
MAILLON_PLANIFIEE = "planifiee"
MAILLON_TENTATIVE = "tentative"
MAILLON_PUBLIEE = "publiee"
MAILLON_ECHEC = "echec"
MAILLON_REPRISE = "reprise"
MAILLON_ANNULEE = "annulee"
TYPES_MAILLON = (
    MAILLON_CREE,
    MAILLON_REVISE,
    MAILLON_SOUMISE,
    MAILLON_APPROUVEE,
    MAILLON_PLANIFIEE,
    MAILLON_TENTATIVE,
    MAILLON_PUBLIEE,
    MAILLON_ECHEC,
    MAILLON_REPRISE,
    MAILLON_ANNULEE,
)
_ARRIVEE = {
    MAILLON_SOUMISE: EN_ATTENTE,
    MAILLON_APPROUVEE: APPROUVE,
    MAILLON_PLANIFIEE: PLANIFIE,
    MAILLON_PUBLIEE: PUBLIE,
    MAILLON_ECHEC: ECHEC,
    MAILLON_REPRISE: PLANIFIE,
    MAILLON_ANNULEE: ANNULE,
}

REJ_JOURNAL_INCOHERENT = "REJ-SOCIAL-JOURNAL-INCOHERENT"
TENTATIVES_MAX = 3


class JournalIncoherent(ValueError):
    """Un maillon qui n'a pas de sens depuis l'état courant : on ne devine pas, on s'arrête."""


@dataclasses.dataclass
class EtatPublication:
    publication_id: str
    etat: str
    reseau: str
    compte: str
    cle_idempotence: str
    publication: dict[str, Any]
    empreinte: str
    revision: int
    niveau_requis: int | None = None
    approbation: dict[str, Any] | None = None
    planifie_le: str | None = None
    tentatives: int = 0
    incertain: bool = False
    derniere_tentative_le: str | None = None
    id_externe: str | None = None
    url_externe: str | None = None
    publie_le: str | None = None
    derniere_erreur: dict[str, Any] | None = None
    rangs: list[int] = dataclasses.field(default_factory=list)

    def resume(self) -> dict[str, Any]:
        """Vue sans le texte ni les médias (la file se lit en bref ; `lire` donne le détail)."""
        return {
            "publication_id": self.publication_id,
            "etat": self.etat,
            "reseau": self.reseau,
            "compte": self.compte,
            "type_publication": self.publication["type_publication"],
            "planifie_le": self.planifie_le,
            "empreinte": self.empreinte,
            "revision": self.revision,
            "niveau_requis": self.niveau_requis,
            "tentatives": self.tentatives,
            "incertain": self.incertain,
            "id_externe": self.id_externe,
            "derniere_erreur": self.derniere_erreur,
        }


def transition_permise(depuis: str, vers: str) -> bool:
    return vers in TRANSITIONS.get(depuis, frozenset())


def _appliquer(etats: dict[str, EtatPublication], maillon: Mapping[str, Any]) -> None:
    type_maillon = maillon["type"]
    if type_maillon not in TYPES_MAILLON:
        raise JournalIncoherent(f"rang {maillon['rang']} : type de maillon inconnu {type_maillon!r}")
    identifiant = maillon.get("publication_id")
    if type_maillon == MAILLON_CREE:
        if identifiant in etats:
            raise JournalIncoherent(f"rang {maillon['rang']} : publication {identifiant} déjà créée")
        etats[identifiant] = EtatPublication(
            publication_id=identifiant,
            etat=BROUILLON,
            reseau=maillon["publication"]["reseau"],
            compte=maillon["publication"]["compte"],
            cle_idempotence=maillon["cle_idempotence"],
            publication=maillon["publication"],
            empreinte=maillon["empreinte"],
            revision=1,
            planifie_le=maillon["publication"]["planifie_le"],
            rangs=[maillon["rang"]],
        )
        return
    courant = etats.get(identifiant)
    if courant is None:
        raise JournalIncoherent(f"rang {maillon['rang']} : publication {identifiant!r} inconnue")
    courant.rangs.append(maillon["rang"])
    if type_maillon == MAILLON_REVISE:
        if courant.etat not in (BROUILLON, EN_ATTENTE):
            raise JournalIncoherent(f"rang {maillon['rang']} : révision interdite depuis {courant.etat}")
        courant.etat = BROUILLON
        courant.publication = maillon["publication"]
        courant.empreinte = maillon["empreinte"]
        courant.revision += 1
        courant.planifie_le = maillon["publication"]["planifie_le"]
        courant.niveau_requis = None
        courant.approbation = None
        return
    if type_maillon == MAILLON_TENTATIVE:
        if courant.etat != PLANIFIE:
            raise JournalIncoherent(f"rang {maillon['rang']} : tentative hors de l'état planifie ({courant.etat})")
        courant.tentatives += 1
        courant.incertain = True
        courant.derniere_tentative_le = maillon["horodatage"]
        return
    if courant.etat == ANNULE and courant.incertain and type_maillon in (MAILLON_PUBLIEE, MAILLON_ECHEC):
        # Une annulation a été posée PENDANT une tentative d'envoi ouverte : l'appel réseau a fini après elle. Le
        # registre dit la vérité sans devenir incohérent (il serait mort pour toujours) : un message sorti est `publie`
        # (rien ne se retire d'un réseau), un échec laisse l'annulation en place.
        if type_maillon == MAILLON_PUBLIEE:
            courant.etat = PUBLIE
            courant.incertain = False
            courant.id_externe = maillon["id_externe"]
            courant.url_externe = maillon.get("url")
            courant.publie_le = maillon["publie_le"]
            courant.derniere_erreur = None
        else:
            courant.incertain = bool(maillon["resultat_incertain"])
            courant.derniere_erreur = {
                "code": maillon["code"],
                "detail": maillon["detail"],
                "transitoire": maillon["transitoire"],
            }
        return
    cible = _ARRIVEE[type_maillon]
    if not transition_permise(courant.etat, cible):
        raise JournalIncoherent(f"rang {maillon['rang']} : {courant.etat} -> {cible} interdit")
    courant.etat = cible
    if type_maillon == MAILLON_SOUMISE:
        courant.niveau_requis = maillon["niveau_requis"]
    elif type_maillon == MAILLON_APPROUVEE:
        courant.approbation = {
            "empreinte": maillon["empreinte"],
            "niveau": maillon["niveau"],
            "approbation": dict(maillon["approbation"]),
        }
    elif type_maillon == MAILLON_PLANIFIEE:
        courant.planifie_le = maillon["planifie_le"]
    elif type_maillon == MAILLON_REPRISE:
        courant.derniere_erreur = None
    elif type_maillon == MAILLON_PUBLIEE:
        courant.incertain = False
        courant.id_externe = maillon["id_externe"]
        courant.url_externe = maillon.get("url")
        courant.publie_le = maillon["publie_le"]
        courant.derniere_erreur = None
    elif type_maillon == MAILLON_ECHEC:
        courant.incertain = bool(maillon["resultat_incertain"])
        courant.derniere_erreur = {
            "code": maillon["code"],
            "detail": maillon["detail"],
            "transitoire": maillon["transitoire"],
        }


def plier(journal: Iterable[Any]) -> dict[str, EtatPublication]:
    """L'état de chaque publication. `JournalIncoherent` si un maillon n'a pas de sens."""
    etats: dict[str, EtatPublication] = {}
    for maillon in journal:
        _appliquer(etats, maillon)
    return etats


def index_cles(etats: Mapping[str, EtatPublication]) -> dict[tuple[str, str, str], str]:
    """`(réseau, compte, clé d'idempotence) -> publication_id` : une clé, une publication."""
    return {(e.reseau, e.compte, e.cle_idempotence): e.publication_id for e in etats.values()}
