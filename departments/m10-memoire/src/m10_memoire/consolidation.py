"""Consolidation nocturne (PLAN T3.3, règle 9 de la fiche source — « mémoire après action »).

Condense les événements d'UNE affaire (``lead_id``) survenus un JOUR donné en UN fait durable,
avec la trace vers ses sources (jamais perdue : chaque source cite son ``ligne_id`` d'origine).
Idempotente par ``(affaire_id, jour)`` : rejouer la même nuit ne crée rien de plus — un fait déjà
consolidé pour ce jour est rendu tel quel, jamais dupliqué ni fusionné (DA-M10-05, append-only : la
consolidation AJOUTE un maillon, elle ne réécrit jamais un maillon-source).

``horodatage`` (l'instant d'écriture du fait consolidé) est TOUJOURS fourni par l'appelant ; ``jour``
(la date consolidée) aussi. Aucune horloge n'est lue ici (conformite.py::HORLOGE_INTERNE le
détecterait) : la fonction est pure vis-à-vis du temps, testable avec n'importe quelle date.

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

from typing import Any

from . import classification

TYPE_ENTREE_FAIT = "fait_consolide"

REJ_CONSOLIDATION_AFFAIRE_ABSENTE = "REJ-CONSOLIDATION-AFFAIRE-ABSENTE"
REJ_CONSOLIDATION_JOUR_ABSENT = "REJ-CONSOLIDATION-JOUR-ABSENT"
REJ_CONSOLIDATION_AUCUN_EVENEMENT = "REJ-CONSOLIDATION-AUCUN-EVENEMENT"


def _cle_consolidation(affaire_id: str, jour: str) -> str:
    return f"{affaire_id}:{jour}"


def _jour_de(horodatage: str) -> str:
    """Les 10 premiers caractères d'un horodatage ISO 8601 déjà validé (``AAAA-MM-JJ``) — le
    registre qui a écrit ce maillon a déjà refusé tout horodatage mal formé (``registre.py``)."""
    return horodatage[:10]


def _resumer(evenements_du_jour: list[dict]) -> str:
    """Résumé DÉTERMINISTE (comptage, jamais un texte généré par un modèle) : le code calcule, le
    LLM orchestre (AGENTS.md)."""
    nb_wct = sum(1 for e in evenements_du_jour if classification.type_evenement(e) == classification.TYPE_WCT)
    nb_variance = sum(
        1 for e in evenements_du_jour if classification.type_evenement(e) == classification.TYPE_VARIANCE
    )
    nb_variance_critique = sum(
        1
        for e in evenements_du_jour
        if classification.type_evenement(e) == classification.TYPE_VARIANCE and e.get("signal_critique") is True
    )

    nb_rentabilite = sum(
        1 for e in evenements_du_jour if classification.type_evenement(e) == classification.TYPE_RENTABILITE
    )

    segments = []
    if nb_wct:
        segments.append(f"{nb_wct} travaux terminés")
    if nb_variance:
        segment = f"{nb_variance} variance(s) matériaux"
        if nb_variance_critique:
            segment += f" dont {nb_variance_critique} critique(s)"
        segments.append(segment)
    if nb_rentabilite:
        # Un COMPTE seulement : le fait consolidé n'est pas FINANCIAL, aucun montant n'y entre.
        segments.append(f"{nb_rentabilite} rentabilité(s) de chantier")
    return ", ".join(segments) if segments else "aucun événement classifié"


def _sources(evenements_du_jour: list[dict]) -> list[dict[str, Any]]:
    return [
        {
            "registre": "evenements",
            "ligne_id": e["ligne_id"],
            "type_evenement": classification.type_evenement(e),
            "identifiant": classification.identifiant(e),
        }
        for e in evenements_du_jour
    ]


def consolider_affaire(
    affaire_id: str,
    jour: str,
    horodatage: str,
    registre_evenements: Any,
    registre_affaires: Any,
) -> dict[str, Any]:
    """Rend TOUJOURS un dict explicite (jamais une valeur par défaut) :
    ``{"ecrit": bool, "deja_consolide": bool, "fait": maillon | None, "verdict": code | None}``.

    ``ecrit`` n'est vrai que si un NOUVEAU maillon a été ajouté PAR CET APPEL — l'idempotence par
    jour se lit sur ce champ : un second appel pour le même ``(affaire_id, jour)`` rend
    ``ecrit=False, deja_consolide=True`` et le MÊME fait, sans rien écrire de plus.
    """
    if not affaire_id or not isinstance(affaire_id, str):
        return {"ecrit": False, "deja_consolide": False, "fait": None, "verdict": REJ_CONSOLIDATION_AFFAIRE_ABSENTE}
    if not jour or not isinstance(jour, str):
        return {"ecrit": False, "deja_consolide": False, "fait": None, "verdict": REJ_CONSOLIDATION_JOUR_ABSENT}

    cle = _cle_consolidation(affaire_id, jour)
    for maillon in registre_affaires.lire():
        if maillon.get("type_entree") == TYPE_ENTREE_FAIT and maillon.get("cle_consolidation") == cle:
            return {"ecrit": False, "deja_consolide": True, "fait": maillon, "verdict": None}

    evenements_affaire = classification.evenements_de_laffaire(affaire_id, registre_evenements.lire())
    evenements_du_jour = [e for e in evenements_affaire if _jour_de(e["horodatage"]) == jour]
    if not evenements_du_jour:
        return {
            "ecrit": False,
            "deja_consolide": False,
            "fait": None,
            "verdict": REJ_CONSOLIDATION_AUCUN_EVENEMENT,
        }

    entree = {
        "type_entree": TYPE_ENTREE_FAIT,
        "horodatage": horodatage,
        "affaire_id": affaire_id,
        "jour": jour,
        "cle_consolidation": cle,
        "resume": _resumer(evenements_du_jour),
        "sources": _sources(evenements_du_jour),
    }
    ligne_id = registre_affaires.ajouter(entree)

    for maillon in registre_affaires.lire():
        if maillon.get("ligne_id") == ligne_id:
            return {"ecrit": True, "deja_consolide": False, "fait": maillon, "verdict": None}

    raise RuntimeError("Maillon ajouté introuvable.")
