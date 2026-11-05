"""Réglages de direction : la déclaration (schéma FERMÉ du manifeste) et la validation d'une valeur.

Un département déclare, dans son `department.yaml`, ce que la direction doit décider (bloc `reglages:`). La
déclaration ne porte JAMAIS une valeur en vigueur : seulement de quoi la décider (libellé, type, unité, bornes, ce
que sa valeur débloque, niveau d'approbation) et, facultativement, une PROPOSITION étiquetée « recommandation, non
validée » avec sa justification et sa source écrite. Une proposition ne s'applique jamais d'elle-même (`magasin`,
`outils_reglages` de M9).

Schéma fermé, fail-closed : une clé inconnue, un type inconnu, un chemin hors de `configuration`, une proposition
hors bornes ou sans source, un doublon sont des refus à la lecture du manifeste (`opsys-metier verifier` les voit),
jamais ignorés.

Les valeurs sont des JSON simples : entier, texte décimal canonique (« 12.5 », jamais un flottant), liste d'entiers,
objet `{pire, cible}`, texte. Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from ..outils import Niveau

ETIQUETTE_PROPOSITION = "recommandation, non validée"
TYPES = ("entier", "decimal", "texte", "liste_entiers_croissants", "bornes_pire_cible")
# Seul N3 est pris en charge : l'adoption passe par un outil N3 (`m9_adopter_reglage`). Un réglage N4 ne pourrait
# jamais être adopté tant qu'aucun outil N4 n'existe : le déclarer est donc refusé, pas accepté pour rien.
NIVEAUX_PRIS_EN_CHARGE = (Niveau.N3,)
RACINE_CHEMIN = "configuration"
LIBELLE_MAX = 120
DEBLOQUE_MAX = 300
JUSTIFICATION_MAX = 400
SOURCE_MAX = 200
UNITE_MAX = 24
TEXTE_VALEUR_MAX = 200
_CLE = re.compile(r"^(m(?:10|[1-9]))\.([a-z][a-z0-9_]{2,60})$")
_SEGMENT = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ENTIER_MAX = 10**12
_DECIMAL_MAX = Decimal(10) ** 15
_CLES_DECLARATION = {
    "cle", "libelle", "chemin", "type", "unite", "min", "max", "longueur", "ordre", "longueur_max", "debloque",
    "niveau", "proposition",
}
_CLES_PROPOSITION = {"valeur", "etiquette", "justification", "source"}
_ORDRES = ("croissant", "decroissant")


class ReglageRefuse(ValueError):
    """Refus typé : `code` stable (`REJ-REGLAGE-…`), `detail` lisible. Jamais un secret ni une personne."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail


@dataclasses.dataclass(frozen=True)
class Proposition:
    valeur: Any
    etiquette: str
    justification: str
    source: str


@dataclasses.dataclass(frozen=True)
class Reglage:
    cle: str
    departement: str
    libelle: str
    chemin: tuple[str, ...]
    type: str
    unite: str | None
    minimum: Any
    maximum: Any
    longueur: int | None
    ordre: str | None
    longueur_max: int | None
    debloque: str
    niveau: Niveau
    proposition: Proposition | None

    @property
    def chemin_texte(self) -> str:
        return ".".join(self.chemin)


# ---------------------------------------------------------------------------------------------------------
# Valeurs
# ---------------------------------------------------------------------------------------------------------
def texte_decimal(valeur: Decimal) -> str:
    """Texte décimal exact, sans exposant ni « -0 » : `Decimal('40.0')` -> `'40'`, `12.50` -> `'12.5'`."""
    if valeur.is_zero():
        return "0"
    texte = format(valeur, "f")
    if "." in texte:
        texte = texte.rstrip("0").rstrip(".")
    return texte


def _decimal(brut: Any, code_type: str = "REJ-REGLAGE-TYPE") -> Decimal:
    """Un nombre décimal fini lu d'un entier, texte, Decimal ou flottant ; jamais un booléen.

    Un flottant reçu par un autre outil a déjà perdu son lexème JSON ; la console N3 évite cette perte en
    décodant ses nombres en Decimal avant d'appeler cette validation.
    """
    if brut is None or isinstance(brut, bool) or not isinstance(brut, (int, float, str, Decimal)):
        raise ReglageRefuse(code_type, "un nombre est attendu")
    if isinstance(brut, str) and (not brut.strip() or len(brut) > 40):
        raise ReglageRefuse(code_type, "un nombre est attendu")
    if isinstance(brut, Decimal) and len(str(brut)) > 40:
        raise ReglageRefuse(code_type, "un nombre est attendu")
    try:
        lu = brut if isinstance(brut, Decimal) else Decimal(str(brut).strip())
    except (InvalidOperation, ValueError):
        raise ReglageRefuse(code_type, "un nombre est attendu") from None
    if not lu.is_finite() or lu.copy_abs() >= _DECIMAL_MAX:
        raise ReglageRefuse(code_type, "un nombre fini est attendu")
    if not lu.is_zero() and lu.adjusted() < -9:
        raise ReglageRefuse(code_type, "nombre trop petit pour être un seuil")
    return lu


