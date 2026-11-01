"""Les gestes du sas de publication sociale, sur un journal append-only : composer, soumettre, approuver, annuler, lire.

Chaque geste lit le journal, le vérifie (chaîne de hachage), plie les états, contrôle, puis écrit AU PLUS les
maillons de
sa transition. Un refus n'écrit rien. Aucun geste ici ne publie : la sortie est `executeur.executer`, appelée par un
exécuteur hors transaction, jamais par un outil d'agent.

L'approbation exige : un humain décideur (le propriétaire) établi par la plateforme, l'EMPREINTE exacte du contenu
soumis, le NIVEAU de l'outil appelé (N3 pour une publication publique, N4 pour une annonce payante) et le succès de tous
les contrôles au moment même (fenêtre, quota, plafonds de budget). Elle écrit `approuvee` puis `planifiee` : l'heure
approuvée est celle de l'empreinte.

Le journal est n'importe quelle séquence `append`/`len`/itération (liste en test, registre durable en production).

Module sans entrée-sortie propre : l'horloge est un argument.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any

from .. import journal_chaine
from ..studio import portes
from . import etats, garde_fous, modele
from .etats import EtatPublication
from .politique import PolitiqueSas
from .reseaux import DeclarationReseau

ROLE_DECIDEUR = "nathan_owner"
_CLE = re.compile(r"[A-Za-z0-9_-]{16,64}")

REJ_JOURNAL_ALTERE = "REJ-SOCIAL-JOURNAL-ALTERE"
REJ_PUBLICATION_INCONNUE = "REJ-SOCIAL-PUBLICATION-INCONNUE"
REJ_CLE = "REJ-SOCIAL-CLE-INVALIDE"
REJ_CLE_CONFLIT = "REJ-SOCIAL-CLE-CONFLIT"
REJ_COMPTE_INCONNU = "REJ-SOCIAL-COMPTE-INCONNU"
REJ_IDENTITE_IMMUABLE = "REJ-SOCIAL-IDENTITE-IMMUABLE"
REJ_ETAT = "REJ-SOCIAL-ETAT"
REJ_EMPREINTE = "REJ-SOCIAL-EMPREINTE-DIFFERENTE"
REJ_HUMAIN = "REJ-SOCIAL-HUMAIN-REQUIS"
REJ_DEJA_PUBLIE = "REJ-SOCIAL-DEJA-PUBLIE"
REJ_ADAPTATEUR = "REJ-SOCIAL-ADAPTATEUR"


def _refus(code: str, chemin: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "refus": [{"code": code, "chemin": chemin, "detail": detail}]}


def identifiant_publication(reseau: str, compte: str, cle: str) -> str:
    """Déterministe : la même clé sur le même compte est la même publication, par construction."""
    return "pub-" + hashlib.sha256(f"{reseau}\n{compte}\n{cle}".encode()).hexdigest()[:20]


def charger(journal: Any) -> tuple[dict[str, EtatPublication], dict[str, Any] | None]:
    """(états, refus). Un journal dont la chaîne ne tient plus ou dont un maillon n'a pas de sens n'est pas lu."""
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return {}, _refus(REJ_JOURNAL_ALTERE, "$", "; ".join(problemes[:3]))
    try:
        return etats.plier(journal), None
    except etats.JournalIncoherent as exc:
        return {}, _refus(etats.REJ_JOURNAL_INCOHERENT, "$", str(exc))


def horaires_du_compte(
    tous: Mapping[str, EtatPublication],
    reseau: str,
    compte: str,
    exclure: str | None = None,
) -> list[datetime]:
    """Les instants qui comptent contre le quota du compte : publiées (à leur instant de publication), planifiées, et
    en échec après une tentative (la requête a pu consommer du quota) — pas les brouillons, ni les annulées."""
    instants = []
    for e in tous.values():
        if e.publication_id == exclure or (e.reseau, e.compte) != (reseau, compte):
            continue
        if e.etat == etats.PUBLIE:
            instants.append(modele.instant(e.publie_le or e.planifie_le))
        elif e.etat == etats.PLANIFIE or (e.etat == etats.ECHEC and e.tentatives):
            instants.append(modele.instant(e.planifie_le))
    return instants


def composer(
    journal: Any,
    donnees: Any,
    cle_idempotence: str,
    comptes_actifs: Collection[tuple[str, str]],
    par: str,
    horodatage: str,
    *,
    publication_id: str | None = None,
) -> dict[str, Any]:
    """Crée un brouillon, ou en révise un (`publication_id`). Même clé et même contenu : la même publication, rien
    d'écrit (`deja_cree`). Même clé et autre contenu : refus (`REJ-SOCIAL-CLE-CONFLIT`)."""
    tous, refus = charger(journal)
    if refus is not None:
        return refus
    publication, problemes = modele.depuis_dict(donnees)
    if publication is None:
        return {"accepte": False, "refus": problemes}
    if not isinstance(cle_idempotence, str) or not _CLE.fullmatch(cle_idempotence):
        return _refus(REJ_CLE, "$.cle_idempotence", "16 à 64 caractères [A-Za-z0-9_-]")
    if (publication.reseau, publication.compte) not in comptes_actifs:
        return _refus(
            REJ_COMPTE_INCONNU, "$.compte", f"compte {publication.compte!r} non enregistré pour {publication.reseau}"
        )
    contenu = modele.en_dict(publication)
    empreinte = modele.empreinte(publication)
    if publication_id is not None:
        courant = tous.get(publication_id)
        if courant is None:
            return _refus(REJ_PUBLICATION_INCONNUE, "$.publication_id", f"publication inconnue : {publication_id!r}")
        if (courant.reseau, courant.compte) != (publication.reseau, publication.compte):
            return _refus(
                REJ_IDENTITE_IMMUABLE,
                "$.compte",
                "le réseau et le compte d'une publication ne changent pas : en créer une autre",
            )
        if courant.etat not in (etats.BROUILLON, etats.EN_ATTENTE):
            return _refus(
                REJ_ETAT,
                "$.publication_id",
                f"publication {courant.etat} : seul un brouillon (ou une demande en attente) se révise",
            )
        if courant.empreinte == empreinte:
            return {
                "accepte": True,
                "publication_id": publication_id,
                "etat": courant.etat,
                "empreinte": empreinte,
                "revision": courant.revision,
                "deja_cree": True,
            }
        journal_chaine.ajouter(
            journal,
            etats.MAILLON_REVISE,
            {
                "publication_id": publication_id,
                "publication": contenu,
                "empreinte": empreinte,
                "par": par,
                "etat_avant": courant.etat,
            },
            horodatage,
        )
        return {
            "accepte": True,
            "publication_id": publication_id,
            "etat": etats.BROUILLON,
            "empreinte": empreinte,
            "revision": courant.revision + 1,
            "deja_cree": False,
        }
    identifiant = identifiant_publication(publication.reseau, publication.compte, cle_idempotence)
    existant = tous.get(identifiant)
    if existant is not None:
        if existant.empreinte != empreinte:
            return _refus(
                REJ_CLE_CONFLIT,
                "$.cle_idempotence",
                "cette clé désigne déjà une publication au contenu différent : une clé, une publication "
                f"({identifiant}) ; pour la modifier, la réviser par son identifiant",
            )
        return {
            "accepte": True,
            "publication_id": identifiant,
            "etat": existant.etat,
            "empreinte": empreinte,
            "revision": existant.revision,
            "deja_cree": True,
        }
    journal_chaine.ajouter(
        journal,
        etats.MAILLON_CREE,
        {
            "publication_id": identifiant,
            "publication": contenu,
            "empreinte": empreinte,
            "cle_idempotence": cle_idempotence,
            "par": par,
            "ia": {"texte": publication.divulgation.texte_ia, "media": modele.media_synthetique_realiste(publication)},
        },
        horodatage,
    )
    return {
        "accepte": True,
        "publication_id": identifiant,
        "etat": etats.BROUILLON,
        "empreinte": empreinte,
        "revision": 1,
        "deja_cree": False,
    }


