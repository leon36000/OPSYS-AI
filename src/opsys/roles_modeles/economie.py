"""Politique d'économie : classe de tâche → rôle, déclarée EN DONNÉES.

Aucune valeur inventée : chaque ligne est une RECOMMANDATION non validée (`statut`), issue de la consigne du
propriétaire (jetons économisés, Haiku au maximum, Sonnet par défaut, Opus seulement si vraiment nécessaire). Le
propriétaire la valide ou la corrige ; tant que ce n'est pas fait, l'étiquette reste affichée partout.

Règles de fond (testées) :
- une classe INCONNUE est refusée (`REJ-MODELES-CLASSE-INCONNUE`) : jamais d'aiguillage par défaut vers un rôle fort ;
- le raisonnement n'est atteignable que par la classe `escalade_raisonnement`, qui exige une approbation ;
- aucune classe ordinaire ne mène à `llm_raisonnement` (invariant vérifié par `verifier_politique`).
"""

from __future__ import annotations

from typing import Any

from .roles import ROLE_RAISONNEMENT, ROLES, STATUT_RECOMMANDATION

VERSION_POLITIQUE = "2026-11-02/recommandation"
CLASSE_ESCALADE = "escalade_raisonnement"

# classe -> (rôle, approbation requise, libellé)
CLASSES: dict[str, dict[str, Any]] = {
    "classification": {"role": "llm_rapide", "approbation": False, "libelle": "Classer, étiqueter, trier"},
    "extraction": {"role": "llm_rapide", "approbation": False, "libelle": "Extraire des champs d'un texte"},
    "resume_court": {"role": "llm_rapide", "approbation": False, "libelle": "Résumé court"},
    "normalisation": {"role": "llm_rapide", "approbation": False, "libelle": "Normaliser, reformater"},
    "routage": {"role": "llm_rapide", "approbation": False, "libelle": "Choisir un outil ou une file"},
    "redaction": {"role": "llm_fort", "approbation": False, "libelle": "Rédiger (courriel, texte client)"},
    "analyse": {"role": "llm_fort", "approbation": False, "libelle": "Analyser, comparer, expliquer"},
    "resume_long": {"role": "llm_fort", "approbation": False, "libelle": "Résumé long ou multi-documents"},
    "outil_complexe": {"role": "llm_fort", "approbation": False, "libelle": "Enchaîner des outils, planifier"},
    "conversation": {"role": "llm_fort", "approbation": False, "libelle": "Conversation avec une personne"},
    "vision_document": {"role": "vl", "approbation": False, "libelle": "Lire une image ou un document numérisé"},
    "plongement": {"role": "embeddings", "approbation": False, "libelle": "Calculer des embeddings"},
    "reclassement": {"role": "reranker", "approbation": False, "libelle": "Reclasser des passages"},
    "ocr": {"role": "ocr", "approbation": False, "libelle": "Reconnaissance de texte"},
    "transcription": {"role": "stt", "approbation": False, "libelle": "Transcrire de la voix"},
    "synthese_vocale": {"role": "tts", "approbation": False, "libelle": "Synthétiser de la voix"},
    "generation_image": {"role": "image", "approbation": False, "libelle": "Générer une image"},
    CLASSE_ESCALADE: {
        "role": ROLE_RAISONNEMENT,
        "approbation": True,
        "libelle": "Raisonnement poussé : escalade explicite, approuvée, journalisée",
    },
}
for _classe in CLASSES.values():
    _classe["statut"] = STATUT_RECOMMANDATION


class ClasseInconnue(ValueError):
    pass


def verifier_politique(classes: dict[str, dict[str, Any]] | None = None) -> None:
    """Invariants de la politique (appelés par les tests et par la console) ; lève `ValueError` sinon."""
    table = CLASSES if classes is None else classes
    for nom, ligne in table.items():
        if ligne["role"] not in ROLES:
            raise ValueError(f"{nom} : rôle inconnu {ligne['role']!r}")
        if ligne["role"] == ROLE_RAISONNEMENT and (nom != CLASSE_ESCALADE or not ligne["approbation"]):
            raise ValueError(f"{nom} : seul {CLASSE_ESCALADE} mène au raisonnement, avec approbation")
        if nom == CLASSE_ESCALADE and ligne["role"] != ROLE_RAISONNEMENT:
            raise ValueError("l'escalade doit mener au rôle de raisonnement")


def regle(classe: Any) -> dict[str, Any]:
    if not isinstance(classe, str) or classe not in CLASSES:
        raise ClasseInconnue(f"classe de tâche inconnue : {classe!r} (aucun aiguillage par défaut)")
    return CLASSES[classe]


def role_pour(classe: Any) -> str:
    return regle(classe)["role"]


def vue() -> dict[str, Any]:
    return {
        "version": VERSION_POLITIQUE,
        "statut": STATUT_RECOMMANDATION,
        "classes": {nom: dict(ligne) for nom, ligne in CLASSES.items()},
    }
