import sys
from pathlib import Path
import re
import yaml

STATUTS_VIDES = ("STUB",)
STATUTS_AVEC_CODE = ("PILOTE", "PARTIAL", "COMPLET")


def mesurer_module(racine_module: Path) -> dict:
    """Retourne le nombre de paquets, modules source, fichiers plats et fichiers de test."""
    resultat = {"paquets": 0, "modules_source": 0, "fichiers_plats": 0, "fichiers_test": 0}
    src_dir = racine_module / "src"
    tests_dir = racine_module / "tests"

    # Paquets et modules source
    if src_dir.is_dir():
        # Fichiers .py à plat (hors paquet)
        fichiers_plats = list(src_dir.glob("*.py"))
        resultat["fichiers_plats"] = len(fichiers_plats)

        # Paquets : sous-dossiers contenant __init__.py
        for subdir in src_dir.iterdir():
            if subdir.is_dir() and (subdir / "__init__.py").is_file():
                resultat["paquets"] += 1
                # Modules source dans ce paquet (hors __init__.py)
                modules = [f for f in subdir.glob("*.py") if f.name != "__init__.py"]
                resultat["modules_source"] += len(modules)

    # Fichiers de test
    if tests_dir.is_dir():
        resultat["fichiers_test"] = len(list(tests_dir.glob("test_*.py")))

    return resultat


def lire_statut_readme(racine_module: Path) -> str | None:
    """Retourne le statut déclaré dans le README.md du module, ou None si absent."""
    readme_path = racine_module / "README.md"
    if not readme_path.is_file():
        return None
    try:
        with open(readme_path, encoding="utf-8") as f:
            for line in f:
                # Chercher une ligne commençant exactement par "Statut:"
                match = re.match(r"^Statut:\s*(\w+)", line)
                if match:
                    return match.group(1)
    except Exception:
        return None
    return None


def verifier(chemin_registre: Path, racine_modules: Path) -> list:
    """Vérifie la cohérence entre le registre, le statut README et la réalité des modules.
    Retourne une liste de messages d'anomalie (vide si tout est correct)."""
    with open(chemin_registre, encoding="utf-8") as f:
        registre = yaml.safe_load(f)
    modules_registre = registre["modules"]
    noms_registre = {m["name"]: m["statut"] for m in modules_registre}

    noms_disque = set()
    if racine_modules.is_dir():
        noms_disque = {d.name for d in racine_modules.iterdir() if d.is_dir()}

    anomalies = []

    # Bijection disque ↔ registre (point 6)
    # Modules dans le registre mais absents du disque
    for nom in noms_registre.keys() - noms_disque:
        anomalies.append(f"Module '{nom}' présent dans le registre mais absent sur le disque.")
    # Modules sur le disque mais absents du registre
    for nom in noms_disque - noms_registre.keys():
        anomalies.append(f"Module '{nom}' présent sur le disque mais absent du registre.")

    # Vérifications par module (seulement ceux présents à la fois sur disque et registre)
    for nom_module, statut_registre in noms_registre.items():
        if nom_module not in noms_disque:
            continue  # déjà signalé

        dossier_module = racine_modules / nom_module
        mesure = mesurer_module(dossier_module)
        statut_readme = lire_statut_readme(dossier_module)

        # 1. Statut inconnu
        if statut_registre not in STATUTS_VIDES and statut_registre not in STATUTS_AVEC_CODE:
            anomalies.append(
                f"Module '{nom_module}' : statut '{statut_registre}' inconnu "
                f"(hors listes STATUTS_VIDES / STATUTS_AVEC_CODE)."
            )

        # 2. STUB avec du code ou des tests
        if statut_registre in STATUTS_VIDES:
            if mesure["modules_source"] > 0 or mesure["fichiers_test"] > 0:
                anomalies.append(
                    f"Module '{nom_module}' déclaré STUB mais porte "
                    f"{mesure['modules_source']} modules source "
                    f"et {mesure['fichiers_test']} fichiers de test."
                )

        # 3. AVEC_CODE sans code ou sans tests
        if statut_registre in STATUTS_AVEC_CODE:
            if mesure["modules_source"] == 0 or mesure["fichiers_test"] == 0:
                anomalies.append(
                    f"Module '{nom_module}' déclaré {statut_registre} mais a "
                    f"{mesure['modules_source']} modules source "
                    f"(min 1 exigé) et {mesure['fichiers_test']} fichiers de test "
                    f"(min 1 exigé)."
                )

        # 4. Fichiers plats interdits
        if mesure["fichiers_plats"] > 0:
            anomalies.append(
                f"Module '{nom_module}' contient {mesure['fichiers_plats']} "
                f"fichier(s) .py à plat sous src/ (identité de paquet interdite)."
            )

        # 5. Alignement README ↔ registre
        if statut_readme is None:
            anomalies.append(
                f"Module '{nom_module}' : README.md absent ou sans ligne 'Statut:'."
            )
        elif statut_readme != statut_registre:
            anomalies.append(
                f"Module '{nom_module}' : statut README '{statut_readme}' "
                f"≠ statut registre '{statut_registre}'."
            )

    return anomalies


def main(argv=None):
    """Point d'entrée. RETOURNE le code de sortie (0 conforme, 1 anomalies).

    `argv` est une liste explicite ; `None` reprend `sys.argv[1:]`. Un `main` qui
    consomme l'argv AMBIANT est intestable : lancé sous pytest, il lisait les
    arguments de pytest comme chemin de registre (mesuré).

    Les chemins par défaut sont déduits de l'EMPLACEMENT DU SCRIPT, jamais du
    répertoire courant : une gate de CI ne doit pas dépendre d'où on l'invoque.
    """
    argv = list(sys.argv[1:]) if argv is None else list(argv)

    racine = Path(__file__).resolve().parent.parent
    registre_defaut = racine / "registries" / "modules.yaml"
    modules_defaut = racine / "Modules M"

    chemin_registre = Path(argv[0]) if len(argv) > 0 else registre_defaut
    racine_modules = Path(argv[1]) if len(argv) > 1 else modules_defaut

    anomalies = verifier(chemin_registre, racine_modules)

    # Nombre de modules vérifiés pour le message VERT
    nb_modules_verifies = 0
    if chemin_registre.is_file() and racine_modules.is_dir():
        with open(chemin_registre, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        noms = {m["name"] for m in data["modules"]}
        noms_disque = {d.name for d in racine_modules.iterdir() if d.is_dir()}
        nb_modules_verifies = len(noms & noms_disque)

    if not anomalies:
        print(f"STATUT_LINT: VERT ({nb_modules_verifies} modules vérifiés)")
        return 0
    else:
        print(f"STATUT_LINT: ROUGE ({len(anomalies)} anomalies)")
        for a in anomalies:
            print(a)
        return 1


if __name__ == "__main__":
    sys.exit(main())
