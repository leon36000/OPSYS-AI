"""`m7_lister_demandes_avis` (PLAN T1.5-d) : ce que le propriétaire relit avant d'écrire à un client.

Lecture seule du registre durable `demandes_avis`, alimenté par le consommateur `m4.travaux_termines`
(`tests/test_evenements_travaux_termines.py`). Ces tests passent par le VRAI outil du VRAI manifeste,
appelé comme en production (`executer_atomique`), sur une base SQLite temporaire migrée. Données fictives.
"""

from __future__ import annotations

import json

import pytest
from m7_marketing.outils import consommateurs, outils

from opsys import jetons, stockage
from opsys.outils import executer_atomique

FICTIF = True
PREUVE = {
    "consentement_recueilli_par": "etienne",
    "consentement_recueilli_le": "2026-09-28T18:05:00+00:00",
    "consentement_version_texte": "consentement-client-fr-CA-v1",
}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def lister():
    par_nom = {o.nom: o for o in outils()}

    def _lister(**arguments):
        return executer_atomique(par_nom["m7_lister_demandes_avis"], arguments)

    return _lister


def _recevoir(wct_id: str, **overrides) -> dict:
    charge = {
        "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "lead_id": f"lead-{wct_id}",
        "technicien_id": "etienne", "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5}, "duree_reelle_minutes": 180,
        "ecart_signale": False, "revue_id": None, "hash_maillon": "deadbeef",
        "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"], "devis_id": f"devis-{wct_id}",
        "statut": "completed_pending_review", "type_travaux": "renovation_totale",
        "consentement_demande_avis": True, **PREUVE,
    }
    charge.update(overrides)
    with stockage.transaction():
        return consommateurs()["m4.travaux_termines"](charge)


def test_sans_brouillon_la_liste_est_vide(base_durable, lister):
    reponse = lister()
    assert reponse["ok"] is True
    assert reponse["resultat"] == {"total": 0, "demandes": [], "reste": 0}


def test_le_brouillon_se_lit_avec_son_texte_et_la_preuve_du_consentement(base_durable, lister):
    assert _recevoir("wct-1")["brouillon_cree"] is True

    (ligne,) = lister()["resultat"]["demandes"]

    assert ligne["wct_id"] == "wct-1" and ligne["approval_status"] == "PROPOSE"
    assert "(renovation totale)" in ligne["texte"]
    assert ligne["consentement"] == {
        "recueilli_par": "etienne", "recueilli_le": "2026-09-28T18:05:00+00:00",
        "version_texte": "consentement-client-fr-CA-v1",
    }
    assert "lead_id" not in ligne and "intervention_id" not in ligne  # ce qui reste au registre


def test_sans_consentement_rien_n_est_liste(base_durable, lister):
    _recevoir("wct-sans", consentement_demande_avis=False)
    _recevoir("wct-absent", **{"consentement_demande_avis": None})

    assert lister()["resultat"] == {"total": 0, "demandes": [], "reste": 0}


def test_les_plus_recents_d_abord_et_la_limite_dit_ce_qui_reste(base_durable, lister):
    for numero in range(1, 5):
        assert _recevoir(f"wct-{numero}")["brouillon_cree"] is True

    resultat = lister(limite=2)["resultat"]

    assert [d["wct_id"] for d in resultat["demandes"]] == ["wct-4", "wct-3"]
    assert (resultat["total"], resultat["reste"]) == (4, 2)


def test_la_limite_par_defaut_est_bornee(base_durable, lister):
    for numero in range(1, 9):
        _recevoir(f"wct-{numero}")

    resultat = lister()["resultat"]

    assert len(resultat["demandes"]) == 5 and resultat["reste"] == 3


@pytest.mark.parametrize("limite", [0, -1, 9, True, "5", 2.5])
def test_une_limite_hors_bornes_est_refusee(base_durable, lister, limite):
    reponse = lister(limite=limite)

    assert reponse["ok"] is False, reponse


def test_la_reponse_la_plus_longue_tient_sous_la_limite_de_capacites(base_durable, lister):
    """Huit brouillons de gabarit, nature et ville comprises : `Capacites` tronque au-delà de sa limite de sortie,
    et un aperçu tronqué n'est plus une réponse que le téléphone peut lire."""
    for numero in range(1, 13):
        _recevoir(f"wct-{numero:02d}", ville="Saint-Jean-sur-Richelieu", type_travaux="isolation_thermique")

    reponse = lister(limite=8)

    assert len(reponse["resultat"]["demandes"]) == 8
    assert len(json.dumps(reponse["resultat"], ensure_ascii=False)) < jetons.LIMITE_SORTIE_DEFAUT


def test_lister_n_ecrit_rien(base_durable, lister):
    _recevoir("wct-1")
    with stockage.transaction():
        avant = list(stockage.maillons("m07-marketing", "demandes_avis"))

    lister()
    lister(limite=1)

    with stockage.transaction():
        assert list(stockage.maillons("m07-marketing", "demandes_avis")) == avant


def test_seul_l_admin_peut_l_appeler_depuis_un_appareil():
    outil = next(o for o in outils() if o.nom == "m7_lister_demandes_avis")

    assert outil.roles_appareil == frozenset({"admin"})
