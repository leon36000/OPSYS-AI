"""Contrôle statique transversal et déterministe du paquet M3.

Ce module analyse exclusivement les arbres syntaxiques Python : il contrôle les
énumérés publics de domaine, les échappatoires explicites, certains appels
interdits aux sources d'ambiance et les littéraux numériques placés dans un
contexte monétaire identifiable. Il ne prouve ni l'absence de comportement
dynamique, ni les imports construits à l'exécution, ni les coûts masqués sous
des noms neutres. Les constantes ``CHAMPS_*`` sont volontairement exclues des
énumérés de domaine : elles décrivent des noms de propriétés de contrat et non
des valeurs métier parmi lesquelles un appelant doit pouvoir exprimer une
incertitude. Leur imposer ``INDETERMINE`` créerait des faux positifs nuisibles.

Les catalogues fermés de codes de rejet sont également distingués des énumérés
de domaine : ils recensent des causes techniques déjà nommées, et non des
issues métier à classifier. Le résolveur d'échappatoires comprend les accès
indexés à une séquence constante avec indice littéral, tout en bornant sa
profondeur afin de conserver un refus fermé face aux expressions inconnues ou
cycliques.

La table ``_DEROGATIONS_ECHAPPATOIRE`` recense les dérogations explicites à
D-032. Ajouter une entrée à cette table est un geste de conception, et non un
ajustement local : chaque dérogation doit exposer la raison pour laquelle son
énuméré ne bloque pas avec l'échappatoire canonique.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from . import contrats

_PROFONDEUR_RESOLUTION_MAXIMALE = 32

_DEROGATIONS_ECHAPPATOIRE = {
    "TYPES_TRAVAUX": {
        "echappatoire": "autre",
        "raison": (
            "Un type de travaux inconnu reste un type de travaux, là où un "
            "niveau de confiance ou un verdict indéterminé doit bloquer."
        ),
    },
}


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
    """Reconnaît structurellement un catalogue fermé de causes de rejet.

    Le critère est explicite : un tel catalogue porte un nom ``CODES_*``, est
    une séquence littérale, et chacune de ses valeurs est un identifiant texte
    préfixé par ``REJ-``. Il ne dépend donc pas du nom d'une constante précise.
    """
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
    """Distingue les valeurs métier des listes structurelles de champs.

    Le contrat de nommage public réserve ``CHAMPS_*`` aux noms de propriétés
    sérialisées. Les autres séquences publiques en majuscules sont examinées :
    elles représentent des vocabulaires fermés de domaine et doivent donc
    prévoir une sortie explicite pour l'incertitude.

    L'échappatoire ``INDETERMINE`` de D-032 existe pour le cas où le système ne
    PEUT PAS classer à l'exécution : il doit alors pouvoir le dire d'un nom et
    BLOQUER, plutôt que d'inventer ou de planter. Ce cas existe pour
    ``NiveauConfiance`` (les photos ne permettent pas de trancher) et pour
    ``VerdictEstimation`` (l'issue métier est indéterminée). Il n'existe PAS
    pour un catalogue de codes de rejet : chaque site de rejet NOMME sa cause,
    il n'y a aucun chemin d'exécution où M3 rejette sans savoir pourquoi. Un
    ``REJ-INDETERMINE`` n'aurait aucun producteur — et ce dépôt compte déjà
    deux valeurs de ``VERDICTS_ESTIMATION`` sans producteur, c'est un défaut
    connu qu'il ne faut pas reproduire. Le refus par exception vise une erreur
    de PROGRAMMATION (un code mal orthographié), pas une lacune de
    classification.

    Si un chemin d'exécution devait un jour rejeter sans cause nommée, cette
    décision ne serait plus valable : le catalogue devrait alors porter une
    échappatoire explicitement produite.
    """
    return (
        nom.isupper()
        and not nom.startswith("_")
        and not nom.startswith("CHAMPS_")
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
        morceau in {"prix", "cout", "tarif", "montant", "euro", "euros"}
        for morceau in morceaux
    )


def _importations(arbre: ast.Module) -> tuple[dict[str, str], dict[str, str]]:
    modules: dict[str, str] = {}
    symboles: dict[str, str] = {}
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                nom_local = alias.asname or alias.name.split(".", 1)[0]
                modules[nom_local] = alias.name
        elif isinstance(noeud, ast.ImportFrom):
            module = noeud.module or ""
            for alias in noeud.names:
                nom_local = alias.asname or alias.name
                if alias.name == "*":
                    continue
                symboles[nom_local] = f"{module}.{alias.name}".strip(".")
                if module:
                    modules[nom_local] = f"{module}.{alias.name}".strip(".")
    return modules, symboles


def _analyser_motifs(arbre: ast.Module, fichier: str) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    modules, symboles = _importations(arbre)

    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Call):
            appele = _attribut_complet(noeud.func)
            if appele is None and isinstance(noeud.func, ast.Name):
                appele = noeud.func.id

            if appele is not None:
                racine = appele.split(".", 1)[0]
                module_racine = modules.get(racine, "")
                symbole = symboles.get(racine, "")

                est_random = (
                    module_racine == "random"
                    or module_racine.startswith("random.")
                    or symbole == "random.Random"
                    or symbole == "random.random"
                )
                if est_random:
                    suffixe = appele.rsplit(".", 1)[-1]
                    if suffixe != "seed" and not noeud.args and not noeud.keywords:
                        violations.append(
                            {
                                "code": "RANDOM_NON_ENSEMENCE",
                                "fichier": fichier,
                                "ligne": noeud.lineno,
                            }
                        )

                est_horloge = (
                    module_racine == "time"
                    or module_racine.startswith("time.")
                    or module_racine == "datetime"
                    or module_racine.startswith("datetime.")
                    or symbole.startswith("datetime.datetime")
                )
                if est_horloge and appele.rsplit(".", 1)[-1] in {
                    "time",
                    "now",
                    "today",
                    "utcnow",
                }:
                    violations.append(
                        {
                            "code": "HORLOGE_INTERNE",
                            "fichier": fichier,
                            "ligne": noeud.lineno,
                        }
                    )

                est_reseau = (
                    module_racine == "socket"
                    or module_racine.startswith("socket.")
                    or module_racine == "urllib"
                    or module_racine.startswith("urllib.")
                    or module_racine == "requests"
                    or module_racine.startswith("requests.")
                    or module_racine == "http"
                    or module_racine.startswith("http.client")
                    or symbole.startswith(
                        ("socket.", "urllib.", "requests.", "http.client.")
                    )
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
                    imports[module][alias.asname or alias.name.split(".", 1)[0]] = alias.name
            elif isinstance(noeud, ast.ImportFrom):
                base = noeud.module or ""
                for alias in noeud.names:
                    if alias.name != "*":
                        imports[module][alias.asname or alias.name] = (
                            f"{base}.{alias.name}".strip(".")
                        )
    return constantes, imports


def _module_existant(nom: str, constantes: dict[str, dict[str, ast.AST]]) -> str | None:
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
        alias = morceaux[0]
        cible_import = imports.get(module, {}).get(alias)
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
        if nom not in constantes.get(module, {}):
            return None, nom, []
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

    if isinstance(expression, ast.Attribute):
        qualifie = _attribut_complet(expression)
        if qualifie is None:
            return None, None, []
        morceaux = qualifie.split(".")
        alias = morceaux[0]
        cible_import = imports.get(module, {}).get(alias)
        if cible_import is None or len(morceaux) < 2:
            return None, qualifie, []
        nom_constante = morceaux[-1]
        nom_module = cible_import
        if cible_import.endswith(f".{nom_constante}"):
            nom_module = cible_import.rsplit(".", 1)[0]
        module_reel = _module_existant(nom_module, constantes)
        if module_reel is None:
            return None, qualifie, []
        if nom_constante not in constantes.get(module_reel, {}):
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
    """Analyse récursivement les sources Python d'un répertoire M3."""
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
                else contrats.VERDICT_INDETERMINE
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

            entree = {
                "nom": nom,
                "fichier": fichier,
                "echappatoire_attendue": echappatoire,
                "echappatoire_trouvee": trouvee,
                "references_resolues": sorted(set(references)),
            }
            enumerees.append(entree)

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
