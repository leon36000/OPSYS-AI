"""Confidentialité des questions libres : doubles unitaires, aucun résultat RAG réel prétendu."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from opsys.memoire import autorite, outils
from opsys.memoire.store import Recherche

FICTIF = True
QUESTION = "Dossier de PERSONNE-FICTIVE, courriel personne-fictive@example.invalid"
SUJET = "client:qa-confidentialite"


@pytest.fixture
def contexte_m3(monkeypatch):
    racine = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(racine / "departments"))
    monkeypatch.setenv("OPSYS_DEPARTEMENT", "m03-estimation")
    dep = outils.departement_appelant()
    assert {"clients", "procedures"} <= set(dep.memoire_lecture)
    with autorite.lecture_bornee((SUJET,), ("procedures",)):
        yield monkeypatch


def _capture_store(monkeypatch):
    appels = []

    def rechercher(requete, vecteur, k, filtres, *, embedding_profile_sha256=None):
        appels.append((requete, vecteur, k, filtres, embedding_profile_sha256))
        # Réponse vide de forme valide seulement ; aucune recherche documentaire simulée.
        return Recherche("plein_texte", ())

    monkeypatch.setattr(outils, "_memoire", lambda: SimpleNamespace(rechercher=rechercher))
    return appels


def test_requetes_externes_clients_et_mixtes_restent_plein_texte(contexte_m3):
    appels = _capture_store(contexte_m3)
    provider = []

    def interdit(textes):
        provider.append(textes)
        pytest.fail("une question libre non classifiée a atteint le provider externe")

    client = SimpleNamespace(local=False, plonger=interdit)
    contexte_m3.setattr(outils, "_embeddings", lambda: (client, ""))
    for portees in (["clients"], ["clients", "procedures"]):
        reponse = outils.rechercher(QUESTION, portees=list(portees), k=1, sujet=SUJET)
        assert reponse["mode"] == "plein_texte"
        assert "requête non classifiée" in reponse["avertissement"]
        assert "plein texte" in reponse["avertissement"]
        requete, vecteur, k, filtres, profil = appels[-1]
        assert requete == QUESTION and vecteur is None and k == 1 and profil is None
        assert filtres == {"portee": list(portees), "sujet": SUJET,
                           "sujets_autorises": [SUJET], "portees_globales": ["procedures"]}
    assert provider == [] and len(appels) == 2


def test_client_local_garde_vectorisation_et_transmet_vecteur(contexte_m3):
    appels = _capture_store(contexte_m3)
    vecteur = [1.0] + [0.0] * 1023
    provider = []

    def plonger(textes):
        provider.append(textes)
        return [vecteur]

    contexte_m3.setattr(outils, "_embeddings", lambda: (SimpleNamespace(local=True, plonger=plonger), ""))
    outils.rechercher(QUESTION, portees=["clients"], k=1, sujet=SUJET)
    assert provider == [[QUESTION]]
    assert len(appels) == 1 and appels[0][0] == QUESTION
    assert appels[0][1] is vecteur and appels[0][4] is None
    assert appels[0][3]["sujets_autorises"] == [SUJET]


def test_portee_ou_sujet_hors_autorite_refuses_avant_store_et_provider(contexte_m3):
    def interdit():
        pytest.fail("un refus d'autorité a atteint un collaborateur de recherche")

    contexte_m3.setattr(outils, "_embeddings", interdit)
    contexte_m3.setattr(outils, "_memoire", interdit)
    with pytest.raises(ValueError, match="hors du manifeste"):
        outils.rechercher(QUESTION, portees=["finances-qa-non-admises"], sujet=SUJET)
    with pytest.raises(ValueError, match="MEMOIRE-SUJET-HORS-AUTORITE"):
        outils.rechercher(QUESTION, portees=["clients"], sujet="client:qa-autre")
