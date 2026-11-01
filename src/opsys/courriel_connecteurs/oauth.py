"""Cycle OAuth 2.0 côté SERVEUR (sans navigateur ici) : URL d'autorisation PKCE, `state` signé à usage unique,
échange du code, rafraîchissement (avec rotation du refresh token), révocation, portées vérifiées.

- **PKCE (S256)** : le `code_verifier` n'est jamais stocké : il se re-dérive du `nonce` du `state` par HMAC avec une clé
  serveur (`cle_signature`, tirée du coffre en production). Le `state` porte (nonce, compte, fournisseur, usage,
  expiration) et sa signature HMAC-SHA256 ; il est refusé s'il est falsifié, expiré ou DÉJÀ UTILISÉ (la table
  `courriel_etats_oauth` consomme le nonce par comparaison-échange atomique).
- **Portées minimales** (`PolitiquePortees`) : la liste de ce qu'OPSYS demande est fermée par fournisseur ; à
  l'échange ET à chaque rafraîchissement, la portée ACCORDÉE est comparée : toute portée excessive est un refus typé
  (`REJ-COURRIEL-PORTEE-EXCESSIVE`, rien n'est stocké), une portée de lecture manquante aussi
  (`REJ-COURRIEL-PORTEE-INSUFFISANTE`). Aucun scope restreint inutile : Gmail lecture = `gmail.readonly` seul ; l'envoi
  (`gmail.send`, `Mail.Send`) n'est demandé que si l'usage `lecture_envoi` est choisi.
- Les appels au fournisseur passent par le `Transport` injecté. Aucun secret (code, jeton, secret client) n'entre dans
  une erreur : les détails ne portent que le champ `error` du fournisseur, assaini.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import re
import secrets
import time
import urllib.parse
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy import Connection, insert, update

from ..stockage.schema import COURRIEL_ETATS_OAUTH
from .erreurs import ErreurCourriel
from .jetons import JeuJetons
from .transport import ErreurTransport, ReponseHttp, RequeteHttp, Transport

USAGES = ("lecture", "lecture_envoi")
DUREE_ETAT_S = 600
_ERREUR_FOURNISSEUR = re.compile(r"[a-z_]{1,40}")
_COMPTE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode("ascii")


def _debase64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


@dataclasses.dataclass(frozen=True)
class PolitiquePortees:
    """Les portées d'un fournisseur : `lecture` (requises), `envoi` (en plus, si l'usage l'exige), `tolerees`
    (portées d'identité sans accès au courrier). Tout le reste est EXCESSIF."""

    lecture: frozenset[str]
    envoi: frozenset[str]
    tolerees: frozenset[str] = frozenset()
    insensible_casse: bool = False
    prefixe: str = ""

    def normaliser(self, portee: str) -> str:
        portee = portee.strip()
        if self.prefixe and portee.lower().startswith(self.prefixe.lower()):
            portee = portee[len(self.prefixe):]
        return portee.casefold() if self.insensible_casse else portee

    def _ensemble(self, portees: Iterable[str]) -> frozenset[str]:
        return frozenset(self.normaliser(p) for p in portees if p.strip())

    def demandees(self, usage: str) -> tuple[str, ...]:
        if usage not in USAGES:
            raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", f"usage OAuth parmi : {', '.join(USAGES)}", 422)
        return tuple(sorted(self.lecture | (self.envoi if usage == "lecture_envoi" else frozenset())))

    def verifier(self, accordees: Iterable[str], usage: str) -> frozenset[str]:
        """Rend les portées accordées normalisées si elles sont acceptables ; refus typé sinon."""
        accordees_n = self._ensemble(accordees)
        permises = self._ensemble(self.lecture | self.envoi | self.tolerees)
        excessives = sorted(accordees_n - permises)
        if excessives:
            raise ErreurCourriel("REJ-COURRIEL-PORTEE-EXCESSIVE",
                                 f"portée(s) accordée(s) au-delà du minimum : {', '.join(excessives)[:200]}", 403)
        if usage == "lecture" and self._ensemble(self.envoi) & accordees_n:
            raise ErreurCourriel("REJ-COURRIEL-PORTEE-EXCESSIVE",
                                 "portée d'envoi accordée pour un compte en lecture seule", 403)
        requises = self._ensemble(self.lecture | (self.envoi if usage == "lecture_envoi" else frozenset()))
        manquantes = sorted(requises - accordees_n)
        if manquantes:
            raise ErreurCourriel("REJ-COURRIEL-PORTEE-INSUFFISANTE",
                                 f"portée(s) requise(s) non accordée(s) : {', '.join(manquantes)[:200]}", 403)
        return accordees_n


@dataclasses.dataclass(frozen=True)
class ConfigOAuth:
    fournisseur: str
    url_autorisation: str
    url_jeton: str
    url_revocation: str | None
    client_id: str
    redirect_uri: str
    portees: PolitiquePortees
    parametres_autorisation: tuple[tuple[str, str], ...] = ()
    portees_en_url_complete: bool = False

    def __post_init__(self) -> None:
        for nom in ("url_autorisation", "url_jeton", "redirect_uri"):
            if not getattr(self, nom).startswith("https://") and not (
                    nom == "redirect_uri" and re.match(r"http://(localhost|127\.0\.0\.1)(:\d+)?/", self.redirect_uri)):
                raise ErreurCourriel("REJ-COURRIEL-OAUTH-CONFIGURATION", f"{nom} : https:// requis", 422)
        if self.url_revocation is not None and not self.url_revocation.startswith("https://"):
            raise ErreurCourriel("REJ-COURRIEL-OAUTH-CONFIGURATION", "url_revocation : https:// requis", 422)
        if not self.client_id.strip() or any(c in self.client_id for c in " \r\n"):
            raise ErreurCourriel("REJ-COURRIEL-OAUTH-CONFIGURATION", "client_id invalide", 422)


# Gmail : sources officielles dans docs/architecture/CONNECTEURS-COURRIEL.md. `gmail.readonly` est un scope RESTREINT
# (exemption « Internal » seulement avec le projet OAuth du client) ; `gmail.send` est SENSIBLE.
PORTEES_GMAIL = PolitiquePortees(
    lecture=frozenset({"https://www.googleapis.com/auth/gmail.readonly"}),
    envoi=frozenset({"https://www.googleapis.com/auth/gmail.send"}),
)
PORTEES_GRAPH = PolitiquePortees(
    lecture=frozenset({"Mail.Read"}), envoi=frozenset({"Mail.Send"}),
    tolerees=frozenset({"offline_access", "openid", "profile", "email"}),
    insensible_casse=True, prefixe="https://graph.microsoft.com/",
)


def config_gmail(*, client_id: str, redirect_uri: str) -> ConfigOAuth:
    return ConfigOAuth(
        "gmail", "https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token",
        "https://oauth2.googleapis.com/revoke", client_id, redirect_uri, PORTEES_GMAIL,
        parametres_autorisation=(("access_type", "offline"), ("prompt", "consent")),
    )


def config_graph(*, client_id: str, redirect_uri: str, tenant: str) -> ConfigOAuth:
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,80}", tenant):
        raise ErreurCourriel("REJ-COURRIEL-OAUTH-CONFIGURATION", "tenant invalide", 422)
    base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
    return ConfigOAuth("graph", f"{base}/authorize", f"{base}/token", None, client_id, redirect_uri, PORTEES_GRAPH,
                       parametres_autorisation=(("response_mode", "query"),))


