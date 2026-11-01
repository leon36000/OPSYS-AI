# ruff: noqa: E501
#!/usr/bin/env python3
"""Rafraîchit les chiffres clés cités dans la documentation à partir du dépôt (après un ajout d'outils, de migrations ou
un nouveau sceau du registre MCP). Les mêmes valeurs sont vérifiées par `tests/test_coherence_documentaire.py` : ce script
évite de les corriger à la main, il ne décide d'aucun chiffre.

    python scripts/docs/rafraichir_chiffres.py            # montre ce qui changerait
    python scripts/docs/rafraichir_chiffres.py --ecrire   # réécrit les fichiers

Sources : le vérificateur de cohérence (`opsys.cli verifier`), le registre MCP scellé, les fichiers de migration, le
chargeur de départements. Le bloc des matrices se régénère avec `scripts/docs/synthese_matrices.py --ecrire`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import coherence_documentaire as C  # noqa: E402


def mesurer() -> dict[str, object]:
    sortie = subprocess.run([sys.executable, "-m", "opsys.cli", "verifier"], capture_output=True, text=True,
                            cwd=RACINE, check=True).stdout.strip().splitlines()[-1]
    outils = int(re.search(r"(\d+) outils,", sortie).group(1))
    appareils = int(re.search(r"\((\d+) outils déclarés", sortie).group(1))
    registre = json.loads((RACINE / "src/opsys/registre_mcp/registre.v1.json").read_text(encoding="utf-8"))
    n_migrations, tete = C.migrations(RACINE)
    from opsys.departements import charger_departements

    par_departement = {d.code: len(d.charger_outils()) for d in charger_departements().values()}
    return {
        "outils": outils, "appareils": appareils, "registre_outils": len(registre["outils"]),
        "registre_revision": registre["revision"], "migrations": n_migrations, "tete": tete,
        "par_departement": par_departement,
    }


def remplacements(m: dict[str, object]) -> dict[str, list[tuple[str, str]]]:
    """`{fichier: [(motif regex, remplacement)]}` ; chaque motif doit trouver au moins une occurrence."""
    return {
        "README.md": [
            (r"(\| Outils \| )\d+( \|)", rf"\g<1>{m['outils']}\2"),
            (r"(\| Tête alembic \| )\d+( \|)", rf"\g<1>{m['tete']}\2"),
            (r"(\| Fichiers de migration \| )\d+( \|)", rf"\g<1>{m['migrations']}\2"),
            (r"(\| Révision du registre MCP \| )\d+( \|)", rf"\g<1>{m['registre_revision']}\2"),
            (r"(\| Outils scellés au registre MCP \| )\d+( \|)", rf"\g<1>{m['registre_outils']}\2"),
        ],
        "docs/architecture/ROLES.md": [
            (r"\d+ outils sur \d+ sont déclarés", f"{m['appareils']} outils sur {m['outils']} sont déclarés"),
        ],
        "docs/utilisation/GLOSSAIRE-ET-FAQ.md": [
            (r"Il y en a \d+\.", f"Il y en a {m['outils']}."),
            (r"\((\d{4}) aujourd'hui\)", f"({m['tete']} aujourd'hui)"),
        ],
        "docs/utilisation/GUIDE-ADMINISTRATION.md": [
            (r"\*\*\d+ outils\*\* y sont scellés \(les \d+ outils",
             f"**{m['registre_outils']} outils** y sont scellés (les {m['outils']} outils"),
        ],
        "docs/utilisation/GUIDE-PROPRIETAIRE.md": [
            (r"\*\*\d+ outils\*\*", f"**{m['outils']} outils**"),
            (r"\*\*\d+\*\* de ces outils", f"**{m['appareils']}** de ces outils"),
        ],
        "docs/architecture/OBSERVABILITE-MCP.md": [
            (r"\d+ à la révision \d+ de la ligne actuelle",
             f"{m['registre_outils']} à la révision {m['registre_revision']} de la ligne actuelle"),
        ],
        "departments/m05-financecore/README.md": [
            (r"\*\*\d+ au 1er novembre 2026\*\*", f"**{m['par_departement']['M5']} au 1er novembre 2026**"),
        ],
    }


def appliquer(m: dict[str, object], ecrire: bool) -> list[str]:
    changes: list[str] = []
    for fichier, motifs in remplacements(m).items():
        chemin = RACINE / fichier
        texte = chemin.read_text(encoding="utf-8")
        nouveau = texte
        for motif, remplacement in motifs:
            nouveau, n = re.subn(motif, remplacement, nouveau)
            if n == 0:
                raise SystemExit(f"{fichier} : motif introuvable {motif!r}")
    # la table des départements du guide du propriétaire
        if fichier == "docs/utilisation/GUIDE-PROPRIETAIRE.md":
            for code, n in m["par_departement"].items():
                nouveau = re.sub(rf"^(\| {code} \| [^|]+ \| [^|]+ \| .* \| )\d+( \|)$", rf"\g<1>{n}\2", nouveau, flags=re.M)
        if nouveau != texte:
            changes.append(fichier)
            if ecrire:
                chemin.write_text(nouveau, encoding="utf-8")
    return changes


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--ecrire", action="store_true")
    args = a.parse_args()
    changes = appliquer(mesurer(), args.ecrire)
    print(("Réécrit : " if args.ecrire else "À réécrire : ") + (", ".join(changes) or "rien"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
