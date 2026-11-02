"""Client minimal de la passerelle LiteLLM (API compatible OpenAI) pour le banc : embeddings, discussion, dépense.

Bibliothèque standard seulement. La clé est lue d'un FICHIER (jamais d'un argument de ligne de commande), n'est envoyée
que dans l'en-tête Authorization, n'est jamais journalisée et est EXPURGÉE de tout message d'erreur. Aucune redirection
n'est suivie (urllib renverrait l'en-tête Authorization à l'hôte désigné par un serveur compromis). Les relances sont
bornées (2) et ne portent que sur les pannes transitoires.

Ce module n'est exercé contre le vrai service que par le test OPT-IN (OPSYS_LITELLM_TEST_URL et
OPSYS_LITELLM_TEST_KEY_FILE) ; les tests par défaut utilisent un faux serveur local.
"""

from __future__ import annotations

import dataclasses
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

ENV_URL = "OPSYS_LITELLM_TEST_URL"
ENV_CLE_FICHIER = "OPSYS_LITELLM_TEST_KEY_FILE"
REPONSE_MAX_OCTETS = 32_000_000
LOT_MAX = 128
RELANCES = 2
CODES_TRANSITOIRES = (429, 500, 502, 503, 504)


class ErreurPasserelle(RuntimeError):
    """Panne de la passerelle ou réponse inexploitable ; le message ne contient jamais la clé."""

    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OUVREUR = urllib.request.build_opener(_SansRedirection())


def lire_cle(chemin: str | Path) -> str:
    """Contenu d'un fichier de clé (espaces retirés). Refus typé s'il est absent, vide ou suspect."""
    try:
        cle = Path(chemin).read_text(encoding="utf-8").strip()
    except OSError:
        raise ErreurPasserelle("fichier de clé illisible") from None
    if not cle or len(cle) > 512 or not cle.isprintable() or any(c.isspace() for c in cle):
        raise ErreurPasserelle("fichier de clé vide ou mal formé")
    return cle


@dataclasses.dataclass(frozen=True)
class ReponseEmbeddings:
    vecteurs: list[list[float]]
    jetons: int | None
    secondes: float


@dataclasses.dataclass(frozen=True)
class ReponseDiscussion:
    texte: str
    jetons_entree: int | None
    jetons_sortie: int | None
    secondes: float
    cout_usd: float | None = None  # coût rapporté par la passerelle (usage.cost d'OpenRouter) quand il est présent


