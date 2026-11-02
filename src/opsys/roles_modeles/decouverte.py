"""Test de connexion de la passerelle et découverte de son catalogue (`/v1/models`, `/model/info`).

Seules des métadonnées sont retenues : nom, mode (chat, embedding…), vision, coût déclaré par million de jetons, modèle
d'amont. `litellm_params` n'est JAMAIS recopié (il peut contenir une clé ou une base d'URL privée). Un coût `0` est
« non déclaré » : LiteLLM rapporte 0 pour un modèle absent de sa table de prix.
"""

from __future__ import annotations

from typing import Any

from . import acces, service
from .client import ErreurAppel, cout_par_million


def _entree(modele: str, info: dict[str, Any] | None) -> dict[str, Any]:
    sortie: dict[str, Any] = {
        "nom": modele,
        "mode": None,
        "cout_entree_par_million": None,
        "cout_sortie_par_million": None,
        "vision": None,
        "modele_amont": None,
    }
    if not info:
        return sortie
    details = info.get("model_info") if isinstance(info.get("model_info"), dict) else {}
    params = info.get("litellm_params") if isinstance(info.get("litellm_params"), dict) else {}
    mode = details.get("mode")
    sortie["mode"] = mode if isinstance(mode, str) and len(mode) <= 24 else None
    sortie["cout_entree_par_million"] = cout_par_million(details.get("input_cost_per_token"))
    sortie["cout_sortie_par_million"] = cout_par_million(details.get("output_cost_per_token"))
    vision = details.get("supports_vision")
    sortie["vision"] = vision if isinstance(vision, bool) else None
    amont = params.get("model")
    sortie["modele_amont"] = amont[:120] if isinstance(amont, str) else None
    return sortie


def decouvrir(fabrique: acces.FabriqueConnexion, *, acteur: str, ouvrir=None, delai_s: float = 8.0) -> dict[str, Any]:
    """Un `GET /v1/models` (+ `/model/info` si offert) ; le résultat est conservé (réglage `catalogue`) et rendu."""
    try:
        with acces.client_passerelle(fabrique, ouvrir=ouvrir, delai_s=delai_s) as (client, _reglage):
            noms, latence = client.modeles()
            infos = client.info_modeles()
    except ErreurAppel as exc:
        resultat = {"statut": "echec", "code": exc.code, "detail": exc.detail[:200], "modeles": 0}
        return resultat
    par_nom = {i.get("model_name"): i for i in infos or [] if isinstance(i, dict)}
    entrees = [_entree(nom, par_nom.get(nom)) for nom in sorted(set(noms))]
    with fabrique() as cnx:
        service.exiger_admin(cnx, acteur)
        service.ecrire_catalogue(cnx, entrees, acteur)
    return {
        "statut": "succes",
        "latence_ms": latence,
        "modeles": len(entrees),
        "cout_disponible": infos is not None,
        "entrees": entrees,
    }


def catalogue_courant(cnx: Any) -> list[dict[str, Any]]:
    valeur, _ = service.lire_reglage(cnx, "catalogue")
    return list(valeur["entrees"]) if valeur else []
