"""Références de corrections : projection pure, ordre du registre, aucune reprise automatique."""
from __future__ import annotations

import hashlib

TYPE = "m2.contact_corrige"


def charge(client_id, lead_id, revision, source_ligne_id, horodatage):
    cle = f"m2-contact-v1:{client_id}:{revision}:{lead_id}"
    return {"fait_id": hashlib.sha256(cle.encode("utf-8")).hexdigest(),
            "client_id": client_id, "lead_id": lead_id, "revision": revision,
            "source_ligne_id": source_ligne_id, "horodatage": horodatage}


def references_attendues(maillons, client_id, revision_max):
    """Les projets ajoutés après une correction ne font pas partie de son fanout historique."""
    projets = {}
    for maillon in maillons:
        if maillon.get("client_id") != client_id:
            continue
        if maillon.get("type_entree") == "client_associe":
            projets[maillon["lead_id"]] = None
        elif maillon.get("type_entree") == "contact_client_corrige" and maillon["revision"] <= revision_max:
            for lead_id in projets:
                yield charge(client_id, lead_id, maillon["revision"], maillon["ligne_id"], maillon["horodatage"])


def comparer(attendu, publication, memoires, recu):
    """Sortie fermée ; jamais la charge reçue, une erreur libre ou les coordonnées d'origine."""
    publie = publication is not None
    publication_conforme = publie and publication["charge"] == attendu and (
        publication["producteur"] == "m02-revenue-crm" and publication["type_evenement"] == TYPE)
    memoire_conforme = bool(memoires) and len(memoires) == 1 and all(
        memoires[0].get(k) == v for k, v in attendu.items()) and memoires[0].get("confidentialite") == "CLIENT_PRIVATE"
    livraison = recu["statut"] if recu else "absent"
    contradictoire = (publie and not publication_conforme) or (bool(memoires) and not memoire_conforme)
    if recu and livraison == "traite":
        contradictoire |= not memoire_conforme or recu.get("contradictoire", False)
    if contradictoire:
        etat = "CONFLIT"
    elif not publie:
        etat = "NON_PUBLIE"
    elif memoire_conforme:
        etat = "MEMORISE"
    else:
        etat = {"echec": "ECHEC_LIVRAISON", "quarantaine": "QUARANTAINE"}.get(livraison, "EN_ATTENTE")
    return {"fait_id": attendu["fait_id"], "lead_id": attendu["lead_id"], "revision": attendu["revision"],
            "source_ligne_id": attendu["source_ligne_id"], "etat": etat,
            "publication_presente": publie, "memoire_presente": bool(memoires), "livraison": livraison}
