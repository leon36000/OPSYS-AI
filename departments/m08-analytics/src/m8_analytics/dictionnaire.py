import pathlib
import re

import yaml

from . import contrats

# Garde de devise (docs/research/R9-m7-m8.md §1.3) : une unité de la forme
# DEVISE/quelquechose (ex. "CAD/lead") est une unité MONÉTAIRE et doit être en
# CAD — projet 100 % QC/CAD (TPS/TVQ, Loi 25). Une unité qui ne suit pas ce
# patron (ex. "ratio", "pourcentage", "dict {note: entier}") n'est pas
# monétaire et n'est pas contrainte par cette garde. Préfixée `_` : allow-list
# technique, pas un énuméré de domaine à classer (pas d'échappatoire D-032).
_MOTIF_UNITE_MONETAIRE = re.compile(r"^([A-Z]{3})/\w+$")
_DEVISES_AUTORISEES = frozenset({"CAD"})


def _devise_non_autorisee(unite):
    """Devise trouvée dans une unité monétaire non autorisée, sinon None."""
    correspondance = _MOTIF_UNITE_MONETAIRE.match(unite)
    if correspondance is None:
        return None
    devise = correspondance.group(1)
    if devise in _DEVISES_AUTORISEES:
        return None
    return devise


def compiler_dictionnaire(racine_modules):
    dictionnaire = {}
    erreurs = []

    for chemin in sorted(pathlib.Path(racine_modules).glob("*/metrics/*.yaml")):
        try:
            contenu = yaml.safe_load(chemin.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            erreurs.append(f"Erreur de parsing YAML : {chemin}")
            continue

        if not isinstance(contenu, dict):
            erreurs.append(f"Contenu YAML invalide : {chemin}")
            continue

        module = contenu.get("module")
        if (
            contenu.get("schema_version") != 1
            or not isinstance(module, str)
            or not module
            or not isinstance(contenu.get("metrics"), list)
        ):
            erreurs.append(f"Schéma invalide : {chemin}")
            continue

        ids_vus = set()
        for index, metrique in enumerate(contenu["metrics"]):
            identifiant = (
                metrique.get("id")
                if isinstance(metrique, dict) and "id" in metrique
                else index
            )

            if (
                not isinstance(metrique, dict)
                or set(metrique.keys()) != contrats.CHAMPS_DEFINITION_METRIQUE
                or any(
                    not isinstance(metrique[cle], str) or not metrique[cle]
                    for cle in contrats.CHAMPS_DEFINITION_METRIQUE
                )
            ):
                erreurs.append(f"Métrique invalide {identifiant} : {chemin}")
                continue

            metric_id = metrique["id"]
            if metric_id in ids_vus:
                erreurs.append(f"ID de métrique dupliqué {metric_id} : {chemin}")
                continue

            devise_refusee = _devise_non_autorisee(metrique["unite"])
            if devise_refusee is not None:
                erreurs.append(
                    f"Devise non autorisée {devise_refusee!r} (unité {metrique['unite']!r}) "
                    f"pour métrique monétaire {metric_id} : {chemin}"
                )
                continue

            ids_vus.add(metric_id)
            dictionnaire.setdefault(module, {})[metric_id] = {
                cle: metrique[cle] for cle in contrats.CHAMPS_DEFINITION_METRIQUE
            }

    return dictionnaire, erreurs