def _etat(tous: Mapping[str, EtatPublication], publication_id: str) -> EtatPublication | dict[str, Any]:
    courant = tous.get(publication_id)
    if courant is None:
        return _refus(REJ_PUBLICATION_INCONNUE, "$.publication_id", f"publication inconnue : {publication_id!r}")
    return courant


def _publication(courant: EtatPublication) -> tuple[modele.Publication | None, dict[str, Any] | None]:
    """La publication relue du journal ET son empreinte recalculée : un contenu retouché dans le registre est vu ici."""
    publication, problemes = modele.depuis_dict(courant.publication)
    if publication is None:
        return None, {"accepte": False, "refus": problemes}
    if modele.empreinte(publication) != courant.empreinte:
        return None, _refus(REJ_EMPREINTE, "$", "le contenu du journal ne correspond plus à son empreinte")
    return publication, None


def _adaptateur_de(reseau: str, adaptateurs: Mapping[str, DeclarationReseau]) -> DeclarationReseau | dict[str, Any]:
    adaptateur = adaptateurs.get(reseau)
    if adaptateur is None or adaptateur.LIMITES.reseau != reseau:
        return _refus(REJ_ADAPTATEUR, "$.reseau", f"aucun adaptateur déclaré pour {reseau!r}")
    return adaptateur


