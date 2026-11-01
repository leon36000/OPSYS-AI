#!/usr/bin/env python3
"""Inventaire des gardes « SQLite seulement » du code de production (analyse syntaxique, rien n'est exécuté).

Une garde est un `if` dont la condition compare un nom de moteur à « sqlite » avec `!=` ou `not in`
(`cnx.dialect.name != "sqlite"`, `url.get_backend_name() != "sqlite"`…). Ces gardes REFUSENT PostgreSQL de façon typée
(fail-closed) : le code qui les suit n'a jamais tourné sur PostgreSQL. Le résultat est le recensement de ce qui est
« non porté » ; le rapport `docs/qualification/QUALIFICATION-POSTGRESQL.md` en rend le tableau.

Usage : python3 gardes.py [--json SORTIE.json] [--md SORTIE.md]   (depuis la racine du dépôt)
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]


def _comparaison_sqlite(noeud: ast.AST) -> str | None:
    if not isinstance(noeud, ast.Compare):
        return None
    source = ast.unparse(noeud)
    if "sqlite" in source and any(isinstance(o, (ast.NotEq, ast.NotIn)) for o in noeud.ops):
        return source
    return None


class _Visiteur(ast.NodeVisitor):
    def __init__(self, fichier: Path) -> None:
        self.fichier = fichier
        self.pile: list[str] = []
        self.gardes: list[dict] = []

    def visit_FunctionDef(self, noeud: ast.FunctionDef) -> None:
        self.pile.append(noeud.name)
        self.generic_visit(noeud)
        self.pile.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_If(self, noeud: ast.If) -> None:
        for sous in ast.walk(noeud.test):
            source = _comparaison_sqlite(sous)
            if source:
                effet = ""
                for instruction in ast.walk(ast.Module(body=noeud.body, type_ignores=[])):
                    if isinstance(instruction, ast.Raise) and instruction.exc is not None:
                        effet = ast.unparse(instruction.exc)[:170]
                        break
                    if isinstance(instruction, ast.Return) and instruction.value is not None and not effet:
                        effet = "return " + ast.unparse(instruction.value)[:100]
                self.gardes.append({"fichier": str(self.fichier.relative_to(RACINE)), "ligne": noeud.lineno,
                                    "fonction": ".".join(self.pile), "garde": source[:120], "effet": effet})
                break
        self.generic_visit(noeud)


def inventaire() -> list[dict]:
    fichiers = sorted((RACINE / "src").rglob("*.py")) + sorted(RACINE.glob("departments/*/src/**/*.py"))
    resultat: list[dict] = []
    for fichier in fichiers:
        if "migrations" in fichier.parts:
            continue
        try:
            arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        visiteur = _Visiteur(fichier)
        visiteur.visit(arbre)
        resultat += visiteur.gardes
    return resultat


def markdown(gardes: list[dict]) -> str:
    par_fichier: dict[str, list[dict]] = collections.OrderedDict()
    for g in gardes:
        court = re.sub(r"^departments/(m\d\d)[^/]*/src/", r"\1/", g["fichier"]).removeprefix("src/opsys/")
        par_fichier.setdefault(court, []).append(g)
    lignes = ["| Module | Gardes | Fonction → refus typé |", "|---|---:|---|"]
    for fichier, liste in par_fichier.items():
        effets = []
        for g in liste:
            m = re.search(r"['\"]([A-Z][A-Z0-9_\-]{5,})['\"]", g["effet"])  # code typé en majuscules, s'il y en a un
            refus = m.group(1) if m else (g["effet"][:70] + ("…" if len(g["effet"]) > 70 else "")) or "—"
            effets.append(f"`{g['fonction'].split('.')[-1] or '(module)'}` → {refus}")
        lignes.append(f"| `{fichier}` | {len(liste)} | {'; '.join(dict.fromkeys(effets))} |")
    return "\n".join(lignes) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--md", type=Path)
    a = ap.parse_args()
    gardes = inventaire()
    if a.json:
        a.json.write_text(json.dumps(gardes, ensure_ascii=False, indent=1), encoding="utf-8")
    texte = markdown(gardes)
    if a.md:
        a.md.write_text(texte, encoding="utf-8")
    print(f"{len(gardes)} gardes dans {len({g['fichier'] for g in gardes})} fichiers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
