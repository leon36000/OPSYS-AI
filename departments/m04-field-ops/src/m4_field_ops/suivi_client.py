"""Consentement de suivi du client (Loi 25) et enregistrements d'arrivée estimée (M4.14).

CE QUE CE MODULE PROTÈGE.

* Le client reçoit une fenêtre d'arrivée SEULEMENT s'il a consenti à ce SUIVI-LÀ (finalité ``fenetre_arrivee``), pour
  CE chantier et CE canal (SMS ou courriel). Le consentement est un maillon du registre de M4 (append-only, chaîné) :
  qui l'a recueilli (la personne qui l'a approuvé dans le sas), quand, l'énoncé présenté (version), la preuve (une
  référence, jamais le document), jusqu'à quand il vaut. Il ne contient AUCUN contact (le canal d'envoi est celui de
  M1, par ``lead_id``) et AUCUNE position.
* Un RETRAIT (STOP, demande du client, ou de l'équipe) est effectif tout de suite et ne se lève pas tout seul : un
  nouveau consentement doit être recueilli APRÈS le retrait. Un consentement a une durée de validité
  (``valide_jusqu_au``, au plus ``VALIDITE_MAX_JOURS``) : une fois expiré, il ne permet plus rien.
* Rétention bornée : le consentement a une date de fin ; l'enregistrement d'une fenêtre préparée en a une aussi
  (``conserve_jusqu_au``) et ne contient ni position, ni nom, ni contact, ni texte libre (seulement la fenêtre,
  l'empreinte du texte, des identifiants). Le registre étant append-only, la ligne subsiste physiquement : sa
  suppression est une destruction définitive (N5, hors de ce module) et ne contient de toute façon aucune donnée
  sensible. La durée légale de conservation est à valider auprès d'un juriste (Loi 25).
* Un plafond de messages par chantier et canal (``messages_max_par_intervention``, déclaré) empêche de harceler le
  client de mises à jour.

Module pur : stdlib seulement, aucun import ``opsys``, aucune horloge (les instants sont fournis), aucun aléa, aucun
réseau.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from . import verdicts

__all__ = [
    "CANAUX",
    "FINALITE",
    "TYPE_CONSENTEMENT",
    "TYPE_ETA",
    "TYPE_RETRAIT",
    "VALIDITE_MAX_JOURS",
    "construire_consentement",
    "construire_enregistrement_eta",
    "construire_retrait",
    "compter_messages",
    "etat_du_consentement",
]

TYPE_CONSENTEMENT = "consentement_suivi_client"
TYPE_RETRAIT = "retrait_suivi_client"
TYPE_ETA = "eta_client_preparee"
FINALITE = "fenetre_arrivee"
CANAUX = ("sms", "courriel")
# Plafond de sécurité du CODE (la durée effective est déclarée par l'entreprise, jamais au-dessus) : à valider auprès
# d'un juriste.
VALIDITE_MAX_JOURS = 30
_IDENTIFIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,79}$")
_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_SOURCES_RETRAIT = ("client_stop", "client_demande", "equipe", "administration")


def _refus(code: str, detail: str) -> dict[str, Any]:
    return verdicts.construire_verdict(code, detail=detail)


def _instant(texte: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(texte) if isinstance(texte, str) else None
    except ValueError:
        return None
    return d if d is not None and d.tzinfo is not None else None


def construire_consentement(
    *,
    intervention_id: Any,
    lead_id: Any,
    canal: Any,
    enonce_version: Any,
    preuve: Any,
    recueilli_le: Any,
    recueilli_par: Any,
    approbation_ref: Any,
    enregistre_le: Any,
    validite_jours: Any,
    maillons: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Le maillon ``consentement_suivi_client`` ou un verdict. ``maillons`` : le registre, pour refuser un
    consentement antérieur
    à un retrait (il ne le lève pas)."""
    if (
        not isinstance(intervention_id, str)
        or not _IDENTIFIANT.fullmatch(intervention_id)
        or not isinstance(lead_id, str)
        or not _IDENTIFIANT.fullmatch(lead_id)
        or canal not in CANAUX
        or not isinstance(enonce_version, str)
        or not _VERSION.fullmatch(enonce_version)
        or not isinstance(recueilli_par, str)
        or not _IDENTIFIANT.fullmatch(recueilli_par)
        or not isinstance(approbation_ref, str)
        or not _IDENTIFIANT.fullmatch(approbation_ref)
    ):
        return None, _refus(
            "REJ-SUIVI-CONSENTEMENT-INVALIDE",
            "intervention_id, lead_id, canal (sms ou courriel), enonce_version, recueilli_par et "
            "approbation_ref valides requis",
        )
    if (
        not isinstance(preuve, Mapping)
        or set(preuve) != {"fictif", "reference"}
        or type(preuve["fictif"]) is not bool
        or not isinstance(preuve["reference"], str)
        or not _IDENTIFIANT.fullmatch(preuve["reference"])
    ):
        return None, _refus(
            "REJ-SUIVI-CONSENTEMENT-INVALIDE",
            "preuve : {fictif, reference} (une référence au formulaire ou à la trace, jamais le document)",
        )
    recueilli, enregistre = _instant(recueilli_le), _instant(enregistre_le)
    if recueilli is None or enregistre is None or recueilli > enregistre:
        return None, _refus(
            "REJ-SUIVI-CONSENTEMENT-INVALIDE",
            "recueilli_le et enregistre_le : instants avec fuseau, le recueil n'est pas postérieur à l'enregistrement",
        )
    if type(validite_jours) is not int or not 1 <= validite_jours <= VALIDITE_MAX_JOURS:
        return None, _refus("REJ-SUIVI-CONSENTEMENT-INVALIDE", f"validité : 1 à {VALIDITE_MAX_JOURS} jours")
    for m in maillons:
        if (
            m.get("type_entree") == TYPE_RETRAIT
            and m.get("intervention_id") == intervention_id
            and m.get("canal") == canal
        ):
            retrait = _instant(m["horodatage"])
            if retrait is not None and recueilli <= retrait:
                return None, _refus(
                    "REJ-SUIVI-CONSENTEMENT-INVALIDE",
                    "un consentement recueilli avant un retrait ne le lève pas : le client doit "
                    "consentir "
                    "de nouveau, après le retrait",
                )
    return {
        "type_entree": TYPE_CONSENTEMENT,
        "horodatage": enregistre.isoformat(),
        "intervention_id": intervention_id,
        "lead_id": lead_id,
        "canal": canal,
        "finalite": FINALITE,
        "enonce_version": enonce_version,
        "preuve": {"fictif": preuve["fictif"], "reference": preuve["reference"]},
        "recueilli_le": recueilli.isoformat(),
        "recueilli_par": recueilli_par,
        "approbation_ref": approbation_ref,
        "valide_jusqu_au": (enregistre + timedelta(days=validite_jours)).isoformat(),
    }, None


