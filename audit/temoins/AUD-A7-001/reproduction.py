#!/usr/bin/env python3
"""Témoin RED — AUD-A7-001 : des README annoncent moins que ce qui a été livré.

Chaque module porte un `README.md` dont la ligne de statut résume l'avancement. Ce résumé
est ce qu'un lecteur consulte en premier ; s'il est périmé, il désinforme.

Le témoin confronte deux sources indépendantes :
  - ce que le README ANNONCE (le numéro de story le plus élevé qu'il cite) ;
  - ce qui a été REVU (les dossiers `reviews/<module>-S<nnn>`, une revue scellée par story).

Un README qui cite une story unique alors que huit ont été revues n'est pas faux sur le
statut — le module est bien PARTIAL — mais il l'est sur l'avancement.

La casse des dossiers de revue a changé en cours de projet (`M1-S001` puis `m10-s001`) : la
comparaison est donc insensible à la casse. Une recherche sensible aurait manqué la moitié
des modules et conclu à tort qu'ils n'avaient aucune revue.

Code retour : 1 si un README est en retard, 0 sinon, 2 si la mesure est impossible.
"""
import pathlib
import re
import subprocess
import sys
from collections import defaultdict

RACINE = pathlib.Path(__file__).resolve().parents[3]
MODULES = RACINE / "Modules M"


def _fichiers_suivis() -> list[str]:
    sortie = subprocess.run(
        ["git", "ls-files", "-z"], cwd=RACINE, capture_output=True, text=True, check=True
    ).stdout
    return [c for c in sortie.split("\0") if c]


def main() -> int:
    if not MODULES.exists():
        print(f"TÉMOIN INAPPLICABLE : {MODULES} est introuvable", file=sys.stderr)
        return 2

    suivis = _fichiers_suivis()

    # Stories réellement revues, par module. Insensible à la casse : la convention de
    # nommage a changé en cours de projet et une comparaison stricte perdrait 5 modules.
    revues: dict[str, set[int]] = defaultdict(set)
    for relatif in suivis:
        trouve = re.match(r"reviews/(m\d+)-s(\d{3})", relatif, re.IGNORECASE)
        if trouve:
            revues[trouve.group(1).upper()].add(int(trouve.group(2)))

    constats = []
    print("module  README annonce jusqu'à   stories revues   écart")

    for repertoire in sorted(MODULES.iterdir()):
        if not repertoire.is_dir():
            continue
        readme = repertoire / "README.md"
        if not readme.exists():
            continue
        module = repertoire.name.split("-")[0].upper()

        ligne_statut = ""
        for ligne in readme.read_text(encoding="utf-8").splitlines()[:40]:
            if re.search(r"statut", ligne, re.IGNORECASE):
                ligne_statut = ligne
                break
        if not ligne_statut:
            continue

        # Le plus haut numéro de story que le README cite.
        cites = [int(n) for n in re.findall(r"S(\d{3})", ligne_statut)]
        annonce = max(cites) if cites else None
        faites = max(revues.get(module, {0})) if revues.get(module) else 0

        if annonce is None:
            marque = "(aucune story citée)"
        elif annonce < faites:
            marque = f"RETARD de {faites - annonce}"
            constats.append(
                f"{repertoire.name}/README.md annonce jusqu'à S{annonce:03d} alors que "
                f"S{faites:03d} a été revue — {faites - annonce} story(ies) livrée(s) non annoncée(s)"
            )
        else:
            marque = "à jour"

        annonce_txt = f"S{annonce:03d}" if annonce is not None else "—"
        print(f"  {module:5s}  {annonce_txt:22s}  S{faites:03d} ({len(revues.get(module, ()))})"
              f"        {marque}")

    print()
    if not constats:
        print("CONSTAT NON REPRODUIT : chaque README annonce au moins ce qui a été revu.")
        print("AUD-A7-001 est périmé et doit être retiré du rapport.")
        return 0

    print(f"CONSTAT AUD-A7-001 CONFIRMÉ — {len(constats)} README en retard :")
    for constat in constats:
        print(f"  - {constat}")
    print()
    print("Ce que le témoin N'AFFIRME PAS : que le statut PARTIAL soit faux — il est exact")
    print("pour les dix modules. Il établit que la ligne consultée en premier par un lecteur")
    print("annonce moins d'avancement qu'il n'y en a, et qu'aucun gate ne compare ces deux")
    print("sources.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
