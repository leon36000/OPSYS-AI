from __future__ import annotations

import yaml

from . import validation

CHAMPS_TAUX_FISCAL = frozenset({"id", "nom", "taux", "version", "source"})
_CHAMPS_TEXTE = ("id", "nom", "version", "source")


def charger_taux_fiscaux(chemin):
    dictionnaire = {}
    erreurs = []

    contenu = yaml.safe_load(open(chemin, encoding="utf-8").read())

    if not isinstance(contenu, dict) or contenu.get("schema_version") != 1:
        erreurs.append(f"schema_version invalide : {chemin}")
        return dictionnaire, erreurs

    liste_taux = contenu.get("taux")
    if not isinstance(liste_taux, list):
        erreurs.append(f"clé 'taux' absente ou invalide : {chemin}")
        return dictionnaire, erreurs

    for index, item in enumerate(liste_taux):
        identifiant = item.get("id") if isinstance(item, dict) else index

        if not isinstance(item, dict) or set(item.keys()) != CHAMPS_TAUX_FISCAL:
            erreurs.append(f"taux invalide {identifiant} : clés non conformes")
            continue

        montant = item["taux"]
        if isinstance(montant, bool) or not isinstance(montant, (int, float)):
            erreurs.append(
                f"taux invalide {identifiant} : 'taux' doit être un nombre"
            )
            continue

        if any(
            not isinstance(item[champ], str) or item[champ] == ""
            for champ in _CHAMPS_TEXTE
        ):
            erreurs.append(f"taux invalide {identifiant} : champ texte vide")
            continue

        taux_id = item["id"]
        if taux_id in dictionnaire:
            erreurs.append(f"identifiant de taux dupliqué {taux_id} : {chemin}")
            continue

        dictionnaire[taux_id] = dict(item)

    return dictionnaire, erreurs


def rechercher_taux(dictionnaire, taux_id):
    if taux_id in dictionnaire:
        return dictionnaire[taux_id], None
    return None, validation.construire_verdict(
        "REJ-TAUX-INCONNU",
        detail=f"identifiant de taux inconnu : {taux_id!r}",
    )
