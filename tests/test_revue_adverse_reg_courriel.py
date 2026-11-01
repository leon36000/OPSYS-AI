"""Revue adverse (reg) : l'ingestion courriel survit à une page de fournisseur qui répète une référence.

Graph (delta) peut renvoyer le même message plusieurs fois dans une page. Avant le correctif, les références de la page
étaient écrites en bloc : la deuxième occurrence violait la clé primaire de `courriel_refs`, la transaction de page
sautait en `IntegrityError` brute (ni signalée, ni journalisée) et, comme le curseur n'avançait pas, la MÊME page
revenait à chaque passage : dossier bloqué à jamais. Vrai stockage, vraie file d'onboarding ; fournisseur = double.
"""

from __future__ import annotations

import courriel_doubles as dbl
import courriel_qa as qa
import pytest
from sqlalchemy import func, select

from opsys import stockage
from opsys.courriel_connecteurs.ingestion import IngestionCourriel
from opsys.courriel_connecteurs.modele import PageSync
from opsys.stockage.schema import COURRIEL_MESSAGES, COURRIEL_REFS

FICTIF = True


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = qa.preparer(tmp_path, monkeypatch)
    qa.creer_compte(m)
    qa.connecter_oauth(m)
    return m


class FournisseurQuiRepete:
    """Enveloppe d'un fournisseur : chaque page rend ses références `fois` fois (comportement permis d'un delta)."""

    def __init__(self, vrai, fois: int = 2) -> None:
        self._vrai, self._fois = vrai, fois
        self.identifiant = vrai.identifiant

    def synchroniser(self, dossier, curseur, *, limite=100):
        page = self._vrai.synchroniser(dossier, curseur, limite=limite)
        return PageSync(page.ajouts * self._fois, page.suppressions, page.curseur, page.termine)

    def lire_message(self, ref):
        return self._vrai.lire_message(ref)

    def __getattr__(self, nom):
        return getattr(self._vrai, nom)


def _ingestion(monde) -> IngestionCourriel:
    return IngestionCourriel(stockage.transaction, acteur="nathan", signaler=monde.service.signaler_erreur)


def _compter(table) -> int:
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(table)).scalar_one()


def test_une_reference_repetee_dans_une_page_ne_bloque_pas_le_dossier(monde):
    monde.gmail.ajouter(dbl.courriel_brut(objet="A", message_id="<a@example.test>"))
    monde.gmail.ajouter(dbl.courriel_brut(objet="B", message_id="<b@example.test>"))
    fournisseur = FournisseurQuiRepete(monde.service.fournisseur("gmail-paul"), fois=3)
    rapport = _ingestion(monde).synchroniser("gmail-paul", fournisseur, "INBOX")
    assert rapport.statut == "termine" and rapport.code is None
    assert rapport.nouveaux == 2 and rapport.messages_lus == 2
    assert rapport.deja_vus == 4  # les quatre occurrences en trop sont sautées, sans appel au fournisseur
    assert _compter(COURRIEL_MESSAGES) == 2 and _compter(COURRIEL_REFS) == 2


def test_la_page_repetee_est_idempotente_au_passage_suivant(monde):
    monde.gmail.ajouter(dbl.courriel_brut(objet="A", message_id="<a@example.test>"))
    fournisseur = FournisseurQuiRepete(monde.service.fournisseur("gmail-paul"))
    ing = _ingestion(monde)
    ing.synchroniser("gmail-paul", fournisseur, "INBOX")
    second = ing.synchroniser("gmail-paul", fournisseur, "INBOX")
    assert second.nouveaux == 0 and second.statut == "termine"
    assert _compter(COURRIEL_MESSAGES) == 1


def test_cas_negatif_sans_repetition_le_comportement_est_inchange(monde):
    monde.gmail.ajouter(dbl.courriel_brut(objet="A", message_id="<a@example.test>"))
    monde.gmail.ajouter(dbl.courriel_brut(objet="B", message_id="<b@example.test>"))
    rapport = _ingestion(monde).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    assert (rapport.nouveaux, rapport.deja_vus, rapport.doublons) == (2, 0, 0)


def test_deux_references_distinctes_du_meme_message_restent_un_doublon(monde):
    """Même `Message-ID`, même contenu, deux références : un seul message ingéré, l'autre est un doublon compté."""
    brut = dbl.courriel_brut(objet="A", message_id="<a@example.test>")
    monde.gmail.ajouter(brut)
    monde.gmail.ajouter(brut)
    rapport = _ingestion(monde).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    assert rapport.nouveaux == 1 and rapport.doublons == 1
    assert _compter(COURRIEL_REFS) == 2
