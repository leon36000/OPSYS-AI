"""La couche UNIQUE par laquelle un département lit un réglage de direction.

PRÉCÉDENCE (la seule règle, écrite ici et dans `docs/architecture/REGLAGES-DIRECTION.md`), réglage par réglage :

1. une valeur ADOPTÉE (magasin chaîné, valide, conforme à la déclaration actuelle du manifeste) l'emporte ;
2. sinon la valeur que `department.yaml` porte déjà à ce chemin (compatibilité : rien n'est cassé pour qui a déjà
   rempli le fichier) ;
3. sinon l'ABSENCE : le département reste fail-closed exactement comme avant (« seuil à configurer », score
   indéterminé…).

Jamais une valeur par défaut, jamais une proposition : une proposition étiquetée « recommandation, non validée »
n'est lue par aucun département, seulement affichée à la direction qui l'adopte (ou non).

Ce qui n'est PAS servi, par conception (fail-closed, on retombe sur 2 puis 3) : hors transaction (rien ne se lit sans
la base de l'instance) ; chaîne cassée ; valeur adoptée devenue incompatible avec la déclaration (bornes resserrées
depuis) ; réglage non déclaré au manifeste du département qui lit.

Un département appelle `superposer(donnees_du_manifeste, bloc, valeur_lue_du_fichier)` avec les données YAML qu'il
vient de lire (il n'a ni cache à invalider ni évènement à consommer : l'adoption est visible à l'appel suivant).
"""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.exc import OperationalError, ProgrammingError

from .. import stockage
from . import magasin
from .declaration import Reglage, ReglageRefuse, lire, texte_decimal, valeur_en_texte, valider_valeur

STATUT_ADOPTE = "adopte"
STATUT_FICHIER = "fichier"
STATUT_FICHIER_INVALIDE = "fichier_invalide"
STATUT_VIDE = "vide"
STATUTS_MANQUANTS = (STATUT_VIDE, STATUT_FICHIER_INVALIDE)
JOURNAL_MAX = 20


@dataclasses.dataclass(frozen=True)
class Adoptees:
    """Ce que la chaîne sert aujourd'hui. `lisible` : faux hors transaction (rien n'est lu). `chaine_valide` : faux
    si la chaîne ne se rejoue pas (alors `valeurs` est vide : on ne sert rien d'une chaîne douteuse)."""

    valeurs: Mapping[str, Any]
    versions: Mapping[str, int]
    chaine_valide: bool
    detail: str
    lisible: bool
    maillons: int = 0


def adoptees() -> Adoptees:
    if stockage.connexion_courante() is None:
        return Adoptees({}, {}, True, "hors transaction : aucune valeur adoptée n'est lisible", False)
    cnx = stockage.connexion_courante()
    try:
        # Point de sauvegarde : une lecture qui échoue n'empoisonne pas la transaction de l'appelant (PostgreSQL).
        with cnx.begin_nested():
            chaine, rejeu = magasin.chaine_verifiee()
    except magasin.ChaineInvalide as exc:
        return Adoptees({}, {}, False, exc.detail, True)
    except (OperationalError, ProgrammingError) as exc:
        if "registres_maillons" not in str(exc):
            raise
        # Base sans le registre (instance non migrée, jeu de test partiel) : aucun réglage n'a pu être adopté.
        return Adoptees({}, {}, True, "base non migrée : aucune valeur adoptée n'est lisible", False)
    valeurs = {cle: e["pile"][-1] for cle, e in rejeu.items() if e["pile"]}
    versions = {cle: e["version"] for cle, e in rejeu.items()}
    return Adoptees(valeurs, versions, True, "", True, len(chaine))


def _poser(destination: dict[str, Any], chemin: Sequence[str], valeur: Any) -> None:
    """Pose `valeur` au chemin relatif, en créant les objets intermédiaires. Un intermédiaire illisible (ni vide ni
    objet) est remplacé : la valeur adoptée l'emporte sur ce que le fichier porte à son chemin."""
    courant = destination
    for segment in chemin[:-1]:
        suivant = courant.get(segment)
        if not isinstance(suivant, dict):
            suivant = {}
            courant[segment] = suivant
        courant = suivant
    courant[chemin[-1]] = valeur


def superposer(donnees: Any, bloc: Sequence[str], valeur_fichier: Any) -> Any:
    """`valeur_fichier` (le contenu de `bloc` dans `department.yaml`, ex. `("configuration", "segments")`) avec,
    par-dessus, les valeurs ADOPTÉES des réglages que le manifeste déclare sous ce bloc. Sans rien d'adopté :
    `valeur_fichier` TELLE QUELLE (même objet), donc aucun changement de comportement.
    `donnees` : le manifeste déjà lu (dictionnaire YAML)."""
    if not isinstance(donnees, Mapping) or not donnees.get("reglages"):
        return valeur_fichier
    bloc = tuple(bloc)
    try:
        declares = lire(donnees["reglages"], "manifeste", donnees["code"], donnees["id"])
    except (KeyError, TypeError, ValueError):
        return valeur_fichier  # déclaration illisible : `opsys-metier verifier` la signale ; ici, fail-closed
    cibles = [r for r in declares if len(r.chemin) > len(bloc) and r.chemin[: len(bloc)] == bloc]
    if not cibles:
        return valeur_fichier
    lues = adoptees()
    if not lues.valeurs:
        return valeur_fichier
    resultat: dict[str, Any] | None = None
    for reglage in cibles:
        if reglage.cle not in lues.valeurs:
            continue
        try:
            valeur = valider_valeur(reglage, lues.valeurs[reglage.cle])
        except ReglageRefuse:
            continue  # incompatible avec la déclaration actuelle : jamais servie
        if resultat is None:
            resultat = copy.deepcopy(valeur_fichier) if isinstance(valeur_fichier, dict) else {}
        _poser(resultat, reglage.chemin[len(bloc):], copy.deepcopy(valeur))
    return valeur_fichier if resultat is None else resultat


