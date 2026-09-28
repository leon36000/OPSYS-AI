"""`outils.attentes()` : la file du propriétaire de M5 (ADR-0009 §5, PLAN T1.3-c point 4).

Combine (1) les attentes de facturation déjà calculées par `lister_attentes_facturation`, (2)
chaque facture BROUILLON prête à envoyer (N4, même niveau que `m5_envoyer_facture`), et (3) le
signal de variance de chantier CRITIQUE reçu de M6 (`m6.variance_chantier`, catalogue existant,
gardé par wct_id via `variance_recus.py`) affiché À CÔTÉ d'une facture BROUILLON — jamais un
blocage de son envoi (relevé de bout en bout : `test_variance_critique_n_empeche_jamais_l_envoi`).

Utilise le VRAI bus (`opsys.evenements.publier`/`repartir`, patron déjà établi par
`test_evenements_m5.py`) sur une base SQLite temporaire migrée, avec SEULEMENT M5 routé — les
comptes de `repartir()` restent scopés à M5, jamais les comptes globaux du bus. Identifiants et
montants fictifs (DEFINITION-PRODUIT §1).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import m5_financecore.outils as m5_outils  # noqa: E402

from opsys import approbations, evenements, stockage  # noqa: E402
from opsys.departements import charger_departements, lire_manifeste  # noqa: E402

_DEPARTEMENT = "m05-financecore"
_RACINE_M5 = Path(__file__).resolve().parents[1]
_CHAMPS_ATTENTE = {"type", "id", "resume", "niveau", "depuis", "action_proposee"}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m5-attentes.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    yield url
    stockage.liberer()


def _deps_bus():
    """Seul M5 reçoit ces événements (même patron que test_evenements_m5.py::_deps_bus)."""
    tous = charger_departements()
    return {_DEPARTEMENT: tous[_DEPARTEMENT]}


def _devis_accepte(devis_id="DEVIS-1", chantier_id="CHANTIER-1", **overrides):
    """Mêmes chiffres que test_evenements_m5.py/test_facturation.py : 600.00 $ avant taxes ->
    689.85 $ après taxes."""
    base = {
        "devis_id": devis_id, "lead_id": "LEAD-1-fictif", "chantier_id": chantier_id,
        "lignes": [
            {
                "reference_ligne": f"{devis_id}-L0", "description": "Gouttières 5po aluminium",
                "quantite": "40", "unite": "pi", "prix_unitaire": "10.00", "prix_ligne": "400.00",
                "reference_besoin_materiau": "gouttiere_5po_alu",
            },
            {
                "reference_ligne": f"{devis_id}-L1", "description": "Main d'oeuvre installation",
                "quantite": "1", "unite": "forfait", "prix_unitaire": "200.00", "prix_ligne": "200.00",
                "reference_besoin_materiau": None,
            },
        ],
        "cout_total": "450.00", "prix_total": "600.00", "taux_marge": "0.20",
        "horodatage_acceptation": "2026-09-20T10:00:00-04:00",
    }
    base.update(overrides)
    return base


def _wct(wct_id="WCT-1", devis_id="DEVIS-1", horodatage_completion="2026-09-25T16:30:00-04:00", **overrides):
    base = {
        "wct_id": wct_id, "intervention_id": f"INT-{wct_id}-fictif", "lead_id": "LEAD-1-fictif",
        "technicien_id": "TECH-1-fictif", "horodatage_completion": horodatage_completion,
        "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2}, "duree_reelle_minutes": 180,
        "ecart_signale": False, "revue_id": None, "hash_maillon": f"hash-{wct_id}-fictif",
        "consommateurs_cibles": ["M5"], "devis_id": devis_id, "statut": "completed_verified",
    }
    base.update(overrides)
    return base


def _variance_chantier(
    wct_id, intervention_id, chantier_id="CHANTIER-1", statut_variance="evaluee", signal_critique=True,
    horodatage_completion="2026-09-25T16:30:00-04:00", seuil_pourcentage=0.3, lignes=None,
):
    if lignes is None and statut_variance == "evaluee":
        lignes = [{
            "materiau": "gouttiere_5po_alu", "unite": "pi", "quantite_prevue": "40.0",
            "quantite_reelle": "56.0", "ecart_pourcentage": "0.4", "critique": bool(signal_critique),
        }]
    return {
        "evenement_id": f"m6-variance-{wct_id}-{statut_variance}",
        "wct_id": wct_id, "intervention_id": intervention_id, "chantier_id": chantier_id,
        "statut_variance": statut_variance, "signal_critique": signal_critique,
        "seuil_pourcentage": seuil_pourcentage, "horodatage_completion": horodatage_completion,
        "lignes": lignes,
    }


def _publier_variance(charge):
    evenements.publier("m6.variance_chantier", "m06-material-control", charge, evenement_id=charge["evenement_id"])


def _attentes():
    with stockage.transaction():
        return m5_outils.attentes()


def _valider_forme(items):
    for item in items:
        assert set(item) == _CHAMPS_ATTENTE, item
        assert item["depuis"], item  # jamais une date vide


# -- attentes de facturation (déjà calculées) reformées à la forme commune ----------------------


def test_devis_seul_donne_une_attente_en_attente_travaux_termines_avec_depuis(base_durable):
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    resume = evenements.repartir(deps, maintenant="2026-09-20T10:05:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    items = _attentes()

    _valider_forme(items)
    [item] = items
    assert item["type"] == "facturation_en_attente_travaux_termines"
    assert item["id"] == "DEVIS-1"
    assert item["niveau"] == "N3"
    assert item["depuis"] == "2026-09-20T10:00:00-04:00"  # horodatage_acceptation du devis
    assert item["action_proposee"] == "compléter"


def test_wct_seul_donne_une_attente_en_attente_devis_accepte_avec_depuis(base_durable):
    deps = _deps_bus()
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    resume = evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    items = _attentes()

    _valider_forme(items)
    [item] = items
    assert item["type"] == "facturation_en_attente_devis_accepte"
    assert item["depuis"] == "2026-09-25T16:30:00-04:00"  # horodatage_completion du WCT


def test_wct_sans_devis_id_donne_une_attente_avec_depuis(base_durable):
    deps = _deps_bus()
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct(wct_id="WCT-SANS-DEVIS", devis_id=None))
    resume = evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    items = _attentes()

    _valider_forme(items)
    [item] = items
    assert item["type"] == "wct_sans_devis_id"
    assert item["id"] == "WCT-SANS-DEVIS"
    assert item["niveau"] == "N3"
    assert item["depuis"] == "2026-09-25T16:30:00-04:00"


# -- facture BROUILLON prête à envoyer (point 4) -------------------------------------------------


def test_facture_brouillon_apparait_prete_a_envoyer_niveau_n4(base_durable):
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    resume = evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    items = _attentes()

    _valider_forme(items)
    [item] = items
    assert item["type"] == "facture_brouillon"
    assert item["id"] == "fac-DEVIS-1"
    assert item["niveau"] == "N4"
    assert item["action_proposee"] == "envoyer"
    assert item["depuis"] == "2026-09-25T16:30:00-04:00"  # horodatage de la facture (celui du WCT)


# -- le signal de variance CRITIQUE de M6, à côté de la facture, sans jamais la bloquer ----------


def test_variance_critique_apparait_a_cote_de_la_facture_brouillon(base_durable):
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")

    with stockage.transaction():
        _publier_variance(_variance_chantier("WCT-1", "INT-WCT-1-fictif", signal_critique=True))
    resume = evenements.repartir(deps, maintenant="2026-09-25T16:40:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    items = _attentes()

    _valider_forme(items)
    types = {item["type"] for item in items}
    assert types == {"facture_brouillon", "chantier_a_reviser"}
    facture_item = next(i for i in items if i["type"] == "facture_brouillon")
    variance_item = next(i for i in items if i["type"] == "chantier_a_reviser")
    assert facture_item["id"] == "fac-DEVIS-1"  # toujours là : le signal ne la remplace jamais
    assert variance_item["id"] == "variance-WCT-1"
    assert variance_item["niveau"] == "N4"
    assert variance_item["action_proposee"] == "réviser"
    assert "CHANTIER-1" in variance_item["resume"] and "WCT-1" in variance_item["resume"]


def test_variance_critique_n_empeche_jamais_l_envoi(base_durable):
    """Relevé de bout en bout (point 4 du mandat) : même en présence du signal critique,
    m5_envoyer_facture reste utilisable — M6 « signale seulement », jamais un verrou."""
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    with stockage.transaction():
        _publier_variance(_variance_chantier("WCT-1", "INT-WCT-1-fictif", signal_critique=True))
    evenements.repartir(deps, maintenant="2026-09-25T16:40:00-04:00")

    items = _attentes()
    assert any(i["type"] == "chantier_a_reviser" for i in items), "le signal doit être présent"

    with stockage.transaction():
        reponse = m5_outils.envoyer_facture("fac-DEVIS-1", "2026-09-26T09:00:00-04:00")

    assert reponse["accepte"] is True
    assert reponse["resultat"]["statut"] == "ENVOYEE"


def test_variance_non_critique_n_ajoute_aucun_item(base_durable):
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    with stockage.transaction():
        _publier_variance(_variance_chantier("WCT-1", "INT-WCT-1-fictif", signal_critique=False))
    resume = evenements.repartir(deps, maintenant="2026-09-25T16:40:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    items = _attentes()

    assert {item["type"] for item in items} == {"facture_brouillon"}


def test_variance_statut_non_evalue_n_ajoute_aucun_item(base_durable):
    """declaration_absente/prevu_absent/seuil_absent : rien à réviser, signal_critique est null."""
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    with stockage.transaction():
        _publier_variance(_variance_chantier(
            "WCT-1", "INT-WCT-1-fictif", statut_variance="declaration_absente", signal_critique=None,
        ))
    resume = evenements.repartir(deps, maintenant="2026-09-25T16:40:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    items = _attentes()

    assert {item["type"] for item in items} == {"facture_brouillon"}


def test_variance_republiee_garde_le_dernier_signal_connu_par_wct_id_idempotent(base_durable):
    """PLAN T1.3-c point 4 : « garder le signal par wct_id, idempotent ». Une réévaluation change
    de statut pour le MÊME wct_id (declaration_absente -> evaluee, cf. catalogue) : le DERNIER
    connu fait foi, jamais les deux empilés."""
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")

    with stockage.transaction():
        _publier_variance(_variance_chantier(
            "WCT-1", "INT-WCT-1-fictif", statut_variance="declaration_absente", signal_critique=None,
        ))
    evenements.repartir(deps, maintenant="2026-09-25T16:40:00-04:00")
    assert {item["type"] for item in _attentes()} == {"facture_brouillon"}, "pas encore évalué"

    with stockage.transaction():
        _publier_variance(_variance_chantier("WCT-1", "INT-WCT-1-fictif", signal_critique=True))
    resume = evenements.repartir(deps, maintenant="2026-09-25T16:45:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    items = _attentes()
    variance_items = [i for i in items if i["type"] == "chantier_a_reviser"]
    assert len(variance_items) == 1, "un seul signal affiché par wct_id, jamais empilé"

    # redélivrance du MÊME evenement_id (le bus la rend déjà idempotente, ADR-0009 §3) : toujours un seul.
    resume_redelivraison = evenements.repartir(deps, maintenant="2026-09-25T16:50:00-04:00")
    assert resume_redelivraison == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert len([i for i in _attentes() if i["type"] == "chantier_a_reviser"]) == 1


# -- file_proprietaire (ADR-0009 §5) : le mécanisme générique du socle affiche bien attentes() ---


def test_file_proprietaire_affiche_la_facture_brouillon_et_le_signal_de_variance(base_durable):
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    with stockage.transaction():
        _publier_variance(_variance_chantier("WCT-1", "INT-WCT-1-fictif", signal_critique=True))
    evenements.repartir(deps, maintenant="2026-09-25T16:40:00-04:00")

    dep = lire_manifeste(_RACINE_M5)
    with stockage.transaction() as cnx:
        file = approbations.file_proprietaire(cnx, {_DEPARTEMENT: dep})

    types = {item["type"] for item in file}
    assert {"facture_brouillon", "chantier_a_reviser"} <= types
    for item in file:
        assert item["departement"] == _DEPARTEMENT
        assert set(item) == _CHAMPS_ATTENTE | {"departement"}
