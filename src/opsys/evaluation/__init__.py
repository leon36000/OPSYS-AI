"""Gabarit d'évaluation commun aux dix départements (`docs/architecture/EVALUATION.md`).

Chaque département remplit le même format de corpus (`departments/mNN-*/evals/gabarit.v1.yaml`) ; un exécuteur
déterministe soumet chaque cas à un « répondant » derrière un port, exécute pour de vrai les appels d'outils sûrs sur
une instance fictive temporaire, sonde les refus d'autorité du dépôt et rend un rapport (JSON et Markdown) par
département et par catégorie. Aucune vérification ne passe par un modèle-juge : toutes les attentes sont
vérifiables de façon déterministe. « CI verte » n'est pas « qualité » : un département n'est qualifié que si aucun
cas bloquant n'échoue ET si son score atteint le seuil du gabarit.
"""

from __future__ import annotations

from .corpus import CATEGORIES, CODES_REFUS, GRAVITES, RefusEvaluation, charger_corpus, valider_corpus

__all__ = ["CATEGORIES", "CODES_REFUS", "GRAVITES", "RefusEvaluation", "charger_corpus", "valider_corpus"]
