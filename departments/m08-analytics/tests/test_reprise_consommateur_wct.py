"""Panne tardive du vrai consommateur WCT de M8, puis reprise par le répartiteur natif.

Snapshot, fait `wct` et alerte `m8.alerte_proposee` sont réellement écrits dans le point de
sauvegarde du consommateur ; une panne dédiée levée APRÈS la publication doit tout annuler côté
M8, laisser le reçu en échec (backoff), puis une seule reprise écrit chaque effet une fois.
Manifeste M8 réel, catalogue réel, base SQLite temporaire migrée ; charges et seuil fictifs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from m8_analytics import outils as m8_outils
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

_DEP = "m08-analytics"
_WCT_ID = "wct-reprise-fictif"
_EVT_WCT = "evt-wct-reprise-fictif"


class PanneApresAlerte(RuntimeError):
    """Panne fictive, distincte de toute erreur du socle ou de la fixture."""


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def departements(tmp_path, monkeypatch):
    """M8 réel seul abonné ; seuil de durée posé par la fixture (le vrai manifeste n'en fixe aucun)."""
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": {
        "seuils_alerte": {"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50}},
    }}), encoding="utf-8")
    monkeypatch.setattr(m8_outils, "_MANIFESTE", manifeste)
    return {_DEP: charger_departements(Path(__file__).resolve().parents[2])[_DEP]}


def _wct():
    return {
        "wct_id": _WCT_ID, "intervention_id": "int-reprise-fictif", "lead_id": "lead-reprise-fictif",
        "technicien_id": "tech-reprise-fictif", "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5}, "duree_reelle_minutes": 120,
        "ecart_signale": False, "revue_id": None, "hash_maillon": "b" * 64, "consommateurs_cibles": ["M8"],
        "devis_id": "devis-reprise-fictif", "statut": "completed_verified",
    }


def _devis():
    return {
        "devis_id": "devis-reprise-fictif", "lead_id": "lead-reprise-fictif", "chantier_id": None,
        "lignes": [{
            "reference_ligne": "devis-reprise-fictif-L0", "description": "Gouttières (fictif)", "quantite": "40",
            "unite": "pi", "prix_unitaire": "15.00", "prix_ligne": "600.00", "reference_besoin_materiau": None,
        }],
        "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25",
        "duree_estimee_minutes": "60", "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
    }


def _etat_m8():
    """Effets M8 seulement : snapshots, faits, outbox. Les reçus du répartiteur sont lus à part."""
    with stockage.transaction() as cnx:
        sortants = cnx.execute(
            select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.type_evenement,
                   EVENEMENTS_SORTANTS.c.charge).order_by(EVENEMENTS_SORTANTS.c.evenement_id)
        ).all()
        return {
            "snapshots": list(stockage.maillons(_DEP, "snapshots")),
            "faits": list(stockage.maillons(_DEP, "faits_chantier")),
            "sortants": [tuple(ligne) for ligne in sortants],
        }


def _recu_wct():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(
            EVENEMENTS_RECUS.c.consommateur, EVENEMENTS_RECUS.c.statut, EVENEMENTS_RECUS.c.tentatives,
            EVENEMENTS_RECUS.c.prochaine_tentative, EVENEMENTS_RECUS.c.derniere_erreur,
        ).where(EVENEMENTS_RECUS.c.evenement_id == _EVT_WCT)).all()
    return [tuple(ligne) for ligne in lignes]


def _ids_alertes(etat):
    return sorted(ident for ident, type_evenement, _ in etat["sortants"] if type_evenement == "m8.alerte_proposee")


