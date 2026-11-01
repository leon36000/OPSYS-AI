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
- `handlers_sans_declaration` : une fonction de `consommateurs()` absente de `evenements.consomme`
  (le répartiteur ne l'appelle jamais : du code mort qui se croit branché) ;
- `types_sans_producteur` / `producteurs_sans_trace` : un type consommé que personne ne déclare publier, ou un type
  déclaré publié dont le nom n'apparaît nulle part dans le code du producteur.

Le module ne publie rien, n'écrit rien et ne se connecte à aucune base : il lit des fichiers et importe les modules
des départements (comme `opsys-metier verifier`). Les justifications sont des DONNÉES versionnées, relues à date
fixe, jamais une liste en dur dans un test.
"""

from __future__ import annotations

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
    transverses, ex. le planificateur des connecteurs) ? Un nom qui n'apparaît nulle part ne peut être publié."""
    motif = f'"{type_evenement}"'
    motif_simple = f"'{type_evenement}'"
    racines = [departement.racine / "src", _RACINE_SOCLE]
    for racine in racines:
        if not racine.is_dir():
            continue
        for fichier in racine.rglob("*.py"):
            try:
                texte = fichier.read_text(encoding="utf-8")
            except OSError:
                continue
            if motif in texte or motif_simple in texte:
                return True
    # Un module peut composer le nom (`f"{PREFIXE}.suffixe"`) : on cherche aussi la partie après le point.
    suffixe = type_evenement.split(".", 1)[1]
    for racine in racines:
        if racine.is_dir():
            for fichier in racine.rglob("*.py"):
                try:
                    if re.search(rf"[\"']{re.escape(suffixe)}[\"']", fichier.read_text(encoding="utf-8")):
                        return True
                except OSError:
                    continue
    return False


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
    producteurs_sans_trace: list[dict[str, str]] = []
    for dep in sorted(departements.values(), key=lambda d: d.numero):
        for type_evenement in dep.evenements_publie:
            producteurs.setdefault(type_evenement, []).append(dep.id)
            if type_evenement in catalogue and not _trace_dans_le_code(dep, type_evenement):
                producteurs_sans_trace.append({"departement": dep.id, "type": type_evenement})
        try:
            fonctions = set(dep.charger_consommateurs())
        except Exception as exc:  # noqa: BLE001 — décrit dans le rapport, jamais une panne de l'audit
            illisibles.append({"departement": dep.id, "erreur": f"{type(exc).__name__}: {exc}"})
            fonctions = set()
        for type_evenement in dep.evenements_consomme:
            declares.setdefault(type_evenement, []).append(dep.id)
            if type_evenement in fonctions:
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
