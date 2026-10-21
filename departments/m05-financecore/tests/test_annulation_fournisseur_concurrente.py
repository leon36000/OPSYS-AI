"""Fictif : annulation N4 réelle et écriture N3 B dans la même transaction SQLite."""

import importlib.util
import json
from pathlib import Path

import pytest
from m5_financecore import comptes_a_payer, outils
from sqlalchemy import select, update

from opsys import approbations, stockage
from opsys.capacites import Capacites
from opsys.stockage import codec
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import REGISTRES

WT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "sanspo_canon_fictif", WT / "departments/m05-financecore/tests/test_saisie_sans_po_concurrente.py"
)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
base_durable = f.base_durable
dep = f.dep
personnes = f.personnes
categories = f.categories
D = f.D


def seed(dep):
    r = f.decider(dep, f.demander(dep, "INIT-FICTIF", "100.00"))
    assert r["statut"] == "executee" and r["reponse"]["resultat"]["accepte"]
    return r["reponse"]["resultat"]["resultat"]["facture"]["facture_fournisseur_id"]


def revision_lue(ident):
    """`corrections` de la ligne sans PO lue avant de proposer ; absent au statut SAISIE : 0."""
    page, verdict = comptes_a_payer.lister_sans_po(f.journal(), budget_caracteres=6000)
    assert verdict is None, verdict
    (ligne,) = [x for x in page["factures"] if x["facture_fournisseur_id"] == ident]
    if "corrections" not in ligne:
        assert ligne["statut"] == "SAISIE", ligne
        return 0
    return ligne["corrections"]


def demander_annulation(dep, ident):
    r = Capacites({D: dep}, stockage.transaction).appeler(
        "m5_annuler_facture_fournisseur",
        {
            "facture_fournisseur_id": ident,
            "motif": "Facture fictive annulee par finance",
            "horodatage": f.fixtures.SAISIE,
            "revision_attendue": revision_lue(ident),
        },
    )
    assert r["statut"] == "en_attente_approbation"
    return r["demande_id"]


def test_annulation_n4_legitime(dep, personnes):
    ident = seed(dep)
    r = f.decider(dep, demander_annulation(dep, ident))
    assert r["statut"] == "executee" and r["reponse"]["resultat"]["accepte"]
    assert r["reponse"]["resultat"]["resultat"]["facture"]["statut"] == "ANNULEE"
    assert f.journal().taille() == 2 and f.journal().valider_chaine() == (True, "")


def test_annulation_n4_perimee_refuse(dep, personnes, monkeypatch):
    ident = seed(dep)
    avant = f.journal().lire()
    mouvements = list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS))
    a = demander_annulation(dep, ident)
    b = f.demander(dep, "B-FICTIF", "20.00")
    original = MaillonsDurables.append
    obs = []

    def interposer(self, maillon, *, rang_attendu=None):
        if (self.departement, self.registre) == (D, outils._NOM_REGISTRE_COMPTES_A_PAYER) and maillon.get(
            "type_entree"
        ) == "annulation_facture_fournisseur":
            cnx = stockage.connexion_courante()
            rb = f.decider(dep, b)
            assert rb["statut"] == "executee" and rb["reponse"]["resultat"]["accepte"]
            assert stockage.connexion_courante() is cnx and f.journal().valider_chaine() == (True, "")
            obs.append(len(self))
        return original(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", interposer)
    r = f.decider(dep, a)
    print(
        json.dumps(
            {
                "decision": r,
                "observations": obs,
                "chaine": f.journal().valider_chaine(),
                "taille": f.journal().taille(),
            },
            default=str,
        )
    )
    assert obs == [2]
    assert r["statut"] == "echec" and r["reponse"]["erreur"] == "panne_execution"
    assert r["reponse"]["details"].startswith("EcritureConcurrente:")
    stockage.liberer()
    assert f.journal().lire() == avant

    assert list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS)) == mouvements
    with stockage.transaction() as cnx:
        assert approbations.lire(cnx, a)["statut"] == "echec"
        assert approbations.lire(cnx, b)["statut"] == "en_attente"
    with pytest.raises(ValueError, match="déjà"):
        f.decider(dep, a)
    monkeypatch.setattr(MaillonsDurables, "append", original)
    assert f.decider(dep, b)["statut"] == "executee"
    suivant = demander_annulation(dep, ident)
    assert suivant != a and f.decider(dep, suivant)["statut"] == "executee"
    stockage.liberer()
    apres = f.journal().lire()
    assert apres[:1] == avant and len(apres) == 3
    assert apres[-1]["type_entree"] == "annulation_facture_fournisseur"
    assert (
        apres[-1]["annule_par"] == "financeuse"
        and apres[-1]["role"] == "finance"
        and apres[-1]["voie"] == "approbation"
    )
    assert f.journal().valider_chaine() == (True, "")
    assert list(stockage.maillons(D, outils._NOM_REGISTRE_MOUVEMENTS)) == mouvements


