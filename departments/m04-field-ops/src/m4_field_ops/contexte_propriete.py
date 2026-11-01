"""Le profil de propriété CONFIRMÉ de M2, reçu par le bus et dit à qui prépare le chantier (interconnexion M2 -> M4).

Module PUR (aucun import `opsys`, aucune horloge). `outils.py` reçoit `m2.client_associe` (le lien lead -> client) et
`m2.profil_propriete_confirme` (le fait minimisé publié quand une PERSONNE a confirmé un profil), range ces faits dans
deux registres de M4, et `m4_verifier_preparation` ajoute au verdict, APRÈS son empreinte, le bloc `contexte_propriete`.

Ce que ce bloc est, et n'est pas :

- un RENSEIGNEMENT pour l'équipe et l'admin (type de bâtiment, étages, année de construction, nombre de photos et de
  mesures liées) : il ne devient JAMAIS un volet de la préparation. La porte « prête à planifier » ne change pas, et
  l'empreinte du verdict (qui la verrouille) n'en dépend pas ;
- jamais une adresse, un contact ni un nom : le fait de M2 n'en porte pas, M4 n'en ajoute pas ;
- jamais deviné : un client qui a PLUSIEURS propriétés confirmées est `ambigu` (M4 ne sait pas laquelle est le
chantier) ;
  aucun profil reçu : `absent` (« non reçu » n'est pas « sans particularité »).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

REGISTRE_LIENS = "liens_lead_client"
REGISTRE_PROFILS = "profils_propriete_recus"
TYPE_LIEN = "lien_lead_client"
TYPE_PROFIL = "profil_propriete_recu"

STATUT_RECU = "recu"
STATUT_ABSENT = "absent"
STATUT_AMBIGU = "ambigu"


def fait_lien(charge: Mapping[str, Any]) -> dict[str, Any]:
    return {"type_entree": TYPE_LIEN, "lead_id": charge["lead_id"], "client_id": charge["client_id"]}


def fait_profil(charge: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type_entree": TYPE_PROFIL,
        "client_id": charge["client_id"],
        "propriete_id": charge["propriete_id"],
        "revision": charge["revision"],
        "type_batiment": charge.get("type_batiment"),
        "etages": charge.get("etages"),
        "annee_construction": charge.get("annee_construction"),
        "nb_photos_liees": charge["nb_photos_liees"],
        "nb_mesures_liees": charge["nb_mesures_liees"],
        "horodatage": charge["horodatage"],
    }


def contexte_du_lead(
    liens: Iterable[Mapping[str, Any]], profils: Iterable[Mapping[str, Any]], lead_id: str
) -> dict[str, Any]:
    """Le bloc `contexte_propriete` d'une intervention, d'après son `lead_id`."""
    client_id = None
    for lien in liens:
        if lien.get("type_entree") == TYPE_LIEN and lien.get("lead_id") == lead_id:
            client_id = lien["client_id"]
            break  # le PREMIER lien fait foi (M2 n'en établit qu'un par lead ; M5 garde aussi le premier)
    if client_id is None:
        return {"statut": STATUT_ABSENT, "raison": "aucun lien lead -> client reçu de M2"}
    meilleures: dict[str, Mapping[str, Any]] = {}
    for p in profils:
        if p.get("type_entree") != TYPE_PROFIL or p.get("client_id") != client_id:
            continue
        actuelle = meilleures.get(p["propriete_id"])
        if actuelle is None or p["revision"] > actuelle["revision"]:
            meilleures[p["propriete_id"]] = p
    if not meilleures:
        return {"statut": STATUT_ABSENT, "raison": "aucun profil de propriété confirmé reçu de M2 pour ce client"}
    if len(meilleures) > 1:
        return {
            "statut": STATUT_AMBIGU,
            "raison": f"{len(meilleures)} propriétés confirmées pour ce client : M4 ne devine pas le chantier",
        }
    p = next(iter(meilleures.values()))
    return {
        "statut": STATUT_RECU,
        "source": "M2 (m2.profil_propriete_confirme)",
        "revision": p["revision"],
        "type_batiment": p["type_batiment"],
        "etages": p["etages"],
        "annee_construction": p["annee_construction"],
        "nb_photos_liees": p["nb_photos_liees"],
        "nb_mesures_liees": p["nb_mesures_liees"],
        "confirme_le": p["horodatage"],
        "nature": "renseignement pour l'équipe, jamais un volet de la préparation",
    }
