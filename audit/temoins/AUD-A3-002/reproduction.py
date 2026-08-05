#!/usr/bin/env python3
"""Témoin RED — AUD-A3-002 : les services transversaux de D-010 ne sont pas dans le core.

D-010 constate que six plans de module réinventaient chacun leur approbation, leur piste
d'audit et leurs permissions, et décide : « ces mécanismes deviennent des services du core,
consommés par tous les modules via des API de domaine. Chaque module garde ses règles
métier ; le core fournit la mécanique. »

Chercher les noms de la première colonne du tableau tels quels ne prouverait rien : un
service peut vivre sous un nom technique différent de son libellé de plan. Le témoin fait
donc correspondre chaque service à des mots-clés, et distingue **trois** situations, parce
que les confondre donnerait une mesure fausse dans les deux sens :

  - implémenté DANS le core : la décision est tenue ;
  - implémenté DANS UN MODULE : c'est précisément ce que D-010 voulait empêcher, et cela
    ne peut pas compter comme conforme ;
  - absent partout : le service n'existe pas.

Un décompte qui dirait « cinq services à zéro fichier » serait faux : l'autorisation fine
existe. Un décompte qui dirait « trois sur cinq présents » le serait tout autant :
l'approbation vit dans un module. La mesure ne vaut que si elle sépare les trois cas.

Code retour : 1 si le défaut est reproduit, 0 s'il ne l'est plus, 2 si la mesure est
impossible.
"""
import pathlib
import subprocess
import sys

RACINE = pathlib.Path(__file__).resolve().parents[3]

# Correspondance service de D-010 -> mots-clés susceptibles de le désigner dans un chemin.
# Les mots-clés sont larges à dessein : mieux vaut trouver une implémentation sous un nom
# inattendu et réfuter le constat, que la manquer et l'affirmer à tort.
SERVICES = {
    "Approval Engine": ("approval", "approbation"),
    "Autorisation fine": ("authz", "autorisation", "permission", "rbac", "openfga"),
    "Audit / Ledger": ("ledger", "audit_log", "piste_audit"),
    "Gate Engine": ("gate_engine", "moteur_gate"),
    "Bus de notifications": ("notification_bus", "bus_notification", "event_bus", "bus"),
}

PREFIXE_CORE = "core/"
PREFIXE_MODULE = "Modules M/"


def _fichiers_suivis() -> list[str]:
    """Chemins NUL-terminés : « Modules M/ » contient une espace."""
    sortie = subprocess.run(
        ["git", "ls-files", "-z"], cwd=RACINE, capture_output=True, text=True, check=True
    ).stdout
    return [c for c in sortie.split("\0") if c]


def main() -> int:
    fichiers = _fichiers_suivis()
    if not fichiers:
        print("TÉMOIN INAPPLICABLE : aucun fichier suivi", file=sys.stderr)
        return 2

    # L'audit ne se compte pas lui-même : ses propres fichiers citent ces mots-clés.
    fichiers = [f for f in fichiers if not f.startswith("audit/")]

    dans_core, dans_module, absents = {}, {}, []

    for service, motscles in SERVICES.items():
        core = [
            f for f in fichiers
            if f.startswith(PREFIXE_CORE) and any(m in f.lower() for m in motscles)
        ]
        module = [
            f for f in fichiers
            if f.startswith(PREFIXE_MODULE) and any(m in f.lower() for m in motscles)
        ]
        if core:
            dans_core[service] = core
        elif module:
            dans_module[service] = module
        else:
            absents.append(service)

    print(f"services énumérés par D-010 : {len(SERVICES)}\n")

    for service, chemins in dans_core.items():
        print(f"  DANS LE CORE      {service} — {len(chemins)} fichier(s)")
        for chemin in chemins[:3]:
            print(f"                      {chemin}")

    for service, chemins in dans_module.items():
        print(f"  DANS UN MODULE    {service} — {len(chemins)} fichier(s)")
        for chemin in chemins[:3]:
            print(f"                      {chemin}")

    for service in absents:
        print(f"  ABSENT PARTOUT    {service}")

    print()
    print(f"  dans le core   : {len(dans_core)}/{len(SERVICES)}")
    print(f"  dans un module : {len(dans_module)}/{len(SERVICES)}")
    print(f"  absents        : {len(absents)}/{len(SERVICES)}")

    constats = []
    if dans_module:
        constats.append(
            f"{len(dans_module)} service(s) implémenté(s) DANS UN MODULE — "
            f"{', '.join(dans_module)} — alors que D-010 les place dans le core"
        )
    if absents:
        constats.append(
            f"{len(absents)} service(s) absent(s) du dépôt entier — {', '.join(absents)}"
        )

    print()
    if not constats:
        print("CONSTAT NON REPRODUIT : les cinq services vivent dans le core.")
        print("AUD-A3-002 est périmé et doit être retiré du rapport.")
        return 0

    print(f"CONSTAT AUD-A3-002 CONFIRMÉ — {len(constats)} manifestation(s) :")
    for constat in constats:
        print(f"  - {constat}")
    print()
    print("Ce que le témoin N'AFFIRME PAS : que ces services soient nécessaires dès")
    print("aujourd'hui. Les dix modules sont au statut PARTIAL et rien n'est en production ;")
    print("D-010 ne fixe aucune échéance. Il établit un écart entre une décision ratifiée")
    print("et l'état du dépôt, et signale que l'un des services vit précisément là où la")
    print("décision voulait qu'il ne soit pas.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
