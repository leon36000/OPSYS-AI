import re
import hashlib
from pathlib import Path

from opsys import taxonomie

from .verdicts import construire_verdict

# Enums fermés issus des contrats
# Énuméré du contrat GELÉ v1 (`m1-lead-qualifie.v1.yaml`, épinglé par SHA-256) : conservé pour
# valider les leads v1 déjà écrits. Le contrat v2 n'a plus cet énuméré : son `service` est un code
# de la taxonomie du socle (`opsys.taxonomie`), déclaré par le profil d'entreprise de l'instance.
_TYPES_TRAVAUX = {
    "renovation_totale",
    "extension",
    "ravalement",
    "isolation_thermique",
    "autre",
}
_CANAUX = {"telephone", "courriel", "formulaire", "texte"}

# Contrat v2 (`m1-lead-qualifie.v2.yaml`) : la version est portée par le lead, jamais devinée.
# Un lead sans `schema_version` est un lead v1 (le contrat gelé v1 n'a pas ce champ).
VERSION_LEAD_V2 = 2
_CHAMPS_LEAD_V2 = (
    "schema_version", "lead_id", "conversation_id", "contact", "service", "ville",
    "urgence_declaree", "canal",
)
_CHAMPS_LEAD_V2_OPTIONNELS = ("source", "utm", "campagne")
_CLES_UTM = ("utm_source", "utm_medium", "utm_campaign", "utm_content")

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


def valider_lead(lead: dict, services=None) -> dict:
    """Valide un lead conforme au contrat M1-M2, dans la version qu'il DÉCLARE.

    Un lead qui porte `schema_version` est validé en v2 ; sans ce champ, c'est un lead v1 (contrat
    gelé, sans champ de version). Aucune version n'est devinée à partir des autres champs : un lead
    v1 qui porte `service`, ou un lead v2 qui porte `type_travaux`, est refusé.

    `services` : déclaration de services à confronter en v2 (tests) ; absente, le profil d'entreprise
    de l'instance est lu (`opsys.taxonomie`). Retourne un verdict structuré avec code
    'EVT-CONTRAT-VALIDE' ou lève ValueError.
    """
    if isinstance(lead, dict) and "schema_version" in lead:
        return _valider_lead_v2(lead, services)
    return _valider_lead_v1(lead)


def _valider_communs(lead: dict) -> None:
    """Contrôles identiques en v1 et en v2 : canal, ville, contact, urgence déclarée."""
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


def _valider_lead_v1(lead: dict) -> dict:
    """Contrat gelé v1 (`type_travaux`, énuméré fermé). Comportement inchangé."""
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

    _valider_communs(lead)
    return construire_verdict("EVT-CONTRAT-VALIDE", statut="", detail="Lead valide")


def _champ_optionnel_v2_invalide(lead: dict) -> str | None:
    """`source`, `campagne`, `utm` SI PRÉSENTS (mêmes règles que M2 et M3) ; None si conforme."""
    for champ in ("source", "campagne"):
        if champ in lead and (not isinstance(lead[champ], str) or lead[champ] == ""):
            return f"champ optionnel {champ!r} : chaîne non vide exigée s'il est fourni"
    if "utm" in lead:
        utm = lead["utm"]
        if not isinstance(utm, dict) or not utm:
            return "champ optionnel 'utm' : dictionnaire non vide exigé s'il est fourni"
        for cle, valeur in utm.items():
            if cle not in _CLES_UTM or not isinstance(valeur, str) or valeur == "":
                return f"champ optionnel 'utm' : sous-clé {cle!r} hors de {list(_CLES_UTM)} ou valeur vide"
    return None


def _valider_lead_v2(lead: dict, services) -> dict:
    """Contrat v2 (`service` de la taxonomie du socle ; `source`/`utm`/`campagne` optionnels)."""
    version = lead["schema_version"]
    if type(version) is not int or version != VERSION_LEAD_V2:
        raise ValueError(
            f"REJ-CONTRAT-INVALIDE: schema_version doit valoir {VERSION_LEAD_V2} (reçu {version!r})"
        )
    for champ in _CHAMPS_LEAD_V2:
        if champ not in lead:
            raise ValueError(f"{champ} obligatoire")
    for champ in lead:
        if champ not in _CHAMPS_LEAD_V2 and champ not in _CHAMPS_LEAD_V2_OPTIONNELS:
            raise ValueError(f"REJ-CONTRAT-INVALIDE: champ inconnu en v2 ('{champ}')")

    _, verdict = taxonomie.valider_service(lead["service"], services)
    if verdict is not None:
        raise ValueError(
            f"REJ-ENUM-INVALIDE: service invalide ({verdict['code']}) : {verdict['detail']}"
        )

    _valider_communs(lead)

    probleme = _champ_optionnel_v2_invalide(lead)
    if probleme is not None:
        raise ValueError(f"REJ-CONTRAT-INVALIDE: {probleme}")

    return construire_verdict("EVT-CONTRAT-VALIDE", statut="", detail="Lead valide (v2)")


def valider_chiffrage(demande: dict) -> dict:
    """Valide une demande de chiffrage conforme au contrat M1-M3. Retourne un verdict structuré avec code 'EVT-CONTRAT-VALIDE' ou lève ValueError."""
    # Valide d'abord la partie lead commune. La demande de chiffrage v1 (M1→M3, gelée) porte
    # `type_travaux` : elle se valide TOUJOURS contre le lead v1, quelle que soit la version du
    # lead émis à M2 (la demande de chiffrage v2 reste à faire, hors périmètre de T0.13).
    _valider_lead_v1(demande)

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
