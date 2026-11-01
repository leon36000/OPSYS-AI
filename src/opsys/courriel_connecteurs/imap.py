"""Adaptateur IMAP / SMTP générique, en bibliothèque standard (`imaplib`, `smtplib`) : mot de passe d'APPLICATION.

- Le mot de passe vit dans le coffre (`jetons.StockageJetons`, champ `access_token` d'un `JeuJetons` sans expiration) ;
  il n'est lu qu'au moment de la connexion et n'est jamais journalisé ni mis dans une erreur.
- Connexion TLS implicite seulement (`IMAP4_SSL`, `SMTP_SSL`) ; les fabriques sont INJECTÉES (`fabrique_imap`,
  `fabrique_smtp`) : les tests branchent un faux serveur en mémoire, aucun socket réel. L'hôte est refusé s'il s'agit
  d'une adresse IP privée ou de `localhost` (SSRF).
- Curseur opaque `imap:v1:…` = (dossier, UIDVALIDITY, dernier UID traité). Si UIDVALIDITY change, les UID ne veulent
  plus rien dire : `REJ-COURRIEL-CURSEUR-EXPIRE` (nouvel amorçage, l'idempotence évite les doublons). `UID n:*` renvoie
  TOUJOURS au moins le dernier message, même si son UID est inférieur à `n` : les UID sont donc refiltrés.
- Lecture seule : `SELECT` en lecture seule et `BODY.PEEK[]` (le message n'est jamais marqué lu). La taille est demandée
  AVANT le téléchargement (`RFC822.SIZE`).
- Injection de commande : un nom de dossier, un utilisateur ou un mot de passe contenant CR, LF ou NUL est refusé avant
  tout envoi sur le fil ; les noms sont mis entre guillemets et échappés.
- Limites assumées : pas de QRESYNC/CONDSTORE (une suppression ou un changement de drapeau n'est pas vu), pas d'OAuth
  XOAUTH2, pas de STARTTLS, un seul niveau de dossiers listés tels que le serveur les rend.

Jamais testé contre un vrai serveur : seulement contre `FauxImap4SSL` (tests/fixtures/courriel_doubles.py).
"""

from __future__ import annotations

import base64
import contextlib
import imaplib
import ipaddress
import re
import smtplib
import ssl
from collections.abc import Callable
from typing import Any

from .erreurs import ErreurCourriel
from .jetons import StockageJetons, masquer_pendant
from .modele import (
    Boite,
    BrouillonSortant,
    Dossier,
    MessageBrut,
    PageSync,
    RefMessage,
)
from .normalisation import SOURCE_MAX
from .port import (
    EnvoiSousGarde,
    GardeEnvoi,
    Issue,
    construire_mime,
    decoder_curseur,
    encoder_curseur,
    limite_valide,
)

DELAI_S = 30.0
_ETIQUETTE = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOTE = re.compile(rf"^(?=.{{1,253}}$){_ETIQUETTE}(?:\.{_ETIQUETTE})+$")
_LISTE = re.compile(r'^\((?P<drapeaux>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<nom>.+)$', re.DOTALL)
_ROLES = {"\\sent": "sent", "\\trash": "trash", "\\drafts": "drafts", "\\junk": "junk", "\\archive": "archive",
          "\\all": "all"}
_UIDVALIDITY = re.compile(r"^[1-9][0-9]{0,9}$")
_TAILLE = re.compile(rb"RFC822\.SIZE\s+(\d+)")
_INTERDITS = re.compile(r"[\x00\r\n]")


def decoder_mutf7(nom: str) -> str:
    """Nom de dossier IMAP (UTF-7 modifié, RFC 3501 §5.1.3) lisible, pour l'AFFICHAGE seulement."""
    def morceau(m: re.Match[str]) -> str:
        if m.group(1) == "":
            return "&"
        brut = m.group(1).replace(",", "/")
        try:
            return base64.b64decode(brut + "=" * (-len(brut) % 4)).decode("utf-16-be")
        except (ValueError, UnicodeError):
            return m.group(0)
    return re.sub(r"&([^-]*)-", morceau, nom)


