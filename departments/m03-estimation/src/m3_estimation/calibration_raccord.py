"""Jointure serveur M3→M4 pour produire une candidate de cohorte toujours inactive."""

from __future__ import annotations

import copy
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any

from . import calibration_cohortes, devis_durable, estime_vs_reel

PROTOCOLE = "cohortes-r32-v1"
_MAX_OBSERVATIONS = 2000
_MAX_DEVIS = 10000


def _devis_sequence_valide(maillons: list[Any], devis_id: str, devis: dict[str, Any]) -> bool:
    """Valide la séquence append-only existante, sans prétendre qu'elle est cryptographiquement chaînée."""
    lignes = [m for m in maillons if isinstance(m, dict) and m.get("devis_id") == devis_id]
    creations = [m for m in lignes if m.get("type_entree") == "devis_cree"]
    if len(creations) != 1 or not lignes or lignes[0] is not creations[0]:
        return False
    initial = creations[0]
    cles_creation = {
        "type_entree", "devis_id", "lead_id", "chantier_id", "lignes", "taux_marge", "cout_total",
        "prix_total", "statut", "horodatage",
    }
    cles_creation_optionnelles = {"estimation_source_hash"}
    if (
        not cles_creation <= set(initial)
        or not set(initial) <= cles_creation | cles_creation_optionnelles
        or initial.get("statut") != "brouillon"
        or not isinstance(initial.get("horodatage"), str)
    ):
        return False
    statut = "brouillon"
    for ligne in lignes[1:]:
        cles_transition = {"type_entree", "devis_id", "statut", "horodatage"}
        cles_transition_optionnelles = {
            "approbateur", "envoi_approuve_par", "envoi_approuve_role", "revue_envoi",
        }
        if (
            ligne.get("type_entree") != "transition_devis"
            or not cles_transition <= set(ligne)
            or not set(ligne) <= cles_transition | cles_transition_optionnelles
            or not isinstance(ligne.get("horodatage"), str)
        ):
            return False
        suivant = ligne.get("statut")
        if (statut, suivant) not in (("brouillon", "envoye"), ("brouillon", "accepte"), ("envoye", "accepte")):
            return False
        statut = suivant
    etat_relu, verdict = devis_durable.lire_devis(maillons, devis_id)
    return verdict is None and statut == "accepte" and etat_relu == devis


