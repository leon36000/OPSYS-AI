"""Fictif: vraie livraison du bus M6→M5, deux réceptions et journal durable."""

import importlib.util
import json
from pathlib import Path

import pytest
from m5_financecore import outils, registre
from sqlalchemy import select, update

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import EVENEMENTS_RECUS, REGISTRES

WT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "ap_reception_canon_fictif", WT / "departments/m05-financecore/tests/test_comptes_a_payer_outils.py"
)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
base_durable = f.base_durable
dep = f.dep
D = f.DEPARTEMENT


def journal():
    return registre.Registre(stockage.maillons(D, outils._NOM_REGISTRE_COMPTES_A_PAYER))


def test_reception_legitime_et_rejeu(dep):
    a = f._charge(evenement_id="A-FICTIF")
    f._publier(a)
    result = f._drainer(dep)
    assert result["traites"] == 1 and result["echecs"] == 0
    assert journal().taille() == 1 and journal().valider_chaine() == (True, "")
    before = journal().lire()
    with stockage.transaction():
        replay = outils._recevoir_reception_enregistree(a)
        assert replay["statut"] == "deja_recue"
    assert journal().lire() == before


def test_reception_bus_perimee_refuse(dep, monkeypatch):
    avant = journal().lire()
    movements = list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS))
    a = f._charge(evenement_id="A-FICTIF")
    b = f._charge(evenement_id="B-FICTIF", gouttiere="0", vis="40", horodatage=f.LIVRAISON_2)
    f._publier(a)
    original = MaillonsDurables.append
    observations = []

    def interposer(self, maillon, *, rang_attendu=None):
        if (self.departement, self.registre) == (D, outils._NOM_REGISTRE_COMPTES_A_PAYER) and maillon.get(
            "evenement_id"
        ) == "A-FICTIF":
            cnx = stockage.connexion_courante()
            rb = outils._recevoir_reception_enregistree(b)
            assert rb["statut"] == "recue" and stockage.connexion_courante() is cnx
            assert journal().valider_chaine() == (True, "")
            observations.append(len(self))
        return original(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", interposer)
    result = f._drainer(dep)
    print(
        json.dumps(
            {
                "bus": result,
                "observations": observations,
                "taille": journal().taille(),
                "chaine": journal().valider_chaine(),
            }
        )
    )
    assert observations == [1]
    assert result["traites"] == 0 and result["echecs"] == 1
    stockage.liberer()
    assert journal().lire() == avant
    assert list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS)) == movements

    with stockage.transaction() as cnx:
        receipt = (
            cnx.execute(select(EVENEMENTS_RECUS).where(EVENEMENTS_RECUS.c.evenement_id == "A-FICTIF")).mappings().one()
        )
        assert receipt["statut"] == "echec" and receipt["tentatives"] == 1
        assert receipt["derniere_erreur"].startswith("EcritureConcurrente:")
        assert receipt["prochaine_tentative"] == "2026-09-29T12:00:02+00:00"
    monkeypatch.setattr(MaillonsDurables, "append", original)
    with stockage.transaction():
        assert outils._recevoir_reception_enregistree(b)["statut"] == "recue"
    with_b = journal().lire()
    early = f._drainer(dep, heure="2026-09-29T12:00:01+00:00")
    assert early["livres"] == 0 and journal().lire() == with_b
    retry = f._drainer(dep, heure="2026-09-29T12:00:03+00:00")
    assert retry["traites"] == 1 and retry["echecs"] == 0
    after = journal().lire()
    assert after[:1] == with_b and [m["evenement_id"] for m in after] == ["B-FICTIF", "A-FICTIF"]
    assert after[-1]["precedent_ligne_id"] == with_b[-1]["ligne_id"] and journal().valider_chaine() == (True, "")
    with stockage.transaction() as cnx:
        receipt = (
            cnx.execute(select(EVENEMENTS_RECUS).where(EVENEMENTS_RECUS.c.evenement_id == "A-FICTIF")).mappings().one()
        )
        assert receipt["statut"] == "traite" and receipt["tentatives"] == 2 and receipt["prochaine_tentative"] is None
    assert list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS)) == movements


def test_reception_corrompue_refuse_meme_rejeu(dep, monkeypatch):
    a = f._charge(evenement_id="A-FICTIF")
    f._publier(a)
    assert f._drainer(dep)["traites"] == 1
    with stockage.transaction() as cnx:
        clause = (
            (REGISTRES.c.departement == D)
            & (REGISTRES.c.registre == outils._NOM_REGISTRE_COMPTES_A_PAYER)
            & (REGISTRES.c.rang == 0)
        )
        m = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(clause)).scalar_one())
        m["ligne_id"] = "0" * 64
        cnx.execute(update(REGISTRES).where(clause).values(maillon=codec.encoder(m)))
    before = journal().lire()
    calls = []

    def interdit(*args, **kwargs):
        calls.append(True)
        raise AssertionError("append interdit sur préfixe corrompu fictif")

    monkeypatch.setattr(MaillonsDurables, "append", interdit)
    with pytest.raises(ValueError, match="REJ-FACTURE-CHAINE-INVALIDE"), stockage.transaction():
        outils._recevoir_reception_enregistree(a)
    assert calls == [] and journal().lire() == before
    f._publier(f._charge(evenement_id="C-FICTIF"))
    result = f._drainer(dep)
    assert result["echecs"] == 1 and result["traites"] == 0 and calls == [] and journal().lire() == before


def test_reception_rejeu_sans_append(dep, monkeypatch):
    a = f._charge(evenement_id="A-FICTIF")
    f._publier(a)
    assert f._drainer(dep)["traites"] == 1
    before = journal().lire()
    calls = []

    def interdit(*args, **kwargs):
        calls.append(True)
        raise AssertionError("append interdit sur rejeu fictif")

    monkeypatch.setattr(MaillonsDurables, "append", interdit)
    with stockage.transaction():
        assert outils._recevoir_reception_enregistree(a)["statut"] == "deja_recue"
    assert journal().lire() == before and calls == []


def test_reception_sql_puis_exception_annule_et_rejoue(dep, monkeypatch):
    a = f._charge(evenement_id="A-FICTIF")
    f._publier(a)
    original = MaillonsDurables.append
    seen = []

    def apres(self, maillon, *, rang_attendu=None):
        result = original(self, maillon, rang_attendu=rang_attendu)
        if (self.departement, self.registre) == (D, outils._NOM_REGISTRE_COMPTES_A_PAYER):
            assert journal().taille() == 1 and journal().valider_chaine() == (True, "")
            seen.append(maillon["evenement_id"])
            raise RuntimeError("panne fictive après écriture native")
        return result

    monkeypatch.setattr(MaillonsDurables, "append", apres)
    result = f._drainer(dep)
    assert result["echecs"] == 1 and result["traites"] == 0 and seen == ["A-FICTIF"]
    stockage.liberer()
    assert journal().lire() == []
    monkeypatch.setattr(MaillonsDurables, "append", original)
    assert f._drainer(dep, heure="2026-09-29T12:00:03+00:00")["traites"] == 1
    assert journal().taille() == 1 and journal().valider_chaine() == (True, "")


def test_reception_durable_meme_mouvements_memoires(dep, monkeypatch):
    monkeypatch.setattr(outils, "_stockage_durable_actif", False)
    movements = list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS))
    f._publier(f._charge(evenement_id="A-FICTIF"))
    assert f._drainer(dep)["traites"] == 1
    stockage.liberer()
    assert journal().taille() == 1 and journal().valider_chaine() == (True, "")
    assert list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS)) == movements
