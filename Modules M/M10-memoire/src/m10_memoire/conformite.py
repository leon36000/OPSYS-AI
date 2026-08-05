"""Contrôle statique transversal et déterministe du paquet M10.

Ce module analyse exclusivement les arbres syntaxiques Python.
`verifier_conformite` couvre l'échappatoire D-032 sur les énumérés publics de
domaine, les quatre familles d'appels interdits aux sources d'ambiance, ainsi
que les littéraux numériques en contexte de coût ou de taux.
Contrairement à M9 qui n'avait aucun énuméré, M10 en possède deux et exige
donc une échappatoire D-032 sur chacun.

`verifier_aucun_import_domaine` interdit les imports absolus d'autres paquets
de domaine ainsi que du paquet `core`.
`verifier_aucune_cause_signalee` interdit les champs de cause ou de
responsabilité dans les littéraux `dict`.
`verifier_aucune_methode_de_mutation` interdit les méthodes de mutation dans
les classes du paquet.

Ces gardes ne prouvent pas l'absence de comportement dynamique, des imports
construits à l'exécution, ni des coûts masqués sous des noms neutres.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from . import contrats

_PROFONDEUR_RESOLUTION_MAXIMALE = 32

_DEROGATIONS_ECHAPPATOIRE = {
    "STATUT_DECISION": {
        "echappatoire": "indetermine",
        "raison": (
            "Le statut d'une décision n'est pas toujours tranché : indetermine EST"
            " l'indétermination explicite (règle 4 de la fiche source M10)."
        ),
    },
    "STATUT_REVISION": {
        "echappatoire": "indetermine",
        "raison": (
            "Une révision peut rester sans arbitrage tranché ; aucune valeur de FUSION"
            " n'existe dans cet énuméré (DA-M10-05)."
        ),
    },
}

PATRON_MODULE_DOMAINE = re.compile(r"^m\d+_")
PAQUET_CORE_INTERDIT = "core"
METHODES_MUTATION_INTERDITES = frozenset(
    {"modifier", "supprimer", "fusionner", "mettre_a_jour"}
)

_AUCUNE_ECHAPPATOIRE_DISPONIBLE = object()
_ENUMERES_CALLER_SPECIFIES = frozenset()


def _chemin_module(racine: Path, chemin: Path) -> str:
    relatif = chemin.relative_to(racine).with_suffix("")
    morceaux = list(relatif.parts)
    if morceaux and morceaux[-1] == "__init__":
        morceaux.pop()
    return ".".join(morceaux)


def _nom_cible(cible: ast.expr) -> str | None:
    if isinstance(cible, ast.Name):
        return cible.id
    if isinstance(cible, ast.Attribute):
        return cible.attr
    return None


def _est_sequence_constante(noeud: ast.AST) -> bool:
    return isinstance(noeud, (ast.Tuple, ast.List, ast.Set))


def _est_catalogue_codes_rejet(nom: str, valeur: ast.AST) -> bool:
    if not nom.startswith("CODES_") or not _est_sequence_constante(valeur):
        return False
    assert isinstance(valeur, (ast.Tuple, ast.List, ast.Set))
    return bool(valeur.elts) and all(
        isinstance(element, ast.Constant)
        and isinstance(element.value, str)
        and element.value.startswith("REJ-")
        for element in valeur.elts
    )


def _est_enumere_domaine(nom: str, valeur: ast.AST) -> bool:
    return (
        nom.isupper()
        and not nom.startswith("_")
        and not nom.startswith("CHAMPS_")
        and nom not in _ENUMERES_CALLER_SPECIFIES
        and not _est_catalogue_codes_rejet(nom, valeur)
        and _est_sequence_constante(valeur)
    )


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
        morceau in {"prix", "cout", "tarif", "montant", "euro", "euros", "taux"}
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


def _construire_tables(
    sources: dict[str, ast.Module],
) -> tuple[dict[str, dict[str, ast.AST]], dict[str, dict[str, str]]]:
    constantes: dict[str, dict[str, ast.AST]] = {}
    imports: dict[str, dict[str, str]] = {}

    for module, arbre in sources.items():
        constantes[module] = {}
        imports[module] = {}
        for noeud in arbre.body:
            if isinstance(noeud, (ast.Assign, ast.AnnAssign)):
                valeur = noeud.value
                cibles = noeud.targets if isinstance(noeud, ast.Assign) else [noeud.target]
                if valeur is not None:
                    for cible in cibles:
                        nom = _nom_cible(cible)
                        if nom is not None:
                            constantes[module][nom] = valeur
            elif isinstance(noeud, ast.Import):
                for alias in noeud.names:
                    imports[module][alias.asname or alias.name.split(".", 1)[0]] = (
                        alias.name
                    )
            elif isinstance(noeud, ast.ImportFrom):
                base = noeud.module or ""
                for alias in noeud.names:
                    if alias.name != "*":
                        imports[module][alias.asname or alias.name] = (
                            f"{base}.{alias.name}".strip(".")
                        )
    return constantes, imports


def _module_existant(
    nom: str,
    constantes: dict[str, dict[str, ast.AST]],
) -> str | None:
    if nom in constantes:
        return nom
    candidats = [
        module
        for module in constantes
        if module.endswith(f".{nom}") or module == nom
    ]
    if len(candidats) == 1:
        return candidats[0]
    return None


def _cible_importee(
    cible: str,
    constantes: dict[str, dict[str, ast.AST]],
) -> tuple[str | None, str | None]:
    morceaux = cible.split(".")
    if len(morceaux) < 2:
        return None, None
    nom_constante = morceaux[-1]
    module_reel = _module_existant(".".join(morceaux[:-1]), constantes)
    return module_reel, nom_constante


def _resoudre_sequence(
    expression: ast.AST,
    module: str,
    constantes: dict[str, dict[str, ast.AST]],
    imports: dict[str, dict[str, str]],
    pile: set[tuple[str, str]],
    profondeur: int,
) -> tuple[list[ast.AST] | None, str | None, list[str]]:
    if profondeur > _PROFONDEUR_RESOLUTION_MAXIMALE:
        return None, ast.unparse(expression), []

    if isinstance(expression, (ast.Tuple, ast.List)):
        return list(expression.elts), None, []

    if isinstance(expression, ast.Name):
        nom = expression.id
        if nom not in constantes.get(module, {}):
            return None, nom, []
        cle = (module, nom)
        if cle in pile:
            return None, nom, []
        return _resoudre_sequence(
            constantes[module][nom],
            module,
            constantes,
            imports,
            pile | {cle},
            profondeur + 1,
        )

    if isinstance(expression, ast.Attribute):
        qualifie = _attribut_complet(expression)
        if qualifie is None:
            return None, None, []
        morceaux = qualifie.split(".")
        cible_import = imports.get(module, {}).get(morceaux[0])
        if cible_import is None or len(morceaux) < 2:
            return None, qualifie, []
        nom_constante = morceaux[-1]
        nom_module = cible_import
        if cible_import.endswith(f".{nom_constante}"):
            nom_module = cible_import.rsplit(".", 1)[0]
        module_reel = _module_existant(nom_module, constantes)
        if module_reel is None or nom_constante not in constantes.get(module_reel, {}):
            return None, qualifie, []
        cle = (module_reel, nom_constante)
        if cle in pile:
            return None, qualifie, []
        elements, inconnu, references = _resoudre_sequence(
            constantes[module_reel][nom_constante],
            module_reel,
            constantes,
            imports,
            pile | {cle},
            profondeur + 1,
        )
        return elements, inconnu, [qualifie] + references

    return None, ast.unparse(expression), []


def _resoudre_valeur(
    expression: ast.AST,
    module: str,
    constantes: dict[str, dict[str, ast.AST]],
    imports: dict[str, dict[str, str]],
    pile: set[tuple[str, str]],
    profondeur: int = 0,
) -> tuple[str | None, str | None, list[str]]:
    if profondeur > _PROFONDEUR_RESOLUTION_MAXIMALE:
        return None, ast.unparse(expression), []

    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return expression.value, None, []

    if isinstance(expression, ast.Name):
        nom = expression.id
        if nom in constantes.get(module, {}):
            cle = (module, nom)
            if cle in pile:
                return None, nom, []
            return _resoudre_valeur(
                constantes[module][nom],
                module,
                constantes,
                imports,
                pile | {cle},
                profondeur + 1,
            )

        cible_import = imports.get(module, {}).get(nom)
        if cible_import is None:
            return None, nom, []
        module_reel, nom_constante = _cible_importee(cible_import, constantes)
        if (
            module_reel is None
            or nom_constante is None
            or nom_constante not in constantes.get(module_reel, {})
        ):
            return None, nom, []
        cle = (module_reel, nom_constante)
        if cle in pile:
            return None, nom, []
        valeur, inconnu, references = _resoudre_valeur(
            constantes[module_reel][nom_constante],
            module_reel,
            constantes,
            imports,
            pile | {cle},
            profondeur + 1,
        )
        return valeur, inconnu, [cible_import] + references

    if isinstance(expression, ast.Attribute):
        qualifie = _attribut_complet(expression)
        if qualifie is None:
            return None, None, []
        morceaux = qualifie.split(".")
        cible_import = imports.get(module, {}).get(morceaux[0])
        if cible_import is None or len(morceaux) < 2:
            return None, qualifie, []
        nom_constante = morceaux[-1]
        nom_module = cible_import
        if cible_import.endswith(f".{nom_constante}"):
            nom_module = cible_import.rsplit(".", 1)[0]
        module_reel = _module_existant(nom_module, constantes)
        if (
            module_reel is None
            or nom_constante not in constantes.get(module_reel, {})
        ):
            return None, qualifie, []
        cle = (module_reel, nom_constante)
        if cle in pile:
            return None, qualifie, []
        valeur, inconnu, references = _resoudre_valeur(
            constantes[module_reel][nom_constante],
            module_reel,
            constantes,
            imports,
            pile | {cle},
            profondeur + 1,
        )
        return valeur, inconnu, [qualifie] + references

    if isinstance(expression, ast.Subscript):
        indice = expression.slice
        if not isinstance(indice, ast.Constant) or type(indice.value) is not int:
            return None, ast.unparse(expression), []
        elements, inconnu, references = _resoudre_sequence(
            expression.value,
            module,
            constantes,
            imports,
            pile,
            profondeur + 1,
        )
        if inconnu is not None or elements is None:
            return None, inconnu or ast.unparse(expression), references
        try:
            element = elements[indice.value]
        except IndexError:
            return None, ast.unparse(expression), references
        valeur, inconnu, references_element = _resoudre_valeur(
            element,
            module,
            constantes,
            imports,
            pile,
            profondeur + 1,
        )
        return valeur, inconnu, references + references_element

    return None, ast.unparse(expression), []


def verifier_conformite(repertoire: str | Path) -> dict[str, Any]:
    """Analyse récursivement les sources Python d'un répertoire M10."""
    racine = Path(repertoire)
    violations: list[dict[str, Any]] = []
    enumerees: list[dict[str, Any]] = []
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

    sources: dict[str, ast.Module] = {}
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
        module = _chemin_module(racine, chemin)
        sources[module] = arbre
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

    constantes, imports = _construire_tables(sources)
    for module in sorted(sources):
        fichier = f"{module.replace('.', '/')}.py"
        for nom, valeur in constantes.get(module, {}).items():
            if not _est_enumere_domaine(nom, valeur):
                continue
            assert isinstance(valeur, (ast.Tuple, ast.List, ast.Set))
            derogation = _DEROGATIONS_ECHAPPATOIRE.get(nom)
            echappatoire = (
                derogation["echappatoire"]
                if derogation is not None
                else getattr(
                    contrats, "VERDICT_INDETERMINE", _AUCUNE_ECHAPPATOIRE_DISPONIBLE
                )
            )
            trouvee: str | None = None
            references: list[str] = []
            inconnues: list[str] = []

            for element in valeur.elts:
                resolue, inconnue, refs = _resoudre_valeur(
                    element,
                    module,
                    constantes,
                    imports,
                    set(),
                )
                references.extend(refs)
                if inconnue is not None:
                    inconnues.append(inconnue)
                if resolue == echappatoire:
                    trouvee = resolue

            enumerees.append(
                {
                    "nom": nom,
                    "enumere": nom,
                    "fichier": fichier,
                    "echappatoire_attendue": echappatoire,
                    "echappatoire_trouvee": trouvee,
                    "references_resolues": sorted(set(references)),
                }
            )

            for inconnue in sorted(set(inconnues)):
                violations.append(
                    {
                        "code": "REFERENCE_ENUMERE_NON_RESOLUE",
                        "enumere": nom,
                        "reference": inconnue,
                        "fichier": fichier,
                    }
                )
            if not inconnues and trouvee != echappatoire:
                violations.append(
                    {
                        "code": "ENUMERE_SANS_ECHAPPATOIRE",
                        "enumere": nom,
                        "fichier": fichier,
                        "echappatoire_attendue": echappatoire,
                    }
                )

    if not enumerees:
        violations.append({"code": "AUCUN_ENUMERE_EXAMINE"})
    if not motifs:
        violations.append({"code": "AUCUN_MOTIF_EXAMINE"})

    violations.sort(
        key=lambda element: (
            element["code"],
            str(element.get("fichier", "")),
            str(element.get("ligne", "")),
            str(element.get("enumere", "")),
        )
    )
    enumerees.sort(key=lambda element: (element["fichier"], element["nom"]))

    return {
        "conforme": not violations,
        "violations": violations,
        "enumerees_examinees": enumerees,
        "motifs_examines": motifs,
        "limites": limites,
    }


