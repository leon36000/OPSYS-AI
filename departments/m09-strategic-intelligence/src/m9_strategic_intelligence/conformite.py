"""Contrôles statiques transversaux du paquet M9.

Ce module analyse les AST Python pour vérifier les littéraux de coût codés en
dur et trois familles d'appels interdits via ``verifier_conformite``, l'absence
d'import de domaine via ``verifier_aucun_import_domaine``, ainsi que l'absence
de champ de cause ou de responsable via ``verifier_aucune_cause_signalee``.

Contrairement aux modules M3, M5, M6 et M8, ``verifier_conformite`` n'examine
aucun énuméré fermé : DA-M9-02 précise que M9 v1 ne possède aucune
classification de domaine, et en fabriquer une produirait des faux négatifs.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

PATRON_MODULE_DOMAINE = re.compile(r"^m\d+_")


def _nom_cible(cible: ast.expr) -> str | None:
    if isinstance(cible, ast.Name):
        return cible.id
    if isinstance(cible, ast.Attribute):
        return cible.attr
    return None


def _attribut_complet(noeud: ast.AST) -> str | None:
    morceaux: list[str] = []
    courant = noeud
    while isinstance(courant, ast.Attribute):
        morceaux.append(courant.attr)
        courant = courant.value
    if isinstance(courant, ast.Name):
        morceaux.append(courant.id)
        return ".".join(reversed(morceaux))
    return None


def _est_nombre(noeud: ast.AST) -> bool:
    return isinstance(noeud, ast.Constant) and type(noeud.value) in (int, float)


def _contexte_monetaire(nom: str) -> bool:
    morceaux = nom.lower().split("_")
    return any(
        morceau in {"prix", "cout", "tarif", "montant", "euro", "euros"}
        for morceau in morceaux
    )


def _importations(arbre: ast.Module) -> tuple[dict[str, str], dict[str, str]]:
    modules: dict[str, str] = {}
    symboles: dict[str, str] = {}

    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                if alias.asname:
                    modules[alias.asname] = alias.name
                else:
                    modules[alias.name.split(".", 1)[0]] = alias.name.split(".", 1)[0]
        elif isinstance(noeud, ast.ImportFrom):
            module = noeud.module or ""
            for alias in noeud.names:
                if alias.name == "*":
                    continue
                nom_local = alias.asname or alias.name
                cible = f"{module}.{alias.name}".strip(".")
                symboles[nom_local] = cible
                modules[nom_local] = cible

    return modules, symboles


def _origine_appelee(
    noeud: ast.Call,
    modules: dict[str, str],
    symboles: dict[str, str],
) -> str | None:
    if isinstance(noeud.func, ast.Name):
        nom = noeud.func.id
        return symboles.get(nom) or modules.get(nom)

    appele = _attribut_complet(noeud.func)
    if appele is None:
        return None

    morceaux = appele.split(".")
    origine = modules.get(morceaux[0])
    if origine is None:
        return None
    if len(morceaux) == 1:
        return origine
    return ".".join([origine] + morceaux[1:])


def _argument_graine_fournie(noeud: ast.Call, suffixe: str) -> bool:
    if len(noeud.args) == 1 and not noeud.keywords:
        argument = noeud.args[0]
    elif not noeud.args and len(noeud.keywords) == 1:
        mot_cle = "x" if suffixe == "Random" else "a"
        if noeud.keywords[0].arg != mot_cle:
            return False
        argument = noeud.keywords[0].value
    else:
        return False

    return not (isinstance(argument, ast.Constant) and argument.value is None)


def _analyser_motifs(arbre: ast.Module, fichier: str) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    modules, symboles = _importations(arbre)

    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Call):
            origine = _origine_appelee(noeud, modules, symboles)
            if origine is None:
                continue

            suffixe = origine.rsplit(".", 1)[-1]
            est_random = origine == "random" or origine.startswith("random.")
            if est_random and suffixe in {"Random", "seed"}:
                if not _argument_graine_fournie(noeud, suffixe):
                    violations.append(
                        {
                            "code": "RANDOM_NON_ENSEMENCE",
                            "fichier": fichier,
                            "ligne": noeud.lineno,
                        }
                    )
            elif est_random and suffixe not in {"getstate", "setstate"}:
                violations.append(
                    {
                        "code": "RANDOM_NON_ENSEMENCE",
                        "fichier": fichier,
                        "ligne": noeud.lineno,
                    }
                )

            est_alea_systeme = (
                origine == "uuid"
                or origine.startswith("uuid.")
                or origine == "secrets"
                or origine.startswith("secrets.")
                or origine in {"os.urandom", "os.getrandom"}
            )
            if est_alea_systeme:
                violations.append(
                    {
                        "code": "ALEA_SYSTEME_INTERDIT",
                        "fichier": fichier,
                        "ligne": noeud.lineno,
                    }
                )

            est_horloge = (
                origine == "time"
                or origine.startswith("time.")
                or origine == "datetime"
                or origine.startswith("datetime.")
            )
            if est_horloge and suffixe in {
                "time",
                "time_ns",
                "now",
                "today",
                "utcnow",
                "monotonic",
                "monotonic_ns",
                "perf_counter",
                "perf_counter_ns",
                "process_time",
                "localtime",
                "gmtime",
                "ctime",
                "thread_time",
                "asctime",
                "strftime",
            }:
                violations.append(
                    {
                        "code": "HORLOGE_INTERNE",
                        "fichier": fichier,
                        "ligne": noeud.lineno,
                    }
                )

            est_reseau = (
                origine == "socket"
                or origine.startswith("socket.")
                or origine == "urllib"
                or origine.startswith("urllib.")
                or origine == "requests"
                or origine.startswith("requests.")
                or origine == "http"
                or origine.startswith("http.client.")
            )
            if est_reseau:
                violations.append(
                    {
                        "code": "RESEAU_INTERDIT",
                        "fichier": fichier,
                        "ligne": noeud.lineno,
                    }
                )

        if isinstance(noeud, (ast.Assign, ast.AnnAssign)):
            valeur = noeud.value
            if valeur is None or not _est_nombre(valeur):
                continue
            cibles = noeud.targets if isinstance(noeud, ast.Assign) else [noeud.target]
            for cible in cibles:
                nom = _nom_cible(cible)
                if nom is not None and _contexte_monetaire(nom):
                    violations.append(
                        {
                            "code": "LITTERAL_COUT_INTERDIT",
                            "fichier": fichier,
                            "ligne": noeud.lineno,
                            "contexte": nom,
                        }
                    )
    return violations


def verifier_conformite(repertoire: str | Path) -> dict[str, Any]:
    """Analyse récursivement les sources Python d'un répertoire M9."""
    racine = Path(repertoire)
    violations: list[dict[str, Any]] = []
    motifs: list[dict[str, str]] = []
    limites = [
        {
            "code": "LIMITE_DETECTION_COUT_CONTEXTUELLE",
            "detail": (
                "Un littéral numérique n'est signalé comme coût que lorsqu'un "
                "nom de cible monétaire explicite permet de l'identifier."
            ),
        }
    ]

    try:
        fichiers = sorted(
            chemin for chemin in racine.rglob("*.py") if chemin.is_file()
        )
    except OSError:
        fichiers = []

    if not fichiers:
        violations.append({"code": "AUCUN_FICHIER_ANALYSE"})

    for chemin in fichiers:
        fichier = chemin.relative_to(racine).as_posix()
        try:
            texte = chemin.read_text(encoding="utf-8")
            arbre = ast.parse(texte, filename=str(chemin))
        except (OSError, UnicodeError, SyntaxError) as erreur:
            violations.append(
                {
                    "code": "SOURCE_NON_ANALYSABLE",
                    "fichier": fichier,
                    "detail": str(erreur),
                }
            )
            continue
        motifs.extend(
            {"fichier": fichier, "famille": famille}
            for famille in (
                "RANDOM_NON_ENSEMENCE",
                "ALEA_SYSTEME_INTERDIT",
                "HORLOGE_INTERNE",
                "RESEAU_INTERDIT",
            )
        )
        violations.extend(_analyser_motifs(arbre, fichier))

    if not motifs:
        violations.append({"code": "AUCUN_MOTIF_EXAMINE"})

    violations.sort(
        key=lambda element: (
            element["code"],
            str(element.get("fichier", "")),
            str(element.get("ligne", "")),
        )
    )

    return {
        "conforme": not violations,
        "violations": violations,
        "motifs_examines": motifs,
        "limites": limites,
    }


