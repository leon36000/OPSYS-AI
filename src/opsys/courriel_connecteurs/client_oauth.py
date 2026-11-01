"""Client d'API authentifié par OAuth : un seul endroit pour 401 -> rafraîchissement, 429, 5xx et liens de pagination.

- **401** : le jeton d'accès est rafraîchi UNE fois puis l'appel est rejoué ; un second 401 est un refus
  (`REJ-COURRIEL-AUTH-REFUSEE`) et le compte passe en « reconnexion requise ».
- **429 / 503 avec `Retry-After`** (secondes ou date HTTP) : attente (fonction `dormir` injectée) bornée à
  `attente_max_s` ; au-delà, refus REPRENABLE qui dit après combien de secondes réessayer. Le 403 Gmail
  `rateLimitExceeded` / `userRateLimitExceeded` est traité comme un 429.
- **5xx** : reprises avec attente exponentielle bornée, puis `REJ-COURRIEL-FOURNISSEUR-INDISPONIBLE`.
- **Appel non idempotent** (envoi) : AUCUNE reprise sur 5xx ni panne de transport (le message a pu partir) ; l'appelant
  traite l'issue incertaine. Seul le 401 est rejoué (rien n'a été traité).
- **Hôtes autorisés** : toute URL, y compris un `nextLink` / `deltaLink` rendu par le serveur, doit être en HTTPS sur un
  hôte de la liste du fournisseur, sans identifiant ni port : le jeton ne part jamais ailleurs.
- Une erreur ne recopie JAMAIS le corps de la réponse (il peut contenir du courriel) : seulement le statut et, pour un
  403, la raison courte assainie.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from .erreurs import ErreurCourriel
from .jetons import JeuJetons, StockageJetons, masquer_pendant
from .oauth import ServiceOAuth
from .transport import ErreurTransport, ReponseHttp, RequeteHttp, Transport

MARGE_EXPIRATION_S = 60
_RAISON = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,60}")
_RAISONS_DEBIT = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "RESOURCE_EXHAUSTED"})
Rapport = Callable[[str, Mapping[str, Any]], None]


class GestionnaireJetons:
    """Fournit un jeton d'accès valide : lit le coffre, rafraîchit avant l'expiration ou sur demande, réécrit le coffre
    (rotation du refresh token si le fournisseur en renvoie un). Verrou par instance contre deux rafraîchissements."""

    def __init__(self, nom_secret: str, stockage: StockageJetons, oauth: ServiceOAuth | None, *, usage: str,
                 service: str, horloge: Callable[[], float] = time.time, rapport: Rapport | None = None) -> None:
        self._nom, self._stockage, self._oauth = nom_secret, stockage, oauth
        self._usage, self._service, self._horloge = usage, service, horloge
        self._rapport = rapport or (lambda *_: None)
        self._jeu: JeuJetons | None = None
        self._verrou = threading.Lock()

    @property
    def jeu(self) -> JeuJetons:
        if self._jeu is None:
            self._jeu = self._stockage.lire(self._nom)
        return self._jeu

    def jeton_acces(self, *, force: bool = False) -> str:
        with self._verrou:
            jeu = self.jeu
            valide = jeu.expire_epoch == 0 or jeu.expire_epoch - MARGE_EXPIRATION_S > self._horloge()
            if valide and not force:
                return jeu.access_token
            if self._oauth is None or not jeu.refresh_token:
                raise ErreurCourriel("REJ-COURRIEL-JETON-EXPIRE", "jeton d'accès expiré sans moyen de rafraîchir : "
                                     "reconnecter le compte", 401)
            # Un autre processus a pu rafraîchir pendant ce temps : relire avant d'appeler le fournisseur.
            frais = self._stockage.lire(self._nom)
            if (frais.access_token != jeu.access_token and frais.expire_epoch - MARGE_EXPIRATION_S > self._horloge()):
                self._jeu = frais
                return frais.access_token
            nouveau = self._oauth.rafraichir(jeu, usage=self._usage)
            self._stockage.ecrire(self._nom, nouveau, service=self._service)
            self._jeu = nouveau
            self._rapport("jeton.rafraichi", {"rotation_refresh": nouveau.refresh_token != jeu.refresh_token})
            return nouveau.access_token


def _attente_demandee(reponse: ReponseHttp, maintenant: Callable[[], float]) -> float | None:
    brut = reponse.entete("retry-after")
    if brut is None:
        return None
    brut = brut.strip()
    if brut.isascii() and brut.isdigit():
        return float(int(brut))
    try:
        date = parsedate_to_datetime(brut)
        if date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
        return max(0.0, (date - datetime.fromtimestamp(maintenant(), UTC)).total_seconds())
    except (TypeError, ValueError, IndexError):
        return None


def _raison_403(reponse: ReponseHttp) -> str | None:
    try:
        erreurs = json.loads(reponse.corps.decode("utf-8")).get("error", {}).get("errors", [])
        raison = erreurs[0].get("reason") if erreurs else None
    except (ValueError, UnicodeError, AttributeError, IndexError, TypeError):
        return None
    return raison if isinstance(raison, str) and _RAISON.fullmatch(raison) else None


class ClientApi:
    def __init__(self, transport: Transport, jetons: GestionnaireJetons, *, hotes: frozenset[str],
                 dormir: Callable[[float], None] = time.sleep, horloge: Callable[[], float] = time.time,
                 max_tentatives: int = 5, attente_max_s: float = 30.0, delai_s: float = 30.0,
                 rapport: Rapport | None = None) -> None:
        self._transport, self._jetons, self._hotes = transport, jetons, hotes
        self._dormir, self._horloge = dormir, horloge
        self._max, self._attente_max, self._delai = max_tentatives, attente_max_s, delai_s
        self._rapport = rapport or (lambda *_: None)

    def verifier_url(self, url: str) -> str:
        try:
            analyse = urllib.parse.urlsplit(url)
            hote, port = analyse.hostname, analyse.port
        except ValueError:
            raise ErreurCourriel("REJ-COURRIEL-LIEN-NON-AUTORISE", "URL illisible", 502) from None
        if (analyse.scheme != "https" or hote is None or hote.lower() not in self._hotes or analyse.username is not None
                or analyse.password is not None or port not in (None, 443)):
            raise ErreurCourriel("REJ-COURRIEL-LIEN-NON-AUTORISE", "URL hors de l'hôte autorisé du fournisseur", 502)
        return url

    def appeler(self, methode: str, url: str, *, params: Mapping[str, Any] | None = None,
                json_corps: Any = None, octets: bytes | None = None, entetes: Mapping[str, str] | None = None,
                idempotente: bool = True, rendre: frozenset[int] = frozenset()) -> ReponseHttp:
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True, safe="$,")
        self.verifier_url(url)
        corps = octets
        base = {"Accept": "application/json", **(entetes or {})}
        if json_corps is not None:
            corps = json.dumps(json_corps, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            base["Content-Type"] = "application/json"
        rafraichi, echecs = False, 0
        while True:
            jeton = self._jetons.jeton_acces(force=False)
            with masquer_pendant(self._jetons.jeu):
                requete = RequeteHttp(methode, url, {**base, "Authorization": f"Bearer {jeton}"}, corps, self._delai)
                try:
                    reponse = self._transport.envoyer(requete)
                except ErreurTransport:
                    if not idempotente:
                        raise ErreurCourriel("REJ-COURRIEL-RESEAU",
                                             "panne de transport pendant un appel non idempotent",
                                             503, reprenable=False) from None
                    echecs += 1
                    if echecs >= self._max:
                        raise ErreurCourriel("REJ-COURRIEL-RESEAU", "fournisseur injoignable", 503,
                                             reprenable=True) from None
                    self._dormir(min(2.0 ** echecs, self._attente_max))
                    continue
                except Exception:  # noqa: BLE001 — jamais le message d'origine (URL, en-têtes)
                    raise ErreurCourriel("REJ-COURRIEL-RESEAU", "erreur de transport inattendue", 503) from None
            statut = reponse.statut
            if 200 <= statut < 300 or statut in rendre:
                return reponse
            if statut == 401:
                if rafraichi:
                    self._rapport("auth.refusee", {})
                    raise ErreurCourriel("REJ-COURRIEL-AUTH-REFUSEE", "jeton refusé après rafraîchissement : "
                                         "reconnecter le compte", 401)
                rafraichi = True
                self._jetons.jeton_acces(force=True)
                continue
            raison = _raison_403(reponse) if statut == 403 else None
            if statut == 429 or (statut == 403 and raison in _RAISONS_DEBIT) or (statut == 503 and idempotente
                                                                                  and reponse.entete("retry-after")):
                attente = _attente_demandee(reponse, self._horloge)
                echecs += 1
                if not idempotente:
                    raise ErreurCourriel("REJ-COURRIEL-LIMITE-DEBIT", "limite de débit : requête non traitée", 429,
                                         reprenable=True, reessayer_apres_s=int(attente or 60))
                if attente is None:
                    attente = min(2.0 ** echecs, self._attente_max)
                if attente > self._attente_max or echecs >= self._max:
                    self._rapport("limite.debit", {"attente_s": int(attente)})
                    raise ErreurCourriel("REJ-COURRIEL-LIMITE-DEBIT", "limite de débit du fournisseur", 429,
                                         reprenable=True, reessayer_apres_s=int(attente))
                self._rapport("limite.attente", {"attente_s": int(attente)})
                self._dormir(attente)
                continue
            if statut >= 500:
                if not idempotente:
                    raise ErreurCourriel("REJ-COURRIEL-FOURNISSEUR-INDISPONIBLE",
                                         f"HTTP {statut} pendant un appel non idempotent", 503, reprenable=False)
                echecs += 1
                if echecs >= self._max:
                    raise ErreurCourriel("REJ-COURRIEL-FOURNISSEUR-INDISPONIBLE", f"HTTP {statut} répété", 503,
                                         reprenable=True)
                self._dormir(min(2.0 ** echecs, self._attente_max))
                continue
            if statut == 403:
                raise ErreurCourriel("REJ-COURRIEL-PERMISSION-REFUSEE", "accès refusé par le fournisseur "
                                     f"(HTTP 403{', ' + raison if raison else ''})", 403)
            if statut == 404:
                raise ErreurCourriel("REJ-COURRIEL-INTROUVABLE", "ressource introuvable (HTTP 404)", 404)
            raise ErreurCourriel("REJ-COURRIEL-REQUETE-INVALIDE", f"requête refusée (HTTP {statut})", 422)

    def json(self, methode: str, url: str, **options: Any) -> dict[str, Any]:
        reponse = self.appeler(methode, url, **options)
        return self.lire_json(reponse)

    @staticmethod
    def lire_json(reponse: ReponseHttp) -> dict[str, Any]:
        try:
            donnees = json.loads(reponse.corps.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise ErreurCourriel("REJ-COURRIEL-REPONSE-INVALIDE", "réponse du fournisseur illisible", 502) from None
        if not isinstance(donnees, dict):
            raise ErreurCourriel("REJ-COURRIEL-REPONSE-INVALIDE", "réponse du fournisseur : objet JSON attendu", 502)
        return donnees
