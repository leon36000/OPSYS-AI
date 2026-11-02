"""Client minimal d'une API compatible OpenAI (LiteLLM, vLLM, Ollama) : modèles, catalogue, chat, embeddings, rerank.

- Transport `urllib`, délai borné (10 s au plus), AUCUNE redirection suivie (l'en-tête `Authorization` ne part jamais
  vers un autre hôte), réponse bornée en taille ;
- la clé n'est jamais journalisée ni recopiée dans une erreur : le détail d'une erreur d'amont est tronqué et masqué
  (`masquage.masquer_texte`) ;
- `ouvrir` est injectable : les tests passent par un faux serveur local (127.0.0.1) ou un double, jamais un réseau réel.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from ..secrets_coffre import masquage

DELAI_MAX_S = 10.0
REPONSE_MAX_OCTETS = 4 * 1024 * 1024
CORPS_MAX_OCTETS = 2 * 1024 * 1024
JETONS_TEST_MAX = 16


class ErreurAppel(Exception):
    """Échec d'un appel. `retentable` : un repli est légitime (panne, surcharge, délai) ; sinon la requête ou la
    configuration est en cause et un autre fournisseur ne la corrigerait pas."""

    def __init__(self, code: str, detail: str, retentable: bool, statut: int | None = None) -> None:
        super().__init__(f"{code} : {detail}")
        self.code, self.detail, self.retentable, self.statut = code, detail, retentable, statut


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _ouvrir_reel(requete: urllib.request.Request, delai_s: float) -> tuple[int, bytes]:
    ouvreur = urllib.request.build_opener(_SansRedirection())
    try:
        with ouvreur.open(requete, timeout=delai_s) as reponse:  # noqa: S310 — schéma validé en amont
            return reponse.status, reponse.read(REPONSE_MAX_OCTETS + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(REPONSE_MAX_OCTETS + 1)


Ouvrir = Callable[[urllib.request.Request, float], "tuple[int, bytes]"]


def racine_api(url_base: str) -> str:
    """Racine `/v1` de l'API compatible OpenAI à partir de l'URL de base de la passerelle."""
    base = url_base.rstrip("/")
    return base if base.endswith("/v1") else base + "/v1"


def racine_admin(url_base: str) -> str:
    base = url_base.rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def _detail_amont(corps: bytes, cle: str | None = None) -> str:
    try:
        donnees = json.loads(corps)
        message = donnees.get("error", {}).get("message") if isinstance(donnees, dict) else None
        if isinstance(message, dict):
            message = None
        texte = str(message) if message else ""
    except (ValueError, AttributeError):
        texte = ""
    texte = texte[:120].replace("\n", " ")
    if cle and len(cle) >= 4:  # le client connaît sa propre clé : jamais recopiée, même non enregistrée au masquage
        texte = texte.replace(cle, masquage.MASQUE)
    return masquage.masquer_texte(texte)


class ClientOpenAI:
    def __init__(
        self, url_base: str, cle: str | None = None, *, delai_s: float = 8.0, ouvrir: Ouvrir | None = None
    ) -> None:
        self._base = url_base.rstrip("/")
        self._cle = cle
        self._delai = min(max(delai_s, 0.1), DELAI_MAX_S)
        self._ouvrir = ouvrir or _ouvrir_reel

    def _requete(self, methode: str, url: str, corps: Mapping[str, Any] | None = None) -> Any:
        entetes = {"Accept": "application/json", "User-Agent": "opsys-modeles/1"}
        donnees = None
        if corps is not None:
            donnees = json.dumps(corps, ensure_ascii=False).encode("utf-8")
            if len(donnees) > CORPS_MAX_OCTETS:
                raise ErreurAppel("REJ-MODELES-APPEL-REFUSE", "requête trop volumineuse", False)
            entetes["Content-Type"] = "application/json"
        if self._cle:
            entetes["Authorization"] = f"Bearer {self._cle}"
        requete = urllib.request.Request(url, data=donnees, method=methode, headers=entetes)
        debut = time.monotonic()
        try:
            statut, brut = self._ouvrir(requete, self._delai)
        except TimeoutError:
            raise ErreurAppel("REJ-MODELES-APPEL-ECHEC", f"aucune réponse en {self._delai:g} s", True) from None
        except urllib.error.URLError as exc:
            delai = isinstance(exc.reason, (TimeoutError, socket.timeout))
            raise ErreurAppel(
                "REJ-MODELES-APPEL-ECHEC", "aucune réponse" if delai else "hôte injoignable", True
            ) from None
        except OSError:
            raise ErreurAppel("REJ-MODELES-APPEL-ECHEC", "erreur réseau", True) from None
        latence = int((time.monotonic() - debut) * 1000)
        if len(brut) > REPONSE_MAX_OCTETS:
            raise ErreurAppel("REJ-MODELES-REPONSE-INVALIDE", "réponse trop volumineuse", False, statut)
        if statut in (401, 403):
            raise ErreurAppel("REJ-MODELES-APPEL-REFUSE", f"authentification refusée (HTTP {statut})", False, statut)
        if statut == 429 or statut >= 500:
            detail = _detail_amont(brut, self._cle)
            raise ErreurAppel("REJ-MODELES-APPEL-ECHEC", f"HTTP {statut} {detail}".strip(), True, statut)
        if statut >= 300:
            detail = _detail_amont(brut, self._cle)
            raise ErreurAppel("REJ-MODELES-APPEL-REFUSE", f"HTTP {statut} {detail}".strip(), False, statut)
        try:
            resultat = json.loads(brut or b"null")
        except ValueError:
            raise ErreurAppel("REJ-MODELES-REPONSE-INVALIDE", "réponse non JSON", False, statut) from None
        return resultat, latence

    # -- découverte ----------------------------------------------------------------------------------
    def modeles(self) -> tuple[list[str], int]:
        donnees, latence = self._requete("GET", racine_api(self._base) + "/models")
        liste = donnees.get("data") if isinstance(donnees, dict) else None
        if not isinstance(liste, list):
            raise ErreurAppel("REJ-MODELES-REPONSE-INVALIDE", "liste de modèles absente", False)
        return [str(m["id"]) for m in liste if isinstance(m, dict) and isinstance(m.get("id"), str)][:500], latence

    def info_modeles(self) -> list[dict[str, Any]] | None:
        """`/model/info` de LiteLLM ; `None` si le serveur ne l'offre pas (vLLM, Ollama) ou refuse."""
        try:
            donnees, _ = self._requete("GET", racine_admin(self._base) + "/model/info")
        except ErreurAppel as exc:
            if exc.statut in (404, 405, 400):
                return None
            raise
        liste = donnees.get("data") if isinstance(donnees, dict) else None
        return liste[:500] if isinstance(liste, list) else None

    # -- appels ----------------------------------------------------------------------------------------
    def chat(self, modele: str, messages: Sequence[Mapping[str, Any]], max_tokens: int) -> dict[str, Any]:
        donnees, latence = self._requete(
            "POST",
            racine_api(self._base) + "/chat/completions",
            {"model": modele, "messages": list(messages), "max_tokens": int(max_tokens), "stream": False},
        )
        try:
            choix = donnees["choices"][0]
            contenu = choix["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ErreurAppel("REJ-MODELES-REPONSE-INVALIDE", "réponse de chat sans contenu", False) from None
        if contenu is not None and not isinstance(contenu, str):
            raise ErreurAppel("REJ-MODELES-REPONSE-INVALIDE", "contenu de chat invalide", False)
        return {
            "contenu": contenu or "",
            "arret": choix.get("finish_reason"),
            "usage": _usage(donnees),
            "latence_ms": latence,
        }

    def embeddings(self, modele: str, textes: Sequence[str]) -> dict[str, Any]:
        donnees, latence = self._requete(
            "POST", racine_api(self._base) + "/embeddings", {"model": modele, "input": list(textes)}
        )
        try:
            vecteurs = [list(ligne["embedding"]) for ligne in sorted(donnees["data"], key=lambda x: x["index"])]
        except (KeyError, TypeError, ValueError):
            raise ErreurAppel("REJ-MODELES-REPONSE-INVALIDE", "réponse d'embeddings invalide", False) from None
        if len(vecteurs) != len(textes):
            raise ErreurAppel("REJ-MODELES-REPONSE-INVALIDE", "un vecteur par texte était attendu", False)
        return {"vecteurs": vecteurs, "usage": _usage(donnees), "latence_ms": latence}

    def rerank(self, modele: str, requete: str, passages: Sequence[str]) -> dict[str, Any]:
        donnees, latence = self._requete(
            "POST", racine_api(self._base) + "/rerank", {"model": modele, "query": requete, "documents": list(passages)}
        )
        try:
            notes = [0.0] * len(passages)
            for ligne in donnees["results"]:
                notes[int(ligne["index"])] = float(ligne["relevance_score"])
        except (KeyError, TypeError, ValueError, IndexError):
            raise ErreurAppel("REJ-MODELES-REPONSE-INVALIDE", "réponse de reranking invalide", False) from None
        return {"notes": notes, "usage": _usage(donnees), "latence_ms": latence}


def _usage(donnees: Any) -> dict[str, int | None]:
    usage = donnees.get("usage") if isinstance(donnees, dict) else None
    usage = usage if isinstance(usage, dict) else {}

    def entier(*cles: str) -> int | None:
        for cle in cles:
            valeur = usage.get(cle)
            if type(valeur) is int and valeur >= 0:
                return valeur
        return None

    return {"entree": entier("prompt_tokens", "input_tokens"), "sortie": entier("completion_tokens", "output_tokens")}


def cout_par_million(valeur: Any) -> str | None:
    """Coût par million de jetons (USD, chaîne décimale) depuis un coût PAR JETON de `/model/info`. `0` ou absent =
    non déclaré : LiteLLM rapporte 0 pour un modèle absent de sa table de prix, ce qui n'est pas « gratuit »."""
    try:
        montant = Decimal(str(valeur)) * Decimal(1_000_000)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not montant.is_finite() or montant <= 0:
        return None
    return format(montant.normalize(), "f")[:24]
