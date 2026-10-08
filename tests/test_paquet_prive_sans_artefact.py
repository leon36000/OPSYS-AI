"""Lecture privée M10 : plafond réel de sortie, aucun artefact, rapports génériques préservés."""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from opsys import jetons
from opsys.capacites import Capacites
from opsys.stockage.schema import ARTEFACTS, META

CODE = "REJ-PAQUET-AFFAIRE-SORTIE-TROP-VOLUMINEUSE"
DETAIL = "le paquet dépasse la borne de sortie du contexte privé ; aucun détail partiel n'est transmis"
SOURCE = "m10_paquet_contexte_affaire"


def tables(session):
    with session() as cnx:
        return {t.name: tuple(sorted(repr(dict(row)) for row in cnx.execute(select(t)).mappings()))
                for t in META.sorted_tables}


def enveloppe(taille, prefixe):
    # Donnée synthétique explicitement fictive, pas une capture de paquet métier.
    r = {"ok": True, "resultat": {"fictif": True, "texte": prefixe}}
    manque = taille - len(json.dumps(r, ensure_ascii=False))
    assert manque >= 0
    r["resultat"]["texte"] += "x" * manque
    assert len(json.dumps(r, ensure_ascii=False)) == taille
    return r


@pytest.mark.parametrize("limite", [800, 6000])
@pytest.mark.parametrize("ecart", [-1, 0, 1])
@pytest.mark.parametrize("prefixe", ["fictif", "é😀", '"\\\n\t'])
def test_plafond_prive_mesure_json_entier_sans_transaction_artefact(
    departements_demo, session, monkeypatch, limite, ecart, prefixe,
):
    cap = Capacites(departements_demo, session, limite_sortie=limite)
    initial = tables(session)
    transaction = Mock(side_effect=AssertionError("transaction de fallback sur lecture privée"))
    tronquer = Mock(side_effect=AssertionError("artefact sur lecture privée"))
    monkeypatch.setattr(cap, "_cnx_factory", transaction)
    monkeypatch.setattr(jetons, "tronquer", tronquer)
    r = enveloppe(limite + ecart, prefixe)
    lu = cap._tronquer(r, SOURCE, departement="m10-memoire", origine="m01-front-office")
    if ecart <= 0:
        assert lu is r  # même objet, pas de projection ou perte de faits
    else:
        assert lu == {"ok": False, "erreur": CODE, "details": DETAIL}
        assert len(json.dumps(lu, ensure_ascii=False)) < limite
    transaction.assert_not_called()
    tronquer.assert_not_called()
    assert tables(session) == initial


@pytest.mark.parametrize("source", ["m9_gros_rapport", "m10_paquet_contexte_affaire_bis", "m10_lire_autre_rapport"])
def test_autres_sources_conservent_artefact_generique(departements_demo, session, source):
    cap = Capacites(departements_demo, session, limite_sortie=800)
    initial = tables(session)
    lu = cap._tronquer(enveloppe(801, "fictif"), source, departement="m09-demo", origine="m09-demo")
    assert lu["ok"] is True and lu["tronque"] is True and "opsys_lire_artefact" in lu["apercu"]
    final = tables(session)
    assert len(final[ARTEFACTS.name]) == len(initial[ARTEFACTS.name]) + 1
    assert {k:v for k,v in final.items() if k != ARTEFACTS.name} == {
        k:v for k,v in initial.items() if k != ARTEFACTS.name}


def test_sous_plafond_cap_preserve_meme_un_budget_faits_depasse(departements_demo, session):
    cap = Capacites(departements_demo, session, limite_sortie=6000)
    r = {"ok": True, "resultat": {"fictif": True, "budget_caracteres": 4000,
                                 "caracteres_utilises": 4100, "premier_fait": "x" * 4100}}
    assert len(json.dumps(r, ensure_ascii=False)) < 6000
    assert cap._tronquer(r, SOURCE, departement="m10-memoire", origine="m01-front-office") is r
