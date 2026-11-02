"""Application d'une version d'apprentissage dans l'orchestrateur d'estimation : durée sur site corrigée, trace durable
« version, n chantiers, intervalle », mode ombre sans effet, barème modifié sans effet, prix inchangé. Fictif."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import estimation, registre  # noqa: E402

FICTIF = True
VERSION = "c" * 64


def bareme(taux=30):
    return {"version": "2026.1", "unite": "pi_lin", "semantique_temps": "duree_ecoulee_intervention",
            "postes": {"ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0,
                                      "duree_minutes_par_unite": taux}}}


def version(**plus):
    base = {
        "version_id": VERSION, "cohorte": {"type_service": "ravalement", "unite_quantite": "pi_lin"},
        "taux_baseline": "30.0000", "taux_applique": "34.2857", "facteur": "1.1429",
        "intervalle": {"bas": "33.9000", "haut": "34.6000", "niveau": "0.90"}, "n_chantiers": 12,
        "mode_activation": "auto",
    }
    base.update(plus)
    return base


def orchestrer(**plus):
    contrat = {"lead_id": "lead-appr-1", "conversation_id": "conv-appr-1", "type_travaux": "ravalement",
               "ville": "Quebec", "canal": "formulaire_web",
               "contact": {"nom": "Client fictif", "telephone": "5145550000"},
               "urgence_declaree": False}
    marqueur = {"readiness_ok": True, "lead_id": "lead-appr-1", "hash_tete_registre": "f" * 64,
                "horodatage": "2026-09-28T10:00:00-04:00", "empreinte": "a" * 64}
    photo = {"photo_id": "p1", "resolution_largeur": 3000, "resolution_hauteur": 2000, "eclairage": 7, "angle": "face",
             "reference_echelle": {"type": "porte", "dimensions_connues": True}}
    reg = registre.Registre()
    params = {"contrat": contrat, "marqueur": marqueur, "photos": [photo],
              "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4}, "bareme": bareme(), "quantite": 28,
              "plancher_rentable": 1, "registre_cible": reg, "graine": 42, "taux_marge": "0.20"}
    params.update(plus)
    reponse = estimation.orchestrer_estimation(**params)
    return reponse, reg


def charge_ecrite(reg):
    return reg.lire()[-1]["charge"]


def test_sans_apprentissage_la_charge_et_le_hash_sont_ceux_d_avant():
    reponse, reg = orchestrer()
    assert reponse["accepte"] and Decimal(reponse["duree_estimee_minutes"]) == 840
    assert reponse["apprentissage_duree"] is None
    assert "apprentissage_duree" not in charge_ecrite(reg)
    assert charge_ecrite(reg)["trace_calibration_temps"]["version_schema"] == 2


def test_version_active_14h_devient_16h_avec_trace_et_prix_inchange():
    avant, _ = orchestrer()
    reponse, reg = orchestrer(apprentissage_duree=version())
    assert abs(Decimal(reponse["duree_estimee_minutes"]) - 960) < Decimal("0.01")
    bloc = reponse["apprentissage_duree"]
    assert bloc["statut"] == "applique" and bloc["version_id"] == VERSION and bloc["n_chantiers"] == 12
    assert bloc["intervalle"]["bas"] == "33.9000" and Decimal(bloc["temps_sur_site_baseline_minutes"]) == 840
    assert bloc["deplacement"]["inclus"] is False
    charge = charge_ecrite(reg)
    trace = charge["trace_calibration_temps"]
    assert trace["version_schema"] == 3 and trace["calibration_version_id"] == VERSION
    assert Decimal(trace["taux_minutes_par_unite_source"]) == 30 and trace["taux_minutes_par_unite"] == "34.2857"
    assert charge["apprentissage_duree"]["version_id"] == VERSION and charge["duree_estimee_minutes"] == \
        reponse["duree_estimee_minutes"]
    # La durée sur site ne touche ni l'intervalle de coût ni le prix recommandé : seule la durée change.
    assert reponse["estimation"]["intervalle_confiance"] == avant["estimation"]["intervalle_confiance"]
    assert reponse["prix_recommande"] == avant["prix_recommande"]


def test_ombre_montre_16h_mais_n_applique_rien_et_la_charge_reste_identique():
    base, reg_base = orchestrer()
    reponse, reg = orchestrer(apprentissage_ombre=version())
    assert Decimal(reponse["duree_estimee_minutes"]) == 840
    bloc = reponse["apprentissage_duree"]
    assert bloc["statut"] == "ombre" and abs(Decimal(bloc["temps_sur_site_ombre_minutes"]) - 960) < Decimal("0.01")
    assert charge_ecrite(reg) == charge_ecrite(reg_base)
    assert reponse["estimation"]["hash_maillon"] == base["estimation"]["hash_maillon"]


def test_bareme_modifie_depuis_la_version_rien_n_est_applique_et_la_raison_est_dite():
    reponse, reg = orchestrer(apprentissage_duree=version(), bareme=bareme(31))
    assert Decimal(reponse["duree_estimee_minutes"]) == 868
    assert reponse["apprentissage_duree"]["statut"] == "non_appliquee"
    assert reponse["apprentissage_duree"]["raison"] == "bareme_modifie_depuis_la_version"
    assert "apprentissage_duree" not in charge_ecrite(reg)


def test_version_d_une_autre_cohorte_n_est_pas_appliquee():
    autre = version(cohorte={"type_service": "extension", "unite_quantite": "pi_lin"})
    reponse, _ = orchestrer(apprentissage_duree=autre)
    assert Decimal(reponse["duree_estimee_minutes"]) == 840
    assert reponse["apprentissage_duree"]["raison"] == "cohorte_differente"


def test_calibration_exacte_et_apprentissage_sont_exclusifs():
    reponse, reg = orchestrer(apprentissage_duree=version(), calibration_candidate={"scope": {}})
    assert reponse["accepte"] is False and reponse["raisons"] == ["calibrations_exclusives"] and len(reg.lire()) == 0


def test_sans_duree_dans_le_bareme_aucun_apprentissage_n_invente_une_duree():
    b = bareme()
    del b["postes"]["ravalement"]["duree_minutes_par_unite"]
    reponse, _ = orchestrer(apprentissage_duree=version(), bareme=b)
    assert reponse["duree_estimee_minutes"] is None
    assert reponse["apprentissage_duree"]["statut"] == "aucune"
