"""M10 consomme `m4.travaux_termines` (ADR-0009 §3, PLAN T1.2-c partie 1) : mémorise le WCT au
registre Événements par la logique EXISTANTE (`memoriser_wct`), une seule fois par événement
(idempotent — le répartiteur ne rappelle jamais un consommateur déjà traité pour le même
evenement_id), et met en quarantaine sans écriture un WCT que `wct.valider_wct` refuse (contrat
figé, « M10 » absent de `consommateurs_cibles`).

Utilise le VRAI bus (`evenements.repartir` + `opsys.departements.charger_departements()`, sur les
manifestes réels de `departments/` — donc M2, qui consomme aussi ce type depuis PLAN T1.2-c, y est
également livré pour le même événement). Les assertions ci-dessous ne portent jamais sur le
résumé AGRÉGÉ de `repartir` (qui mélangerait le sort de M2 — ce fichier ne fait jamais exister le
lead_id fictif côté M2), seulement sur l'état PROPRE à m10-memoire : le registre Événements et
`etat()` filtré par `consommateur`. Sur une base SQLite temporaire migrée (patron de
`test_registre_durable.py::base_sqlite`). Les WCT publiés sont des événements de test fictifs.
"""

from __future__ import annotations

import datetime as dt

import pytest

from opsys import evenements, stockage
from opsys.departements import charger_departements


def _wct(wct_id: str, **overrides) -> dict:
    base = {
        "wct_id": wct_id,
        "intervention_id": f"int-{wct_id}",
        "lead_id": f"lead-{wct_id}",
        "technicien_id": "tech-fictif-1",
        "horodatage_completion": "2026-09-15T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 90,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": f"hash-{wct_id}",
        "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"],
        "devis_id": f"devis-{wct_id}",
        "statut": "completed_verified",
    }
    base.update(overrides)
    return base


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée (patron de test_registre_durable.py::base_sqlite)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _registre_evenements():
    return stockage.maillons("m10-memoire", "evenements")


def _deps_bus():
    """Seul M10 reçoit les événements de ces tests : les comptes de `repartir()` sont globaux, et
    chaque autre consommateur de `m4.travaux_termines` (M2, M6, M7, M8…) ou de ce qu'il publie en
    retour (`m6.variance_chantier` vers M4) les changerait."""
    return {"m10-memoire": charger_departements()["m10-memoire"]}


def _quarantaine_m10():
    return [ligne for ligne in evenements.etat()["quarantaine"] if ligne["consommateur"] == "m10-memoire"]


class TestManifeste:
    def test_m10_declare_consommer_travaux_termines(self):
        dep = charger_departements()["m10-memoire"]
        assert dep.evenements_consomme == ("m4.travaux_termines",)
        assert "m4.travaux_termines" in dep.charger_consommateurs()


class TestNominal:
    def test_wct_memorise_une_seule_fois(self, base_durable):
        wct_id = "WCT-M10-NOM-1"
        charge = _wct(wct_id)
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

        deps = _deps_bus()
        evenements.repartir(deps, maintenant="2026-09-15T14:05:00-04:00")

        maillons_wct = [m for m in _registre_evenements() if m.get("wct_id") == wct_id]
        assert len(maillons_wct) == 1, "le WCT est mémorisé exactement une fois"
        maillon = maillons_wct[0]
        assert maillon["type_entree"] == "evenement_memorise"
        assert maillon["horodatage"] == charge["horodatage_completion"]
        # Les 12 champs exacts du contrat figé (contrats.CHAMPS_WCT) sont conservés tels quels ;
        # `statut` (ajouté au catalogue par T1.1-b) et les champs optionnels réservés à M7, hors
        # de ce contrat, ne sont jamais écrits ici (wct.valider_wct les aurait refusés).
        assert maillon["lead_id"] == charge["lead_id"]
        assert maillon["intervention_id"] == charge["intervention_id"]
        assert maillon["devis_id"] == charge["devis_id"]
        assert "statut" not in maillon
        assert _quarantaine_m10() == []

        # Redélivraison (même événement, même instant : rien de neuf n'est dû — ni pour M10 déjà
        # traité, ni pour M2 dont le backoff n'a pas encore expiré) : idempotent, sans effet.
        resume2 = evenements.repartir(deps, maintenant="2026-09-15T14:05:00-04:00")
        assert resume2 == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
        assert len([m for m in _registre_evenements() if m.get("wct_id") == wct_id]) == 1


class TestWctRefuse:
    def test_m10_absent_de_consommateurs_cibles_va_en_quarantaine_sans_ecriture(self, base_durable):
        wct_id = "WCT-M10-REFUS-1"
        charge = _wct(wct_id, consommateurs_cibles=["M6", "M5"])  # « M10 » absent, à dessein
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

        taille_avant = len(_registre_evenements())
        deps = _deps_bus()
        t = dt.datetime(2026, 9, 15, 14, 5, tzinfo=dt.UTC)
        for _ in range(5):
            evenements.repartir(deps, maintenant=t.isoformat())
            t += dt.timedelta(seconds=100)

        assert len(_registre_evenements()) == taille_avant, "un WCT refusé n'écrit rien"
        lignes = _quarantaine_m10()
        assert len(lignes) == 1
        assert lignes[0]["tentatives"] == 5
        assert "WctRefuse" in lignes[0]["derniere_erreur"]
