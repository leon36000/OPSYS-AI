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
from sqlalchemy import select, update

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import devis_durable, estime_vs_reel  # noqa: E402
from m3_estimation.outils import outils, registre_production  # noqa: E402

from opsys import evenements, stockage  # noqa: E402
from opsys.evenements.schemas import erreurs_charge  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402
from opsys.stockage import codec  # noqa: E402
from opsys.stockage.schema import EVENEMENTS_SORTANTS, REGISTRES  # noqa: E402

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
    return [{"hash_maillon": f"{rang + 1:064x}", "charge": charge} for rang, charge in enumerate(charges)]


def _charge_devis():
    return {"devis_id": _DEVIS_ID, "lead_id": "lead-001", "prix_total": "360.00"}


def _charge_avec_source(duree, *, hash_source="a" * 64, semantique="duree_ecoulee_intervention"):
    registre_devis = []
    devis, verdict = devis_durable.creer_devis(
        devis_id=_DEVIS_ID, lead_id="lead-001", chantier_id=None,
        lignes=[{"description": "Gouttière", "quantite": "1", "unite": "pi", "cout_unitaire": "10.00",
                 "reference_besoin_materiau": None}],
        taux_marge="0.20", horodatage=_HORODATAGE, registre_cible=registre_devis,
        estimation_source_hash=hash_source,
    )
    assert verdict is None
    source = _estimation(
        duree_estimee_minutes=duree,
        trace_calibration_temps={
            "version_schema": 2, "semantique_temps": semantique, "duree_estimee_minutes": duree,
        },
    )
    maillon = {"hash_maillon": hash_source, "charge": source}
    charge = estime_vs_reel.avec_duree_estimee(_charge_devis(), _DEVIS_ID, registre_devis, [maillon])
    return charge


# Aucun devis durable : `lire_devis` rend un verdict, seule l'estimation d'origine peut porter la durée.
_SANS_DEVIS: list = []


# =========================================================================================
# 1. La fonction pure
# =========================================================================================
def test_la_duree_de_l_estimation_d_origine_entre_dans_la_charge_en_texte_decimal():
    charge = _charge_avec_source("180.5")

    assert charge["duree_estimee_minutes"] == "180.5"
    assert isinstance(charge["duree_estimee_minutes"], str)  # jamais un nombre JSON
    sans_mesure = {
        cle: valeur for cle, valeur in charge.items()
        if cle not in {"duree_estimee_minutes", "semantique_temps"}
    }
    assert sans_mesure == _charge_devis()


def test_la_charge_d_origine_n_est_pas_modifiee_c_est_une_copie():
    origine = _charge_devis()

    estime_vs_reel.avec_duree_estimee(
        origine, _DEVIS_ID, _SANS_DEVIS, _maillons(_estimation(duree_estimee_minutes="60")))

    assert "duree_estimee_minutes" not in origine


@pytest.mark.parametrize("duree", ["60", "60.0", "0.5", Decimal("1E+2"), Decimal("120.50")])
def test_la_duree_est_toujours_un_texte_decimal_sans_exposant_ni_signe(duree):
    charge = _charge_avec_source(duree)

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


def test_aucune_estimation_recente_n_est_choisie_sans_reference_devis():
    charge = estime_vs_reel.avec_duree_estimee(
        _charge_devis(), _DEVIS_ID, _SANS_DEVIS,
        _maillons(_estimation(duree_estimee_minutes="60"), _estimation(duree_estimee_minutes="90")))

    assert "duree_estimee_minutes" not in charge


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


def _creer_brouillon(devis_id=_DEVIS_ID, estimation_source_hash=None, lead_id="lead-001"):
    arguments = {
        "devis_id": devis_id,
        "lead_id": lead_id,
        "chantier_id": None,
        "lignes": [
            {
                "description": "Gouttière alu 5 po",
                "quantite": "30",
                "unite": "pi_lin",
                "cout_unitaire": "10.00",
                "reference_besoin_materiau": "besoin-goutt-001",
            }
        ],
        "taux_marge": "0.20",
        "horodatage": _HORODATAGE,
    }
    if estimation_source_hash is not None:
        arguments["estimation_source_hash"] = estimation_source_hash
    cree = executer_atomique(_outil("m3_creer_devis"), arguments)
    assert cree["ok"] is True and cree["resultat"]["accepte"] is True, cree


