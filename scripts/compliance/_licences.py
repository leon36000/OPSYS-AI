"""Bibliothèque commune de la conformité des licences (stdlib seulement, aucune entrée-sortie réseau).

Lue par `collecter_constats.py` (relève les licences des paquets installés sur UNE machine), `generer_sbom.py`
(SBOM CycloneDX reproductible depuis les verrous du dépôt) et `tests/test_conformite_licences.py`.

Principe directeur : une licence n'est « connue » que si une SOURCE la porte — métadonnées d'un paquet installé,
champ `license` d'un verrou npm, ou déclaration écrite dans la documentation du dépôt (avec sa référence). Rien n'est
complété de mémoire : ce qu'aucune source ne porte reste `non_verifiee`, visible, et fait échouer le test dès qu'un
NOUVEAU composant de production y entre sans être consigné.
"""

# ruff: noqa: E501  (assertions et chaînes de documentation longues, lisibles telles quelles)

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[2]
DONNEES = RACINE / "docs" / "compliance" / "donnees"
FICHIER_POLITIQUE = DONNEES / "politique-licences.json"
FICHIER_CONSTATS = DONNEES / "constats-licences.json"
FICHIER_HORS_GESTIONNAIRE = DONNEES / "composants-hors-gestionnaire.json"
FICHIER_SBOM = RACINE / "docs" / "compliance" / "sbom.cdx.json"

NIVEAUX = ("metadonnees_locales", "verrou", "documentation_depot", "non_verifiee")
PORTEES = ("production", "production-optionnel", "developpement")
CLASSES = ("permissive", "copyleft_faible", "copyleft_fort", "usage_restreint", "inconnue")
# Plus grand = plus risqué. `OR` retient l'alternative la moins risquée, `AND` la plus risquée.
RISQUE = {"permissive": 0, "copyleft_faible": 1, "inconnue": 2, "usage_restreint": 3, "copyleft_fort": 4}


def normaliser_nom_pypi(nom: str) -> str:
    return re.sub(r"[-_.]+", "-", nom).lower()


# --------------------------------------------------------------------------------------------- verrous Python
def lire_exigences(chemin: Path) -> dict[tuple[str, str], str]:
    """`{(nom, version): marqueur}` d'un `requirements*.lock.txt` (format `uv export`)."""
    sortie: dict[tuple[str, str], str] = {}
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)\s*(?:;\s*(.*?))?\s*\\?$", ligne)
        if m:
            sortie[(normaliser_nom_pypi(m.group(1)), m.group(2))] = (m.group(3) or "").strip()
    return sortie


def lire_uv_lock(chemin: Path) -> set[tuple[str, str]]:
    """Tous les paquets `[[package]]` de `uv.lock` (production, extras et développement), hors le projet lui-même."""
    paquets: set[tuple[str, str]] = set()
    nom = None
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if ligne == "[[package]]":
            nom = None
        elif ligne.startswith("name = ") and nom is None:
            nom = normaliser_nom_pypi(ligne.split('"')[1])
        elif ligne.startswith("version = ") and nom is not None:
            paquets.add((nom, ligne.split('"')[1]))
            nom = None
    paquets.discard(("opsys-ai", "2.0.0.dev0"))
    return {p for p in paquets if p[0] != "opsys-ai"}


# ---------------------------------------------------------------------------------------------- verrou pnpm
def _sans_guillemets(texte: str) -> str:
    texte = texte.strip()
    if texte.endswith(": {}"):
        texte = texte[:-4]
    elif texte.endswith(":"):
        texte = texte[:-1]
    return texte.strip("'")