def construire_rapport(
    *,
    coupure_utc: str,
    registre_estimations: Any,
    registre_devis: Any,
    projections_m4: dict[str, Any],
    _inclure_observations: bool = False,
    _train_only: bool = False,
) -> dict[str, Any]:
    """Construit les observations depuis les registres/bus authentifiés par les adaptateurs.

    Les attestations de preuve sont calculées ici. Les valeurs venant de l'agent ne sont pas
    acceptées; seuls la coupure UTC et les registres relus par le serveur entrent.
    """
    if not isinstance(projections_m4, dict) or set(projections_m4) != {"observations", "refus"}:
        return {"statut": "refuse", "raisons": ["projection_m4_invalide"]}
    if not isinstance(projections_m4["observations"], list) or len(projections_m4["observations"]) > _MAX_OBSERVATIONS:
        return {"statut": "refuse", "raisons": ["limite_observations_depassee"]}
    raisons_refus = Counter()
    try:
        chaine_m3_valide, _ = registre_estimations.valider_chaine()
        maillons_estimations = registre_estimations.lire() if chaine_m3_valide else []
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        chaine_m3_valide, maillons_estimations = False, []
    if not chaine_m3_valide:
        return {"statut": "refuse", "raisons": ["chaine_m3_non_valide"], "candidate_active": False}
    try:
        if len(registre_devis) > _MAX_DEVIS:
            return {"statut": "refuse", "raisons": ["limite_registre_devis_depassee"], "candidate_active": False}
        lignes_devis = list(registre_devis)
    except (TypeError, ValueError, RecursionError):
        return {"statut": "refuse", "raisons": ["registre_devis_illisible"], "candidate_active": False}
    if len(lignes_devis) > _MAX_DEVIS:
        return {"statut": "refuse", "raisons": ["limite_registre_devis_depassee"], "candidate_active": False}

    observations: list[dict[str, Any]] = []
    for projection in projections_m4["observations"]:
        if not isinstance(projection, dict) or set(projection) != {
            "wct", "wct_hash", "statut_publie", "statut_courant", "horodatage_debut",
            "horodatage_depart", "horodatage_completion", "duree_reelle_minutes",
            "semantique_temps", "unite_duree",
        }:
            raisons_refus["projection_m4_invalide"] += 1
            continue
        wct = projection["wct"]
        if not isinstance(wct, dict):
            raisons_refus["wct_invalide"] += 1
            continue
        if (
            projection["wct_hash"] != wct.get("hash_maillon")
            or projection["statut_publie"] != wct.get("statut")
            or projection["statut_courant"] != "completed_verified"
            or projection["semantique_temps"] != "duree_ecoulee_intervention"
            or projection["unite_duree"] != "minute"
        ):
            raisons_refus["projection_m4_non_concordante"] += 1
            continue
        devis_id, lead_id = wct.get("devis_id"), wct.get("lead_id")
        if not isinstance(devis_id, str) or not isinstance(lead_id, str):
            raisons_refus["lien_devis_lead_absent"] += 1
            continue
        devis, erreur_devis = devis_durable.lire_devis(lignes_devis, devis_id)
        if erreur_devis is not None or not isinstance(devis, dict):
            raisons_refus["devis_introuvable"] += 1
            continue
        if not _devis_sequence_valide(lignes_devis, devis_id, devis):
            raisons_refus["chaine_devis_non_valide"] += 1
            continue
        if devis.get("statut") != "accepte" or devis.get("lead_id") != lead_id:
            raisons_refus["devis_non_accepte_ou_lead_divergent"] += 1
            continue
        hash_source = devis.get("estimation_source_hash")
        if not isinstance(hash_source, str):
            raisons_refus["source_estimation_absente"] += 1
            continue
        sources = [m for m in maillons_estimations if m.get("hash_maillon") == hash_source]
        if len(sources) != 1 or not isinstance(sources[0].get("charge"), dict):
            raisons_refus["source_estimation_hash_absent_ou_ambigu"] += 1
            continue
        charge = sources[0]["charge"]
        if charge.get("devis_id") != devis_id or charge.get("lead_id") != lead_id:
            raisons_refus["source_estimation_identite_divergente"] += 1
            continue
        # Appelle la résolution publique existante (hash exact, devis et lead), au lieu de
        # recopier son résolveur interne. La durée est reprise de la charge M3 après concordance.
        charge_acceptee = estime_vs_reel.avec_duree_estimee(
            {"devis_id": devis_id}, devis_id, lignes_devis, maillons_estimations,
        )
        trace = charge.get("trace_calibration_temps")
        if not isinstance(trace, dict) or charge_acceptee.get("duree_estimee_minutes") != trace.get(
            "duree_estimee_minutes"
        ):
            raisons_refus["trace_temps_absente_ou_non_qualifiee"] += 1
            continue
        if trace.get("version_schema") not in (2, 3) or trace.get("semantique_temps") != "duree_ecoulee_intervention":
            raisons_refus["trace_temps_absente_ou_non_qualifiee"] += 1
            continue
        try:
            quantite = Decimal(trace["quantite"])
            taux = Decimal(trace["taux_minutes_par_unite"])
            duree_estimee = Decimal(trace["duree_estimee_minutes"])
            taux_source = Decimal(trace.get("taux_minutes_par_unite_source", trace["taux_minutes_par_unite"]))
        except (KeyError, InvalidOperation, TypeError, ValueError):
            raisons_refus["trace_temps_invalide"] += 1
            continue
        if trace.get("version_schema") == 3:
            calibration_id = trace.get("calibration_version_id")
            if (not isinstance(calibration_id, str) or len(calibration_id) != 64
                    or any(c not in "0123456789abcdef" for c in calibration_id)):
                raisons_refus["trace_schema3_non_concordante"] += 1
                continue
        else:
            calibration_id = None
        observations.append({
            "wct_id": wct["wct_id"],
            "chantier_id": devis.get("chantier_id"),
            "intervention_id": wct.get("intervention_id"),
            "devis_id": devis_id,
            "horodatage_debut": projection["horodatage_debut"],
            "horodatage_completion": projection["horodatage_completion"],
            "statut": projection["statut_courant"],
            "duree_estimee_minutes": duree_estimee,
            "duree_reelle_minutes": projection["duree_reelle_minutes"],
            "type_service": trace.get("type_service"),
            "quantite": quantite,
            "unite_quantite": trace.get("unite_quantite"),
            "taux_minutes_par_unite": taux,
            "bareme_version": trace.get("bareme_version"),
            "empreinte_bareme": trace.get("empreinte_bareme"),
            "calibration_version_id": calibration_id,
            "taux_minutes_par_unite_source": taux_source,
            "preuve": {
                "m3_source_hash": hash_source,
                "m4_wct_hash": projection["wct_hash"],
                "liaison_exacte": True,
                "chaine_m3_valide": True,
                "schema_trace": trace.get("version_schema"),
                "semantique_trace": trace.get("semantique_temps"),
                "semantique_reel": projection["semantique_temps"],
                "unite_duree_estimee": "minute",
                "unite_duree_reelle": projection["unite_duree"],
            },
        })
    rapport = calibration_cohortes.construire_rapport(
        observations, coupure_utc=coupure_utc, protocole_version=PROTOCOLE, train_only=_train_only,
    )
    rapport["refus_projection_m4"] = [] if _train_only else copy.deepcopy(projections_m4["refus"])
    rapport["refus_jointure_m3"] = {} if _train_only else dict(sorted(raisons_refus.items()))
    rapport["source_wct_ids"] = "registre_m03_estime_vs_reel"
    rapport["completude_corpus_m4"] = "non_prouvee"
    rapport["candidate_active"] = False
    if _inclure_observations:
        rapport["_observations_qualifiees"] = observations
    return rapport
