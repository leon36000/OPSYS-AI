"""Parcours complet des connecteurs sur un vrai PostgreSQL éphémère (conteneur), si Docker est disponible :
connexion OAuth, ingestion dans la file d'onboarding, brouillon, approbation N3 et envoi. Les doubles réseau restent
des doubles."""

from __future__ import annotations

import base64
import os

import courriel_doubles as dbl
import courriel_qa as qa
import ingestion_onboarding_qa as onboarding_qa
import pytest
from sqlalchemy import func, select

from opsys import approbations, identite, stockage
from opsys.courriel_connecteurs import comptes, envoi
from opsys.courriel_connecteurs.envoi import NOM_OUTIL, OUTIL_APPROBATION, ServiceEnvoi
from opsys.courriel_connecteurs.ingestion import IngestionCourriel
from opsys.stockage.schema import COURRIEL_MESSAGES, INGESTION_LOTS

FICTIF = True


def _raison_sans_docker():
    try:
        from memoire.doubles import raison_sans_docker
    except ImportError as exc:  # pragma: no cover
        return str(exc)
    return raison_sans_docker()


@pytest.mark.skipif(_raison_sans_docker() is not None, reason=str(_raison_sans_docker()))
def test_parcours_complet_sur_postgresql(tmp_path, monkeypatch):
    from memoire.doubles import postgres_ephemere

    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        try:
            monde = qa.preparer(tmp_path, monkeypatch, scope_google=f"{qa.SCOPE_GMAIL_LECTURE} {qa.SCOPE_GMAIL_ENVOI}")
            stockage.liberer()
            monkeypatch.setenv(stockage.ENV_URL, url)
            monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(os.urandom(32)).decode("ascii"))
            stockage.migrer(url)
            assert stockage.moteur(url).dialect.name == "postgresql"
            with stockage.transaction() as cnx:
                identite.creer_personne(cnx, "nathan", "Nathan fictif", "mot-de-passe-nathan-1234",
                                        ["nathan_owner", "admin"])
            qa.creer_compte(monde, usage="lecture_envoi")
            qa.connecter_oauth(monde)
            facture = dbl.courriel_brut(objet="Facture", message_id="<pg1@example.test>", pieces=[
                ("F1.txt", "text/plain", onboarding_qa.texte_corpus("factures/F1-quincaillerie.txt").encode())])
            monde.gmail.ajouter(facture)
            monde.gmail.ajouter(dbl.courriel_brut(objet="Sans pièce", message_id="<pg2@example.test>"))
            rapport = IngestionCourriel(stockage.transaction, acteur="nathan").synchroniser(
                "gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
            assert rapport.statut == "termine" and rapport.nouveaux == 2 and len(rapport.lots) == 1
            with stockage.transaction() as cnx:
                assert cnx.execute(select(func.count()).select_from(COURRIEL_MESSAGES)).scalar_one() == 2
                assert cnx.execute(select(func.count()).select_from(INGESTION_LOTS)).scalar_one() == 1
            with stockage.transaction() as cnx:
                brouillon = envoi.creer_brouillon(cnx, "agent-m1", "gmail-paul", a=["cliente.fictive@example.test"],
                                                  objet="Suite", corps="Bonjour, merci pour votre message.")
                demande = envoi.demander_approbation(cnx, "agent-m1", brouillon.brouillon_id, contexte="Réponse.",
                                                     sources=["gmail:pg1"])
            with stockage.transaction() as cnx:
                assert approbations.decider(cnx, demande, True, "nathan", {NOM_OUTIL: OUTIL_APPROBATION},
                                            {})["statut"] == "executee"
            ServiceEnvoi(stockage.transaction).envoyer(monde.service.fournisseur("gmail-paul"), brouillon.brouillon_id)
            assert len(monde.gmail.envoyes) == 1
            with stockage.transaction() as cnx:
                assert envoi.statut_brouillon(cnx, brouillon.brouillon_id)["statut"] == "ENVOYE"
                assert any(j["evenement"] == "envoi.envoye" for j in comptes.journal(cnx, "gmail-paul"))
        finally:
            stockage.liberer()