def _entier(brut: Any) -> int:
    if isinstance(brut, bool) or not isinstance(brut, int):
        raise ReglageRefuse("REJ-REGLAGE-TYPE", "un entier est attendu (ni texte, ni booléen, ni décimal)")
    return brut


def _dans_les_bornes(valeur: Any, reglage: Reglage, quoi: str = "la valeur") -> None:
    if valeur < reglage.minimum or valeur > reglage.maximum:
        unite = f" {reglage.unite}" if reglage.unite else ""
        raise ReglageRefuse(
            "REJ-REGLAGE-HORS-BORNES",
            f"{quoi} doit être entre {_afficher(reglage.minimum)} et {_afficher(reglage.maximum)}{unite}",
        )


def _afficher(valeur: Any) -> str:
    return texte_decimal(valeur) if isinstance(valeur, Decimal) else str(valeur)


def valider_valeur(reglage: Reglage, brut: Any) -> Any:
    """La valeur NORMALISÉE d'un réglage (JSON simple), ou `ReglageRefuse`. Le type et les bornes viennent de la
    déclaration du département, jamais de l'appelant."""
    type_ = reglage.type
    if type_ == "entier":
        valeur = _entier(brut)
        _dans_les_bornes(valeur, reglage)
        return valeur
    if type_ == "decimal":
        valeur = _decimal(brut)
        _dans_les_bornes(valeur, reglage)
        return texte_decimal(valeur)
    if type_ == "texte":
        if not isinstance(brut, str):
            raise ReglageRefuse("REJ-REGLAGE-TYPE", "un texte est attendu")
        propre = " ".join(brut.split())
        if not 3 <= len(propre) <= (reglage.longueur_max or TEXTE_VALEUR_MAX) or not propre.isprintable():
            raise ReglageRefuse(
                "REJ-REGLAGE-HORS-BORNES",
                f"texte imprimable de 3 à {reglage.longueur_max or TEXTE_VALEUR_MAX} caractères",
            )
        return propre
    if type_ == "liste_entiers_croissants":
        if not isinstance(brut, (list, tuple)) or len(brut) != reglage.longueur:
            raise ReglageRefuse("REJ-REGLAGE-FORME", f"une liste de {reglage.longueur} entiers est attendue")
        valeurs = [_entier(v) for v in brut]
        for valeur in valeurs:
            _dans_les_bornes(valeur, reglage, "chaque valeur")
        if any(a >= b for a, b in zip(valeurs, valeurs[1:], strict=False)):
            raise ReglageRefuse("REJ-REGLAGE-FORME", "les valeurs doivent être strictement croissantes")
        return valeurs
    if type_ == "bornes_pire_cible":
        if not isinstance(brut, Mapping) or set(brut) != {"pire", "cible"}:
            raise ReglageRefuse("REJ-REGLAGE-FORME", "un objet {pire, cible} est attendu, sans autre clé")
        pire, cible = _decimal(brut["pire"]), _decimal(brut["cible"])
        for nom, valeur in (("pire", pire), ("cible", cible)):
            _dans_les_bornes(valeur, reglage, f"la borne « {nom} »")
        if pire == cible:
            raise ReglageRefuse("REJ-REGLAGE-FORME", "« pire » et « cible » ne peuvent pas être égales")
        if (reglage.ordre == "croissant") != (pire < cible):
            sens = "inférieure" if reglage.ordre == "croissant" else "supérieure"
            raise ReglageRefuse(
                "REJ-REGLAGE-FORME",
                f"« pire » doit être {sens} à « cible » (le mieux va dans le sens {reglage.ordre})",
            )
        return {"pire": texte_decimal(pire), "cible": texte_decimal(cible)}
    raise ReglageRefuse("REJ-REGLAGE-TYPE", f"type de réglage inconnu : {type_!r}")  # pragma: no cover - schéma fermé


