"""Classificateur déterministe d'avis clients (REJ-0040 : aucun score LLM).

Règles appliquées dans cet ordre de priorité :
  1. litige  — mots-clés litige détectés dans le texte (quelle que soit la note)
  2. urgence — note ≤ 2  OU  mots-clés urgence dans le texte
  3. eloge   — note = 5  OU  mots-clés éloge dans le texte
  4. neutre  — cas résiduel

Toutes les règles sont purement déterministes (chaîne → ensemble de tokens).
Aucune pondération probabiliste, aucun appel extérieur.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Listes de mots-clés canoniques (FR, minuscules, sans accents homogénéisés
# via .lower() à l'exécution).
# ---------------------------------------------------------------------------

_MOTS_LITIGE: frozenset[str] = frozenset(
    {
        "réclamation",
        "reclamation",
        "litige",
        "remboursement",
        "avocat",
        "plainte",
        "procédure",
        "procedure",
        "tribunal",
        "juridique",
        "poursuite",
        "contestation",
        "mise en demeure",
        "indemnisation",
        "préjudice",
        "prejudice",
    }
)

_MOTS_URGENCE: frozenset[str] = frozenset(
    {
        "urgence",
        "urgent",
        "urgente",
        "urgents",
        "urgentes",
        "immédiat",
        "immediat",
        "immédiatement",
        "immediatement",
        "rapidement",
        "vite",
        "critique",
        "dès que possible",
        "des que possible",
        "au plus tôt",
        "au plus tot",
    }
)

_MOTS_ELOGE: frozenset[str] = frozenset(
    {
        "excellent",
        "excellente",
        "parfait",
        "parfaite",
        "recommande",
        "recommandons",
        "recommandez",
        "bravo",
        "super",
        "magnifique",
        "exceptionnel",
        "exceptionnelle",
        "fantastique",
        "merveilleux",
        "merveilleuse",
        "formidable",
        "incroyable",
        "remarquable",
        "félicitations",
        "felicitations",
        "impeccable",
        "irréprochable",
        "irreprochable",
        "top",
    }
)

# Catégories valides exposées publiquement
CATEGORIES = frozenset({"litige", "urgence", "eloge", "neutre"})

# Plage valide des notes (contrat des fixtures S008a)
NOTE_MIN: int = 1
NOTE_MAX: int = 5


def _contient_mot(texte_lower: str, mots: frozenset[str]) -> bool:
    """Retourne True si au moins un mot (ou expression) figure dans le texte."""
    for mot in mots:
        if mot in texte_lower:
            return True
    return False


def classifier_avis(avis: dict) -> str:
    """Classifie un avis par règles déterministes.

    Paramètres
    ----------
    avis : dict portant au minimum ``note`` (int 1-5) et ``texte`` (str).

    Retourne
    --------
    str : 'litige' | 'urgence' | 'eloge' | 'neutre'

    Lève
    ----
    ValueError : si ``note`` est absente ou hors de [1, 5].
    """
    note = avis.get("note")
    if note is None or not isinstance(note, int) or not (NOTE_MIN <= note <= NOTE_MAX):
        raise ValueError(
            f"note invalide (attendu int {NOTE_MIN}-{NOTE_MAX}, reçu {note!r}) pour l'avis {avis.get('id')!r}"
        )

    texte = (avis.get("texte") or "").lower()

    # Priorité 1 — litige (indépendant de la note)
    if _contient_mot(texte, _MOTS_LITIGE):
        return "litige"

    # Priorité 2 — urgence (note ≤ 2 OU mot-clé)
    if note <= 2 or _contient_mot(texte, _MOTS_URGENCE):
        return "urgence"

    # Priorité 3 — éloge (note = 5 OU mot-clé)
    if note == 5 or _contient_mot(texte, _MOTS_ELOGE):
        return "eloge"

    # Priorité 4 — neutre (cas résiduel)
    return "neutre"
