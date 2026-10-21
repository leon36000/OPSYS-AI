"""Régressions audit : unités confirmées et tarifs à la date du WCT ; données fictives."""

from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import cout_reel

FICTIF = True


def _pieces():
    wct = {
        "wct_id": "WCT-fictif", "intervention_id": "INT-fictif", "devis_id": "DEVIS-fictif",
        "horodatage_completion": "2026-09-15T15:00:00+00:00", "duree_reelle_minutes": 180,
    }
    signal = {
        "wct_id": "WCT-fictif", "chantier_id": "CH-fictif", "statut_variance": "evaluee",
        "signal_critique": False, "horodatage_completion": wct["horodatage_completion"],
        "lignes": [{"materiau": "alu-fictif", "unite": "pi", "quantite_reelle": "42"}],
    }
    prix = {
        "materiau_id": "alu-fictif", "fournisseur_id": "fournisseur-fictif", "prix_unitaire": 8,
        "devise": "CAD", "date_effet": "2026-09-01", "source_document": None, "unite": "pi",
    }
    return wct, signal, prix


def _calcul(wct, signal, livre):
    # L'interpréteur partagé ne doit pas charger l'ancienne installation éditable d'un autre checkout.
    assert Path(cout_reel.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1] / "src")
    return cout_reel.calculer_cout_reel(wct, signal, livre, "50.00")


@pytest.mark.parametrize("unite", [None, "", "   ", "rouleau", 123])
def test_unite_du_tarif_absente_ou_differente_interdit_un_cout_complet(unite):
    wct, signal, prix = _pieces()
    if unite is None:
        del prix["unite"]
    else:
        prix["unite"] = unite

    resultat = _calcul(wct, signal, [prix])

    assert resultat["complet"] is False, "unité du tarif inconnue/incompatible mais coût déclaré complet"
    assert resultat["cout_total"] is None
    assert resultat["cout_total_connu"] == Decimal("150.00")
    assert "unité" in resultat["manque"][0]["detail"]


def test_tarif_futur_ne_reecrit_pas_la_valorisation_du_wct_passe():
    wct, signal, prix = _pieces()
    avant = _calcul(wct, signal, [prix])
    apres = _calcul(wct, signal, [prix, {**prix, "prix_unitaire": 80, "date_effet": "2027-01-01"}])

    assert avant["complet"] is True and avant["cout_total"] == Decimal("486.00")
    assert apres["cout_total"] == avant["cout_total"], "le tarif futur remplace silencieusement le coût historique"
    assert apres["entrees"] == avant["entrees"]


def test_tarif_futur_seul_ne_permet_pas_de_chiffrer_le_passe():
    wct, signal, prix = _pieces()
    resultat = _calcul(wct, signal, [{**prix, "date_effet": "2027-01-01"}])

    assert resultat["complet"] is False
    assert resultat["cout_total"] is None


@pytest.mark.parametrize("date_effet", [None, "", "hier", "2026-02-30", "2026-09-01T00:00:00Z"])
def test_tarif_sans_date_civile_valide_ne_certifie_pas_le_cout(date_effet):
    wct, signal, prix = _pieces()
    resultat = _calcul(wct, signal, [{**prix, "date_effet": date_effet}])

    assert resultat["complet"] is False
    assert resultat["cout_total"] is None


@pytest.mark.parametrize("completion", [None, "", "hier", "2026-09-15", "2026-09-15T15:00:00"])
def test_wct_sans_horodatage_date_et_zone_ne_certifie_pas_les_materiaux(completion):
    wct, signal, prix = _pieces()
    resultat = _calcul({**wct, "horodatage_completion": completion}, signal, [prix])

    assert resultat["complet"] is False
    assert resultat["cout_total"] is None


def test_tarif_du_jour_et_revisions_eligibles_gardent_la_precedence_append_only():
    wct, signal, prix = _pieces()
    livre = [prix, {**prix, "prix_unitaire": 9, "date_effet": "2026-09-15"},
             {**prix, "prix_unitaire": 10, "date_effet": "2026-09-05"}]

    resultat = _calcul(wct, signal, livre)

    assert resultat["complet"] is True
    assert resultat["cout_total"] == Decimal("570.00")  # dernière révision éligible : 42 * 10 + 150


def test_le_tarif_futur_devient_utilisable_pour_un_wct_apres_sa_date_effet():
    wct, signal, prix = _pieces()
    wct["horodatage_completion"] = "2027-01-01T15:00:00+00:00"
    resultat = _calcul(wct, signal, [prix, {**prix, "prix_unitaire": 80, "date_effet": "2027-01-01"}])

    assert resultat["complet"] is True
    assert resultat["cout_total"] == Decimal("3510.00")


def test_un_fournisseur_sans_unite_ne_disparait_pas_derriere_un_tarif_utilisable():
    wct, signal, prix = _pieces()
    inconnu = {**prix, "fournisseur_id": "autre-fictif", "unite": None}
    resultat = _calcul(wct, signal, [prix, inconnu])

    assert resultat["complet"] is False
    assert resultat["cout_total"] is None
