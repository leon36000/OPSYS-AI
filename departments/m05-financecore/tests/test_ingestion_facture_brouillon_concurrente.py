from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import outils, registre
from sqlalchemy import select, update

from opsys import stockage
from opsys.departements import charger_departements
from opsys.outils import Autonomie, executer_atomique
from opsys.stockage import codec
from opsys.stockage.maillons import EcritureConcurrente, MaillonsDurables
from opsys.stockage.schema import REGISTRES

D = "m05-financecore"
R = "factures"


def args(n):
    return dict(
        facture_id="FICTIF-FACT-" + n,
        chantier_id="FICTIF-CHANT-" + n,
        devis_id="FICTIF-DEVIS-" + n,
        client_id="FICTIF-CLIENT",
        lignes=[
            dict(
                description="FICTIF",
                quantite="1",
                unite="forfait",
                prix_unitaire="100.00",
                reference_ligne_devis="FICTIF-L1",
            )
        ],
        horodatage="2026-08-03T12:00:00+00:00",
    )


def journal():
    return registre.Registre(stockage.maillons(D, R))


@pytest.fixture
def outil(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "instance-fictive"))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    stockage.migrer()
    outils.utiliser_stockage_durable()
    o = next(
        o
        for o in charger_departements(Path.cwd() / "departments")[D].charger_outils()
        if o.nom == "m5_creer_facture_brouillon"
    )
    assert o.autonomie == Autonomie.T1
    yield o
    stockage.liberer()


def test_sequentiel_et_rejeu(outil):
    for n in ["SEED", "A", "B"]:
        r = executer_atomique(outil, args(n))
        assert r["ok"] and r["resultat"]["accepte"]
    avant = journal().lire()
    assert len(avant) == 3 and journal().valider_chaine() == (True, "")
    assert all(type(x["montant_avant_taxes"]) is Decimal for x in avant)
    assert executer_atomique(outil, args("A"))["resultat"]["accepte"]
    stockage.liberer()
    assert journal().lire() == avant


@pytest.mark.parametrize("meme_devis", [False, True])
def test_candidate_perime_refuse_et_preserve_prefixe(outil, monkeypatch, meme_devis):
    assert executer_atomique(outil, args("SEED"))["resultat"]["accepte"]
    avant = journal().lire()
    orig = MaillonsDurables.append
    observations = []

    def interposer(self, maillon, *, rang_attendu=None):
        if (self.departement, self.registre) == (D, R) and maillon.get("facture_id") == "FICTIF-FACT-A":
            cnx = stockage.connexion_courante()
            arguments_b = args("B")
            if meme_devis:
                arguments_b["devis_id"] = args("A")["devis_id"]
            b = executer_atomique(outil, arguments_b)
            assert b["ok"] and b["resultat"]["accepte"]
            assert stockage.connexion_courante() is cnx and journal().valider_chaine() == (True, "")
            observations.append(len(self))
        return orig(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", interposer)
    with pytest.raises(EcritureConcurrente):
        executer_atomique(outil, args("A"))
    assert observations == [2]
    stockage.liberer()
    assert journal().lire() == avant

    monkeypatch.setattr(MaillonsDurables, "append", orig)
    r = executer_atomique(outil, args("A"))
    assert r["ok"] and r["resultat"]["accepte"]
    stockage.liberer()
    assert len(journal().lire()) == 2 and journal().valider_chaine() == (True, "")


def test_journal_corrompu_refuse_avant_ajout(outil):
    assert executer_atomique(outil, args("SEED"))["resultat"]["accepte"]
    filtre = (REGISTRES.c.departement == D) & (REGISTRES.c.registre == R)
    with stockage.transaction() as cnx:
        ligne = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one())
        ligne["ligne_id"] = "0" * 64
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(ligne)))
    avant = journal().lire()
    r = executer_atomique(outil, args("A"))
    assert not r["ok"] and r["erreur"] == "refus_metier"
    stockage.liberer()
    assert journal().lire() == avant


def test_reponse_decrit_le_prefixe_accepte(outil, monkeypatch):
    assert executer_atomique(outil, args("SEED"))["resultat"]["accepte"]
    orig = MaillonsDurables.append

    def apres_a(self, maillon, *, rang_attendu=None):
        resultat = orig(self, maillon, rang_attendu=rang_attendu)
        if (self.departement, self.registre) == (D, R) and maillon.get("facture_id") == "FICTIF-FACT-A":
            b = executer_atomique(outil, args("B"))
            assert b["ok"] and b["resultat"]["accepte"]
        return resultat

    monkeypatch.setattr(MaillonsDurables, "append", apres_a)
    r = executer_atomique(outil, args("A"))
    assert r["ok"] and r["resultat"]["accepte"]
    assert r["resultat"]["registre_factures"] == dict(taille=2, tete=r["resultat"]["resultat"]["ligne_id"])
    stockage.liberer()
    assert journal().taille() == 3 and journal().valider_chaine() == (True, "")


def test_identite_facture_conflit_necrit_pas(outil):
    assert executer_atomique(outil, args("A"))["resultat"]["accepte"]
    avant = journal().lire()
    a = args("A")
    a["lignes"][0]["prix_unitaire"] = "200.00"
    r = executer_atomique(outil, a)
    assert r["ok"] and not r["resultat"]["accepte"]
    stockage.liberer()
    assert journal().lire() == avant


def test_historique_explicite_reste_simulation(outil):
    assert executer_atomique(outil, args("SEED"))["resultat"]["accepte"]
    avant = journal().lire()
    r = executer_atomique(outil, dict(args("A"), factures_historique=[]))
    assert r["ok"] and r["resultat"]["accepte"] and len(r["resultat"]["factures_historique"]) == 1
    assert "registre_factures" not in r["resultat"]
    stockage.liberer()
    assert journal().lire() == avant


def test_mode_memoire_necrit_pas(outil):
    outils.reinitialiser_stockage_mouvements()
    try:
        r = executer_atomique(outil, args("A"))
        assert r["ok"] and r["resultat"]["accepte"]
        assert len(r["resultat"]["factures_historique"]) == 1 and journal().taille() == 0
    finally:
        outils.utiliser_stockage_durable()
