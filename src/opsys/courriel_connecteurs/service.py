"""Service de connexion des comptes : autorisation OAuth, mot de passe d'application, fabrique d'adaptateurs,
révocation.

Ce service orchestre ; il ne contient aucune logique de protocole (elle est dans les adaptateurs) et ne touche jamais un
secret autrement que par le `StockageJetons` (coffre). Chaque opération d'administration exige une personne active
`nathan_owner` ou `admin`, relue en base.

Les états d'un compte : `non_connecte` -> `autorisation_en_cours` -> `connecte` ; `reconnexion_requise` quand le
fournisseur refuse le jeton (révoqué, expiré sans rafraîchissement, 401 répété) ; `revoque` (terminal : un nom de secret
révoqué n'est jamais réutilisé, un nouveau compte repart de zéro) ; `erreur` pour un échec d'autorisation.
"""

from __future__ import annotations

import imaplib
import json
import smtplib
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from sqlalchemy import Connection

from . import comptes, gmail, graph
from .client_oauth import ClientApi, GestionnaireJetons
from .erreurs import ErreurCourriel
from .imap import FournisseurImap
from .jetons import SERVICES_COFFRE, JeuJetons, StockageJetons
from .mbox import FournisseurMbox
from .oauth import ServiceOAuth, UrlAutorisation
from .port import FournisseurCourriel, GardeEnvoi
from .transport import Transport

FabriqueConnexion = Callable[[], AbstractContextManager[Connection]]
CODES_RECONNEXION = frozenset({
    "REJ-COURRIEL-JETON-REVOQUE", "REJ-COURRIEL-JETON-EXPIRE", "REJ-COURRIEL-AUTH-REFUSEE",
    "REJ-COURRIEL-REFRESH-ABSENT",
    "REJ-COURRIEL-COFFRE-REFUSE", "REJ-COURRIEL-IMAP-AUTH", "REJ-COURRIEL-PORTEE-EXCESSIVE",
    "REJ-COURRIEL-PORTEE-INSUFFISANTE",
})


