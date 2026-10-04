"""Projection publique, en lecture seule, des faits M4 admissibles à la calibration M3.

Le bus est relu par type et identité; aucune charge fournie par un consommateur n'est
acceptée. La durée est recalculée depuis les pointages, jamais déduite du WCT.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from opsys import evenements, stockage

from . import etats, outbox, registre

_DEPARTEMENT = "m04-field-ops"
_REGISTRE = "principal"
_TYPE_EVENEMENT = "m4.travaux_termines"
_MAX_IDS = 200
_MAX_MAILLONS = 20000


def lire_projections(wct_ids: Any, registre_cible: Any = None) -> dict[str, Any]:
    """Projette une liste bornée de WCT demandés après vérification de la chaîne et du bus.

    ``registre_cible`` est un port de liste pour tests/composition serveur seulement. En
    production, M4 relit son registre durable dans la transaction de l'appel. Les identifiants
    sont des filtres seulement; aucun champ WCT fourni par l'appelant ne devient une preuve.
    """
    if (
        not isinstance(wct_ids, list) or not 1 <= len(wct_ids) <= _MAX_IDS
        or any(not isinstance(item, str) or not item or len(item) > 128 for item in wct_ids)
        or len(set(wct_ids)) != len(wct_ids)
    ):
        return {"observations": [], "refus": [{"motif": "identites_wct_invalides_ou_hors_bornes"}]}
    if registre_cible is None:
        registre_cible = registre.Registre(stockage.maillons(_DEPARTEMENT, _REGISTRE))
    try:
        if registre_cible.taille() > _MAX_MAILLONS:
            return {"observations": [], "refus": [{"motif": "registre_m4_hors_borne", "limite": _MAX_MAILLONS}]}
        if not registre_cible.valider_chaine():
            return {"observations": [], "refus": [{"motif": "chaine_m4_non_valide"}]}
        maillons = registre_cible.lire()
        if outbox.verifier_invariants_outbox(registre_cible)[0] is not True:
            return {"observations": [], "refus": [{"motif": "invariants_wct_non_valides"}]}
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        return {"observations": [], "refus": [{"motif": "chaine_m4_non_valide"}]}

    par_id: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for m in maillons:
        wct = m.get(outbox.CLE_WCT)
        if isinstance(wct, dict) and isinstance(wct.get("wct_id"), str):
            par_id.setdefault(wct["wct_id"], []).append((m, wct))
    observations: list[dict[str, Any]] = []
    refus: list[dict[str, str]] = []
    for wct_id in wct_ids:
        trouves = par_id.get(wct_id, [])
        if len(trouves) != 1:
            refus.append({"wct_id": wct_id, "motif": "wct_absent_ou_ambigu"})
            continue
        maillon, wct = trouves[0]
        canonique = evenements.charge_publiee(_TYPE_EVENEMENT, wct_id)
        if canonique is None or canonique != wct:
            refus.append({"wct_id": wct_id, "motif": "fait_bus_absent_ou_divergent"})
            continue
        intervention_id = wct.get("intervention_id")
        courant = etats.statut_courant(registre_cible, intervention_id)
        if courant != "completed_verified":
            refus.append({"wct_id": wct_id, "motif": "statut_courant_non_verifie"})
            continue
        if wct.get("statut") not in outbox.STATUTS_COMPLETION:
            refus.append({"wct_id": wct_id, "motif": "statut_publie_invalide"})
            continue
        pointages = [
            p for p in maillons
            if p.get("type_entree") == "pointage" and p.get("intervention_id") == intervention_id
        ]
        arrivees = [p.get("horodatage") for p in pointages if p.get("action") == "arrivee"]
        departs = [p.get("horodatage") for p in pointages if p.get("action") == "depart"]
        if not arrivees or not departs:
            refus.append({"wct_id": wct_id, "motif": "arrivee_ou_depart_absent"})
            continue
        try:
            debut_dt = min(datetime.fromisoformat(value) for value in arrivees)
            depart_dt = max(datetime.fromisoformat(value) for value in departs)
            completion_dt = datetime.fromisoformat(wct["horodatage_completion"])
            if any(value.tzinfo is None for value in (debut_dt, depart_dt, completion_dt)):
                raise ValueError("fuseau absent")
            if depart_dt < debut_dt or completion_dt < depart_dt:
                refus.append({"wct_id": wct_id, "motif": "chronologie_invalide"})
                continue
            debut_utc = debut_dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
            depart_utc = depart_dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
            completion_utc = completion_dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
        except (KeyError, TypeError, ValueError):
            refus.append({"wct_id": wct_id, "motif": "chronologie_invalide"})
            continue
        duree, code = outbox.calculer_duree_reelle(registre_cible, intervention_id)
        if code is not None or duree != wct.get("duree_reelle_minutes"):
            refus.append({"wct_id": wct_id, "motif": "duree_recalculee_divergente"})
            continue
        observations.append({
            "wct": {cle: wct.get(cle) for cle in (
                "wct_id", "intervention_id", "lead_id", "devis_id", "statut",
                "hash_maillon", "horodatage_completion", "duree_reelle_minutes",
            )},
            "wct_hash": wct.get("hash_maillon"),
            "statut_publie": wct.get("statut"),
            "statut_courant": courant,
            "horodatage_debut": debut_utc,
            "horodatage_depart": depart_utc,
            "horodatage_completion": completion_utc,
            "duree_reelle_minutes": duree,
            "semantique_temps": "duree_ecoulee_intervention",
            "unite_duree": "minute",
        })
    return {"observations": observations, "refus": refus}
