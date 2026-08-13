from __future__ import annotations

import math
from pathlib import Path

import yaml

from . import validation

CHAMPS_TAUX_FISCAL = frozenset({"id", "nom", "taux", "version", "source"})
_CHAMPS_TEXTE = ("id", "nom", "version", "source")

# Borne de validation (pas une valeur financière — invariant de représentation) :
# le champ 'taux' est une fraction entre 0 et 1 (ex. 0.05 pour 5 %), confirmée
# par contracts/taux_fiscaux.v1.yaml (tps_federale.taux == 0.05). Nom choisi
# sans le morceau "taux" pour ne pas déclencher LITTERAL_COUT_INTERDIT
# (conformite._contexte_monetaire) sur ce qui n'est pas un montant.
_BORNE_HAUTE_FRACTION_VALIDATION = 1.0


def charger_taux_fiscaux(chemin):
    dictionnaire = {}
    erreurs = []

    contenu = yaml.safe_load(Path(chemin).read_text(encoding="utf-8"))

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

        if isinstance(montant, float) and not math.isfinite(montant):
            erreurs.append(f"taux invalide {identifiant} : 'taux' doit être fini")
            continue

        if montant < 0 or montant > _BORNE_HAUTE_FRACTION_VALIDATION:
            erreurs.append(f"taux invalide {identifiant} : 'taux' hors bornes")
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
