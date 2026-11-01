"""Doubles DÉTERMINISTES des ports d'embeddings et de reranker : pour les tests et le harnais de mesure. Ils ne sont pas
des modèles.

**Ce que ces doubles ne mesurent pas.** `EmbeddingsDeterministe` est un hachage de termes et de trigrammes de
caractères en dimension fixe : il rapproche des textes qui PARTAGENT des mots, des radicaux ou des fragments de mots
(pluriels, fautes de frappe, formes dérivées proches). Il ne comprend aucun sens : « voiture » et « automobile » n'ont
aucun lien pour lui, alors qu'un vrai modèle (bge-m3, Qwen3-Embedding) les rapproche. Les métriques calculées avec lui
valident le HARNAIS, la fusion et la plomberie ; elles ne disent rien de la qualité d'un vrai modèle sur du français
québécois, qui reste à mesurer sur nos propres corpus avant toute adoption (FEUILLE DE ROUTE, B.4).
`RerankerDeterministe` n'est pas un cross-encodeur : c'est une couverture de termes pondérée.

Aucun réseau, aucune horloge, aucun hasard : mêmes entrées, mêmes sorties, sur toute machine.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from ..fournisseurs.modele import Fournisseur
from . import normalisation
from .ports import IdentiteReranker, ProfilEmbeddings, empreinte_configuration

IDENTIFIANT_DOUBLE_EMBEDDINGS = "embeddings.double-test"
IDENTIFIANT_DOUBLE_RERANKER = "reranker.double-test"


class EmbeddingsDeterministe:
    """Hachage signé de termes (poids 1) et de trigrammes de caractères (poids 0,5) en dimension `dimension`."""

    def __init__(self, *, modele: str = "double-hachage-v1", dimension: int = 256,
                 fournisseur: Fournisseur | None = None) -> None:
        self._modele, self._dimension = modele, dimension
        if fournisseur is not None:
            self._profil = ProfilEmbeddings(fournisseur.identifiant, modele, dimension,
                empreinte_configuration(fournisseur))
        else:
            graine = hashlib.sha256(f"{IDENTIFIANT_DOUBLE_EMBEDDINGS}|{modele}|{dimension}".encode()).hexdigest()
            self._profil = ProfilEmbeddings(IDENTIFIANT_DOUBLE_EMBEDDINGS, modele, dimension, graine)

    def profil(self) -> ProfilEmbeddings:
        return self._profil

    def _vecteur(self, texte: str) -> list[float]:
        v = [0.0] * self._dimension
        for terme in normalisation.termes(texte):
            self._ajouter(v, f"t:{terme}", 1.0)
            borne = f"^{terme}$"
            for i in range(len(borne) - 2):
                self._ajouter(v, f"g:{borne[i:i + 3]}", 0.5)
        if not any(v):  # texte sans terme : vecteur déterministe non nul (jamais un vecteur nul)
            self._ajouter(v, "vide", 1.0)
        return v

    def _ajouter(self, v: list[float], trait: str, poids: float) -> None:
        h = hashlib.blake2b(f"{self._modele}|{trait}".encode(), digest_size=8).digest()
        n = int.from_bytes(h, "big")
        v[n % self._dimension] += poids if (n >> 40) & 1 else -poids

    def plonger_documents(self, textes: Sequence[str]) -> list[list[float]]:
        return [self._vecteur(t) for t in textes]

    def plonger_requete(self, texte: str) -> list[float]:
        return self._vecteur(texte)


class RerankerDeterministe:
    """Note = part des termes de la requête présents dans le passage + 0,25 × part des paires de termes consécutifs."""

    def __init__(self, *, fournisseur: Fournisseur | None = None, modele: str = "double-couverture-v1") -> None:
        if fournisseur is not None:
            self._identite = IdentiteReranker(fournisseur.identifiant, modele, empreinte_configuration(fournisseur))
        else:
            self._identite = IdentiteReranker(
                IDENTIFIANT_DOUBLE_RERANKER, modele,
                    hashlib.sha256(f"{IDENTIFIANT_DOUBLE_RERANKER}|{modele}".encode()).hexdigest())

    def identite(self) -> IdentiteReranker:
        return self._identite

    def noter(self, requete: str, passages: Sequence[str]) -> list[float]:
        termes_q = normalisation.termes_uniques(requete)
        paires_q = set(zip(normalisation.termes(requete), normalisation.termes(requete)[1:], strict=False))
        notes: list[float] = []
        for passage in passages:
            termes_p = normalisation.termes(passage)
            presents = set(termes_p)
            couverture = sum(1 for t in termes_q if t in presents) / len(termes_q) if termes_q else 0.0
            paires_p = set(zip(termes_p, termes_p[1:], strict=False))
            bigrammes = len(paires_q & paires_p) / len(paires_q) if paires_q else 0.0
            notes.append(round(couverture + 0.25 * bigrammes, 6))
        return notes
