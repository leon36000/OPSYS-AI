import re
import hashlib
from pathlib import Path

# Enums fermés issus des contrats
_TYPES_TRAVAUX = {
    "renovation_totale",
    "extension",
    "ravalement",
    "isolation_thermique",
    "autre",
}
_CANAUX = {"telephone", "courriel", "formulaire", "texte"}

# Patterns de détection pour les interdits de la description
_PRIX_REGEX = re.compile(
    r"(\$|€|CAD|dollars|euros|à\s+partir\s+de|fourchette|/m²|/h|\d+\s*(dollars|euros|CAD|\$|€))",
    re.IGNORECASE,
)

_MOIS = "janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre"
_DATE_REGEX = re.compile(
    r"\d{1,2}\s+(?:" + _MOIS + r")|" + r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
    re.IGNORECASE,
)


def valider_lead(lead: dict) -> str:
    """Valide un lead conforme au contrat M1-M2. Retourne 'OK' ou lève ValueError."""
    champs_oblig = [
        "lead_id",
        "conversation_id",
        "contact",
        "type_travaux",
        "ville",
        "urgence_declaree",
        "canal",
    ]
    for champ in champs_oblig:
        if champ not in lead:
            raise ValueError(f"{champ} obligatoire")

    # Type travaux
    if lead["type_travaux"] not in _TYPES_TRAVAUX:
        raise ValueError(
            f"REJ-ENUM-INVALIDE: type_travaux invalide ('{lead['type_travaux']}')"
        )

    # Canal
    if lead["canal"] not in _CANAUX:
        raise ValueError(
            f"REJ-ENUM-INVALIDE: canal invalide ('{lead['canal']}')"
        )

    # Ville
    ville = lead["ville"]
    if not isinstance(ville, str) or not ville.strip():
        raise ValueError("ville doit être non vide")

    # Contact
    contact = lead.get("contact", {})
    if not isinstance(contact, dict):
        raise ValueError("contact doit être un dictionnaire")
    # Au moins un champ non vide parmi nom, telephone, courriel
    if not (
        (isinstance(contact.get("nom"), str) and contact["nom"].strip())
        or (isinstance(contact.get("telephone"), str) and contact["telephone"].strip())
        or (isinstance(contact.get("courriel"), str) and contact["courriel"].strip())
    ):
        raise ValueError("contact doit avoir au moins un champ non vide")

    # Urgence déclarée
    if not isinstance(lead["urgence_declaree"], bool):
        raise ValueError("urgence_declaree doit être un booléen")

    return "OK"


def valider_chiffrage(demande: dict) -> str:
    """Valide une demande de chiffrage conforme au contrat M1-M3. Retourne 'OK' ou lève ValueError."""
    # Valide d'abord la partie lead commune
    valider_lead(demande)

    if "description_factuelle" not in demande:
        raise ValueError("description_factuelle requise")
    desc = demande["description_factuelle"]
    if not isinstance(desc, str):
        raise ValueError("description_factuelle doit être une chaîne")

    if len(desc) < 50:
        raise ValueError("description_factuelle trop courte (min 50 caractères)")

    if len(desc) > 500:
        raise ValueError("description_factuelle trop longue (max 500 caractères)")

    if _PRIX_REGEX.search(desc):
        raise ValueError("description_factuelle contient un prix")

    if _DATE_REGEX.search(desc):
        raise ValueError("description_factuelle contient une date")

    return "OK"


# Hash des contrats
_ICI = Path(__file__).resolve().parent  # répertoire de contrats.py
_CONTRACTS_DIR = _ICI / "contracts"


def hash_contrat(nom: str) -> str:
    """Retourne le sha256 du fichier de contrat situé dans contracts/."""
    chemin = _CONTRACTS_DIR / nom
    data = chemin.read_bytes()
    return hashlib.sha256(data).hexdigest()