def _creer_et_accepter(devis_id=_DEVIS_ID, estimation_source_hash=None):
    _creer_brouillon(devis_id, estimation_source_hash)
    accepte = executer_atomique(
        _outil("m3_marquer_devis_accepte"),
        {"devis_id": devis_id, "approbateur": "nathan", "horodatage": _HORODATAGE},
    )
    assert accepte["ok"] is True and accepte["resultat"]["accepte"] is True, accepte


def _ecrire_estimation(**charge):
    with stockage.transaction():
        maillon, verdict = registre_production().ajouter(_estimation(**charge))
    assert verdict is None
    return maillon["hash_maillon"]


def _corrompre_source(hash_source):
    with stockage.transaction() as cnx:
        rows = cnx.execute(select(REGISTRES.c.rang, REGISTRES.c.maillon).where(
            (REGISTRES.c.departement == "m03-estimation") & (REGISTRES.c.registre == "principal")
        )).all()
        for row in rows:
            maillon = codec.decoder(row.maillon)
            if maillon["hash_maillon"] == hash_source:
                maillon["charge"]["lead_id"] = "lead-corrompu"
                cnx.execute(update(REGISTRES).where(
                    (REGISTRES.c.departement == "m03-estimation") &
                    (REGISTRES.c.registre == "principal") & (REGISTRES.c.rang == row.rang)
                ).values(maillon=codec.encoder(maillon)))
                return
    raise AssertionError(f"maillon source {hash_source} absent")


def _charge_publiee(devis_id=_DEVIS_ID):
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m3.devis_accepte",
            EVENEMENTS_SORTANTS.c.evenement_id == f"m3-devis-accepte-{devis_id}")).one()
    return codec.decoder(ligne.charge)


def test_devis_accepte_publie_mesure_seulement_depuis_source_exacte_qualifiee(base_durable):
    source_hash = _ecrire_estimation(
        duree_estimee_minutes="180",
        trace_calibration_temps={
            "version_schema": 2, "semantique_temps": "duree_ecoulee_intervention", "duree_estimee_minutes": "180",
        },
    )

    _creer_et_accepter(estimation_source_hash=source_hash)

    charge = _charge_publiee()
    assert charge["duree_estimee_minutes"] == "180"
    assert charge["estimation_source_hash"] == source_hash
    assert charge["semantique_temps"] == "duree_ecoulee_intervention"
    assert (charge["cout_total"], charge["prix_total"], charge["taux_marge"]) == ("300.00", "360.00", "0.20")
    assert erreurs_charge("m3.devis_accepte", charge) == []  # conforme au catalogue (clé optionnelle, motif décimal)
    assert all("cout_unitaire" not in ligne and "cout_ligne" not in ligne for ligne in charge["lignes"])


def test_sans_estimation_l_evenement_est_publie_sans_la_cle_comme_avant(base_durable):
    _creer_et_accepter()

    charge = _charge_publiee()
    assert "duree_estimee_minutes" not in charge
    assert erreurs_charge("m3.devis_accepte", charge) == []


def test_estimation_presente_mais_reference_absente_ne_fournit_pas_de_mesure(base_durable):
    _ecrire_estimation(
        duree_estimee_minutes="180",
        trace_calibration_temps={"version_schema": 2, "semantique_temps": "duree_ecoulee_intervention"},
    )
    _creer_et_accepter()
    assert "duree_estimee_minutes" not in _charge_publiee()


def test_reference_exacte_mais_semantique_nonqualifiee_ne_fournit_pas_de_mesure(base_durable):
    source_hash = _ecrire_estimation(
        duree_estimee_minutes="180",
        trace_calibration_temps={
            "version_schema": 2,
            "semantique_temps": "non_qualifiee",
            "duree_estimee_minutes": "180",
        },
    )
    _creer_et_accepter(estimation_source_hash=source_hash)
    charge = _charge_publiee()
    assert charge["estimation_source_hash"] == source_hash
    assert "duree_estimee_minutes" not in charge and "semantique_temps" not in charge


def test_une_estimation_sans_duree_publie_un_devis_sans_la_cle(base_durable):
    _ecrire_estimation()  # barème sans durée par unité : aucune durée n'est calculée

    _creer_et_accepter()

    assert "duree_estimee_minutes" not in _charge_publiee()


