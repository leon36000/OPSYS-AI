"""Contrat des réponses publiques produites par les vrais outils M8, avec données QA fictives."""

from __future__ import annotations

from decimal import Decimal

import pytest

from m8_analytics import entonnoir, mesures_chantier, operations_recues
from m8_analytics import outils as m8_outils
from m8_analytics.registre import RegistreSnapshots
from opsys.evenements import schemas as catalogue
from opsys.outils import executer


def _faits_entonnoir():
    faits = []
    for i in range(1, 4):
        lead_id = f"qa-lead-{i}"
        devis_id = f"qa-devis-{i}"
        jour = f"2026-01-0{i}"
        faits.append(entonnoir.fait_lead_recu({
            "lead_id": lead_id, "client_id": "a" * 64,
            "horodatage_association": f"{jour}T00:00:00Z",
        }))
        faits.append(entonnoir.fait_devis_envoye({
            "devis_id": devis_id, "lead_id": lead_id,
            "horodatage_envoi": f"{jour}T00:01:00Z",
        }))
        if i < 3:
            faits.append(entonnoir.fait_devis_accepte({
                "devis_id": devis_id, "lead_id": lead_id, "prix_total": "500.00",
                "horodatage_acceptation": f"2026-01-0{i + 1}T05:44:09.600000Z",
            }))
        else:
            faits.append(entonnoir.fait_devis_sans_reponse({
                "devis_id": devis_id, "lead_id": lead_id, "statut": "envoye",
                "horodatage_reference": "2026-01-10T00:00:00Z",
                "horodatage_devis": f"{jour}T00:01:00Z", "delai_relance_jours": 7,
            }))
    return faits


def _faits_chantier():
    wct_id, devis_id = "qa-wct-fictif", "qa-devis-chantier-fictif"
    faits = [
        mesures_chantier.fait_wct({
            "wct_id": wct_id, "intervention_id": "qa-intervention-fictive", "devis_id": devis_id,
            "technicien_id": "qa-technicien-fictif", "horodatage_completion": "2026-02-01T12:00:00Z",
            "duree_reelle_minutes": 4, "statut": "completed_verified",
        }),
        mesures_chantier.fait_devis({
            "devis_id": devis_id, "prix_total": "1000.00", "cout_total": "600.00",
            "duree_estimee_minutes": "3", "horodatage_acceptation": "2026-01-20T12:00:00Z",
        }),
        mesures_chantier.fait_variance({
            "wct_id": wct_id, "statut_variance": "evaluee", "signal_critique": True,
            "seuil_pourcentage": 0.3,
            "lignes": [{
                "materiau": "materiau-qa-fictif", "unite": "u", "quantite_prevue": "100",
                "quantite_reelle": "133.335", "ecart_pourcentage": "0.33335", "critique": True,
            }],
        }),
        mesures_chantier.fait_rentabilite({
            "wct_id": wct_id, "devis_id": devis_id, "sequence": 1, "verdict": "CALCULEE",
            "cout_reel_complet": True, "prix_definitif": True, "marge_reelle_cad": "266.66", "manque": [],
        }),
    ]
    return wct_id, faits


def _outils_qa(monkeypatch):
    monkeypatch.setattr(m8_outils, "_seuils_entonnoir", lambda: {
        "m8_taux_acceptation_pct": {"sens": "au_dessus", "valeur": 66.67},
        "m8_delai_lead_acceptation_jours": {"sens": "au_dessus", "valeur": 1.24},
        "m8_devis_sans_reponse": {"sens": "au_dessus", "valeur": 1},
        "m8_carnet_signe_cad": {"sens": "au_dessous", "valeur": 1000.01},
    })
    monkeypatch.setattr(m8_outils, "_seuils_alerte", lambda: {
        "m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 33.33},
        "m8_ecart_marge_pct": {"sens": "au_dessous", "valeur": -33.34},
        "m8_ecart_materiaux_max_pct": {"sens": "au_dessus", "valeur": 33.34},
    })
    wct_id, faits_chantier = _faits_chantier()
    faits_entonnoir = _faits_entonnoir()
    instruments = {
        outil.nom: outil for outil in m8_outils.outils(
            RegistreSnapshots(), [], faits_chantier, faits_entonnoir, faits_cash_libre_cible=[],
        )
    }
    return wct_id, instruments


