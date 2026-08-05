#!/usr/bin/env python3
"""Témoin RED — AUD-A2-003 : aucun verdict ne dit SUR QUEL CODE il porte.

Le dispositif de revue scelle le pack soumis aux relecteurs par un `prompt_sha256`
partagé : les trois membres d'un trio ont donc démontrablement lu le même texte. C'est
une garantie réelle, et elle tient.

Ce qu'aucun verdict ne porte, en revanche, c'est un lien vers le code approuvé — ni
commit, ni sha d'arbre, ni empreinte de diff. L'approbation flotte : elle atteste qu'un
pack a été jugé, sans que rien n'établisse que le code fusionné soit celui de ce pack.

Conséquence, formulée sans exagération : entre le moment où le pack est construit et
celui où la branche est fusionnée, la branche peut recevoir d'autres commits. Le verdict
resterait le même fichier, avec le même sceau, et rien dans le dossier de revue ne
permettrait de s'en apercevoir. C'est un décalage entre ce qui est vérifié et ce qui est
utilisé.

Le témoin ne modifie rien : il inventorie les clés des verdicts et cherche un champ
liant à un état du dépôt.

Code retour : 1 si le défaut est reproduit, 0 s'il ne l'est plus, 2 si la mesure est
impossible.
"""
import json
import pathlib
import sys
from collections import Counter

RACINE = pathlib.Path(__file__).resolve().parents[3]

# Un champ liant l'approbation à un état du dépôt porterait l'un de ces noms.
# La liste est large à dessein : si le lien existait sous un nom inattendu, mieux vaut
# le trouver et réfuter le constat que le manquer et l'affirmer à tort.
INDICES_DE_LIEN = (
    "commit", "sha1", "sha256_diff", "diff_sha", "head", "branche", "branch",
    "revision", "tree", "arbre", "base", "merge",
)


def main() -> int:
    racines = [RACINE / "reviews", RACINE / "registries" / "verdicts"]
    presentes = [r for r in racines if r.exists()]
    if not presentes:
        print("TÉMOIN INAPPLICABLE : aucun répertoire de verdicts")
        return 2

    cles = Counter()
    total = 0
    porteurs = []

    for racine in presentes:
        for chemin in sorted(racine.rglob("*.json")):
            try:
                contenu = json.loads(chemin.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(contenu, dict):
                continue
            total += 1
            cles.update(contenu.keys())
            for cle in contenu:
                if any(indice in cle.lower() for indice in INDICES_DE_LIEN):
                    porteurs.append((chemin.relative_to(RACINE).as_posix(), cle))

    if total == 0:
        print("TÉMOIN INAPPLICABLE : aucun verdict lisible")
        return 2

    print(f"verdicts inventoriés : {total}\n")
    print("clés observées :")
    for cle, nombre in cles.most_common():
        print(f"  {nombre:5d}×  {cle}")

    scelles = cles.get("prompt_sha256", 0)
    print(f"\nverdicts portant prompt_sha256 (sceau du pack) : {scelles}/{total}")
    print(f"verdicts portant un lien vers un état du dépôt   : {len(porteurs)}/{total}")

    print()
    if porteurs:
        print("CONSTAT NON REPRODUIT : des verdicts portent un lien vers le code.")
        for chemin, cle in porteurs[:5]:
            print(f"  {chemin} -> {cle}")
        print("AUD-A2-003 est périmé et doit être retiré du rapport.")
        return 0

    print(f"CONSTAT AUD-A2-003 CONFIRMÉ :")
    print(f"  - aucun des {total} verdicts ne porte de champ liant l'approbation à un")
    print(f"    commit, un arbre, une branche ou une empreinte de diff")
    print(f"  - le sceau du pack est en revanche présent sur {scelles} d'entre eux : les")
    print("    relecteurs ont bien lu le même texte, ce que le constat ne remet pas en cause")
    print()
    print("Ce que le témoin N'AFFIRME PAS : qu'un code non approuvé ait été fusionné.")
    print("Il établit que rien, dans le dossier de revue, ne permettrait de le savoir.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
