"""Envoi N4 fictif par décision du socle, concurrence SQLite dans la même transaction.

B n'est pas une connexion indépendante : le cas PostgreSQL est qualifié séparément.
"""

import json
from pathlib import Path

import pytest
from m5_financecore import facturation, registre
from m5_financecore import outils as m5_outils
from sqlalchemy import select, update

from opsys import approbations, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import REGISTRES

D = "m05-financecore"
R = "factures"


# Fixtures existantes du parcours N4, copiées sans changement fonctionnel.
_RACINE_M5 = Path(__file__).resolve().parents[1]

HORODATAGE = "2026-08-03T12:00:00+00:00"

_LIGNES_FACTURE = [
    {
        "description": "Gouttières 5po aluminium", "quantite": "40", "unite": "pi",
        "prix_unitaire": "8.50", "reference_ligne_devis": "L1",
    },
    {
        "description": "Main d'oeuvre installation", "quantite": "1", "unite": "forfait",
        "prix_unitaire": "260.00", "reference_ligne_devis": "L2",
    },
]

@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-approbations-socle.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    yield url
    stockage.liberer()

@pytest.fixture
def dep(base_durable):
    return lire_manifeste(_RACINE_M5)

@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "employe1", "Un Employé (fictif)", "mot-de-passe-employe-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur1", "Un Vendeur (fictif)", "mot-de-passe-vendeur-1234", ["seller"])
        identite.creer_personne(cnx, "financeuse", "Une Comptable (fictif)", "mot-de-passe-finance-1234",
                                ["finance"])
        identite.creer_personne(cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234",
                                ["nathan_owner"])
    return {"employe": "employe1", "vendeur": "vendeur1", "finance": "financeuse", "nathan": "nathan"}

def _creer_facture_brouillon(facture_id="FACT-SOCLE", devis_id="DEVIS-SOCLE"):
    """Setup hors périmètre du test (créer une facture BROUILLON n'est pas le sujet ici) : appel
    direct de l'outil, sans passer par l'approbation — même esprit que
    `tests/test_cascade_travaux_termines.py` pour ses étapes non testées par un scénario donné."""
    outil = next(o for o in m5_outils.outils() if o.nom == "m5_creer_facture_brouillon")
    reponse = executer_atomique(outil, {
        "facture_id": facture_id, "chantier_id": "CHANTIER-SOCLE-fictif", "devis_id": devis_id,
        "client_id": "CLIENT-SOCLE-fictif", "lignes": _LIGNES_FACTURE, "horodatage": HORODATAGE,
    })
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse
    return facture_id

def _statut_facture(facture_id):
    with stockage.transaction():
        return facturation._etat_facture(m5_outils._registre_factures(None), facture_id)["statut"]


def journal():
    return registre.Registre(stockage.maillons(D, R))


def demander(dep, facture_id):
    reponse = Capacites({D: dep}, stockage.transaction).appeler(
        "m5_envoyer_facture", {"facture_id": facture_id, "horodatage": HORODATAGE}
    )
    assert reponse["statut"] == "en_attente_approbation"
    assert _statut_facture(facture_id) == "BROUILLON"
    return reponse["demande_id"]


def decider(dep, personnes, ident):
    disponibles = outils_executables({D: dep}, stockage.transaction)
    with stockage.transaction() as cnx:
        return approbations.decider(cnx, ident, True, personnes["finance"], disponibles, {D: dep})


def test_envoi_n4_legitime(dep, personnes):
    facture = _creer_facture_brouillon("FICTIF-FACT-A", "FICTIF-DEVIS-A")
    ident = demander(dep, facture)
    resultat = decider(dep, personnes, ident)
    assert resultat["statut"] == "executee" and resultat["reponse"]["resultat"]["accepte"]
    stockage.liberer()
    assert _statut_facture(facture) == "ENVOYEE"
    assert journal().valider_chaine() == (True, "")


