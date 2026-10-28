"""Rejeu fictif du WCT par le répartiteur et la base SQLite réels."""
import importlib.util
from pathlib import Path

import pytest

from opsys import evenements, stockage

spec = importlib.util.spec_from_file_location(
    "fixtures_evenements_m5", Path(__file__).with_name("test_evenements_m5.py")
)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
base_durable = fixtures.base_durable
D = "m05-financecore"


def _livrer(charge, ident, instant):
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id=ident)
    return evenements.repartir(fixtures._deps_bus(), maintenant=instant)


def test_rejeu_identique_et_divergent_sans_effet_de_bord(base_durable):
    charge = fixtures._wct(wct_id="FICTIF-WCT", devis_id=None)
    assert _livrer(charge, "FICTIF-EVT-1", "2026-09-25T17:00:00-04:00")["traites"] == 1
    avant = list(stockage.maillons(D, "wct_recus"))
    assert len(avant) == 1
    assert _livrer(charge, "FICTIF-EVT-2", "2026-09-25T17:00:01-04:00")["traites"] == 1
    assert list(stockage.maillons(D, "wct_recus")) == avant
    divergente = {**charge, "technicien_id": "FICTIF-AUTRE"}
    resultat = _livrer(divergente, "FICTIF-EVT-3", "2026-09-25T17:00:02-04:00")
    assert resultat["echecs"] == 1
    assert list(stockage.maillons(D, "wct_recus")) == avant
    assert list(stockage.maillons(D, "factures")) == []


def test_ancien_recu_sans_empreinte_ne_peut_pas_certifier_un_rejeu(base_durable):
    charge = fixtures._wct(wct_id="FICTIF-ANCIEN", devis_id=None)
    with stockage.transaction():
        stockage.maillons(D, "wct_recus").append({
            "wct_id": charge["wct_id"], "intervention_id": charge["intervention_id"],
            "devis_id": None, "horodatage_completion": charge["horodatage_completion"],
            "duree_reelle_minutes": charge["duree_reelle_minutes"],
        })
    resultat = _livrer(charge, "FICTIF-EVT-ANCIEN", "2026-09-25T17:00:00-04:00")
    assert resultat["echecs"] == 1
    assert len(stockage.maillons(D, "wct_recus")) == 1


def test_concurrence_rejoue_sans_double_enregistrement(base_durable):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    charge = fixtures._wct(wct_id="FICTIF-CONCURRENT", devis_id=None)
    barriere = Barrier(2)

    def reception():
        barriere.wait(timeout=5)
        with stockage.transaction():
            return fixtures.outils_mod._recevoir_travaux_termines(charge)

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = list(pool.map(lambda _: reception(), range(2)))
    assert all(r["traite"] for r in resultats)
    assert len(list(stockage.maillons(D, "wct_recus"))) == 1


def test_ecriture_concurrente_annule_toute_la_transaction(base_durable, monkeypatch):
    from opsys.stockage.maillons import EcritureConcurrente, MaillonsDurables

    charge = fixtures._wct(wct_id="FICTIF-ROLLBACK", devis_id=None)
    originale = MaillonsDurables.append

    def interposer(self, maillon, *, rang_attendu=None):
        if (self.departement, self.registre) == (D, "wct_recus"):
            originale(self, {"wct_id": "FICTIF-INTERPOSE"})
        return originale(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", interposer)
    with pytest.raises(EcritureConcurrente), stockage.transaction():
        fixtures.outils_mod._recevoir_travaux_termines(charge)
    assert list(stockage.maillons(D, "wct_recus")) == []


def test_recu_historique_traite_ne_prouve_pas_la_charge_complete(base_durable, monkeypatch):
    """Un ancien consommateur peut avoir accepté deux charges distinctes pour le même WCT."""
    from m5_financecore import wct_recus

    from opsys.evenements.bus import copier_publications_et_recus

    originale = fixtures._wct(wct_id="FICTIF-HISTORIQUE", devis_id=None)
    divergente = {**originale, "technicien_id": "FICTIF-AUTRE"}

    # Comportement du consommateur historique : premier WCT conservé, les suivants ignorés.
    def ancienne_reception(charge):
        registre = stockage.maillons(D, "wct_recus")
        if wct_recus.pour_wct_id(charge["wct_id"], registre) is None:
            registre.append(wct_recus.construire(
                charge["wct_id"], charge["intervention_id"], charge.get("devis_id"),
                charge["horodatage_completion"], charge.get("duree_reelle_minutes"),
            ))
        return {"traite": True, "wct_id": charge["wct_id"], "statut": "wct_sans_devis_id"}

    with monkeypatch.context() as m:
        m.setattr(fixtures.outils_mod, "_recevoir_travaux_termines", ancienne_reception)
        assert _livrer(divergente, "FICTIF-EVT-ANTERIEUR", "2026-09-25T17:00:00-04:00")["traites"] == 1
        assert _livrer(originale, originale["wct_id"], "2026-09-25T17:00:01-04:00")["traites"] == 1

    avec_source = list(stockage.maillons(D, "wct_recus"))
    assert len(avec_source) == 1 and "empreinte_charge" not in avec_source[0]
    assert all(avec_source[0][cle] == originale.get(cle) for cle in avec_source[0])
    with stockage.transaction() as cnx:
        copie = copier_publications_et_recus(
            cnx, type_evenement="m4.travaux_termines", consommateur=D,
        )
    assert any(p.evenement_id == originale["wct_id"] and p.producteur == "m04-field-ops"
               and p.charge == originale for p in copie.publications)
    assert any(r.evenement_id == originale["wct_id"] and r.statut == "traite" for r in copie.recus)
    # Le reçu canonique n'établit pas quel contenu complet a créé l'ancien maillon.
    assert _livrer(originale, "FICTIF-EVT-REJEU", "2026-09-25T17:00:02-04:00")["echecs"] == 1
    assert list(stockage.maillons(D, "wct_recus")) == avec_source
