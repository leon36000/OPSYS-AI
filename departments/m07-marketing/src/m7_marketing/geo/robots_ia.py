"""Robots d'IA et `robots.txt` du site du client : qui y est autorisé, et est-ce ce que le client a décidé ?

La liste des robots est FERMÉE et sa source est dite : R4 §4.2 (niveaux de preuve S ou H, à revérifier dans la
documentation de chaque éditeur avant de s'y fier). Trois catégories, parce qu'elles n'ont pas les mêmes conséquences :
- `recherche` : le robot construit l'index d'un moteur de réponses (bloquer OAI-SearchBot exclut le site de la
recherche de
  ChatGPT, R4 §4.2) ;
- `recuperation_a_la_demande` : le robot va chercher la page parce qu'une personne l'a demandée à l'assistant ;
- `entrainement` : le robot nourrit l'entraînement d'un modèle ; la décision appartient au client (R4 §4.2).

Le client DÉCIDE (`politique`) : aucune valeur par défaut, l'absence d'une des trois catégories est un refus typé.
Ce module constate et RECOMMANDE la ligne à ajouter à `robots.txt` ; il ne modifie rien. Il ne promet aucune
visibilité : la page officielle de Google (R4 §4.1, V) dit qu'aucune optimisation spéciale n'est requise pour
apparaître dans les fonctions d'IA ; `llms.txt` coûte presque rien et n'a quasi aucun effet démontré (R4 §4.2, S) :
générer, sans rien promettre.

Module pur : aucune entrée-sortie ; le texte de `robots.txt` et le statut HTTP de sa réponse sont fournis par
l'appelant.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from ..veille import robots

CATEGORIES = ("recherche", "recuperation_a_la_demande", "entrainement")
DECISIONS = ("autoriser", "bloquer")
SOURCE_LISTE = "R4 §4.2 (niveaux de preuve S/H) : liste fermée, à revérifier dans la documentation de chaque éditeur"


class ErreurGeo(ValueError):
    """Refus typé du volet GEO (`REJ-GEO-…`) : `code` stable, `detail` lisible. C'est un `ValueError` (un outil qui
    la laisse
    sortir obtient un refus métier normal)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code, self.detail = code, detail


@dataclasses.dataclass(frozen=True)
class RobotIA:
    nom: str
    categorie: str
    editeur: str
    niveau_preuve: str  # S (source secondaire) ou H (hypothèse) selon R4
    a_verifier: bool = True


ROBOTS_IA: tuple[RobotIA, ...] = (
    RobotIA("OAI-SearchBot", "recherche", "OpenAI", "S"),
    RobotIA("ChatGPT-User", "recuperation_a_la_demande", "OpenAI", "S"),
    RobotIA("GPTBot", "entrainement", "OpenAI", "S"),
    RobotIA("PerplexityBot", "recherche", "Perplexity", "S"),
    RobotIA("Perplexity-User", "recuperation_a_la_demande", "Perplexity", "S"),
    RobotIA("ClaudeBot", "entrainement", "Anthropic", "H"),
    RobotIA("Claude-User", "recuperation_a_la_demande", "Anthropic", "H"),
    RobotIA("Claude-SearchBot", "recherche", "Anthropic", "H"),
    RobotIA("Google-Extended", "entrainement", "Google", "S"),
    RobotIA("Applebot-Extended", "entrainement", "Apple", "H"),
    RobotIA("CCBot", "entrainement", "Common Crawl", "H"),
    RobotIA("Bingbot", "recherche", "Microsoft", "S"),
)
PAR_NOM: Mapping[str, RobotIA] = {r.nom: r for r in ROBOTS_IA}

AVERTISSEMENTS = (
    "Liste de robots, catégories et noms d'agents : à revérifier dans la documentation de chaque éditeur (R4 §4.2, "
    "niveaux S/H).",
    "Aucune visibilité n'est promise : Google indique qu'aucune optimisation spéciale n'est requise pour "
    "apparaître dans "
    "ses fonctions d'IA (R4 §4.1).",
    "llms.txt : coût quasi nul, effet quasi jamais démontré (R4 §4.2) ; on peut le générer, sans rien promettre.",
    "Bingbot est aussi le robot de la recherche Bing elle-même : le bloquer retire le site de Bing, pas seulement "
    "de Copilot.",
)


