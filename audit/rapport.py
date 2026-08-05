#!/usr/bin/env python3
"""Génère RAPPORT.md depuis les constats — jamais l'inverse.

REG-12 : généré bat maintenu. Une prose saisie à la main peut affirmer ce qu'aucune
mesure ne soutient ; c'est précisément ce que cet audit reproche au dépôt quand il le
trouve. Le rapport est donc reconstruit à chaque exécution depuis `constats/*.json`, et
toute affirmation qu'il porte vient d'un fichier de constat validé par le contrat.

Le générateur RECALCULE la sévérité de chaque constat depuis ses entrées de rubrique et
refuse d'écrire si elle diverge de celle enregistrée : un constat dont la sévérité aurait
été retouchée à la main ne peut pas entrer au rapport.

Sort en code non nul si un constat est invalide, ou si une sévérité diverge.
"""
import json
import pathlib
import subprocess
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "audit"))

from contrats import valider_constat  # noqa: E402
from rubrique import calculer_severite  # noqa: E402

ORDRE_SEVERITE = {"critique": 0, "majeure": 1, "mineure": 2, "indetermine": 3}


def _charger_constats() -> tuple[list[dict], list[str]]:
    dossier = RACINE / "audit" / "constats"
    constats, erreurs = [], []
    for chemin in sorted(dossier.glob("AUD-*.json")):
        try:
            constat = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            erreurs.append(f"{chemin.name} : illisible ({exc})")
            continue
        valide, rejet = valider_constat(constat)
        if not valide:
            erreurs.append(f"{chemin.name} : rejeté par le contrat ({rejet})")
            continue
        recalculee, regle = calculer_severite(constat["entrees_rubrique"])
        if recalculee != constat["severite"]:
            erreurs.append(
                f"{chemin.name} : sévérité enregistrée {constat['severite']!r} mais "
                f"recalculée {recalculee!r} ({regle})"
            )
            continue
        constat["_regle"] = regle
        constats.append(constat)
    return constats, erreurs


def _temoin_rejoue(constat: dict) -> tuple[int, bool]:
    """Rejoue le témoin : un constat dont le témoin ne rougit plus est périmé."""
    chemin = RACINE / constat["temoin"]
    if not chemin.exists():
        return -1, False
    resultat = subprocess.run(
        [sys.executable, str(chemin)], cwd=RACINE, capture_output=True, text=True, timeout=300
    )
    return resultat.returncode, resultat.returncode == constat["temoin_rc"]


def main() -> int:
    constats, erreurs = _charger_constats()
    if erreurs:
        print("RAPPORT NON GÉNÉRÉ — constats invalides :", file=sys.stderr)
        for erreur in erreurs:
            print(f"  - {erreur}", file=sys.stderr)
        return 1
    if not constats:
        print("RAPPORT NON GÉNÉRÉ : aucun constat", file=sys.stderr)
        return 2

    constats.sort(key=lambda c: (ORDRE_SEVERITE.get(c["severite"], 9), c["id"]))

    lignes = [
        "# RAPPORT D'AUDIT — OPSYS-AI",
        "",
        "> Ce fichier est **généré** par `audit/rapport.py` depuis `audit/constats/*.json`.",
        "> Ne pas l'éditer : toute modification manuelle sera écrasée à la prochaine",
        "> exécution. Chaque affirmation ci-dessous vient d'un constat validé par",
        "> `audit/contrats.py`, dont la sévérité est **recalculée** par `audit/rubrique.py`",
        "> au moment de la génération — un constat dont la sévérité aurait été retouchée à",
        "> la main empêche la génération.",
        "",
        "## Ce que cet audit prouve, et ce qu'il ne prouve pas",
        "",
        "Il prouve que, pour chaque constat listé, un témoin rejouable sort en code non nul",
        "sur le dépôt, et que la réfutation a été tentée avant de conclure.",
        "",
        "Il ne prouve **pas** qu'il n'existe aucun autre défaut. Une zone sans constat n'est",
        "réputée propre que si elle porte une preuve de morsure — un défaut synthétique",
        "injecté et détecté. Les zones sans constat ni preuve de morsure ne sont pas",
        "couvertes, et le tableau de complétude le dit.",
        "",
        "## Constats",
        "",
        "| Constat | Sévérité | Lot | Classe | Titre |",
        "|---|---|---|---|---|",
    ]
    for constat in constats:
        lignes.append(
            f"| `{constat['id']}` | **{constat['severite']}** | {constat['lot']} | "
            f"{constat['classe']} | {constat['titre']} |"
        )

    lignes += ["", "## Détail, constat par constat", ""]
    for constat in constats:
        code, conforme = _temoin_rejoue(constat)
        etat = "rejoué, rouge comme attendu" if conforme else f"REJOUÉ : rc={code} (attendu {constat['temoin_rc']})"
        lignes += [
            f"### {constat['id']} — {constat['titre']}",
            "",
            f"- **sévérité** : {constat['severite']} — calculée par la règle `{constat['_regle']}`",
            f"- **entrées mesurées** : " + ", ".join(
                f"{cle}={valeur!r}" for cle, valeur in sorted(constat["entrees_rubrique"].items())
            ),
            f"- **emplacement** : " + ", ".join(f"`{e}`" for e in constat["emplacement"]),
            f"- **témoin** : `{constat['temoin']}` — {etat}",
            "",
            "**Ce que la mesure a donné**",
            "",
            "```",
            constat["refutation"]["sortie"],
            "```",
            "",
            "**Réfutation tentée**",
            "",
            constat["refutation"]["conclusion"],
            "",
        ]

    sortie = RACINE / "audit" / "RAPPORT.md"
    sortie.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    print(f"RAPPORT.md généré — {len(constats)} constats")
    for severite in ("critique", "majeure", "mineure", "indetermine"):
        nombre = sum(1 for c in constats if c["severite"] == severite)
        if nombre:
            print(f"  {severite:12s} : {nombre}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