def construire_retrait(
    *,
    intervention_id: Any,
    canal: Any,
    source: Any,
    retire_le: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    retire = _instant(retire_le)
    if (
        not isinstance(intervention_id, str)
        or not _IDENTIFIANT.fullmatch(intervention_id)
        or canal not in CANAUX
        or source not in _SOURCES_RETRAIT
        or retire is None
    ):
        return None, _refus(
            "REJ-SUIVI-CONSENTEMENT-INVALIDE",
            f"retrait : intervention_id, canal, source ({', '.join(_SOURCES_RETRAIT)}) et instant avec fuseau",
        )
    return {
        "type_entree": TYPE_RETRAIT,
        "horodatage": retire.isoformat(),
        "intervention_id": intervention_id,
        "canal": canal,
        "finalite": FINALITE,
        "source": source,
    }, None


def etat_du_consentement(
    maillons: Sequence[Mapping[str, Any]],
    intervention_id: str,
    canal: str,
    reference: datetime,
) -> dict[str, Any]:
    """``{etat: absent|actif|retire|expire, ...}`` : le DERNIER fait (consentement ou retrait) gagne ; un consentement
    actif
    expire à ``valide_jusqu_au``."""
    dernier: Mapping[str, Any] | None = None
    for m in maillons:
        if (
            m.get("intervention_id") == intervention_id
            and m.get("canal") == canal
            and m.get("type_entree") in (TYPE_CONSENTEMENT, TYPE_RETRAIT)
        ):
            dernier = m
    if dernier is None:
        return {"etat": "absent", "ligne_id": None}
    if dernier["type_entree"] == TYPE_RETRAIT:
        return {
            "etat": "retire",
            "retire_le": dernier["horodatage"],
            "source": dernier["source"],
            "ligne_id": dernier.get("ligne_id"),
        }
    fin = _instant(dernier["valide_jusqu_au"])
    if fin is None or reference >= fin:
        return {"etat": "expire", "valide_jusqu_au": dernier["valide_jusqu_au"], "ligne_id": dernier.get("ligne_id")}
    return {
        "etat": "actif",
        "valide_jusqu_au": dernier["valide_jusqu_au"],
        "ligne_id": dernier.get("ligne_id"),
        "lead_id": dernier["lead_id"],
        "enonce_version": dernier["enonce_version"],
    }


def compter_messages(maillons: Sequence[Mapping[str, Any]], intervention_id: str, canal: str) -> int:
    return sum(
        1
        for m in maillons
        if m.get("type_entree") == TYPE_ETA and m.get("intervention_id") == intervention_id and m.get("canal") == canal
    )


def construire_enregistrement_eta(
    *,
    intervention_id: str,
    canal: str,
    fenetre: Mapping[str, str],
    message_empreinte: str,
    consentement_ligne_id: str | None,
    prepare_le: str,
    conservation_heures: int,
) -> dict[str, Any]:
    """Ce que M4 garde d'une fenêtre préparée : la fenêtre, l'empreinte du texte et des identifiants, jusqu'à
    ``conserve_jusqu_au``."""
    prepare = _instant(prepare_le)
    fin = _instant(fenetre["fin"])
    if prepare is None or fin is None or not _SHA.fullmatch(message_empreinte):
        raise ValueError("enregistrement d'arrivée estimée : instants avec fuseau et empreinte SHA-256 requis")
    return {
        "type_entree": TYPE_ETA,
        "horodatage": prepare.isoformat(),
        "intervention_id": intervention_id,
        "canal": canal,
        "fenetre_debut": fenetre["debut"],
        "fenetre_fin": fenetre["fin"],
        "message_empreinte": message_empreinte,
        "consentement_ligne_id": consentement_ligne_id,
        "conserve_jusqu_au": (max(prepare, fin) + timedelta(hours=conservation_heures)).isoformat(),
    }
