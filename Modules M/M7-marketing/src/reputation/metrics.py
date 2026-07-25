"""Métriques réputation déterministes — M7-S009.

Métriques calculées localement, sans réseau, sans LLM (REJ-0040) :
  - répartition des notes (1-5)
  - note moyenne
  - taux de réponse proposée (reponses / total avis)
  - répartition des catégories classifiées
  - délai moyen entre date de l'avis et date de traitement (si fourni)

Alignées avec m7-metrics.v1.yaml (ids : m7_rep_*).
"""

from __future__ import annotations

from collections import Counter
from datetime import date


def calculer_repartition_notes(avis_list: list[dict]) -> dict[int, int]:
    """Retourne un dict {note: nombre} pour les notes de 1 à 5.

    Les notes absentes de la liste sont représentées avec la valeur 0.
    """
    compteur = Counter(a.get("note") for a in avis_list if isinstance(a.get("note"), int))
    return {note: compteur.get(note, 0) for note in range(1, 6)}


def calculer_note_moyenne(avis_list: list[dict]) -> float:
    """Retourne la note moyenne (float) ou 0.0 si la liste est vide."""
    notes = [a.get("note") for a in avis_list if isinstance(a.get("note"), int)]
    if not notes:
        return 0.0
    return sum(notes) / len(notes)


def calculer_taux_reponse(
    avis_list: list[dict], reponses: list[dict]
) -> float:
    """Retourne le taux de réponse proposée (0.0 à 1.0).

    Un avis est considéré « traité » si au moins une réponse porte
    son identifiant dans le champ ``avis_id``.
    """
    if not avis_list:
        return 0.0
    avis_ids = {a["id"] for a in avis_list if a.get("id")}
    traites = {r["avis_id"] for r in reponses if r.get("avis_id") in avis_ids}
    return len(traites) / len(avis_ids)


def calculer_repartition_categories(classifications: list[str]) -> dict[str, int]:
    """Retourne un dict {categorie: nombre} pour les 4 catégories connues.

    Les catégories absentes sont représentées avec la valeur 0.
    """
    compteur = Counter(classifications)
    return {cat: compteur.get(cat, 0) for cat in ("litige", "urgence", "eloge", "neutre")}


def calculer_delai_moyen(
    avis_list: list[dict], reponses: list[dict]
) -> float | None:
    """Retourne le délai moyen en jours entre la date de l'avis et la date de traitement.

    La date de traitement est lue dans ``reponses[*].date_traitement`` (str ISO 8601).
    Si aucune réponse ne porte cette clé, retourne None.

    Seuls les avis disposant d'une réponse avec ``date_traitement`` valide sont pris en compte.
    """
    index_avis: dict[str, str] = {
        a["id"]: a.get("date", "") for a in avis_list if a.get("id") and a.get("date")
    }
    delais: list[float] = []
    for rep in reponses:
        avis_id = rep.get("avis_id")
        date_traitement_str = rep.get("date_traitement")
        if not avis_id or not date_traitement_str:
            continue
        date_avis_str = index_avis.get(avis_id)
        if not date_avis_str:
            continue
        try:
            d_avis = date.fromisoformat(date_avis_str)
            d_trait = date.fromisoformat(date_traitement_str)
            delais.append((d_trait - d_avis).days)
        except ValueError:
            continue
    if not delais:
        return None
    return sum(delais) / len(delais)


def calculer_metriques(
    avis_list: list[dict],
    reponses: list[dict] | None = None,
    classifications: list[str] | None = None,
) -> dict:
    """Calcule l'ensemble des métriques réputation (deterministe, zéro réseau).

    Paramètres
    ----------
    avis_list       : liste des avis chargés depuis les fixtures.
    reponses        : liste des réponses PROPOSÉES (optionnel).
    classifications : liste des catégories classifiées (même ordre qu'avis_list, optionnel).

    Retourne
    --------
    dict avec les clés alignées sur m7-metrics.v1.yaml (ids m7_rep_*) :
        m7_rep_total_avis         : int
        m7_rep_repartition_notes  : dict {1..5: int}
        m7_rep_note_moyenne       : float
        m7_rep_taux_reponse       : float (0.0–1.0)
        m7_rep_repartition_cats   : dict {litige|urgence|eloge|neutre: int}
        m7_rep_delai_moyen_jours  : float | None
    """
    reponses = reponses or []
    classifications = classifications or []

    return {
        "m7_rep_total_avis": len(avis_list),
        "m7_rep_repartition_notes": calculer_repartition_notes(avis_list),
        "m7_rep_note_moyenne": calculer_note_moyenne(avis_list),
        "m7_rep_taux_reponse": calculer_taux_reponse(avis_list, reponses),
        "m7_rep_repartition_cats": calculer_repartition_categories(classifications),
        "m7_rep_delai_moyen_jours": calculer_delai_moyen(avis_list, reponses),
    }