def _citer(valeur: str, nature: str) -> str:
    if not isinstance(valeur, str) or not valeur or len(valeur) > 255 or _INTERDITS.search(valeur):
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", f"{nature} invalide (vide, trop long ou caractère de "
                             "contrôle)", 422)
    return '"' + valeur.replace("\\", "\\\\").replace('"', '\\"') + '"'


def verifier_hote(hote: str) -> str:
    """Nom d'hôte public ou adresse IP globale ; refuse `localhost`, `.local`, `.internal` et toute IP privée (SSRF)."""
    if not isinstance(hote, str):
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "hôte IMAP/SMTP invalide", 422)
    try:
        adresse = ipaddress.ip_address(hote)
    except ValueError:
        adresse = None
    if adresse is not None:
        if not adresse.is_global:
            raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "adresse privée ou spéciale refusée", 422)
        return hote
    if (not _HOTE.fullmatch(hote) or hote.lower() == "localhost"
            or hote.lower().endswith((".localhost", ".local", ".internal"))):
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "hôte IMAP/SMTP invalide", 422)
    return hote


def _lignes(donnees: list[Any]) -> list[bytes]:
    sortie = []
    for element in donnees or []:
        if isinstance(element, tuple):
            sortie.append(element[0])
        elif isinstance(element, (bytes, bytearray)):
            sortie.append(bytes(element))
    return sortie


