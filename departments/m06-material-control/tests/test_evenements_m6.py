"""M6 côté bus d'événements (ADR-0009 §3, PLAN T1.2-b, points 2 et 3) :

- `_seuil_variance_chantier()` lit `department.yaml/configuration`, fail-closed si absent
  ou invalide.
- `consommateurs()["m4.travaux_termines"]` (`_recevoir_travaux_termines`) garde le prévu
  (`m6_enregistrer_besoins_prevus`) contre le réel déclaré (`m6_declarer_materiaux_utilises`)
  et publie `m6.variance_chantier` avec le bon `statut_variance`/`signal_critique`/
  `chantier_id`, dans les quatre cas du PLAN (évalué sans signal, écart critique, prévu
  absent, déclaration absente) plus le fail-closed de configuration (seuil absent).

Base SQLite temporaire migrée (ADR-0009) : ces fonctions touchent TOUJOURS le registre
durable (`stockage.maillons` direct), jamais le mode `registre_historique` en mémoire de
`outils.py` (réservé aux outils d'agent testés hors transaction, `test_outils_agent.py`).
"""

from __future__ import annotations

import pytest
import m6_material_control.outils as outils_mod
from m6_material_control.outils import consommateurs, outils
from sqlalchemy import func, select

from opsys import stockage
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _compte_sortants(type_evenement=None):
    requete = select(func.count()).select_from(EVENEMENTS_SORTANTS)
    if type_evenement is not None:
        requete = requete.where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
    with stockage.transaction() as cnx:
        return cnx.execute(requete).scalar_one()


def _charges_publiees(type_evenement="m6.variance_chantier"):
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS)
            .where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
            .order_by(EVENEMENTS_SORTANTS.c.cree_le)
        ).mappings().all()
    return [codec.decoder(ligne["charge"]) for ligne in lignes]


def _wct_charge(wct_id="wct-1", intervention_id="int-1", devis_id="DEVIS-1", **overrides):
    base = {
        "wct_id": wct_id, "intervention_id": intervention_id, "lead_id": "lead-1",
        "technicien_id": "t1", "horodatage_completion": "2026-01-01T10:00:00-05:00",
        "fix_gps_completion": {"latitude": 45.5, "longitude": -73.5},
        "duree_reelle_minutes": 120, "ecart_signale": True, "revue_id": None,
        "hash_maillon": "a" * 16, "consommateurs_cibles": ["M6"], "devis_id": devis_id,
        "statut": "completed_pending_review",
    }
    base.update(overrides)
    return base


def _wct_pour_m6(**overrides):
    """WctRecu (contrats.CHAMPS_WCT, 12 clés) : le WCT de M4 SANS son champ `statut`, que
    seul le catalogue d'événement m4.travaux_termines porte."""
    wct = _wct_charge(**overrides)
    return {k: v for k, v in wct.items() if k != "statut"}


