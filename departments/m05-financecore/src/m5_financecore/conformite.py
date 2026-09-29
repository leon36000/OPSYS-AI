"""Contrôle statique transversal et déterministe du paquet M5.

Ce module analyse exclusivement les arbres syntaxiques Python. `verifier_conformite` couvre CA-M5-15 (échappatoire
D-032 sur les énumérés publics de domaine) et CA-M5-14 (quatre familles d'appels interdits aux sources d'ambiance,
plus les littéraux numériques en contexte de coût ou de taux). `verifier_aucun_import_domaine` couvre CA-M5-16 (aucune
fonction de M5 n'écrit dans le registre d'un autre module — garde structurelle : aucun import, absolu ou depuis, d'un
paquet `mX_*` de domaine). `verifier_aucune_cause_signalee` renforce transversalement CA-M5-18 en interdisant tout
champ de cause ou de responsabilité dans un littéral `dict`. `verifier_arrondi_monetaire_explicite` (PLAN T1.2-d,
préalable arrondi monétaire) interdit tout appel `.quantize(` sans argument `rounding=` explicite : sans lui,
`Decimal.quantize` prend le mode par défaut du module `decimal` (ROUND_HALF_EVEN, « arrondi du banquier ») plutôt que
le ROUND_HALF_UP exigé par la loi pour les taxes (`taxes.py` — Agence du revenu du Canada, Revenu Québec) et par
cohérence avec M3 pour les montants de ligne (`facturation.py`). `verifier_aucun_decaissement` (PLAN T4.15) prouve que
le code des comptes à payer n'écrit jamais au registre des MOUVEMENTS : aucun DECAISSEMENT, aucune PROVISION, aucun
ENCAISSEMENT n'en naît (payer un fournisseur est N5). PLAN T4.16 l'étend au calendrier fiscal et au cash libre : en
STRICT (jamais un mot de mouvement) pour le code qui n'a aucune raison de lire le registre des mouvements, et en
LECTURE SEULE (le registre se lit pour le solde, jamais aucune écriture, aucun paiement, aucune remise) pour le code
qui le lit. Aucune de ces cinq gardes ne prouve l'absence de comportement dynamique, les imports construits à
l'exécution, ni les coûts masqués sous des noms neutres.

Les constantes ``CHAMPS_*`` sont volontairement exclues des énumérés de domaine :
elles décrivent des noms de propriétés de contrat et non des valeurs métier parmi
lesquelles un appelant doit pouvoir exprimer une incertitude.

``CLASSE_RETENTION``, ``PALIER_APPROBATION`` et ``STATUT_APPROBATION`` sont également
exclus (mesuré : le vrai paquet portait ces trois `ENUMERE_SANS_ECHAPPATOIRE` avant
correction). Contrairement à ``TYPE_MOUVEMENT``, ces trois énumérés ne sont jamais une
CLASSIFICATION que M5 déduit d'une entrée ambiguë : ``ClasseRetention`` et
``PalierApprobation`` sont toujours choisis EXPLICITEMENT par l'appelant (PRD §4.2/§4.4,
"caller-spécifié — pas d'échappatoire"), et ``StatutApprobation`` est un état de machine
interne entièrement contrôlé par ``approbation.py``, jamais une valeur externe à classer.
Aucun des trois ne peut donc se retrouver dans un état "je ne sais pas laquelle des
valeurs nommées s'applique" — l'échappatoire D-032 n'a de sens que là où cette
indétermination est réellement possible.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from . import contrats

_PROFONDEUR_RESOLUTION_MAXIMALE = 32

_DEROGATIONS_ECHAPPATOIRE = {
    "TYPE_MOUVEMENT": {
        "echappatoire": "AUTRE",
        "raison": (
            "Un mouvement financier réel et daté dont la nature ne correspond à "
            "aucune catégorie nommée reste néanmoins un mouvement réel (patron "
            "TYPES_TRAVAUX/'autre' de M3)."
        ),
    }
}

PATRON_MODULE_DOMAINE = re.compile(r"^m\d+_")

_AUCUNE_ECHAPPATOIRE_DISPONIBLE = object()

# Caller-spécifiés (PRD §4.2/§4.4) ou machine à états interne — jamais une classification
# que M5 déduit d'une entrée ambiguë, donc aucune échappatoire D-032 n'est requise ici.
_ENUMERES_CALLER_SPECIFIES = frozenset(
    {"CLASSE_RETENTION", "PALIER_APPROBATION", "STATUT_APPROBATION"}
)


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
        morceau
        in {"prix", "cout", "tarif", "montant", "euro", "euros", "taux"}
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
    """Analyse récursivement les sources Python d'un répertoire M5."""
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
                        and module != "m5_financecore"
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
                    and module != "m5_financecore"
                ):
                    violations.append(
                        f"{fichier}: import interdit {noeud.module}"
                    )

    if violations:
        return False, "; ".join(violations)
    return True, ""


