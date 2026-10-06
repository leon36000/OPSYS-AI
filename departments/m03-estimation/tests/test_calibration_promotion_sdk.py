"""Parcours gouverné de calibration sur SQLite et les outils M3/M4 réels.

Toutes les données de chantier sont fictives. Les 30 WCT train précèdent le sceau; un WCT à date
métier future est déjà reçu et doit rester hors holdout. Les 30 WCT holdout sont reçus après la
proposition et commencent après sa coupure.
"""

from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import json
import struct
import sys
import zlib
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

_SRC_M3 = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_M3) not in sys.path:
    sys.path.insert(0, str(_SRC_M3))

from m3_estimation import outils as outils_m3  # noqa: E402
from m4_field_ops import outbox as outbox_m4  # noqa: E402
from m4_field_ops import registre as registre_m4  # noqa: E402
from m4_field_ops.outils import outils as outils_m4  # noqa: E402

from opsys import approbations, contexte, evenements, identite, stockage  # noqa: E402
from opsys.capacites import Capacites, outils_executables  # noqa: E402
from opsys.departements import charger_departements  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402

FICTIF = True
DEP = "m03-estimation"
DEBUT_TRAIN = date(2025, 6, 2)
DEBUT_HOLDOUT = date(2025, 7, 4)
_MOT_DE_PASSE = "mot-de-passe-long-pour-fixture"


@pytest.fixture
def base_promotion(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'calibration-promotion.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "proprio-calibration", "Owner fictif", _MOT_DE_PASSE,
                                ["admin", "nathan_owner"])
    yield url
    stockage.liberer()


def _png_test() -> bytes:
    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b"")
    )


def _deposer_photo_m4(par_nom: dict[str, object]) -> str:
    body = _png_test()
    response = executer_atomique(par_nom["m4_deposer_fichier"], {
        "empreinte_sha256": hashlib.sha256(body).hexdigest(), "taille_octets": len(body),
        "type_mime": "image/png", "index_bloc": 0, "nombre_blocs": 1,
        "bloc_base64": base64.b64encode(body).decode("ascii"),
    })
    assert response["ok"] and response["resultat"]["accepte"]
    return response["resultat"]["resultat"]["reference"]


def _estimation_et_devis(par_nom: dict[str, object], index: int) -> tuple[str, str, dict, dict]:
    lead_id = f"LEAD-CAL-PROMO-{index:03d}"
    estimation = executer_atomique(par_nom["m3_estimer_projet"], {
        "contrat": {
            "lead_id": lead_id, "conversation_id": f"CONV-CAL-PROMO-{index:03d}",
            "type_travaux": "renovation_totale", "ville": "Montreal", "canal": "formulaire",
            "contact": {"nom": "Client fictif", "telephone": "5145550101"}, "urgence_declaree": False,
        },
        "marqueur": {
            "readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": "f" * 64,
            "horodatage": "2025-06-01T12:00:00Z", "empreinte": "ab" * 32,
        },
        "photos": [{
            "photo_id": f"photo-cal-promo-{index:03d}", "resolution_largeur": 3000,
            "resolution_hauteur": 2000, "eclairage": 7, "angle": "face",
            "reference_echelle": {"type": "porte", "dimensions_connues": True},
        }],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": {
            "version": "calibration-r2-sdk-fictif", "unite": "pi_lin",
            "semantique_temps": "duree_ecoulee_intervention",
            "postes": {"renovation_totale": {
            "cout_unitaire_min": 10.0, "cout_unitaire_max": 20.0, "duree_minutes_par_unite": 15.0,
            }},
        },
        "quantite": 10.0, "plancher_rentable": 1, "graine": 7000,
    })
    assert estimation["ok"] and estimation["resultat"]["accepte"], estimation
    devis_id = estimation["resultat"]["estimation"]["devis_id"]
    source_hash = estimation["resultat"]["estimation"]["hash_maillon"]
    source = next(m for m in outils_m3.registre_production().lire() if m["hash_maillon"] == source_hash)
    trace = source["charge"]["trace_calibration_temps"]
    assert trace["version_schema"] == 2 and trace["semantique_temps"] == "duree_ecoulee_intervention"
    assert trace["duree_estimee_minutes"] == "150.00"

    devis = executer_atomique(par_nom["m3_creer_devis"], {
        "devis_id": devis_id, "estimation_source_hash": source_hash, "lead_id": lead_id,
        "chantier_id": f"CHANTIER-CAL-PROMO-{index:03d}",
        "lignes": [{"description": "Travaux fictifs", "quantite": "10", "unite": "pi_lin",
                    "cout_unitaire": "12.00", "reference_besoin_materiau": None}],
        "taux_marge": "0.20", "horodatage": "2025-06-01T13:00:00Z",
    })
    assert devis["ok"] and devis["resultat"]["accepte"], devis
    acceptee = executer_atomique(par_nom["m3_marquer_devis_accepte"], {
        "devis_id": devis_id, "approbateur": "approbateur-fictif", "horodatage": "2025-06-01T14:00:00Z",
    })
    assert acceptee["ok"] and acceptee["resultat"]["accepte"], acceptee
    maillon_source = next(m for m in outils_m3.registre_production().lire() if m["hash_maillon"] == source_hash)
    return lead_id, devis_id, maillon_source, estimation["resultat"]