def analyser_saisie(reglage: Reglage, texte: str) -> Any:
    """La valeur brute d'un champ de formulaire (texte) selon le type du réglage, prête pour `valider_valeur`.

    Entier et décimal : le texte lui-même ; liste : entiers séparés par des virgules ; bornes : « pire ; cible » ;
    texte : tel quel. Une saisie illisible est un refus de forme, jamais une valeur devinée."""
    if not isinstance(texte, str) or len(texte) > 400:
        raise ReglageRefuse("REJ-REGLAGE-FORME", "saisie illisible")
    propre = texte.strip()
    if reglage.type == "entier":
        if not re.fullmatch(r"-?[0-9]{1,13}", propre):
            raise ReglageRefuse("REJ-REGLAGE-TYPE", "un entier est attendu")
        return int(propre)
    if reglage.type in ("decimal", "texte"):
        return propre.replace(",", ".") if reglage.type == "decimal" else propre
    if reglage.type == "liste_entiers_croissants":
        morceaux = [m.strip() for m in propre.split(",")]
        if not all(re.fullmatch(r"-?[0-9]{1,13}", m) for m in morceaux):
            raise ReglageRefuse("REJ-REGLAGE-FORME", "des entiers séparés par des virgules sont attendus")
        return [int(m) for m in morceaux]
    if reglage.type == "bornes_pire_cible":
        morceaux = [m.strip().replace(",", ".") for m in propre.split(";")]
        if len(morceaux) != 2:
            raise ReglageRefuse(
                "REJ-REGLAGE-FORME", "deux nombres séparés par un point-virgule sont attendus : pire ; cible"
            )
        return {"pire": morceaux[0], "cible": morceaux[1]}
    raise ReglageRefuse("REJ-REGLAGE-TYPE", "type inconnu")  # pragma: no cover - schéma fermé


def valeur_en_texte(reglage: Reglage, valeur: Any) -> str:
    """La valeur normalisée, lisible et rejouable dans `analyser_saisie` (champ de formulaire prérempli)."""
    if valeur is None:
        return ""
    if reglage.type == "liste_entiers_croissants":
        return ", ".join(str(v) for v in valeur)
    if reglage.type == "bornes_pire_cible":
        return f"{valeur['pire']} ; {valeur['cible']}"
    return str(valeur)


# ---------------------------------------------------------------------------------------------------------
# Lecture du bloc `reglages:` d'un manifeste
# ---------------------------------------------------------------------------------------------------------
def _texte(entree: Mapping[str, Any], cle: str, ctx: str, minimum: int, maximum: int) -> str:
    valeur = entree.get(cle)
    if not isinstance(valeur, str) or not minimum <= len(" ".join(valeur.split())) <= maximum:
        raise ValueError(f"{ctx} : {cle} : texte de {minimum} à {maximum} caractères requis")
    return " ".join(valeur.split())


def _borne(brut: Any, type_: str, cle: str, ctx: str) -> Any:
    if type_ == "entier" or type_ == "liste_entiers_croissants":
        if isinstance(brut, bool) or not isinstance(brut, int) or abs(brut) > _ENTIER_MAX:
            raise ValueError(f"{ctx} : {cle} : entier requis")
        return brut
    if isinstance(brut, bool) or not isinstance(brut, (int, str)):
        raise ValueError(f"{ctx} : {cle} : nombre décimal requis, entier ou texte (« 0.5 »), jamais un flottant YAML")
    try:
        return _decimal(brut)
    except ReglageRefuse:
        raise ValueError(f"{ctx} : {cle} : nombre décimal fini requis") from None


