"""Dossiers de période scellés par M5 (M5.6) : M10 en garde la MÉMOIRE (qu'il a été scellé, quand, sous quel sceau),
tels quels, sans jamais les rouvrir (interconnexion M5 -> M10).

M5 publie ``m5.dossier_cpa_scelle`` quand l'agent finance PRÉPARE et SCELLE le dossier d'une période : un BROUILLON pour
le CPA (ni compilation, ni examen, ni audit, ni déclaration ; l'attestation est hors d'OPSYS). L'événement ne porte ni
chemin, ni donnée de client, ni montant : l'identifiant du dossier, la période, le sceau (SHA-256 du manifeste), le
nombre
de fichiers, les totaux de la liste de contrôle et la date de référence. M10 les range dans son registre
``dossiers_cpa_scelles`` (append-only, chaîné), distinct des registres Événements, Affaires, Faits analytiques et
Faits stratégiques : ce n'est pas un fait d'affaire (aucun ``lead_id``).

Règles :

* LISTE BLANCHE, FORMES FERMÉES. Chaque champ gardé a une forme ; un champ de plus, manquant ou hors forme est un refus
  nommé qui dit le CHAMP, jamais la valeur ;
* CONFIDENTIALITÉ. L'entrée est ``FINANCIAL`` : aucun paquet de contexte, pour aucun agent (``confidentialite.py``) ;
* IDEMPOTENCE. Un maillon par ``dossier_id`` : une relivraison, ou le même dossier sous un autre ``evenement_id``,
n'ajoute
  rien. Le MÊME ``dossier_id`` sous un AUTRE sceau est une contradiction : refus nommé (le premier sceau reste) - un
  dossier scellé ne change pas de sceau en silence ;
* RIEN D'UN AVIS. M10 ne dit pas si le dossier est « bon » : il se souvient qu'il existe. Mention obligatoire à la
lecture :
  « À valider auprès d'un comptable (CPA) / professionnel qualifié ».

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from . import confidentialite, validation

TYPE_EVENEMENT = "m5.dossier_cpa_scelle"
TYPE_ENTREE = "dossier_cpa_scelle"
PRODUCTEUR = "m05-financecore"
MENTION = "À valider auprès d'un comptable (CPA) / professionnel qualifié"

REJ_DOSSIER_CHAMP_INVALIDE = "REJ-DOSSIER-CPA-CHAMP-INVALIDE"
REJ_DOSSIER_SCEAU_CONTRADICTOIRE = "REJ-DOSSIER-CPA-SCEAU-CONTRADICTOIRE"

_DOSSIER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_JOUR = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_EMPREINTE = re.compile(r"^[0-9a-f]{64}$")
_CLES = frozenset(
    {
        "dossier_id",
        "periode_debut",
        "periode_fin",
        "scelle",
        "fichiers",
        "liste_de_controle",
        "statut",
        "date_reference",
    }
)
_CLES_CONTROLE = frozenset({"FAIT", "A_FAIRE", "A_VERIFIER"})


class ChampRefuse(ValueError):
    """Un champ manque ou sort de sa forme fermée. ``code`` est le verdict, ``detail`` le CHAMP (jamais sa valeur)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail

    def verdict(self) -> dict[str, Any]:
        return validation.construire_verdict(self.code, self.detail)


def _texte(valeur: Any, champ: str, motif: re.Pattern[str]) -> str:
    if not isinstance(valeur, str) or not motif.fullmatch(valeur):
        raise ChampRefuse(REJ_DOSSIER_CHAMP_INVALIDE, champ)
    return valeur


def _compte(valeur: Any, champ: str, maximum: int, minimum: int = 0) -> int:
    if isinstance(valeur, bool) or not isinstance(valeur, int) or not minimum <= valeur <= maximum:
        raise ChampRefuse(REJ_DOSSIER_CHAMP_INVALIDE, champ)
    return valeur


def extraire(charge: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(charge, Mapping) or set(charge) != _CLES:
        raise ChampRefuse(REJ_DOSSIER_CHAMP_INVALIDE, "(racine)")
    controle = charge["liste_de_controle"]
    if not isinstance(controle, Mapping) or set(controle) != _CLES_CONTROLE:
        raise ChampRefuse(REJ_DOSSIER_CHAMP_INVALIDE, "liste_de_controle")
    if charge["statut"] != "BROUILLON_POUR_CPA":
        raise ChampRefuse(REJ_DOSSIER_CHAMP_INVALIDE, "statut")
    return {
        "dossier_id": _texte(charge["dossier_id"], "dossier_id", _DOSSIER_ID),
        "periode_debut": _texte(charge["periode_debut"], "periode_debut", _JOUR),
        "periode_fin": _texte(charge["periode_fin"], "periode_fin", _JOUR),
        "scelle": _texte(charge["scelle"], "scelle", _EMPREINTE),
        "fichiers": _compte(charge["fichiers"], "fichiers", 40, 1),
        "liste_de_controle": {cle: _compte(controle[cle], f"liste_de_controle.{cle}", 40) for cle in sorted(controle)},
        "statut": charge["statut"],
        "date_reference": _texte(charge["date_reference"], "date_reference", _JOUR),
    }


def entree(champs: Mapping[str, Any]) -> dict[str, Any]:
    """Le maillon à écrire : les champs extraits, puis ce que M10 pose (jamais la charge)."""
    return {
        **champs,
        "type_entree": TYPE_ENTREE,
        "producteur": PRODUCTEUR,
        "confidentialite": confidentialite.NIVEAU_FINANCIER,
        "mention": MENTION,
        # L'événement ne porte qu'un JOUR de référence et M10 n'a pas d'horloge : le registre exige un instant avec
        # fuseau,
        # c'est donc le début de ce jour en UTC, jamais l'heure de la réception.
        "horodatage": f"{champs['date_reference']}T00:00:00+00:00",
    }


def memoriser(charge: Mapping[str, Any], registre_cible: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Mémorise un dossier scellé ; rend ``(resultat, None)`` ou ``(None, verdict)``, sans rien écrire au refus.
    ``resultat`` : ``{maillon, deja_memorise}``. Un seul maillon par ``dossier_id``."""
    try:
        champs = extraire(charge)
    except ChampRefuse as refus:
        return None, refus.verdict()
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") == TYPE_ENTREE and maillon.get("dossier_id") == champs["dossier_id"]:
            if maillon["scelle"] != champs["scelle"]:
                return None, validation.construire_verdict(REJ_DOSSIER_SCEAU_CONTRADICTOIRE, "scelle")
            return {"maillon": maillon, "deja_memorise": True}, None
    ligne_id = registre_cible.ajouter(entree(champs))
    maillon = next(m for m in registre_cible.lire() if m["ligne_id"] == ligne_id)
    return {"maillon": maillon, "deja_memorise": False}, None
