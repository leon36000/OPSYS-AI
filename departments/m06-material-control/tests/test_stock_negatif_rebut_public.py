"""Public fictif : les attentes de stock négatif décrivent l'état sans attribuer une cause."""

from __future__ import annotations

import pytest
import yaml
from m6_material_control import outils as outils_mod

from opsys import evenements, stockage
from opsys.outils import executer_atomique

MATERIAU = "MAT-STOCK-NEGATIF-FICTIF"
CHANTIER = "CH-STOCK-NEGATIF-FICTIF"
WCT_ID = "WCT-STOCK-NEGATIF-FICTIF"
DATE_RECEPTION = "2026-11-03T10:00:00-04:00"
DATE_WCT = "2026-11-03T12:00:00-04:00"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    url = f"sqlite:///{tmp_path / 'm6-fictif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    manifeste = tmp_path / "department-fictif.yaml"
    monkeypatch.setattr(outils_mod, "_MANIFESTE", manifeste)
    outils = {outil.nom: outil for outil in outils_mod.outils()}
    yield tmp_path, outils
    stockage.liberer()


def _configurer_seuil(monde, articles):
    path, _ = monde
    manifeste = path / "department-fictif.yaml"
    manifeste.write_text(
        yaml.safe_dump({"configuration": {"reapprovisionnement": {"articles": articles}}}),
        encoding="utf-8",
    )
    manifeste.chmod(0o600)


def _publier_et_declarer(monde):
    _, outils = monde
    recu = executer_atomique(outils["m6_receptionner_commande"], {
        "bon_demande": {
            "po_id": "PO-STOCK-NEGATIF-FICTIF",
            "chantier_id": CHANTIER,
            "lignes_demandees": [{"materiau_id": MATERIAU, "quantite_demandee": 5.0}],
            "horodatage": DATE_RECEPTION,
        },
        "reception_po": {
            "po_id": "PO-STOCK-NEGATIF-FICTIF",
            "chantier_id": CHANTIER,
            "lignes_recues": [{"materiau_id": MATERIAU, "quantite_recue": 5.0}],
            "horodatage": DATE_RECEPTION,
        },
        "details_reception": [{
            "materiau_id": MATERIAU,
            "statut_ligne": "endommage",
            "photos": ["fichier:sha256:" + "cd" * 32],
        }],
        "lieu_livraison": {"type": "depot"},
    })
    assert recu["ok"] and recu["resultat"]["accepte"] is True, recu

    wct = {
        "wct_id": WCT_ID,
        "intervention_id": "INT-STOCK-NEGATIF-FICTIF",
        "lead_id": "LEAD-STOCK-NEGATIF-FICTIF",
        "technicien_id": "TECH-STOCK-NEGATIF-FICTIF",
        "horodatage_completion": DATE_WCT,
        "fix_gps_completion": {"latitude": 1.0, "longitude": 2.0},
        "duree_reelle_minutes": 30,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M6"],
        "devis_id": None,
    }
    with stockage.transaction():
        evenements.publier(
            "m4.travaux_termines",
            "m04-field-ops",
            {**wct, "statut": "completed_pending_review"},
            evenement_id=WCT_ID,
        )

    declaration = executer_atomique(outils["m6_declarer_materiaux_utilises"], {
        "wct_id": WCT_ID,
        "formulaire": {
            "wct_id": WCT_ID,
            "intervention_id": wct["intervention_id"],
            "chantier_id": CHANTIER,
            "lignes_materiaux": [{
                "type_ligne": "prevu",
                "materiau_id": MATERIAU,
                "quantite": 5.0,
                "unite": "boite",
                "quantite_estimee": 5.0,
            }],
        },
    })
    assert declaration["ok"] and declaration["resultat"]["accepte"] is True, declaration


def _attente(monde, type_):
    with stockage.transaction():
        attentes = outils_mod.attentes()
    return next(a for a in attentes if a["type"] == type_)


def _lire_disponibilite(monde):
    _, outils = monde
    response = executer_atomique(outils["m6_lire_disponibilite"], {"materiau_ids": [MATERIAU]})
    assert response["ok"] is True, response
    return response["resultat"]["resultat"]["articles"][0]


def test_attente_sans_seuil_ne_deduit_pas_une_reception_manquante(monde):
    _configurer_seuil(monde, {})
    _publier_et_declarer(monde)

    attente = _attente(monde, "stock_negatif")
    assert attente["resume"] == (
        f"Stock en main négatif : {MATERIAU} — -5.0 boite. "
        "Vérifier les mouvements de stock et les transferts d'emplacement avant toute décision de commande ; "
        "la cause n'est pas déterminée automatiquement."
    )
    assert "réception manquante" not in attente["resume"]
    assert "Saisir la réception manquante" not in attente["action_proposee"]
    assert "quantite_a_commander" not in attente
    assert "corrige pas le stock seul" in attente["action_proposee"]
    assert _attente(monde, "seuil_a_configurer")["type"] == "seuil_a_configurer"

    article = _lire_disponibilite(monde)
    assert article["stock_theorique"] == "0"
    assert article["hors_main"] == "5"
    assert article["en_main"] == article["disponible"] == "-5"


def test_attente_avec_seuil_distingue_stock_theorique_du_stock_en_main(monde):
    _configurer_seuil(monde, {
        MATERIAU: {"seuil_reapprovisionnement": 2, "quantite_cible": 4},
    })
    _publier_et_declarer(monde)

    attente = _attente(monde, "besoin_commande")
    assert attente["resume"] == (
        f"Stock en main négatif : {MATERIAU} — -5.0 boite. Seuil configuré : 2 boite. "
        "Vérifier les mouvements de stock et les transferts d'emplacement avant toute décision de commande ; "
        "aucune quantité à commander n'est calculée tant que le stock en main est négatif."
    )
    assert "stock théorique" not in attente["resume"]
    assert "réception manquante" not in attente["resume"]
    assert "quantite_a_commander" not in attente
    assert "Décider de commander" not in attente["action_proposee"]
    article = _lire_disponibilite(monde)
    assert article["stock_theorique"] == "0"
    assert article["en_main"] == article["disponible"] == "-5"