def test_reponse_de_l_outil_vue_executive_expose_la_base_et_l_evaluation_non_arrondie(monkeypatch):
    _, instruments = _outils_qa(monkeypatch)
    reponse = executer(instruments["m8_lire_vue_executive"], {})

    assert reponse["ok"] is True
    evalues = {e["metric_id"]: e for e in reponse["resultat"]["entonnoir"]["seuils"]["evalues"]}
    assert evalues["m8_taux_acceptation_pct"]["base_taux_acceptation"] == {
        "n_acceptes_parmi_envoyes": 2, "n_envoyes": 3,
    }
    assert evalues["m8_taux_acceptation_pct"]["valeur"] == "66.67"
    assert evalues["m8_taux_acceptation_pct"]["seuil"] == "66.67"
    assert evalues["m8_taux_acceptation_pct"]["statut"] == "non_franchi"
    assert evalues["m8_delai_lead_acceptation_jours"]["comparaison_non_arrondie"] is True
    assert evalues["m8_delai_lead_acceptation_jours"]["valeur"] == "1.24"
    assert evalues["m8_delai_lead_acceptation_jours"]["seuil"] == "1.24"
    assert evalues["m8_delai_lead_acceptation_jours"]["statut"] == "non_franchi"


def test_reponse_de_l_outil_mesures_chantier_expose_les_trois_ratios_non_arrondis(monkeypatch):
    wct_id, instruments = _outils_qa(monkeypatch)
    reponse = executer(instruments["m8_lire_mesures_chantier"], {"wct_id": wct_id})

    assert reponse["ok"] is True
    evalues = {e["metric_id"]: e for e in reponse["resultat"]["seuils"]}
    assert evalues["m8_ecart_duree_pct"]["valeur"] == "33.33"
    assert evalues["m8_ecart_duree_pct"]["seuil"] == "33.33"
    assert evalues["m8_ecart_duree_pct"]["statut"] == "franchi"
    assert evalues["m8_ecart_duree_pct"]["comparaison_non_arrondie"] is True
    assert evalues["m8_ecart_marge_pct"]["valeur"] == "-33.34"
    assert evalues["m8_ecart_marge_pct"]["seuil"] == "-33.34"
    assert evalues["m8_ecart_marge_pct"]["statut"] == "non_franchi"
    assert evalues["m8_ecart_marge_pct"]["comparaison_non_arrondie"] is True
    assert evalues["m8_ecart_materiaux_max_pct"]["valeur"] == "33.34"
    assert evalues["m8_ecart_materiaux_max_pct"]["seuil"] == "33.34"
    assert evalues["m8_ecart_materiaux_max_pct"]["statut"] == "non_franchi"
    assert evalues["m8_ecart_materiaux_max_pct"]["comparaison_non_arrondie"] is True


def test_reponse_publique_compare_le_carnet_avec_la_somme_exacte_des_prix(monkeypatch):
    monkeypatch.setattr(m8_outils, "_seuils_entonnoir", lambda: {
        "m8_carnet_signe_cad": {"sens": "au_dessous", "valeur": 10000000000000},
    })
    faits = [
        entonnoir.fait_devis_accepte({
            "devis_id": "qa-devis-carnet-grand", "lead_id": "qa-lead-carnet",
            "prix_total": "10000000000000", "horodatage_acceptation": "2026-01-01T00:00:00Z",
        }),
        entonnoir.fait_devis_accepte({
            "devis_id": "qa-devis-carnet-petit", "lead_id": "qa-lead-carnet",
            "prix_total": "0.000000000000001", "horodatage_acceptation": "2026-01-01T00:00:01Z",
        }),
    ]
    instruments = {
        outil.nom: outil for outil in m8_outils.outils(
            RegistreSnapshots(), [], [], faits, faits_cash_libre_cible=[],
        )
    }

    reponse = executer(instruments["m8_lire_vue_executive"], {})

    assert reponse["ok"] is True
    valeur = next(
        m for m in reponse["resultat"]["entonnoir"]["mesures"]
        if m["metric_id"] == "m8_carnet_signe_cad"
    )
    evaluation = next(
        e for e in reponse["resultat"]["entonnoir"]["seuils"]["evalues"]
        if e["metric_id"] == "m8_carnet_signe_cad"
    )
    assert valeur["valeur"] == "10000000000000.00"
    assert evaluation["seuil"] == "10000000000000.00"
    assert evaluation["statut"] == "non_franchi"


