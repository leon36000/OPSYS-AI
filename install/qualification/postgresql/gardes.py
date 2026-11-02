#!/usr/bin/env python3
"""Inventaire des gardes « SQLite seulement » du code de production (analyse syntaxique, rien n'est exécuté).

DEUX CHOSES, jamais confondues :

1. Les gardes qui REFUSENT PostgreSQL (`inventaire()`) : un `if` dont la condition compare un nom de moteur à « sqlite »
   avec `!=` ou `not in`, sans que PostgreSQL y soit admis (`cnx.dialect.name != "sqlite"`, `url.get_backend_name() !=
   "sqlite"`…). Elles REFUSENT PostgreSQL de façon typée (fail-closed) : le code qui les suit n'a jamais tourné sur
   PostgreSQL. `inventaire_ancien()` applique la règle EXACTE de la qualification initiale (91 gardes dans 63 fichiers
   au commit `6c6dba4e1`) pour pouvoir comparer avant / après sans changer de règle ; `inventaire()` écarte en plus les
   faux positifs que cette règle comptait (une comparaison de révisions, un `elif` qui suit une branche PostgreSQL, un
   `not in ("sqlite", "postgresql")` qui refuse seulement les AUTRES moteurs).

2. Les gardes PORTÉES (`portees()`) : les endroits où le code admet explicitement les deux moteurs
   (`… not in DIALECTES_QUALIFIES`, `moteur_qualifie(…)`). Ce recensement ne prouve RIEN : une garde n'est comptée
   « portée » que si un test PostgreSQL réel a PASSÉ au-delà de son point de contrôle (`suivi_gardes.py` +
   `matrice.py portage`).

Usage : python3 gardes.py [--json SORTIE.json] [--md SORTIE.md] [--ancien] [--portees]   (depuis la racine du dépôt)
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]

# Gardes qui restent, et pourquoi. Le test `test_banc_postgresql` exige que `inventaire()` soit INCLUS dans ce
# dictionnaire : ajouter une garde « SQLite seulement » sans l'expliquer ici fait échouer la suite (les garde-fous se
# resserrent, jamais l'inverse). Clé : « fichier::fonction ».
#
# Trois gardes subsistent (quatre au départ de la vague 8 : `consolidation_developpement._sqlite_seulement` a été PORTÉE,
# verrou nommé `m10-developpement`, prouvée en vrais processus sur PostgreSQL 17). Ce ne sont pas des défauts de portage
# mais des frontières correctes par construction ; chacune a sa preuve sur un vrai PostgreSQL
# (`JUSTIFICATIONS_TESTEES`, vérifiée par `test_banc_postgresql`) : ce qui est dit à la place, et qu'aucun secret ne fuit.
GARDES_RESTANTES: dict[str, str] = {
    "src/opsys/cles_chiffrement.py::_nettoyer_fichiers_courants": (
        "réécriture des pages d'un FICHIER SQLite (VACUUM, WAL) : sans objet pour PostgreSQL (le nettoyage physique "
        "d'un serveur n'est pas une opération de l'application) ; la clé y est détruite logiquement et l'effacement est "
        "inscrit `non_qualifie`, jamais « terminé »"),
    "src/opsys/exportation.py::_base_sqlite": (
        "exporte le fichier SQLite de l'instance ; PostgreSQL se sauvegarde par `deploy/backup.sh` (pg_dump), éprouvé "
        "sur PostgreSQL réel"),
    "src/opsys/openclaw.py::configuration_cron_memoire_developpement": (
        "la déclaration du cron place l'URL de la base dans l'environnement d'une commande de la Gateway : sur "
        "PostgreSQL, ce serait un mot de passe en clair dans la configuration d'un autre produit (pas de coffre pour "
        "cette frontière)"),
}

# Pour chaque garde restante : les tests, sur un VRAI PostgreSQL, qui prouvent qu'elle est correcte par construction.
# `test_banc_postgresql` vérifie que chaque test nommé existe.
JUSTIFICATIONS_TESTEES: dict[str, tuple[str, ...]] = {
    "src/opsys/cles_chiffrement.py::_nettoyer_fichiers_courants": (
        "tests/test_postgresql_gardes_justifiees.py::test_effacement_de_cle_sur_postgresql_detruit_logiquement_et_dit_non_qualifie",
        "tests/test_postgresql_gardes_justifiees.py::test_le_nettoyage_de_fichiers_refuse_un_moteur_postgresql_sans_rien_toucher",
        "tests/test_postgresql_gardes_justifiees.py::test_la_reprise_ne_boucle_pas_sur_postgresql_aucun_effacement_n_attend"),
    "src/opsys/exportation.py::_base_sqlite": (
        "tests/test_postgresql_gardes_justifiees.py::test_l_export_du_fichier_sqlite_est_refuse_sur_postgresql_avec_la_voie_pg_dump",
        "tests/test_postgresql_gardes_justifiees.py::test_la_voie_proposee_existe_et_est_un_vrai_pg_dump"),
    "src/opsys/openclaw.py::configuration_cron_memoire_developpement": (
        "tests/test_postgresql_gardes_justifiees.py::test_la_declaration_du_cron_m10_refuse_postgresql_sans_divulguer_l_url_ni_le_mot_de_passe",),
}

_FILTRE_NOM = re.compile(r"dialect|backend|dialecte|moteur|\.name\b")


def _est_comparaison_dialecte(noeud: ast.Compare) -> bool:
    return bool(_FILTRE_NOM.search(ast.unparse(noeud.left)))


def _comparaison_sqlite(noeud: ast.AST, *, affinee: bool) -> str | None:
    if not isinstance(noeud, ast.Compare):
        return None
    source = ast.unparse(noeud)
    if "sqlite" not in source or not any(isinstance(o, (ast.NotEq, ast.NotIn)) for o in noeud.ops):
        return None
    if affinee:
        if not _est_comparaison_dialecte(noeud):
            return None  # `revision_sqlite != revision` compare des révisions, pas un moteur
        if "postgresql" in source:
            return None  # `not in ("sqlite", "postgresql")` : seuls les AUTRES moteurs sont refusés
    return source


def _porte_postgresql(test: ast.AST) -> bool:
    return "postgresql" in ast.unparse(test)


class _Visiteur(ast.NodeVisitor):
    def __init__(self, fichier: Path, affinee: bool) -> None:
        self.fichier = fichier
        self.affinee = affinee
        self.pile: list[str] = []
        self.gardes: list[dict] = []
        self._elif_apres_pg: set[int] = set()

    def visit_FunctionDef(self, noeud: ast.FunctionDef) -> None:
        self.pile.append(noeud.name)
        self.generic_visit(noeud)
        self.pile.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_If(self, noeud: ast.If) -> None:
        if self.affinee and _porte_postgresql(noeud.test):
            # `if … == "postgresql": … elif … != "sqlite": raise` : le `elif` ne refuse que les moteurs inconnus.
            for suite in noeud.orelse:
                if isinstance(suite, ast.If):
                    self._elif_apres_pg.add(id(suite))
        if id(noeud) not in self._elif_apres_pg:
            for sous in ast.walk(noeud.test):
                source = _comparaison_sqlite(sous, affinee=self.affinee)
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


def _fichiers() -> list[Path]:
    fichiers = sorted((RACINE / "src").rglob("*.py")) + sorted(RACINE.glob("departments/*/src/**/*.py"))
    return [f for f in fichiers if "migrations" not in f.parts]


def _inventaire(affinee: bool) -> list[dict]:
    resultat: list[dict] = []
    for fichier in _fichiers():
        try:
            arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        visiteur = _Visiteur(fichier, affinee)
        visiteur.visit(arbre)
        resultat += visiteur.gardes
    return resultat


def inventaire_ancien() -> list[dict]:
    """La règle EXACTE de la qualification initiale (91 gardes dans 63 fichiers au commit `6c6dba4e1`)."""
    return _inventaire(affinee=False)


def inventaire() -> list[dict]:
    """Les gardes qui refusent réellement PostgreSQL aujourd'hui (règle affinée, sans faux positif connu)."""
    return _inventaire(affinee=True)


