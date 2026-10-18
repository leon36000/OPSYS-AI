"""Âge des observations d'un dossier figé, sans qualification d'actualité métier.

Interne au serveur : l'appelant fournit le dossier issu de sa capture validée et
de confiance. Les empreintes vérifient la cohérence du contenu, pas son origine
ni une autorisation. Ce module n'accepte pas un dossier client comme preuve de
confiance et ne relit aucun registre. Aucune politique de péremption n'est inférée.
"""
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime


def _empreinte(objet):
    return hashlib.sha256(json.dumps(
        objet, sort_keys=True, ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _instant(valeur, code):
    if not isinstance(valeur, str) or not valeur or valeur.strip() != valeur or len(valeur) > 128:
        raise ValueError(code + " : horodatage avec fuseau explicite requis")
    try:
        instant = datetime.fromisoformat(valeur[:-1] + "+00:00" if valeur.endswith("Z") else valeur)
        if instant.utcoffset() is None:
            raise ValueError("fuseau absent")
        return instant.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise ValueError(code + " : horodatage avec fuseau explicite requis") from exc


def _capturer_dossier(dossier):
    try:
        if not isinstance(dossier, dict):
            raise ValueError("dossier absent")
        copie = deepcopy(dossier)
        representation = json.dumps(copie, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if json.loads(representation) != copie:
            raise ValueError("conversion JSON")
        if (
            copie["type"] != "DOSSIER_PREPARATOIRE_DIRECTION"
            or copie["statut_preparation"] != "NON_VALIDE"
            or copie["actualite"] != "NON_EVALUEE"
            or _empreinte({k: v for k, v in copie.items() if k != "dossier_id"}) != copie["dossier_id"]
        ):
            raise ValueError("contenu ou empreinte modifié")
        faits, preuves = copie["faits_selectionnes"], copie["preuves"]
        if not isinstance(faits, dict) or not isinstance(preuves, list):
            raise ValueError("preuves absentes")
        attendus, manquants = copie["modules_attendus"], copie["modules_manquants"]
        if (
            not isinstance(attendus, list) or not 1 <= len(attendus) <= 16
            or any(not isinstance(m, str) or not m.strip() or len(m) > 128 for m in attendus)
            or len(set(attendus)) != len(attendus)
            or not isinstance(manquants, list)
            or manquants != sorted(set(attendus) - faits.keys())
        ):
            raise ValueError("périmètre déclaré ou modules manquants incohérents")
        indices = set()
        for preuve in preuves:
            index = preuve["index"]
            if type(index) is not int or index < 0 or index in indices:
                raise ValueError("index ambigu")
            indices.add(index)
        for module, fait in faits.items():
            if fait["module_source"] != module or fait not in preuves:
                raise ValueError("fait sans preuve exacte")
        if not isinstance(copie["contradictions"], list):
            raise ValueError("contradictions absentes")
        for contradiction in copie["contradictions"]:
            for champ in ("ligne_id_a", "ligne_id_b"):
                index = contradiction[champ]
                if type(index) is not int or index not in indices:
                    raise ValueError("variante contradictoire sans preuve exacte")
        etat = {"type": "ETAT_CONSOLIDE", "faits_par_module": faits, "contradictions": copie["contradictions"]}
        if _empreinte(etat) != copie["etat_id"]:
            raise ValueError("REJ-DIAGNOSTIC-ETAT : empreinte de l'état incohérente")
        return copie
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("REJ-DIAGNOSTIC-ETAT"):
            raise
        raise ValueError("REJ-DIAGNOSTIC-DOSSIER : dossier figé incohérent") from exc


def diagnostiquer_dossier(dossier, horodatage_reference, *, budget_caracteres):
    """Copier une fois le dossier de confiance ; calculer sur cette seule capture.

    Un horodatage historique sans fuseau reste licite dans le dossier existant,
    mais ce diagnostic distinct le refuse comme non comparable, sans le réparer.
    """
    if type(budget_caracteres) is not int or budget_caracteres <= 0:
        raise ValueError("REJ-DIAGNOSTIC-BORNE : budget positif entier requis")
    reference = _instant(horodatage_reference, "REJ-DIAGNOSTIC-REFERENCE")
    copie = _capturer_dossier(dossier)
    observations = []
    for module, fait in sorted(copie["faits_selectionnes"].items()):
        instant = _instant(fait["horodatage"], "REJ-DIAGNOSTIC-OBSERVATION")
        ecart = (reference - instant).total_seconds()
        diagnostic = (
            "OBSERVATION_FUTURE" if ecart < 0
            else "A_REFERENCE" if ecart == 0
            else "ANTERIEURE_REFERENCE"
        )
        observations.append({
            "module_source": module, "index": fait["index"], "hash_maillon": fait["hash_maillon"],
            "horodatage_source": fait["horodatage"], "ecart_secondes": ecart, "diagnostic": diagnostic,
        })
    resultat = {
        "type": "DIAGNOSTIC_TEMPOREL_DOSSIER", "dossier_id": copie["dossier_id"], "etat_id": copie["etat_id"],
        "reference_source": horodatage_reference, "reference_utc": reference.isoformat(),
        "actualite_metier": "NON_EVALUEE", "observations": observations,
        "modules_manquants": copie["modules_manquants"],
        "limites": [
            "Écarts sur les horodatages déclarés des observations sélectionnées ; "
            "ni vérité ni fraîcheur métier prouvée.",
            "Aucun seuil de péremption, couverture globale, arbitrage de contradiction ou action déduit.",
            "Les empreintes lient le contenu capturé, sans authentifier une origine ni accorder de droit.",
        ],
    }
    resultat["diagnostic_id"] = _empreinte(resultat)
    if len(json.dumps(resultat, ensure_ascii=False, allow_nan=False)) > budget_caracteres:
        raise ValueError("REJ-DIAGNOSTIC-BORNE : diagnostic trop volumineux ; aucune sortie tronquée")
    return resultat