class FournisseurImap(EnvoiSousGarde):
    identifiant = "imap"

    def __init__(self, *, hote: str, port: int, smtp_hote: str, smtp_port: int, utilisateur: str, adresse: str,
                 nom_secret: str, stockage: StockageJetons,
                 fabrique_imap: Callable[..., Any] = imaplib.IMAP4_SSL,
                 fabrique_smtp: Callable[..., Any] = smtplib.SMTP_SSL, garde_envoi: GardeEnvoi | None = None) -> None:
        self._hote, self._port = verifier_hote(hote), port
        self._smtp_hote, self._smtp_port = verifier_hote(smtp_hote), smtp_port
        _citer(utilisateur, "utilisateur")
        self._utilisateur, self._adresse, self._nom_secret, self._stockage = utilisateur, adresse, nom_secret, stockage
        self._fabrique_imap, self._fabrique_smtp, self._garde = fabrique_imap, fabrique_smtp, garde_envoi

    # -- connexion ------------------------------------------------------------------------------------------------
    def _mot_de_passe(self) -> str:
        mot = self._stockage.lire(self._nom_secret).access_token
        if _INTERDITS.search(mot):
            raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "mot de passe d'application invalide", 422)
        return mot

    def _ouvrir(self) -> Any:
        mot = self._mot_de_passe()
        try:
            session = self._fabrique_imap(self._hote, self._port, timeout=DELAI_S)
            with masquer_pendant(_JeuMot(mot)):
                session.login(self._utilisateur, mot)
        except (TimeoutError, OSError, ssl.SSLError, imaplib.IMAP4.abort):
            raise ErreurCourriel("REJ-COURRIEL-RESEAU", "serveur IMAP injoignable", 503, reprenable=True) from None
        except imaplib.IMAP4.error:
            raise ErreurCourriel("REJ-COURRIEL-IMAP-AUTH", "connexion IMAP refusée : mot de passe d'application "
                                 "invalide ou IMAP désactivé", 401) from None
        return session

    @staticmethod
    def _fermer(session: Any) -> None:
        try:
            session.logout()
        except Exception:  # noqa: BLE001 — la fermeture ne masque jamais l'erreur d'origine
            return

    @staticmethod
    def _ok(reponse: Any, nature: str) -> list[Any]:
        try:
            statut, donnees = reponse
        except (TypeError, ValueError):
            raise ErreurCourriel("REJ-COURRIEL-IMAP-PROTOCOLE", f"réponse IMAP illisible ({nature})", 502) from None
        if statut != "OK":
            raise ErreurCourriel("REJ-COURRIEL-IMAP-PROTOCOLE", f"commande IMAP refusée ({nature})", 502)
        return donnees

    # -- lecture --------------------------------------------------------------------------------------------------
    def lister_boites(self) -> list[Boite]:
        return [Boite(id=self._adresse, adresse=self._adresse, fournisseur=self.identifiant)]

    def lister_dossiers(self) -> list[Dossier]:
        session = self._ouvrir()
        try:
            donnees = self._ok(session.list(), "LIST")
        except (imaplib.IMAP4.error, OSError):
            raise ErreurCourriel("REJ-COURRIEL-IMAP-PROTOCOLE", "LIST IMAP en échec", 502) from None
        finally:
            self._fermer(session)
        dossiers = []
        for ligne in _lignes(donnees):
            trouve = _LISTE.match(ligne.decode("utf-8", "replace").strip())
            if trouve is None:
                continue
            drapeaux = {d.lower() for d in trouve["drapeaux"].split()}
            if "\\noselect" in drapeaux:
                continue
            nom = trouve["nom"].strip()
            if nom.startswith('"') and nom.endswith('"') and len(nom) >= 2:
                nom = re.sub(r"\\(.)", r"\1", nom[1:-1])
            role = next((r for d, r in _ROLES.items() if d in drapeaux), "inbox" if nom.upper() == "INBOX" else None)
            dossiers.append(Dossier(nom, decoder_mutf7(nom), role))
        return dossiers

    def _selectionner(self, session: Any, dossier: str) -> str:
        try:
            self._ok(session.select(_citer(dossier, "dossier"), readonly=True), "SELECT")
            valeur = _lignes(session.response("UIDVALIDITY")[1])
        except imaplib.IMAP4.error:
            raise ErreurCourriel("REJ-COURRIEL-IMAP-PROTOCOLE", "SELECT IMAP refusé", 502) from None
        if not valeur or not _UIDVALIDITY.fullmatch(valeur[0].decode("ascii", "replace")):
            raise ErreurCourriel("REJ-COURRIEL-IMAP-PROTOCOLE", "UIDVALIDITY absent ou illisible", 502)
        return valeur[0].decode("ascii")

    def synchroniser(self, dossier: str, curseur: str | None, *, limite: int = 100) -> PageSync:
        limite = limite_valide(limite)
        dernier, validite_connue = 0, None
        if curseur is not None:
            etat = decoder_curseur("imap", curseur)
            if (etat.get("d") != dossier or type(etat.get("u")) is not int or etat["u"] < 0
                    or not isinstance(etat.get("v"), str) or not _UIDVALIDITY.fullmatch(etat["v"])):
                raise ErreurCourriel("REJ-COURRIEL-CURSEUR-INVALIDE", "curseur IMAP mal formé ou d'un autre dossier",
                                     422)
            dernier, validite_connue = etat["u"], etat["v"]
        session = self._ouvrir()
        try:
            validite = self._selectionner(session, dossier)
            if validite_connue is not None and validite != validite_connue:
                raise ErreurCourriel("REJ-COURRIEL-CURSEUR-EXPIRE", "UIDVALIDITY a changé : les UID mémorisés sont "
                                     "caducs, relancer un amorçage complet", 409, reprenable=True)
            donnees = self._ok(session.uid("SEARCH", None, "UID", f"{dernier + 1}:*"), "UID SEARCH")
        except (imaplib.IMAP4.error, OSError):
            raise ErreurCourriel("REJ-COURRIEL-IMAP-PROTOCOLE", "recherche IMAP en échec", 502) from None
        finally:
            self._fermer(session)
        uids = sorted({int(x) for ligne in _lignes(donnees) for x in ligne.split() if x.isdigit()})
        uids = [u for u in uids if u > dernier]
        lot = uids[:limite]
        fin = lot[-1] if lot else dernier
        curseur_suivant = encoder_curseur("imap", {"d": dossier, "v": validite, "u": fin})
        return PageSync(tuple(RefMessage(f"{validite}:{u}", dossier) for u in lot), (), curseur_suivant,
                        len(uids) <= limite)

    def lire_message(self, ref: RefMessage) -> MessageBrut:
        trouve = re.fullmatch(r"([1-9][0-9]{0,9}):([1-9][0-9]{0,9})", ref.ref)
        if trouve is None:
            raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "référence de message IMAP invalide", 422)
        validite, uid = trouve.group(1), trouve.group(2)
        session = self._ouvrir()
        try:
            if self._selectionner(session, ref.dossier) != validite:
                raise ErreurCourriel("REJ-COURRIEL-CURSEUR-EXPIRE", "UIDVALIDITY a changé depuis le listage", 409,
                                     reprenable=True)
            taille = _lignes(self._ok(session.uid("FETCH", uid, "(RFC822.SIZE)"), "FETCH SIZE"))
            mesure = _TAILLE.search(b" ".join(taille))
            if mesure is None:
                raise ErreurCourriel("REJ-COURRIEL-INTROUVABLE", "message absent du dossier", 404)
            if int(mesure.group(1)) > SOURCE_MAX:
                raise ErreurCourriel("REJ-COURRIEL-MESSAGE-TROP-GROS", "message de plus de 32 Mio", 413)
            donnees = self._ok(session.uid("FETCH", uid, "(BODY.PEEK[])"), "FETCH")
        except (imaplib.IMAP4.error, OSError):
            raise ErreurCourriel("REJ-COURRIEL-IMAP-PROTOCOLE", "lecture IMAP en échec", 502) from None
        finally:
            self._fermer(session)
        for element in donnees:
            if isinstance(element, tuple) and len(element) == 2 and isinstance(element[1], (bytes, bytearray)):
                return MessageBrut(ref.ref, ref.dossier, bytes(element[1]))
        raise ErreurCourriel("REJ-COURRIEL-INTROUVABLE", "message absent du dossier", 404)

    # -- envoi (jamais direct : voir port.EnvoiSousGarde) ------------------------------------------------------------
    def _transmettre(self, brouillon: BrouillonSortant) -> Issue:
        c = brouillon.contenu
        message = construire_mime(brouillon, avec_bcc=False)
        mot = self._mot_de_passe()
        try:
            serveur = self._fabrique_smtp(self._smtp_hote, self._smtp_port, timeout=DELAI_S)
        except (OSError, ssl.SSLError):
            raise ErreurCourriel("REJ-COURRIEL-ENVOI-ECHEC", "connexion SMTP impossible : rien n'a été envoyé",
                                 503) from None
        try:
            with masquer_pendant(_JeuMot(mot)):
                try:
                    serveur.login(self._utilisateur, mot)
                except smtplib.SMTPAuthenticationError:
                    raise ErreurCourriel("REJ-COURRIEL-IMAP-AUTH",
                                         "authentification SMTP refusée : rien n'a été envoyé",
                                         401) from None
                except (smtplib.SMTPException, OSError):
                    raise ErreurCourriel("REJ-COURRIEL-ENVOI-ECHEC", "connexion SMTP impossible : rien n'a été envoyé",
                                         503) from None
                try:
                    serveur.send_message(message, from_addr=c.de, to_addrs=[*c.a, *c.cc, *c.cci])
                except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError,
                        smtplib.SMTPNotSupportedError):
                    raise ErreurCourriel("REJ-COURRIEL-ENVOI-ECHEC", "le serveur SMTP a refusé le message ou des "
                                         "destinataires", 422) from None
        finally:
            with contextlib.suppress(Exception):  # la fermeture ne masque jamais l'issue de l'envoi
                serveur.quit()
        return "envoye"


class _JeuMot:
    """Adapte un mot de passe au masquage (qui attend des `valeurs_secretes`)."""

    def __init__(self, mot: str) -> None:
        self._mot = mot

    def valeurs_secretes(self) -> tuple[str, ...]:
        return (self._mot,)
