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
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

ENV_URL = "OPSYS_EMBEDDINGS_URL"
ENV_MODELE = "OPSYS_EMBEDDINGS_MODELE"
ENV_CLE = "OPSYS_EMBEDDINGS_CLE"
ENV_LOCAL = "OPSYS_EMBEDDINGS_LOCAL"
DIMENSION = 1024  # bge-m3 dense ; doit correspondre à vector(1024) de schema.sql


class ErreurEmbeddings(RuntimeError):
    """Service d'embeddings mal configuré, injoignable, ou dont la réponse est inexploitable."""


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
            raise ErreurEmbeddings(f"{ENV_URL} est définie mais {ENV_MODELE} est absente : "
                                   "aucun modèle d'embeddings par défaut")
        return cls(base_url=url, modele=modele, cle=env.get(ENV_CLE, "").strip() or None,
                   local=env.get(ENV_LOCAL, "").strip() == "1")

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
            vecteurs.extend(self._appeler(liste[debut:debut + self.taille_lot]))
        return vecteurs

    # -- transport ---------------------------------------------------------------------------------
    def _masquer(self, texte: str) -> str:
        return texte.replace(self.cle, "***") if self.cle else texte

    def _appeler(self, lot: list[str]) -> list[list[float]]:
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
                brut = reponse.read()
        except urllib.error.HTTPError as exc:
            detail = self._masquer(exc.read(300).decode("utf-8", "replace").strip()) or exc.reason
            raise ErreurEmbeddings(f"HTTP {exc.code} de l'endpoint d'embeddings {self._cible} : {detail}") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ErreurEmbeddings(f"délai de {self.delai_s} s dépassé vers {self._cible}") from exc
            raise ErreurEmbeddings(f"endpoint d'embeddings injoignable ({self._cible}) : {exc.reason}") from exc
        except TimeoutError as exc:
            raise ErreurEmbeddings(f"délai de {self.delai_s} s dépassé vers {self._cible}") from exc
        except OSError as exc:
            raise ErreurEmbeddings(f"endpoint d'embeddings injoignable ({self._cible}) : {exc}") from exc
        return self._lire(brut, len(lot))

    def _lire(self, brut: bytes, attendus: int) -> list[list[float]]:
        try:
            donnees: Any = json.loads(brut)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ErreurEmbeddings(f"réponse non JSON de l'endpoint d'embeddings {self._cible}") from exc
        elements = donnees.get("data") if isinstance(donnees, dict) else None
        if not isinstance(elements, list):
            raise ErreurEmbeddings(f"réponse sans liste « data » de {self._cible} (format OpenAI attendu)")
        if len(elements) != attendus:
            raise ErreurEmbeddings(f"{len(elements)} vecteur(s) reçu(s) pour {attendus} texte(s)")
        par_index: dict[int, list[float]] = {}
        for position, element in enumerate(elements):
            index = element.get("index", position) if isinstance(element, dict) else None
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < attendus \
                    or index in par_index:
                raise ErreurEmbeddings(f"index de vecteur absent, invalide ou en double : {index!r}")
            par_index[index] = self._valider(element.get("embedding"), index)
        return [par_index[i] for i in range(attendus)]

    def _valider(self, vecteur: Any, index: int) -> list[float]:
        if not isinstance(vecteur, list):
            raise ErreurEmbeddings(f"vecteur {index} absent ou non numérique (encodage « float » attendu)")
        if len(vecteur) != self.dimension:
            raise ErreurEmbeddings(f"vecteur {index} de dimension {len(vecteur)} (attendu {self.dimension}) : "
                                   "modèle incompatible avec le schéma")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in vecteur):
            raise ErreurEmbeddings(f"valeur non finie ou non numérique dans le vecteur {index}")
        return [float(v) for v in vecteur]
