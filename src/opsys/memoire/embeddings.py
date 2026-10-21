"""Client d'embeddings OpenAI-compatible (`POST {base_url}/embeddings`), bibliothèque standard seule.

Il sert BAAI/bge-m3 (1 024 dimensions) :
- par défaut, via un endpoint local sur le VPS ;
- sinon, via un service cloud. Les données quittent alors le VPS : une EFVP est exigée (Loi 25,
  art. 17). Voir docs/memory/RAG-PREMIUM.md §3 et §6.

Aucune valeur par défaut n'est inventée : l'URL et le modèle viennent de l'environnement. Chaque panne
lève une `ErreurEmbeddings` qui dit quoi corriger, sans jamais révéler la clé.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

from .profil_embeddings_local import DIMENSION_LOCALE, MODELE_LOCAL, PROFILE_SHA256, RECETTE_CANONIQUE

ENV_URL = "OPSYS_EMBEDDINGS_URL"
ENV_MODELE = "OPSYS_EMBEDDINGS_MODELE"
ENV_CLE = "OPSYS_EMBEDDINGS_CLE"
ENV_LOCAL = "OPSYS_EMBEDDINGS_LOCAL"
ENV_TAILLE_LOT = "OPSYS_EMBEDDINGS_TAILLE_LOT"
DIMENSION = DIMENSION_LOCALE  # bge-m3 dense ; doit correspondre à vector(1024) de schema.sql
MAX_REPONSE_OCTETS = 1_000_000  # 32 × 1 024 nombres JSON + enveloppe OpenAI


class ErreurEmbeddings(RuntimeError):
    """Service d'embeddings mal configuré, injoignable, ou dont la réponse est inexploitable."""

    def __init__(self, message: str, *, code: str | None = None, http_status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


@dataclasses.dataclass(frozen=True)
class EmbeddingsProfil:
    vecteurs: tuple[tuple[float, ...], ...]
    profile_sha256: str


def _valider_profil(profil: Any, modele: str, dimension: int) -> str:
    if not isinstance(profil, dict) or set(profil) != {"id", "recipe"}:
        raise ErreurEmbeddings("empreinte de profil absente ou mal formée")
    ident, recette = profil.get("id"), profil.get("recipe")
    if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{64}", ident) or not isinstance(recette, dict):
        raise ErreurEmbeddings("empreinte de profil absente ou mal formée")
    if type(dimension) is not int or modele != MODELE_LOCAL or dimension != DIMENSION_LOCALE:
        raise ErreurEmbeddings("modèle ou dimension locale incompatibles")
    try:
        canonique = json.dumps(recette, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ErreurEmbeddings("recette de profil non canonique") from exc
    if canonique != RECETTE_CANONIQUE or ident != PROFILE_SHA256:
        raise ErreurEmbeddings("empreinte de profil différente de la recette locale canonique")
    return PROFILE_SHA256


@dataclasses.dataclass(frozen=True)
class ClientEmbeddings:
    base_url: str  # base OpenAI-compatible, ex. http://embeddings:11434/v1
    modele: str
    cle: str | None = dataclasses.field(default=None, repr=False)
    local: bool = False  # True seulement si l'endpoint tourne sur le VPS (données personnelles admises)
    dimension: int = DIMENSION
    taille_lot: int = 32
    delai_s: float = 30.0

    def __post_init__(self) -> None:
        url = self.base_url.strip().rstrip("/")
        parties = urllib.parse.urlsplit(url)
        if parties.scheme not in ("http", "https") or not parties.hostname:
            raise ErreurEmbeddings(
                f"{ENV_URL} doit être une URL http(s) avec un hôte (ex. http://embeddings:11434/v1) ; "
                f"schéma reçu : {parties.scheme or 'aucun'}"
            )
        if not self.modele.strip():
            raise ErreurEmbeddings(f"{ENV_MODELE} vide : aucun modèle d'embeddings par défaut")
        if self.dimension < 1 or self.taille_lot < 1 or self.delai_s <= 0:
            raise ErreurEmbeddings("dimension, taille_lot et delai_s doivent être strictement positifs")
        object.__setattr__(self, "base_url", url)
        object.__setattr__(self, "modele", self.modele.strip())

    @classmethod
    def depuis_env(cls, environ: Mapping[str, str] | None = None) -> ClientEmbeddings | None:
        """Client configuré par l'environnement ; None si `OPSYS_EMBEDDINGS_URL` est absente.

        None signifie « pas d'embeddings » : l'appelant passe en mode plein texte explicite.
        """
        env = os.environ if environ is None else environ
        url = env.get(ENV_URL, "").strip()
        if not url:
            return None
        modele = env.get(ENV_MODELE, "").strip()
        if not modele:
            raise ErreurEmbeddings(
                f"{ENV_URL} est définie mais {ENV_MODELE} est absente : aucun modèle d'embeddings par défaut"
            )
        lot_brut = env.get(ENV_TAILLE_LOT)
        taille_lot = 32
        if lot_brut is not None:
            if len(lot_brut) > 2 or not lot_brut.isascii() or not lot_brut.isdigit():
                raise ErreurEmbeddings(f"{ENV_TAILLE_LOT} doit être un entier entre 1 et 32")
            taille_lot = int(lot_brut)
            if not 1 <= taille_lot <= 32 or str(taille_lot) != lot_brut:
                raise ErreurEmbeddings(f"{ENV_TAILLE_LOT} doit être un entier entre 1 et 32")
        return cls(
            base_url=url,
            modele=modele,
            cle=env.get(ENV_CLE, "").strip() or None,
            local=env.get(ENV_LOCAL, "").strip() == "1",
            taille_lot=taille_lot,
        )

    @property
    def _cible(self) -> str:
        parties = urllib.parse.urlsplit(self.base_url)
        port = f":{parties.port}" if parties.port else ""
        return f"{parties.scheme}://{parties.hostname}{port}"

    def plonger(self, textes: Sequence[str]) -> list[list[float]]:
        """Un vecteur par texte, dans l'ordre des textes, par lots de `taille_lot`."""
        liste = list(textes)
        for position, texte in enumerate(liste):
            if not isinstance(texte, str) or not texte.strip():
                raise ValueError(f"texte vide ou non textuel à la position {position} : rien à vectoriser")
        vecteurs: list[list[float]] = []
        for debut in range(0, len(liste), self.taille_lot):
            vecteurs.extend(self._appeler(liste[debut : debut + self.taille_lot]))
        return vecteurs

    def verifier_profil_local(self) -> str:
        """Effectue le handshake authentifié et retourne l'empreinte de recette exacte."""
        if not self.local:
            raise ErreurEmbeddings("la vectorisation des procédures exige un provider explicitement local")
        entetes = {"Accept": "application/json"}
        if self.cle:
            entetes["Authorization"] = f"Bearer {self.cle}"
        racine = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        requete = urllib.request.Request(f"{racine}/healthz", headers=entetes, method="GET")
        try:
            with urllib.request.urlopen(requete, timeout=self.delai_s) as reponse:  # noqa: S310 - URL validée
                brut = reponse.read(8193)
                if len(brut) > 8192:
                    raise ErreurEmbeddings("handshake du provider trop volumineux")
        except urllib.error.HTTPError as exc:
            raise self._erreur_http(exc, "handshake") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ErreurEmbeddings(f"handshake du provider local impossible ({self._cible})") from exc
        donnees = self._json(brut, "handshake")
        if not isinstance(donnees, dict) or donnees.get("status") != "ready":
            raise ErreurEmbeddings("provider local non prêt")
        if donnees.get("model") != self.modele or donnees.get("dimension") != self.dimension:
            raise ErreurEmbeddings("modèle ou dimension du handshake incompatibles")
        return _valider_profil(donnees.get("opsys_embedding_profile"), self.modele, self.dimension)

    def plonger_avec_profil(self, textes: Sequence[str]) -> EmbeddingsProfil:
        """Vectorise après handshake; chaque réponse porte la même recette fingerprintée.

        Un 503 local connu autorise une seule reprise par lot après une seconde : le worker
        précédent peut terminer sa fermeture. `delai_s` borne chaque requête HTTP, pas le lot.
        """
        liste = list(textes)
        for position, texte in enumerate(liste):
            if not isinstance(texte, str) or not texte.strip():
                raise ValueError(f"texte vide ou non textuel à la position {position} : rien à vectoriser")
        profil = self.verifier_profil_local()
        vecteurs: list[tuple[float, ...]] = []
        for debut in range(0, len(liste), self.taille_lot):
            lot = liste[debut : debut + self.taille_lot]
            try:
                groupe, profil_reponse = self._appeler_reponse(lot)
            except ErreurEmbeddings as exc:
                if not self.local or exc.http_status != 503:
                    raise
                time.sleep(1)
                groupe, profil_reponse = self._appeler_reponse(lot)
            if profil_reponse != profil:
                raise ErreurEmbeddings("empreinte de réponse différente du handshake du provider")
            vecteurs.extend(tuple(v) for v in groupe)
        return EmbeddingsProfil(tuple(vecteurs), profil)

    # -- transport ---------------------------------------------------------------------------------
    def _masquer(self, texte: str) -> str:
        return texte.replace(self.cle, "***") if self.cle else texte

    def _appeler(self, lot: list[str]) -> list[list[float]]:
        return self._appeler_reponse(lot)[0]

    def _appeler_reponse(self, lot: list[str]) -> tuple[list[list[float]], str | None]:
        entetes = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.cle:
            entetes["Authorization"] = f"Bearer {self.cle}"
        requete = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=json.dumps({"model": self.modele, "input": lot}).encode("utf-8"),
            headers=entetes,
            method="POST",
        )
        try:
            with urllib.request.urlopen(requete, timeout=self.delai_s) as reponse:  # noqa: S310 - http(s) vérifié
                brut = reponse.read(MAX_REPONSE_OCTETS + 1)
                if len(brut) > MAX_REPONSE_OCTETS:
                    raise ErreurEmbeddings(f"réponse d'embeddings supérieure à {MAX_REPONSE_OCTETS} octets")
        except urllib.error.HTTPError as exc:
            raise self._erreur_http(exc, "embedding") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ErreurEmbeddings(f"délai de {self.delai_s} s dépassé vers {self._cible}") from exc
            raise ErreurEmbeddings(f"endpoint d'embeddings injoignable ({self._cible}) : {exc.reason}") from exc
        except TimeoutError as exc:
            raise ErreurEmbeddings(f"délai de {self.delai_s} s dépassé vers {self._cible}") from exc
        except OSError as exc:
            raise ErreurEmbeddings(f"endpoint d'embeddings injoignable ({self._cible}) : {exc}") from exc
        return self._lire_reponse(brut, len(lot))

    def _erreur_http(self, exc: urllib.error.HTTPError, action: str) -> ErreurEmbeddings:
        brut = exc.read(2048)
        code = None

        def objet_sans_doublon(paires: list[tuple[str, Any]]) -> dict[str, Any]:
            objet: dict[str, Any] = {}
            for cle, valeur in paires:
                if cle in objet:
                    raise ValueError("clé JSON dupliquée")
                objet[cle] = valeur
            return objet

        try:
            corps = json.loads(brut, object_pairs_hook=objet_sans_doublon)
            error = corps.get("error") if isinstance(corps, dict) else None
            candidat = error.get("code") if isinstance(error, dict) else None
            if isinstance(candidat, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", candidat):
                code = candidat
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            pass
        # Le corps d'erreur d'un endpoint n'est pas fiable et pourrait répéter le texte d'entrée.
        detail = f"; code={code}" if code else ""
        return ErreurEmbeddings(
            f"HTTP {exc.code} de l'endpoint d'embeddings {self._cible} ({action}){detail}",
            code=code, http_status=exc.code,
        )

    def _json(self, brut: bytes, action: str) -> Any:
        def objet_sans_doublon(paires: list[tuple[str, Any]]) -> dict[str, Any]:
            objet: dict[str, Any] = {}
            for cle, valeur in paires:
                if cle in objet:
                    raise ValueError("clé JSON dupliquée")
                objet[cle] = valeur
            return objet

        try:
            return json.loads(brut, object_pairs_hook=objet_sans_doublon)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise ErreurEmbeddings(f"réponse non JSON du provider local ({action})") from exc

    def _lire(self, brut: bytes, attendus: int) -> list[list[float]]:
        return self._lire_reponse(brut, attendus)[0]

    def _lire_reponse(self, brut: bytes, attendus: int) -> tuple[list[list[float]], str | None]:
        donnees: Any = self._json(brut, "embedding")
        elements = donnees.get("data") if isinstance(donnees, dict) else None
        if not isinstance(elements, list):
            raise ErreurEmbeddings(f"réponse sans liste « data » de {self._cible} (format OpenAI attendu)")
        if len(elements) != attendus:
            raise ErreurEmbeddings(f"{len(elements)} vecteur(s) reçu(s) pour {attendus} texte(s)")
        par_index: dict[int, list[float]] = {}
        for position, element in enumerate(elements):
            index = element.get("index", position) if isinstance(element, dict) else None
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < attendus or index in par_index:
                raise ErreurEmbeddings(f"index de vecteur absent, invalide ou en double : {index!r}")
            par_index[index] = self._valider(element.get("embedding"), index)
        profil_brut = donnees.get("opsys_embedding_profile") if isinstance(donnees, dict) else None
        profil = None if profil_brut is None else _valider_profil(profil_brut, self.modele, self.dimension)
        return [par_index[i] for i in range(attendus)], profil

    def _valider(self, vecteur: Any, index: int) -> list[float]:
        if not isinstance(vecteur, list):
            raise ErreurEmbeddings(f"vecteur {index} absent ou non numérique (encodage « float » attendu)")
        if len(vecteur) != self.dimension:
            raise ErreurEmbeddings(
                f"vecteur {index} de dimension {len(vecteur)} (attendu {self.dimension}) : "
                "modèle incompatible avec le schéma"
            )
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in vecteur):
            raise ErreurEmbeddings(f"valeur non finie ou non numérique dans le vecteur {index}")
        return [float(v) for v in vecteur]
