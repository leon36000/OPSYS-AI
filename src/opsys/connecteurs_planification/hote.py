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
(`non raccordé`) ; les tests y branchent des doubles. Il en va de même des connecteurs de signaux, de la veille et des
générateurs du studio (planification autonome).

Trois ports de la planification autonome SONT raccordés en production parce que leur « transport » est local :

- `dossier_traces` : le journal de traces de l'instance (`<OPSYS_HOME>/traces`, clés dérivées de la clé locale) ; sa
  rétention vient de `OPSYS_TRACES_RETENTION_JOURS` (30 par défaut) ;
- `verifier_sauvegarde` : seulement si l'opérateur a nommé le dossier des sauvegardes
  (`OPSYS_PLANIF_SAUVEGARDES_DOSSIER`)
  ET la clé de sauvegarde (`OPSYS_SAUVEGARDE_CLE_FICHIER`) pour le processus du serveur : donner cette clé au serveur
  est une décision d'exploitation (la politique veut la clé hors de l'instance), jamais prise par défaut ;
- `embeddings_raccordes` : vrai dès qu'un adaptateur d'embeddings est enregistré (aucun ne l'est dans cette version).
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


def journal_traces(environ: Mapping[str, str] | None = None) -> Any:
    """Le journal de traces à purger, ou `None` si l'instance n'en a pas (rien à purger). Dossier présent mais clé
    locale absente : en attente (on ne purge pas un journal qu'on ne sait pas ouvrir)."""
    from ..observabilite import cle_locale
    from ..observabilite.traces import JournalTraces, retention_jours_env
    from .planificateur import EnAttenteTransport

    environ = os.environ if environ is None else environ
    dossier = stockage.dossier_opsys() / "traces"
    if not dossier.is_dir():
        return None
    try:
        cle = cle_locale.deriver(cle_locale.charger(), "traces/chaine/v1")
    except Exception:  # noqa: BLE001 — clé absente ou illisible : le motif exact n'a pas à fuir
        raise EnAttenteTransport("REJ-PLAN-TRACES-CLE-ABSENTE") from None
    return JournalTraces(dossier, cle, retention_jours=retention_jours_env(environ))


def verifier_sauvegarde_depuis_env(environ: Mapping[str, str] | None = None
                                   ) -> Callable[[], Mapping[str, Any]] | None:
    """Le vérificateur de sauvegardes si l'opérateur l'a configuré (dossier ET clé), sinon `None`."""
    from pathlib import Path

    from .. import sauvegarde_chiffree as sauvegarde

    environ = os.environ if environ is None else environ
    dossier = environ.get("OPSYS_PLANIF_SAUVEGARDES_DOSSIER", "").strip()
    if not dossier or not environ.get(sauvegarde.ENV_CLE_FICHIER, "").strip():
        return None

    def verifier(maintenant: float | None = None) -> Mapping[str, Any]:
        import datetime as dt
        import time

        racine = Path(dossier)
        trouvees = sorted((p for p in racine.iterdir() if sauvegarde._NOM_SAUVEGARDE.match(p.name) and p.is_file()),
                          key=lambda p: p.name) if racine.is_dir() else []
        if not trouvees:
            return {"trouvee": False}
        derniere = trouvees[-1]
        horodatage = sauvegarde._NOM_SAUVEGARDE.match(derniere.name).group(1)  # type: ignore[union-attr]
        age = int((time.time() if maintenant is None else maintenant)
                  - dt.datetime.strptime(horodatage, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC).timestamp())
        try:
            sauvegarde.verifier(derniere, environ=environ)
        except sauvegarde.ErreurSauvegarde as exc:
            return {"trouvee": True, "authentique": False, "code": exc.code, "age_s": age}
        return {"trouvee": True, "authentique": True, "age_s": age}

    return verifier


def embeddings_raccordes() -> bool:
    from ..connaissances import ports as ports_connaissances

    return bool(ports_connaissances._ADAPTATEURS_EMBEDDINGS)  # noqa: SLF001 — lecture de la table d'adaptateurs


def ports_par_defaut() -> Ports:
    """Les ports de production : courriel réel (urllib, jamais exercé contre un vrai service dans cette version) ;
    WordPress, réseaux sociaux, signaux, veille et studio non raccordés ; traces, sauvegardes et embeddings locaux."""
    return Ports(service_courriel=construire_service, recepteur_m1=recepteur_m1(), dossier_traces=journal_traces,
                 verifier_sauvegarde=verifier_sauvegarde_depuis_env(), embeddings_raccordes=embeddings_raccordes)