def test_panne_apres_alerte_wct_annule_les_effets_m8_puis_une_seule_reprise(base_durable, departements):
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis(), evenement_id="evt-devis-reprise-fictif")
    assert evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")["traites"] == 1
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct(), evenement_id=_EVT_WCT)
    avant = _etat_m8()
    assert avant["snapshots"] == [] and [f["type_entree"] for f in avant["faits"]] == ["devis"]
    assert _ids_alertes(avant) == []

    originale = m8_outils._publier_charges_mesure
    temoins = []

    def publier_puis_panne(charges):
        publiees = originale(charges)
        cnx = stockage.connexion_courante()
        assert cnx is not None
        dans_outbox = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.type_evenement)
                                  .where(EVENEMENTS_SORTANTS.c.type_evenement == "m8.alerte_proposee")).all()
        temoins.append({
            "snapshots": [m["valeurs"].get("m4_wct_id") for m in stockage.maillons(_DEP, "snapshots")],
            "faits_wct": [f["wct_id"] for f in stockage.maillons(_DEP, "faits_chantier") if f["type_entree"] == "wct"],
            "outbox": sorted(ligne.evenement_id for ligne in dans_outbox),
            "publiees": sorted(p["evenement_id"] for p in publiees),
            "types": sorted(p["type_alerte"] for p in publiees),
        })
        raise PanneApresAlerte("panne fictive après insertion réelle de l'alerte")

    m8_outils._publier_charges_mesure = publier_puis_panne
    try:
        echec = evenements.repartir(departements, maintenant="2026-09-28T18:01:00+00:00")
    finally:
        m8_outils._publier_charges_mesure = originale
    assert m8_outils._publier_charges_mesure is originale
    assert stockage.connexion_courante() is None and stockage.moteur().pool.checkedout() == 0

    # Le point d'effet a été atteint : les trois écritures existaient dans le point de sauvegarde.
    assert len(temoins) == 1
    temoin = temoins[0]
    assert temoin["snapshots"] == [_WCT_ID] and temoin["faits_wct"] == [_WCT_ID]
    assert "MESURE-SEUIL-FRANCHI" in temoin["types"]
    assert temoin["outbox"] == temoin["publiees"] != []
    assert echec["echecs"] == 1 and echec["traites"] == 0 and echec["quarantaines"] == 0

    stockage.liberer()  # nouvelle connexion : rien de la tentative n'a survécu côté M8
    assert _etat_m8() == avant
    # Le répartiteur, lui, garde légitimement l'échec, l'erreur exacte et l'échéance de réessai.
    assert _recu_wct() == [(_DEP, "echec", 1, "2026-09-28T18:01:02+00:00",
                            "PanneApresAlerte: panne fictive après insertion réelle de l'alerte")]

    assert evenements.repartir(departements, maintenant="2026-09-28T18:01:01+00:00")["livres"] == 0  # backoff
    reprise = evenements.repartir(departements, maintenant="2026-09-28T18:01:03+00:00")
    assert reprise["traites"] == 1 and reprise["echecs"] == 0
    stockage.liberer()
    apres = _etat_m8()
    assert [m["valeurs"].get("m4_wct_id") for m in apres["snapshots"]] == [_WCT_ID]
    assert [(f["type_entree"], f.get("wct_id")) for f in apres["faits"]] == [("devis", None), ("wct", _WCT_ID)]
    assert _ids_alertes(apres) == temoin["publiees"]  # mêmes identifiants déterministes, une fois chacun
    assert [r[:3] + (r[4],) for r in _recu_wct()] == [(_DEP, "traite", 2, None)]

    # Réouverture puis rejeu : ni le répartiteur, ni une relivraison du même fait ne doublent rien.
    stockage.liberer()
    assert evenements.repartir(departements, maintenant="2026-09-28T18:05:00+00:00")["livres"] == 0
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct(), evenement_id=_EVT_WCT)
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct(), evenement_id="evt-wct-reprise-relivre")
    relivraison = evenements.repartir(departements, maintenant="2026-09-28T18:06:00+00:00")
    assert relivraison["traites"] == 1 and relivraison["echecs"] == 0
    stockage.liberer()
    final = _etat_m8()
    assert final["snapshots"] == apres["snapshots"] and final["faits"] == apres["faits"]
    assert _ids_alertes(final) == _ids_alertes(apres)