def verifier_arrondi_monetaire_explicite(repertoire: str | Path) -> tuple[bool, str]:
    """Vérifie qu'aucun appel `.quantize(` du paquet n'omet `rounding=` (PLAN T1.2-d).

    Sans `rounding=` explicite, `Decimal.quantize` prend le mode par défaut du module `decimal`
    (ROUND_HALF_EVEN, « arrondi du banquier ») au lieu du ROUND_HALF_UP exigé par la loi pour les
    taxes (`taxes.py` — Agence du revenu du Canada, RC4022 ; Revenu Québec, « Calcul des taxes »)
    et par cohérence avec M3 pour les montants de ligne (`facturation.py`). Garde purement
    syntaxique (AST, même patron que `verifier_aucun_import_domaine`) : elle signale tout appel
    dont l'attribut se nomme `quantize`, sans inférer si la cible est un `Decimal` — dans ce
    paquet, seul `Decimal.quantize` porte ce nom (aucun faux positif mesuré,
    `test_verifier_arrondi_monetaire_explicite_du_vrai_paquet`). Elle exige seulement la
    PRÉSENCE du mot-clé `rounding=`, jamais une valeur précise : un mode mal choisi mais explicite
    ne serait pas détecté ici.
    """
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
            if not isinstance(noeud, ast.Call):
                continue
            if not isinstance(noeud.func, ast.Attribute) or noeud.func.attr != "quantize":
                continue
            if any(mot_cle.arg == "rounding" for mot_cle in noeud.keywords):
                continue
            violations.append(f"{fichier}:{noeud.lineno}: quantize() sans rounding= explicite")

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


# PLAN T4.15 : ce que la garde surveille. `None` : le fichier ENTIER ; sinon, ces fonctions seulement (leur absence
# est elle-même une violation : renommer une fonction ne doit pas désarmer la garde en silence). Les fonctions
# d'`outils.py` sont celles du chemin des comptes à payer : consommateur du bus, saisie (avec ou sans PO), correction
# et annulation (T4.15-c : des pièces de plus au registre des comptes à payer, jamais un mouvement), lecture, et
# l'établissement de l'acteur humain. PLAN T4.16 y ajoute, en STRICT, le calendrier fiscal (ni `calendrier_fiscal.py`,
# ni `cash_libre.py`, ni `analyse.py` n'ont de raison de toucher au registre des mouvements : le solde leur est
# apporté déjà calculé) et les fonctions d'`outils.py` qui lisent le calendrier et les registres autres que celui des
# mouvements.
_SURVEILLE_SANS_DECAISSEMENT: dict[str, tuple[str, ...] | None] = {
    "comptes_a_payer": None,
    "calendrier_fiscal": None,
    "cash_libre": None,
    "analyse": None,
    "outils": (
        "_registre_comptes_a_payer",
        "_recevoir_reception_enregistree",
        "_acteur_humain",
        "_horodatage_faisant_foi",
        "_suite_de_la_facture",
        "_reponse_facture",
        "saisir_facture_fournisseur",
        "_categories_depense_sans_po",
        "saisir_facture_sans_po",
        "corriger_facture_fournisseur",
        "annuler_facture_fournisseur",
        "lister_comptes_a_payer",
        "_configuration_manifeste",
        "_calendrier_fiscal",
        "_taxes_par_echeance",
        "lire_echeances_fiscales",
        "_cash_libre",
    ),
}
# PLAN T4.16 : LECTURE SEULE. Le cash libre part du solde : le code qui OUVRE le registre des mouvements pour en tirer
# le solde (`etat_tresorerie` et son adaptateur `_registre_mouvements`, `soldes.py`, `etat_financier.py`) le lit. Lire
# n'est pas écrire : dans ces portées, le registre peut être nommé et lu, mais aucune fonction d'écriture ni de
# transition de l'argent ne peut l'être (voir `_NOMS_ECRITURE_INTERDITS_EN_LECTURE`). `_cash_libre`, lui, reçoit le
# registre déjà ouvert : il est en STRICT, plus haut.
_SURVEILLE_EN_LECTURE_SEULE: dict[str, tuple[str, ...] | None] = {
    "soldes": None,
    "etat_financier": None,
    "outils": ("etat_tresorerie",),
}
# Tout ce qui écrit ou nomme le registre des mouvements : sa fonction d'écriture, son adaptateur et son nom durable
# (« principal »), les types de mouvement et la clé qui les porte.
_NOMS_MOUVEMENTS_INTERDITS = frozenset(
    {"enregistrer_mouvement", "_registre_mouvements", "_etat_mouvements", "_NOM_REGISTRE_MOUVEMENTS"}
)
_TEXTES_MOUVEMENTS_INTERDITS = frozenset(
    {
        "DECAISSEMENT", "ENCAISSEMENT", "PROVISION", "AJUSTEMENT", "mouvement_enregistre", "type_mouvement",
        "principal",
    }
)