def lire(brut: Any, ctx: str, code: str, departement: str) -> tuple[Reglage, ...]:
    """`reglages:` d'un manifeste (optionnel) -> déclarations validées. `ctx` : le chemin du manifeste (messages) ;
    `code` : le code du département (`M2`) dont la clé de chaque réglage porte le préfixe (`m2.`) ; `departement` : son
    identifiant
    (`m02-revenue-crm`), rattaché à chaque déclaration."""
    if brut is None:
        return ()
    if not isinstance(brut, list):
        raise ValueError(f"{ctx} : reglages doit être une liste")
    departement_code = code.lower()
    cles: set[str] = set()
    chemins: list[tuple[str, ...]] = []
    sortie: list[Reglage] = []
    for entree in brut:
        if not isinstance(entree, dict):
            raise ValueError(f"{ctx} : chaque réglage doit être un objet")
        inconnues = sorted(set(entree) - _CLES_DECLARATION)
        if inconnues:
            raise ValueError(f"{ctx} : reglages : clé(s) inconnue(s) {inconnues}")
        cle = entree.get("cle")
        correspondance = _CLE.match(cle) if isinstance(cle, str) else None
        if correspondance is None or correspondance.group(1) != departement_code:
            raise ValueError(f"{ctx} : réglage {cle!r} : clé « {departement_code}.nom_en_snake_case » requise")
        if cle in cles:
            raise ValueError(f"{ctx} : réglage {cle!r} en double")
        cles.add(cle)
        sous = f"{ctx} : réglage {cle}"
        libelle = _texte(entree, "libelle", sous, 5, LIBELLE_MAX)
        debloque = _texte(entree, "debloque", sous, 10, DEBLOQUE_MAX)
        chemin_brut = entree.get("chemin")
        segments = tuple(chemin_brut.split(".")) if isinstance(chemin_brut, str) else ()
        if (not 2 <= len(segments) <= 6 or segments[0] != RACINE_CHEMIN
                or not all(_SEGMENT.match(s) for s in segments)):
            raise ValueError(f"{sous} : chemin « configuration.…» requis (2 à 6 segments en snake_case)")
        for autre in chemins:
            if autre[: len(segments)] == segments or segments[: len(autre)] == autre:
                raise ValueError(f"{sous} : chemin {chemin_brut!r} en conflit avec {'.'.join(autre)!r}")
        chemins.append(segments)
        type_ = entree.get("type")
        if type_ not in TYPES:
            raise ValueError(f"{sous} : type {type_!r} inconnu (attendu : {', '.join(TYPES)})")
        niveau_brut = entree.get("niveau")
        niveau = next((n for n in NIVEAUX_PRIS_EN_CHARGE if n.value == niveau_brut), None)
        if niveau is None:
            raise ValueError(
                f"{sous} : niveau {niveau_brut!r} non pris en charge (seul "
                f"{', '.join(n.value for n in NIVEAUX_PRIS_EN_CHARGE)} : l'adoption passe par un outil N3)"
            )
        unite = entree.get("unite")
        longueur = entree.get("longueur")
        ordre = entree.get("ordre")
        longueur_max = entree.get("longueur_max")
        minimum = maximum = None
        if type_ == "texte":
            if any(k in entree for k in ("unite", "min", "max", "longueur", "ordre")):
                raise ValueError(f"{sous} : un réglage texte ne porte que longueur_max")
            if (isinstance(longueur_max, bool) or not isinstance(longueur_max, int)
                    or not 3 <= longueur_max <= TEXTE_VALEUR_MAX):
                raise ValueError(f"{sous} : longueur_max : entier de 3 à {TEXTE_VALEUR_MAX} requis")
            unite = None
        else:
            if not isinstance(unite, str) or not 1 <= len(unite) <= UNITE_MAX:
                raise ValueError(f"{sous} : unite : texte de 1 à {UNITE_MAX} caractères requis")
            if "min" not in entree or "max" not in entree:
                raise ValueError(f"{sous} : min et max obligatoires (bornes de saisie, jamais des valeurs d'affaires)")
            minimum, maximum = _borne(entree["min"], type_, "min", sous), _borne(entree["max"], type_, "max", sous)
            if minimum >= maximum:
                raise ValueError(f"{sous} : min doit être inférieur à max")
            if longueur_max is not None:
                raise ValueError(f"{sous} : longueur_max ne concerne que le type texte")
        if type_ == "liste_entiers_croissants":
            if isinstance(longueur, bool) or not isinstance(longueur, int) or not 2 <= longueur <= 12:
                raise ValueError(f"{sous} : longueur : entier de 2 à 12 requis")
        elif longueur is not None:
            raise ValueError(f"{sous} : longueur ne concerne que liste_entiers_croissants")
        if type_ == "bornes_pire_cible":
            if ordre not in _ORDRES:
                raise ValueError(f"{sous} : ordre : {' ou '.join(_ORDRES)} requis (le sens du « mieux »)")
        elif ordre is not None:
            raise ValueError(f"{sous} : ordre ne concerne que bornes_pire_cible")
        reglage = Reglage(
            cle=cle, departement=departement, libelle=libelle, chemin=segments, type=type_, unite=unite,
            minimum=minimum, maximum=maximum, longueur=longueur, ordre=ordre, longueur_max=longueur_max,
            debloque=debloque, niveau=niveau, proposition=None,
        )
        proposition = _proposition(entree.get("proposition"), reglage, sous)
        sortie.append(dataclasses.replace(reglage, proposition=proposition))
    return tuple(sortie)


def _proposition(brut: Any, reglage: Reglage, ctx: str) -> Proposition | None:
    if brut is None:
        return None
    if not isinstance(brut, dict) or set(brut) != _CLES_PROPOSITION:
        raise ValueError(f"{ctx} : proposition : exactement {sorted(_CLES_PROPOSITION)}")
    if brut["etiquette"] != ETIQUETTE_PROPOSITION:
        raise ValueError(f"{ctx} : proposition.etiquette doit être exactement « {ETIQUETTE_PROPOSITION} »")
    justification = _texte(brut, "justification", f"{ctx} : proposition", 10, JUSTIFICATION_MAX)
    source = _texte(brut, "source", f"{ctx} : proposition", 5, SOURCE_MAX)
    try:
        valeur = valider_valeur(reglage, brut["valeur"])
    except ReglageRefuse as exc:
        raise ValueError(f"{ctx} : proposition.valeur : {exc.detail}") from None
    return Proposition(valeur=valeur, etiquette=ETIQUETTE_PROPOSITION, justification=justification, source=source)

