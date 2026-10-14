"""M5 journal natif fictif : composant seulement, aucune admission T3 qualifiée."""
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
R = "principal"


def _arguments(montant, source):
    return {"montant": montant, "type_mouvement": "ENCAISSEMENT",
            "horodatage": "2026-08-03T12:00:00+00:00", "classe_retention": "STANDARD", "source": source}


def _relire():
    return registre.Registre(stockage.maillons(D, R))


@pytest.fixture
def natif(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "instance-fictive"))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    stockage.migrer()
    dep = charger_departements(Path.cwd() / "departments")[D]
    outil = next(o for o in dep.charger_outils() if o.nom == "m5_enregistrer_mouvement")
    assert outil.autonomie == Autonomie.T3  # metadata only, no admission test.
    yield outil
    stockage.liberer()


def test_mouvements_natifs_gardent_decimal_et_ligne_id(natif):
    memoire = registre.Registre()
    for montant, source in [("100.00", "FICTIF-SEED"), ("200.00", "FICTIF-A"), ("300.00", "FICTIF-B")]:
        arguments = _arguments(montant, source)
        mouvement = dict(arguments, montant=Decimal(montant))
        attendu = registre.enregistrer_mouvement(mouvement, memoire)
        r = executer_atomique(natif, arguments)
        assert r["ok"] and r["resultat"]["accepte"]
        # L'API présente Decimal en texte ; le journal natif reste typé.
        assert r["resultat"]["resultat"] == dict(attendu, montant=str(attendu["montant"]))
        assert r["resultat"]["registre_mouvements"] == {"taille": memoire.taille(), "tete": memoire.tete()}
    stockage.liberer()
    assert _relire().lire() == memoire.lire() and _relire().valider_chaine() == (True, "")


def test_rang_perime_annule_et_reprise_conserve_chaine(natif, monkeypatch):
    assert executer_atomique(natif, _arguments("100.00", "FICTIF-SEED"))["ok"]
    avant = _relire().lire()
    originale = MaillonsDurables.append
    observations = []

    def interposer(self, maillon, *, rang_attendu=None):
        if (self.departement, self.registre) == (D, R) and maillon.get("source") == "FICTIF-A":
            cnx = stockage.connexion_courante()
            b = executer_atomique(natif, _arguments("300.00", "FICTIF-B"))
            assert b["ok"] and b["resultat"]["accepte"]
            assert stockage.connexion_courante() is cnx and _relire().valider_chaine() == (True, "")
            observations.append(len(self))
        return originale(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", interposer)
    with pytest.raises(EcritureConcurrente):
        executer_atomique(natif, _arguments("200.00", "FICTIF-A"))
    assert observations == [2]
    stockage.liberer()
    assert _relire().lire() == avant  # B belongs to A's transaction, no PG commit claim.
    monkeypatch.setattr(MaillonsDurables, "append", originale)
    r = executer_atomique(natif, _arguments("200.00", "FICTIF-A"))
    assert r["ok"] and r["resultat"]["accepte"]
    stockage.liberer()
    assert _relire().valider_chaine() == (True, "") and _relire().taille() == 2


def test_journal_corrompu_refuse_avant_ajout(natif):
    assert executer_atomique(natif, _arguments("100.00", "FICTIF-SEED"))["ok"]
    filtre = (REGISTRES.c.departement == D) & (REGISTRES.c.registre == R)
    with stockage.transaction() as cnx:
        ligne = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one())
        ligne["ligne_id"] = "0" * 64
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(ligne)))
    avant = _relire().lire()
    r = executer_atomique(natif, _arguments("200.00", "FICTIF-A"))
    assert not r["ok"] and r["erreur"] == "refus_metier"
    stockage.liberer()
    assert _relire().lire() == avant


def test_reponse_decrit_le_prefixe_accepte(natif, monkeypatch):
    assert executer_atomique(natif, _arguments("100.00", "FICTIF-SEED"))["ok"]
    originale = MaillonsDurables.append

    def apres_a(self, maillon, *, rang_attendu=None):
        resultat = originale(self, maillon, rang_attendu=rang_attendu)
        if (self.departement, self.registre) == (D, R) and maillon.get("source") == "FICTIF-A":
            b = executer_atomique(natif, _arguments("300.00", "FICTIF-B"))
            assert b["ok"] and b["resultat"]["accepte"]
        return resultat

    monkeypatch.setattr(MaillonsDurables, "append", apres_a)
    r = executer_atomique(natif, _arguments("200.00", "FICTIF-A"))
    assert r["ok"] and r["resultat"]["accepte"]
    a = r["resultat"]["resultat"]
    assert r["resultat"]["registre_mouvements"] == {"taille": 2, "tete": a["ligne_id"]}
    stockage.liberer()
    assert _relire().taille() == 3 and _relire().valider_chaine() == (True, "")


def test_historique_explicite_reste_simulation(natif):
    assert executer_atomique(natif, _arguments("100.00", "FICTIF-SEED"))["ok"]
    avant = _relire().lire()
    r = executer_atomique(natif, dict(_arguments("200.00", "FICTIF-A"), mouvements_historique=[]))
    assert r["ok"] and r["resultat"]["accepte"]
    assert len(r["resultat"]["mouvements_historique"]) == 1
    assert "registre_mouvements" not in r["resultat"]
    stockage.liberer()
    assert _relire().lire() == avant


def test_mode_memoire_historique_reste_sans_effet_natif(natif):
    outils.reinitialiser_stockage_mouvements()
    try:
        r = executer_atomique(natif, _arguments("200.00", "FICTIF-A"))
        assert r["ok"] and r["resultat"]["accepte"]
        assert len(r["resultat"]["mouvements_historique"]) == 1
        assert _relire().taille() == 0
    finally:
        outils.utiliser_stockage_durable()