def valider_politique(politique: Any) -> dict[str, str]:
    """La décision du client pour CHAQUE catégorie ; aucune valeur par défaut."""
    if not isinstance(politique, Mapping):
        raise ErreurGeo("REJ-GEO-POLITIQUE-ABSENTE", "politique du client attendue : une décision par catégorie")
    manquantes = [c for c in CATEGORIES if c not in politique]
    inconnues = sorted(str(c) for c in set(politique) - set(CATEGORIES))
    if manquantes or inconnues:
        raise ErreurGeo("REJ-GEO-POLITIQUE-ABSENTE",
                        f"catégories manquantes {manquantes}, inconnues {inconnues} : le client décide pour chacune "
                        f"des "
                        f"trois {list(CATEGORIES)}, aucune valeur par défaut")
    if any(politique[c] not in DECISIONS for c in CATEGORIES):
        raise ErreurGeo("REJ-GEO-POLITIQUE-INVALIDE", f"chaque décision est l'une de {list(DECISIONS)}")
    return {c: politique[c] for c in CATEGORIES}


def _ligne_recommandee(robot: RobotIA, voulu_autorise: bool) -> str:
    return f"User-agent: {robot.nom}\n{'Allow' if voulu_autorise else 'Disallow'}: /"


def analyser_robots_ia(texte_robots: str | None, statut_http: int, politique: Any) -> dict[str, Any]:
    """Pour chaque robot de la liste : autorisé sur `/` par le fichier ? voulu par la politique ? conforme ? Rend
    aussi les
    constats et les lignes RECOMMANDÉES (jamais appliquées)."""
    decisions = valider_politique(politique)
    regle = robots.analyser(texte_robots, statut_http)
    lignes: list[dict[str, Any]] = []
    constats: list[dict[str, Any]] = []
    recommandations: list[str] = []
    for robot in ROBOTS_IA:
        autorise = robots.autorise(regle, robot.nom, "/")
        voulu = decisions[robot.categorie] == "autoriser"
        conforme = autorise == voulu
        constat = None
        if not conforme:
            if voulu:
                constat = "GEO-ROBOT-BLOQUE-CONTRE-POLITIQUE"
                detail = (f"{robot.nom} ({robot.categorie}) est bloqué alors que la politique dit autoriser cette "
                          "catégorie")
            else:
                constat = "GEO-ROBOT-AUTORISE-CONTRE-POLITIQUE"
                detail = (f"{robot.nom} ({robot.categorie}) est autorisé alors que la politique dit bloquer cette "
                          "catégorie")
            constats.append({"code": constat, "robot": robot.nom, "categorie": robot.categorie, "detail": detail})
            if regle.etat == "lu":
                recommandations.append(_ligne_recommandee(robot, voulu))
        lignes.append({"robot": robot.nom, "categorie": robot.categorie, "editeur": robot.editeur,
                       "niveau_preuve": robot.niveau_preuve, "a_verifier": robot.a_verifier, "autorise": autorise,
                       "voulu": voulu, "conforme": conforme, "constat": constat})
    if regle.etat == "inaccessible":
        constats.insert(0, {"code": "GEO-ROBOTS-INACCESSIBLE", "robot": None, "categorie": None,
                            "detail": "robots.txt est inaccessible (5xx, délai ou réponse illisible) : un robot doit "
                                      "alors supposer une interdiction complète (RFC 9309) ; corriger la "
                                      "disponibilité du fichier avant toute autre chose"})
    if regle.etat == "absent":
        constats.insert(0, {"code": "GEO-ROBOTS-ABSENT", "robot": None, "categorie": None,
                            "detail": "robots.txt est absent (4xx) : tout est permis à tous les robots"})
    return {
        "type": "ROBOTS_IA", "etat_robots": regle.etat, "tronque": regle.tronque, "politique": decisions,
        "robots": lignes, "constats": constats, "lignes_recommandees": recommandations,
        "conformes": sum(1 for ligne in lignes if ligne["conforme"]), "total": len(lignes),
        "source_liste": SOURCE_LISTE, "avertissements": list(AVERTISSEMENTS),
        "application": "RECOMMANDATION seulement : rien n'est modifié sur le site",
    }


__all__ = ["AVERTISSEMENTS", "CATEGORIES", "DECISIONS", "ErreurGeo", "PAR_NOM", "ROBOTS_IA", "RobotIA",
           "analyser_robots_ia", "valider_politique"]