def _terminer_wct(par_nom: dict[str, object], index: int, jour: date) -> tuple[str, dict, dict]:
    lead_id, devis_id, maillon_source, estimation_source = _estimation_et_devis(par_nom, index)
    jour_iso = jour.isoformat()
    technicien = f"T-CAL-{index:03d}"
    fenetre = {"debut": f"{jour_iso}T07:00:00+00:00", "fin": f"{jour_iso}T19:00:00+00:00"}
    plan = executer_atomique(par_nom["m4_planifier_intervention"], {
        "contrat": {
            "lead_id": lead_id, "conversation_id": f"CONV-CAL-PROMO-{index:03d}",
            "type_travaux": "renovation_totale", "ville": "Montreal", "canal": "formulaire",
            "contact": {"nom": "Client fictif", "telephone": "5145550101"}, "urgence_declaree": False,
        },
        "marqueur": {"readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
                     "horodatage": "2025-06-01T12:00:00Z", "empreinte": "ab" * 32},
        "horodatage": f"{jour_iso}T08:00:00+00:00", "sel": "calibration-promotion-fictive",
        "techniciens_disponibles": [technicien], "fenetres_disponibles": [fenetre], "devis_id": devis_id,
    })
    assert plan["ok"] and plan["resultat"]["accepte"], plan
    intervention_id = plan["resultat"]["intervention_id"]
    consentement = executer_atomique(par_nom["m4_definir_consentement_gps"], {
        "technicien_id": technicien, "action": "donne", "horodatage": f"{jour_iso}T07:00:00+00:00",
        "version_politique": "POLITIQUE-geolocalisation-v1-test",
        "preuve": {"fictif": True, "reference": f"consentement-{index}"},
    })
    assert consentement["ok"] and consentement["resultat"]["accepte"], consentement
    depart = executer_atomique(par_nom["m4_demarrer_route"], {
        "intervention_id": intervention_id, "technicien_id": technicien,
        "horodatage": f"{jour_iso}T08:30:00+00:00",
    })
    assert depart["ok"] and depart["resultat"]["accepte"], depart
    token = __import__("m4_field_ops.cedule", fromlist=["tokeniser_ville"]).tokeniser_ville(
        "calibration-promotion-fictive", "Montreal",
    )
    reference = {token: {"latitude": 45.5088, "longitude": -73.5878, "rayon_km": 25.0}}
    pointages = (
        ("arrivee", f"{jour_iso}T09:00:00+00:00"),
        ("pause_debut", f"{jour_iso}T10:00:00+00:00"),
        ("pause_fin", f"{jour_iso}T10:15:00+00:00"),
        ("depart", f"{jour_iso}T11:30:00+00:00"),
    )
    for action, timestamp in pointages:
        pointage = executer_atomique(par_nom["m4_pointer"], {
            "intervention_id": intervention_id, "technicien_id": technicien, "action": action,
            "horodatage": timestamp, "fix_gps": {"latitude": 45.5088, "longitude": -73.5878},
            "attestation": {"fictif": True, "appareil_id": "APP-CALIBRATION"},
            "fenetre_travail": fenetre, "referentiel_villes": reference, "ville": "Montreal",
            "sel": "calibration-promotion-fictive",
        })
        assert pointage["ok"] and pointage["resultat"]["accepte"], pointage
    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": intervention_id, "horodatage": f"{jour_iso}T11:35:00+00:00",
        "preuves_completion": {"checklist_complete": True, "photos_apres": [_deposer_photo_m4(par_nom)],
                               "notes": "Fixture fictive R2", "signature": None},
    })
    assert completion["ok"] and completion["resultat"]["accepte"], completion
    wct_id = completion["resultat"]["resultat"]["wct_id"]
    assert completion["resultat"]["resultat"]["duree_reelle_minutes"] == 135
    with stockage.transaction():
        faits = registre_m4.Registre(stockage.maillons("m04-field-ops", "principal"))
        accuse, verdict = outbox_m4.resoudre_revue_completion(
            intervention_id, "verifiee", f"{jour_iso}T12:00:00+00:00", faits,
            motif="Vérification de fixture fictive de calibration.",
        )
    assert verdict is None and accuse["statut"] == "completed_verified"
    return wct_id, maillon_source, estimation_source


