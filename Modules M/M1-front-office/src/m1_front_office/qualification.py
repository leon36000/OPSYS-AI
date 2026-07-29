import re
import hashlib
from . import verdicts

# Motifs d'extraction déterministes
_RENOVATION_TOTALE = re.compile(
    r"rénovation\s+(?:totale|complète|intégrale|majeure)|rénover\s+au\s+complet",
    re.IGNORECASE
)
_EXTENSION = re.compile(r"\bextension\b", re.IGNORECASE)
_RAVALEMENT = re.compile(r"\bravalement\b", re.IGNORECASE)
_ISOLATION_THERMIQUE = re.compile(r"isolation\s+thermique", re.IGNORECASE)

# Ensemble fermé de villes québécoises reconnues par le contrat
_VILLES_VALIDES = {
    "Montréal",
    "Québec",
    "Laval",
    "Gatineau",
    "Sherbrooke",
    "Trois-Rivières",
    "Longueuil",
    "Lévis",
    "Saguenay",
    "Terrebonne",
    "Granby",
    "Saint-Jérôme",
    "Shawinigan",
}

# Marqueurs d'urgence explicites (jamais inférés)
_URGENCE_PATTERNS = [
    re.compile(r"urgent", re.IGNORECASE),
    re.compile(r"urgence", re.IGNORECASE),
    re.compile(r"au\s+plus\s+vite", re.IGNORECASE),
    re.compile(r"d[ée]g[âa]t\s+d['’]?eau", re.IGNORECASE),
    re.compile(r"\bfuite\b", re.IGNORECASE),
]

# Marqueur de neutralisation posé par S005, à ignorer
_MARQUEUR = re.compile(r"\[CONTENU_NON_FIABLE\]", re.IGNORECASE)

# Mot-clé autorisé pour le type "autre" (après échec des quatre types concrets)
_AUTRE = re.compile(r"\bautre\b", re.IGNORECASE)

# Expression régulière pour détecter une ville (utilisée avec \b et escape)
_VILLE_REGEX_CACHE = {}

# --------------------------------------------------
# Motifs de contact
# --------------------------------------------------
_PHONE_REGEX = re.compile(
    r'''
    (?:\(\d{3}\)\s?\d{3}[-.\s]?\d{4}  # (514) 555-0142
    |\d{3}[-.\s]?\d{3}[-.\s]?\d{4}   # 514-555-0142, 514 555 0142, 5145550142
    )\b
    ''',
    re.VERBOSE
)

_EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')


def _rejet():
    """Verdict de rejet normalisé."""
    return {"verdict": verdicts.construire_verdict("REJ-QUALIF-INSUFFISANTE")}


def _clean(contenu_filtre: str) -> str:
    """Supprime le marqueur de contenu non fiable et nettoie les blancs."""
    return _MARQUEUR.sub("", contenu_filtre).strip()


def _extraire_type(contenu: str):
    """Retourne le type de travaux ou None."""
    if _RENOVATION_TOTALE.search(contenu):
        return "renovation_totale"
    if _EXTENSION.search(contenu):
        return "extension"
    if _RAVALEMENT.search(contenu):
        return "ravalement"
    if _ISOLATION_THERMIQUE.search(contenu):
        return "isolation_thermique"
    if _AUTRE.search(contenu):
        return "autre"
    return None


def _extraire_ville(contenu: str):
    """Retourne la première ville québécoise reconnue ou None."""
    for ville in sorted(_VILLES_VALIDES, key=lambda v: -len(v)):
        if ville not in _VILLE_REGEX_CACHE:
            _VILLE_REGEX_CACHE[ville] = re.compile(
                r"\b" + re.escape(ville) + r"\b", re.IGNORECASE
            )
        if _VILLE_REGEX_CACHE[ville].search(contenu):
            return ville
    return None


def _extraire_urgence(contenu: str) -> bool:
    """Détecte la présence d'un marqueur d'urgence explicite."""
    return any(p.search(contenu) for p in _URGENCE_PATTERNS)


def _extraire_contact(contenu: str) -> dict | None:
    """Extrait un contact (téléphone et/ou courriel) du contenu.
    Retourne None si aucun contact trouvé.
    """
    contact = {}
    phone_match = _PHONE_REGEX.search(contenu)
    if phone_match:
        contact["telephone"] = phone_match.group().strip()
    email_match = _EMAIL_REGEX.search(contenu)
    if email_match:
        contact["courriel"] = email_match.group().strip()
    return contact if contact else None


def _materiau_lead_id(conversation_id: str, contenu: str) -> str:
    """Encodage canonique INJECTIF (préfixage par longueur) : deux couples différents
    ne peuvent pas produire le même matériau, contrairement à une concaténation directe."""
    return f"{len(conversation_id)}:{conversation_id}|{len(contenu)}:{contenu}"


def qualifier(contenu_filtre: str, canal: str, conversation_id: str) -> dict:
    """
    Extrait les informations obligatoires d'un message filtré.
    Retourne un LeadQualifie selon le contrat M1-M2,
    ou un verdict de rejet REJ-QUALIF-INSUFFISANTE.
    """
    contenu = _clean(contenu_filtre)
    if not contenu:
        return _rejet()

    type_travaux = _extraire_type(contenu)
    if type_travaux is None:
        return _rejet()

    ville = _extraire_ville(contenu)
    if ville is None:
        return _rejet()

    urgence = _extraire_urgence(contenu)

    contact = _extraire_contact(contenu)
    if contact is None:
        return _rejet()

    materiau = _materiau_lead_id(conversation_id, contenu)
    lead_id = hashlib.sha256(materiau.encode("utf-8")).hexdigest()

    lead = {
        "lead_id": lead_id,
        "type_travaux": type_travaux,
        "ville": ville,
        "urgence_declaree": urgence,
        "canal": canal,
        "conversation_id": conversation_id,
        "contact": contact,
    }
    return lead
