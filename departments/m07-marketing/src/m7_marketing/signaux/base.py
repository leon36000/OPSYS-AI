"""La base commune des connecteurs de LECTURE : un seul chemin d'appel, les mêmes garde-fous pour tous.

Un connecteur sait construire la requête d'une source, lire sa réponse et la traduire en faits
(`modele.brouillon_fait`).
Il ne sait RIEN faire d'autre. Tout appel passe par `_appeler`, qui impose, dans cet ordre :

1. le POINT D'ACCÈS est dans la liste de lecture que la classe déclare (`POINTS_ACCES`) : un point d'accès d'écriture
   (`mutate`, `POST /campaigns`, publication…) n'est pas appelable, même par erreur (`REJ-SIGNAUX-ECRITURE-INTERDITE`) ;
2. l'URL est en HTTPS, sans identifiant, sur un HÔTE déclaré (les hôtes fixes du fournisseur, ou l'hôte que le client a
   déclaré pour son service auto-hébergé) : une URL tirée d'une réponse n'est jamais suivie ;
3. le QUOTA local réserve la requête, ou refuse AVANT l'envoi (`quotas.py`) ;
4. le jeton sort du coffre le temps d'UN appel (`with fournisseur() as jeton`), n'est gardé nulle part et n'entre dans
   aucun message ; toute exception du transport est remplacée par un refus typé SANS son texte ;
5. la réponse est bornée en taille et son statut traduit en refus typé : 401 jeton refusé ou révoqué, 403 permission (ou
   quota selon le motif), 429 limite de débit avec `Retry-After`, 5xx indisponibilité reprenable. Le corps de la
   réponse n'est jamais recopié.

Module sans entrée-sortie : le transport est un port injecté (`transport.py`).
"""

from __future__ import annotations

import abc
import contextlib
import dataclasses
import hashlib
import json
import urllib.parse
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from . import modele
from .comptes import CompteSource
from .erreurs import ErreurSignaux, refus
from .minimisation import exiger_masqueur
from .quotas import LimiteurQuota, Quota
from .transport import Authentification, ErreurTransport, ReponseHttp, RequeteHttp, Transport

FournisseurSecret = Callable[[], contextlib.AbstractContextManager[str]]
REPONSE_OCTETS_MAX = 5 * 1024 * 1024
LIGNES_PAGE_MAX = 5000
_MOTIFS_QUOTA_GOOGLE = frozenset(
    {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded", "RESOURCE_EXHAUSTED"}
)


@dataclasses.dataclass(frozen=True)
class PageLue:
    """Une page lue et traduite : des faits de révision 1 (avant normalisation), le curseur de la suivante, et ce que la
    page dit de sa fraîcheur. `termine` : il n'y a plus de page pour cette fenêtre."""

    faits: tuple[dict[str, Any], ...]
    curseur_suivant: str | None
    termine: bool
    observe_le: str
    donnees_jusqu_au: str | None
    empreinte_reponse: str
    appels: int = 1
    ignores: int = 0


def empreinte_reponse(corps: Any) -> str:
    return hashlib.sha256(
        json.dumps(corps, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def nombre_texte(valeur: Any, decimales: int = 6) -> str:
    """Un nombre du fournisseur en TEXTE décimal. Refuse un booléen, NaN, l'infini ou une valeur non numérique."""
    if isinstance(valeur, bool) or valeur is None:
        raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "valeur numérique attendue dans la réponse", 502)
    try:
        d = Decimal(str(valeur))
        if not d.is_finite():
            raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "valeur non finie dans la réponse", 502)
        texte = format(d.quantize(Decimal(1).scaleb(-decimales)), "f")
    except (InvalidOperation, OverflowError, ValueError):
        raise refus(
            "REJ-SIGNAUX-REPONSE-INVALIDE", "valeur numérique illisible ou hors bornes dans la réponse", 502
        ) from None
    if "." in texte:
        texte = texte.rstrip("0").rstrip(".")
    texte = texte or "0"
    return "0" if texte == "-0" else texte


def champ(corps: Any, *chemin: str | int, types: tuple[type, ...] = (dict, list, str, int, float)) -> Any:
    """Lit un champ imbriqué ; un chemin absent ou un type inattendu est `REJ-SIGNAUX-REPONSE-INVALIDE`."""
    courant = corps
    for cle in chemin:
        try:
            courant = courant[cle]
        except (KeyError, IndexError, TypeError):
            raise refus(
                "REJ-SIGNAUX-REPONSE-INVALIDE", "champ attendu absent de la réponse du fournisseur", 502
            ) from None
    if isinstance(courant, bool) or not isinstance(courant, types):
        raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "type inattendu dans la réponse du fournisseur", 502)
    return courant