class ClientPasserelle:
    def __init__(self, url: str, cle: str, *, delai_s: float = 90.0,
                 dormir: Callable[[float], None] = time.sleep) -> None:
        analyse = urllib.parse.urlparse(url)
        if analyse.scheme not in ("http", "https") or not analyse.hostname or analyse.username or analyse.password:
            raise ErreurPasserelle("URL de passerelle : http(s) sans identifiants intégrés")
        if not cle:
            raise ErreurPasserelle("clé absente")
        self._base = url.rstrip("/")
        self._cle = cle
        self._delai = delai_s
        self._dormir = dormir

    def _expurger(self, texte: str) -> str:
        return texte.replace(self._cle, "***")

    def _requete(self, methode: str, chemin: str, corps: dict[str, Any] | None) -> tuple[Any, float]:
        donnees = json.dumps(corps).encode("utf-8") if corps is not None else None
        derniere: ErreurPasserelle | None = None
        for tentative in range(RELANCES + 1):
            requete = urllib.request.Request(
                self._base + chemin, data=donnees, method=methode,
                headers={"Authorization": f"Bearer {self._cle}", "Content-Type": "application/json",
                         "Accept": "application/json"})
            debut = time.perf_counter()
            try:
                with _OUVREUR.open(requete, timeout=self._delai) as reponse:  # noqa: S310 — schéma vérifié plus haut
                    brut = reponse.read(REPONSE_MAX_OCTETS + 1)
                secondes = time.perf_counter() - debut
                if len(brut) > REPONSE_MAX_OCTETS:
                    raise ErreurPasserelle("réponse trop volumineuse")
                try:
                    return json.loads(brut), secondes
                except ValueError:
                    raise ErreurPasserelle("réponse non JSON") from None
            except urllib.error.HTTPError as exc:
                corps_erreur = self._expurger(exc.read(300).decode("utf-8", "replace"))
                derniere = ErreurPasserelle(f"HTTP {exc.code} : {corps_erreur}", http_status=exc.code)
                if exc.code not in CODES_TRANSITOIRES:
                    raise derniere from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                derniere = ErreurPasserelle(f"passerelle injoignable : {self._expurger(type(exc).__name__)}")
            if tentative < RELANCES:
                self._dormir(1.0 + 2.0 * tentative)
        assert derniere is not None
        raise derniere

    def embeddings(self, modele: str, textes: Sequence[str], *, input_type: str | None = None) -> ReponseEmbeddings:
        if not textes or len(textes) > LOT_MAX or any(not isinstance(t, str) or not t.strip() for t in textes):
            raise ErreurPasserelle(f"embeddings : de 1 à {LOT_MAX} textes non vides")
        corps: dict[str, Any] = {"model": modele, "input": list(textes), "encoding_format": "float"}
        if input_type is not None:
            corps["input_type"] = input_type
        reponse, secondes = self._requete("POST", "/v1/embeddings", corps)
        donnees = reponse.get("data") if isinstance(reponse, dict) else None
        if not isinstance(donnees, list) or len(donnees) != len(textes):
            raise ErreurPasserelle("embeddings : nombre de vecteurs incohérent")
        try:
            ordonnees = sorted(donnees, key=lambda d: d["index"])
            vecteurs = [[float(x) for x in d["embedding"]] for d in ordonnees]
        except (KeyError, TypeError, ValueError):
            raise ErreurPasserelle("embeddings : réponse mal formée") from None
        if [d["index"] for d in ordonnees] != list(range(len(textes))):
            raise ErreurPasserelle("embeddings : index incohérents")
        dimension = len(vecteurs[0])
        for v in vecteurs:
            if len(v) != dimension or dimension == 0 or not all(math.isfinite(x) for x in v) or not any(v):
                raise ErreurPasserelle("embeddings : vecteur de dimension incohérente, nul ou non fini")
        usage = reponse.get("usage") if isinstance(reponse.get("usage"), dict) else {}
        jetons = usage.get("prompt_tokens") if isinstance(usage.get("prompt_tokens"), int) else None
        return ReponseEmbeddings(vecteurs, jetons, secondes)

    def discussion(self, modele: str, messages: Sequence[dict[str, str]], *, max_tokens: int) -> ReponseDiscussion:
        if not 1 <= max_tokens <= 1024:
            raise ErreurPasserelle("discussion : max_tokens de 1 à 1024")
        # « reasoning_effort: none » : sans cela un petit modèle de raisonnement dépense tout max_tokens à réfléchir et
        # ne rend aucun contenu (constaté sur opsys-haiku-5-5 le 2026-11-02).
        corps = {"model": modele, "messages": list(messages), "max_tokens": max_tokens, "reasoning_effort": "none"}
        reponse, secondes = self._requete("POST", "/v1/chat/completions", corps)
        try:
            texte = reponse["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ErreurPasserelle("discussion : réponse mal formée") from None
        if not isinstance(texte, str):
            raise ErreurPasserelle("discussion : contenu non textuel")
        usage = reponse.get("usage") if isinstance(reponse.get("usage"), dict) else {}
        entree = usage.get("prompt_tokens") if isinstance(usage.get("prompt_tokens"), int) else None
        sortie = usage.get("completion_tokens") if isinstance(usage.get("completion_tokens"), int) else None
        cout = usage.get("cost") if isinstance(usage.get("cost"), (int, float)) and not isinstance(
            usage.get("cost"), bool) else None
        return ReponseDiscussion(texte, entree, sortie, secondes, float(cout) if cout is not None else None)

    def depense(self) -> float | None:
        """Dépense cumulée de la clé (USD) selon /key/info, ou None si le service ne la rend pas."""
        try:
            reponse, _ = self._requete("GET", "/key/info", None)
            info = reponse.get("info", reponse)
            valeur = info.get("spend")
            return float(valeur) if isinstance(valeur, (int, float)) and not isinstance(valeur, bool) else None
        except (ErreurPasserelle, AttributeError, ValueError):
            return None