class ServiceCourriel:
    def __init__(self, fabrique: FabriqueConnexion, *, transport: Transport,
                 fabrique_stockage: Callable[[str], StockageJetons], oauth: dict[str, ServiceOAuth] | None = None,
                 horloge: Callable[[], float] = time.time, dormir: Callable[[float], None] = time.sleep,
                 fabrique_imap: Callable[..., Any] = imaplib.IMAP4_SSL,
                 fabrique_smtp: Callable[..., Any] = smtplib.SMTP_SSL, garde_envoi: GardeEnvoi | None = None,
                 dossier_imports: Path | None = None) -> None:
        self._fabrique, self._transport, self._fabrique_stockage = fabrique, transport, fabrique_stockage
        self._oauth = oauth or {}
        self._horloge, self._dormir = horloge, dormir
        self._fabrique_imap, self._fabrique_smtp, self._garde = fabrique_imap, fabrique_smtp, garde_envoi
        self._dossier_imports = dossier_imports

    def _oauth_de(self, fournisseur: str) -> ServiceOAuth:
        service = self._oauth.get(fournisseur)
        if service is None:
            raise ErreurCourriel("REJ-COURRIEL-OAUTH-CONFIGURATION", f"OAuth non configuré pour {fournisseur}", 503)
        return service

    # -- OAuth ----------------------------------------------------------------------------------------------------
    def demarrer_autorisation(self, acteur: str, compte_id: str) -> UrlAutorisation:
        with self._fabrique() as cnx:
            comptes.exiger_admin(cnx, acteur)
            ligne = comptes.ligne_brute(cnx, compte_id)
            if ligne["fournisseur"] not in {"gmail", "graph"}:
                raise ErreurCourriel("REJ-COURRIEL-FOURNISSEUR-INCONNU", "ce fournisseur n'utilise pas OAuth", 422)
            comptes.exiger_consentement(ligne)
            if ligne["etat"] == "revoque":
                raise ErreurCourriel("REJ-COURRIEL-COMPTE-INACTIF", "compte révoqué", 409)
            url = self._oauth_de(ligne["fournisseur"]).url_autorisation(cnx, compte_id, ligne["usage"])
            comptes.changer_etat(cnx, compte_id, "autorisation_en_cours", acteur, evenement="oauth.demarre")
        return url

    def terminer_autorisation(self, acteur: str, state: str, code: str) -> dict[str, Any]:
        # 1. Le state est consommé et VALIDÉ même si l'échange échoue ensuite (usage unique).
        with self._fabrique() as cnx:
            comptes.exiger_admin(cnx, acteur)
            fournisseur = self._fournisseur_du_state(state)
            oauth = self._oauth_de(fournisseur)
            donnees = oauth.consommer_state(cnx, state)
            ligne = comptes.ligne_brute(cnx, donnees["c"])
            if ligne["fournisseur"] != fournisseur or ligne["etat"] != "autorisation_en_cours":
                raise ErreurCourriel("REJ-COURRIEL-OAUTH-ETAT-INVALIDE",
                                     "aucune autorisation en cours pour ce compte", 400)
            comptes.exiger_consentement(ligne)
            generation = ligne["generation"] + 1
        # 2. Échange hors transaction (réseau), portées vérifiées.
        try:
            echange = oauth.echanger_code(donnees, code)
        except ErreurCourriel as exc:
            with self._fabrique() as cnx:
                comptes.changer_etat(cnx, donnees["c"], "erreur", acteur, code=exc.code, evenement="oauth.echec")
            raise
        # 3. Jetons dans le coffre, puis état du compte.
        nom = comptes.nom_secret(donnees["c"], generation)
        self._fabrique_stockage(acteur).ecrire(nom, echange.jeu, service=SERVICES_COFFRE[fournisseur])
        with self._fabrique() as cnx:
            comptes.marquer_connecte(cnx, donnees["c"], acteur, secret_nom=nom, generation=generation,
                                     portees=echange.jeu.portees)
            return comptes.lire(cnx, donnees["c"])

    @staticmethod
    def _fournisseur_du_state(state: str) -> str:
        import base64

        try:
            charge = state.split(".")[0]
            return json.loads(base64.urlsafe_b64decode(charge + "=" * (-len(charge) % 4)))["f"]
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            raise ErreurCourriel("REJ-COURRIEL-OAUTH-ETAT-INVALIDE", "state mal formé", 400) from None

    # -- IMAP : mot de passe d'application ----------------------------------------------------------------------------
    def enregistrer_mot_de_passe_imap(self, acteur: str, compte_id: str, mot_de_passe: str) -> dict[str, Any]:
        with self._fabrique() as cnx:
            comptes.exiger_admin(cnx, acteur)
            ligne = comptes.ligne_brute(cnx, compte_id)
            if ligne["fournisseur"] != "imap":
                raise ErreurCourriel("REJ-COURRIEL-FOURNISSEUR-INCONNU", "compte non IMAP", 422)
            comptes.exiger_consentement(ligne)
            if ligne["etat"] == "revoque":
                raise ErreurCourriel("REJ-COURRIEL-COMPTE-INACTIF", "compte révoqué", 409)
            generation = ligne["generation"] + 1
        if (not isinstance(mot_de_passe, str) or not mot_de_passe.strip() or len(mot_de_passe) > 512
                or any(c in mot_de_passe for c in "\x00\r\n")):
            raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "mot de passe d'application invalide", 422)
        nom = comptes.nom_secret(compte_id, generation)
        self._fabrique_stockage(acteur).ecrire(nom, JeuJetons(mot_de_passe, None, 0, frozenset()), service="autre")
        with self._fabrique() as cnx:
            comptes.marquer_connecte(cnx, compte_id, acteur, secret_nom=nom, generation=generation, portees=frozenset())
            return comptes.lire(cnx, compte_id)

    # -- export mbox : lecture seule d'un fichier déposé
    # ------------------------------------------------------------------
    def connecter_export_mbox(self, acteur: str, compte_id: str) -> dict[str, Any]:
        """Un compte « mbox » n'a ni secret ni jeton : le fichier est lu par son nom, dans le dossier d'imports."""
        with self._fabrique() as cnx:
            comptes.exiger_admin(cnx, acteur)
            ligne = comptes.ligne_brute(cnx, compte_id)
            if ligne["fournisseur"] != "mbox":
                raise ErreurCourriel("REJ-COURRIEL-FOURNISSEUR-INCONNU", "compte non mbox", 422)
            comptes.exiger_consentement(ligne)
            FournisseurMbox(json.loads(ligne["configuration"]).get("fichier", ""))  # valide le nom et l'existence
            comptes.changer_etat(cnx, compte_id, "connecte", acteur, evenement="compte.connecte")
            return comptes.lire(cnx, compte_id)

    # -- adaptateurs ------------------------------------------------------------------------------------------------
    def fournisseur(self, compte_id: str) -> FournisseurCourriel:
        with self._fabrique() as cnx:
            ligne = dict(comptes.ligne_brute(cnx, compte_id))
        if ligne["etat"] != "connecte":
            raise ErreurCourriel("REJ-COURRIEL-COMPTE-INACTIF", f"compte non connecté ({ligne['etat']})", 409)
        configuration = json.loads(ligne["configuration"])
        if ligne["fournisseur"] == "mbox":
            return FournisseurMbox(configuration["fichier"], dossier=self._dossier_imports)
        stockage = self._fabrique_stockage(ligne["connecte_par"])
        if ligne["fournisseur"] == "imap":
            return FournisseurImap(
                hote=configuration["hote"], port=int(configuration.get("port", 993)),
                smtp_hote=configuration.get("smtp_hote", configuration["hote"]),
                smtp_port=int(configuration.get("smtp_port", 465)),
                utilisateur=configuration.get("utilisateur", ligne["adresse"]), adresse=ligne["adresse"],
                nom_secret=ligne["secret_nom"], stockage=stockage, fabrique_imap=self._fabrique_imap,
                fabrique_smtp=self._fabrique_smtp,
                garde_envoi=self._garde if ligne["usage"] == "lecture_envoi" else None)
        oauth = self._oauth_de(ligne["fournisseur"])
        jetons = GestionnaireJetons(ligne["secret_nom"], stockage, oauth, usage=ligne["usage"],
                                    service=SERVICES_COFFRE[ligne["fournisseur"]], horloge=self._horloge,
                                    rapport=lambda nom, d: self._rapport(compte_id, nom, d))
        garde = self._garde if ligne["usage"] == "lecture_envoi" else None
        if ligne["fournisseur"] == "gmail":
            client = ClientApi(self._transport, jetons, hotes=gmail.HOTES, dormir=self._dormir, horloge=self._horloge,
                               rapport=lambda nom, d: self._rapport(compte_id, nom, d))
            return gmail.FournisseurGmail(client, garde_envoi=garde)
        client = ClientApi(self._transport, jetons, hotes=graph.HOTES, dormir=self._dormir, horloge=self._horloge,
                           rapport=lambda nom, d: self._rapport(compte_id, nom, d))
        return graph.FournisseurGraph(client, adresse=ligne["adresse"], garde_envoi=garde)

    def _rapport(self, compte_id: str, nom: str, details: Any) -> None:
        permis = {k: v for k, v in dict(details).items() if k in comptes.DETAILS_PERMIS}
        with self._fabrique() as cnx:
            comptes.journaliser(cnx, compte_id, nom, "systeme", details=permis)

    def signaler_erreur(self, compte_id: str, exc: ErreurCourriel, acteur: str = "systeme") -> None:
        """Reflète une erreur typée de l'adaptateur dans l'état du compte (visible côté admin)."""
        with self._fabrique() as cnx:
            if exc.code in CODES_RECONNEXION:
                comptes.changer_etat(cnx, compte_id, "reconnexion_requise", acteur, code=exc.code,
                                     evenement="compte.erreur")
            else:
                comptes.noter_erreur(cnx, compte_id, acteur, exc.code)

    # -- révocation ------------------------------------------------------------------------------------------------
    def revoquer(self, acteur: str, compte_id: str) -> dict[str, Any]:
        """Révoque le compte : jeton révoqué chez le fournisseur si possible, secret détruit dans le coffre, état
        terminal `revoque`. Les originaux déjà ingérés suivent leur propre cycle de rétention (pas de suppression
        ici)."""
        with self._fabrique() as cnx:
            comptes.exiger_admin(cnx, acteur)
            ligne = dict(comptes.ligne_brute(cnx, compte_id))
        revoque_chez_fournisseur = False
        if ligne["secret_nom"] and ligne["etat"] != "revoque":
            stockage = self._fabrique_stockage(acteur)
            if ligne["fournisseur"] in {"gmail", "graph"}:
                try:
                    revoque_chez_fournisseur = self._oauth_de(ligne["fournisseur"]).revoquer_chez_fournisseur(
                        stockage.lire(ligne["secret_nom"]))
                except ErreurCourriel:
                    revoque_chez_fournisseur = False  # le coffre est quand même purgé ci-dessous
            stockage.revoquer(ligne["secret_nom"])
        with self._fabrique() as cnx:
            comptes.changer_etat(cnx, compte_id, "revoque", acteur, evenement="compte.revoque")
            comptes.journaliser(cnx, compte_id, "compte.revocation", acteur,
                                details={"statut": "fournisseur" if revoque_chez_fournisseur else "local"})
            return comptes.lire(cnx, compte_id)