# ---------------------------------------------------------------------------------------------------------
# État pour la direction : ce qui manque, ce que ça bloque, ce qui est proposé
# ---------------------------------------------------------------------------------------------------------
def valeur_au_chemin(donnees: Any, chemin: Sequence[str]) -> Any:
    courant = donnees
    for segment in chemin:
        if not isinstance(courant, Mapping) or segment not in courant:
            return None
        courant = courant[segment]
    return courant


def _manifeste(racine: Path) -> Any:
    try:
        return yaml.safe_load((racine / "department.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def _lisible(valeur: Any) -> str:
    texte = str(valeur)
    return texte if len(texte) <= 80 else texte[:77] + "…"


def _projeter(reglage: Reglage, statut: str, valeur: Any, version: int, dernier: Mapping[str, Any] | None,
              fichier: Any = None) -> dict[str, Any]:
    proposition = None
    if reglage.proposition is not None:
        proposition = {
            "valeur": reglage.proposition.valeur, "valeur_texte": valeur_en_texte(reglage, reglage.proposition.valeur),
            "etiquette": reglage.proposition.etiquette, "justification": reglage.proposition.justification,
            "source": reglage.proposition.source,
        }
    return {
        "cle": reglage.cle, "departement": reglage.departement, "libelle": reglage.libelle, "type": reglage.type,
        "unite": reglage.unite, "chemin": reglage.chemin_texte, "debloque": reglage.debloque,
        "niveau": reglage.niveau.value, "statut": statut, "manque": statut in STATUTS_MANQUANTS,
        "valeur": valeur, "valeur_texte": valeur_en_texte(reglage, valeur),
        "valeur_fichier_illisible": _lisible(fichier) if statut == STATUT_FICHIER_INVALIDE else None,
        "version": version, "adopte_par": dernier["par"] if dernier else None,
        "adopte_le": dernier["quand"] if dernier else None,
        "bornes": _bornes(reglage), "proposition": proposition,
    }


def _bornes(reglage: Reglage) -> dict[str, Any]:
    texte = _texte_borne
    bornes: dict[str, Any] = {}
    if reglage.minimum is not None:
        bornes = {"min": texte(reglage.minimum), "max": texte(reglage.maximum)}
    if reglage.longueur is not None:
        bornes["longueur"] = reglage.longueur
    if reglage.ordre is not None:
        bornes["ordre"] = reglage.ordre
    if reglage.longueur_max is not None:
        bornes["longueur_max"] = reglage.longueur_max
    return bornes


def _texte_borne(valeur: Any) -> str:
    return texte_decimal(valeur) if isinstance(valeur, Decimal) else str(valeur)


def etat_des_reglages(departements: Mapping[str, Any], *, departement: str | None = None) -> dict[str, Any]:
    """L'état de chaque réglage déclaré par les départements : valeur en vigueur et d'où elle vient, ce qui manque,
    ce que ça bloque, la proposition et son origine. Lecture seule. Dans la transaction courante."""
    lues = adoptees()
    chaine: list[dict[str, Any]] = []
    if lues.lisible and lues.chaine_valide:
        chaine = magasin.lire_chaine()
    items: list[dict[str, Any]] = []
    for dep in departements.values():
        if departement is not None and dep.id != departement:
            continue
        donnees = _manifeste(dep.racine) if dep.reglages else None
        for reglage in dep.reglages:
            if reglage.cle in lues.valeurs:
                try:
                    valeur = valider_valeur(reglage, lues.valeurs[reglage.cle])
                except ReglageRefuse:
                    valeur = None
                if valeur is not None:
                    dernier = next((m for m in reversed(chaine) if m["cle"] == reglage.cle), None)
                    items.append(_projeter(reglage, STATUT_ADOPTE, valeur, lues.versions[reglage.cle], dernier))
                    continue
            version = lues.versions.get(reglage.cle, 0)
            brut = valeur_au_chemin(donnees, reglage.chemin)
            if brut is None or brut == {} or brut == []:
                items.append(_projeter(reglage, STATUT_VIDE, None, version, None))
                continue
            try:
                items.append(_projeter(reglage, STATUT_FICHIER, valider_valeur(reglage, brut), version, None))
            except ReglageRefuse:
                items.append(_projeter(reglage, STATUT_FICHIER_INVALIDE, None, version, None, fichier=brut))
    manquants = [i for i in items if i["manque"]]
    return {
        "chaine": {"valide": lues.chaine_valide, "detail": lues.detail, "maillons": lues.maillons,
                   "lisible": lues.lisible},
        "total": len(items), "manquants": len(manquants),
        "reglages": items,
    }


def journal(limite: int = JOURNAL_MAX) -> list[dict[str, Any]]:
    """Les derniers gestes de la direction, du plus récent au plus ancien (chaîne valide seulement)."""
    if adoptees().chaine_valide is False or stockage.connexion_courante() is None:
        return []
    return list(reversed(magasin.lire_chaine()[-limite:]))