def test_envoi_perime_clot_echec_puis_exige_nouvelle_decision(dep, personnes, monkeypatch):
    facture = _creer_facture_brouillon("FICTIF-FACT-A", "FICTIF-DEVIS-A")
    avant = journal().lire()
    ident = demander(dep, facture)
    original = MaillonsDurables.append
    observations = []

    def interposer(self, maillon, *, rang_attendu=None):
        if (self.departement, self.registre) == (D, R) and maillon.get("statut") == "ENVOYEE":
            cnx = stockage.connexion_courante()
            _creer_facture_brouillon("FICTIF-FACT-B", "FICTIF-DEVIS-B")
            assert stockage.connexion_courante() is cnx
            assert journal().valider_chaine() == (True, "")
            observations.append(len(self))
        return original(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", interposer)
    decision = decider(dep, personnes, ident)
    print(json.dumps({"decision": decision, "observations": observations,
                      "chaine": journal().valider_chaine(), "taille": journal().taille()}, default=str))
    assert observations == [2]
    assert decision["statut"] == "echec"
    assert decision["reponse"]["erreur"] == "panne_execution"
    assert decision["reponse"]["details"].startswith("EcritureConcurrente:")
    stockage.liberer()
    assert journal().lire() == avant
    assert _statut_facture(facture) == "BROUILLON"
    with stockage.transaction() as cnx:
        assert approbations.lire(cnx, ident)["statut"] == "echec"
    with pytest.raises(ValueError, match="déjà"):
        decider(dep, personnes, ident)
    assert journal().lire() == avant
    monkeypatch.setattr(MaillonsDurables, "append", original)
    autre = demander(dep, facture)
    assert autre != ident
    assert decider(dep, personnes, autre)["statut"] == "executee"
    stockage.liberer()
    assert _statut_facture(facture) == "ENVOYEE"
    assert journal().valider_chaine() == (True, "")
    assert len(journal().lire()) == 2



def test_reponse_decrit_prefixe_accepte_apres_interposition_tardive(dep, personnes, monkeypatch):
    facture = _creer_facture_brouillon("FICTIF-FACT-A", "FICTIF-DEVIS-A")
    ident = demander(dep, facture)
    original = MaillonsDurables.append

    def apres(self, maillon, *, rang_attendu=None):
        reponse = original(self, maillon, rang_attendu=rang_attendu)
        if (self.departement, self.registre) == (D, R) and maillon.get("statut") == "ENVOYEE":
            _creer_facture_brouillon("FICTIF-FACT-B", "FICTIF-DEVIS-B")
        return reponse

    monkeypatch.setattr(MaillonsDurables, "append", apres)
    decision = decider(dep, personnes, ident)
    assert decision["statut"] == "executee"
    resultat = decision["reponse"]["resultat"]
    assert resultat["registre_factures"] == {"taille": 2, "tete": resultat["resultat"]["ligne_id"]}
    assert len(journal().lire()) == 3 and journal().valider_chaine() == (True, "")


def test_chaine_corrompue_clot_echec_sans_ajout(dep, personnes, monkeypatch):
    facture = _creer_facture_brouillon("FICTIF-FACT-A", "FICTIF-DEVIS-A")
    ident = demander(dep, facture)
    filtre = (REGISTRES.c.departement == D) & (REGISTRES.c.registre == R)
    with stockage.transaction() as cnx:
        ligne = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one())
        ligne["ligne_id"] = "0" * 64
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(ligne)))
    avant = journal().lire()

    def interdit(*args, **kwargs):
        pytest.fail("aucun append sur préfixe corrompu")

    monkeypatch.setattr(MaillonsDurables, "append", interdit)
    decision = decider(dep, personnes, ident)
    assert decision["statut"] == "echec"
    assert "REJ-FACTURE-CHAINE-INVALIDE" in decision["reponse"]["details"]
    stockage.liberer()
    assert journal().lire() == avant
