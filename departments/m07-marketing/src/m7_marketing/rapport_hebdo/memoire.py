"""Observations d'apprentissage marketing (M7-MEMOIRE) : ce que M7 annonce à la mémoire de M10 après chaque rapport.

Pur : transforme un rapport hebdomadaire en charges `m7.apprentissage_marketing_constate` MINIMALES (catalogue
`src/opsys/evenements/catalogue/m7.apprentissage_marketing_constate.json`) : le genre, le canal, la clé de mesure d'un
contenu
(`utm_content`, empreinte non réversible déjà publique dans les liens de suivi) ou la catégorie d'avis, des comptes
entiers et
l'empreinte du rapport. AUCUN texte de contenu, d'avis ou de client, aucune coordonnée, aucun identifiant de lead ni de
chantier. L'identifiant est déterministe : la même observation d'une même semaine ne s'annonce jamais deux fois.

Une observation n'est PAS une leçon : M10 en tire des leçons gouvernées (proposition, évaluation, décision d'une
personne).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

TYPE_EVENEMENT = "m7.apprentissage_marketing_constate"
GENRES = ("contenu_gagnant", "contenu_faible", "objection_frequente", "avis_constate")
CANAL_AVIS = "avis_clients"
OBJECTIONS_MIN = 2  # une catégorie d'avis n'est un signal d'objection qu'à partir de ce nombre d'avis dans la semaine
_CLE = re.compile(r"^[a-z0-9_-]{1,80}$")
_CATEGORIES_OBJECTION = ("litige", "urgence")


def identifiant(semaine: str, genre: str, canal: str, cle: str | None) -> str:
    corps = "|".join((semaine, genre, canal, cle or ""))
    return "m7-appr-" + hashlib.sha256(corps.encode("utf-8")).hexdigest()[:40]


def _resultat(**comptes: int | None) -> dict[str, int | None]:
    base = {
        "leads": None,
        "devis_envoyes": None,
        "devis_acceptes": None,
        "occurrences": None,
        "avis_positifs": None,
        "avis_negatifs": None,
    }
    base.update(comptes)
    return base


def _contenu(rapport: dict[str, Any], genre: str, c: dict[str, Any]) -> dict[str, Any] | None:
    cle = c.get("utm_content")
    if (
        not isinstance(cle, str)
        or not _CLE.fullmatch(cle)
        or c.get("canal") not in ("facebook", "instagram", "fiche_google", "video_courte", "demande_temoignage")
    ):
        return None
    comptes = {
        k: c.get(k) if type(c.get(k)) is int and c.get(k) >= 0 else None
        for k in ("leads", "devis_envoyes", "devis_acceptes")
    }
    semaine = rapport["semaine"]["debut"]
    return {
        "observation_id": identifiant(semaine, genre, c["canal"], cle),
        "semaine": semaine,
        "genre_observation": genre,
        "canal": c["canal"],
        "cle_mesure": cle,
        "resultat": _resultat(**comptes),
        "rapport_empreinte": rapport["empreinte"],
    }


def observations(rapport: dict[str, Any]) -> list[dict[str, Any]]:
    """Les observations minimales d'un rapport, dans un ordre stable. Une section sans donnée n'en produit aucune."""
    sortie: list[dict[str, Any]] = []
    contenus = rapport["contenus"]
    if contenus.get("statut") == "calcule":
        for genre, cle in (("contenu_gagnant", "meilleurs"), ("contenu_faible", "faibles")):
            for c in contenus.get(cle, []):
                o = _contenu(rapport, genre, c)
                if o is not None:
                    sortie.append(o)
    reputation = rapport["reputation"]
    if reputation.get("statut") == "calcule" and reputation["avis_semaine"] >= 1:
        semaine = rapport["semaine"]["debut"]
        categories = reputation["categories"]
        for categorie in _CATEGORIES_OBJECTION:
            n = categories.get(categorie, 0)
            if n >= OBJECTIONS_MIN:
                sortie.append(
                    {
                        "observation_id": identifiant(semaine, "objection_frequente", CANAL_AVIS, categorie),
                        "semaine": semaine,
                        "genre_observation": "objection_frequente",
                        "canal": CANAL_AVIS,
                        "cle_mesure": categorie,
                        "resultat": _resultat(occurrences=n),
                        "rapport_empreinte": rapport["empreinte"],
                    }
                )
        sortie.append(
            {
                "observation_id": identifiant(semaine, "avis_constate", CANAL_AVIS, "semaine"),
                "semaine": semaine,
                "genre_observation": "avis_constate",
                "canal": CANAL_AVIS,
                "cle_mesure": "semaine",
                "resultat": _resultat(
                    occurrences=reputation["avis_semaine"],
                    avis_positifs=categories.get("eloge", 0),
                    avis_negatifs=categories.get("litige", 0) + categories.get("urgence", 0),
                ),
                "rapport_empreinte": rapport["empreinte"],
            }
        )
    return sortie