def liste(corps: Any, *chemin: str | int, maximum: int = LIGNES_PAGE_MAX) -> list[Any]:
    valeur = champ(corps, *chemin, types=(list,))
    if len(valeur) > maximum:
        raise refus("REJ-SIGNAUX-REPONSE-TROP-GROSSE", f"plus de {maximum} lignes dans une page", 502)
    return valeur


class ConnecteurLecture(abc.ABC):
    """Base des connecteurs. La classe fille déclare `SOURCE`, `FOURNISSEUR`, `VERSION_API`, `LIMITES`, `POINTS_ACCES`,
    `HOTES` (vide pour un service auto-hébergé), `FLUX`, et implémente `lire_page`."""

    SOURCE: ClassVar[str]
    FOURNISSEUR: ClassVar[str]
    VERSION_API: ClassVar[str]
    LIMITES: ClassVar[Quota]
    POINTS_ACCES: ClassVar[frozenset[str]]
    HOTES: ClassVar[frozenset[str]] = frozenset()
    FLUX: ClassVar[tuple[str, ...]] = ("principal",)
    HISTORIQUE_JOURS: ClassVar[int] = 28
    RELECTURE_JOURS: ClassVar[int] = 3
    PAGES_MAX_PAR_FENETRE: ClassVar[int] = 40

    def __init__(
        self,
        transport: Transport,
        compte: CompteSource,
        fournisseurs: Mapping[str, FournisseurSecret],
        *,
        maintenant: Callable[[], datetime],
        masqueur: Any,
        limiteur: LimiteurQuota | None = None,
        delai_s: float = 30.0,
    ) -> None:
        if compte.source != self.SOURCE:
            raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", "compte d'une autre source", 500)
        if not compte.actif:
            raise refus("REJ-SIGNAUX-COMPTE-INACTIF", "compte désactivé : jamais lu", 409)
        attendus = {"principal", *modele.SOURCES[self.SOURCE].secrets_annexes}
        if set(fournisseurs) != attendus:
            raise refus("REJ-SIGNAUX-SECRET-REF", f"fournisseurs de secrets attendus : {sorted(attendus)}", 500)
        self._transport, self.compte, self._fournisseurs = transport, compte, dict(fournisseurs)
        self._maintenant, self._masqueur = maintenant, exiger_masqueur(masqueur)
        self._limiteur = limiteur or LimiteurQuota(self.LIMITES)
        self._delai_s = delai_s

    # -- fenêtre ---------------------------------------------------------------------------------------------------
    def fenetre_suivante(self, watermark: date | None, aujourd_hui: date) -> modele.Fenetre | None:
        """La prochaine fenêtre à lire : on relit les `RELECTURE_JOURS` derniers jours (le fournisseur révise) puis on
        avance jusqu'au dernier jour que la source a eu le temps de produire. `None` : rien de nouveau à lire."""
        fin = aujourd_hui - timedelta(days=modele.SOURCES[self.SOURCE].retard_donnees_jours)
        debut = (
            fin - timedelta(days=self.HISTORIQUE_JOURS - 1)
            if watermark is None
            else watermark - timedelta(days=self.RELECTURE_JOURS - 1)
        )
        if watermark is not None and fin <= watermark - timedelta(days=self.RELECTURE_JOURS):
            return None
        if debut > fin:
            return None
        return modele.Fenetre(debut, fin)

    @abc.abstractmethod
    def lire_page(self, flux: str, fenetre: modele.Fenetre, curseur: str | None) -> PageLue:
        """Lit UNE page du flux pour la fenêtre, à partir du curseur (None : la première), et la traduit en faits."""

    # -- appel ---------------------------------------------------------------------------------------------------
    def _hotes_permis(self) -> frozenset[str]:
        if self.HOTES:
            return self.HOTES
        base = self.compte.base_url
        return frozenset({urllib.parse.urlsplit(base).hostname or ""}) if base else frozenset()

    def _verifier_url(self, url: str) -> None:
        morceaux = urllib.parse.urlsplit(url)
        try:
            port = morceaux.port
        except ValueError:
            port = -1
        if (
            morceaux.scheme != "https"
            or morceaux.username is not None
            or morceaux.password is not None
            or port not in (None, 443)
            or morceaux.hostname not in self._hotes_permis()
            or morceaux.fragment
        ):
            raise refus("REJ-SIGNAUX-HOTE-NON-PERMIS", "URL hors des hôtes déclarés pour cette source", 403)

    def _authentification(self, principal: str, annexes: Mapping[str, str]) -> Authentification:
        return Authentification("bearer", principal)

    @staticmethod
    def _est_limite_debit(statut: int, corps: Any) -> bool:
        if statut != 403 or not isinstance(corps, Mapping):
            return False
        erreur = corps.get("error")
        if not isinstance(erreur, Mapping):
            return False
        details = erreur.get("errors")
        motifs = {d.get("reason") for d in details if isinstance(d, Mapping)} if isinstance(details, list) else set()
        return bool(motifs & _MOTIFS_QUOTA_GOOGLE) or erreur.get("status") in _MOTIFS_QUOTA_GOOGLE

    def _appeler(
        self,
        point_acces: str,
        methode: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        corps: Mapping[str, Any] | None = None,
    ) -> tuple[Any, str]:
        """UN appel de lecture. Rend (corps décodé, empreinte de la réponse) ou lève `ErreurSignaux`."""
        if point_acces not in self.POINTS_ACCES:
            raise refus(
                "REJ-SIGNAUX-ECRITURE-INTERDITE",
                f"point d'accès {point_acces!r} hors de la liste de lecture de {self.SOURCE}",
                403,
            )
        self._verifier_url(url)
        self._limiteur.reserver(self._maintenant())
        try:
            with contextlib.ExitStack() as pile:
                principal = pile.enter_context(self._fournisseurs["principal"]())
                annexes = {
                    nom: pile.enter_context(self._fournisseurs[nom]())
                    for nom in modele.SOURCES[self.SOURCE].secrets_annexes
                }
                requete = RequeteHttp(
                    methode,
                    url,
                    dict(params or {}),
                    dict(corps) if corps is not None else None,
                    self._authentification(principal, annexes),
                )
                try:
                    reponse = self._transport.envoyer(requete, delai_s=self._delai_s)
                except ErreurSignaux:
                    raise
                except ErreurTransport:
                    raise refus(
                        "REJ-SIGNAUX-RESEAU", "panne de transport (délai, connexion ou TLS)", 504, reprenable=True
                    ) from None
                except Exception:  # noqa: BLE001 — le texte d'une exception de transport peut contenir le secret
                    raise refus("REJ-SIGNAUX-RESEAU", "panne de transport inattendue", 504, reprenable=True) from None
        except ErreurSignaux:
            raise
        except Exception:  # noqa: BLE001 — l'ouverture du coffre : jamais son message
            raise refus(
                "REJ-SIGNAUX-COFFRE-INDISPONIBLE", "le secret n'a pas pu être ouvert dans le coffre", 503
            ) from None
        return self._lire_reponse(reponse)

    def _lire_reponse(self, reponse: Any) -> tuple[Any, str]:
        if not isinstance(reponse, ReponseHttp) or type(reponse.statut) is not int:
            raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "réponse de transport illisible", 502)
        statut, corps = reponse.statut, reponse.corps
        if 200 <= statut < 300:
            if not isinstance(corps, (dict, list)):
                raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "réponse sans corps JSON structuré", 502)
            try:
                taille = len(json.dumps(corps, default=str).encode("utf-8"))
            except (TypeError, ValueError, RecursionError):
                raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "corps de réponse non sérialisable", 502) from None
            if taille > REPONSE_OCTETS_MAX:
                raise refus("REJ-SIGNAUX-REPONSE-TROP-GROSSE", f"réponse de plus de {REPONSE_OCTETS_MAX} octets", 502)
            return corps, empreinte_reponse(corps)
        attente = _retry_after(reponse.en_tetes)
        if statut == 401:
            raise refus(
                "REJ-SIGNAUX-AUTH-REFUSEE", "jeton refusé, expiré ou révoqué : le renouveler dans le coffre", 401
            )
        if statut == 403 and self._est_limite_debit(statut, corps) or statut == 429:
            raise refus(
                "REJ-SIGNAUX-LIMITE-DEBIT",
                "limite de débit du fournisseur",
                429,
                reprenable=True,
                reessayer_apres_s=attente or 60,
            )
        if statut == 403:
            raise refus(
                "REJ-SIGNAUX-PERMISSION-REFUSEE", "permission refusée : le jeton n'a pas accès à cette ressource", 403
            )
        if statut == 404:
            raise refus("REJ-SIGNAUX-INTROUVABLE", "ressource introuvable chez le fournisseur", 404)
        if statut == 408:
            raise refus(
                "REJ-SIGNAUX-RESEAU",
                "délai dépassé chez le fournisseur",
                504,
                reprenable=True,
                reessayer_apres_s=attente,
            )
        if statut == 400:
            raise refus("REJ-SIGNAUX-REQUETE-INVALIDE", "requête refusée par le fournisseur", 422)
        if 500 <= statut < 600:
            raise refus(
                "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE",
                f"fournisseur indisponible (HTTP {statut})",
                503,
                reprenable=True,
                reessayer_apres_s=attente,
            )
        raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", f"statut HTTP inattendu {statut}", 502)

    @property
    def limiteur(self) -> LimiteurQuota:
        return self._limiteur

    def releves_depenses(self, faits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Les relevés de dépense que ces faits établissent (`depenses_marketing.normaliser_releve`). Aucun par défaut :
        seuls les connecteurs publicitaires en produisent."""
        return []

    # -- fabrication de faits -------------------------------------------------------------------------------------
    def _provenance(self, point_acces: str, empreinte: str, page: int) -> dict[str, Any]:
        return {
            "fournisseur": self.FOURNISSEUR,
            "point_acces": point_acces,
            "version_api": self.VERSION_API,
            "mode": "api_lecture",
            "empreinte_reponse": empreinte,
            "page": page,
        }

    def _instant(self) -> str:
        maintenant = self._maintenant()
        if maintenant.tzinfo is None:
            raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", "horloge sans fuseau", 500)
        return maintenant.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _retry_after(en_tetes: Mapping[str, str]) -> int | None:
    for nom, valeur in (en_tetes or {}).items():
        if isinstance(nom, str) and nom.lower() == "retry-after":
            try:
                secondes = int(str(valeur).strip())
            except ValueError:
                return None
            return min(max(secondes, 1), 86400)
    return None


__all__ = [
    "ConnecteurLecture",
    "FournisseurSecret",
    "LIGNES_PAGE_MAX",
    "PageLue",
    "REPONSE_OCTETS_MAX",
    "champ",
    "empreinte_reponse",
    "liste",
    "nombre_texte",
]
