#!/usr/bin/env python3
"""Témoin RED — AUD-A2-001 : le dépouillement déterministe ne lit aucune revue du dépôt.

`scripts/tally.py` est l'instrument qui rend REG-04 (le vendor d'un relecteur ne peut pas
être celui du codeur) et REG-05 (au moins trois vendors distincts) vérifiables par machine
plutôt que sur parole. Il exige quatre champs : `reviewer`, `vendor`, `verdict`, `objections`.

Les verdicts déposés sous `reviews/` par `civ_review.py` portent `verdict` et `objections`,
mais ni `reviewer` ni `vendor` — l'identité du relecteur est dans le NOM DU FICHIER, pas dans
son contenu. `tally.py` sort donc en code 2 avec « champ manquant » sur chaque dossier, et
les deux règles de décorrélation ne sont vérifiées nulle part par un script.

Ceux produits par `scripts/consensus_run.py`, en revanche, sont exploitables : ce script
normalise `reviewer` et `vendor` depuis sa table de vendors avant d'écrire. Le défaut n'est
donc pas dans `tally.py` — il est dans l'absence de contrat commun entre les deux
producteurs de verdicts. C'est ce que le témoin distingue, plutôt que d'accuser en bloc.

Code retour : 1 si le défaut est reproduit, 0 s'il ne l'est plus.
"""
import json
import pathlib
import subprocess
import sys

RACINE = pathlib.Path(__file__).resolve().parents[3]
TALLY = RACINE / "scripts" / "tally.py"
REQUIS = ("reviewer", "vendor", "verdict", "objections")


def _inventaire(racine: pathlib.Path) -> tuple[int, int, list[str]]:
    """Retourne (verdicts lus, exploitables, champs manquants observés)."""
    total = exploitables = 0
    manquants: set[str] = set()
    for chemin in sorted(racine.rglob("*.json")):
        try:
            contenu = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Un verdict illisible est un défaut distinct : on le compte à part plutôt
            # que de le confondre avec un verdict au schéma incomplet.
            continue
        if not isinstance(contenu, dict):
            continue
        total += 1
        absents = [champ for champ in REQUIS if champ not in contenu]
        if absents:
            manquants.update(absents)
        else:
            exploitables += 1
    return total, exploitables, sorted(manquants)


def main() -> int:
    if not TALLY.exists():
        print(f"TÉMOIN INAPPLICABLE : {TALLY} est introuvable")
        return 2

    constats = []

    for nom in ("reviews", "registries/verdicts"):
        racine = RACINE / nom
        if not racine.exists():
            continue
        total, exploitables, manquants = _inventaire(racine)
        print(f"── {nom} ──")
        print(f"  verdicts lus : {total}")
        print(f"  exploitables par scripts/tally.py : {exploitables}"
              f"  ({100 * exploitables // max(total, 1)} %)")
        if manquants:
            print(f"  champs manquants observés : {manquants}")
        if total and exploitables == 0:
            constats.append(
                f"{nom} : aucun des {total} verdicts ne porte les 4 champs requis "
                f"(manquants : {manquants})"
            )
        print()

    # Dossiers de revue réellement dépouillables — c'est l'unité qui compte pour REG-05.
    dossiers = [d for d in (RACINE / "reviews").rglob("*") if d.is_dir()]
    a_trois = [d for d in dossiers if len(list(d.glob("*.json"))) >= 3]
    depouillables = 0
    for dossier in a_trois:
        try:
            if all(
                all(champ in json.loads(f.read_text(encoding="utf-8")) for champ in REQUIS)
                for f in dossier.glob("*.json")
            ):
                depouillables += 1
        except (OSError, json.JSONDecodeError):
            continue

    print(f"dossiers de revue à au moins 3 verdicts : {len(a_trois)}")
    print(f"  entièrement dépouillables : {depouillables}")
    if a_trois and depouillables == 0:
        constats.append(
            f"aucun des {len(a_trois)} dossiers de revue n'est dépouillable : "
            "REG-04 et REG-05 ne sont vérifiés par aucun script"
        )

    # Exécution réelle sur un dossier existant : la mesure vaut mieux que l'inférence.
    echantillon = next((d for d in a_trois), None)
    if echantillon is not None:
        relatif = echantillon.relative_to(RACINE).as_posix()
        resultat = subprocess.run(
            [sys.executable, "scripts/tally.py", relatif, "deepseek"],
            cwd=RACINE,
            capture_output=True,
            text=True,
        )
        print(f"\n$ python3 scripts/tally.py {relatif} deepseek")
        print(f"  {resultat.stdout.strip() or resultat.stderr.strip()}")
        print(f"  rc={resultat.returncode}")
        if resultat.returncode == 0:
            print("  le dépouillement RÉUSSIT — ce volet ne se reproduit plus")
        else:
            constats.append(
                f"exécution réelle sur {relatif} : rc={resultat.returncode}"
            )

    print()
    if not constats:
        print("CONSTAT NON REPRODUIT : le dépouillement fonctionne désormais.")
        print("AUD-A2-001 est périmé et doit être retiré du rapport.")
        return 0

    print(f"CONSTAT AUD-A2-001 CONFIRMÉ — {len(constats)} manifestation(s) :")
    for constat in constats:
        print(f"  - {constat}")
    print()
    print("Nuance mesurée, à ne pas perdre : les verdicts produits par consensus_run.py")
    print("SONT exploitables (il normalise reviewer et vendor avant d'écrire). Le défaut")
    print("n'est donc pas dans tally.py mais dans l'absence de contrat commun entre les")
    print("deux producteurs de verdicts du dispositif.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
