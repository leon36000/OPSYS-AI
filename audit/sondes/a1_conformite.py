#!/usr/bin/env python3
"""Sonde factuelle du lot A1 de l'audit de conformité."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shlex
import subprocess
import sys
import tokenize
from io import StringIO
from pathlib import Path
from typing import Any


RACINE = Path(__file__).resolve().parents[2]
EXTENSIONS_SOURCE = {".py", ".pyw"}
EXTENSIONS_TEXTE = {
    ".py",
    ".md",
    ".json",
    ".jsonl",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".txt",
    ".sh",
    ".cfg",
    ".properties",
}
MARQUEURS_LIVRAISON = re.compile(
    r"\b(LIVR[ÉE]|LIVREE|LIVR[ÉE]E|PARTIAL|COMPLETE|COMPLET|"
    r"DELIVERED|DONE|TERMIN[ÉE])\b",
    re.IGNORECASE,
)
# Points d'extension que la bibliothèque standard invite à redéfinir en no-op pour
# faire taire une sortie. La liste est CLOSE et nommée : toute autre méthode au corps
# `pass` reste signalée, fût-elle dans une classe héritant d'une base externe.
METHODES_SILENCE_ATTENDU = frozenset({
    "log_message",      # http.server.BaseHTTPRequestHandler
    "log_request",      # http.server.BaseHTTPRequestHandler
    "log_error",        # http.server.BaseHTTPRequestHandler
    "emit",             # logging.Handler
    "handle_error",     # socketserver.BaseServer
})


MARQUEURS_COMMENTAIRE = re.compile(r"\b(TODO|FIXME)\b", re.IGNORECASE)    # proof:allow — motif de détection de la sonde
PRAGMA_ALLOW = re.compile(r"\bproof:allow\b", re.IGNORECASE)


class ErreurExecution(Exception):
    """Indique que les faits nécessaires à la sonde ne sont pas accessibles."""


class Lecteur:
    """Centralise les ouvertures afin que le périmètre lu soit vérifiable."""

    def __init__(self, racine: Path, anomalies: list[dict[str, str]]) -> None:
        self.racine = racine
        self.anomalies = anomalies
        self.ouverts: list[str] = []
        self._vus: set[str] = set()
        self._cache: dict[str, str | None] = {}

    def relatif(self, chemin: Path) -> str:
        try:
            return chemin.resolve(strict=False).relative_to(self.racine).as_posix()
        except ValueError:
            return str(chemin)

    def _marquer_ouvert(self, chemin: Path) -> str:
        relatif = self.relatif(chemin)
        if relatif not in self._vus:
            self._vus.add(relatif)
            self.ouverts.append(relatif)
        return relatif

    def lire(self, chemin: Path, controle: str) -> str | None:
        relatif = self._marquer_ouvert(chemin)
        if relatif in self._cache:
            return self._cache[relatif]
        try:
            with chemin.open("r", encoding="utf-8") as fichier:
                contenu = fichier.read()
        except (
            FileNotFoundError,
            PermissionError,
            IsADirectoryError,
            OSError,
            UnicodeError,
        ) as erreur:
            ajouter_anomalie(
                self.anomalies,
                controle,
                relatif,
                f"lecture impossible: {erreur}",
                "fichier lisible en UTF-8",
            )
            self._cache[relatif] = None
            return None
        self._cache[relatif] = contenu
        return contenu

    def lire_octets(self, chemin: Path, controle: str) -> bytes | None:
        relatif = self._marquer_ouvert(chemin)
        try:
            with chemin.open("rb") as fichier:
                return fichier.read()
        except (FileNotFoundError, PermissionError, IsADirectoryError, OSError) as erreur:
            ajouter_anomalie(
                self.anomalies,
                controle,
                relatif,
                f"lecture impossible: {erreur}",
                "fichier ouvrable",
            )
            return None


def ajouter_anomalie(
    anomalies: list[dict[str, str]],
    controle: str,
    objet: str,
    constate: str,
    attendu: str,
) -> None:
    anomalies.append(
        {
            "controle": controle,
            "objet": objet,
            "constate": constate,
            "attendu": attendu,
        }
    )


def executer_git(arguments: list[str]) -> str:
    try:
        resultat = subprocess.run(
            ["git", *arguments],
            cwd=RACINE,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as erreur:
        raise ErreurExecution("git indisponible") from erreur
    except subprocess.CalledProcessError as erreur:
        message = erreur.stderr.strip() or erreur.stdout.strip() or str(erreur)
        raise ErreurExecution(
            f"git {' '.join(arguments)} impossible: {message}"
        ) from erreur
    return resultat.stdout


def executer_git_octets(arguments: list[str]) -> bytes:
    try:
        resultat = subprocess.run(
            ["git", *arguments],
            cwd=RACINE,
            check=True,
            capture_output=True,
        )
    except FileNotFoundError as erreur:
        raise ErreurExecution("git indisponible") from erreur
    except subprocess.CalledProcessError as erreur:
        message = (
            erreur.stderr.decode("utf-8", errors="replace").strip()
            or erreur.stdout.decode("utf-8", errors="replace").strip()
            or str(erreur)
        )
        raise ErreurExecution(
            f"git {' '.join(arguments)} impossible: {message}"
        ) from erreur
    return resultat.stdout


def fichiers_suivis_git() -> list[Path]:
    sortie = executer_git_octets(["ls-files", "-z"])
    if sortie and not sortie.endswith(b"\0"):
        raise ErreurExecution("git ls-files -z n'a pas produit une liste NUL-terminée")

    chemins: list[Path] = []
    for element in sortie.split(b"\0"):
        if not element:
            continue
        try:
            relatif = element.decode("utf-8")
        except UnicodeDecodeError as erreur:
            raise ErreurExecution(
                "git ls-files -z contient un chemin non décodable en UTF-8"
            ) from erreur
        chemin = Path(relatif)
        if chemin.is_absolute() or ".." in chemin.parts:
            raise ErreurExecution(f"git ls-files -z a retourné un chemin invalide: {relatif}")
        chemins.append(RACINE / chemin)
    return sorted(chemins, key=lambda chemin: chemin.relative_to(RACINE).as_posix())


def chemins_python(fichiers_suivis: list[Path]) -> list[Path]:
    return [
        chemin
        for chemin in fichiers_suivis
        if chemin.suffix.lower() in EXTENSIONS_SOURCE
    ]


def fichiers_sous(
    fichiers_suivis: list[Path],
    dossier: Path,
    motif: str,
) -> list[Path]:
    prefixe = dossier.relative_to(RACINE).as_posix().rstrip("/") + "/"
    resultat = [
        chemin
        for chemin in fichiers_suivis
        if chemin.relative_to(RACINE).as_posix().startswith(prefixe)
        and chemin.match(motif)
    ]
    return sorted(resultat, key=lambda chemin: chemin.as_posix())


def modules_declares(lecteur: Lecteur, anomalies: list[dict[str, str]]) -> list[str]:
    chemin = RACINE / "scripts" / "structure_lint.py"
    texte = lecteur.lire(chemin, "arborescence")
    if texte is None:
        return []
    try:
        arbre = ast.parse(texte, filename=lecteur.relatif(chemin))
    except SyntaxError as erreur:
        ajouter_anomalie(
            anomalies,
            "arborescence",
            lecteur.relatif(chemin),
            f"syntaxe invalide ligne {erreur.lineno}: {erreur.msg}",
            "liste MODS lisible syntaxiquement",
        )
        return []
    for noeud in arbre.body:
        if isinstance(noeud, ast.Assign) and any(
            isinstance(cible, ast.Name) and cible.id == "MODS"
            for cible in noeud.targets
        ):
            try:
                valeur = ast.literal_eval(noeud.value)
            except (ValueError, TypeError, SyntaxError):
                ajouter_anomalie(
                    anomalies,
                    "arborescence",
                    lecteur.relatif(chemin),
                    "MODS n'est pas une liste littérale de chaînes",
                    "liste MODS littérale",
                )
                return []
            if isinstance(valeur, list) and all(
                isinstance(module, str) for module in valeur
            ):
                return valeur
            ajouter_anomalie(
                anomalies,
                "arborescence",
                lecteur.relatif(chemin),
                "MODS n'est pas une liste de chaînes",
                "liste MODS de chaînes",
            )
            return []
    ajouter_anomalie(
        anomalies,
        "arborescence",
        lecteur.relatif(chemin),
        "variable MODS absente",
        "variable MODS portant les modules déclarés",
    )
    return []


def controler_arborescence(
    lecteur: Lecteur,
    anomalies: list[dict[str, str]],
    fichiers_suivis: list[Path],
) -> tuple[dict[str, Any], list[str]]:
    declares = modules_declares(lecteur, anomalies)
    presents = sorted(
        {
            chemin.relative_to(RACINE).parts[1]
            for chemin in fichiers_suivis
            if len(chemin.relative_to(RACINE).parts) >= 2
            and chemin.relative_to(RACINE).parts[0] == "Modules M"
        }
    )
    absents = sorted(set(declares) - set(presents))
    non_declares = sorted(set(presents) - set(declares))
    for module in absents:
        ajouter_anomalie(
            anomalies,
            "arborescence",
            f"Modules M/{module}",
            "répertoire déclaré absent du disque",
            "répertoire déclaré présent",
        )
    for module in non_declares:
        ajouter_anomalie(
            anomalies,
            "arborescence",
            f"Modules M/{module}",
            "répertoire présent sans déclaration dans MODS",
            "répertoire présent dans MODS",
        )
    return (
        {
            "modules_declares": declares,
            "modules_presents": presents,
            "declares_absents": absents,
            "presents_non_declares": non_declares,
        },
        declares,
    )


def controler_statuts(
    lecteur: Lecteur,
    anomalies: list[dict[str, str]],
    modules: list[str],
    fichiers_suivis: list[Path],
) -> dict[str, Any]:
    mesures_modules: dict[str, Any] = {}
    for module in modules:
        base = RACINE / "Modules M" / module
        readme = base / "README.md"
        texte_readme = lecteur.lire(readme, "statuts_declares_vs_mesures")
        statut: str | None = None
        if texte_readme is not None:
            correspondance = re.search(
                r"^\s*Statut\s*:\s*(.+?)\s*$",
                texte_readme,
                flags=re.IGNORECASE | re.MULTILINE,
            )
            if correspondance is None:
                ajouter_anomalie(
                    anomalies,
                    "statuts_declares_vs_mesures",
                    lecteur.relatif(readme),
                    "ligne de statut absente",
                    "ligne « Statut: ... »",
                )
            else:
                statut = correspondance.group(1)

        sources = fichiers_sous(fichiers_suivis, base / "src", "*.py")
        tests = fichiers_sous(fichiers_suivis, base / "tests", "test_*.py")
        sources_non_vides = 0
        for source in sources:
            contenu = lecteur.lire(source, "statuts_declares_vs_mesures")
            if contenu is not None and contenu.strip():
                sources_non_vides += 1
        for test in tests:
            lecteur.lire(test, "statuts_declares_vs_mesures")

        mesures_modules[module] = {
            "statut_declare": statut,
            "fichiers_source_non_vides": sources_non_vides,
            "fichiers_test": len(tests),
        }
        if statut is not None and MARQUEURS_LIVRAISON.search(statut):
            if sources_non_vides == 0:
                ajouter_anomalie(
                    anomalies,
                    "statuts_declares_vs_mesures",
                    f"Modules M/{module}",
                    f"statut déclaré « {statut} » et 0 fichier source non vide",
                    "au moins 1 fichier source non vide pour un statut indiquant une livraison",
                )
            if len(tests) == 0:
                ajouter_anomalie(
                    anomalies,
                    "statuts_declares_vs_mesures",
                    f"Modules M/{module}",
                    f"statut déclaré « {statut} » et 0 fichier de test",
                    "au moins 1 fichier de test pour un statut indiquant une livraison",
                )
    return {"modules": mesures_modules}


def registres_declares(
    lecteur: Lecteur,
    anomalies: list[dict[str, str]],
) -> list[str]:
    chemin = RACINE / "scripts" / "ledger_append.py"
    texte = lecteur.lire(chemin, "registres_chaine")
    if texte is None:
        return []
    try:
        arbre = ast.parse(texte, filename=lecteur.relatif(chemin))
    except SyntaxError as erreur:
        ajouter_anomalie(
            anomalies,
            "registres_chaine",
            lecteur.relatif(chemin),
            f"syntaxe invalide ligne {erreur.lineno}: {erreur.msg}",
            "dictionnaire FILES lisible syntaxiquement",
        )
        return []

    for noeud in arbre.body:
        valeur: ast.expr | None = None
        if isinstance(noeud, ast.Assign) and any(
            isinstance(cible, ast.Name) and cible.id == "FILES"
            for cible in noeud.targets
        ):
            valeur = noeud.value
        elif (
            isinstance(noeud, ast.AnnAssign)
            and isinstance(noeud.target, ast.Name)
            and noeud.target.id == "FILES"
            and noeud.value is not None
        ):
            valeur = noeud.value
        if valeur is None:
            continue
        try:
            dictionnaire = ast.literal_eval(valeur)
        except (ValueError, TypeError, SyntaxError):
            ajouter_anomalie(
                anomalies,
                "registres_chaine",
                lecteur.relatif(chemin),
                "FILES n'est pas un dictionnaire littéral",
                "dictionnaire FILES littéral de chaînes",
            )
            return []
        if not isinstance(dictionnaire, dict) or not all(
            isinstance(cle, str) and isinstance(nom, str)
            for cle, nom in dictionnaire.items()
        ):
            ajouter_anomalie(
                anomalies,
                "registres_chaine",
                lecteur.relatif(chemin),
                "FILES n'est pas un dictionnaire de chaînes",
                "dictionnaire FILES de chaînes",
            )
            return []
        return sorted(set(dictionnaire.values()))

    ajouter_anomalie(
        anomalies,
        "registres_chaine",
        lecteur.relatif(chemin),
        "variable FILES absente",
        "variable FILES portant les registres attendus",
    )
    return []


def controler_registres(
    lecteur: Lecteur,
    anomalies: list[dict[str, str]],
) -> dict[str, Any]:
    noms = registres_declares(lecteur, anomalies)
    dossier = RACINE / "registries" / "ledger"
    mesures: list[dict[str, Any]] = []

    for nom in noms:
        registre = dossier / nom
        relatif = lecteur.relatif(registre)
        existe = registre.is_file()
        mesure: dict[str, Any] = {
            "chemin": relatif,
            "registre_attendu": nom,
            "present_sur_disque": existe,
            "entrees": 0,
            "chaine_valide": None,
            "verdict": "absent_du_disque",
            "ruptures": [],
        }
        if not existe:
            ajouter_anomalie(
                anomalies,
                "registres_chaine",
                relatif,
                "registre attendu absent du disque",
                "registre attendu présent sur disque",
            )
            mesures.append(mesure)
            continue

        texte = lecteur.lire(registre, "registres_chaine")
        if texte is None:
            mesure["verdict"] = "lecture_impossible"
            mesures.append(mesure)
            continue

        lignes = [ligne for ligne in texte.splitlines() if ligne.strip()]
        mesure["entrees"] = len(lignes)
        if not lignes:
            mesure["chaine_valide"] = True
            mesure["verdict"] = "present_vide"
            ajouter_anomalie(
                anomalies,
                "registres_chaine",
                relatif,
                "registre présent mais vide",
                "registre contenant au moins un maillon",
            )
            mesures.append(mesure)
            continue

        precedent = "GENESIS"
        ruptures: list[dict[str, Any]] = []
        for numero, ligne in enumerate(lignes, start=1):
            try:
                entree = json.loads(ligne)
            except json.JSONDecodeError as erreur:
                ruptures.append(
                    {"ligne": numero, "constate": f"JSON invalide: {erreur.msg}"}
                )
                continue
            if not isinstance(entree, dict):
                ruptures.append({"ligne": numero, "constate": "entrée JSON non objet"})
                continue
            manquants = [
                cle
                for cle in ("hash", "prev_hash", "ts", "type", "payload")
                if cle not in entree
            ]
            if manquants:
                ruptures.append(
                    {
                        "ligne": numero,
                        "constate": f"clés absentes: {', '.join(manquants)}",
                    }
                )
                continue
            canonique = json.dumps(
                {
                    "ts": entree["ts"],
                    "type": entree["type"],
                    "payload": entree["payload"],
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            attendu = hashlib.sha256(
                (precedent + canonique).encode("utf-8")
            ).hexdigest()
            constates: list[str] = []
            if entree["prev_hash"] != precedent:
                constates.append(
                    f"prev_hash={entree['prev_hash']!r}, précédent={precedent!r}"
                )
            if entree["hash"] != attendu:
                constates.append(f"hash={entree['hash']!r}, calculé={attendu!r}")
            if constates:
                ruptures.append({"ligne": numero, "constate": "; ".join(constates)})
            precedent = entree["hash"]

        mesure["ruptures"] = ruptures
        mesure["chaine_valide"] = not ruptures
        mesure["verdict"] = (
            "chaine_valide_non_vide" if not ruptures else "chaine_brisee"
        )
        if ruptures:
            for rupture in ruptures:
                ajouter_anomalie(
                    anomalies,
                    "registres_chaine",
                    f"{relatif}:{rupture['ligne']}",
                    rupture["constate"],
                    "maillon conforme à sha256(prev_hash + encodage_canonique({ts, type, payload}))",
                )
        mesures.append(mesure)

    return {"registres": mesures}


def corps_stub(noeud: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    corps = list(noeud.body)
    if (
        corps
        and isinstance(corps[0], ast.Expr)
        and isinstance(corps[0].value, ast.Constant)
        and isinstance(corps[0].value.value, str)
    ):
        corps = corps[1:]
    if len(corps) != 1:
        return False
    instruction = corps[0]
    if isinstance(instruction, ast.Pass):
        return True
    if (
        isinstance(instruction, ast.Expr)
        and isinstance(instruction.value, ast.Constant)
        and instruction.value.value is Ellipsis
    ):
        return True
    if isinstance(instruction, ast.Raise):
        exception = instruction.exc
        if isinstance(exception, ast.Name):
            return exception.id == "NotImplementedError"    # proof:allow — motif de détection de la sonde
        if isinstance(exception, ast.Call) and isinstance(exception.func, ast.Name):
            return exception.func.id == "NotImplementedError"    # proof:allow — motif de détection de la sonde
    return False


def corps_est_exactement_pass(noeud: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return len(noeud.body) == 1 and isinstance(noeud.body[0], ast.Pass)


def dernier_nom(noeud: ast.expr) -> str | None:
    if isinstance(noeud, ast.Name):
        return noeud.id
    if isinstance(noeud, ast.Attribute):
        return noeud.attr
    return None


def est_decoree_abstractmethod(
    noeud: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    return any(dernier_nom(decorateur) == "abstractmethod" for decorateur in noeud.decorator_list)


def classe_abc_ou_protocol(noeud: ast.ClassDef) -> bool:
    return any(dernier_nom(base) in {"ABC", "Protocol"} for base in noeud.bases)


def base_non_locale(base: ast.expr, classes_locales: set[str]) -> bool:
    if isinstance(base, ast.Name):
        return base.id not in classes_locales
    if isinstance(base, ast.Attribute):
        return True
    if isinstance(base, ast.Subscript):
        return base_non_locale(base.value, classes_locales)
    return False


def parents_ast(arbre: ast.AST) -> dict[ast.AST, ast.AST]:
    resultat: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(arbre):
        for enfant in ast.iter_child_nodes(parent):
            resultat[enfant] = parent
    return resultat


def fonction_imbriquee(
    noeud: ast.FunctionDef | ast.AsyncFunctionDef,
    parents: dict[ast.AST, ast.AST],
) -> bool:
    parent = parents.get(noeud)
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return True
        parent = parents.get(parent)
    return False


def controler_stubs(
    lecteur: Lecteur,
    anomalies: list[dict[str, str]],
    sources: list[Path],
) -> dict[str, Any]:
    stubs: list[str] = []
    commentaires: list[dict[str, Any]] = []

    for chemin in sources:
        relatif = lecteur.relatif(chemin)
        texte = lecteur.lire(chemin, "stubs_et_todo")
        if texte is None:
            continue
        try:
            arbre = ast.parse(texte, filename=relatif)
        except SyntaxError as erreur:
            ajouter_anomalie(
                anomalies,
                "stubs_et_todo",
                f"{relatif}:{erreur.lineno}",
                f"syntaxe invalide: {erreur.msg}",
                "source analysable syntaxiquement",
            )
            continue

        lignes = texte.splitlines()
        parents = parents_ast(arbre)
        classes_locales = {
            noeud.name for noeud in ast.walk(arbre) if isinstance(noeud, ast.ClassDef)
        }
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not corps_stub(noeud):
                continue

            parent = parents.get(noeud)
            classe = parent if isinstance(parent, ast.ClassDef) else None
            instruction = noeud.body[-1]
            ligne_corps = (
                lignes[instruction.lineno - 1]
                if 0 < instruction.lineno <= len(lignes)
                else ""
            )
            exempt = (
                est_decoree_abstractmethod(noeud)
                or fonction_imbriquee(noeud, parents)
                or PRAGMA_ALLOW.search(ligne_corps) is not None
                or (classe is not None and classe_abc_ou_protocol(classe))
            )
            # Cinquième exemption, RESTREINTE après revue. Elle exemptait auparavant
            # toute méthode `pass` d'une classe héritant d'une base non locale — deux
            # relecteurs indépendants ont montré que cela laissait passer un vrai stub :
            #
            #     class GerantCache(BackendDistant):
            #         def fermer(self): pass        <- stub oublié, non signalé
            #
            # Mesuré : la sonde ne le voyait pas. L'exemption porte désormais sur le NOM
            # de la méthode, restreint aux points d'extension que la bibliothèque standard
            # invite explicitement à redéfinir en no-op pour faire taire une sortie. Une
            # règle qui nomme ce qu'elle autorise se relit ; une règle sur l'héritage
            # autorisait tout ce qui hérite.
            if (
                not exempt
                and classe is not None
                and corps_est_exactement_pass(noeud)
                and noeud.name in METHODES_SILENCE_ATTENDU
                and any(
                    base_non_locale(base, classes_locales) for base in classe.bases
                )
            ):
                exempt = True
            if exempt:
                continue

            objet = f"{relatif}:{noeud.lineno}:{noeud.name}"
            stubs.append(objet)
            ajouter_anomalie(
                anomalies,
                "stubs_et_todo",
                objet,
                "corps réduit à une instruction inachevée",
                "corps ne se réduisant ni à pass, ni à ..., ni à NotImplementedError",    # proof:allow — motif de détection de la sonde
            )

        try:
            jetons = tokenize.generate_tokens(StringIO(texte).readline)
            for jeton in jetons:
                if jeton.type == tokenize.COMMENT:
                    marqueur = MARQUEURS_COMMENTAIRE.search(jeton.string)
                    if marqueur is not None:
                        objet = f"{relatif}:{jeton.start[0]}"
                        commentaires.append(
                            {
                                "fichier": relatif,
                                "ligne": jeton.start[0],
                                "marqueur": marqueur.group(1).upper(),
                            }
                        )
                        ajouter_anomalie(
                            anomalies,
                            "stubs_et_todo",
                            objet,
                            f"commentaire contenant {marqueur.group(1).upper()}",
                            "commentaire sans marqueur TODO ni FIXME",    # proof:allow — motif de détection de la sonde
                        )
        except tokenize.TokenError as erreur:
            ajouter_anomalie(
                anomalies,
                "stubs_et_todo",
                relatif,
                f"jetonisation impossible: {erreur}",
                "source jetonisable",
            )
    return {"fonctions_stub": stubs, "commentaires": commentaires}


class RechercheVerification(ast.NodeVisitor):
    """Évite que le contenu d'une fonction imbriquée compte pour son appelant."""

    def __init__(self, racine: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.racine = racine
        self.trouvee = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.racine:
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.racine:
            self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.trouvee = True

    def visit_Raise(self, node: ast.Raise) -> None:
        exception = node.exc
        if isinstance(exception, ast.Name) and exception.id == "AssertionError":
            self.trouvee = True
        elif (
            isinstance(exception, ast.Call)
            and isinstance(exception.func, ast.Name)
            and exception.func.id == "AssertionError"
        ):
            self.trouvee = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        fonction = node.func
        if isinstance(fonction, ast.Attribute):
            if fonction.attr.startswith("assert") or fonction.attr == "subTest":
                self.trouvee = True
            if (
                fonction.attr == "raises"
                and isinstance(fonction.value, ast.Name)
                and fonction.value.id == "pytest"
            ):
                self.trouvee = True
        self.generic_visit(node)


class RechercheAppels(ast.NodeVisitor):
    """Recense les appels sans entrer dans les fonctions imbriquées."""

    def __init__(self, racine: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.racine = racine
        self.appels: list[ast.Call] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.racine:
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.racine:
            self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self.appels.append(node)
        self.generic_visit(node)


def appels_fonction(
    noeud: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.Call]:
    recherche = RechercheAppels(noeud)
    recherche.visit(noeud)
    return recherche.appels


def cible_appel(
    appel: ast.Call,
    fonctions_module: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    methodes: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    nom_classe: str | None,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    if isinstance(appel.func, ast.Name):
        return fonctions_module.get(appel.func.id)
    if not isinstance(appel.func, ast.Attribute):
        return None
    valeur = appel.func.value
    if isinstance(valeur, ast.Name) and valeur.id in {"self", "cls"}:
        return methodes.get(appel.func.attr)
    if (
        isinstance(valeur, ast.Name)
        and nom_classe is not None
        and valeur.id == nom_classe
    ):
        return methodes.get(appel.func.attr)
    return None


# Après correction, tests_sans_assertion signale 0 cas dans
# Modules M/M3-estimation/tests/test_registre.py et 0 cas dans
# Modules M/M10-memoire/tests/test_encodage.py.
def controler_tests_sans_assertion(
    lecteur: Lecteur,
    anomalies: list[dict[str, str]],
    sources: list[Path],
) -> dict[str, Any]:
    tests: list[str] = []
    sans_verification: list[str] = []
    assertions_deleguees: list[str] = []

    for chemin in sources:
        if not chemin.name.startswith("test_"):
            continue
        relatif = lecteur.relatif(chemin)
        texte = lecteur.lire(chemin, "tests_sans_assertion")
        if texte is None:
            continue
        try:
            arbre = ast.parse(texte, filename=relatif)
        except SyntaxError as erreur:
            ajouter_anomalie(
                anomalies,
                "tests_sans_assertion",
                f"{relatif}:{erreur.lineno}",
                f"syntaxe invalide: {erreur.msg}",
                "test analysable syntaxiquement",
            )
            continue

        parents = parents_ast(arbre)
        fonctions_module = {
            noeud.name: noeud
            for noeud in arbre.body
            if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        methodes_classes: dict[
            ast.ClassDef, dict[str, ast.FunctionDef | ast.AsyncFunctionDef]
        ] = {
            classe: {
                methode.name: methode
                for methode in classe.body
                if isinstance(methode, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for classe in arbre.body
            if isinstance(classe, ast.ClassDef)
        }

        for noeud in ast.walk(arbre):
            if not (
                isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef))
                and noeud.name.startswith("test_")
            ):
                continue
            objet = f"{relatif}:{noeud.lineno}:{noeud.name}"
            tests.append(objet)
            recherche = RechercheVerification(noeud)
            recherche.visit(noeud)
            if recherche.trouvee:
                continue

            classe = parents.get(noeud)
            if not isinstance(classe, ast.ClassDef):
                classe = None
            methodes = methodes_classes.get(classe, {}) if classe is not None else {}
            deleguee = False
            # Les appels sont recherchés dans tout le corps du test : un helper peut
            # être appelé après une préparation ou une mutation des données.
            for appel in appels_fonction(noeud):
                cible = cible_appel(
                    appel,
                    fonctions_module,
                    methodes,
                    classe.name if classe is not None else None,
                )
                if cible is None:
                    continue
                recherche_helper = RechercheVerification(cible)
                recherche_helper.visit(cible)
                if recherche_helper.trouvee:
                    deleguee = True
                    break
            if deleguee:
                assertions_deleguees.append(objet)
                continue

            sans_verification.append(objet)
            ajouter_anomalie(
                anomalies,
                "tests_sans_assertion",
                objet,
                "aucun assert, assert*, pytest.raises, self.subTest ou raise AssertionError",
                "au moins une vérification syntaxiquement présente",
            )

    return {
        "fonctions_test": tests,
        "fonctions_sans_verification": sans_verification,
        "nombre_tests_assertion_deleguee": len(assertions_deleguees),
        "tests_assertion_deleguee": assertions_deleguees,
    }


def est_commande_pytest(morceaux: list[str], indice: int) -> bool:
    if indice == 0:
        return True
    return indice >= 1 and morceaux[indice - 1] == "-m"


def chemins_pytest_ci(
    lecteur: Lecteur,
    anomalies: list[dict[str, str]],
) -> list[str]:
    chemin = RACINE / ".github" / "workflows" / "ci.yml"
    relatif = lecteur.relatif(chemin)
    texte = lecteur.lire(chemin, "fichiers_non_collectes")
    if texte is None:
        return []

    chemins: set[str] = set()
    for ligne in texte.splitlines():
        if ligne.lstrip().startswith("#"):
            continue
        correspondance = re.match(r"^\s*run\s*:\s*(.*?)\s*$", ligne)
        if correspondance is None:
            continue
        commande = correspondance.group(1)
        if not commande or commande.startswith("#"):
            continue
        try:
            morceaux = shlex.split(commande)
        except ValueError as erreur:
            ajouter_anomalie(
                anomalies,
                "fichiers_non_collectes",
                relatif,
                f"commande CI impossible à découper: {erreur}",
                "commande pytest interprétable",
            )
            continue

        indices = [
            indice
            for indice, morceau in enumerate(morceaux)
            if morceau == "pytest" and est_commande_pytest(morceaux, indice)
        ]
        if not indices:
            continue

        for morceau in morceaux[indices[0] + 1 :]:
            if morceau.startswith("-"):
                continue
            candidat = Path(morceau)
            if candidat.is_absolute():
                continue
            chemin_candidat = RACINE / candidat
            try:
                chemin_candidat.resolve(strict=False).relative_to(RACINE)
            except ValueError:
                continue
            if chemin_candidat.exists():
                chemins.add(candidat.as_posix())

    return sorted(chemins)


def est_collecte(chemin: Path, chemins_ci: list[str]) -> bool:
    relatif = chemin.relative_to(RACINE).as_posix()
    for chemin_ci in chemins_ci:
        if relatif == chemin_ci or relatif.startswith(chemin_ci.rstrip("/") + "/"):
            return True
    return False


def controler_fichiers_non_collectes(
    lecteur: Lecteur,
    anomalies: list[dict[str, str]],
    sources: list[Path],
) -> dict[str, Any]:
    chemins_ci = chemins_pytest_ci(lecteur, anomalies)
    fichiers_test = [
        chemin
        for chemin in sources
        if chemin.name.startswith("test_") and chemin.suffix == ".py"
    ]
    non_collectes: list[str] = []
    for chemin in fichiers_test:
        relatif = lecteur.relatif(chemin)
        lecteur.lire(chemin, "fichiers_non_collectes")
        if not est_collecte(chemin, chemins_ci):
            non_collectes.append(relatif)
            ajouter_anomalie(
                anomalies,
                "fichiers_non_collectes",
                relatif,
                "fichier test hors des chemins passés à pytest par la CI",
                "fichier situé sous un chemin passé à pytest par la CI",
            )
    return {
        "chemins_pytest_ci": chemins_ci,
        "fichiers_test": [lecteur.relatif(chemin) for chemin in fichiers_test],
        "fichiers_non_collectes": non_collectes,
    }


def produire_resultat() -> dict[str, Any]:
    anomalies: list[dict[str, str]] = []
    lecteur = Lecteur(RACINE, anomalies)
    commit = executer_git(["rev-parse", "HEAD"]).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ErreurExecution("git rev-parse HEAD n'a pas retourné un SHA complet")

    fichiers_suivis = fichiers_suivis_git()
    sources = chemins_python(fichiers_suivis)

    mesures_arborescence, modules = controler_arborescence(
        lecteur, anomalies, fichiers_suivis
    )
    mesures_statuts = controler_statuts(
        lecteur, anomalies, modules, fichiers_suivis
    )
    mesures_registres = controler_registres(lecteur, anomalies)
    mesures_stubs = controler_stubs(lecteur, anomalies, sources)
    mesures_tests = controler_tests_sans_assertion(lecteur, anomalies, sources)
    mesures_collecte = controler_fichiers_non_collectes(lecteur, anomalies, sources)

    perimetre = [
        chemin.relative_to(RACINE).as_posix()
        for chemin in fichiers_suivis
    ]
    for chemin in fichiers_suivis:
        if chemin.suffix.lower() in EXTENSIONS_TEXTE:
            lecteur.lire(chemin, "perimetre")
        else:
            lecteur.lire_octets(chemin, "perimetre")

    ouverts = lecteur.ouverts
    non_ouverts = sorted(set(perimetre) - set(ouverts))
    return {
        "lot": "A1",
        "commit_gele": commit,
        "fichiers_ouverts": ouverts,
        "fichiers_du_perimetre": perimetre,
        "non_ouverts": non_ouverts,
        "mesures": {
            "arborescence": mesures_arborescence,
            "statuts_declares_vs_mesures": mesures_statuts,
            "registres_chaine": mesures_registres,
            "stubs_et_todo": mesures_stubs,
            "tests_sans_assertion": mesures_tests,
            "fichiers_non_collectes": mesures_collecte,
        },
        "anomalies": sorted(
            anomalies,
            key=lambda anomalie: (
                anomalie["controle"],
                anomalie["objet"],
                anomalie["constate"],
                anomalie["attendu"],
            ),
        ),
    }


def main() -> int:
    try:
        resultat = produire_resultat()
    except ErreurExecution as erreur:
        # La raison va sur la sortie d'erreur, jamais dans le JSON : un lecteur qui
        # analyse la sortie standard doit obtenir un document valide, ou rien du tout.
        # Sortir en 2 sans dire pourquoi reproduirait l'échec silencieux que cette
        # sonde est précisément chargée de détecter ailleurs.
        sys.stderr.write(f"SONDE INEXÉCUTABLE : {erreur}\n")
        return 2
    sys.stdout.write(
        json.dumps(resultat, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    return 1 if resultat["anomalies"] else 0


if __name__ == "__main__":
    sys.exit(main())
