"""Vocabulaire fermé des bases de connaissances : états, domaines, licences, autorités et transitions permises.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping

from .codes import ENTREE_INVALIDE, ErreurConnaissances

ETAT_BROUILLON = "brouillon"
ETAT_REVU = "revu"
ETAT_PUBLIE = "publie"
ETAT_RETIRE = "retire"
ETATS: tuple[str, ...] = (ETAT_BROUILLON, ETAT_REVU, ETAT_PUBLIE, ETAT_RETIRE)

# Le premier événement d'une version est toujours « brouillon » (clé None). Rien ne sort de « retire » : le retrait est
# définitif pour cette version (une correction est une NOUVELLE version, jamais une résurrection).
TRANSITIONS: Mapping[str | None, frozenset[str]] = {
    None: frozenset({ETAT_BROUILLON}),
    ETAT_BROUILLON: frozenset({ETAT_REVU, ETAT_RETIRE}),
    ETAT_REVU: frozenset({ETAT_PUBLIE, ETAT_RETIRE}),
    ETAT_PUBLIE: frozenset({ETAT_RETIRE}),
    ETAT_RETIRE: frozenset(),
}

TYPES_SOURCE: tuple[str, ...] = ("texte", "markdown", "html", "pdf")
LICENCES: tuple[str, ...] = (
    "domaine_public", "licence_ouverte", "permission_ecrite", "interne", "droit_auteur_reserve", "inconnue",
)
AUTORITES: tuple[str, ...] = ("officielle", "reconnue", "interne", "tierce", "fictive")
DOMAINES: tuple[str, ...] = ("comptabilite", "fiscalite", "juridique", "investissement", "technique", "general")
# Domaines où une erreur coûte cher et où un professionnel doit valider : revue humaine, source officielle identifiée,
# date de publication et échéance de révision connues, mention obligatoire (DÉCISIONS ARCHITECTE r1 §1).
DOMAINES_REGLEMENTES: frozenset[str] = frozenset({"comptabilite", "fiscalite", "juridique", "investissement"})
MENTION_PROFESSIONNELLE = "À valider auprès d'un comptable (CPA) / professionnel qualifié"
MENTION_DEMONSTRATION = (
    "Contenu de démonstration FICTIF : ne jamais le citer comme une source réelle (aucune valeur n'est exacte)."
)

MODES_ACTEUR = ("humain", "agent", "systeme")

CLE_SOURCE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}$")
DEPARTEMENT = re.compile(r"^m(0[1-9]|10)-[a-z][a-z0-9-]{1,40}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TEXTE_MAX = 400_000
FRAGMENTS_MAX = 2_000
PDF_MAX_OCTETS = 8 * 1024 * 1024
RAISON_MIN = 10
RAISON_MAX = 500
# Plafond de la similarité exacte en Python (phase 1, sans sqlite-vec) : au-delà, la recherche vectorielle refuse plutôt
# que de devenir lente sans le dire. La cible de production (pgvector, HNSW) n'a pas ce plafond.
VECTEURS_PLAFOND = 20_000
FRAGMENTS_PLAFOND_PAR_BASE = 60_000


def date_iso(valeur: object, champ: str, *, requise: bool) -> str | None:
    """`AAAA-MM-JJ` réelle (le 30 février est refusé) ; `None` si absente et facultative."""
    if valeur is None or valeur == "":
        if requise:
            raise ErreurConnaissances(ENTREE_INVALIDE, f"{champ} requise (AAAA-MM-JJ)")
        return None
    if not isinstance(valeur, str) or not _DATE.fullmatch(valeur):
        raise ErreurConnaissances(ENTREE_INVALIDE, f"{champ} invalide : AAAA-MM-JJ attendu")
    try:
        dt.date.fromisoformat(valeur)
    except ValueError:
        raise ErreurConnaissances(ENTREE_INVALIDE, f"{champ} n'est pas une date réelle") from None
    return valeur


def instant_iso(instant: dt.datetime) -> str:
    """Instant canonique UTC à la seconde, comparable comme du texte (`2026-11-01T12:00:00+00:00`)."""
    if not isinstance(instant, dt.datetime) or instant.tzinfo is None:
        raise ErreurConnaissances(ENTREE_INVALIDE, "instant avec fuseau horaire requis")
    return instant.astimezone(dt.UTC).replace(microsecond=0).isoformat()


def fin_de_journee(date_texte: str) -> str:
    """Borne haute inclusive d'un jour, dans le même format que `instant_iso`."""
    return f"{date_texte}T23:59:59+00:00"
