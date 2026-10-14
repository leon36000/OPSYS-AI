"""Fictif : AP N3 avec réceptions canoniques et deux décisions humaines, mêmeTxSQLite."""

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import outils, registre
from sqlalchemy import select, update

from opsys import approbations, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.stockage import codec
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import REGISTRES

WT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "canon_ap_fictif", WT / "departments/m05-financecore/tests/test_comptes_a_payer_outils.py"
)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
base_durable = fixtures.base_durable
dep = fixtures.dep
personnes = fixtures.personnes
D = fixtures.DEPARTEMENT


def journal():
    return registre.Registre(stockage.maillons(D, outils._NOM_REGISTRE_COMPTES_A_PAYER))


def demander(dep, numero, montant):
    r = Capacites({D: dep}, stockage.transaction).appeler(
        "m5_saisir_facture_fournisseur", fixtures._facture_args(numero_facture=numero, montant_avant_taxes=montant)
    )
    assert r["statut"] == "en_attente_approbation"
    return r["demande_id"]


def decider(dep, demande):
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx, demande, True, "financeuse", outils_executables({D: dep}, stockage.transaction), {D: dep}
        )


def recevoir(dep):
    fixtures._recevoir(dep)
    fixtures._recevoir(dep, evenement_id="evt-2-fictif", gouttiere="0", vis="40", horodatage=fixtures.LIVRAISON_2)
    assert journal().taille() == 2 and journal().valider_chaine() == (True, "")


def test_saisie_ap_legitime(dep, personnes):
    recevoir(dep)
    demande = demander(dep, "F-1001", "300.00")
    r = decider(dep, demande)
    assert r["statut"] == "executee" and r["reponse"]["resultat"]["accepte"]
    assert journal().taille() == 3 and journal().valider_chaine() == (True, "")


def test_saisie_ap_perimee_refuse(dep, personnes, monkeypatch):
    recevoir(dep)
    avant = journal().lire()
    avant_mouvements = list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS))
    a = demander(dep, "F-1001", "300.00")
    b = demander(dep, "F-1002", "20.00")
    original = MaillonsDurables.append
    observations = []

    def interposer(self, maillon, *, rang_attendu=None):
        if (self.departement, self.registre) == (D, outils._NOM_REGISTRE_COMPTES_A_PAYER) and maillon.get(
            "numero_facture"
        ) == "F-1001":
            cnx = stockage.connexion_courante()
            decision_b = decider(dep, b)
            assert decision_b["statut"] == "executee" and decision_b["reponse"]["resultat"]["accepte"]
            assert stockage.connexion_courante() is cnx and journal().valider_chaine() == (True, "")
            observations.append(len(self))
        return original(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", interposer)
    r = decider(dep, a)
    print(
        json.dumps(
            {
                "decision": r,
                "observations": observations,
                "chaine": journal().valider_chaine(),
                "taille": journal().taille(),
            },
            default=str,
        )
    )
    assert observations == [3]
    assert r["statut"] == "echec" and r["reponse"]["erreur"] == "panne_execution"
    assert r["reponse"]["details"].startswith("EcritureConcurrente:")
    stockage.liberer()
    assert journal().lire() == avant

    assert list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS)) == avant_mouvements
    with stockage.transaction() as cnx:
        assert approbations.lire(cnx, a)["statut"] == "echec"
        assert approbations.lire(cnx, b)["statut"] == "en_attente"
    with pytest.raises(ValueError, match="déjà"):
        decider(dep, a)
    monkeypatch.setattr(MaillonsDurables, "append", original)
    assert decider(dep, b)["statut"] == "executee"
    suivant = demander(dep, "F-1001", "300.00")
    assert suivant != a and decider(dep, suivant)["statut"] == "executee"
    stockage.liberer()
    maillons = journal().lire()
    assert maillons[:2] == avant and len(maillons) == 4
    assert [m["numero_facture"] for m in maillons[2:]] == ["F-1002", "F-1001"]
    assert all(type(m["montant_avant_taxes"]) is Decimal for m in maillons[2:])
    assert all(m["saisi_par"] == "financeuse" and m["voie"] == "approbation" for m in maillons[2:])
    assert journal().valider_chaine() == (True, "")
    assert list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS)) == avant_mouvements


def test_reponse_ap_utilise_prefixe_accepte(dep, personnes, monkeypatch):
    recevoir(dep)
    a = demander(dep, "F-1001", "300.00")
    b = demander(dep, "F-1002", "20.00")
    original = MaillonsDurables.append

    def apres(self, maillon, *, rang_attendu=None):
        r = original(self, maillon, rang_attendu=rang_attendu)
        if (self.departement, self.registre) == (D, outils._NOM_REGISTRE_COMPTES_A_PAYER) and maillon.get(
            "numero_facture"
        ) == "F-1001":
            assert decider(dep, b)["statut"] == "executee"
        return r

    monkeypatch.setattr(MaillonsDurables, "append", apres)
    r = decider(dep, a)
    assert r["statut"] == "executee"
    assert r["reponse"]["resultat"]["resultat"]["rapprochement"]["facture_avant_taxes"] == "300.00"
    assert journal().taille() == 4 and journal().valider_chaine() == (True, "")


def test_ap_corrompu_refuse_sans_ajout(dep, personnes, monkeypatch):
    recevoir(dep)
    a = demander(dep, "F-1001", "300.00")
    filtre = (
        (REGISTRES.c.departement == D)
        & (REGISTRES.c.registre == outils._NOM_REGISTRE_COMPTES_A_PAYER)
        & (REGISTRES.c.rang == 0)
    )
    with stockage.transaction() as cnx:
        m = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one())
        m["ligne_id"] = "0" * 64
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(m)))
    avant = journal().lire()

    def interdit(*args, **kwargs):
        pytest.fail("aucun append sur journal corrompu")

    monkeypatch.setattr(MaillonsDurables, "append", interdit)
    r = decider(dep, a)
    assert r["statut"] == "echec" and r["reponse"]["erreur"] == "refus_metier"
    assert "REJ-FACTURE-CHAINE-INVALIDE" in r["reponse"]["details"]
    stockage.liberer()
    assert journal().lire() == avant


def test_ap_doublon_refuse_sans_ajout(dep, personnes, monkeypatch):
    recevoir(dep)
    assert decider(dep, demander(dep, "F-1001", "300.00"))["statut"] == "executee"
    avant = journal().lire()
    a = demander(dep, "F-1001", "300.00")

    def interdit(*args, **kwargs):
        pytest.fail("aucun append sur doublon")

    monkeypatch.setattr(MaillonsDurables, "append", interdit)
    r = decider(dep, a)
    assert r["statut"] == "echec" and not r["reponse"]["resultat"]["accepte"]
    assert r["reponse"]["resultat"]["verdict"]["code"] == "REJ-AP-FACTURE-DOUBLON"
    stockage.liberer()
    assert journal().lire() == avant


def test_ap_reste_durable_quand_mode_mouvements_memoire(dep, personnes, monkeypatch):
    monkeypatch.setattr(outils, "_stockage_durable_actif", False)
    recevoir(dep)
    assert decider(dep, demander(dep, "F-1001", "300.00"))["statut"] == "executee"
    stockage.liberer()
    assert journal().taille() == 3 and journal().valider_chaine() == (True, "")
