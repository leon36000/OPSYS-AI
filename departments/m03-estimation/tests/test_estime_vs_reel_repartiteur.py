"""Bout en bout de l'estimé-vs-réel de M3 (PLAN T1.2-d) par le VRAI répartiteur du bus
(`opsys.evenements.repartir`), en ne routant QUE M3 (un seul département dans le dict passé au
répartiteur — M4/M6 ne sont jamais chargés ni appelés ici, seuls leurs événements sont publiés
directement, comme s'ils l'avaient déjà fait). Vérifie les REÇUS DE M3 (`evenements_recus`,
filtrés `consommateur == "m03-estimation"`), jamais les comptes globaux du bus.

Base SQLite temporaire migrée, même patron que `test_devis_durable_stockage.py`.
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
from m3_estimation.outils import outils, registre_estime_vs_reel_production  # noqa: E402

from opsys import evenements, stockage  # noqa: E402
from opsys.departements import lire_manifeste  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402
from opsys.stockage.schema import EVENEMENTS_RECUS  # noqa: E402

_DEPARTEMENT_M3 = Path(__file__).resolve().parents[1]


def _departements_m3_seul():
    """Un seul département dans le dict : le répartiteur ne route donc qu'à M3, quels que soient
    les autres consommateurs déclarés ailleurs dans le dépôt réel."""
    return {"m03-estimation": lire_manifeste(_DEPARTEMENT_M3)}


def _recus_m3():
    """Les reçus DE M3 précisément (jamais un compte global du bus, cf. docstring du module)."""
    with stockage.transaction() as cnx:
        return list(
            cnx.execute(
                select(EVENEMENTS_RECUS).where(EVENEMENTS_RECUS.c.consommateur == "m03-estimation")
            ).mappings()
        )


def _charge_wct(**surcharges):
    charge = {
        "wct_id": "wct-e2e-001",
        "intervention_id": "int-e2e-001",
        "lead_id": "lead-e2e-001",
        "technicien_id": "tech-e2e-001",
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {},
        "duree_reelle_minutes": 120,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "deadbeef",
        "consommateurs_cibles": ["M3"],
        "devis_id": "M3-DEVIS-e2e-001",
        "statut": "completed_verified",
    }
    charge.update(surcharges)
    return charge


def _charge_variance(*, wct_id="wct-e2e-001", statut_variance="evaluee", **surcharges):
    charge = {
        "wct_id": wct_id,
        "intervention_id": "int-e2e-001",
        "chantier_id": "chantier-e2e-001",
        "statut_variance": statut_variance,
        "signal_critique": False if statut_variance == "evaluee" else None,
        "seuil_pourcentage": 10.0,
        "horodatage_completion": "2026-09-28T15:00:00-04:00",
        "lignes": (
            [
                {
                    "materiau": "gouttiere_alu",
                    "unite": "pi_lin",
                    "quantite_prevue": "30",
                    "quantite_reelle": "32",
                    "ecart_pourcentage": "0.0667",
                    "critique": False,
                }
            ]
            if statut_variance == "evaluee"
            else None
        ),
    }
    charge.update(surcharges)
    charge["evenement_id"] = f"m6-variance-{wct_id}-{statut_variance}"
    return charge


def _publier_wct(**surcharges):
    charge = _charge_wct(**surcharges)
    return evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id=charge["wct_id"])


def _publier_variance(**surcharges):
    charge = _charge_variance(**surcharges)
    return evenements.publier(
        "m6.variance_chantier", "m06-material-control", charge, evenement_id=charge["evenement_id"]
    )


def _creer_devis(devis_id="M3-DEVIS-e2e-001"):
    outil = next(o for o in outils() if o.nom == "m3_creer_devis")
    reponse = executer_atomique(
        outil,
        {
            "devis_id": devis_id,
            "lead_id": "lead-e2e-001",
            "chantier_id": None,
            "lignes": [
                {
                    "description": "Gouttière alu 5 po",
                    "quantite": "30",
                    "unite": "pi_lin",
                    "cout_unitaire": "10.00",
                    "reference_besoin_materiau": None,
                }
            ],
            "taux_marge": "0.20",
            "horodatage": "2026-09-01T09:00:00-04:00",
        },
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


# -- complétion puis variance evaluee -> enregistrement complet ----------------------------------
def test_completion_puis_variance_evaluee_enregistrement_complet(base_durable):
    _creer_devis()
    _publier_wct()
    _publier_variance()

    resume = evenements.repartir(_departements_m3_seul())
    assert resume["traites"] == 2
    assert resume["echecs"] == 0
    assert resume["quarantaines"] == 0

    recus = _recus_m3()
    assert len(recus) == 2
    assert all(r["statut"] == "traite" for r in recus)

    etat = estime_vs_reel._etat(registre_estime_vs_reel_production(), "wct-e2e-001")
    assert etat is not None
    assert etat["main_doeuvre"]["duree_reelle_minutes"] == Decimal("120")
    # "Complet" veut dire : les DEUX événements sont reçus et fusionnés dans une seule ligne —
    # pas que la comparaison main-d'œuvre aboutisse : AUCUNE source du dépôt (devis T2.3-a/b,
    # registre.py S008) ne porte encore duree_estimee_minutes aujourd'hui (cf. estime_vs_reel.py,
    # docstring) ; l'absence honnête, nommée, EST le comportement correct, pas un échec du test.
    assert etat["main_doeuvre"]["verdict"]["code"] == "REJ-ECART-ESTIMATION-ORIGINE-ABSENTE"
    assert etat["materiaux"] is not None
    assert etat["materiaux"]["lignes"][0]["materiau"] == "gouttiere_alu"


# -- variance declaration_absente, puis evaluee -> une seule ligne finale ------------------------
def test_variance_declaration_absente_puis_evaluee_une_seule_ligne_finale(base_durable):
    _creer_devis()
    _publier_wct()
    _publier_variance(statut_variance="declaration_absente")

    premier_resume = evenements.repartir(_departements_m3_seul())
    assert premier_resume["traites"] == 2  # WCT + variance declaration_absente (ignorée, mais traitée)

    etat_intermediaire = estime_vs_reel._etat(registre_estime_vs_reel_production(), "wct-e2e-001")
    assert etat_intermediaire is not None
    assert etat_intermediaire["materiaux"] is None, "declaration_absente ne renseigne jamais les matériaux"

    # M6 réévalue plus tard, la déclaration est enfin arrivée : un événement DISTINCT (evenement_id
    # différent, le statut fait partie de l'id) est publié.
    _publier_variance(statut_variance="evaluee")
    second_resume = evenements.repartir(_departements_m3_seul())
    assert second_resume["traites"] == 1

    recus = _recus_m3()
    assert len(recus) == 3  # wct + declaration_absente + evaluee : trois événements DISTINCTS reçus
    assert all(r["statut"] == "traite" for r in recus)

    etats = estime_vs_reel._etats_courants(registre_estime_vs_reel_production())
    assert len(etats) == 1, "un seul wct_id, donc une seule ligne finale malgré les deux variances"
    assert etats["wct-e2e-001"]["materiaux"] is not None


# -- complétion sans devis_id -> verdict ----------------------------------------------------------
def test_completion_sans_devis_id_verdict_nomme(base_durable):
    _publier_wct(devis_id=None)

    resume = evenements.repartir(_departements_m3_seul())
    assert resume["traites"] == 1
    assert resume["echecs"] == 0

    recus = _recus_m3()
    assert len(recus) == 1 and recus[0]["statut"] == "traite"

    etat = estime_vs_reel._etat(registre_estime_vs_reel_production(), "wct-e2e-001")
    assert etat["devis_id"] is None
    assert etat["main_doeuvre"]["verdict"]["code"] == "REJ-ECART-DEVIS-ID-ABSENT"


# -- relivraisons -> aucun doublon -----------------------------------------------------------------
def test_relivraisons_aucun_doublon(base_durable):
    _creer_devis()
    _publier_wct()
    _publier_variance()

    premier = evenements.repartir(_departements_m3_seul())
    assert premier["traites"] == 2
    recus_apres_premier = _recus_m3()
    assert len(recus_apres_premier) == 2

    # Rejeu de repartir() SANS aucun nouvel événement publié : les deux reçus sont déjà "traite",
    # donc plus aucun candidat — le répartiteur lui-même garantit qu'aucun consommateur n'est
    # réappelé pour un couple (événement, consommateur) déjà clos.
    second = evenements.repartir(_departements_m3_seul())
    assert second["traites"] == 0
    assert second["livres"] == 0

    recus_apres_second = _recus_m3()
    assert len(recus_apres_second) == 2, "aucun second reçu n'apparaît"
    assert recus_apres_second == recus_apres_premier

    etats = estime_vs_reel._etats_courants(registre_estime_vs_reel_production())
    assert len(etats) == 1, "toujours une seule ligne pour ce wct_id malgré le rejeu"


def test_relivraison_directe_de_la_meme_charge_wct_ne_duplique_pas(base_durable):
    """Défense en profondeur au niveau du CONSOMMATEUR lui-même (pas seulement du répartiteur) :
    republier deux fois la même charge de WCT sous deux evenement_id ARTIFICIELLEMENT identiques
    (même wct_id, ce que fait déjà M4 en pratique) est absorbé par publier() (no-op, bus), et même
    un appel direct au consommateur pour le même wct_id resterait idempotent côté registre M3
    (cf. test_estime_vs_reel.py::test_wct_idempotent_par_wct_id_ne_grossit_pas_le_registre)."""
    _creer_devis()
    ident_premier = _publier_wct()
    ident_second = _publier_wct()  # même wct_id -> même evenement_id -> no-op au niveau du bus
    assert ident_premier == ident_second

    resume = evenements.repartir(_departements_m3_seul())
    assert resume["traites"] == 1  # une seule ligne evenements_sortants existe pour ce wct_id

    etats = estime_vs_reel._etats_courants(registre_estime_vs_reel_production())
    assert len(etats) == 1
