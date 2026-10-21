"""PLAN T1.4-m : M3 relit le propriétaire COURANT d'un lead au bus (le plus grand rang de `m2.lead_assigne`).

Le fait est publié à la main, comme M2 le publie (`assignation.fait_assigne` : rang 1 sous `m2-lead-assigne-<lead>`,
rang n >= 2 sous `m2-lead-reassigne-<n>-<lead>` avec `rang` et `proprietaire_precedent`). La chaîne réelle est prouvée
par `tests/test_reassignation_suit_m3.py` du socle. Données fictives (AGENTS.md).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import outils as outils_m3  # noqa: E402

from opsys import evenements, stockage  # noqa: E402

FICTIF = True
H = "2026-09-29T14:00:00-04:00"


@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m3-reassigne.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _rang_un(lead_id, proprietaire):
    evenements.publier("m2.lead_assigne", "m02-revenue-crm",
                       {"lead_id": lead_id, "proprietaire": proprietaire, "horodatage_assignation": H},
                       evenement_id=f"m2-lead-assigne-{lead_id}")


def _rang(lead_id, rang, proprietaire, precedent, **plus):
    charge = {"lead_id": lead_id, "proprietaire": proprietaire, "horodatage_assignation": H, "rang": rang,
              "proprietaire_precedent": precedent}
    evenements.publier("m2.lead_assigne", "m02-revenue-crm", {**charge, **plus},
                       evenement_id=f"m2-lead-reassigne-{rang}-{lead_id}")


def _proprietaire(lead_id):
    with stockage.transaction():
        return outils_m3._proprietaire_du_lead(lead_id)


def test_sans_reassignation_c_est_le_rang_un_comme_avant():
    with stockage.transaction():
        _rang_un("lead-1", "vendeur.un")

    assert _proprietaire("lead-1") == "vendeur.un"


def test_le_plus_grand_rang_publie_gagne():
    with stockage.transaction():
        _rang_un("lead-1", "vendeur.un")
        _rang("lead-1", 2, "vendeur.deux", "vendeur.un")
        _rang("lead-1", 3, "vendeur.un", "vendeur.deux")
        _rang("lead-1", 4, "vendeur.trois", "vendeur.un")

    assert _proprietaire("lead-1") == "vendeur.trois"


def test_un_rang_un_absent_n_arrete_pas_la_lecture_d_un_lead_reassigne_avant_la_republication():
    with stockage.transaction():
        _rang("lead-1", 2, "vendeur.deux", "vendeur.un")

    assert _proprietaire("lead-1") == "vendeur.deux"


def test_un_lead_sans_aucun_fait_n_a_pas_de_proprietaire():
    assert _proprietaire("lead-inconnu") is None


def test_un_rang_isole_apres_un_trou_est_ignore_jamais_un_proprietaire_suppose():
    with stockage.transaction():
        _rang_un("lead-1", "vendeur.un")
        _rang("lead-1", 3, "vendeur.trois", "vendeur.deux")  # le rang 2 n'existe pas

    assert _proprietaire("lead-1") == "vendeur.un"


def test_un_fait_qui_ne_dit_pas_son_rang_ou_son_lead_est_ignore():
    with stockage.transaction():
        _rang_un("lead-1", "vendeur.un")
        evenements.publier("m2.lead_assigne", "m02-revenue-crm",
                           {"lead_id": "autre-lead", "proprietaire": "vendeur.deux", "horodatage_assignation": H,
                            "rang": 2, "proprietaire_precedent": "vendeur.un"},
                           evenement_id="m2-lead-reassigne-2-lead-1")

    assert _proprietaire("lead-1") == "vendeur.un"


def test_un_fait_dont_le_rang_contredit_son_identifiant_est_ignore():
    """Publié sous `m2-lead-reassigne-2-...` mais annonçant le rang 3 : ce n'est pas le rang 2. (Un rang absent ou
    non entier, lui, est refusé dès la publication par le schéma du catalogue.)"""
    charge = {"lead_id": "lead-1", "proprietaire": "vendeur.deux", "horodatage_assignation": H, "rang": 3,
              "proprietaire_precedent": "vendeur.un"}
    with stockage.transaction():
        _rang_un("lead-1", "vendeur.un")
        evenements.publier("m2.lead_assigne", "m02-revenue-crm", charge, evenement_id="m2-lead-reassigne-2-lead-1")

    assert _proprietaire("lead-1") == "vendeur.un"


def test_deux_leads_ne_partagent_jamais_un_identifiant_de_fait():
    """`lead-1-r2`-like : un lead nommé comme le suffixe d'un autre ne lit pas son fait."""
    with stockage.transaction():
        _rang_un("2-lead-1", "vendeur.trois")
        _rang_un("lead-1", "vendeur.un")

    assert _proprietaire("lead-1") == "vendeur.un" and _proprietaire("2-lead-1") == "vendeur.trois"


def test_hors_transaction_rien_n_est_lisible():
    assert outils_m3._proprietaire_du_lead("lead-1") is None
