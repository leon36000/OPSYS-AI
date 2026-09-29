"""Mémorisation des faits de l'amont d'une affaire au registre Événements (PLAN T4.18, P4, DEFINITION-PRODUIT §6).

``memoriser`` garde un fait du bus (``m1.lead_qualifie``, ``m2.client_associe``, ``m3.devis_accepte``,
``m3.devis_sans_reponse``) sous la forme que ``etapes.py`` décrit : des identifiants et des faits d'étape, jamais la
charge. ``situation`` dit ce que M10 sait d'une affaire : une affaire SANS fait, ou dont on ignore l'origine. Le
consommateur (``outils.py``) la rend au reçu de chaque fait ; le paquet, dont la forme est épinglée contre les
fixtures du core, n'en porte pas.

Idempotence et ordre, par la CLÉ du fait et son TYPE (jamais par ``lead_id`` seul) :

- un rejeu (même type, même clé publique : ``lead_id`` ou ``devis_id``) ne crée rien ; le maillon EXISTANT est rendu.
  Cela vaut aussi pour une relivraison du même fait sous un ``evenement_id`` différent (producteur en défaut, rejeu
  manuel), que la garde du répartiteur ne voit pas. Le premier maillon reste : rien n'est écrasé. Un rejeu qui
  porterait d'autres faits est dit (``identique: False``), jamais tu, jamais fusionné ;
- un fait reçu AVANT celui qui le précède ne se perd pas et ne bloque pas l'autre. C'est le défaut que T1.5-d a
  corrigé pour le WCT (``wct.py``) : un devis accepté porte le ``lead_id`` de son lead ; un test « ce lead_id est
  déjà au registre » ferait croire le lead mémorisé et ne l'écrirait jamais. Ici, seul un maillon DU MÊME TYPE et de
  la MÊME clé compte comme déjà mémorisé ;
- un lead que M10 ne connaît pas (aucun ``m1.lead_qualifie`` reçu) n'est jamais inventé : le fait est gardé sous son
  ``lead_id`` et ``situation`` le dit (``AMONT-ORIGINE-NON-RECUE``). Aucune étape manquante n'est fabriquée.

Module pur (DA-M10-08) : aucun import d'``opsys``. L'instant de chaque maillon est celui du fait, donné par la
charge.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import classification, confidentialite, etapes, validation

AMONT_AFFAIRE_INCONNUE = "AMONT-AFFAIRE-INCONNUE"
AMONT_ORIGINE_NON_RECUE = "AMONT-ORIGINE-NON-RECUE"

_TYPE_ENTREE_EVENEMENT = "evenement_memorise"


def situation(affaire_id: str, maillons: list[dict[str, Any]]) -> dict[str, Any]:
    """Ce que le registre Événements sait de l'affaire : ``{connue, origine_recue, verdict}``.

    ``connue`` : au moins un événement (amont, WCT, variance, rentabilité) est résolu à cette affaire.
    ``origine_recue`` : le ``m1.lead_qualifie`` de ce lead est au registre. Un lead saisi hors de M1 n'en a pas ;
    M10 ne le déduit pas, il le dit. ``verdict`` : ``None``, ou ce qu'il faut savoir d'une affaire absente ou sans
    origine.
    """
    de_l_affaire = classification.evenements_de_laffaire(affaire_id, maillons)
    connue = bool(de_l_affaire)
    origine_recue = any(
        classification.type_evenement(maillon) == etapes.TYPE_LEAD_QUALIFIE for maillon in de_l_affaire
    )
    if not connue:
        verdict = AMONT_AFFAIRE_INCONNUE
    elif not origine_recue:
        verdict = AMONT_ORIGINE_NON_RECUE
    else:
        verdict = None
    return {"connue": connue, "origine_recue": origine_recue, "verdict": verdict}


def _deja_memorise(maillons: list[dict[str, Any]], type_maillon: str, cle: str, valeur: Any) -> dict[str, Any] | None:
    for maillon in maillons:
        if etapes.type_du_maillon(maillon) == type_maillon and maillon.get(cle) == valeur:
            return maillon
    return None


def _entree(type_maillon: str, niveau: str, champs: dict[str, Any]) -> dict[str, Any]:
    """Le maillon à écrire : les faits extraits, puis ce que M10 pose. Une charge ne peut ni choisir le type ni
    ouvrir le niveau : ces deux clés sont écrites APRÈS elle."""
    return {**champs, "type_entree": _TYPE_ENTREE_EVENEMENT, "type_evenement": type_maillon, "confidentialite": niveau}


def _identique(existant: Mapping[str, Any] | None, champs: Mapping[str, Any] | None) -> bool:
    if existant is None or champs is None:
        return True
    return all(existant.get(cle) == valeur for cle, valeur in champs.items())


def memoriser(
    type_evenement: str, charge: Mapping[str, Any], registre_cible: Any
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Mémorise un fait de l'amont ; rend ``(resultat, None)`` ou ``(None, verdict)``, sans rien écrire au refus.

    ``resultat`` : ``{maillon, montants, deja_memorise, identique, affaire}``. ``montants`` est le maillon
    compagnon ``FINANCIAL`` (devis accepté seulement), sinon ``None``. ``deja_memorise`` : rien n'a été écrit par cet
    appel. ``affaire`` : ``situation`` après l'appel.
    """
    etape = etapes.etape(type_evenement)
    if etape is None:
        return None, validation.construire_verdict(etapes.REJ_AMONT_TYPE_INCONNU, str(type_evenement))
    try:
        champs = etape.extraire(charge)
        champs_montants = etape.montants(charge) if etape.montants is not None else None
    except etapes.ChampRefuse as refus:
        return None, refus.verdict()

    maillons = registre_cible.lire()
    existant = _deja_memorise(maillons, type_evenement, etape.cle, champs[etape.cle])
    type_montants = etapes.type_montants(type_evenement)
    existant_montants = (
        None
        if champs_montants is None
        else _deja_memorise(maillons, type_montants, etape.cle, champs_montants[etape.cle])
    )

    ecrits: list[str] = []
    if existant is None:
        ecrits.append(registre_cible.ajouter(_entree(type_evenement, etape.niveau, champs)))
    if champs_montants is not None and existant_montants is None:
        ecrits.append(registre_cible.ajouter(_entree(type_montants, confidentialite.NIVEAU_FINANCIER, champs_montants)))
    if ecrits:
        maillons = registre_cible.lire()
        nouveaux = {maillon["ligne_id"]: maillon for maillon in maillons if maillon["ligne_id"] in ecrits}
        if existant is None:
            existant = nouveaux[ecrits[0]]
        if champs_montants is not None and existant_montants is None:
            existant_montants = nouveaux[ecrits[-1]]

    return {
        "maillon": existant,
        "montants": existant_montants,
        "deja_memorise": not ecrits,
        "identique": _identique(existant, champs) and _identique(existant_montants, champs_montants),
        "affaire": situation(existant.get("lead_id", champs["lead_id"]), maillons),
    }, None
