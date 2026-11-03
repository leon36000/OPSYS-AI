"""Tests tueurs de mutants pour ``synthese.py`` : ce que la couverture existante laissait passer.

Chaque cas vise un comportement OBSERVABLE du module (comptage des chantiers, écart d'équipe, variance de matériaux,
fraîcheur d'un constat, motif d'un cash libre non calculable), avec des faits fictifs et déterministes.
"""

from __future__ import annotations

import pytest
from m8_analytics import synthese

_DEFINITIONS = synthese.charger_definitions()


def _definition(metric_id: str) -> dict[str, dict[str, str]]:
    return {metric_id: _DEFINITIONS[metric_id]}


def _wct(wct_id: str, **surcharges) -> dict:
    base = {
        "type_entree": "wct",
        "wct_id": wct_id,
        "intervention_id": f"int-{wct_id}",
        "devis_id": f"devis-{wct_id}",
        "technicien_id": "tech-fictif",
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "duree_reelle_minutes": 120,
        "statut": "completed_verified",
    }
    base.update(surcharges)
    return base


def _devis(wct_id: str, duree_estimee: str) -> dict:
    return {
        "type_entree": "devis",
        "devis_id": f"devis-{wct_id}",
        "duree_estimee_minutes": duree_estimee,
        "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
    }


def _variance(wct_id: str, critique: bool, statut: str = "evaluee") -> dict:
    return {
        "type_entree": "variance",
        "wct_id": wct_id,
        "statut_variance": statut,
        "signal_critique": critique,
        "seuil_pourcentage": 0.3,
        "lignes": [],
    }


def _mesure(metric_id: str, faits_chantier: list[dict], faits_cash: list[dict] | None = None) -> dict:
    return synthese.mesurer(faits_chantier, faits_cash or [], _definition(metric_id), "America/Toronto")[0]


# ================================================================ plus récent achèvement
def test_le_dernier_achevement_est_choisi_par_INSTANT_pas_par_ordre_alphabetique():
    """Deux textes ISO de fuseaux différents : l'ordre des textes n'est pas l'ordre des instants."""
    faits = [
        _wct("wct-a", horodatage_completion="2026-01-02T00:00:00+00:00"),  # 00 h UTC
        _wct("wct-b", horodatage_completion="2026-01-01T23:00:00-05:00"),  # 04 h UTC, plus tard
    ]

    mesure = _mesure("m8_chantiers_termines", faits)

    assert mesure["statut"] == "calculee"
    assert mesure["dernier_fait_le"] == "2026-01-01T23:00:00-05:00"


def test_sans_aucun_chantier_termine_la_mesure_est_non_calculable_pas_zero():
    mesure = _mesure("m8_chantiers_termines", [])

    assert mesure["statut"] == "non_calculable"
    assert mesure["valeur"] is None
    assert mesure["manque"][0]["champ"] == "m4.travaux_termines"


# ================================================================ écart de durée d'équipe
def test_un_seul_chantier_mesure_suffit_a_calculer_l_ecart_d_equipe():
    """``n_chantiers_mesures == 1`` n'est pas le cas « aucun chantier mesuré »."""
    faits = [_wct("wct-a", duree_reelle_minutes=120), _devis("wct-a", "100")]

    mesure = _mesure("m8_ecart_duree_equipe_pct", faits)

    assert mesure["statut"] == "calculee"
    assert mesure["entrees"]["n_chantiers_mesures"] == 1
    assert mesure["valeur"] is not None


def test_sans_aucun_chantier_termine_l_ecart_d_equipe_est_non_calculable():
    mesure = _mesure("m8_ecart_duree_equipe_pct", [])

    assert mesure["statut"] == "non_calculable"
    assert mesure["manque"][0]["champ"] == "m4.travaux_termines"


# ================================================================ variance de matériaux
def test_les_variance_evaluees_sont_comptees_une_par_une_et_seules_les_critiques_levent_le_compteur():
    faits = [
        _wct("wct-a"),
        _variance("wct-a", critique=True),
        _wct("wct-b"),
        _variance("wct-b", critique=False),
        _wct("wct-c"),
        _variance("wct-c", critique=False),
    ]

    mesure = _mesure("m8_chantiers_signal_materiaux", faits)

    assert mesure["statut"] == "calculee"
    assert mesure["valeur"] == "1"
    assert mesure["entrees"] == {
        "n_chantiers_termines": 3,
        "n_variances_evaluees": 3,
        "n_chantiers_sans_variance_evaluee": 0,
    }


def test_une_variance_non_evaluee_ne_compte_pas_dans_les_variances_evaluees():
    faits = [_wct("wct-a"), _variance("wct-a", critique=True, statut="en_attente"), _wct("wct-b")]

    mesure = _mesure("m8_chantiers_signal_materiaux", faits)

    assert mesure["statut"] == "non_calculable"
    assert mesure["entrees"]["n_chantiers_termines"] == 2
    assert mesure["manque"][0]["champ"] == "m6.variance_chantier"


def test_les_chantiers_sans_variance_evaluee_sont_comptes_a_part():
    faits = [_wct("wct-a"), _variance("wct-a", critique=True), _wct("wct-b")]

    mesure = _mesure("m8_chantiers_signal_materiaux", faits)

    assert mesure["entrees"]["n_chantiers_sans_variance_evaluee"] == 1


# ================================================================ cash libre de M5
def _constat(**surcharges) -> dict:
    base = {
        "type_entree": "cash_libre_constate",
        "evenement_id": "evt-cash-fictif-1",
        "sequence": 1,
        "date_reference": "2026-11-12",
        "statut": "CALCULE",
        "cash_libre_cad": "1234.56",
        "en_deficit": False,
    }
    base.update(surcharges)
    return base


def test_un_constat_non_calcule_avec_un_montant_reste_non_calculable():
    """Un statut autre que CALCULE bloque, même si un montant traîne dans le fait (jamais montré)."""
    mesure = _mesure("m8_cash_libre_cad", [], [_constat(statut="NON_CALCULABLE")])

    assert mesure["statut"] == "non_calculable"
    assert mesure["valeur"] is None
    assert mesure["manque"][0]["champ"] == "cash_libre"


def test_un_cash_libre_non_calculable_nomme_les_composantes_qui_manquent():
    constat = _constat(
        statut="NON_CALCULABLE",
        cash_libre_cad=None,
        manque=[
            {"composante": "comptes_a_payer", "code": "M5-COMPOSANTE-ABSENTE"},
            {"composante": "taxes_a_remettre", "code": "M5-COMPOSANTE-ABSENTE"},
        ],
    )

    mesure = _mesure("m8_cash_libre_cad", [], [constat])

    assert mesure["statut"] == "non_calculable"
    assert "comptes_a_payer : M5-COMPOSANTE-ABSENTE" in mesure["manque"][0]["raison"]
    assert "taxes_a_remettre : M5-COMPOSANTE-ABSENTE" in mesure["manque"][0]["raison"]


@pytest.mark.parametrize("montant", ["0.00", "1234.56"])
def test_un_constat_calcule_rend_le_montant_tel_quel_et_donne_minuit_local(montant):
    mesure = _mesure("m8_cash_libre_cad", [], [_constat(cash_libre_cad=montant)])

    assert mesure["statut"] == "calculee"
    assert mesure["valeur"] == montant
    assert mesure["dernier_fait_le"] == "2026-11-12T00:00:00-05:00"
