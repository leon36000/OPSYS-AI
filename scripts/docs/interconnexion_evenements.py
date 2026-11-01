#!/usr/bin/env python3
"""Audit exécutable de l'interconnexion des départements par le bus d'événements (stdlib, hors ligne).

Croise le catalogue (`src/opsys/evenements/catalogue/*.json`), les `evenements.publie` / `evenements.consomme` des
`department.yaml` et les `consommateurs()` RÉELS de chaque module, et produit la matrice producteur -> consommateurs.

  python scripts/docs/interconnexion_evenements.py --audit      # écarts bloquants (code de sortie 1 s'il y en a)
  python scripts/docs/interconnexion_evenements.py --matrice    # la matrice en Markdown, sur la sortie standard
  python scripts/docs/interconnexion_evenements.py --ecrire     # remplace le bloc de
  docs/architecture/INTERCONNEXION.md
  python scripts/docs/interconnexion_evenements.py --verifier   # échoue si le bloc de la page est périmé

Le bloc est délimité par `<!-- interconnexion:debut -->` et `<!-- interconnexion:fin -->`. Les types sans consommateur
sont justifiés dans `docs/architecture/evenements-sans-consommateur.json` (raison + date de revue) ; une revue échue
(`a_revoir_avant` passé) est signalée en avertissement, jamais en échec (le test de garde n'a pas d'horloge).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
PAGE = RACINE / "docs" / "architecture" / "INTERCONNEXION.md"
DEBUT, FIN = "<!-- interconnexion:debut -->", "<!-- interconnexion:fin -->"


def _chemins() -> None:
    for chemin in [RACINE / "src", *sorted((RACINE / "departments").glob("*/src"))]:
        if str(chemin) not in sys.path:
            sys.path.insert(0, str(chemin))


def analyse_departements() -> dict:
    _chemins()
    from opsys.departements import charger_departements

    return charger_departements(RACINE / "departments")


def analyse() -> dict:
    _chemins()
    from opsys.evenements import interconnexion

    return interconnexion.analyser(analyse_departements())


def bloc() -> str:
    from opsys.evenements import interconnexion

    a = analyse()
    consommes = sum(1 for ligne in a["matrice"] if ligne["consommateurs"])
    entete = (
        f"{len(a['matrice'])} types au catalogue : {consommes} ont au moins un consommateur réel, "
        f"{len(a['types_sans_consommateur'])} n'en ont pas (chacun avec sa justification datée)."
    )
    lectures = interconnexion.auditer_lectures_croisees(analyse_departements())
    sans_dependance = "; ".join(lectures["sans_dependance"]) or "aucune"
    return "\n".join(
        [
            DEBUT,
            "",
            entete,
            "",
            interconnexion.matrice_markdown(a),
            "",
            "### Lectures croisées déclarées (hors événements)",
            "",
            interconnexion.lectures_markdown(lectures),
            "",
            f"Lectures sans entrée dans `dependances` (volontairement non élargi) : {sans_dependance}.",
            "",
            FIN,
        ]
    )


def remplacer(texte: str) -> str:
    debut, fin = texte.index(DEBUT), texte.index(FIN) + len(FIN)
    return texte[:debut] + bloc() + texte[fin:]


def _revues_echues(a: dict, aujourd_hui: dt.date) -> list[str]:
    return [
        f"{ligne['type']} : revue échue depuis le {ligne['justification']['a_revoir_avant']}"
        for ligne in a["matrice"]
        if ligne["justification"]
        and not ligne["consommateurs"]
        and dt.date.fromisoformat(ligne["justification"]["a_revoir_avant"]) < aujourd_hui
    ]


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    groupe = parseur.add_mutually_exclusive_group(required=True)
    for nom in ("audit", "matrice", "ecrire", "verifier"):
        groupe.add_argument(f"--{nom}", action="store_true")
    args = parseur.parse_args(argv)
    if args.matrice:
        _chemins()
        from opsys.evenements import interconnexion

        print(interconnexion.matrice_markdown(analyse()))
        return 0
    if args.audit:
        _chemins()
        from opsys.evenements import interconnexion

        a = analyse()
        defauts = interconnexion.problemes(a) + interconnexion.problemes_lectures(
            interconnexion.auditer_lectures_croisees(analyse_departements())
        )
        for defaut in defauts:
            print(f"ECART : {defaut}", file=sys.stderr)
        for avertissement in _revues_echues(a, dt.datetime.now(dt.UTC).date()):
            print(f"AVERTISSEMENT : {avertissement}", file=sys.stderr)
        print("interconnexion cohérente" if not defauts else f"{len(defauts)} écart(s)")
        return 1 if defauts else 0
    _chemins()
    texte = PAGE.read_text(encoding="utf-8")
    nouveau = remplacer(texte)
    if args.ecrire:
        PAGE.write_text(nouveau, encoding="utf-8")
        return 0
    if nouveau != texte:
        print("bloc de l'interconnexion périmé : relancer --ecrire", file=sys.stderr)
        return 1
    print("à jour")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
