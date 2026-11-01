#!/usr/bin/env python3
"""Mutations de SOURCE (côté Python) : chaque correction issue du banc est affaiblie dans le dépôt, la suite
`tests/test_console_navigateur_corrections.py` est rejouée, puis le fichier est RESTAURÉ. Une mutation « survivante » (tests
toujours verts) est un trou des tests.

Usage : mutations_sources.py [--python PYTHON]   (PYTHONPATH/HOME/TMPDIR déjà posés comme pour pytest)
Ne tourne jamais en parallèle d'un parcours navigateur (les deux lisent les mêmes sources).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
CIBLE = "tests/test_console_navigateur_corrections.py"
CONSOLE = "src/opsys/console/"

# (nom, fichier, ancien, nouveau)
MUTATIONS = [
    ("csp-sans-connect-src", "application.py", "CSP_CONNEXION_MEME_ORIGINE = \"connect-src 'self'\"", 'CSP_CONNEXION_MEME_ORIGINE = "img-src \'self\'"'),
    ("csp-connect-src-partout", "application.py", 'if _PAGE_WALLBOARD.search(scope.get("path", ""))', "if True"),
    ("csp-regex-trop-large", "application.py", r'_PAGE_WALLBOARD = re.compile(r"/wallboards/[a-z0-9][a-z0-9-]*$")', r'_PAGE_WALLBOARD = re.compile(r"/wallboards")'),
    ("tables-non-enveloppees", "pages.py", "corps = envelopper_tables(retrograder_titres_niveau_1(contenu))", "corps = retrograder_titres_niveau_1(contenu)"),
    ("tables-doublement-enveloppees", "pages.py", "sortie.append(tableau if deja else f\"{_ENVELOPPE_TABLE}{tableau}</div>\")", "sortie.append(f\"{_ENVELOPPE_TABLE}{tableau}</div>\")"),
    ("second-h1-conserve", "pages.py", "corps = envelopper_tables(retrograder_titres_niveau_1(contenu))", "corps = envelopper_tables(contenu)"),
    ("erreur-en-status", "pages.py", 'role = "alert" if genre == "erreur" else "status"', 'role = "status"'),
    ("lien-evitement-retire", "pages.py", """'</head><body><a class="saut" href="#contenu">Aller au contenu</a>'""", "'</head><body>'"),
    ("cible-evitement-retiree", "pages.py", '<h1 id="contenu" tabindex="-1">', "<h1>"),
    ("navigation-sans-connaissances", "pages.py", '    ("connaissances", "Connaissances"),\n', ""),
    ("navigation-sans-aria-current", "pages.py", """courante = ' aria-current="page"' if cle == courant else \"\"""", 'courante = ""'),
    ("navigation-sans-repere-nav", "pages.py", """return f'<nav aria-label="Plateforme"><p>{liens}</p></nav>'""", "return f'<p>{liens}</p>'"),
    ("erreur-html-pour-les-api", "application.py", 'if "text/html" in request.headers.get("accept", "") and not est_api(request):', 'if "text/html" in request.headers.get("accept", ""):'),
    ("erreur-html-pour-tous", "application.py", 'if "text/html" in request.headers.get("accept", "") and not est_api(request):', "if not est_api(request):"),
    ("detail-non-echappe", "application.py", "pages.page_erreur(titre, texte, prefixe=prefixe)", "f'<html><body>{texte}</body></html>'"),
    ("libelle-anglais-affiche", "application.py", "texte = detail if detail and detail not in standard else _MESSAGES_ERREUR.get(exc.status_code, titre)", "texte = detail or titre"),
    ("pastille-blanc-en-sombre", "ressources.py", "--danger-fond: #3a1618; --sur-danger: #0f1318;", "--danger-fond: #3a1618; --sur-danger: #ffffff;"),
    ("table-defilante-sans-regle", "ressources.py", ".table-defilante { max-width: 100%; overflow-x: auto; }", ".table-defilante { max-width: 100%; }"),
    ("cases-etirees", "ressources.py", 'input[type="checkbox"], input[type="radio"] { width: auto; margin: 0 .4rem 0 0; }', ""),
    ("texte-long-deborde", "ressources.py", "code { overflow-wrap: anywhere; }", ""),
    ("nav-mobile-pleine-hauteur", "ressources.py", "  .entete nav { flex-basis: 100%; }\n", ""),
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--python", default=sys.executable)
    args = p.parse_args()
    survivantes = []
    for nom, fichier, ancien, nouveau in MUTATIONS:
        chemin = RACINE / CONSOLE / fichier
        original = chemin.read_text(encoding="utf-8")
        if ancien not in original:
            print(f"[INVALIDE] {nom} : motif introuvable dans {fichier}")
            survivantes.append(nom + " (invalide)")
            continue
        chemin.write_text(original.replace(ancien, nouveau, 1), encoding="utf-8")
        try:
            r = subprocess.run([args.python, "-m", "pytest", "-p", "no:cacheprovider", "--import-mode=importlib", "-x", "-q", CIBLE],
                               cwd=RACINE, capture_output=True, text=True)
        finally:
            chemin.write_text(original, encoding="utf-8")
        tuee = r.returncode != 0
        print(f"[{'TUÉE ' if tuee else 'SURVIT'}] {nom}")
        if not tuee:
            survivantes.append(nom)
    print(f"{len(MUTATIONS)} mutations, survivantes : {survivantes or 'aucune'}")
    return 1 if survivantes else 0


if __name__ == "__main__":
    raise SystemExit(main())
