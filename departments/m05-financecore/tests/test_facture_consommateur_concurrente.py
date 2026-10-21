import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import registre
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.outils import Autonomie, executer_atomique
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fixtures = charger("canon_m5_evenements", Path(__file__).with_name("test_evenements_m5.py"))


def _arguments(montant, source):
    return {
        "facture_id": source,
        "chantier_id": "FICTIF-CHANT-" + source,
        "devis_id": "FICTIF-DEVIS-" + source,
        "client_id": "FICTIF-CLIENT",
        "lignes": [
            {
                "description": "FICTIF",
                "quantite": "1",
                "unite": "forfait",
                "prix_unitaire": montant,
                "reference_ligne_devis": "FICTIF-L1",
            }
        ],
        "horodatage": "2026-08-03T12:00:00+00:00",
    }


base_durable = fixtures.base_durable
D = "m05-financecore"


def journal():
    return registre.Registre(stockage.maillons(D, "factures"))


@pytest.mark.parametrize("devis_premier", [True, False])
def test_public_consumer_refuse_facture_perimee(base_durable, monkeypatch, devis_premier):
    deps = fixtures._deps_bus()
    outil = next(o for o in deps[D].charger_outils() if o.nom == "m5_creer_facture_brouillon")
    assert outil.autonomie == Autonomie.T1
    assert executer_atomique(outil, _arguments("100.00", "FICTIF-SEED"))["resultat"]["accepte"]
    pieces = [
        ("m3.devis_accepte", "m03-estimation", fixtures._devis_accepte()),
        ("m4.travaux_termines", "m04-field-ops", fixtures._wct()),
    ]
    if not devis_premier:
        pieces.reverse()
    for i, (typ, producteur, charge) in enumerate(pieces):
        evenements.publier(typ, producteur, charge, evenement_id=f"FICTIF-PIECE-{i}")
        if i == 0:
            r = evenements.repartir(deps, maintenant="2026-09-25T17:00:00-04:00")
            assert r["echecs"] == 0 and journal().taille() == 1
    avant_traces = list(stockage.maillons(D, fixtures.outils_mod._NOM_REGISTRE_RENTABILITE))
    avant_publications = _publications_rentabilite()
    originale = MaillonsDurables.append
    observations = []

    def interposer(self, maillon, *, rang_attendu=None):
        if (self.departement, self.registre) == (D, "factures") and maillon.get("facture_id") == "fac-DEVIS-1":
            b = executer_atomique(outil, _arguments("300.00", "FICTIF-B"))
            assert b["ok"] and b["resultat"]["accepte"]
            assert journal().valider_chaine() == (True, "")
            observations.append(len(self))
        return originale(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", interposer)
    resume = evenements.repartir(deps, maintenant="2026-09-25T17:00:00-04:00")
    stockage.liberer()
    maillons = journal().lire()
    valide = journal().valider_chaine()[0]

    assert observations == [2]
    assert resume["echecs"] == 1 and valide, {"resume": resume, "factures": maillons}

    assert resume["traites"] == 0 and resume["quarantaines"] == 0
    assert list(stockage.maillons(D, fixtures.outils_mod._NOM_REGISTRE_RENTABILITE)) == avant_traces
    assert _publications_rentabilite() == avant_publications
    assert [m["facture_id"] for m in maillons] == ["FICTIF-SEED"]  # B rolls back with A in SQLite.
    assert _recu("FICTIF-PIECE-0")["statut"] == "traite"
    second = _recu("FICTIF-PIECE-1")
    assert second["statut"] == "echec" and second["tentatives"] == 1
    assert second["derniere_erreur"].startswith("EcritureConcurrente:")
    premier_registre = "devis_recus" if devis_premier else "wct_recus"
    second_registre = "wct_recus" if devis_premier else "devis_recus"
    assert len(stockage.maillons(D, premier_registre)) == 1 and len(stockage.maillons(D, second_registre)) == 0
    for i, (typ, _, charge) in enumerate(pieces):
        assert evenements.charge_publiee(typ, f"FICTIF-PIECE-{i}") == charge
    monkeypatch.setattr(MaillonsDurables, "append", originale)
    assert evenements.repartir(deps, maintenant="2026-09-25T17:00:01-04:00")["livres"] == 0
    r = evenements.repartir(deps, maintenant="2026-09-25T17:00:03-04:00")
    assert r["traites"] == 1 and r["echecs"] == 0
    stockage.liberer()
    fin = journal().lire()
    assert fin[:1] == maillons and [m["facture_id"] for m in fin] == ["FICTIF-SEED", "fac-DEVIS-1"]
    assert journal().valider_chaine() == (True, "")
    assert fin[-1]["montant_avant_taxes"] == Decimal("600.00")
    assert fin[-1]["montant_apres_taxes"] == Decimal("689.85")
    assert len(stockage.maillons(D, "devis_recus")) == len(stockage.maillons(D, "wct_recus")) == 1
    traces = list(stockage.maillons(D, fixtures.outils_mod._NOM_REGISTRE_RENTABILITE))
    assert len(traces) == 1 and traces[0]["verdict"] == "PARTIELLE"
    assert traces[0]["rentabilite"]["cout_reel"]["complet"] is False
    publications = _publications_rentabilite()
    assert len(publications) == 1
    assert _recu("FICTIF-PIECE-1")["statut"] == "traite" and _recu("FICTIF-PIECE-1")["tentatives"] == 2
    assert evenements.repartir(deps, maintenant="2026-09-25T17:00:04-04:00")["livres"] == 0
    assert list(stockage.maillons(D, fixtures.outils_mod._NOM_REGISTRE_RENTABILITE)) == traces
    assert _publications_rentabilite() == publications


def _recu(ident):
    with stockage.transaction() as cnx:
        return dict(
            cnx.execute(
                select(EVENEMENTS_RECUS).where(
                    (EVENEMENTS_RECUS.c.evenement_id == ident) & (EVENEMENTS_RECUS.c.consommateur == D)
                )
            )
            .mappings()
            .one()
        )


def _publications_rentabilite():
    with stockage.transaction() as cnx:
        return [
            dict(ligne)
            for ligne in cnx.execute(
                select(EVENEMENTS_SORTANTS).where(
                    (EVENEMENTS_SORTANTS.c.producteur == D)
                    & (EVENEMENTS_SORTANTS.c.type_evenement == fixtures.outils_mod.cout_reel.TYPE_EVENEMENT_RENTABILITE)
                )
            ).mappings()
        ]
