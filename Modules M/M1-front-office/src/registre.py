import json
import hashlib
from pathlib import Path
import yaml
import horodatage

_registre = []

_TYPES_ENTREE_VALIDES = {
    "signal",
    "transition_phase",
    "lead_emis",
    "chiffrage_emis",
    "alerte",
}


def reset():
    """Vide le registre. Utile pour l'isolation des tests."""
    global _registre
    _registre = []


def ajouter_entree(entree: dict) -> str:
    """Ajoute une entrée immuable au registre. Retourne le ligne_id (sha256)."""
    # Validation type_entree
    type_entree = entree.get("type_entree")
    if type_entree not in _TYPES_ENTREE_VALIDES:
        raise ValueError(f"REJ-ENUM-INVALIDE: type_entree '{type_entree}' invalide")

    # Validation horodatage
    horodatage_str = entree.get("horodatage")
    if horodatage_str is None:
        raise ValueError("horodatage manquant")
    horodatage.valider_horodatage(horodatage_str)

    # Contenu canonique sans les ids de chaînage
    contenu = {}
    for k, v in entree.items():
        if k not in ("ligne_id", "precedent_ligne_id"):
            contenu[k] = v

    # Sérialisation canonique déterministe
    canonique = json.dumps(contenu, sort_keys=True, ensure_ascii=False, default=str)
    ligne_id = hashlib.sha256(canonique.encode("utf-8")).hexdigest()

    # Chaînage avec la dernière entrée
    if _registre:
        precedent = _registre[-1]["ligne_id"]
    else:
        precedent = None

    entree_stockee = dict(entree)
    entree_stockee["ligne_id"] = ligne_id
    entree_stockee["precedent_ligne_id"] = precedent
    _registre.append(entree_stockee)
    return ligne_id


def lire_registre(depuis: str | None = None) -> list:
    """Retourne la portion du registre à partir de l'entrée dont le ligne_id
    correspond à `depuis` (incluse). Si `depuis` est None, retourne tout le registre.
    """
    if depuis is None:
        return list(_registre)  # copie superficielle

    for i, entree in enumerate(_registre):
        if entree.get("ligne_id") == depuis:
            return _registre[i:]
    return []


def valider_chaine() -> bool:
    """Vérifie l'intégrité de toute la chaîne (hash et liens). Retourne False si
    une altération est détectée.
    """
    if not _registre:
        return True

    prev_id = None
    for entree in _registre:
        # Recalcul du hash
        contenu = {}
        for k, v in entree.items():
            if k not in ("ligne_id", "precedent_ligne_id"):
                contenu[k] = v
        canonique = json.dumps(contenu, sort_keys=True, ensure_ascii=False, default=str)
        expected_id = hashlib.sha256(canonique.encode("utf-8")).hexdigest()

        if expected_id != entree.get("ligne_id"):
            return False
        if entree.get("precedent_ligne_id") != prev_id:
            return False
        prev_id = entree.get("ligne_id")

    return True


def charger_signaux(chemin: str) -> list:
    """Charge les signaux depuis un fichier YAML. Exige la clé `fictif: true`.
    Retourne la liste de signaux.
    """
    with open(chemin, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data.get("fictif") is True:
        raise ValueError("fictif manquant ou faux")
    return data.get("signaux", [])
