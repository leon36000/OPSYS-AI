"""Montage de QA des connecteurs courriel (tests seulement) : une instance migrée, un coffre réel, des doubles réseau.

Vrai socle : base SQLite migrée, vrai coffre de secrets (clé maîtresse de test), vraie file d'ingestion d'onboarding,
vrai sas d'approbation, vrai registre de fournisseurs. Seuls le RÉSEAU et les serveurs de courrier sont des doubles
(`courriel_doubles`). Personnes et courriels fictifs.
"""

from __future__ import annotations

import dataclasses
import urllib.parse
from typing import Any

import courriel_doubles as dbl
import ingestion_onboarding_qa as qa

from opsys import stockage
from opsys.courriel_connecteurs import comptes
from opsys.courriel_connecteurs.envoi import GardeEnvoiSas
from opsys.courriel_connecteurs.jetons import StockageJetonsCoffre
from opsys.courriel_connecteurs.oauth import ServiceOAuth, config_gmail, config_graph
from opsys.courriel_connecteurs.service import ServiceCourriel
from opsys.secrets_coffre import cle_maitresse

CLE_SIGNATURE = b"cle-de-signature-fictive-pour-state-oauth-0123456789"
SCOPE_GMAIL_LECTURE = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_GMAIL_ENVOI = "https://www.googleapis.com/auth/gmail.send"
ADMIN = "nathan"


@dataclasses.dataclass
class Monde:
    service: ServiceCourriel
    horloge: dbl.Horloge
    transport: dbl.Aiguilleur
    gmail: dbl.FauxGmail
    graph: dbl.FauxGraph
    oauth_google: dbl.FauxOAuth
    oauth_microsoft: dbl.FauxOAuth
    serveur_imap: dbl.FauxServeurImap
    serveur_smtp: dbl.FauxServeurSmtp
    oauth: dict[str, ServiceOAuth]
    tmp_path: Any


def preparer(
    tmp_path,
    monkeypatch,
    *,
    scope_google: str = SCOPE_GMAIL_LECTURE,
    rotation_google: bool = False,
    scope_microsoft: str = "Mail.Read offline_access",
    rotation_microsoft: bool = True,
) -> Monde:
    qa.preparer_instance(tmp_path, monkeypatch)
    dossier_cle = tmp_path / "cles"
    dossier_cle.mkdir(mode=0o700, exist_ok=True)
    chemin = dossier_cle / "coffre.cle"
    cle_maitresse.generer_fichier(chemin)
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(chemin))
    monkeypatch.delenv(cle_maitresse.ENV_CLE, raising=False)
    horloge = dbl.Horloge()
    gmail, graph = dbl.FauxGmail(), dbl.FauxGraph()
    oauth_google = dbl.FauxOAuth("oauth2.googleapis.com", horloge, scope_accorde=scope_google, rotation=rotation_google)
    oauth_microsoft = dbl.FauxOAuth(
        "login.microsoftonline.com", horloge, scope_accorde=scope_microsoft, rotation=rotation_microsoft
    )
    oauth_google.cibles, oauth_microsoft.cibles = [gmail], [graph]
    transport = dbl.Aiguilleur()
    transport.ajouter(gmail.HOTE, gmail)
    transport.ajouter(graph.HOTE, graph)
    transport.ajouter(oauth_google.HOTE, oauth_google)
    transport.ajouter(oauth_microsoft.HOTE, oauth_microsoft)
    oauth = {
        "gmail": ServiceOAuth(
            config_gmail(
                client_id="client-fictif.apps.example.test", redirect_uri="https://opsys.example.test/oauth/callback"
            ),
            transport,
            lambda: CLE_SIGNATURE,
            horloge=horloge,
        ),
        "graph": ServiceOAuth(
            config_graph(
                client_id="client-fictif-graph",
                tenant="tenant-fictif.example.test",
                redirect_uri="https://opsys.example.test/oauth/callback",
            ),
            transport,
            lambda: CLE_SIGNATURE,
            horloge=horloge,
        ),
    }
    serveur_imap = dbl.FauxServeurImap()
    serveur_smtp = dbl.FauxServeurSmtp(serveur_imap.utilisateur, serveur_imap.mot_de_passe)
    service = ServiceCourriel(
        stockage.transaction,
        transport=transport,
        fabrique_stockage=lambda acteur: StockageJetonsCoffre(stockage.transaction, acteur=acteur),
        oauth=oauth,
        horloge=horloge,
        dormir=horloge.dormir,
        fabrique_imap=dbl.FauxImap4SSL(serveur_imap),
        fabrique_smtp=dbl.FauxSmtpSSL(serveur_smtp),
        garde_envoi=GardeEnvoiSas(stockage.transaction),
    )
    return Monde(
        service,
        horloge,
        transport,
        gmail,
        graph,
        oauth_google,
        oauth_microsoft,
        serveur_imap,
        serveur_smtp,
        oauth,
        tmp_path,
    )


def creer_compte(
    monde: Monde,
    compte_id: str = "gmail-paul",
    fournisseur: str = "gmail",
    usage: str = "lecture",
    adresse: str = "paul.fictif@example.test",
    configuration: dict | None = None,
    consentement: bool = True,
    dossiers: tuple[str, ...] = ("INBOX",),
) -> dict:
    with stockage.transaction() as cnx:
        vue = comptes.creer_compte(
            cnx,
            ADMIN,
            compte_id=compte_id,
            fournisseur=fournisseur,
            adresse=adresse,
            usage=usage,
            finalite="Onboarding : reprise des factures fournisseurs reçues par courriel",
            retention_jours=365,
            configuration=configuration,
            dossiers_suivis=dossiers,
        )
        if consentement:
            vue = comptes.enregistrer_consentement(cnx, ADMIN, compte_id)
    return vue


def connecter_oauth(monde: Monde, compte_id: str = "gmail-paul") -> dict:
    """Parcours complet : URL d'autorisation, consentement simulé chez le fournisseur, retour avec le code."""
    url = monde.service.demarrer_autorisation(ADMIN, compte_id)
    params = urllib.parse.parse_qs(urllib.parse.urlsplit(url.url).query)
    fournisseur = comptes_fournisseur(compte_id)
    faux = monde.oauth_google if fournisseur == "gmail" else monde.oauth_microsoft
    code = f"code-fictif-{compte_id}"
    faux.autoriser(code, params["code_challenge"][0])
    return monde.service.terminer_autorisation(ADMIN, params["state"][0], code)


def comptes_fournisseur(compte_id: str) -> str:
    with stockage.transaction() as cnx:
        return comptes.ligne_brute(cnx, compte_id)["fournisseur"]


def connecter_imap(monde: Monde, compte_id: str = "imap-paul", usage: str = "lecture") -> dict:
    creer_compte(
        monde,
        compte_id,
        "imap",
        usage,
        configuration={
            "hote": "imap.example.test",
            "port": 993,
            "smtp_hote": "smtp.example.test",
            "smtp_port": 465,
            "utilisateur": monde.serveur_imap.utilisateur,
        },
    )
    return monde.service.enregistrer_mot_de_passe_imap(ADMIN, compte_id, monde.serveur_imap.mot_de_passe)
