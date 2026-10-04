"""Consolidation nocturne (PLAN T3.3, règle 9 de la fiche source — « mémoire après action »).

Condense les événements d'UNE affaire (``lead_id``) survenus un JOUR donné en UN fait durable,
avec la trace vers ses sources (jamais perdue : chaque source cite son ``ligne_id`` d'origine).
Idempotente par ensemble des sources de ``(affaire_id, jour)`` : rejouer sans nouvelle source ne crée
rien de plus ; si un événement arrive tard, un nouveau fait agrégé cite les sources complètes. Les
versions antérieures restent intactes (DA-M10-05, append-only : la consolidation AJOUTE un maillon,
elle ne réécrit jamais un maillon-source ni un résumé antérieur).

``horodatage`` (l'instant d'écriture du fait consolidé) est TOUJOURS fourni par l'appelant ; ``jour``
(la date consolidée) aussi. Aucune horloge n'est lue ici (conformite.py::HORLOGE_INTERNE le
détecterait) : la fonction est pure vis-à-vis du temps, testable avec n'importe quelle date.

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

from typing import Any

from . import classification, etapes

TYPE_ENTREE_FAIT = "fait_consolide"

REJ_CONSOLIDATION_AFFAIRE_ABSENTE = "REJ-CONSOLIDATION-AFFAIRE-ABSENTE"
REJ_CONSOLIDATION_JOUR_ABSENT = "REJ-CONSOLIDATION-JOUR-ABSENT"
REJ_CONSOLIDATION_AUCUN_EVENEMENT = "REJ-CONSOLIDATION-AUCUN-EVENEMENT"


def _cle_consolidation(affaire_id: str, jour: str) -> str:
    return f"{affaire_id}:{jour}"


def jour_de(horodatage: str) -> str:
    """Les 10 premiers caractères d'un horodatage ISO 8601 déjà validé (``AAAA-MM-JJ``) — le
    registre qui a écrit ce maillon a déjà refusé tout horodatage mal formé (``registre.py``).

    C'est la date TELLE QU'ELLE EST ÉCRITE, sans conversion de fuseau : 23 h 30 à l'heure de l'Est est encore ce jour-là
    ici. La consolidation groupe par ce jour, et le paquet de contexte dit les jours à consolider avec la même règle."""
    return horodatage[:10]


def jours_non_consolides(
    affaire_id: str,
    jours: list[str],
    maillons_affaires: list[dict[str, Any]],
    sources_omet: dict[str, set[str]] | None = None,
) -> list[str]:
    """Jours sans couverture des événements omis, ou sans consolidation du tout."""
    derniers: dict[str, dict[str, Any]] = {}
    for maillon in maillons_affaires:
        if maillon.get("type_entree") == TYPE_ENTREE_FAIT:
            derniers[maillon.get("cle_consolidation")] = maillon
    a_reprendre = []
    for jour in set(jours):
        fait = derniers.get(_cle_consolidation(affaire_id, jour))
        if fait is None:
            a_reprendre.append(jour)
            continue
        couvertes = {s.get("ligne_id") for s in fait.get("sources", [])}
        if sources_omet and sources_omet.get(jour, set()) - couvertes:
            a_reprendre.append(jour)
    return sorted(a_reprendre)


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

    # L'amont d'abord, dans l'ordre de l'entonnoir (PLAN T4.18) : un COMPTE par étape, jamais un identifiant, un
    # montant ni un contact. Le maillon compagnon FINANCIAL d'un devis n'est pas une étape de plus : pas compté.
    segments = []
    for etape in etapes.etapes_de_l_amont():
        nb_etape = sum(1 for e in evenements_du_jour if classification.type_evenement(e) == etape.type_evenement)
        if nb_etape:
            segments.append(f"{nb_etape} {etape.libelle}")
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

    ``ecrit`` n'est vrai que si un NOUVEAU maillon a été ajouté PAR CET APPEL. Un appel sans
    nouvelles sources rend ``ecrit=False, deja_consolide=True`` et le dernier agrégat existant ;
    une source tardive produit un nouvel agrégat append-only complet.
    """
    if not affaire_id or not isinstance(affaire_id, str):
        return {"ecrit": False, "deja_consolide": False, "fait": None, "verdict": REJ_CONSOLIDATION_AFFAIRE_ABSENTE}
    if not jour or not isinstance(jour, str):
        return {"ecrit": False, "deja_consolide": False, "fait": None, "verdict": REJ_CONSOLIDATION_JOUR_ABSENT}

    cle = _cle_consolidation(affaire_id, jour)
    maillons_affaires = registre_affaires.lire()
    deja = [m for m in maillons_affaires if m.get("type_entree") == TYPE_ENTREE_FAIT
            and m.get("cle_consolidation") == cle]

    evenements_affaire = classification.evenements_de_laffaire(affaire_id, registre_evenements.lire())
    evenements_du_jour = [e for e in evenements_affaire if jour_de(e["horodatage"]) == jour]
    if not evenements_du_jour:
        return {
            "ecrit": False,
            "deja_consolide": False,
            "fait": None,
            "verdict": REJ_CONSOLIDATION_AUCUN_EVENEMENT,
        }

    sources = _sources(evenements_du_jour)
    sources_connues = {s.get("ligne_id") for m in deja for s in m.get("sources", [])}
    sources_nouvelles = {s.get("ligne_id") for s in sources} - sources_connues
    if deja and not sources_nouvelles:
        dernier = deja[-1]
        return {"ecrit": False, "deja_consolide": True, "fait": dernier, "verdict": None}

    entree = {
        "type_entree": TYPE_ENTREE_FAIT,
        "horodatage": horodatage,
        "affaire_id": affaire_id,
        "jour": jour,
        "cle_consolidation": cle,
        "resume": _resumer(evenements_du_jour),
        "sources": sources,
    }
    ligne_id = registre_affaires.ajouter(entree)

    for maillon in registre_affaires.lire():
        if maillon.get("ligne_id") == ligne_id:
            return {"ecrit": True, "deja_consolide": False, "fait": maillon, "verdict": None}

    raise RuntimeError("Maillon ajouté introuvable.")