@dataclasses.dataclass(frozen=True)
class UrlAutorisation:
    url: str
    state: str
    expire_epoch: int


@dataclasses.dataclass(frozen=True)
class Echange:
    compte_id: str
    usage: str
    jeu: JeuJetons


class ServiceOAuth:
    def __init__(self, config: ConfigOAuth, transport: Transport, cle_signature: Callable[[], bytes], *,
                 horloge: Callable[[], float] = time.time,
                 secret_client: Callable[[], AbstractContextManager[str]] | None = None) -> None:
        self.config, self._transport, self._cle = config, transport, cle_signature
        self._horloge, self._secret_client = horloge, secret_client

    # -- clé, state, PKCE ---------------------------------------------------------------------------------
    def _hmac(self, etiquette: bytes, message: bytes) -> bytes:
        cle = self._cle()
        if not isinstance(cle, (bytes, bytearray)) or len(cle) < 32:
            raise ErreurCourriel("REJ-COURRIEL-OAUTH-CONFIGURATION", "clé de signature du state : 32 octets minimum",
                                 503)
        return hmac.new(bytes(cle), etiquette + message, hashlib.sha256).digest()

    def _verifier_pkce(self, nonce: str) -> str:
        return _b64(self._hmac(b"opsys:courriel:pkce:v1:", nonce.encode("ascii")))

    def _signer(self, charge_b64: str) -> str:
        return _b64(self._hmac(b"opsys:courriel:state:v1:", charge_b64.encode("ascii")))

    def url_autorisation(self, cnx: Connection, compte_id: str, usage: str = "lecture") -> UrlAutorisation:
        if not isinstance(compte_id, str) or not _COMPTE.fullmatch(compte_id):
            raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "compte_id invalide", 422)
        portees = self.config.portees.demandees(usage)
        nonce = _b64(secrets.token_bytes(24))
        maintenant = int(self._horloge())
        expire = maintenant + DUREE_ETAT_S
        charge = _b64(json.dumps({"n": nonce, "c": compte_id, "f": self.config.fournisseur, "u": usage, "x": expire},
                                 sort_keys=True, separators=(",", ":")).encode("utf-8"))
        state = f"{charge}.{self._signer(charge)}"
        cnx.execute(insert(COURRIEL_ETATS_OAUTH).values(
            nonce=nonce, compte_id=compte_id, fournisseur=self.config.fournisseur, usage=usage, expire_epoch=expire,
            utilise_epoch=None, cree_epoch=maintenant))
        verifier = self._verifier_pkce(nonce)
        parametres = [
            ("client_id", self.config.client_id), ("redirect_uri", self.config.redirect_uri),
            ("response_type", "code"), ("scope", " ".join(portees)), ("state", state),
            ("code_challenge", _b64(hashlib.sha256(verifier.encode("ascii")).digest())),
            ("code_challenge_method", "S256"), *self.config.parametres_autorisation,
        ]
        return UrlAutorisation(self.config.url_autorisation + "?" + urllib.parse.urlencode(parametres,
                                                                                           quote_via=urllib.parse.quote),
                               state, expire)

    def _ouvrir_state(self, state: str) -> dict[str, Any]:
        try:
            charge, signature = state.split(".")
            attendue = self._signer(charge)
            if not hmac.compare_digest(signature.encode("ascii"), attendue.encode("ascii")):
                raise ValueError("signature")
            donnees = json.loads(_debase64(charge))
            if (set(donnees) != {"n", "c", "f", "u", "x"} or donnees["f"] != self.config.fournisseur
                    or donnees["u"] not in USAGES or type(donnees["x"]) is not int
                    or not _COMPTE.fullmatch(donnees["c"]) or not isinstance(donnees["n"], str)):
                raise ValueError("forme")
        except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
            raise ErreurCourriel("REJ-COURRIEL-OAUTH-ETAT-INVALIDE", "state falsifié ou mal formé", 400) from None
        return donnees

    # -- échange du code ----------------------------------------------------------------------------------
    def consommer_state(self, cnx: Connection, state: str) -> dict[str, Any]:
        """Vérifie la signature et l'expiration du `state`, puis CONSOMME son nonce (usage unique). À appeler dans une
        transaction qui sera VALIDÉE même si l'échange échoue ensuite : un `state` brûlé ne rejoue jamais."""
        if not isinstance(state, str) or len(state) > 2048:
            raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "state requis", 422)
        donnees = self._ouvrir_state(state)
        maintenant = int(self._horloge())
        if donnees["x"] <= maintenant:
            raise ErreurCourriel("REJ-COURRIEL-OAUTH-ETAT-EXPIRE", "state expiré : relancer l'autorisation", 400)
        resultat = cnx.execute(update(COURRIEL_ETATS_OAUTH).where(
            COURRIEL_ETATS_OAUTH.c.nonce == donnees["n"], COURRIEL_ETATS_OAUTH.c.utilise_epoch.is_(None),
            COURRIEL_ETATS_OAUTH.c.compte_id == donnees["c"], COURRIEL_ETATS_OAUTH.c.expire_epoch > maintenant,
        ).values(utilise_epoch=maintenant))
        if resultat.rowcount != 1:
            raise ErreurCourriel("REJ-COURRIEL-OAUTH-ETAT-REUTILISE", "state déjà utilisé ou inconnu", 400)
        return donnees

    def echanger_code(self, donnees_state: dict[str, Any], code: str) -> Echange:
        """Échange le code d'autorisation contre des jetons (PKCE) et vérifie les portées accordées."""
        if not isinstance(code, str) or not code or len(code) > 2048:
            raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "code d'autorisation requis", 422)
        champs = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.config.redirect_uri,
                  "client_id": self.config.client_id, "code_verifier": self._verifier_pkce(donnees_state["n"])}
        reponse = self._appel_jeton(champs)
        jeu = self._jeu(reponse, usage=donnees_state["u"],
                        demandees=self.config.portees.demandees(donnees_state["u"]),
                        precedent=None, exiger_refresh=True, echange=True)
        return Echange(donnees_state["c"], donnees_state["u"], jeu)

    # -- rafraîchissement, révocation ---------------------------------------------------------------------
    def rafraichir(self, jeu: JeuJetons, *, usage: str) -> JeuJetons:
        if not jeu.refresh_token:
            raise ErreurCourriel("REJ-COURRIEL-REFRESH-ABSENT",
                                 "aucun jeton de rafraîchissement : reconnecter le compte",
                                 401)
        champs = {"grant_type": "refresh_token", "refresh_token": jeu.refresh_token, "client_id": self.config.client_id}
        reponse = self._appel_jeton(champs, rafraichissement=True)
        return self._jeu(reponse, usage=usage, demandees=tuple(jeu.portees), precedent=jeu, exiger_refresh=False,
                         echange=False)

    def revoquer_chez_fournisseur(self, jeu: JeuJetons) -> bool:
        """Révoque le jeton chez le fournisseur s'il a un point de révocation ; `False` sinon (Microsoft : le retrait
        du consentement se fait dans Entra, voir la documentation)."""
        if self.config.url_revocation is None:
            return False
        jeton = jeu.refresh_token or jeu.access_token
        corps = urllib.parse.urlencode({"token": jeton}).encode("ascii")
        reponse = self._envoyer(RequeteHttp("POST", self.config.url_revocation, {
            "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, corps))
        return 200 <= reponse.statut < 300

    # -- interne ------------------------------------------------------------------------------------------
    def _envoyer(self, requete: RequeteHttp) -> ReponseHttp:
        try:
            return self._transport.envoyer(requete)
        except ErreurTransport:
            raise ErreurCourriel("REJ-COURRIEL-RESEAU", "fournisseur OAuth injoignable", 503, reprenable=True) from None
        except Exception:  # noqa: BLE001 — jamais le message d'origine (URL, jeton)
            raise ErreurCourriel("REJ-COURRIEL-RESEAU", "erreur de transport inattendue", 503,
                                 reprenable=True) from None

    def _appel_jeton(self, champs: dict[str, str], *, rafraichissement: bool = False) -> dict[str, Any]:
        if self._secret_client is not None:
            with self._secret_client() as secret:
                return self._poster_jeton({**champs, "client_secret": secret}, rafraichissement)
        return self._poster_jeton(champs, rafraichissement)

    def _poster_jeton(self, champs: dict[str, str], rafraichissement: bool) -> dict[str, Any]:
        corps = urllib.parse.urlencode(champs).encode("utf-8")
        reponse = self._envoyer(RequeteHttp("POST", self.config.url_jeton, {
            "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, corps))
        if reponse.statut >= 500 or reponse.statut == 429:
            raise ErreurCourriel("REJ-COURRIEL-FOURNISSEUR-INDISPONIBLE", f"point de jeton : HTTP {reponse.statut}",
                                 503,
                                 reprenable=True)
        try:
            donnees = json.loads(reponse.corps.decode("utf-8"))
            if not isinstance(donnees, dict):
                raise ValueError("forme")
        except (ValueError, UnicodeError):
            raise ErreurCourriel("REJ-COURRIEL-REPONSE-INVALIDE", "réponse du point de jeton illisible", 502) from None
        if reponse.statut != 200:
            erreur = donnees.get("error")
            nature = erreur if isinstance(erreur, str) and _ERREUR_FOURNISSEUR.fullmatch(erreur) else "inconnue"
            if rafraichissement and nature in {"invalid_grant", "invalid_token", "unauthorized_client"}:
                raise ErreurCourriel("REJ-COURRIEL-JETON-REVOQUE",
                                     f"rafraîchissement refusé ({nature}) : reconnecter le compte", 401)
            raise ErreurCourriel("REJ-COURRIEL-OAUTH-ECHANGE-REFUSE", f"échange refusé par le fournisseur ({nature})",
                                 400)
        return donnees

    def _jeu(self, donnees: dict[str, Any], *, usage: str, demandees: Iterable[str], precedent: JeuJetons | None,
             exiger_refresh: bool, echange: bool) -> JeuJetons:
        acces, duree = donnees.get("access_token"), donnees.get("expires_in")
        type_jeton = donnees.get("token_type", "Bearer")
        if (not isinstance(acces, str) or not acces or type(duree) is not int or not 0 < duree <= 86400 * 7
                or not isinstance(type_jeton, str) or type_jeton.lower() != "bearer"):
            raise ErreurCourriel("REJ-COURRIEL-REPONSE-INVALIDE", "réponse de jeton incomplète", 502)
        portee_texte = donnees.get("scope")
        if portee_texte is None:
            accordees: Iterable[str] = demandees  # RFC 6749 §5.1 : omise = identique à la demande
        elif isinstance(portee_texte, str):
            accordees = portee_texte.split()
        else:
            raise ErreurCourriel("REJ-COURRIEL-REPONSE-INVALIDE", "portée de jeton illisible", 502)
        verifiees = self.config.portees.verifier(accordees, usage)
        nouveau = donnees.get("refresh_token")
        if nouveau is not None and (not isinstance(nouveau, str) or not nouveau):
            raise ErreurCourriel("REJ-COURRIEL-REPONSE-INVALIDE", "jeton de rafraîchissement illisible", 502)
        refresh = nouveau or (precedent.refresh_token if precedent else None)  # rotation seulement si fourni
        if exiger_refresh and not refresh:
            raise ErreurCourriel("REJ-COURRIEL-REFRESH-ABSENT",
                                 "le fournisseur n'a pas émis de jeton de rafraîchissement (accès hors ligne requis)",
                                 400)
        return JeuJetons(acces, refresh, int(self._horloge()) + duree, verifiees)


__all__ = ["DUREE_ETAT_S", "PORTEES_GMAIL", "PORTEES_GRAPH", "USAGES", "ConfigOAuth", "Echange", "PolitiquePortees",
           "ServiceOAuth", "UrlAutorisation", "config_gmail", "config_graph"]