def lire_pnpm_lock(chemin: Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """`(production, tous)` : ensembles `(nom, version)` du verrou pnpm de `core/`.

    Production = fermeture transitive des `dependencies` et `optionalDependencies` de chaque projet de l'espace de
    travail ; le reste (`devDependencies` et leurs dépendances) est du développement. Les paquets de l'espace de
    travail (`link:`) sont le code d'OPSYS-CORE lui-même et n'y figurent pas.
    """
    lignes = chemin.read_text(encoding="utf-8").split("\n")
    debut = [i for i, ligne in enumerate(lignes) if ligne.startswith("lockfileVersion")][-1]  # 2e document
    section = None
    importeurs: dict[str, dict[str, dict[str, str]]] = {}
    instantanes: dict[str, dict[str, dict[str, str]]] = {}
    courant: str | None = None
    genre: str | None = None
    dep: str | None = None
    for ligne in lignes[debut:]:
        if not ligne.strip() or ligne.lstrip().startswith("#"):
            continue
        if not ligne.startswith(" "):
            section = ligne.split(":")[0]
            continue
        if section == "importers":
            if re.match(r"^  \S", ligne):
                courant = _sans_guillemets(ligne)
                importeurs[courant] = {}
                genre = None
            elif re.match(r"^    (dependencies|devDependencies|optionalDependencies):", ligne):
                genre = ligne.strip()[:-1]
                importeurs[courant][genre] = {}
            elif re.match(r"^    \S", ligne):
                genre = None
            elif genre and re.match(r"^      \S", ligne):
                dep = _sans_guillemets(ligne)
                importeurs[courant][genre][dep] = ""
            elif genre and dep and ligne.startswith("        version:"):
                importeurs[courant][genre][dep] = ligne.split(":", 1)[1].strip().strip("'")
        elif section == "snapshots":
            if re.match(r"^  \S", ligne):
                courant = _sans_guillemets(ligne)
                instantanes[courant] = {}
                genre = None
            elif re.match(r"^    (dependencies|optionalDependencies):", ligne):
                genre = ligne.strip()[:-1]
                instantanes[courant][genre] = {}
            elif re.match(r"^    \S", ligne):
                genre = None
            elif genre and re.match(r"^      \S", ligne):
                cle, valeur = ligne.strip().split(":", 1)
                instantanes[courant][genre][cle.strip("'")] = valeur.strip().strip("'")

    def cle(nom: str, version: str) -> str | None:
        if version.startswith("link:"):
            return None
        if version.startswith("npm:"):
            return version[4:]
        if "@" in re.sub(r"\(.*$", "", version):  # alias : `nom-local: vrai-nom@version`
            return version
        return f"{nom}@{version}"

    def fermeture(racines: list[str | None]) -> set[str]:
        vus: set[str] = set()
        pile = list(racines)
        while pile:
            k = pile.pop()
            if k is None or k in vus:
                continue
            vus.add(k)
            for genre_dep in ("dependencies", "optionalDependencies"):
                for n, v in instantanes.get(k, {}).get(genre_dep, {}).items():
                    pile.append(cle(n, v))
        return vus

    racines_prod: list[str | None] = []
    racines_dev: list[str | None] = []
    for contenu in importeurs.values():
        for genre_dep in ("dependencies", "optionalDependencies"):
            racines_prod += [cle(n, v) for n, v in contenu.get(genre_dep, {}).items()]
        racines_dev += [cle(n, v) for n, v in contenu.get("devDependencies", {}).items()]

    def vers_paires(ensemble: set[str]) -> set[tuple[str, str]]:
        paires = set()
        for k in ensemble:
            sans_pairs = re.sub(r"\(.*$", "", k)
            i = sans_pairs.rfind("@")
            paires.add((sans_pairs[:i], sans_pairs[i + 1:]))
        return paires

    prod = fermeture(racines_prod)
    tous = fermeture(racines_prod + racines_dev)
    return vers_paires(prod), vers_paires(tous)


# ---------------------------------------------------------------------------------------------- verrou npm
def lire_package_lock(chemin: Path) -> list[dict[str, Any]]:
    """Paquets d'un `package-lock.json` (v2/v3) : nom, version, licence brute du verrou, indicateur `dev`."""
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    sortie = []
    for cle, p in donnees["packages"].items():
        if not cle:
            continue
        nom = p.get("name") or cle.split("node_modules/")[-1]
        sortie.append({
            "nom": nom, "version": p.get("version", ""), "licence_brute": p.get("license"),
            "dev": bool(p.get("dev")), "optionnel": bool(p.get("optional")), "lien": bool(p.get("link")),
            "chemin": cle,
        })
    return sortie


# ------------------------------------------------------------------------------------ licences : normalisation
CLASSIFIEURS_PYPI = {
    "MIT License": "MIT",
    "Apache Software License": "Apache-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
    "ISC License (ISCL)": "ISC",
    "Python Software Foundation License": "PSF-2.0",
    "The Unlicense (Unlicense)": "Unlicense",
}
# « BSD License » (classifieur) ne dit pas laquelle des variantes BSD : jamais devinée.
_TEXTES_SPDX_PYPI = re.compile(r"^[A-Za-z0-9.+-]+( (AND|OR|WITH) [A-Za-z0-9.+-]+)*$")


def spdx_depuis_metadonnees_pypi(expression: str | None, licence: str | None, classifieurs: list[str]) -> tuple[
        str | None, str]:
    """`(spdx|None, brut)` depuis `License-Expression`, `License` (si c'est déjà un identifiant) ou classifieurs."""
    brut = []
    if expression:
        brut.append(f"License-Expression: {expression}")
    if licence:
        brut.append(f"License: {licence.splitlines()[0][:80]}")
    brut += [f"Classifier: {c}" for c in classifieurs]
    if expression:
        return expression.strip(), "; ".join(brut)
    if licence and "\n" not in licence.strip() and len(licence) <= 40 and _TEXTES_SPDX_PYPI.match(licence.strip()):
        return licence.strip(), "; ".join(brut)
    precis = {CLASSIFIEURS_PYPI[c] for c in classifieurs if c in CLASSIFIEURS_PYPI}
    if len(precis) == 1:
        return precis.pop(), "; ".join(brut)
    return None, "; ".join(brut)


def spdx_depuis_package_json(licence: Any, licences: Any = None) -> tuple[str | None, str]:
    """Licence d'un `package.json` : chaîne SPDX, objet `{type}` ou ancien tableau `licenses`."""
    if isinstance(licence, str) and licence.strip():
        valeur = licence.strip()
        if valeur.upper().startswith("SEE LICENSE") or valeur.upper() == "UNLICENSED":
            return None, f"license: {valeur}"
        return valeur, f"license: {valeur}"
    if isinstance(licence, dict) and isinstance(licence.get("type"), str):
        return licence["type"].strip(), f"license.type: {licence['type']}"
    if isinstance(licences, list) and licences:
        types = [x.get("type") for x in licences if isinstance(x, dict) and isinstance(x.get("type"), str)]
        if types:
            return "(" + " OR ".join(types) + ")", f"licenses: {types}"
    return None, "license: absent"


# ------------------------------------------------------------------------------------ licences : expression SPDX
_JETON = re.compile(r"\(|\)|[A-Za-z0-9.+:-]+")


def analyser_expression(expression: str) -> list[list[str]] | None:
    """Expression SPDX → liste d'alternatives (OR) de listes de conjonctions (AND) d'identifiants.

    Forme normale disjonctive : `(A AND B) OR C` → `[[A, B], [C]]`. `X WITH exception` reste l'identifiant `X WITH exception`.
    Renvoie None si l'expression n'est pas analysable (jamais une supposition).
    """
    jetons = _JETON.findall(expression)
    if not jetons or "".join(jetons).replace(" ", "") != re.sub(r"\s+", "", expression):
        return None
    position = 0

    def ou() -> list[list[str]] | None:
        nonlocal position
        gauche = et()
        if gauche is None:
            return None
        while position < len(jetons) and jetons[position].upper() == "OR":
            position += 1
            droite = et()
            if droite is None:
                return None
            gauche = gauche + droite
        return gauche

    def et() -> list[list[str]] | None:
        nonlocal position
        gauche = atome()
        if gauche is None:
            return None
        while position < len(jetons) and jetons[position].upper() == "AND":
            position += 1
            droite = atome()
            if droite is None:
                return None
            gauche = [g + d for g in gauche for d in droite]
        return gauche

    def atome() -> list[list[str]] | None:
        nonlocal position
        if position >= len(jetons):
            return None
        jeton = jetons[position]
        if jeton == "(":
            position += 1
            interieur = ou()
            if interieur is None or position >= len(jetons) or jetons[position] != ")":
                return None
            position += 1
            return interieur
        if jeton in (")",) or jeton.upper() in ("AND", "OR", "WITH"):
            return None
        position += 1
        identifiant = jeton
        if position < len(jetons) and jetons[position].upper() == "WITH":
            if position + 1 >= len(jetons):
                return None
            identifiant = f"{jeton} WITH {jetons[position + 1]}"
            position += 2
        return [[identifiant]]

    resultat = ou()
    return resultat if resultat is not None and position == len(jetons) else None


def charger_politique(chemin: Path = FICHIER_POLITIQUE) -> dict[str, Any]:
    politique = json.loads(chemin.read_text(encoding="utf-8"))
    politique["_motifs_interdits"] = [re.compile(m, re.IGNORECASE) for m in politique["motifs_usage_restreint_ou_fort"]]
    return politique


def classer_identifiant(politique: dict[str, Any], identifiant: str) -> str:
    """Classe d'UN identifiant SPDX (avec exception `WITH` retirée). Un identifiant inconnu est `inconnue`."""
    base = identifiant.split(" WITH ")[0]
    for classe in ("permissive", "copyleft_faible", "copyleft_fort", "usage_restreint"):
        if base in politique["classes"].get(classe, []):
            return classe
    for motif in politique["_motifs_interdits"]:
        if motif.search(base):
            return "copyleft_fort" if re.search(r"GPL|SSPL", base, re.IGNORECASE) else "usage_restreint"
    return "inconnue"


def evaluer_expression(politique: dict[str, Any], expression: str | None) -> tuple[str, str]:
    """`(classe, detail)` d'une expression : OR retient l'alternative la moins risquée, AND la plus risquée."""
    if expression is None:
        return "inconnue", "aucune licence"
    alternatives = analyser_expression(expression)
    if alternatives is None:
        return "inconnue", f"expression non analysable : {expression}"
    meilleure = None
    for conj in alternatives:
        classes = [classer_identifiant(politique, i) for i in conj]
        pire = max(classes, key=lambda c: RISQUE[c])
        if meilleure is None or RISQUE[pire] < RISQUE[meilleure[0]]:
            meilleure = (pire, " AND ".join(conj))
    assert meilleure is not None
    return meilleure


def purl(ecosysteme: str, nom: str, version: str) -> str:
    if ecosysteme == "pypi":
        return f"pkg:pypi/{nom}@{version}"
    if ecosysteme in ("npm-core", "npm-mobile"):
        if nom.startswith("@"):
            return f"pkg:npm/%40{nom[1:]}@{version}"
        return f"pkg:npm/{nom}@{version}"
    return f"pkg:generic/{nom}@{version}"
