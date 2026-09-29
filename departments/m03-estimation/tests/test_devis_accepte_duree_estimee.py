"""PLAN T1.5-d : `m3.devis_accepte` porte la durée estimée du chantier, quand l'estimation du devis la porte
(clé OPTIONNELLE `duree_estimee_minutes`, déjà acceptée par le catalogue) : M8 la compare à la durée réelle du WCT
et calcule le temps prévu contre réel.

Fail-closed : pas d'estimation d'origine pour ce devis, durée absente ou illisible -> la clé est OMISE (jamais une
durée par défaut, jamais zéro) et M8 répond « non calculable, manque duree_estimee_minutes ».

Deux étages : la fonction pure `estime_vs_reel.avec_duree_estimee`, puis l'outil RÉEL `m3_marquer_devis_accepte`
sur une base SQLite temporaire migrée (l'événement publié est relu dans `evenements_sortants`, validé par le
catalogue à la publication). Identifiants et montants fictifs.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import estime_vs_reel  # noqa: E402
from m3_estimation.outils import outils, registre_production  # noqa: E402

from opsys import evenements, stockage  # noqa: E402
from opsys.evenements.schemas import erreurs_charge  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402
from opsys.stockage import codec  # noqa: E402
from opsys.stockage.schema import EVENEMENTS_SORTANTS  # noqa: E402

FICTIF = True
_HORODATAGE = "2026-09-28T14:00:00-04:00"
_DEVIS_ID = "M3-DEVIS-duree-001"


def _estimation(devis_id=_DEVIS_ID, **surcharges):
    """Charge d'estimation du registre d'origine (`registre.py`) : les six clés requises, plus la durée."""
    base = {
        "devis_id": devis_id, "lead_id": "lead-001", "empreinte_marqueur_m2": "e" * 64, "niveau_confiance": 0.9,
        "bareme_version": "v1-fictif", "graine_monte_carlo": 42,
    }
    base.update(surcharges)
    return base


def _maillons(*charges):
    return [{"charge": charge} for charge in charges]


def _charge_devis():
    return {"devis_id": _DEVIS_ID, "lead_id": "lead-001", "prix_total": "360.00"}


# Aucun devis durable : `lire_devis` rend un verdict, seule l'estimation d'origine peut porter la durée.
_SANS_DEVIS: list = []


# =========================================================================================
# 1. La fonction pure
# =========================================================================================
def test_la_duree_de_l_estimation_d_origine_entre_dans_la_charge_en_texte_decimal():
    charge = estime_vs_reel.avec_duree_estimee(
        _charge_devis(), _DEVIS_ID, _SANS_DEVIS, _maillons(_estimation(duree_estimee_minutes="180.5")))

    assert charge["duree_estimee_minutes"] == "180.5"
    assert isinstance(charge["duree_estimee_minutes"], str)  # jamais un nombre JSON
    assert {cle: valeur for cle, valeur in charge.items() if cle != "duree_estimee_minutes"} == _charge_devis()


def test_la_charge_d_origine_n_est_pas_modifiee_c_est_une_copie():
    origine = _charge_devis()

    estime_vs_reel.avec_duree_estimee(
        origine, _DEVIS_ID, _SANS_DEVIS, _maillons(_estimation(duree_estimee_minutes="60")))

    assert "duree_estimee_minutes" not in origine


@pytest.mark.parametrize("duree", ["60", "60.0", "0.5", Decimal("1E+2"), Decimal("120.50")])
def test_la_duree_est_toujours_un_texte_decimal_sans_exposant_ni_signe(duree):
    charge = estime_vs_reel.avec_duree_estimee(
        _charge_devis(), _DEVIS_ID, _SANS_DEVIS, _maillons(_estimation(duree_estimee_minutes=duree)))

    texte = charge["duree_estimee_minutes"]
    assert erreurs_charge("m3.devis_accepte", {
        **_donnees_valides(), "duree_estimee_minutes": texte}) == [], texte
    assert Decimal(texte) == Decimal(duree)


def _donnees_valides():
    return {
        "devis_id": _DEVIS_ID, "lead_id": "lead-001", "chantier_id": None,
        "lignes": [{"reference_ligne": f"{_DEVIS_ID}-L0", "description": "Gouttière", "quantite": "30",
                    "unite": "pi_lin", "prix_unitaire": "12.00", "prix_ligne": "360.00",
                    "reference_besoin_materiau": None}],
        "cout_total": "300.00", "prix_total": "360.00", "taux_marge": "0.20", "horodatage_acceptation": _HORODATAGE,
    }


def test_sans_estimation_d_origine_la_cle_est_omise_jamais_une_duree_par_defaut():
    charge = estime_vs_reel.avec_duree_estimee(_charge_devis(), _DEVIS_ID, _SANS_DEVIS, [])

    assert charge == _charge_devis()


def test_une_estimation_sans_duree_laisse_la_cle_absente():
    charge = estime_vs_reel.avec_duree_estimee(
        _charge_devis(), _DEVIS_ID, _SANS_DEVIS, _maillons(_estimation()))

    assert "duree_estimee_minutes" not in charge


@pytest.mark.parametrize("duree", ["0", "-30", "abc", "NaN", "Infinity", 60, 60.0, None, True, ""])
def test_une_duree_illisible_nulle_negative_ou_pas_un_texte_est_omise(duree):
    charge = estime_vs_reel.avec_duree_estimee(
        _charge_devis(), _DEVIS_ID, _SANS_DEVIS, _maillons(_estimation(duree_estimee_minutes=duree)))

    assert "duree_estimee_minutes" not in charge, repr(duree)


def test_l_estimation_d_un_autre_devis_n_est_jamais_prise():
    charge = estime_vs_reel.avec_duree_estimee(
        _charge_devis(), _DEVIS_ID, _SANS_DEVIS,
        _maillons(_estimation(devis_id="M3-DEVIS-autre", duree_estimee_minutes="999")))

    assert "duree_estimee_minutes" not in charge


def test_la_plus_recente_estimation_du_devis_fait_foi():
    charge = estime_vs_reel.avec_duree_estimee(
        _charge_devis(), _DEVIS_ID, _SANS_DEVIS,
        _maillons(_estimation(duree_estimee_minutes="60"), _estimation(duree_estimee_minutes="90")))

    assert charge["duree_estimee_minutes"] == "90"


# =========================================================================================
# 2. L'outil réel : l'événement publié
# =========================================================================================
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _outil(nom):
    return next(o for o in outils() if o.nom == nom)


def _creer_et_accepter(devis_id=_DEVIS_ID):
    cree = executer_atomique(_outil("m3_creer_devis"), {
        "devis_id": devis_id, "lead_id": "lead-001", "chantier_id": None,
        "lignes": [{"description": "Gouttière alu 5 po", "quantite": "30", "unite": "pi_lin",
                    "cout_unitaire": "10.00", "reference_besoin_materiau": "besoin-goutt-001"}],
        "taux_marge": "0.20", "horodatage": _HORODATAGE,
    })
    assert cree["ok"] is True and cree["resultat"]["accepte"] is True, cree
    accepte = executer_atomique(_outil("m3_marquer_devis_accepte"), {
        "devis_id": devis_id, "approbateur": "nathan", "horodatage": _HORODATAGE})
    assert accepte["ok"] is True and accepte["resultat"]["accepte"] is True, accepte


def _ecrire_estimation(**charge):
    with stockage.transaction():
        _, verdict = registre_production().ajouter(_estimation(**charge))
    assert verdict is None


def _charge_publiee(devis_id=_DEVIS_ID):
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m3.devis_accepte",
            EVENEMENTS_SORTANTS.c.evenement_id == f"m3-devis-accepte-{devis_id}")).one()
    return codec.decoder(ligne.charge)


def test_le_devis_accepte_publie_la_duree_estimee_de_son_estimation(base_durable):
    _ecrire_estimation(duree_estimee_minutes="180")

    _creer_et_accepter()

    charge = _charge_publiee()
    assert charge["duree_estimee_minutes"] == "180"
    assert (charge["cout_total"], charge["prix_total"], charge["taux_marge"]) == ("300.00", "360.00", "0.20")
    assert erreurs_charge("m3.devis_accepte", charge) == []  # conforme au catalogue (clé optionnelle, motif décimal)
    assert all("cout_unitaire" not in ligne and "cout_ligne" not in ligne for ligne in charge["lignes"])


def test_sans_estimation_l_evenement_est_publie_sans_la_cle_comme_avant(base_durable):
    _creer_et_accepter()

    charge = _charge_publiee()
    assert "duree_estimee_minutes" not in charge
    assert erreurs_charge("m3.devis_accepte", charge) == []


def test_une_estimation_sans_duree_publie_un_devis_sans_la_cle(base_durable):
    _ecrire_estimation()  # barème sans durée par unité : aucune durée n'est calculée

    _creer_et_accepter()

    assert "duree_estimee_minutes" not in _charge_publiee()


def test_l_estimation_d_un_autre_devis_ne_donne_pas_de_duree(base_durable):
    _ecrire_estimation(devis_id="M3-DEVIS-autre", duree_estimee_minutes="999")

    _creer_et_accepter()

    assert "duree_estimee_minutes" not in _charge_publiee()


def test_la_publication_reste_idempotente_par_devis(base_durable):
    _ecrire_estimation(duree_estimee_minutes="180")
    _creer_et_accepter()
    avant = _charge_publiee()

    evenements.publier("m3.devis_accepte", "m03-estimation", {**avant, "duree_estimee_minutes": "999"},
                       evenement_id=f"m3-devis-accepte-{_DEVIS_ID}")  # un rejeu du même id n'écrase rien

    assert _charge_publiee() == avant
