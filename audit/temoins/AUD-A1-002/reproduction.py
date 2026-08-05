#!/usr/bin/env python3
"""Témoin RED — AUD-A1-002 : un module vide mais bien rangé passe le contrôle de statut.

`statut_lint.py` est le gate qui confronte le statut déclaré d'un module à la réalité. Il
tourne dans le job `gates`, seul check exigé par la protection de branche.

Le témoin fabrique un module structurellement irréprochable et sémantiquement creux :
arborescence conforme, `README.md` déclarant `PARTIAL (vague 1 livrée)`, un fichier source
sans une seule instruction, un test sans assertion. Puis il l'inscrit au registre et
relance le contrôle.

Une première version de ce témoin n'inscrivait PAS le module au registre. Le contrôle le
rejetait alors — mais pour une tout autre raison (« présent sur le disque, absent du
registre »), c'est-à-dire par une garde antérieure. On aurait conclu que la vacuité était
détectée, alors que rien ne l'avait examinée. Le décor doit être juste pour que le refus
porte sur ce qu'on mesure.

Le témoin ne touche à rien : il opère sur une copie en répertoire temporaire.

Code retour : 1 si le module creux passe, 0 s'il est refusé, 2 si la mesure est impossible.
"""
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

RACINE = pathlib.Path(__file__).resolve().parents[3]
CONTROLE = RACINE / "scripts" / "statut_lint.py"

MODULE = "M99-fantome"


def _inscrire_au_registre(copie: pathlib.Path) -> pathlib.Path | None:
    """Sans cette inscription, le refus viendrait de la bijection, pas de la vacuité."""
    for chemin in sorted(copie.rglob("*.yaml")):
        texte = chemin.read_text(encoding="utf-8")
        if "modules:" not in texte or "name:" not in texte:
            continue
        lignes = texte.splitlines()
        premier = next(
            (k for k, l in enumerate(lignes) if l.strip().startswith("- name:")), None
        )
        if premier is None:
            continue
        marge = " " * (len(lignes[premier]) - len(lignes[premier].lstrip()))
        lignes.insert(premier, f'{marge}- name: "{MODULE}"')
        lignes.insert(premier + 1, f'{marge}  statut: "PARTIAL"')
        chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
        return chemin
    return None


def main() -> int:
    if not CONTROLE.exists():
        print(f"TÉMOIN INAPPLICABLE : {CONTROLE} est introuvable", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="aud-a1-002-") as tmp:
        copie = pathlib.Path(tmp) / "repo"
        for nom in ("scripts", "Modules M", "registries", "Registres"):
            source = RACINE / nom
            if source.exists():
                shutil.copytree(source, copie / nom, dirs_exist_ok=True)

        # Un module irréprochable de forme, creux de fond.
        faux = copie / "Modules M" / MODULE
        (faux / "src" / "m99_fantome").mkdir(parents=True)
        (faux / "tests").mkdir(parents=True)
        (faux / "src" / "m99_fantome" / "__init__.py").write_text("", encoding="utf-8")
        (faux / "src" / "m99_fantome" / "coeur.py").write_text(
            '"""Ce module ne contient aucune instruction exécutable."""\n', encoding="utf-8"
        )
        (faux / "tests" / "test_coeur.py").write_text(
            "def test_qui_n_assure_rien():\n    pass\n", encoding="utf-8"
        )
        (faux / "README.md").write_text(
            f"# {MODULE}\n\nStatut: PARTIAL (vague 1 livree)\n", encoding="utf-8"
        )

        registre = _inscrire_au_registre(copie)
        if registre is None:
            print("TÉMOIN INAPPLICABLE : aucun registre de modules trouvé", file=sys.stderr)
            return 2

        resultat = subprocess.run(
            [sys.executable, "scripts/statut_lint.py"],
            cwd=copie, capture_output=True, text=True, timeout=300,
        )
        sortie = resultat.stdout + resultat.stderr
        signale = MODULE in sortie

        print(f"module creux fabriqué : {MODULE}")
        print("  arborescence conforme, README déclarant « PARTIAL (vague 1 livree) »")
        print("  1 fichier source sans aucune instruction exécutable")
        print("  1 test sans assertion")
        print(f"  inscrit au registre {registre.name} — sans quoi le refus viendrait")
        print("  de la bijection disque/registre, non de la vacuité")
        print()
        print(f"  statut_lint -> rc={resultat.returncode}")
        print(f"  le module creux est-il signalé ? {'OUI' if signale else 'NON'}")
        for ligne in sortie.splitlines():
            if MODULE in ligne:
                print(f"     {ligne.strip()[:120]}")

    print()
    if signale or resultat.returncode != 0:
        print("CONSTAT NON REPRODUIT : le contrôle refuse le module creux.")
        print("AUD-A1-002 est périmé et doit être retiré du rapport.")
        return 0

    print("CONSTAT AUD-A1-002 CONFIRMÉ :")
    print("  - un module sans une seule instruction exécutable, dont l'unique test")
    print("    n'assure rien, déclarant « vague 1 livrée », passe le contrôle en rc=0 ;")
    print("  - ce contrôle tourne dans le job « gates », seul check exigé au merge.")
    print()
    print("Ce que le témoin N'AFFIRME PAS : qu'un tel module existe dans le dépôt — la")
    print("sonde A1 mesure le contraire, 7 771 instructions réparties sur 135 fichiers.")
    print("Il établit que rien n'empêcherait qu'il y en ait un.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
