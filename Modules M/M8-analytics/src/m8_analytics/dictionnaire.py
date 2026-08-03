import pathlib

import yaml

from . import contrats


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

            ids_vus.add(metric_id)
            dictionnaire.setdefault(module, {})[metric_id] = {
                cle: metrique[cle] for cle in contrats.CHAMPS_DEFINITION_METRIQUE
            }

    return dictionnaire, erreurs