def _outils_m3() -> dict[str, object]:
    return {outil.nom: outil for outil in outils_m3.outils()}


def _livrer_bus(departements: dict) -> None:
    resultat = evenements.repartir({DEP: departements[DEP]})
    assert resultat["echecs"] == 0 and resultat["quarantaines"] == 0, resultat


def _contient_cle(valeur: object, cible: str) -> bool:
    if isinstance(valeur, dict):
        return cible in valeur or any(_contient_cle(enfant, cible) for enfant in valeur.values())
    if isinstance(valeur, list):
        return any(_contient_cle(enfant, cible) for enfant in valeur)
    return False


def _decider_owner(base_departements: dict, demande_id: str, *, owner: str = "proprio-calibration"):
    with stockage.transaction() as cnx:
        executables = outils_executables(base_departements, lambda: contextlib.nullcontext(cnx))
        return approbations.decider(cnx, demande_id, True, owner, executables, base_departements)


def test_capacites_real_m4_train_holdout_n4_activation_consumption_rollback(base_promotion, monkeypatch):
    departements = charger_departements()
    par_nom = {**_outils_m3(), **{outil.nom: outil for outil in outils_m4()}}
    capacites = Capacites(departements, stockage.transaction, appelant=DEP, limite_sortie=200_000, memoire=False)
    train_wcts = []
    old_estimations = []

    for index in range(30):
        wct_id, old_record, old_estimation = _terminer_wct(par_nom, index, DEBUT_TRAIN + timedelta(days=index))
        train_wcts.append(wct_id)
        old_estimations.append((old_record, old_estimation))
    assert len(set(train_wcts)) == 30
    wct_connu_avant_sceau, _, _ = _terminer_wct(par_nom, 90, date(2026, 1, 2))
    _livrer_bus(departements)
    with contexte.appeler_en_tant_que(DEP):
        proposition = capacites.appeler("m3_proposer_calibration_temps", {
            "coupure_utc": "2025-07-02T00:00:00Z", "coupure_evaluation_utc": "2025-07-03T00:00:00Z",
        })
    assert proposition.get("ok") is True and isinstance(proposition.get("resultat"), dict), proposition
    assert proposition["resultat"]["statut"] == "proposee", proposition
    [candidate] = proposition["resultat"]["candidates"]
    assert candidate["candidate_active"] is False and candidate["taux_minutes_par_unite_candidat"] == "13.5"
    from m3_estimation import calibration_versions
    candidate_persisted = calibration_versions.lire_candidate(
        outils_m3.registre_calibration_versions_production(), candidate["candidate_id"],
    )
    assert candidate_persisted["source_wct_prefix"]["count"] == 31
    hash_id_independant = hashlib.sha256(json.dumps(
        wct_connu_avant_sceau, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()
    assert hash_id_independant in candidate_persisted["source_wct_hashes_vus"]
    assert not _contient_cle(proposition["resultat"], "_observations_qualifiees")

    empreinte_prefixe_reelle = outils_m3._prefixe_recu_wct
    def prefixe_altere(maillons):
        maillons_alteres = copy.deepcopy(maillons)
        premier_recu = next(m for m in maillons_alteres if m.get("type_entree") == "wct_recu")
        premier_recu["lead_id"] += "-corrompu"
        return empreinte_prefixe_reelle(maillons_alteres)
    monkeypatch.setattr(outils_m3, "_prefixe_recu_wct", prefixe_altere)
    with contexte.appeler_en_tant_que(DEP):
        prefixe_modifie = capacites.appeler("m3_evaluer_candidate_calibration", {
            "candidate_id": candidate["candidate_id"],
        })
    monkeypatch.setattr(outils_m3, "_prefixe_recu_wct", empreinte_prefixe_reelle)
    assert prefixe_modifie["ok"] and prefixe_modifie["resultat"]["raisons"] == ["prefixe_wct_m3_modifie"]

    holdout_wcts = []
    for index in range(30, 60):
        wct_id, old_record, old_estimation = _terminer_wct(par_nom, index, DEBUT_HOLDOUT + timedelta(days=index - 30))
        holdout_wcts.append(wct_id)
        old_estimations.append((old_record, old_estimation))
    assert len(set(holdout_wcts)) == 30
    _terminer_wct(par_nom, 60, date(2025, 7, 2))  # reçu après le sceau, mais date métier hors holdout
    _livrer_bus(departements)
    with contexte.appeler_en_tant_que(DEP):
        evaluation = capacites.appeler("m3_evaluer_candidate_calibration", {
            "candidate_id": candidate["candidate_id"],
        })
    assert evaluation["ok"] and evaluation["resultat"]["statut"] == "acceptable", evaluation
    assert evaluation["resultat"]["holdout_chantiers"] == 30
    assert evaluation["resultat"]["couverture_numerateur"] == 30
    assert evaluation["resultat"]["couverture_denominateur"] == 32
    assert len(evaluation["resultat"]["holdout_wct_hashes"]) == 30
    assert evaluation["resultat"]["mae_baseline_minutes"] == "15"
    assert Decimal(evaluation["resultat"]["mae_candidate_minutes"]) == 0
    assert evaluation["resultat"]["candidate_active"] is False

    args_activation = {"candidate_id": candidate["candidate_id"], "active_version_attendue": None}
    attente = capacites.appeler("m3_activer_candidate_calibration", args_activation)
    assert attente["ok"] and attente["statut"] == "en_attente_approbation", attente
    assert calibration_versions_active() is None
    approved = _decider_owner(departements, attente["demande_id"])
    assert approved["statut"] == "executee" and approved["reponse"]["resultat"]["accepte"] is True, approved
    assert calibration_versions_active()["candidate_id"] == candidate["candidate_id"]

    with contexte.appeler_en_tant_que(DEP):
        nouveau = capacites.appeler("m3_estimer_projet", {
            "contrat": {
                "lead_id": "LEAD-CAL-PROMO-ACTIVE", "conversation_id": "CONV-CAL-PROMO-ACTIVE",
                "type_travaux": "renovation_totale", "ville": "Montreal", "canal": "formulaire",
                "contact": {"nom": "Client fictif", "telephone": "5145550101"}, "urgence_declaree": False,
            },
            "marqueur": {"readiness_ok": True, "lead_id": "LEAD-CAL-PROMO-ACTIVE",
                         "hash_tete_registre": "f" * 64, "horodatage": "2025-06-01T12:00:00Z",
                         "empreinte": "ab" * 32},
            "photos": [{"photo_id": "photo-active", "resolution_largeur": 3000, "resolution_hauteur": 2000,
                         "eclairage": 7, "angle": "face",
                         "reference_echelle": {"type": "porte", "dimensions_connues": True}}],
            "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
            "bareme": {"version": "calibration-r2-sdk-fictif", "unite": "pi_lin",
                       "semantique_temps": "duree_ecoulee_intervention", "postes": {"renovation_totale": {
                           "cout_unitaire_min": 10.0, "cout_unitaire_max": 20.0,
                           "duree_minutes_par_unite": 15.0}}},
            "quantite": 10.0, "plancher_rentable": 1, "graine": 7000,
        })
    assert nouveau.get("ok") and nouveau.get("statut") == "en_attente_approbation", nouveau
    nouveau = _decider_owner(departements, nouveau["demande_id"])
    assert nouveau["statut"] == "executee" and nouveau["reponse"]["resultat"]["accepte"], nouveau
    nouveau = nouveau["reponse"]
    nouveau_charge = next(m["charge"] for m in outils_m3.registre_production().lire()
                          if m["charge"].get("lead_id") == "LEAD-CAL-PROMO-ACTIVE")
    trace_active = nouveau_charge["trace_calibration_temps"]
    assert trace_active["version_schema"] == 3
    assert float(trace_active["taux_minutes_par_unite_source"]) == 15
    assert trace_active["taux_minutes_par_unite"] == "13.5"
    assert nouveau["resultat"]["prix_recommande"] == old_estimations[0][1]["prix_recommande"]

    demande_rollback = capacites.appeler("m3_rollback_candidate_calibration", {
        "candidate_id": candidate["candidate_id"],
    })
    assert demande_rollback["ok"] and demande_rollback["statut"] == "en_attente_approbation"
    rollback = _decider_owner(departements, demande_rollback["demande_id"])
    assert rollback["statut"] == "executee" and rollback["reponse"]["resultat"]["accepte"] is True
    assert calibration_versions_active() is None
    historique_apres = [m for m in outils_m3.registre_production().lire()
                        if m["charge"].get("lead_id") in {f"LEAD-CAL-PROMO-{i:03d}" for i in range(60)}]
    assert historique_apres == [record for record, _ in old_estimations]
    with contexte.appeler_en_tant_que(DEP):
        apres_rollback = capacites.appeler("m3_estimer_projet", {
            "contrat": {
                "lead_id": "LEAD-CAL-PROMO-POST-ROLLBACK", "conversation_id": "CONV-CAL-PROMO-POST",
                "type_travaux": "renovation_totale", "ville": "Montreal", "canal": "formulaire",
                "contact": {"nom": "Client fictif", "telephone": "5145550101"}, "urgence_declaree": False,
            },
            "marqueur": {"readiness_ok": True, "lead_id": "LEAD-CAL-PROMO-POST-ROLLBACK",
                         "hash_tete_registre": "f" * 64, "horodatage": "2025-06-01T12:00:00Z",
                         "empreinte": "ab" * 32},
            "photos": [{"photo_id": "photo-post-rollback", "resolution_largeur": 3000,
                         "resolution_hauteur": 2000, "eclairage": 7, "angle": "face",
                         "reference_echelle": {"type": "porte", "dimensions_connues": True}}],
            "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
            "bareme": {"version": "calibration-r2-sdk-fictif", "unite": "pi_lin",
                       "semantique_temps": "duree_ecoulee_intervention", "postes": {"renovation_totale": {
                           "cout_unitaire_min": 10.0, "cout_unitaire_max": 20.0,
                           "duree_minutes_par_unite": 15.0}}},
            "quantite": 10.0, "plancher_rentable": 1, "graine": 7000,
        })
    assert apres_rollback.get("ok") and apres_rollback.get("statut") == "en_attente_approbation", apres_rollback
    apres_rollback = _decider_owner(departements, apres_rollback["demande_id"])["reponse"]
    assert apres_rollback["resultat"]["accepte"], apres_rollback
    charge_post = next(m["charge"] for m in outils_m3.registre_production().lire()
                       if m["charge"].get("lead_id") == "LEAD-CAL-PROMO-POST-ROLLBACK")
    assert charge_post["trace_calibration_temps"]["version_schema"] == 2


def _outils_m3():
    return {outil.nom: outil for outil in outils_m3.outils()}


def calibration_versions_active():
    """État courant interrogé par l'API produit, pas un drapeau de fixture."""
    from m3_estimation import calibration_versions

    return calibration_versions.version_active(
        outils_m3.registre_calibration_versions_production(), "renovation_totale", "pi_lin",
        "calibration-r2-sdk-fictif", outils_m3.estimation.trace_calibration_temps.empreinte_bareme({
            "version": "calibration-r2-sdk-fictif", "unite": "pi_lin",
            "semantique_temps": "duree_ecoulee_intervention", "postes": {"renovation_totale": {
                "cout_unitaire_min": 10.0, "cout_unitaire_max": 20.0, "duree_minutes_par_unite": 15.0,
            }},
        }), "10", "15", None,
    )


def test_n4_owner_role_retire_pendant_attente_ne_peut_pas_activer(base_promotion):
    departements = charger_departements()
    capacites = Capacites(departements, stockage.transaction, appelant=DEP, memoire=False)
    attente = capacites.appeler("m3_activer_candidate_calibration", {
        "candidate_id": "e" * 64, "active_version_attendue": None,
    })
    assert attente["ok"] and attente["statut"] == "en_attente_approbation", attente
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "proprio-calibration", "nathan_owner")
    with pytest.raises(ValueError, match="aucun rôle autorisé"):
        _decider_owner(departements, attente["demande_id"])
    with stockage.transaction() as cnx:
        demande = approbations.lire(cnx, attente["demande_id"])
    assert demande["statut"] == "en_attente"
    assert calibration_versions_active() is None


def test_couverture_source_m4_reelle_avant_apres_reception_m3(base_promotion):
    """Le diagnostic observe la publication réelle sans déclencher le répartiteur."""
    from sqlalchemy import select

    from opsys.stockage.schema import EVENEMENTS_SORTANTS, REGISTRES

    departements = charger_departements()
    par_nom = {**_outils_m3(), **{outil.nom: outil for outil in outils_m4()}}
    wct_id, _, _ = _terminer_wct(par_nom, 801, DEBUT_TRAIN)
    capacites = Capacites(departements, stockage.transaction, appelant=DEP, limite_sortie=6_000, memoire=False)

    def sources():
        with stockage.transaction() as cnx:
            return (list(cnx.execute(select(EVENEMENTS_SORTANTS))), list(cnx.execute(select(REGISTRES))))

    def lire():
        with contexte.appele_par_appareil(contexte.IdentiteAppelante("proprio-calibration", "admin")):
            reponse = capacites.appeler("m3_auditer_couverture_apprentissage", {})
        assert reponse["ok"], reponse
        return reponse["resultat"]

    avant = sources()
    sans_reception = lire()
    assert sans_reception["statut"] == "ecarts"
    assert sans_reception["compteurs"] == {
        "publications_m4": 1, "recus_m3": 0, "recoupes": 0, "manquants_m3": 1, "hors_univers_m4": 0,
    }
    assert sans_reception["manquants_m3"] == {"exemples": [wct_id], "omis": 0}
    assert sources() == avant

    _livrer_bus(departements)  # Action séparée, volontaire du test; jamais du diagnostic.
    apres_livraison = sources()
    reception = lire()
    assert reception["statut"] == "identites_recues"
    assert reception["compteurs"] == {
        "publications_m4": 1, "recus_m3": 1, "recoupes": 1, "manquants_m3": 0, "hors_univers_m4": 0,
    }
    assert reception["contenu_wct_verifie"] is False and reception["candidate_active"] is False
    assert reception["completude_corpus_m4"] == "non_prouvee"
    assert not any(_contient_cle(reception, cle) for cle in (
        "fix_gps_completion", "technicien_id", "lead_id", "devis_id", "main_doeuvre", "materiaux",
    ))
    assert sources() == apres_livraison