def soumettre(
    journal: Any,
    publication_id: str,
    adaptateurs: Mapping[str, DeclarationReseau],
    politique: PolitiqueSas,
    maintenant: datetime,
    horodatage: str,
    actifs: portes.Resolveur | None = None,
) -> dict[str, Any]:
    """brouillon -> en_attente_approbation, SI tous les contrôles passent (sinon rien n'est écrit et le refus nomme les
    règles). `actifs` : résolveur du registre des actifs du studio créatif (voir `garde_fous.controler_medias`).
    """
    tous, refus = charger(journal)
    if refus is not None:
        return refus
    courant = _etat(tous, publication_id)
    if isinstance(courant, dict):
        return courant
    if courant.etat != etats.BROUILLON:
        return _refus(REJ_ETAT, "$.publication_id", f"publication {courant.etat} : seul un brouillon se soumet")
    publication, refus = _publication(courant)
    if refus is not None:
        return refus
    adaptateur = _adaptateur_de(publication.reseau, adaptateurs)
    if isinstance(adaptateur, dict):
        return adaptateur
    problemes = garde_fous.controler_tout(
        publication,
        adaptateur,
        politique,
        maintenant,
        horaires_du_compte(tous, publication.reseau, publication.compte, exclure=publication_id),
        actifs,
    )
    if problemes:
        return {"accepte": False, "refus": problemes}
    niveau = garde_fous.niveau_requis(publication)
    journal_chaine.ajouter(
        journal,
        etats.MAILLON_SOUMISE,
        {
            "publication_id": publication_id,
            "empreinte": courant.empreinte,
            "niveau_requis": niveau,
            "limites": dict(garde_fous.resume_adaptateur(adaptateur)),
        },
        horodatage,
    )
    return {
        "accepte": True,
        "publication_id": publication_id,
        "etat": etats.EN_ATTENTE,
        "empreinte": courant.empreinte,
        "niveau_requis": f"N{niveau}",
    }