def test_annulation_reponse_sur_prefixe_accepte(dep, personnes, monkeypatch):
    ident = seed(dep)
    a = demander_annulation(dep, ident)
    b = f.demander(dep, "B-FICTIF", "20.00")
    original = MaillonsDurables.append

    def apres(self, maillon, *, rang_attendu=None):
        r = original(self, maillon, rang_attendu=rang_attendu)
        if (self.departement, self.registre) == (D, outils._NOM_REGISTRE_COMPTES_A_PAYER) and maillon.get(
            "type_entree"
        ) == "annulation_facture_fournisseur":
            assert f.decider(dep, b)["statut"] == "executee"
        return r

    monkeypatch.setattr(MaillonsDurables, "append", apres)
    r = f.decider(dep, a)
    assert r["statut"] == "executee"
    assert r["reponse"]["resultat"]["resultat"]["sans_po"]["avant_taxes"] == "0.00"
    assert f.journal().taille() == 3 and f.journal().valider_chaine() == (True, "")


def test_annulation_corrompue_refuse_sans_ajout(dep, personnes, monkeypatch):
    ident = seed(dep)
    a = demander_annulation(dep, ident)
    filtre = (
        (REGISTRES.c.departement == D)
        & (REGISTRES.c.registre == outils._NOM_REGISTRE_COMPTES_A_PAYER)
        & (REGISTRES.c.rang == 0)
    )
    with stockage.transaction() as cnx:
        m = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one())
        m["ligne_id"] = "0" * 64
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(m)))
    avant = f.journal().lire()

    def interdit(*args, **kwargs):
        pytest.fail("aucun append sur journal corrompu")

    monkeypatch.setattr(MaillonsDurables, "append", interdit)
    r = f.decider(dep, a)
    assert r["statut"] == "echec" and r["reponse"]["erreur"] == "refus_metier"
    assert "REJ-FACTURE-CHAINE-INVALIDE" in r["reponse"]["details"]
    stockage.liberer()
    assert f.journal().lire() == avant


def test_annulation_deja_annulee_refuse_sans_ajout(dep, personnes, monkeypatch):
    ident = seed(dep)
    assert f.decider(dep, demander_annulation(dep, ident))["statut"] == "executee"
    avant = f.journal().lire()
    a = demander_annulation(dep, ident)

    def interdit(*args, **kwargs):
        pytest.fail("aucun append sur annulation deja faite")

    monkeypatch.setattr(MaillonsDurables, "append", interdit)
    r = f.decider(dep, a)
    assert r["statut"] == "echec" and not r["reponse"]["resultat"]["accepte"]
    assert r["reponse"]["resultat"]["verdict"]["code"] == "REJ-AP-FACTURE-DEJA-ANNULEE"
    stockage.liberer()
    assert f.journal().lire() == avant


def test_annulation_reste_durable_mode_mouvements_memoire(dep, personnes, monkeypatch):
    monkeypatch.setattr(outils, "_stockage_durable_actif", False)
    ident = seed(dep)
    assert f.decider(dep, demander_annulation(dep, ident))["statut"] == "executee"
    stockage.liberer()
    assert f.journal().taille() == 2 and f.journal().valider_chaine() == (True, "")