def cle(garde: dict) -> str:
    return f"{garde['fichier']}::{garde['fonction'].split('.')[-1] or '(module)'}"


# -- gardes portées -------------------------------------------------------------------------------------------------
class _VisiteurPortees(ast.NodeVisitor):
    def __init__(self, fichier: Path) -> None:
        self.fichier = fichier
        self.pile: list[ast.AST] = []
        self.parents: dict[int, ast.AST] = {}
        self.portees: list[dict] = []

    def visit(self, noeud: ast.AST) -> None:  # type: ignore[override]
        for enfant in ast.iter_child_nodes(noeud):
            self.parents[id(enfant)] = noeud
        super().visit(noeud)

    def _fonction(self, noeud: ast.AST) -> ast.AST | None:
        courant = self.parents.get(id(noeud))
        while courant is not None and not isinstance(courant, (ast.FunctionDef, ast.AsyncFunctionDef)):
            courant = self.parents.get(id(courant))
        return courant

    def _instruction(self, noeud: ast.AST) -> ast.AST:
        courant = noeud
        while courant is not None and not isinstance(courant, ast.stmt):
            courant = self.parents.get(id(courant))
        return courant or noeud

    def _passage(self, instruction: ast.AST, fonction: ast.AST | None) -> int | None:
        """Ligne de la première instruction exécutée APRÈS une garde `if … : raise/return` (le point de passage)."""
        if not isinstance(instruction, ast.If):
            return None
        parent = self.parents.get(id(instruction))
        for champ in ("body", "orelse", "finalbody", "handlers"):
            suite = getattr(parent, champ, None)
            if isinstance(suite, list) and instruction in suite:
                i = suite.index(instruction)
                if i + 1 < len(suite) and hasattr(suite[i + 1], "lineno"):
                    suivante = suite[i + 1]
                    # `if (` / `while (` sur plusieurs lignes : la ligne `if (` n'a aucune instruction machine, le
                    # suivi (`sys.monitoring`) ne voit jamais d'événement dessus ; la première ligne qui s'exécute
                    # est celle du début de la condition.
                    if isinstance(suivante, (ast.If, ast.While, ast.Assert)):
                        return suivante.test.lineno
                    return suivante.lineno
        return None

    def _enregistrer(self, noeud: ast.AST, forme: str) -> None:
        fonction = self._fonction(noeud)
        instruction = self._instruction(noeud)
        nom = getattr(fonction, "name", "(module)")
        negative = isinstance(instruction, ast.If) and any(isinstance(n, (ast.Raise, ast.Return))
                                                           for n in ast.walk(ast.Module(body=instruction.body,
                                                                                        type_ignores=[])))
        passage = self._passage(instruction, fonction) if negative else None
        debut = fonction.lineno if fonction is not None else 1
        fin = getattr(fonction, "end_lineno", None) if fonction is not None else None
        self.portees.append({
            "fichier": str(self.fichier.relative_to(RACINE)), "ligne": noeud.lineno, "fonction": nom,
            "forme": forme, "genre": "refus" if negative else "condition",
            "passage": passage, "fonction_debut": debut, "fonction_fin": fin,
            "id": f"{self.fichier.relative_to(RACINE)}::{nom}::{noeud.lineno}",
        })

    def visit_Compare(self, noeud: ast.Compare) -> None:
        if any(isinstance(c, ast.Name) and c.id == "DIALECTES_QUALIFIES" for c in noeud.comparators):
            self._enregistrer(noeud, "dialecte in/not in DIALECTES_QUALIFIES")
        self.generic_visit(noeud)

    def visit_Call(self, noeud: ast.Call) -> None:
        nom = noeud.func.id if isinstance(noeud.func, ast.Name) else getattr(noeud.func, "attr", "")
        if nom == "moteur_qualifie":
            self._enregistrer(noeud, "moteur_qualifie()")
        self.generic_visit(noeud)


