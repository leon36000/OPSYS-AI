"""L'assemblage de production des connecteurs : le service courriel (OAuth, transport, coffre, sas d'envoi) et les
ports du
planificateur.

Tout vient de l'ENVIRONNEMENT du serveur et du coffre de secrets ; rien n'est lu d'un argument d'agent :

- `OPSYS_COURRIEL_REDIRECT_URI` : l'adresse de retour OAuth enregistrée chez le fournisseur (https, ou
  http://localhost) ;
- Gmail : `OPSYS_COURRIEL_GMAIL_CLIENT_ID` (+ `OPSYS_COURRIEL_GMAIL_SECRET`, NOM d'un secret du coffre qui porte
  le secret
  du client) ; Graph : `OPSYS_COURRIEL_GRAPH_CLIENT_ID`, `OPSYS_COURRIEL_GRAPH_TENANT` (+
  `OPSYS_COURRIEL_GRAPH_SECRET`) ;
- `OPSYS_COURRIEL_STATE_SECRET` : le NOM du secret du coffre qui porte la clé de signature du `state` (32 octets
  au moins,
  en base64) ; défaut `courriel.state-cle`.

Le coffre refuse de résoudre un secret DANS une transaction métier : le service est donc construit hors transaction, et
la clé du `state` est capturée à la construction (octets en mémoire le temps de la requête ou du tour).

Aucun transport WordPress ni aucun adaptateur de réseau social réel n'existe : ces ports restent `None` en production
(`non raccordé`) ; les tests y branchent des doubles.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import os
from collections.abc import Callable, Mapping
from typing import Any

from .. import stockage
from ..courriel_connecteurs.envoi import GardeEnvoiSas
from ..courriel_connecteurs.erreurs import ErreurCourriel
from ..courriel_connecteurs.jetons import StockageJetonsCoffre
from ..courriel_connecteurs.oauth import ServiceOAuth, config_gmail, config_graph
from ..courriel_connecteurs.service import ServiceCourriel
from ..courriel_connecteurs.transport import Transport, TransportUrllib
from ..secrets_coffre import coffre
from ..secrets_coffre.erreurs import CoffreErreur
from ..service_acteur_systeme import IDENTIFIANT as ACTEUR_SYSTEME
from .planificateur import Ports

ENV_REDIRECT = "OPSYS_COURRIEL_REDIRECT_URI"
ENV_STATE = "OPSYS_COURRIEL_STATE_SECRET"
STATE_PAR_DEFAUT = "courriel.state-cle"
USAGE_COFFRE = "courriel:oauth"
CHEMIN_RETOUR = "/courriel/oauth/retour"


def _secret_client(nom: str | None) -> Callable[[], contextlib.AbstractContextManager[str]] | None:
    if not nom:
        return None
    return lambda: coffre.utiliser(usage=USAGE_COFFRE, acteur=ACTEUR_SYSTEME, nom=nom)


def cle_state(environ: Mapping[str, str]) -> bytes | None:
    """La clé de signature du `state` (octets), ou `None` si elle n'est pas configurée. Hors transaction."""
    nom = environ.get(ENV_STATE, STATE_PAR_DEFAUT).strip() or STATE_PAR_DEFAUT
    try:
        with coffre.utiliser(usage=USAGE_COFFRE, acteur=ACTEUR_SYSTEME, nom=nom) as valeur:
            brut = base64.b64decode(valeur, validate=True)
    except (CoffreErreur, binascii.Error, ValueError):
        return None
    return brut if len(brut) >= 32 else None


def services_oauth(environ: Mapping[str, str], transport: Transport) -> dict[str, ServiceOAuth]:
    """Les fournisseurs OAuth configurés par l'environnement (aucun : dictionnaire vide, le service dit alors
    `REJ-COURRIEL-OAUTH-CONFIGURATION`)."""
    redirect = environ.get(ENV_REDIRECT, "").strip()
    cle = cle_state(environ)
    services: dict[str, ServiceOAuth] = {}
    if not redirect:
        return services

    def signature() -> bytes:
        if cle is None:
            raise ErreurCourriel("REJ-COURRIEL-OAUTH-CONFIGURATION",
                                 "clé de signature du state absente du coffre (OPSYS_COURRIEL_STATE_SECRET)", 503)
        return cle

    gmail_id = environ.get("OPSYS_COURRIEL_GMAIL_CLIENT_ID", "").strip()
    if gmail_id:
        services["gmail"] = ServiceOAuth(config_gmail(client_id=gmail_id, redirect_uri=redirect), transport, signature,
                                         secret_client=_secret_client(environ.get("OPSYS_COURRIEL_GMAIL_SECRET")))
    graph_id = environ.get("OPSYS_COURRIEL_GRAPH_CLIENT_ID", "").strip()
    if graph_id:
        services["graph"] = ServiceOAuth(
            config_graph(client_id=graph_id, redirect_uri=redirect,
                         tenant=environ.get("OPSYS_COURRIEL_GRAPH_TENANT", "common").strip() or "common"),
            transport, signature, secret_client=_secret_client(environ.get("OPSYS_COURRIEL_GRAPH_SECRET")))
    return services


def construire_service(environ: Mapping[str, str] | None = None, *, transport: Transport | None = None,
                       **options: Any) -> ServiceCourriel:
    """Le service de connexion, d'ingestion et d'envoi des comptes courriel. À appeler HORS transaction."""
    environ = os.environ if environ is None else environ
    transport = transport or TransportUrllib()
    return ServiceCourriel(
        stockage.transaction, transport=transport,
        fabrique_stockage=lambda acteur: StockageJetonsCoffre(stockage.transaction, acteur=acteur),
        oauth=services_oauth(environ, transport), garde_envoi=GardeEnvoiSas(stockage.transaction), **options)


def recepteur_m1() -> Callable[[Any], dict[str, Any]] | None:
    """Le récepteur des courriels entrants de M1 (département présent) ; `None` sinon."""
    try:
        from m1_front_office.courriel_outils import recevoir_courriel_connecteur
    except ImportError:
        return None
    return recevoir_courriel_connecteur


def ports_par_defaut() -> Ports:
    """Les ports de production : courriel réel (urllib, jamais exercé contre un vrai service dans cette version) ;
    WordPress et réseaux sociaux non raccordés."""
    return Ports(service_courriel=construire_service, recepteur_m1=recepteur_m1())