def test_reponse_publique_arrondit_le_carnet_depuis_la_somme_fractionnaire_exacte(monkeypatch):
    monkeypatch.setattr(m8_outils, "_seuils_entonnoir", lambda: {
        "m8_carnet_signe_cad": {"sens": "au_dessous", "valeur": 10000000000000},
    })
    faits = [
        entonnoir.fait_devis_accepte({
            "devis_id": "qa-devis-carnet-demi-cent-grand", "lead_id": "qa-lead-carnet-demi-cent",
            "prix_total": "10000000000000", "horodatage_acceptation": "2026-01-01T00:00:00Z",
        }),
        entonnoir.fait_devis_accepte({
            "devis_id": "qa-devis-carnet-demi-cent-petit", "lead_id": "qa-lead-carnet-demi-cent",
            "prix_total": "0.00499999999999999999999999999999",
            "horodatage_acceptation": "2026-01-01T00:00:01Z",
        }),
    ]
    instruments = {
        outil.nom: outil for outil in m8_outils.outils(
            RegistreSnapshots(), [], [], faits, faits_cash_libre_cible=[],
        )
    }

    reponse = executer(instruments["m8_lire_vue_executive"], {})
    valeur = next(
        m for m in reponse["resultat"]["entonnoir"]["mesures"]
        if m["metric_id"] == "m8_carnet_signe_cad"
    )
    evaluation = next(
        e for e in reponse["resultat"]["entonnoir"]["seuils"]["evalues"]
        if e["metric_id"] == "m8_carnet_signe_cad"
    )

    assert reponse["ok"] is True
    assert valeur["valeur"] == "10000000000000.00"
    assert evaluation["valeur"] == "10000000000000.00"
    assert evaluation["seuil"] == "10000000000000.00"
    assert evaluation["statut"] == "non_franchi"
    assert evaluation["comparaison_non_arrondie"] is True


def test_reponse_publique_compare_lecart_de_marge_avec_le_devis_exact(monkeypatch):
    monkeypatch.setattr(m8_outils, "_seuils_alerte", lambda: {
        "m8_ecart_marge_pct": {"sens": "au_dessus", "valeur": 0},
    })
    wct_id, devis_id = "qa-wct-marge-exacte", "qa-devis-marge-exacte"
    montant_exact = "1.12345678901234567890123456789012345"
    faits = [
        mesures_chantier.fait_wct({
            "wct_id": wct_id, "intervention_id": "qa-intervention-marge-exacte", "devis_id": devis_id,
            "technicien_id": "qa-technicien-fictif", "horodatage_completion": "2026-02-01T12:00:00Z",
            "duree_reelle_minutes": 100, "statut": "completed_verified",
        }),
        mesures_chantier.fait_devis({
            "devis_id": devis_id, "prix_total": montant_exact, "cout_total": "0",
            "duree_estimee_minutes": "100", "horodatage_acceptation": "2026-01-20T12:00:00Z",
        }),
        mesures_chantier.fait_rentabilite({
            "wct_id": wct_id, "devis_id": devis_id, "sequence": 1, "verdict": "CALCULEE",
            "cout_reel_complet": True, "prix_definitif": True, "marge_reelle_cad": montant_exact, "manque": [],
        }),
    ]
    instruments = {
        outil.nom: outil for outil in m8_outils.outils(
            RegistreSnapshots(), [], faits, [], faits_cash_libre_cible=[],
        )
    }

    reponse = executer(instruments["m8_lire_mesures_chantier"], {"wct_id": wct_id})

    assert reponse["ok"] is True
    evaluation = next(
        e for e in reponse["resultat"]["seuils"] if e["metric_id"] == "m8_ecart_marge_pct"
    )
    assert evaluation["valeur"] == "0.00"
    assert evaluation["seuil"] == "0.00"
    assert evaluation["statut"] == "franchi"
    assert "comparaison_non_arrondie" not in evaluation


