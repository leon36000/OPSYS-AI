#!/usr/bin/env python3
"""Témoin RED — AUD-A1-001 : `ledger_append.py verify` valide un registre absent.

D-042 (ratifiée Nathan) fait des quatre `.jsonl` du répertoire `registries/ledger/` des
journaux d'ajout hachés en chaîne, dont l'intégrité doit être vérifiable. Le job CI
`gates` — le seul que la protection de branche exige — exécute `ledger_append.py verify`
sous le libellé « Ledger integrity (D-042) ».

Or `verify()` commence par `if not os.path.exists(path): return True, 0`. Un registre
absent est donc rapporté `OK (0 entrees)`, et le code retour global reste 0. Supprimer un
registre entier — ou les quatre — laisse le gate au vert.

Ce n'est pas une hypothèse : `registries/ledger/installations.jsonl` n'existe pas dans le
dépôt, et la CI affiche `installations.jsonl: OK (0 entrees)` à chaque exécution depuis la
mise en place du gate.

Ce que le témoin NE fait PAS : il ne touche aucun registre réel. Il travaille sur une copie
en répertoire temporaire (DA-AUD-08). L'audit ne modifie rien (DA-AUD-04).

Code retour : 1 si le défaut est reproduit (constat CONFIRMÉ), 0 s'il ne l'est plus
(le constat serait alors périmé et devrait être retiré du rapport).
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

RACINE = pathlib.Path(__file__).resolve().parents[3]
LEDGER = RACINE / "registries" / "ledger"
SCRIPT = RACINE / "scripts" / "ledger_append.py"


def _verifier(racine_travail: pathlib.Path) -> tuple[int, str]:
    """Exécute le vérificateur SANS pipeline : un pipe masquerait le code retour."""
    resultat = subprocess.run(
        [sys.executable, "scripts/ledger_append.py", "verify"],
        cwd=racine_travail,
        capture_output=True,
        text=True,
    )
    return resultat.returncode, resultat.stdout + resultat.stderr


def main() -> int:
    if not SCRIPT.exists():
        print(f"TÉMOIN INAPPLICABLE : {SCRIPT} est introuvable")
        return 2

    constats = []

    with tempfile.TemporaryDirectory(prefix="aud-a1-001-") as tmp:
        travail = pathlib.Path(tmp) / "repo"
        (travail / "scripts").mkdir(parents=True)
        (travail / "registries" / "ledger").mkdir(parents=True)
        shutil.copy2(SCRIPT, travail / "scripts" / "ledger_append.py")

        registres = sorted(LEDGER.glob("*.jsonl"))
        for chemin in registres:
            shutil.copy2(chemin, travail / "registries" / "ledger" / chemin.name)

        total = sum(
            1
            for chemin in registres
            for ligne in chemin.read_text(encoding="utf-8").splitlines()
            if ligne.strip()
        )
        print(f"registres copiés : {len(registres)} — {total} entrées au total\n")

        code, sortie = _verifier(travail)
        print("── état intact ──")
        print(sortie.rstrip())
        print(f"rc={code}")
        if code != 0:
            print("\nTÉMOIN INAPPLICABLE : le vérificateur échoue déjà sur la copie intacte")
            return 2

        # 1. Un registre déclaré par le script mais absent du disque.
        print("\n── un registre déclaré mais ABSENT du disque ──")
        if "installations.jsonl: OK" in sortie:
            constats.append(
                "installations.jsonl n'existe pas et est rapporté « OK (0 entrees) »"
            )
            print("  installations.jsonl absent -> rapporté OK  ← DÉFAUT")
        else:
            print("  installations.jsonl : plus rapporté OK — ce volet ne se reproduit plus")

        # 2. Suppression d'un registre entier, puis des quatre.
        for nom_etape, a_supprimer in (
            ("un registre de preuves entier", ["preuves.jsonl"]),
            ("TOUS les registres", [c.name for c in registres]),
        ):
            for nom in a_supprimer:
                cible = travail / "registries" / "ledger" / nom
                if cible.exists():
                    cible.unlink()
            code, sortie = _verifier(travail)
            print(f"\n── {nom_etape} supprimé(s) ──")
            print(sortie.rstrip())
            print(f"rc={code}")
            if code == 0:
                constats.append(
                    f"{nom_etape} supprimé(s) : le vérificateur sort 0 et rapporte OK"
                )
                print("  ← DÉFAUT : la disparition des preuves n'est pas détectée")

    print()
    if not constats:
        print("CONSTAT NON REPRODUIT : le vérificateur détecte désormais l'absence.")
        print("AUD-A1-001 est périmé et doit être retiré du rapport.")
        return 0

    print(f"CONSTAT AUD-A1-001 CONFIRMÉ — {len(constats)} manifestation(s) :")
    for constat in constats:
        print(f"  - {constat}")
    print()
    print("Portée : le job CI « gates » est le SEUL check exigé par la protection de la")
    print("branche main, et il exécute ce vérificateur sous le libellé « Ledger integrity")
    print("(D-042) ». Un registre supprimé traverse donc la CI sans être vu.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
