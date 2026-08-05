#!/usr/bin/env python3
"""Témoin RED — AUD-A5-001 : les tests d'autorisation et de secrets ne bloquent rien.

La protection de la branche `main` n'exige qu'un seul check : `gates`. Les deux autres
jobs du fichier de CI portent `continue-on-error: true`, ce qui signifie qu'ils sont
rapportés en succès à GitHub quelle que soit l'issue réelle de leurs étapes.

Or le job `e2e` exécute les tests d'autorisation (`core/src/authz/tests`), ceux du coffre
à secrets (`core/src/config/tests`), ceux du tableau de bord et le harnais de bout en
bout. Une régression d'autorisation — une élévation de privilège, une fuite entre
locataires — laisse donc la CI verte et le merge ouvert.

Le témoin ne modifie ni la CI ni le code : il lit le fichier de workflow, interroge
l'API GitHub pour connaître les checks réellement exigés, et compte les tests concernés.

Code retour : 1 si le défaut est reproduit, 0 s'il ne l'est plus, 2 si la mesure est
impossible (fichier ou API indisponible) — auquel cas il ne conclut pas.
"""
import json
import pathlib
import re
import subprocess
import sys

RACINE = pathlib.Path(__file__).resolve().parents[3]
CI = RACINE / ".github" / "workflows" / "ci.yml"
DEPOT = "leon36000/OPSYS-AI"

# Répertoires dont l'échec devrait, par nature, empêcher une fusion.
SENSIBLES = {
    "core/src/authz/tests": "autorisation",
    "core/src/config/tests": "coffre à secrets",
}


def _jobs_du_workflow() -> dict:
    """Découpe le workflow par job, sans dépendance à un analyseur YAML tiers.

    Le dépôt s'interdit toute dépendance hors bibliothèque standard ; un analyseur
    approximatif mais explicite vaut mieux qu'un import qui ne serait pas disponible
    chez un tiers rejouant ce témoin.
    """
    jobs, courant = {}, None
    for numero, ligne in enumerate(CI.read_text(encoding="utf-8").splitlines(), 1):
        entete = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", ligne)
        if entete:
            courant = entete.group(1)
            jobs[courant] = {"ligne": numero, "non_bloquant": False, "etapes": []}
            continue
        if courant is None:
            continue
        if re.match(r"^\s+continue-on-error:\s*true\s*$", ligne):
            jobs[courant]["non_bloquant"] = True
        commande = re.match(r"^\s+run:\s*(.+)$", ligne)
        if commande:
            jobs[courant]["etapes"].append(commande.group(1).strip())
    return jobs


def _checks_exiges() -> list[str] | None:
    """Ce que la protection de branche exige RÉELLEMENT — jamais ce qu'on suppose."""
    resultat = subprocess.run(
        ["gh", "api", f"repos/{DEPOT}/branches/main/protection",
         "--jq", ".required_status_checks.contexts"],
        capture_output=True, text=True,
    )
    if resultat.returncode != 0:
        return None
    try:
        return json.loads(resultat.stdout)
    except json.JSONDecodeError:
        return None


def _compter_tests(repertoire: str) -> int | None:
    """Nombre de tests réellement collectés — compté, jamais estimé.

    Trois formats de sortie coexistent selon la version de pytest et le niveau de
    verbosité : « N tests collected », une ligne par test contenant « :: », ou
    « chemin: N » par fichier. On les couvre tous, et on renvoie None plutôt qu'un
    zéro si aucun ne s'applique : un constat qui annoncerait « 0 test » là où le
    comptage a échoué serait une donnée inventée.
    """
    chemin = RACINE / repertoire
    if not chemin.exists():
        return None
    resultat = subprocess.run(
        [sys.executable, "-m", "pytest", repertoire, "-q", "--collect-only"],
        cwd=RACINE, capture_output=True, text=True,
    )
    trouve = re.search(r"(\d+) tests? collected", resultat.stdout)
    if trouve:
        return int(trouve.group(1))
    par_test = [l for l in resultat.stdout.splitlines() if "::" in l]
    if par_test:
        return len(par_test)
    par_fichier = re.findall(r"^\S+\.py:\s*(\d+)\s*$", resultat.stdout, re.MULTILINE)
    if par_fichier:
        return sum(int(n) for n in par_fichier)
    return None


def main() -> int:
    if not CI.exists():
        print(f"TÉMOIN INAPPLICABLE : {CI} est introuvable")
        return 2

    jobs = _jobs_du_workflow()
    if not jobs:
        print("TÉMOIN INAPPLICABLE : aucun job reconnu dans le workflow")
        return 2

    exiges = _checks_exiges()
    if exiges is None:
        print("TÉMOIN INAPPLICABLE : la protection de branche n'a pas pu être lue")
        return 2

    print(f"checks exigés par la protection de main : {exiges}\n")

    constats = []
    total_tests = 0

    for nom, details in jobs.items():
        etat = "NON BLOQUANT" if details["non_bloquant"] else "bloquant"
        exige = nom in exiges
        print(f"── job « {nom} » (ligne {details['ligne']}) — {etat}, "
              f"{'exigé' if exige else 'NON exigé'} par la protection")

        if not details["non_bloquant"] and exige:
            continue

        for etape in details["etapes"]:
            for repertoire, quoi in SENSIBLES.items():
                if repertoire in etape:
                    nombre = _compter_tests(repertoire)
                    total_tests += nombre or 0
                    print(f"     {repertoire} — {quoi} — {nombre} tests")
                    constats.append(
                        f"les {nombre} tests d'{quoi} ({repertoire}) sont exécutés par le "
                        f"job « {nom} », qui est {etat.lower()} et n'est pas exigé au merge"
                    )

    print()
    if not constats:
        print("CONSTAT NON REPRODUIT : plus aucun test sensible dans un job non bloquant.")
        print("AUD-A5-001 est périmé et doit être retiré du rapport.")
        return 0

    print(f"CONSTAT AUD-A5-001 CONFIRMÉ — {len(constats)} manifestation(s), "
          f"{total_tests} tests sensibles concernés :")
    for constat in constats:
        print(f"  - {constat}")
    print()
    print("Ce que le témoin NE prétend PAS : il ne montre aucune faille d'autorisation.")
    print("Il montre qu'une régression d'autorisation traverserait la CI sans la rougir —")
    print("c'est une exposition du dispositif de contrôle, pas une vulnérabilité exploitée.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