def test_reponse_publique_arrondit_le_ratio_de_marge_depuis_la_fraction_exacte(monkeypatch):
    monkeypatch.setattr(m8_outils, "_seuils_alerte", lambda: {
        "m8_ecart_marge_pct": {"sens": "au_dessus", "valeur": 0},
    })
    wct_id, devis_id = "qa-wct-arrondi-exact", "qa-devis-arrondi-exact"
    prix = "1"
    marge = "1.000049999999999999999999999999999"
    faits = [
        mesures_chantier.fait_wct({
            "wct_id": wct_id, "intervention_id": "qa-intervention-arrondi-exact", "devis_id": devis_id,
            "technicien_id": "qa-technicien-fictif", "horodatage_completion": "2026-02-01T12:00:00Z",
            "duree_reelle_minutes": 100, "statut": "completed_verified",
        }),
        mesures_chantier.fait_devis({
            "devis_id": devis_id, "prix_total": prix, "cout_total": "0",
            "duree_estimee_minutes": "100", "horodatage_acceptation": "2026-01-20T12:00:00Z",
        }),
        mesures_chantier.fait_rentabilite({
            "wct_id": wct_id, "devis_id": devis_id, "sequence": 1, "verdict": "CALCULEE",
            "cout_reel_complet": True, "prix_definitif": True, "marge_reelle_cad": marge, "manque": [],
        }),
    ]
    instruments = {
        outil.nom: outil for outil in m8_outils.outils(
            RegistreSnapshots(), [], faits, [], faits_cash_libre_cible=[],
        )
    }

    reponse = executer(instruments["m8_lire_mesures_chantier"], {"wct_id": wct_id})

    assert reponse["ok"] is True
    evaluation = next(
        e for e in reponse["resultat"]["seuils"] if e["metric_id"] == "m8_ecart_marge_pct"
    )
    assert evaluation["valeur"] == "0.00"
    assert evaluation["seuil"] == "0.00"
    assert evaluation["statut"] == "franchi"
    assert evaluation["comparaison_non_arrondie"] is True


def test_reponse_publique_arrondit_le_ratio_de_duree_depuis_la_fraction_exacte(monkeypatch):
    monkeypatch.setattr(m8_outils, "_seuils_alerte", lambda: {
        "m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 0.005},
    })
    wct_id, devis_id = "qa-wct-arrondi-duree", "qa-devis-arrondi-duree"
    duree_estimee = "0.9999500024998750062496875156242187891605369734013174347532310900079214828419116017600437412882586961"
    faits = [
        mesures_chantier.fait_wct({
            "wct_id": wct_id, "intervention_id": "qa-intervention-arrondi-duree", "devis_id": devis_id,
            "technicien_id": "qa-technicien-fictif", "horodatage_completion": "2026-02-01T12:00:00Z",
            "duree_reelle_minutes": 1, "statut": "completed_verified",
        }),
        mesures_chantier.fait_devis({
            "devis_id": devis_id, "prix_total": "1", "cout_total": "0",
            "duree_estimee_minutes": duree_estimee, "horodatage_acceptation": "2026-01-20T12:00:00Z",
        }),
        mesures_chantier.fait_rentabilite({
            "wct_id": wct_id, "devis_id": devis_id, "sequence": 1, "verdict": "CALCULEE",
            "cout_reel_complet": True, "prix_definitif": True, "marge_reelle_cad": "1", "manque": [],
        }),
    ]
    instruments = {
        outil.nom: outil for outil in m8_outils.outils(
            RegistreSnapshots(), [], faits, [], faits_cash_libre_cible=[],
        )
    }

    reponse = executer(instruments["m8_lire_mesures_chantier"], {"wct_id": wct_id})

    assert reponse["ok"] is True
    evaluation = next(
        e for e in reponse["resultat"]["seuils"] if e["metric_id"] == "m8_ecart_duree_pct"
    )
    assert evaluation["valeur"] == "0.00"
    assert evaluation["seuil"] == "0.005"
    assert evaluation["statut"] == "non_franchi"
    assert evaluation["comparaison_non_arrondie"] is True


def test_performance_equipe_arrondit_le_ratio_depuis_la_fraction_exacte():
    wct_id, devis_id = "qa-wct-equipe-exact", "qa-devis-equipe-exact"
    faits = [
        mesures_chantier.fait_wct({
            "wct_id": wct_id, "intervention_id": "qa-intervention-equipe-exact", "devis_id": devis_id,
            "technicien_id": "qa-technicien-equipe-exact", "horodatage_completion": "2026-02-01T12:00:00Z",
            "duree_reelle_minutes": 1, "statut": "completed_verified",
        }),
        mesures_chantier.fait_devis({
            "devis_id": devis_id, "prix_total": "1", "cout_total": "0",
            "duree_estimee_minutes": (
                "0.9999500024998750062496875156242187891605369734013174347532310900079214828419116017600437412882586961"
            ), "horodatage_acceptation": "2026-01-20T12:00:00Z",
        }),
    ]
    outils = {
        outil.nom: outil for outil in m8_outils.outils(RegistreSnapshots(), [], faits)
    }

    reponse = executer(outils["m8_performance_equipe"], {})

    assert reponse["ok"] is True
    assert reponse["resultat"]["equipe"]["duree_estimee_totale_minutes"] == "1.00"
    # L'écart exact est strictement inférieur à 0,005 % ; le rendu ROUND_HALF_UP reste donc 0,00.
    assert reponse["resultat"]["equipe"]["ecart_pct"] == "0.00"