def verifier_aucun_import_domaine(repertoire: str | Path) -> tuple[bool, str]:
    """Vérifie l'absence d'import absolu d'un autre module de domaine ou de core."""
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
                        (
                            PATRON_MODULE_DOMAINE.match(module)
                            and module != "m10_memoire"
                        )
                        or module == PAQUET_CORE_INTERDIT
                    ):
                        violations.append(f"{fichier}: import interdit {module}")
            elif (
                isinstance(noeud, ast.ImportFrom)
                and noeud.level == 0
                and noeud.module is not None
            ):
                module = noeud.module.split(".", 1)[0]
                if (
                    (
                        PATRON_MODULE_DOMAINE.match(module)
                        and module != "m10_memoire"
                    )
                    or module == PAQUET_CORE_INTERDIT
                ):
                    violations.append(f"{fichier}: import interdit {noeud.module}")

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


def verifier_aucune_methode_de_mutation(
    repertoire: str | Path,
) -> tuple[bool, str]:
    """Vérifie l'absence de méthodes de mutation interdites dans les classes."""
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
        for classe in ast.walk(arbre):
            if not isinstance(classe, ast.ClassDef):
                continue
            for element in classe.body:
                if (
                    isinstance(element, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and element.name in METHODES_MUTATION_INTERDITES
                ):
                    violations.append(
                        f"{fichier}:{element.lineno}: méthode de mutation "
                        f"{element.name} sur {classe.name}"
                    )

    if violations:
        return False, "; ".join(violations)
    return True, ""
