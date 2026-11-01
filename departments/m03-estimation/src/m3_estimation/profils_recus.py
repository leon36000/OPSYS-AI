"""Le profil de propriété CONFIRMÉ de M2, reçu par le bus et repris dans le contexte de site (interconnexion M2 -> M3).

Module PUR (aucun import `opsys`, aucune horloge, aucun réseau). `outils.py` reçoit deux événements de M2 et range
leurs faits ; `outils_site_vision.construire_contexte_site` relit ces registres quand l'appelant ne fournit pas de
`profil_propriete`.

- `m2.client_associe` : le lien lead -> client que M2 établit à l'ingestion du lead (un lead n'a jamais deux clients) ;
- `m2.profil_propriete_confirme` : le fait minimisé publié quand une PERSONNE a confirmé un profil de propriété (ni
  adresse précise, ni contact, ni photo : seulement la ville, le type de bâtiment, les étages, l'année de construction).

Règles (fail-closed, AGENTS.md) :

- seul un profil CONFIRMÉ entre ici : M2 ne publie rien d'un brouillon ;
- la révision la plus haute d'une propriété fait foi, quel que soit l'ordre de livraison ;
- un client qui a PLUSIEURS propriétés confirmées est ambigu : M3 ne devine pas laquelle est le chantier, il ne reprend
  rien et le dit (`ambigu`) ; l'appelant fournit alors le profil lui-même ;
- les faits repris se limitent à ceux que le contexte de site sait lire (`hauteur.etages` de 1 à 10, `age`) ; un fait
  hors de ces bornes est écarté, jamais tronqué ni corrigé ;
- le contexte garde la SOURCE du fait (`profil_m2`, identifiant de propriété, révision) : un autre facteur déclaré
  qui le contredit reste un « conflit », pas une valeur écrasée.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

REGISTRE_LIENS = "liens_lead_client"
REGISTRE_PROFILS = "profils_propriete_recus"
TYPE_LIEN = "lien_lead_client"
TYPE_PROFIL = "profil_propriete_recu"

STATUT_REPRIS = "repris"
STATUT_ABSENT = "absent"
STATUT_AMBIGU = "ambigu"
STATUT_SANS_FAIT = "sans_fait_lisible"


def fait_lien(charge: Mapping[str, Any]) -> dict[str, Any]:
    return {"type_entree": TYPE_LIEN, "lead_id": charge["lead_id"], "client_id": charge["client_id"]}


def fait_profil(charge: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que M3 garde du profil : ses références et les trois attributs utiles au contexte de site."""
    return {
        "type_entree": TYPE_PROFIL,
        "client_id": charge["client_id"],
        "propriete_id": charge["propriete_id"],
        "revision": charge["revision"],
        "fait_id": charge["fait_id"],
        "type_batiment": charge.get("type_batiment"),
        "etages": charge.get("etages"),
        "annee_construction": charge.get("annee_construction"),
        "horodatage": charge["horodatage"],
    }


def _derniere_revision_par_propriete(profils: Iterable[Mapping[str, Any]], client_id: str) -> list[Mapping[str, Any]]:
    meilleures: dict[str, Mapping[str, Any]] = {}
    for p in profils:
        if p.get("type_entree") != TYPE_PROFIL or p.get("client_id") != client_id:
            continue
        actuelle = meilleures.get(p["propriete_id"])
        if actuelle is None or p["revision"] > actuelle["revision"]:
            meilleures[p["propriete_id"]] = p
    return list(meilleures.values())


def profil_pour_contexte(
    liens: Iterable[Mapping[str, Any]], profils: Iterable[Mapping[str, Any]], lead_id: str
) -> tuple[dict[str, Any] | None, str]:
    """`(profil au format de `contexte_site`, statut)`. Le profil est `{identifiant, version, recu_le, faits}` ou
    `None` ; le statut dit pourquoi (`repris`, `absent`, `ambigu`, `sans_fait_lisible`)."""
    client_id = None
    for lien in liens:
        if lien.get("type_entree") == TYPE_LIEN and lien.get("lead_id") == lead_id:
            client_id = lien["client_id"]
            break  # le PREMIER lien fait foi (M2 n'en établit qu'un par lead ; M5 garde aussi le premier)
    if client_id is None:
        return None, STATUT_ABSENT
    candidats = _derniere_revision_par_propriete(profils, client_id)
    if not candidats:
        return None, STATUT_ABSENT
    if len(candidats) > 1:
        return None, STATUT_AMBIGU
    p = candidats[0]
    faits: dict[str, Any] = {}
    etages = p.get("etages")
    if isinstance(etages, int) and not isinstance(etages, bool) and 1 <= etages <= 10:
        faits["hauteur"] = {"etages": etages}
    annee = p.get("annee_construction")
    if isinstance(annee, int) and not isinstance(annee, bool):
        faits["age"] = {"annee_construction": annee}
    if not faits:
        return None, STATUT_SANS_FAIT
    return {
        "identifiant": p["propriete_id"],
        "version": f"r{p['revision']}",
        "recu_le": p["horodatage"],
        "faits": faits,
    }, STATUT_REPRIS