@pytest.mark.parametrize(
    "valeur_yaml",
    ["66.6666666666666666", "6.66666666666666666e+1", "6_6.6666666666666666", "1:06.6666666666666666"],
)
def test_configuration_yaml_conserve_le_seuil_decimal_jusqu_a_la_reponse_publique(
    monkeypatch, tmp_path, valeur_yaml,
):
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(
        "configuration:\n"
        "  seuils_entonnoir:\n"
        "    m8_taux_acceptation_pct:\n"
        "      sens: au_dessus\n"
        f"      valeur: {valeur_yaml}\n"
        "  autre_nombre: 1.25\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(m8_outils, "_MANIFESTE", manifeste)

    configuration = m8_outils._configuration()
    seuil = configuration["seuils_entonnoir"]["m8_taux_acceptation_pct"]["valeur"]
    assert seuil == Decimal("66.6666666666666666")
    assert type(configuration["autre_nombre"]) is float
    instruments = {
        outil.nom: outil for outil in m8_outils.outils(
            RegistreSnapshots(), [], [], _faits_entonnoir(), faits_cash_libre_cible=[],
        )
    }

    reponse = executer(instruments["m8_lire_vue_executive"], {})
    evaluation = next(
        e for e in reponse["resultat"]["entonnoir"]["seuils"]["evalues"]
        if e["metric_id"] == "m8_taux_acceptation_pct"
    )
    assert reponse["ok"] is True
    assert evaluation["valeur"] == "66.67"
    assert evaluation["seuil"] == "66.6666666666666666"
    assert evaluation["statut"] == "franchi"


@pytest.mark.parametrize("valeur_yaml", [".nan", ".inf", "-.inf"])
def test_configuration_yaml_nan_et_inf_restent_des_seuils_invalides(monkeypatch, tmp_path, valeur_yaml):
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(
        "configuration:\n"
        "  seuils_entonnoir:\n"
        "    m8_taux_acceptation_pct:\n"
        "      sens: au_dessus\n"
        f"      valeur: {valeur_yaml}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(m8_outils, "_MANIFESTE", manifeste)
    instruments = {
        outil.nom: outil for outil in m8_outils.outils(
            RegistreSnapshots(), [], [], _faits_entonnoir(), faits_cash_libre_cible=[],
        )
    }

    reponse = executer(instruments["m8_lire_vue_executive"], {})
    assert reponse["ok"] is True
    assert "m8_taux_acceptation_pct" in reponse["resultat"]["entonnoir"]["seuils"]["invalides"]
    assert all(
        e["metric_id"] != "m8_taux_acceptation_pct"
        for e in reponse["resultat"]["entonnoir"]["seuils"]["evalues"]
    )


def test_seuil_yaml_decimal_long_produit_une_charge_compatible_avec_le_schema(monkeypatch, tmp_path):
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(
        "configuration:\n"
        "  seuils_alerte:\n"
        "    m8_ecart_duree_pct:\n"
        "      sens: au_dessus\n"
        "      valeur: 33.3333333333333333333333\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(m8_outils, "_MANIFESTE", manifeste)
    wct_id, faits = _faits_chantier()

    situation = m8_outils._situation_chantier(wct_id, faits)
    charge = next(c for c in situation["charges"] if c["type_alerte"] == "MESURE-SEUIL-FRANCHI")

    assert charge["preuve"]["seuil"] == "33.3333333333333333333333"
    assert catalogue.erreurs_charge("m8.alerte_proposee", charge) == []


def test_reponse_publique_arrondit_les_ecarts_cad_et_minutes_depuis_les_fractions_exactes():
    wct_id, devis_id = "qa-wct-cent-exact", "qa-devis-cent-exact"
    cout_et_duree = "0.99500000000000000000000000000001"
    faits = [
        mesures_chantier.fait_wct({
            "wct_id": wct_id, "intervention_id": "qa-int-cent-exact", "devis_id": devis_id,
            "technicien_id": "qa-technicien-fictif", "horodatage_completion": "2026-02-01T12:00:00Z",
            "duree_reelle_minutes": 1, "statut": "completed_verified",
        }),
        mesures_chantier.fait_devis({
            "devis_id": devis_id, "prix_total": "1", "cout_total": cout_et_duree,
            "duree_estimee_minutes": cout_et_duree, "horodatage_acceptation": "2026-01-20T12:00:00Z",
        }),
        mesures_chantier.fait_rentabilite({
            "wct_id": wct_id, "devis_id": devis_id, "sequence": 1, "verdict": "CALCULEE",
            "cout_reel_complet": True, "prix_definitif": True, "marge_reelle_cad": "0", "manque": [],
        }),
    ]
    instruments = {
        outil.nom: outil for outil in m8_outils.outils(
            RegistreSnapshots(), [], faits, [], faits_cash_libre_cible=[],
        )
    }

    reponse = executer(instruments["m8_lire_mesures_chantier"], {"wct_id": wct_id})
    mesures = {m["metric_id"]: m for m in reponse["resultat"]["mesures"]}

    assert reponse["ok"] is True
    assert mesures["m8_ecart_duree_minutes"]["valeur"] == "0.00"
    assert mesures["m8_marge_prevue_cad"]["valeur"] == "0.00"
    assert mesures["m8_ecart_marge_cad"]["valeur"] == "0.00"


def test_reponse_publique_garde_round_half_up_au_demi_cent_negatif_et_positif():
    wct_id, devis_id = "qa-wct-demi-cent", "qa-devis-demi-cent"
    faits = [
        mesures_chantier.fait_wct({
            "wct_id": wct_id, "intervention_id": "qa-int-demi-cent", "devis_id": devis_id,
            "technicien_id": "qa-technicien-fictif", "horodatage_completion": "2026-02-01T12:00:00Z",
            "duree_reelle_minutes": 1, "statut": "completed_verified",
        }),
        mesures_chantier.fait_devis({
            "devis_id": devis_id, "prix_total": "1", "cout_total": "0.995",
            "duree_estimee_minutes": "0.995", "horodatage_acceptation": "2026-01-20T12:00:00Z",
        }),
        mesures_chantier.fait_rentabilite({
            "wct_id": wct_id, "devis_id": devis_id, "sequence": 1, "verdict": "CALCULEE",
            "cout_reel_complet": True, "prix_definitif": True, "marge_reelle_cad": "0", "manque": [],
        }),
    ]
    instruments = {
        outil.nom: outil for outil in m8_outils.outils(
            RegistreSnapshots(), [], faits, [], faits_cash_libre_cible=[],
        )
    }

    reponse = executer(instruments["m8_lire_mesures_chantier"], {"wct_id": wct_id})
    mesures = {m["metric_id"]: m for m in reponse["resultat"]["mesures"]}

    assert reponse["ok"] is True
    assert mesures["m8_ecart_duree_minutes"]["valeur"] == "0.01"
    assert mesures["m8_marge_prevue_cad"]["valeur"] == "0.01"
    assert mesures["m8_ecart_marge_cad"]["valeur"] == "-0.01"


def test_reponse_publique_charge_planifiee_utilise_les_heures_m4_avant_arrondi_affiche():
    charge = {
        "evenement_id": "m4-capacite-qa-fractionnaire",
        "semaine_debut": "2026-02-23",
        "portee": "journees_datees_seulement",
        "calculable": True,
        "heures_disponibles": "3.0000",
        "heures_planifiees": "0.0167",
        "manque": [],
        "constate_le": "2026-02-27T12:00:00Z",
        "version_donnees": "a" * 16,
    }
    assert catalogue.erreurs_charge("m4.capacite_equipe_constatee", charge) == []
    fait = operations_recues.fait(
        operations_recues.TYPE_CAPACITE, charge, "2026-02-27T12:00:01Z",
    )
    instruments = {
        outil.nom: outil for outil in m8_outils.outils(
            RegistreSnapshots(), [], faits_cible=[], faits_entonnoir_cible=[], faits_contenus_cible=[],
            faits_cash_libre_cible=[], faits_operations_cible=[fait],
        )
    }

    reponse = executer(instruments["m8_lire_mesures"], {
        "maintenant": "2026-02-28T12:00:00Z",
        "metric_ids": ["m8_charge_planifiee_pct", "m8_capacite_heures_disponibles", "m8_capacite_heures_planifiees"],
    })
    mesures = {m["metric_id"]: m for m in reponse["resultat"]["mesures"]}

    assert reponse["ok"] is True
    assert mesures["m8_capacite_heures_disponibles"]["valeur"] == "3.00"
    assert mesures["m8_capacite_heures_planifiees"]["valeur"] == "0.02"
    assert mesures["m8_charge_planifiee_pct"]["valeur"] == "0.56"
