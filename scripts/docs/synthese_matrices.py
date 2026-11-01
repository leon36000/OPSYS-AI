#!/usr/bin/env python3
"""Génère le bloc « matrices » de `docs/utilisation/LIMITES-CONNUES.md` depuis les matrices d'exigences (stdlib, hors ligne).

Sources : `docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M*.json` (M1-M8, M10) et
`docs/reprise/M9-COMPLETION-20261028/MATRICE-EXIGENCES.json` (M9, autre vocabulaire de statuts). Le bloc est délimité
par `<!-- matrices:debut -->` et `<!-- matrices:fin -->` ; `tests/test_coherence_documentaire.py` échoue s'il diffère.

  python scripts/docs/synthese_matrices.py --ecrire | --verifier
"""

# ruff: noqa: E501  (assertions et chaînes de documentation longues, lisibles telles quelles)

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
DOSSIER = RACINE / "docs" / "reprise" / "MATRICES-20261031"
MATRICE_M9 = RACINE / "docs" / "reprise" / "M9-COMPLETION-20261028" / "MATRICE-EXIGENCES.json"
PAGE = RACINE / "docs" / "utilisation" / "LIMITES-CONNUES.md"
DEBUT, FIN = "<!-- matrices:debut -->", "<!-- matrices:fin -->"
MODULES = ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10")
DEPARTEMENTS = {"M1": "Front Office (Léa)", "M2": "Revenue CRM (Victor)", "M3": "Estimation (Mathis)", "M4": "Field Ops (Gabriel)",
                "M5": "FinanceCore (Sophie)", "M6": "Material Control (Rosalie)", "M7": "Marketing (Chloé)",
                "M8": "Analytics (Olivier)", "M9": "Strategic Intelligence (Athéna)", "M10": "Mémoire (Mnémo)"}


def _charger(module: str) -> dict:
    chemin = MATRICE_M9 if module == "M9" else DOSSIER / f"MATRICE-EXIGENCES-{module}.json"
    return json.loads(chemin.read_text(encoding="utf-8"))


def _exigences(donnees: dict) -> list[dict]:
    return donnees.get("requirements") or donnees.get("exigences") or []


def _statut(r: dict) -> str:
    return r.get("current_status") or r.get("status") or r.get("statut") or "?"


def _unique(listes) -> list[str]:
    vus: list[str] = []
    for liste in listes:
        for x in liste or []:
            if isinstance(x, str) and x.strip() and x.strip() not in vus:
                vus.append(x.strip())
    return vus


def _premiere_phrase(texte: str, maximum: int = 260) -> str:
    texte = re.sub(r"\s+", " ", texte or "").strip()
    coupe = re.split(r"(?<=\.)(?<!cf\.)\s+(?=[A-ZÀ-ÝÉ])", texte, maxsplit=1)[0]
    return (coupe[: maximum - 1] + "…") if len(coupe) > maximum else coupe


def donnees_synthese() -> dict[str, dict]:
    sortie = {}
    for module in MODULES:
        d = _charger(module)
        rows = _exigences(d)
        sortie[module] = {
            "total": len(rows),
            "statuts": Counter(_statut(r) for r in rows),
            "non_atteintes": [(r["id"], r.get("title", ""), _statut(r), _premiere_phrase(r.get("limite", ""))) for r in rows
                              if _statut(r) in ("SIMULE", "ABSENT")],
            "decisions": _unique(r.get("decisions_nathan") for r in rows),
            "portes": _unique(r.get("gates_to_resolve_or_keep_open", r.get("gates")) for r in rows),
            "date": d.get("date"),
        }
    return sortie


def _libelle_statuts(c: Counter, module: str) -> str:
    ordre = ("FAIT_PROUVE", "PARTIEL", "SIMULE", "ABSENT", "INCONNU") if module != "M9" else tuple(c)
    return " · ".join(f"{s} {c[s]}" for s in ordre if c[s] or module != "M9" and s in ("FAIT_PROUVE", "PARTIEL", "SIMULE", "ABSENT"))


def bloc() -> str:
    s = donnees_synthese()
    out = [DEBUT, "",
           "*Bloc généré par `scripts/docs/synthese_matrices.py --ecrire` ; ne pas le modifier à la main (un test le compare aux matrices).*", "",
           "### Où en sont les exigences de chaque département", "",
           "| Code | Département | Exigences | Statuts (matrice) |", "|---|---|---:|---|"]
    for m in MODULES:
        out.append(f"| {m} | {DEPARTEMENTS[m]} | {s[m]['total']} | {_libelle_statuts(s[m]['statuts'], m)} |")
    total = sum(s[m]["total"] for m in MODULES if m != "M9")
    fait = sum(s[m]["statuts"]["FAIT_PROUVE"] for m in MODULES if m != "M9")
    out += ["", f"Pour M1 à M8 et M10 : {total} exigences, dont **{fait}** seulement `FAIT_PROUVE`. M9 suit son propre vocabulaire "
            "(`DONE_VERIFIED` = prouvé sur les doubles et les parcours du dépôt, pas en production). "
            "`PARTIEL` veut dire qu'une partie seulement de la cible est prouvée.", "",
            "### Capacités qui n'existent que sous forme de double, ou pas du tout", "",
            "| Exigence | Titre | Statut | Limite (première phrase) |", "|---|---|---|---|"]
    for m in MODULES:
        for ident, titre, statut, limite in s[m]["non_atteintes"]:
            out.append(f"| {ident} | {titre.replace('|', '/')} | {statut} | {limite.replace('|', '/')} |")
    out += ["", "### Décisions que les matrices attendent de Nathan", ""]
    for m in MODULES:
        if s[m]["decisions"]:
            out.append(f"**{m} ({len(s[m]['decisions'])})**")
            out += [f"- {x}" for x in s[m]["decisions"]] + [""]
    out += ["### Portes encore fermées (gates)", ""]
    for m in MODULES:
        if s[m]["portes"]:
            out.append(f"**{m} ({len(s[m]['portes'])})**")
            out += [f"- {x}" for x in s[m]["portes"]] + [""]
    out.append(FIN)
    return "\n".join(out)


def remplacer(texte: str) -> str:
    debut, fin = texte.index(DEBUT), texte.index(FIN) + len(FIN)
    return texte[:debut] + bloc() + texte[fin:]


def main(argv: list[str] | None = None) -> int:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--ecrire", action="store_true")
    g.add_argument("--verifier", action="store_true")
    args = a.parse_args(argv)
    texte = PAGE.read_text(encoding="utf-8")
    nouveau = remplacer(texte)
    if args.ecrire:
        PAGE.write_text(nouveau, encoding="utf-8")
        return 0
    if nouveau != texte:
        print("bloc des matrices périmé : relancer --ecrire", file=sys.stderr)
        return 1
    print("à jour")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