def test_l_estimation_d_un_autre_devis_ne_donne_pas_de_duree(base_durable):
    _ecrire_estimation(devis_id="M3-DEVIS-autre", duree_estimee_minutes="999")

    _creer_et_accepter()

    assert "duree_estimee_minutes" not in _charge_publiee()


def test_reference_source_invalide_refuse_creation_sans_maillon_devis(base_durable):
    with stockage.transaction():
        avant = len(stockage.maillons("m03-estimation", "devis"))
    reponse = executer_atomique(_outil("m3_creer_devis"), {
        "devis_id": _DEVIS_ID, "lead_id": "lead-001", "chantier_id": None,
        "lignes": [{"description": "Gouttière", "quantite": "1", "unite": "pi",
                    "cout_unitaire": "10.00", "reference_besoin_materiau": None}],
        "taux_marge": "0.20", "horodatage": _HORODATAGE, "estimation_source_hash": "f" * 64,
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    with stockage.transaction():
        assert len(stockage.maillons("m03-estimation", "devis")) == avant


def test_reference_source_mauvais_lead_refuse_creation_sans_append(base_durable):
    source_hash = _ecrire_estimation(duree_estimee_minutes="180")
    avant = None
    with stockage.transaction():
        avant = len(stockage.maillons("m03-estimation", "devis"))
    reponse = executer_atomique(_outil("m3_creer_devis"), {
        "devis_id": _DEVIS_ID, "lead_id": "autre-lead", "chantier_id": None,
        "lignes": [{"description": "Gouttière", "quantite": "1", "unite": "pi",
                    "cout_unitaire": "10.00", "reference_besoin_materiau": None}],
        "taux_marge": "0.20", "horodatage": _HORODATAGE, "estimation_source_hash": source_hash,
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    with stockage.transaction():
        assert len(stockage.maillons("m03-estimation", "devis")) == avant


def test_reference_source_chaine_corrompue_refuse_creation_sans_append(base_durable):
    source_hash = _ecrire_estimation(duree_estimee_minutes="180")
    _corrompre_source(source_hash)
    with stockage.transaction():
        avant = len(stockage.maillons("m03-estimation", "devis"))
    reponse = executer_atomique(_outil("m3_creer_devis"), {
        "devis_id": _DEVIS_ID, "lead_id": "lead-001", "chantier_id": None,
        "lignes": [{"description": "Gouttière", "quantite": "1", "unite": "pi",
                    "cout_unitaire": "10.00", "reference_besoin_materiau": None}],
        "taux_marge": "0.20", "horodatage": _HORODATAGE, "estimation_source_hash": source_hash,
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    with stockage.transaction():
        assert len(stockage.maillons("m03-estimation", "devis")) == avant


def test_source_corrompue_apres_creation_ne_bloque_pas_acceptation_mais_omet_la_mesure(base_durable):
    source_hash = _ecrire_estimation(
        duree_estimee_minutes="180",
        trace_calibration_temps={"version_schema": 2, "semantique_temps": "duree_ecoulee_intervention",
                                 "duree_estimee_minutes": "180"},
    )
    _creer_brouillon(estimation_source_hash=source_hash)
    _corrompre_source(source_hash)

    accepte = executer_atomique(_outil("m3_marquer_devis_accepte"), {
        "devis_id": _DEVIS_ID, "approbateur": "nathan", "horodatage": _HORODATAGE})
    assert accepte["ok"] is True and accepte["resultat"]["accepte"] is True, accepte
    charge = _charge_publiee()
    assert charge["estimation_source_hash"] == source_hash
    assert "duree_estimee_minutes" not in charge and "semantique_temps" not in charge


def test_la_publication_reste_idempotente_par_devis(base_durable):
    _ecrire_estimation(duree_estimee_minutes="180")
    _creer_et_accepter()
    avant = _charge_publiee()

    evenements.publier("m3.devis_accepte", "m03-estimation", {**avant, "duree_estimee_minutes": "999"},
                       evenement_id=f"m3-devis-accepte-{_DEVIS_ID}")  # un rejeu du même id n'écrase rien

    assert _charge_publiee() == avant