def verifier_aucun_import_domaine(repertoire: str | Path) -> tuple[bool, str]:
    """Vérifie l'absence d'import absolu d'un autre module de domaine."""
    racine = Path(repertoire)
    violations: list[str] = []

    try:
        fichiers = sorted(
            chemin for chemin in racine.rglob("*.py") if chemin.is_file()
        )
    except OSError:
        fichiers = []

    for chemin in fichiers:
        try:
            arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
        except (OSError, UnicodeError, SyntaxError):
            continue

        fichier = chemin.relative_to(racine).as_posix()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                for alias in noeud.names:
                    module = alias.name.split(".", 1)[0]
                    if (
                        PATRON_MODULE_DOMAINE.match(module)
                        and module != "m9_strategic_intelligence"
                    ):
                        violations.append(f"{fichier}: import interdit {module}")
            elif (
                isinstance(noeud, ast.ImportFrom)
                and noeud.level == 0
                and noeud.module is not None
            ):
                module = noeud.module.split(".", 1)[0]
                if (
                    PATRON_MODULE_DOMAINE.match(module)
                    and module != "m9_strategic_intelligence"
                ):
                    violations.append(
                        f"{fichier}: import interdit {noeud.module}"
                    )

    if violations:
        return False, "; ".join(violations)
    return True, ""


def verifier_aucune_cause_signalee(repertoire: str | Path) -> tuple[bool, str]:
    """Vérifie qu'aucune cause ou responsabilité n'est signalée."""
    racine = Path(repertoire)
    violations: list[str] = []
    cles_interdites = {"cause", "responsable", "raison_signalee"}

    try:
        fichiers = sorted(
            chemin for chemin in racine.rglob("*.py") if chemin.is_file()
        )
    except OSError:
        fichiers = []

    for chemin in fichiers:
        try:
            arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
        except (OSError, UnicodeError, SyntaxError):
            continue

        fichier = chemin.relative_to(racine).as_posix()
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Dict):
                continue
            for cle in noeud.keys:
                if (
                    isinstance(cle, ast.Constant)
                    and isinstance(cle.value, str)
                    and cle.value in cles_interdites
                ):
                    violations.append(f"{fichier}: clé interdite {cle.value}")

    if violations:
        return False, "; ".join(violations)
    return True, ""
