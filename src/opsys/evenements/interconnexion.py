"""Audit exécutable de l'interconnexion des départements par le bus d'événements.

Croise TROIS sources, sans en croire une seule :

1. le catalogue (`catalogue/*.json`) : les types d'événements qui EXISTENT ;
2. les `evenements.publie` / `evenements.consomme` des `department.yaml` : ce que chaque département DÉCLARE ;
3. les `consommateurs()` réels de chaque module : ce qui sera RÉELLEMENT appelé par `repartir`.

Il en tire une matrice producteur -> consommateurs et quatre familles d'écarts :

- `types_sans_consommateur` : un type du catalogue que personne ne reçoit réellement. Permis seulement avec une
  justification écrite dans `docs/architecture/evenements-sans-consommateur.json` (raison, date de revue) ;
- `declares_sans_handler` : un département déclare consommer un type mais n'a pas de fonction pour lui
  (il croit recevoir, il ne reçoit rien) ;
- `publications_hors_espace` : un `publier(...)` du code d'un département dont le type porte le préfixe d'un autre ;
- `handlers_inertes` : une fonction qui ne référence aucun nom (`lambda charge: {}`) : elle ne compte PAS comme un
  consommateur réel ;
- `handlers_sans_declaration` : une fonction de `consommateurs()` absente de `evenements.consomme`
  (le répartiteur ne l'appelle jamais : du code mort qui se croit branché) ;
- `types_sans_producteur` / `producteurs_sans_trace` : un type consommé que personne ne déclare publier, ou un type
  déclaré publié dont le nom n'apparaît nulle part dans le code du producteur.

Le module ne publie rien, n'écrit rien et ne se connecte à aucune base : il lit des fichiers et importe les modules
des départements (comme `opsys-metier verifier`). Les justifications sont des DONNÉES versionnées, relues à date
fixe, jamais une liste en dur dans un test.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..departements import Departement
from .schemas import types_connus

__all__ = [
    "CHEMIN_JUSTIFICATIONS",
    "CHEMIN_LECTURES",
    "analyser",
    "auditer_lectures_croisees",
    "lectures_markdown",
    "lire_lectures_croisees",
    "problemes_lectures",
    "justifications_invalides",
    "lire_justifications",
    "matrice_markdown",
    "problemes",
]

SCHEMA_JUSTIFICATIONS = "opsys.evenements.sans_consommateur/v1"
CHEMIN_JUSTIFICATIONS = (
    Path(__file__).resolve().parents[3] / "docs" / "architecture" / "evenements-sans-consommateur.json"
)
CHEMIN_LECTURES = Path(__file__).resolve().parents[3] / "docs" / "architecture" / "lectures-croisees.json"
SCHEMA_LECTURES = "opsys.lectures_croisees/v1"
_RACINE_SOCLE = Path(__file__).resolve().parents[1]  # src/opsys
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RAISON_MIN = 40


def lire_justifications(chemin: Path | None = None) -> dict[str, dict[str, Any]]:
    """`{type: {raison, revue_le, a_revoir_avant}}` ; fichier absent ou illisible : refus (fail-closed)."""
    fichier = chemin or CHEMIN_JUSTIFICATIONS
    brut = json.loads(fichier.read_text(encoding="utf-8"))
    if brut.get("schema") != SCHEMA_JUSTIFICATIONS:
        raise ValueError(f"{fichier} : schema attendu {SCHEMA_JUSTIFICATIONS!r}")
    types = brut.get("types")
    if not isinstance(types, dict):
        raise ValueError(f"{fichier} : « types » doit être un objet")
    return types


def justifications_invalides(justifications: Mapping[str, Any], catalogue: frozenset[str]) -> list[str]:
    """Défauts de forme des justifications : type inconnu, raison creuse, date illisible ou revue incohérente."""
    defauts: list[str] = []
    for type_evenement, fiche in sorted(justifications.items()):
        if type_evenement not in catalogue:
            defauts.append(f"{type_evenement} : justification d'un type absent du catalogue")
        if not isinstance(fiche, dict) or set(fiche) != {"raison", "revue_le", "a_revoir_avant"}:
            defauts.append(f"{type_evenement} : la fiche doit porter exactement raison, revue_le, a_revoir_avant")
            continue
        raison = fiche["raison"]
        if not isinstance(raison, str) or len(raison.strip()) < _RAISON_MIN:
            defauts.append(f"{type_evenement} : raison trop courte (< {_RAISON_MIN} caractères) ou absente")
        dates = {}
        for cle in ("revue_le", "a_revoir_avant"):
            valeur = fiche[cle]
            try:
                if not isinstance(valeur, str) or not _DATE.match(valeur):
                    raise ValueError
                dates[cle] = dt.date.fromisoformat(valeur)
            except ValueError:
                defauts.append(f"{type_evenement} : {cle} doit être une date AAAA-MM-JJ")
        if len(dates) == 2 and dates["a_revoir_avant"] <= dates["revue_le"]:
            defauts.append(f"{type_evenement} : a_revoir_avant doit suivre revue_le")
    return defauts


def _trace_dans_le_code(departement: Departement, type_evenement: str) -> bool:
    """Le nom du type apparaît-il dans le code du producteur (son `src/`) ou dans le socle (publications
    transverses, ex. le planificateur des connecteurs) ? Un nom qui n'apparaît nulle part ne peut être publié.

    Le nom COMPLET du type, entre guillemets, compte dans le `src/` du producteur et, dans le socle, seulement dans un
    fichier qui PUBLIE (`publier(`) : le socle nomme aussi les types qu'il consomme ou relit. La forme composée
    (un préfixe suivi de `.suffixe`, point devant le suffixe) ne compte que dans le `src/` du producteur : un suffixe nu
    cherché dans tout le socle y trouve toujours une coïncidence et rendrait l'écart `producteurs_sans_trace` impossible
    à voir."""
    motif = f'"{type_evenement}"'
    motif_simple = f"'{type_evenement}'"
    propre = departement.racine / "src"
    for racine in (propre, _RACINE_SOCLE):
        if not racine.is_dir():
            continue
        for fichier in racine.rglob("*.py"):
            try:
                texte = fichier.read_text(encoding="utf-8")
            except OSError:
                continue
            if (motif in texte or motif_simple in texte) and (racine is propre or "publier(" in texte):
                return True
    # Un module peut composer le nom (`f"{PREFIXE}.suffixe"`) : le suffixe précédé d'un point, dans son propre code.
    suffixe = type_evenement.split(".", 1)[1]
    composee = re.compile(rf"\.{re.escape(suffixe)}[\"']")
    if propre.is_dir():
        for fichier in propre.rglob("*.py"):
            try:
                if composee.search(fichier.read_text(encoding="utf-8")):
                    return True
            except OSError:
                continue
    return False


def _inerte(fonction: Any) -> bool:
    """Un handler qui ne référence AUCUN nom (ni appel, ni attribut, ni variable libre) ne peut rien écrire : c'est le
    consommateur factice (`lambda charge: {}`, `lambda charge: charge`) qui ferait passer l'audit sans rien recevoir.
    Heuristique grossière et dite telle : un handler qui appelle `print` n'est pas vu ; le comportement des handlers
    est prouvé par les tests de chaque consommateur, pas par cet audit."""
    code = getattr(fonction, "__code__", None)  # une méthode liée délègue `__code__` à sa fonction
    return code is not None and not code.co_names and not code.co_freevars


def _publications_hors_espace(departement: Departement) -> list[dict[str, Any]]:
    """Les `publier(<type>, ...)` du code d'un département dont le type (littéral, ou constante du même fichier) porte
    le préfixe d'UN AUTRE département (`m5.…` publié par M3). Le bus ne lie pas le type au producteur : sans ce
    contrôle, un département écrirait dans l'espace de noms d'un autre (un fait « scellé » ou « confirmé » qui n'est pas
    le sien). Les types `opsys.*` et les noms qu'on ne sait pas résoudre statiquement ne sont pas vus (limite dite)."""
    numero = departement.numero
    sortie: list[dict[str, Any]] = []
    racine = departement.racine / "src" if departement.racine is not None else None
    if racine is None or not racine.is_dir():
        return sortie
    for fichier in sorted(racine.rglob("*.py")):
        try:
            arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        constantes = {
            cible.id: noeud.value.value
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Assign) and isinstance(noeud.value, ast.Constant)
            and isinstance(noeud.value.value, str)
            for cible in noeud.targets
            if isinstance(cible, ast.Name)
        }
        for appel in ast.walk(arbre):
            if not isinstance(appel, ast.Call) or not appel.args:
                continue
            nom = appel.func.attr if isinstance(appel.func, ast.Attribute) else getattr(appel.func, "id", None)
            if nom != "publier":
                continue
            premier = appel.args[0]
            type_evenement = (
                premier.value if isinstance(premier, ast.Constant)
                else constantes.get(premier.id) if isinstance(premier, ast.Name) else None
            )
            correspondance = re.match(r"m(\d+)\.", type_evenement) if isinstance(type_evenement, str) else None
            if correspondance and int(correspondance.group(1)) != numero:
                sortie.append({"departement": departement.id, "type": type_evenement,
                               "fichier": fichier.name, "ligne": appel.lineno})
    return sortie