def approuver(
    journal: Any,
    publication_id: str,
    empreinte: str,
    niveau_outil: int,
    approbateur: Mapping[str, str] | None,
    adaptateurs: Mapping[str, DeclarationReseau],
    politique: PolitiqueSas,
    maintenant: datetime,
    horodatage: str,
    actifs: portes.Resolveur | None = None,
) -> dict[str, Any]:
    """en_attente_approbation -> approuve -> planifie. Rien ne s'écrit si un contrôle échoue."""
    if (
        approbateur is None
        or approbateur.get("role") != ROLE_DECIDEUR
        or not approbateur.get("par")
        or not approbateur.get("source")
    ):
        return _refus(
            REJ_HUMAIN, "$", "l'approbation d'une publication publique est une décision humaine du propriétaire"
        )
    tous, refus = charger(journal)
    if refus is not None:
        return refus
    courant = _etat(tous, publication_id)
    if isinstance(courant, dict):
        return courant
    if courant.etat != etats.EN_ATTENTE:
        return _refus(
            REJ_ETAT, "$.publication_id", f"publication {courant.etat} : seule une demande en attente s'approuve"
        )
    publication, refus = _publication(courant)
    if refus is not None:
        return refus
    if empreinte != courant.empreinte:
        return _refus(
            REJ_EMPREINTE,
            "$.empreinte",
            f"l'empreinte approuvée ({empreinte}) n'est pas celle du contenu soumis ({courant.empreinte})",
        )
    niveau = garde_fous.verifier_niveau(publication, niveau_outil)
    if niveau:
        return {"accepte": False, "refus": niveau}
    adaptateur = _adaptateur_de(publication.reseau, adaptateurs)
    if isinstance(adaptateur, dict):
        return adaptateur
    problemes = garde_fous.controler_tout(
        publication,
        adaptateur,
        politique,
        maintenant,
        horaires_du_compte(tous, publication.reseau, publication.compte, exclure=publication_id),
        actifs,
    )
    if problemes:
        return {"accepte": False, "refus": problemes}
    journal_chaine.ajouter(
        journal,
        etats.MAILLON_APPROUVEE,
        {
            "publication_id": publication_id,
            "empreinte": courant.empreinte,
            "niveau": niveau_outil,
            "approbation": {"par": approbateur["par"], "role": approbateur["role"], "source": approbateur["source"]},
        },
        horodatage,
    )
    journal_chaine.ajouter(
        journal,
        etats.MAILLON_PLANIFIEE,
        {
            "publication_id": publication_id,
            "planifie_le": publication.planifie_le,
        },
        horodatage,
    )
    return {
        "accepte": True,
        "publication_id": publication_id,
        "etat": etats.PLANIFIE,
        "empreinte": courant.empreinte,
        "planifie_le": publication.planifie_le,
        "approbation": dict(approbateur),
        "execute": False,
        "execution": "Aucune : la sortie est un exécuteur distinct, hors transaction, jamais un outil d'agent.",
    }


def annuler(journal: Any, publication_id: str, par: str, motif: str, horodatage: str) -> dict[str, Any]:
    """Retire une publication de la file (jamais d'une publication déjà sortie : le retrait d'un message publié se fait
    à la main).
    """
    tous, refus = charger(journal)
    if refus is not None:
        return refus
    courant = _etat(tous, publication_id)
    if isinstance(courant, dict):
        return courant
    if courant.etat == etats.PUBLIE:
        return _refus(
            REJ_DEJA_PUBLIE, "$.publication_id", "déjà publiée : OPSYS ne retire rien d'un réseau, à faire à la main"
        )
    if not etats.transition_permise(courant.etat, etats.ANNULE):
        return _refus(REJ_ETAT, "$.publication_id", f"publication {courant.etat} : rien à annuler")
    journal_chaine.ajouter(
        journal,
        etats.MAILLON_ANNULEE,
        {
            "publication_id": publication_id,
            "par": par,
            "motif": motif[:300],
            "etat_avant": courant.etat,
            "incertain": courant.incertain,
        },
        horodatage,
    )
    return {
        "accepte": True,
        "publication_id": publication_id,
        "etat": etats.ANNULE,
        "attention": (
            "une tentative d'envoi est peut-être passée : vérifier le compte à la main" if courant.incertain else None
        ),
    }


def lire(journal: Any, publication_id: str | None = None, etat: str | None = None, limite: int = 20) -> dict[str, Any]:
    """La file en bref (`limite` entrées, les plus récentes d'abord), ou une publication en détail avec son historique.
    """
    tous, refus = charger(journal)
    if refus is not None:
        return refus
    if publication_id is not None:
        courant = _etat(tous, publication_id)
        if isinstance(courant, dict):
            return courant
        return {
            "accepte": True,
            "publication": {
                **courant.resume(),
                "contenu": courant.publication,
                "approbation": courant.approbation,
                "rangs": courant.rangs,
            },
        }
    choisies = [e for e in tous.values() if etat is None or e.etat == etat]
    choisies.sort(key=lambda e: e.rangs[-1], reverse=True)
    return {
        "accepte": True,
        "total": len(choisies),
        "publications": [e.resume() for e in choisies[: max(1, min(limite, 50))]],
    }