# Tout ce qui écrit dans un registre ou fait bouger de l'argent : les fonctions d'écriture des mouvements, des
# paiements, des factures et des réceptions, et les méthodes d'écriture d'un registre (`ajouter`, `append`, `extend`,
# `insert`, la liste interne `_chain`).
_NOMS_ECRITURE_INTERDITS_EN_LECTURE = frozenset(
    {
        "enregistrer_mouvement", "enregistrer_paiement_facture", "marquer_facture_payee", "envoyer_facture",
        "creer_facture_brouillon", "saisir_facture_fournisseur", "enregistrer_reception", "executer_atomique",
        "ajouter", "append", "extend", "insert", "_chain",
    }
)


def _violations_ecriture(portee: ast.AST, fichier: str, contexte: str) -> list[str]:
    violations: list[str] = []
    for noeud in ast.walk(portee):
        ligne = getattr(noeud, "lineno", 0)
        if isinstance(noeud, ast.Name) and noeud.id in _NOMS_ECRITURE_INTERDITS_EN_LECTURE:
            violations.append(f"{fichier}:{ligne}: {contexte} nomme {noeud.id} (écriture ou mouvement d'argent)")
        elif isinstance(noeud, ast.Attribute) and noeud.attr in _NOMS_ECRITURE_INTERDITS_EN_LECTURE:
            violations.append(f"{fichier}:{ligne}: {contexte} nomme {noeud.attr} (écriture ou mouvement d'argent)")
        elif isinstance(noeud, ast.ImportFrom):
            for alias in noeud.names:
                if alias.name in _NOMS_ECRITURE_INTERDITS_EN_LECTURE:
                    violations.append(
                        f"{fichier}:{ligne}: {contexte} importe {alias.name} (écriture ou mouvement d'argent)"
                    )
    return violations


def _violations_decaissement(portee: ast.AST, fichier: str, contexte: str) -> list[str]:
    violations: list[str] = []
    for noeud in ast.walk(portee):
        ligne = getattr(noeud, "lineno", 0)
        if isinstance(noeud, ast.ImportFrom):
            noms = {alias.name for alias in noeud.names}
            if "registre" in noms or (noeud.module or "").split(".")[-1] == "registre":
                violations.append(f"{fichier}:{ligne}: {contexte} importe registre.py (registre des mouvements)")
        elif isinstance(noeud, ast.Import):
            if any(alias.name.split(".")[-1] == "registre" for alias in noeud.names):
                violations.append(f"{fichier}:{ligne}: {contexte} importe registre.py (registre des mouvements)")
        elif isinstance(noeud, ast.Name) and noeud.id in _NOMS_MOUVEMENTS_INTERDITS:
            violations.append(f"{fichier}:{ligne}: {contexte} nomme {noeud.id} (registre des mouvements)")
        elif isinstance(noeud, ast.Attribute) and noeud.attr in _NOMS_MOUVEMENTS_INTERDITS:
            violations.append(f"{fichier}:{ligne}: {contexte} nomme {noeud.attr} (registre des mouvements)")
        elif (
            isinstance(noeud, ast.Constant)
            and isinstance(noeud.value, str)
            and noeud.value in _TEXTES_MOUVEMENTS_INTERDITS
        ):
            violations.append(f"{fichier}:{ligne}: {contexte} porte le texte {noeud.value!r} (mouvement financier)")
    return violations


