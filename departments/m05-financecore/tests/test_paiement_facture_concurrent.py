"""Fictif : décision N5 réelle, aucune banque ni paiement externe."""
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import select, update

from opsys import approbations, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.stockage import codec
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import REGISTRES

WT = Path(__file__).resolve().parents[3]


def charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, WT / fichier)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


auth = charger("canon_n4_n5_fictif", "departments/m05-financecore/tests/test_envoi_facture_concurrent.py")
ancien = charger("canon_n5_fictif", "departments/m05-financecore/tests/test_approbations_socle.py")
base_durable = auth.base_durable
dep = auth.dep
personnes = auth.personnes


def creer_et_envoyer(dep, personnes):
    facture = auth._creer_facture_brouillon("FICTIF-FACT-A", "FICTIF-DEVIS-A")
    envoi = auth.demander(dep, facture)
    assert auth.decider(dep, personnes, envoi)["statut"] == "executee"
    assert auth._statut_facture(facture) == "ENVOYEE"
    return facture


def demander(dep, facture):
    r = Capacites({auth.D: dep}, stockage.transaction).appeler(
        "m5_enregistrer_paiement_facture",
        {"facture_id": facture, "montant_paye": ancien.MONTANT_DU,
         "approbateur": "Propriétaire fictif", "horodatage": auth.HORODATAGE},
    )
    assert r["statut"] == "en_attente_approbation"
    assert auth._statut_facture(facture) == "ENVOYEE"
    return r["demande_id"]


def decider(dep, personnes, demande):
    disponibles = outils_executables({auth.D: dep}, stockage.transaction)
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx, demande, True, personnes["nathan"], disponibles, {auth.D: dep},
            attestation=ancien.ATTESTATION_VALIDE,
        )


def test_n5_approbation_et_attestation_legitimes(dep, personnes):
    facture = creer_et_envoyer(dep, personnes)
    avant_mouvements = list(stockage.maillons(auth.D, auth.m5_outils._NOM_REGISTRE_MOUVEMENTS))
    demande = demander(dep, facture)
    r = decider(dep, personnes, demande)
    assert r["statut"] == "executee" and r["reponse"]["resultat"]["accepte"]
    stockage.liberer()
    assert auth._statut_facture(facture) == "PAYEE"
    assert auth.journal().valider_chaine() == (True, "")
    assert list(stockage.maillons(auth.D, auth.m5_outils._NOM_REGISTRE_MOUVEMENTS)) == avant_mouvements


def test_n5_candidat_perime_refuse(dep, personnes, monkeypatch):
    facture = creer_et_envoyer(dep, personnes)
    avant_mouvements = list(stockage.maillons(auth.D, auth.m5_outils._NOM_REGISTRE_MOUVEMENTS))
    avant = auth.journal().lire()
    demande = demander(dep, facture)
    original = MaillonsDurables.append
    observations = []

    def interposer(self, maillon, *, rang_attendu=None):
        if (self.departement, self.registre) == (auth.D, auth.R) and maillon.get("statut") == "PAYEE":
            cnx = stockage.connexion_courante()
            auth._creer_facture_brouillon("FICTIF-FACT-B", "FICTIF-DEVIS-B")
            assert stockage.connexion_courante() is cnx and auth.journal().valider_chaine() == (True, "")
            observations.append(len(self))
        return original(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", interposer)
    r = decider(dep, personnes, demande)
    print(json.dumps({"decision": r, "observations": observations,
                      "chaine": auth.journal().valider_chaine(), "taille": auth.journal().taille()}, default=str))
    assert observations == [3]
    assert r["statut"] == "echec" and r["reponse"]["erreur"] == "panne_execution"
    assert r["reponse"]["details"].startswith("EcritureConcurrente:")
    stockage.liberer()
    assert auth.journal().lire() == avant and auth._statut_facture(facture) == "ENVOYEE"
    assert list(stockage.maillons(auth.D, auth.m5_outils._NOM_REGISTRE_MOUVEMENTS)) == avant_mouvements

    with stockage.transaction() as cnx:
        assert approbations.lire(cnx, demande)["statut"] == "echec"
    with pytest.raises(ValueError, match="déjà"):
        decider(dep, personnes, demande)
    assert auth.journal().lire() == avant
    monkeypatch.setattr(MaillonsDurables, "append", original)
    suivante = demander(dep, facture)
    assert suivante != demande
    assert decider(dep, personnes, suivante)["statut"] == "executee"
    stockage.liberer()
    assert auth._statut_facture(facture) == "PAYEE"
    assert auth.journal().valider_chaine() == (True, "")
    assert len(auth.journal().lire()) == len(avant) + 1
    assert list(stockage.maillons(auth.D, auth.m5_outils._NOM_REGISTRE_MOUVEMENTS)) == avant_mouvements



def test_n5_reponse_decrit_prefixe_accepte(dep, personnes, monkeypatch):
    facture = creer_et_envoyer(dep, personnes)
    avant_mouvements = list(stockage.maillons(auth.D, auth.m5_outils._NOM_REGISTRE_MOUVEMENTS))
    demande = demander(dep, facture)
    original = MaillonsDurables.append

    def apres(self, maillon, *, rang_attendu=None):
        r = original(self, maillon, rang_attendu=rang_attendu)
        if (self.departement, self.registre) == (auth.D, auth.R) and maillon.get("statut") == "PAYEE":
            auth._creer_facture_brouillon("FICTIF-FACT-B", "FICTIF-DEVIS-B")
        return r

    monkeypatch.setattr(MaillonsDurables, "append", apres)
    r = decider(dep, personnes, demande)
    assert r["statut"] == "executee"
    resultat = r["reponse"]["resultat"]
    assert resultat["registre_factures"] == {"taille": 3, "tete": resultat["resultat"]["ligne_id"]}
    assert auth.journal().taille() == 4 and auth.journal().valider_chaine() == (True, "")
    assert list(stockage.maillons(auth.D, auth.m5_outils._NOM_REGISTRE_MOUVEMENTS)) == avant_mouvements


def test_n5_chaine_corrompue_refuse_sans_ajout(dep, personnes, monkeypatch):
    facture = creer_et_envoyer(dep, personnes)
    avant_mouvements = list(stockage.maillons(auth.D, auth.m5_outils._NOM_REGISTRE_MOUVEMENTS))
    demande = demander(dep, facture)
    filtre = (REGISTRES.c.departement == auth.D) & (REGISTRES.c.registre == auth.R) & (REGISTRES.c.rang == 1)
    with stockage.transaction() as cnx:
        ligne = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one())
        ligne["ligne_id"] = "0" * 64
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(ligne)))
    avant = auth.journal().lire()

    def interdit(*args, **kwargs):
        pytest.fail("aucun append sur préfixe corrompu")

    monkeypatch.setattr(MaillonsDurables, "append", interdit)
    r = decider(dep, personnes, demande)
    assert r["statut"] == "echec" and r["reponse"]["erreur"] == "refus_metier"
    assert "REJ-FACTURE-CHAINE-INVALIDE" in r["reponse"]["details"]
    stockage.liberer()
    assert auth.journal().lire() == avant
    assert list(stockage.maillons(auth.D, auth.m5_outils._NOM_REGISTRE_MOUVEMENTS)) == avant_mouvements