def _enregistrer_besoins(m6, chantier_id, devis_id, quantite_estimee=10.0, materiau_id="MAT-1"):
    reponse = executer_atomique(m6["m6_enregistrer_besoins_prevus"], {
        "chantier_id": chantier_id, "devis_id": devis_id,
        "lignes": [{"materiau_id": materiau_id, "quantite_estimee": quantite_estimee, "unite": "boite"}],
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def _receptionner(m6, chantier_id, materiau_id, quantite, po_id):
    """Préalable de `_dernier_cout_unitaire_connu` (materiel.py) : une déclaration de
    matériaux utilisés exige un coût unitaire résolu depuis une RECEPTION antérieure pour
    le même couple (chantier_id, materiau_id) — REJ-COUT-UNITAIRE-INTROUVABLE sinon."""
    reponse = executer_atomique(m6["m6_receptionner_commande"], {
        "bon_demande": {
            "po_id": po_id, "chantier_id": chantier_id,
            "lignes_demandees": [{"materiau_id": materiau_id, "quantite_demandee": quantite}],
            "horodatage": "2025-12-01T00:00:00Z",
        },
        "reception_po": {
            "po_id": po_id, "chantier_id": chantier_id,
            "lignes_recues": [{"materiau_id": materiau_id, "quantite_recue": quantite}],
            "horodatage": "2025-12-02T00:00:00Z",
        },
        "catalogue_materiaux": {
            "version": "v1", "unite_monetaire": "CAD",
            "postes": {materiau_id: {"cout_unitaire": 5.0, "libelle": materiau_id}},
        },
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def _declarer_materiaux(m6, wct_id, intervention_id, chantier_id, quantite, materiau_id="MAT-1"):
    _receptionner(m6, chantier_id, materiau_id, max(quantite, 1.0) * 2, po_id=f"PO-{wct_id}")
    reponse = executer_atomique(m6["m6_declarer_materiaux_utilises"], {
        "wct": _wct_pour_m6(wct_id=wct_id, intervention_id=intervention_id),
        "formulaire": {
            "wct_id": wct_id, "intervention_id": intervention_id, "chantier_id": chantier_id,
            "lignes_materiaux": [{
                "type_ligne": "prevu", "materiau_id": materiau_id, "quantite": quantite,
                "unite": "boite", "quantite_estimee": quantite,
            }],
        },
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


# -- déclaration du module ---------------------------------------------------------------------
def test_declaration_module_consommateurs():
    assert set(consommateurs()) == {"m4.travaux_termines"}


# -- seuil de configuration (fail-closed, PLAN point 3) ------------------------------------------
def test_seuil_variance_chantier_reel_est_configure():
    assert outils_mod._seuil_variance_chantier() == 0.30


def test_seuil_variance_chantier_absent_rend_none(tmp_path, monkeypatch):
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text("schema: opsys.departement/v1\n", encoding="utf-8")
    monkeypatch.setattr(outils_mod, "_MANIFESTE", manifeste)
    assert outils_mod._seuil_variance_chantier() is None


def test_seuil_variance_chantier_invalide_rend_none(tmp_path, monkeypatch):
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(
        "schema: opsys.departement/v1\nconfiguration:\n  seuil_variance_chantier_pourcentage: -1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(outils_mod, "_MANIFESTE", manifeste)
    assert outils_mod._seuil_variance_chantier() is None


# -- _recevoir_travaux_termines : les cas du PLAN T1.2-b, point 3 -------------------------------
def test_evaluee_sans_ecart_ne_signale_rien(base_durable):
    m6 = {o.nom: o for o in outils()}
    _enregistrer_besoins(m6, "C1", "DEVIS-1", quantite_estimee=10.0)
    _declarer_materiaux(m6, "wct-1", "int-1", "C1", quantite=10.0)

    with stockage.transaction():
        resultat = consommateurs()["m4.travaux_termines"](_wct_charge())
    assert resultat == {"traite": True, "statut_variance": "evaluee"}

    charge = _charges_publiees()[0]
    assert charge["wct_id"] == "wct-1"
    assert charge["intervention_id"] == "int-1"
    assert charge["chantier_id"] == "C1"
    assert charge["statut_variance"] == "evaluee"
    assert charge["signal_critique"] is False
    assert charge["seuil_pourcentage"] == 0.30
    assert charge["horodatage_completion"] == "2026-01-01T10:00:00-05:00"
    assert charge["evenement_id"] == "m6-variance-wct-1"


def test_evaluee_avec_ecart_quarante_pourcent_signale_critique(base_durable):
    m6 = {o.nom: o for o in outils()}
    _enregistrer_besoins(m6, "C1", "DEVIS-1", quantite_estimee=10.0)
    _declarer_materiaux(m6, "wct-1", "int-1", "C1", quantite=14.0)  # +40 %, seuil configuré 0.30

    with stockage.transaction():
        consommateurs()["m4.travaux_termines"](_wct_charge())

    charge = _charges_publiees()[0]
    assert charge["statut_variance"] == "evaluee"
    assert charge["signal_critique"] is True


def test_prevu_absent_chantier_id_resolu_depuis_la_declaration(base_durable):
    m6 = {o.nom: o for o in outils()}
    # Aucun m6_enregistrer_besoins_prevus pour DEVIS-1 : le prévu manque.
    _declarer_materiaux(m6, "wct-1", "int-1", "C1", quantite=5.0)

    with stockage.transaction():
        resultat = consommateurs()["m4.travaux_termines"](_wct_charge())
    assert resultat["statut_variance"] == "prevu_absent"

    charge = _charges_publiees()[0]
    assert charge["statut_variance"] == "prevu_absent"
    assert charge["signal_critique"] is None
    assert charge["chantier_id"] == "C1"  # connu quand même, via la déclaration déjà soumise
    assert charge["seuil_pourcentage"] == 0.30


def test_declaration_absente_chantier_id_resolu_depuis_le_prevu(base_durable):
    m6 = {o.nom: o for o in outils()}
    _enregistrer_besoins(m6, "C1", "DEVIS-1", quantite_estimee=10.0)
    # Aucun m6_declarer_materiaux_utilises pour wct-1 : la déclaration manque.

    with stockage.transaction():
        resultat = consommateurs()["m4.travaux_termines"](_wct_charge())
    assert resultat["statut_variance"] == "declaration_absente"

    charge = _charges_publiees()[0]
    assert charge["statut_variance"] == "declaration_absente"
    assert charge["signal_critique"] is None
    assert charge["chantier_id"] == "C1"  # connu quand même, via le prévu enregistré


def test_prevu_et_declaration_absents_chantier_id_null_jamais_devine(base_durable):
    m6 = {o.nom: o for o in outils()}
    with stockage.transaction():
        consommateurs()["m4.travaux_termines"](_wct_charge())

    charge = _charges_publiees()[0]
    assert charge["statut_variance"] == "prevu_absent"
    assert charge["chantier_id"] is None


def test_seuil_absent_fail_closed_avant_toute_autre_lecture(base_durable, monkeypatch):
    m6 = {o.nom: o for o in outils()}
    _enregistrer_besoins(m6, "C1", "DEVIS-1", quantite_estimee=10.0)
    _declarer_materiaux(m6, "wct-1", "int-1", "C1", quantite=10.0)
    monkeypatch.setattr(outils_mod, "_seuil_variance_chantier", lambda: None)

    with stockage.transaction():
        resultat = consommateurs()["m4.travaux_termines"](_wct_charge())
    assert resultat["statut_variance"] == "seuil_absent"

    charge = _charges_publiees()[0]
    assert charge["statut_variance"] == "seuil_absent"
    assert charge["signal_critique"] is None
    assert charge["seuil_pourcentage"] is None
    assert charge["chantier_id"] == "C1"  # le prévu ET la déclaration existaient, juste le seuil manque


def test_idempotent_evenement_id_deterministe_une_seule_ligne(base_durable):
    m6 = {o.nom: o for o in outils()}
    _enregistrer_besoins(m6, "C1", "DEVIS-1", quantite_estimee=10.0)
    _declarer_materiaux(m6, "wct-1", "int-1", "C1", quantite=10.0)

    with stockage.transaction():
        consommateurs()["m4.travaux_termines"](_wct_charge())
    with stockage.transaction():
        consommateurs()["m4.travaux_termines"](_wct_charge())

    assert _compte_sortants("m6.variance_chantier") == 1
