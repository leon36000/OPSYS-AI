import re
import hashlib
from pathlib import Path
from .verdicts import construire_verdict

# Enums fermés issus des contrats
_TYPES_TRAVAUX = {
    "renovation_totale",
    "extension",
    "ravalement",
    "isolation_thermique",
    "autre",
}
_CANAUX = {"telephone", "courriel", "formulaire", "texte"}

# Détection de prix affinée
_PRIX_REGEX = re.compile(
    r"""(
        \$\s*\d+(?:[\s,.]\d+)* |                      # $ 5 000 ou 5,000
        \d+(?:[\s,.]\d+)*\s*\$ |                      # 5 000 $ ou 5,000$
        €\s*\d+(?:[\s,.]\d+)* |                        # € 5 000
        \d+(?:[\s,.]\d+)*\s*€ |                        # 5 000 €
        \d+(?:[\s,.]\d+)*\s*(?:dollars|euros|CAD) |    # 500 dollars
        (?:dollars|euros|CAD)\s*\d+(?:[\s,.]\d+)* |    # dollars 500
        à\s+partir\s+de\s+\d+(?:[\s,.]\d+)* |          # à partir de 500
        fourchette\s+\d+(?:[\s,.]\d+)*\s*-\s*\d+(?:[\s,.]\d+)* | # fourchette 100-200
        \d+(?:[\s,.]\d+)*\s*/\s*m[²2] |                # 50/m²
        \d+(?:[\s,.]\d+)*\s*/\s*h |                    # 50/h
        \d+(?:[\s,.]\d+)*\s*/\s*pi[²2]                 # 50/pi²
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# Détection de dates élargie
_MOIS_NOMS = (
    "janvier|février|mars|avril|mai|juin|"
    "juillet|août|septembre|octobre|novembre|décembre"
)
_JOURS_SEMAINE = "lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche"
_RELATIF = "demain|hier|aujourd'hui"

_DATE_REGEX = re.compile(
    r"""(
        \d{4}-\d{2}-\d{2} |                             # ISO complet AAAA-MM-JJ
        \d{2}/\d{2} |                                   # JJ/MM
        \d{1,2}-\d{1,2}-\d{2,4} |                       # JJ-MM-AAAA
        \d{1,2}\s+(?:""" + _MOIS_NOMS + r""") |          # 15 janvier
        (?:début|courant|fin)\s+(?:""" + _MOIS_NOMS + r""") |  # début mars
        (?:en|dès|avant|après)\s+\d{4} |                 # en 2027
        (?:""" + _JOURS_SEMAINE + r""") |                # lundi
        (?:la\s+semaine\s+prochaine) |                   # la semaine prochaine
        (?:dans\s+\d+\s+(?:jours|semaines|mois)) |       # dans 5 jours
        (?:""" + _RELATIF + r""")                         # demain
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def valider_lead(lead: dict) -> dict:
    """Valide un lead conforme au contrat M1-M2. Retourne un verdict structuré avec code 'EVT-CONTRAT-VALIDE' ou lève ValueError."""
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

    return construire_verdict("EVT-CONTRAT-VALIDE", statut="", detail="Lead valide")


def valider_chiffrage(demande: dict) -> dict:
    """Valide une demande de chiffrage conforme au contrat M1-M3. Retourne un verdict structuré avec code 'EVT-CONTRAT-VALIDE' ou lève ValueError."""
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

    return construire_verdict("EVT-CONTRAT-VALIDE", statut="", detail="Chiffrage valide")


# Hash des contrats
_ICI = Path(__file__).resolve().parent  # .../m01-front-office/src/m1_front_office/
# Les contrats vivent à la racine du département (departments/m01-front-office/contracts/),
# pas sous src/ : il faut donc remonter DEUX niveaux (src/m1_front_office -> src -> racine
# du département), pas un seul (bug d'audit : un seul niveau pointait vers src/contracts,
# inexistant, et levait FileNotFoundError).
_CONTRACTS_DIR = _ICI.parent.parent / "contracts"


def hash_contrat(nom: str) -> str:
    """Retourne le sha256 du fichier de contrat situé dans contracts/."""
    chemin = _CONTRACTS_DIR / nom
    data = chemin.read_bytes()
    return hashlib.sha256(data).hexdigest()
