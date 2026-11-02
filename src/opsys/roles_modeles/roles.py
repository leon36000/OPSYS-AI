"""Les dix RÔLES de modèles et leurs recommandations.

Un rôle est un besoin technique d'OPSYS-AI (« un LLM rapide », « des embeddings »…), pas un modèle : le propriétaire
lui affecte un fournisseur du registre (`opsys.fournisseurs`) et un nom de modèle à appeler. Les départements ne
voient jamais un modèle précis (ils déclarent un palier ou une classe de tâche).

**Recommandations.** Chaque rôle porte un défaut PROPOSÉ au propriétaire, étiqueté `recommandation_non_validee` :
c'est une suggestion de départ (consigne du propriétaire : économiser les jetons, Haiku au maximum, Sonnet par
défaut, Opus seulement si nécessaire), jamais une valeur appliquée d'office. Sans affectation, un rôle est inerte
(fail-closed). Aucune mesure locale n'existe : tout reste « non mesuré » tant qu'un test de connexion n'a pas écrit une
mesure.
"""

from __future__ import annotations

from typing import Any

ROLES: tuple[str, ...] = (
    "llm_rapide",
    "llm_fort",
    "llm_raisonnement",
    "embeddings",
    "reranker",
    "ocr",
    "vl",
    "stt",
    "tts",
    "image",
)
ROLES_LLM: tuple[str, ...] = ("llm_rapide", "llm_fort", "llm_raisonnement")
ROLE_RAISONNEMENT = "llm_raisonnement"
ROLE_FORT = "llm_fort"
ROLE_RAPIDE = "llm_rapide"

# Capacité du registre de fournisseurs qui sert chaque rôle. `vl` (modèle vision-langage multimodal) est un LLM qui
# accepte des images : la capacité « vision » du registre est la détection/segmentation d'objets (autre chose).
CAPACITE_DU_ROLE: dict[str, str] = {
    "llm_rapide": "llm",
    "llm_fort": "llm",
    "llm_raisonnement": "llm",
    "vl": "llm",
    "embeddings": "embeddings",
    "reranker": "reranker",
    "ocr": "ocr",
    "stt": "stt",
    "tts": "tts",
    "image": "image",
}
# Rôles dont la capacité a un SEUL fournisseur par portée dans `fournisseurs_selections` : l'affectation du rôle
# met alors aussi à jour la sélection globale, pour que les consommateurs existants (M10…) lisent la même vérité.
ROLES_AVEC_SELECTION: tuple[str, ...] = ("embeddings", "reranker", "ocr", "stt", "tts", "image")

LIBELLES: dict[str, str] = {
    "llm_rapide": "LLM rapide (tâches mécaniques)",
    "llm_fort": "LLM fort (rédaction, analyse, outils)",
    "llm_raisonnement": "LLM de raisonnement (escalade explicite seulement)",
    "embeddings": "Embeddings",
    "reranker": "Reranker",
    "ocr": "OCR / parsing de documents",
    "vl": "Vision-langage (lecture d'images)",
    "stt": "Voix → texte",
    "tts": "Texte → voix",
    "image": "Génération d'image",
}

# Alias de passerelle par défaut (nom exposé par LiteLLM). Les alias de PALIER historiques restent ceux que lisent les
# agents (OpenClaw) : `opsys-rapide`, `opsys-standard`, `opsys-fort`. Aucun palier n'est jamais aiguillé vers le rôle
# de raisonnement : le propriétaire garde l'escalade (consigne : Opus seulement si vraiment nécessaire).
ALIAS_ROLE: dict[str, str] = {role: "opsys-" + role.replace("_", "-") for role in ROLES}
PALIER_VERS_ROLE: dict[str, str] = {"rapide": ROLE_RAPIDE, "standard": ROLE_FORT, "fort": ROLE_FORT}

STATUT_RECOMMANDATION = "recommandation_non_validee"

# Défauts PROPOSÉS (modèle amont suggéré sur OpenRouter, nom de passerelle). À valider par le propriétaire ; coût et
# qualité ne sont pas mesurés ici.
RECOMMANDATIONS: dict[str, dict[str, Any]] = {
    "llm_rapide": {
        "modele_amont": "anthropic/claude-haiku-5.5",
        "alias": "opsys-haiku-5-5",
        "raison": "tâches mécaniques (classification, extraction, résumé court) : le moins cher d'abord",
    },
    "llm_fort": {
        "modele_amont": "anthropic/claude-sonnet-5.5",
        "alias": "opsys-sonnet-5-5",
        "raison": "défaut pour la rédaction, l'analyse et les outils complexes",
    },
    "llm_raisonnement": {
        "modele_amont": "anthropic/claude-opus-5.5",
        "alias": "opsys-opus-5-5",
        "raison": "escalade explicite et approuvée seulement ; jamais un défaut ni un repli",
    },
    "embeddings": {
        "modele_amont": "intfloat/multilingual-e5-large",
        "alias": "opsys-embed-e5-multilingue",
        "raison": "multilingue (français) ; la dimension est mesurée au test de connexion",
    },
    "vl": {
        "modele_amont": "qwen/qwen3-vl-30b-a3b-instruct",
        "alias": "opsys-vl-qwen3-30b",
        "raison": "lecture de photos et de documents numérisés",
    },
}
for _role in RECOMMANDATIONS.values():
    _role["statut"] = STATUT_RECOMMANDATION


def verifier_role(role: Any) -> str:
    if not isinstance(role, str) or role not in ROLES:
        raise ValueError(f"rôle inconnu : attendu {', '.join(ROLES)}")
    return role