def portees() -> list[dict]:
    """Chaque endroit où le code admet SQLite ET PostgreSQL (hors de ce banc et de l'aide `portabilite` elle-même)."""
    resultat: list[dict] = []
    for fichier in _fichiers():
        if fichier.name in {"portabilite.py"}:
            continue
        try:
            arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        visiteur = _VisiteurPortees(fichier)
        visiteur.visit(arbre)
        resultat += visiteur.portees
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
    ap.add_argument("--ancien", action="store_true", help="règle exacte de la qualification initiale (91 au départ)")
    ap.add_argument("--portees", action="store_true", help="recense les gardes portées (preuve : matrice.py portage)")
    a = ap.parse_args()
    if a.portees:
        liste = portees()
        if a.json:
            a.json.write_text(json.dumps(liste, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(liste)} points de contrôle portés dans {len({g['fichier'] for g in liste})} fichiers")
        return 0
    gardes = inventaire_ancien() if a.ancien else inventaire()
    if a.json:
        a.json.write_text(json.dumps(gardes, ensure_ascii=False, indent=1), encoding="utf-8")
    texte = markdown(gardes)
    if a.md:
        a.md.write_text(texte, encoding="utf-8")
    justifiees = sum(1 for g in gardes if cle(g) in JUSTIFICATIONS_TESTEES)
    print(f"{len(gardes)} gardes dans {len({g['fichier'] for g in gardes})} fichiers"
          + (" (règle de la qualification initiale)" if a.ancien
             else f" : {justifiees} correctes par construction et prouvées sur PostgreSQL réel, "
                  f"{len(gardes) - justifiees} sans justification testée"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
