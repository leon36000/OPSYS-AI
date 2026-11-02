"""Métriques de recherche, fusion RRF, intervalles de confiance par rééchantillonnage et séparation des questions sans
réponse. Module PUR : stdlib seulement, aucune entrée/sortie, aucun hasard hors du générateur graine passé en paramètre.

Conventions
- Un `classement` est une liste d'identifiants de passages, du meilleur au moins bon, sans doublon.
- `pertinents` : ensemble des identifiants qui répondent à la question (rappel@k et MRR).
- `gains` : dictionnaire identifiant -> gain (2 = répond, 1 = utile mais partiel), pour le nDCG@k.
- Les moyennes se font sur les seules questions qui ont au moins un pertinent ; les questions sans réponse ont leur
  propre mesure (AUC et taux de faux acceptés), parce qu'un rappel y est indéfini.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence


def rappel_a_k(classement: Sequence[str], pertinents: set[str] | frozenset[str], k: int) -> float:
    """Part des pertinents retrouvés dans les `k` premiers du classement."""
    if not pertinents:
        raise ValueError("rappel@k indéfini sans passage pertinent")
    if k < 1:
        raise ValueError("k doit être au moins 1")
    return len(set(classement[:k]) & set(pertinents)) / len(pertinents)


def rang_reciproque(classement: Sequence[str], pertinents: set[str] | frozenset[str], k: int = 10) -> float:
    """1 / rang du premier pertinent parmi les `k` premiers ; 0 s'il n'y en a pas."""
    if not pertinents:
        raise ValueError("MRR indéfini sans passage pertinent")
    for rang, identifiant in enumerate(classement[:k], start=1):
        if identifiant in pertinents:
            return 1.0 / rang
    return 0.0


def dcg(gains_dans_l_ordre: Sequence[float]) -> float:
    """DCG avec décote log2(rang + 1), rang depuis 1."""
    return sum(g / math.log2(rang + 1) for rang, g in enumerate(gains_dans_l_ordre, start=1))


def ndcg_a_k(classement: Sequence[str], gains: Mapping[str, float], k: int = 10) -> float:
    """nDCG@k = DCG du classement / DCG du classement idéal (gains triés décroissant). Indéfini si aucun gain."""
    ideal = sorted((g for g in gains.values() if g > 0), reverse=True)[:k]
    if not ideal:
        raise ValueError("nDCG indéfini sans gain positif")
    obtenu = [gains.get(identifiant, 0.0) for identifiant in classement[:k]]
    return dcg(obtenu) / dcg(ideal)


def moyenne(valeurs: Sequence[float]) -> float:
    if not valeurs:
        raise ValueError("moyenne d'une liste vide")
    return sum(valeurs) / len(valeurs)


def quantile(valeurs: Sequence[float], q: float) -> float:
    """Quantile par interpolation linéaire entre les rangs voisins (méthode 7 de R / numpy par défaut)."""
    if not valeurs:
        raise ValueError("quantile d'une liste vide")
    if not 0.0 <= q <= 1.0:
        raise ValueError("q dans [0, 1]")
    tri = sorted(valeurs)
    position = q * (len(tri) - 1)
    bas = math.floor(position)
    haut = math.ceil(position)
    return tri[bas] + (tri[haut] - tri[bas]) * (position - bas)


def intervalle_bootstrap(valeurs: Sequence[float], *, graine: int, repetitions: int = 2000, niveau: float = 0.95
                         ) -> tuple[float, float]:
    """Intervalle de confiance percentile de la MOYENNE, par rééchantillonnage des QUESTIONS avec remise."""
    if not valeurs:
        raise ValueError("intervalle d'une liste vide")
    if not 0.0 < niveau < 1.0:
        raise ValueError("niveau dans ]0, 1[")
    alea = random.Random(graine)
    n = len(valeurs)
    moyennes = sorted(sum(valeurs[alea.randrange(n)] for _ in range(n)) / n for _ in range(repetitions))
    alpha = (1.0 - niveau) / 2.0
    return quantile(moyennes, alpha), quantile(moyennes, 1.0 - alpha)


def difference_appariee(a: Sequence[float], b: Sequence[float], *, graine: int, repetitions: int = 2000,
                        niveau: float = 0.95) -> tuple[float, float, float]:
    """(écart moyen a - b, borne basse, borne haute) sur les MÊMES questions. Si l'intervalle contient 0, l'écart
    n'est pas distinguable du bruit d'échantillonnage à ce niveau."""
    if len(a) != len(b):
        raise ValueError("séries de longueurs différentes : différence appariée impossible")
    ecarts = [x - y for x, y in zip(a, b, strict=True)]
    bas, haut = intervalle_bootstrap(ecarts, graine=graine, repetitions=repetitions, niveau=niveau)
    return moyenne(ecarts), bas, haut


def fusion_rrf(listes: Sequence[Sequence[str]], k: int = 60, poids: Sequence[float] | None = None
               ) -> dict[str, float]:
    """Reciprocal Rank Fusion (Cormack et coll., 2009) : score = somme de poids / (k + rang), rang depuis 1. Sans
    `poids`, chaque liste compte pour 1 (c'est la fusion du produit)."""
    if k < 0:
        raise ValueError("k négatif")
    if poids is not None and (len(poids) != len(listes) or any(p < 0 for p in poids)):
        raise ValueError("un poids positif ou nul par liste")
    scores: dict[str, float] = {}
    for position, liste in enumerate(listes):
        poids_liste = 1.0 if poids is None else poids[position]
        for rang, identifiant in enumerate(liste, start=1):
            scores[identifiant] = scores.get(identifiant, 0.0) + poids_liste / (k + rang)
    return scores


def classer(scores: Mapping[str, float]) -> list[str]:
    """Identifiants du plus au moins bon score ; à égalité, ordre alphabétique (déterministe)."""
    return [identifiant for identifiant, _ in sorted(scores.items(), key=lambda t: (-t[1], t[0]))]


def fusionner(listes: Sequence[Sequence[str]], k: int = 60, poids: Sequence[float] | None = None) -> list[str]:
    return classer(fusion_rrf(listes, k, poids))


def cosinus(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("dimensions différentes")
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        raise ValueError("vecteur nul")
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def auc(positifs: Sequence[float], negatifs: Sequence[float]) -> float:
    """Probabilité qu'un score « avec réponse » dépasse un score « sans réponse » (égalités comptées pour moitié).
    1,0 = séparation parfaite ; 0,5 = aucune."""
    if not positifs or not negatifs:
        raise ValueError("AUC : il faut des scores des deux groupes")
    total = 0.0
    for p in positifs:
        for n in negatifs:
            total += 1.0 if p > n else 0.5 if p == n else 0.0
    return total / (len(positifs) * len(negatifs))


def faux_acceptes_au_rappel(positifs: Sequence[float], negatifs: Sequence[float], rappel_cible: float = 0.9
                            ) -> tuple[float, float]:
    """(seuil, part des questions sans réponse acceptées à tort) quand le seuil laisse passer `rappel_cible` des
    questions avec réponse (seuil = quantile 1 - rappel_cible des scores positifs ; accepté si score >= seuil)."""
    if not positifs or not negatifs:
        raise ValueError("il faut des scores des deux groupes")
    if not 0.0 < rappel_cible <= 1.0:
        raise ValueError("rappel cible dans ]0, 1]")
    seuil = quantile(positifs, 1.0 - rappel_cible)
    return seuil, sum(1 for n in negatifs if n >= seuil) / len(negatifs)