def _controler_portees(
    racine: Path, cibles: dict[str, tuple[str, ...] | None], controle: Any, violations: list[str]
) -> None:
    for module in sorted(cibles):
        chemin = racine / f"{module}.py"
        try:
            arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
        except (OSError, UnicodeError, SyntaxError) as erreur:
            violations.append(f"{module}.py: module surveillé illisible ({erreur})")
            continue
        fonctions = cibles[module]
        if fonctions is None:
            violations.extend(controle(arbre, f"{module}.py", "le module"))
            continue
        definies = {
            noeud.name: noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for nom in fonctions:
            if nom not in definies:
                violations.append(f"{module}.py: fonction surveillée introuvable : {nom}")
                continue
            violations.extend(controle(definies[nom], f"{module}.py", f"{nom}()"))


def verifier_aucun_decaissement(
    repertoire: str | Path,
    surveille: dict[str, tuple[str, ...] | None] | None = None,
    lecture_seule: dict[str, tuple[str, ...] | None] | None = None,
) -> tuple[bool, str]:
    """Vérifie que le code des comptes à payer, du calendrier fiscal et du cash libre n'écrit jamais au registre des
    mouvements et ne fait jamais bouger d'argent (PLAN T4.15, T4.16).

    Payer un fournisseur, remettre une taxe ou verser une paie est de l'argent réel (N5, Nathan ET le CPA, ADR-0009
    §5) : aucun de ces chemins ne doit créer de DECAISSEMENT, ni de PROVISION ou d'ENCAISSEMENT. Garde purement
    syntaxique (AST, même patron que `verifier_aucun_import_domaine`), en deux régimes :

    STRICT, sur ce que `_SURVEILLE_SANS_DECAISSEMENT` désigne (le module `comptes_a_payer.py` en entier, le calendrier
    fiscal, le cash libre, la mention, et les fonctions d'`outils.py` de ces chemins) : est une violation
    - importer `registre.py` (le module qui écrit les mouvements) ;
    - nommer `enregistrer_mouvement`, l'adaptateur `_registre_mouvements`, `_etat_mouvements`, ou le nom durable du
      registre (`_NOM_REGISTRE_MOUVEMENTS`, le texte « principal ») ;
    - porter le texte d'un type de mouvement (DECAISSEMENT, ENCAISSEMENT, PROVISION, AJUSTEMENT), la clé
      `type_mouvement` ou le type d'entrée `mouvement_enregistre` ;
    - une fonction surveillée qui n'existe plus (la garde ne se désarme pas par un renommage).

    LECTURE SEULE, sur ce que `_SURVEILLE_EN_LECTURE_SEULE` désigne (le solde et sa lecture : `soldes.py`,
    `etat_financier.py` et `etat_tresorerie` d'`outils.py`) : le registre des mouvements peut être lu, mais est une
    violation de nommer une écriture ou un mouvement d'argent (`_NOMS_ECRITURE_INTERDITS_EN_LECTURE` :
    l'enregistrement d'un mouvement, d'un paiement, d'une facture, d'une réception, `ajouter`, `append`, `extend`,
    `insert`, `_chain`), et une fonction surveillée qui n'existe plus l'est aussi.

    Un texte plus long qui MENTIONNE ces mots (un docstring, un commentaire) n'est pas une violation : seule l'égalité
    exacte d'une constante compte. Elle ne prouve pas l'absence d'écriture construite à l'exécution ni passée par un
    autre module ; le test du registre des mouvements inchangé (base réelle) la complète.

    Un appel qui donne `surveille` sans `lecture_seule` ne contrôle que le régime strict (les fichiers d'un test)."""
    racine = Path(repertoire)
    if surveille is None and lecture_seule is None:
        cibles_strictes, cibles_lecture = _SURVEILLE_SANS_DECAISSEMENT, _SURVEILLE_EN_LECTURE_SEULE
    else:
        cibles_strictes = _SURVEILLE_SANS_DECAISSEMENT if surveille is None else surveille
        cibles_lecture = {} if lecture_seule is None else lecture_seule
    violations: list[str] = []
    _controler_portees(racine, cibles_strictes, _violations_decaissement, violations)
    _controler_portees(racine, cibles_lecture, _violations_ecriture, violations)

    if violations:
        return False, "; ".join(violations)
    return True, ""