def analyser(
    departements: Mapping[str, Departement], justifications: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """La matrice et les écarts. `justifications` : lues du fichier de données quand omises."""
    catalogue = types_connus()
    justifs = dict(lire_justifications() if justifications is None else justifications)
    producteurs: dict[str, list[str]] = {}
    declares: dict[str, list[str]] = {}
    reels: dict[str, list[str]] = {}
    declares_sans_handler: list[dict[str, str]] = []
    handlers_sans_declaration: list[dict[str, str]] = []
    illisibles: list[dict[str, str]] = []
    handlers_inertes: list[dict[str, str]] = []
    publications_hors_espace: list[dict[str, Any]] = []
    producteurs_sans_trace: list[dict[str, str]] = []
    for dep in sorted(departements.values(), key=lambda d: d.numero):
        publications_hors_espace.extend(_publications_hors_espace(dep))
        for type_evenement in dep.evenements_publie:
            producteurs.setdefault(type_evenement, []).append(dep.id)
            if type_evenement in catalogue and not _trace_dans_le_code(dep, type_evenement):
                producteurs_sans_trace.append({"departement": dep.id, "type": type_evenement})
        try:
            handlers = dict(dep.charger_consommateurs())
        except Exception as exc:  # noqa: BLE001 — décrit dans le rapport, jamais une panne de l'audit
            illisibles.append({"departement": dep.id, "erreur": f"{type(exc).__name__}: {exc}"})
            handlers = {}
        fonctions = set(handlers)
        for type_evenement in dep.evenements_consomme:
            declares.setdefault(type_evenement, []).append(dep.id)
            if type_evenement in fonctions and _inerte(handlers[type_evenement]):
                # Un handler inerte ne reçoit rien : il n'est PAS un consommateur réel.
                handlers_inertes.append({"departement": dep.id, "type": type_evenement})
            elif type_evenement in fonctions:
                reels.setdefault(type_evenement, []).append(dep.id)
            else:
                declares_sans_handler.append({"departement": dep.id, "type": type_evenement})
        for type_evenement in sorted(fonctions - set(dep.evenements_consomme)):
            handlers_sans_declaration.append({"departement": dep.id, "type": type_evenement})
    lignes = []
    for type_evenement in sorted(catalogue):
        lignes.append(
            {
                "type": type_evenement,
                "producteurs": producteurs.get(type_evenement, []),
                "consommateurs": reels.get(type_evenement, []),
                "justification": justifs.get(type_evenement),
            }
        )
    sans_consommateur = [ligne["type"] for ligne in lignes if not ligne["consommateurs"]]
    return {
        "matrice": lignes,
        "types_sans_consommateur": sans_consommateur,
        "types_sans_consommateur_non_justifies": [t for t in sans_consommateur if t not in justifs],
        "justifications_perimees": sorted(t for t in justifs if reels.get(t)),
        "declares_sans_handler": declares_sans_handler,
        "handlers_inertes": handlers_inertes,
        "publications_hors_espace": publications_hors_espace,
        "handlers_sans_declaration": handlers_sans_declaration,
        "types_sans_producteur": sorted(t for t in catalogue if reels.get(t) and not producteurs.get(t)),
        "producteurs_sans_trace": producteurs_sans_trace,
        "modules_illisibles": illisibles,
        "justifications_invalides": justifications_invalides(justifs, catalogue),
    }


def problemes(analyse: Mapping[str, Any]) -> list[str]:
    """Liste lisible des écarts bloquants (vide : l'interconnexion déclarée est celle qui tourne)."""
    sortie: list[str] = []
    for t in analyse["types_sans_consommateur_non_justifies"]:
        sortie.append(f"{t} : aucun consommateur réel et aucune justification écrite")
    for t in analyse["justifications_perimees"]:
        sortie.append(f"{t} : justifié « sans consommateur » alors qu'un consommateur réel existe (retirer la fiche)")
    for ecart in analyse["declares_sans_handler"]:
        sortie.append(f"{ecart['departement']} : consomme {ecart['type']} sans handler dans consommateurs()")
    for ecart in analyse["publications_hors_espace"]:
        sortie.append(
            f"{ecart['departement']} : publie {ecart['type']} (espace d'un autre département) "
            f"à {ecart['fichier']}:{ecart['ligne']}")
    for ecart in analyse["handlers_inertes"]:
        sortie.append(f"{ecart['departement']} : handler {ecart['type']} inerte (ne référence aucun appel ni écriture)")
    for ecart in analyse["handlers_sans_declaration"]:
        sortie.append(f"{ecart['departement']} : handler {ecart['type']} absent de evenements.consomme")
    for t in analyse["types_sans_producteur"]:
        sortie.append(f"{t} : consommé mais publié par aucun département déclaré")
    for ecart in analyse["producteurs_sans_trace"]:
        sortie.append(
            f"{ecart['departement']} : déclare publier {ecart['type']} mais le nom n'apparaît dans aucun code"
        )
    for ecart in analyse["modules_illisibles"]:
        sortie.append(f"{ecart['departement']} : consommateurs() illisible ({ecart['erreur']})")
    sortie.extend(analyse["justifications_invalides"])
    return sortie


def _code(id_departement: str) -> str:
    return "M" + str(int(id_departement[1:3]))


def matrice_markdown(analyse: Mapping[str, Any]) -> str:
    """Table Markdown stable (triée) : producteur, type, consommateurs réels ou justification."""
    lignes = ["| Type | Producteur | Consommateurs réels | Sans consommateur : justification |", "|---|---|---|---|"]
    for ligne in analyse["matrice"]:
        producteurs = ", ".join(_code(p) for p in ligne["producteurs"]) or "—"
        consommateurs = ", ".join(_code(c) for c in ligne["consommateurs"]) or "—"
        justification = ""
        if not ligne["consommateurs"]:
            fiche = ligne["justification"]
            if fiche:
                raison = fiche["raison"]
                raison = raison if len(raison) <= 150 else raison[:147].rstrip() + "..."
                justification = f"{raison} (revue {fiche['revue_le']})"
            else:
                justification = "**AUCUNE**"
        lignes.append(f"| `{ligne['type']}` | {producteurs} | {consommateurs} | {justification} |")
    return "\n".join(lignes)


# ----------------------------------------------------------------------------------------------- lectures croisées
_ID = r"(m(?:0[1-9]|10)-[a-z0-9-]+)"
# Les formes par lesquelles un département lit les lignes d'un registre d'un AUTRE : `maillons("autre", ...)`, un
# filtre SQL
# `REGISTRES.c.departement == "autre"`, une copie `_copies(cnx, "autre", ...)`, ou le nom du département posé dans une
# constante de lecture (`dept = "autre"`, `_DEPARTEMENT_X = "autre"`).
_LECTURES_DIRECTES = tuple(
    re.compile(motif, re.MULTILINE)
    for motif in (
        rf"maillons\(\s*[\"']{_ID}[\"']",
        rf"REGISTRES\.c\.departement\s*==\s*[\"']{_ID}[\"']",
        rf"_copies\(\s*\w+\s*,\s*[\"']{_ID}[\"']",
        rf"^\s*(?:dept|_DEPARTEMENT_[A-Z_]+)\s*=\s*[\"']{_ID}[\"']",
    )
)
# Une constante qui porte l'identifiant d'un département (`AUTRE = "m04-field-ops"`, de n'importe quel nom) puis un
# `maillons(AUTRE, ...)` du même fichier : la lecture directe sans que le nom de la constante soit celui qu'on attend.
_AFFECTATION_ID = re.compile(rf"^\s*(\w+)\s*(?::[^=\n]+)?=\s*[\"']{_ID}[\"']\s*(?:#.*)?$", re.MULTILINE)
_APPEL_MAILLONS_PAR_NOM = re.compile(r"maillons\(\s*(\w+)\s*,")
_IMPORT_AUTRE = re.compile(r"^\s*(?:from|import)\s+(m(?:[1-9]|10)_[a-z_]+)", re.MULTILINE)


def lire_lectures_croisees(chemin: Path | None = None) -> list[dict[str, Any]]:
    fichier = chemin or CHEMIN_LECTURES
    brut = json.loads(fichier.read_text(encoding="utf-8"))
    if brut.get("schema") != SCHEMA_LECTURES or not isinstance(brut.get("lectures"), list):
        raise ValueError(f"{fichier} : schema attendu {SCHEMA_LECTURES!r} avec une liste « lectures »")
    return brut["lectures"]


def _lectures_m9() -> list[dict[str, Any]]:
    """Les lectures de M9 vers ses producteurs, tirées de la liste blanche du port (source unique)."""
    from ..lecteurs_m9 import DEPARTEMENT_M9, LECTURES_AUTORISEES

    return [
        {"lecteur": DEPARTEMENT_M9, "source": source, "voie": "port:lecteur_producteurs_m9", "outils": sorted(outils)}
        for source, outils in sorted(LECTURES_AUTORISEES.items())
    ]


def _paquet_de(departement: Departement) -> str:
    return departement.module_outils.split(".", 1)[0]


def auditer_lectures_croisees(
    departements: Mapping[str, Departement], declarees: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Les lectures d'un département dans un autre existent-elles vraiment, et y en a-t-il d'autres ?

    - `ports_introuvables` : une lecture déclarée par un port dont l'outil n'existe pas chez la source, ou n'est pas
    T0/N0
      (une lecture qui écrirait n'en est pas une) ;
    - `directes_non_declarees` : un `maillons("<autre département>", ...)` dans le code d'un département qui n'est pas
    dans
      les lectures déclarées (un département ne touche au registre d'un autre que si c'est écrit, daté et justifié) ;
    - `directes_disparues` : une lecture directe déclarée dont le code n'existe plus (la fiche ment) ;
    - `imports_non_declares` : un `import` du paquet Python d'un autre département hors des lectures déclarées ;
    - `sans_dependance` : lecteur -> source lus mais absents de `dependances` du lecteur. INFORMATIF : `dependances`
    ouvre
      aussi la base de connaissances de la source ; l'élargir pour couvrir une lecture serait élargir un droit.
    """
    from ..outils import Autonomie, Niveau

    lectures = _lectures_m9() + list(lire_lectures_croisees() if declarees is None else declarees)
    ports_introuvables: list[str] = []
    for lecture in lectures:
        if not str(lecture["voie"]).startswith("port:"):
            continue
        source = departements.get(lecture["source"])
        if source is None:
            ports_introuvables.append(f"{lecture['lecteur']} -> {lecture['source']} : département source absent")
            continue
        par_nom = {o.nom: o for o in source.charger_outils()}
        for nom in lecture["outils"]:
            outil = par_nom.get(nom)
            if outil is None:
                ports_introuvables.append(f"{lecture['lecteur']} -> {lecture['source']} : outil {nom} introuvable")
            elif outil.autonomie is not Autonomie.T0 or outil.niveau_effectif is not Niveau.N0:
                ports_introuvables.append(f"{lecture['lecteur']} -> {lecture['source']} : {nom} n'est pas T0/N0")
    declarees_directes = {(x["lecteur"], x["source"]) for x in lectures if x["voie"] == "registre"}
    declarees_import = {(x["lecteur"], x["source"]) for x in lectures}
    paquet_vers_id = {_paquet_de(d): d.id for d in departements.values()}
    trouvees_directes: set[tuple[str, str]] = set()
    trouves_imports: set[tuple[str, str]] = set()
    for dep in departements.values():
        for fichier in sorted((dep.racine / "src").rglob("*.py")):
            texte = fichier.read_text(encoding="utf-8")
            for motif in _LECTURES_DIRECTES:
                for autre in motif.findall(texte):
                    if autre != dep.id:
                        trouvees_directes.add((dep.id, autre))
            constantes = dict(_AFFECTATION_ID.findall(texte))
            for nom in _APPEL_MAILLONS_PAR_NOM.findall(texte):
                autre = constantes.get(nom)
                if autre is not None and autre != dep.id:
                    trouvees_directes.add((dep.id, autre))
            for paquet in _IMPORT_AUTRE.findall(texte):
                autre = paquet_vers_id.get(paquet)
                if autre is not None and autre != dep.id:
                    trouves_imports.add((dep.id, autre))
    sans_dependance = sorted(
        {
            (x["lecteur"], x["source"])
            for x in lectures
            if x["lecteur"] in departements and x["source"] not in departements[x["lecteur"]].dependances
        }
    )
    return {
        "lectures": lectures,
        "ports_introuvables": ports_introuvables,
        "directes_non_declarees": sorted(trouvees_directes - declarees_directes),
        "directes_disparues": sorted(declarees_directes - trouvees_directes),
        "imports_non_declares": sorted(trouves_imports - declarees_import),
        "sans_dependance": [f"{lecteur} lit {source}" for lecteur, source in sans_dependance],
    }


def problemes_lectures(audit: Mapping[str, Any]) -> list[str]:
    """Écarts BLOQUANTS des lectures croisées (`sans_dependance` est informatif et n'en fait pas partie)."""
    sortie = list(audit["ports_introuvables"])
    sortie += [
        f"{a} lit directement le registre de {b} sans que ce soit déclaré" for a, b in audit["directes_non_declarees"]
    ]
    sortie += [f"{a} -> {b} : lecture directe déclarée mais absente du code" for a, b in audit["directes_disparues"]]
    sortie += [f"{a} importe le code de {b} sans que ce soit déclaré" for a, b in audit["imports_non_declares"]]
    return sortie


def lectures_markdown(audit: Mapping[str, Any]) -> str:
    """Table Markdown stable des lectures croisées déclarées (voie, ce qui est lu) et des écarts à `dependances`."""
    lignes = ["| Lecteur | Source | Voie | Outils ou registres lus |", "|---|---|---|---|"]
    for lecture in audit["lectures"]:
        lus = ", ".join(f"`{x}`" for x in lecture.get("outils") or lecture.get("registres") or [])
        lignes.append(f"| {_code(lecture['lecteur'])} | {_code(lecture['source'])} | `{lecture['voie']}` | {lus} |")
    return "\n".join(lignes)
