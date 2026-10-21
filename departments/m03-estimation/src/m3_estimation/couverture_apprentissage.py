"""Comparaison de réception par identité seulement, aucun apprentissage activé."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from opsys.evenements import inventaire_calibration as inventaire


def auditer(*, lire_prefixe: Callable[[Any], Any], autorise: Callable[[], bool]) -> dict[str, Any]:
    """Relit les sources et les droits dans la transaction SQLite courante.

    Les ports sont de composition serveur, jamais des arguments du modèle.
    Le sceau M3 contrôle forme et doublons, pas l'origine des charges.
    """
    def refuser(raison: str) -> dict[str, Any]:
        return {"statut": "refuse", "raison": raison, "candidate_active": False}

    def reception() -> tuple[list[str], str]:
        prefixe = lire_prefixe(inventaire.lire_receptions_m3())
        if prefixe is None:
            raise inventaire.InventaireRefuse("prefixe_reception_m3_invalide")
        identites = sorted(prefixe["rangs"])
        if len(identites) > 2_000:
            raise inventaire.InventaireRefuse("limite_reception_m3_depassee")
        if any(not inventaire.identite_valide(i) for i in identites):
            raise inventaire.InventaireRefuse("identite_reception_m3_invalide")
        return identites, prefixe["sha256"]

    try:
        if not autorise():
            return refuser("identite_admin_authentifiee_requise")
        recus, sceau = reception()
        source = inventaire.lire_publications_m4()
        if reception() != (recus, sceau) or inventaire.lire_publications_m4() != source:
            return refuser("sources_modifiees_pendant_lecture")
        if not autorise():
            return refuser("identite_admin_authentifiee_requise")
    except inventaire.InventaireRefuse as exc:
        return refuser(str(exc))
    except (SQLAlchemyError, ValueError, TypeError, KeyError, RecursionError):
        return refuser("sources_lecture_indisponibles")

    publications = set(source["identites"])
    reception_ids = set(recus)
    manquants = sorted(publications - reception_ids)
    hors_univers = sorted(reception_ids - publications)
    statut = "ecarts" if manquants or hors_univers else "identites_recues" if publications else "univers_vide"
    return {
        "version": "couverture-apprentissage-identites/1", "statut": statut,
        "univers": "identites_publications_m4_instance",
        "compteurs": {"publications_m4": len(publications), "recus_m3": len(reception_ids),
                      "recoupes": len(publications & reception_ids), "manquants_m3": len(manquants),
                      "hors_univers_m4": len(hors_univers)},
        "manquants_m3": {"exemples": manquants[:10], "omis": max(0, len(manquants) - 10)},
        "hors_univers_m4": {"exemples": hors_univers[:10], "omis": max(0, len(hors_univers) - 10)},
        "sources": {"publications_m4_sha256": source["sha256"], "prefixe_m3_sha256": sceau},
        "contenu_wct_verifie": False, "completude_corpus_m4": "non_prouvee", "candidate_active": False,
        "limites": ["Identités seulement : contenu, provenance et mesure terrain non attestés.",
                    "Un reçu hors univers peut être historique; aucune cause d'écart n'est déduite.",
                    "Lecture SQLite seulement; aucun snapshot PostgreSQL qualifié.",
                    "Aucune ingestion, relivraison, admission de cohorte ou activation de barème."],
    }
