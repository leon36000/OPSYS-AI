"""Profil de marque v2 (M7-MARQUE) : les champs étendus que le PROPRIÉTAIRE déclare, leur validation et leur complétude.

Le contrat gelé v1 (`brand_schema`, cinq champs) reste la loi du socle du profil ; ce module lit l'EXTENSION
additive décrite par `contracts/brand-contract.v2.yaml`. Un profil v1 est lu tel quel : c'est un profil v2 dont aucun
champ étendu n'est déclaré (`version_de_lecture`).

Doctrine (AGENTS.md « fail-closed », « données inventées ») :

  - Aucun champ n'est inventé ni deviné : un champ absent est DIT manquant (`completude`), avec ce qu'il faut demander
  au
    propriétaire. Les dimensions de conformité qui en dépendent sont « non évaluables », jamais notées par défaut.
  - Un énoncé POSITIF (promesse, avantages, preuve sociale, valeurs, zones, objections, mentions) n'est repris nulle
  part
    tant que le propriétaire ne l'a pas VALIDÉ (`validation_champs`) : il est « à valider par Nathan ». Une RESTRICTION
    (mots interdits, voix, style…) s'applique dès qu'elle est déclarée.
  - Chaque valeur est une donnée, jamais une instruction : texte d'une ligne, sans caractère de contrôle, borné. Un
  champ
    qui voudrait glisser un saut de ligne ou une consigne dans un guide est refusé à la déclaration.

Module pur : aucune entrée-sortie (hors lecture unique du contrat YAML).
"""

from __future__ import annotations

import functools
import unicodedata
from pathlib import Path
from typing import Any

import yaml

_CONTRAT = Path(__file__).resolve().parents[3] / "contracts" / "brand-contract.v2.yaml"

ETAT_ABSENT = "absent"
ETAT_A_VALIDER = "declare_a_valider"
ETAT_VALIDE = "valide"
ETAT_ACTIF = "declare"  # une restriction : en vigueur dès sa déclaration

STATUT_VALIDE = "valide"
STATUT_A_VALIDER = "a_valider"


@functools.lru_cache(maxsize=1)
def contrat() -> dict[str, Any]:
    """Le contrat v2 (source unique des champs et des bornes). `OSError` s'il est introuvable ou illisible."""
    try:
        brut = yaml.safe_load(_CONTRAT.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise OSError(f"Contrat v2 introuvable : {_CONTRAT}") from None
    if not isinstance(brut, dict) or brut.get("schema_version") != 2:
        raise OSError("Le contrat v2 doit être un mapping de schema_version 2")
    return brut


def champs() -> dict[str, dict[str, Any]]:
    return contrat()["champs"]


def noms_champs() -> tuple[str, ...]:
    return tuple(champs())


def champs_valides_par_proprietaire() -> tuple[str, ...]:
    return tuple(contrat()["champs_valides_par_proprietaire"])


def plateformes_connues() -> tuple[str, ...]:
    return tuple(contrat()["plateformes"])


# -- validation d'une valeur -------------------------------------------------------------------------------------
def _ligne(valeur: Any, champ: str, *, max_len: int, min_len: int = 1) -> str:
    """Un texte d'UNE ligne, imprimable, borné ; refuse tout caractère de contrôle ou de format (il couperait un motif
    ou injecterait une consigne dans un guide)."""
    if not isinstance(valeur, str):
        raise ValueError(f"{champ} : un texte est attendu")
    propre = valeur.strip()
    if not min_len <= len(propre) <= max_len:
        raise ValueError(f"{champ} : {min_len} à {max_len} caractères")
    if any(unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} for c in propre):
        raise ValueError(f"{champ} : caractère de contrôle ou saut de ligne interdit")
    return propre


def _entier(valeur: Any, champ: str, bornes: dict[str, int]) -> int:
    if type(valeur) is not int or not bornes["min"] <= valeur <= bornes["max"]:
        raise ValueError(f"{champ} : entier de {bornes['min']} à {bornes['max']}")
    return valeur


def _liste(valeur: Any, champ: str, defn: dict[str, Any]) -> list[str]:
    if not isinstance(valeur, list) or len(valeur) > defn["max_items"]:
        raise ValueError(f"{champ} : au plus {defn['max_items']} textes")
    propres = [_ligne(v, champ, max_len=defn["max_len"], min_len=defn.get("min_len", 1)) for v in valeur]
    if len(set(propres)) != len(propres):
        raise ValueError(f"{champ} : valeur en double")
    return propres


def _objections(valeur: Any, champ: str, defn: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(valeur, list) or len(valeur) > defn["max_items"]:
        raise ValueError(f"{champ} : au plus {defn['max_items']} objections")
    sortie = []
    for item in valeur:
        if not isinstance(item, dict) or set(item) != {"objection", "reponse"}:
            raise ValueError(f"{champ} : chaque entrée est {{objection, reponse}}")
        sortie.append(
            {
                "objection": _ligne(item["objection"], f"{champ}.objection", max_len=defn["max_len_objection"]),
                "reponse": _ligne(item["reponse"], f"{champ}.reponse", max_len=defn["max_len_reponse"]),
            }
        )
    return sortie


def _voix(valeur: Any, champ: str) -> dict[str, Any]:
    c = contrat()["voix"]
    if (
        not isinstance(valeur, dict)
        or not valeur
        or set(valeur) - {"adresse", "exclamations_max", "majuscules_max_pct", "emojis_max"}
    ):
        raise ValueError(f"{champ} : adresse, exclamations_max, majuscules_max_pct, emojis_max (au moins un)")
    sortie: dict[str, Any] = {}
    if "adresse" in valeur:
        if valeur["adresse"] not in c["adresses"]:
            raise ValueError(f"{champ}.adresse : {' ou '.join(c['adresses'])}")
        sortie["adresse"] = valeur["adresse"]
    for cle in ("exclamations_max", "majuscules_max_pct", "emojis_max"):
        if cle in valeur:
            sortie[cle] = _entier(valeur[cle], f"{champ}.{cle}", c[cle])
    return sortie


def _style(valeur: Any, champ: str) -> dict[str, dict[str, int]]:
    c = contrat()["style"]
    if not isinstance(valeur, dict) or set(valeur) - set(plateformes_connues()):
        raise ValueError(f"{champ} : plateformes connues seulement ({', '.join(plateformes_connues())})")
    sortie: dict[str, dict[str, int]] = {}
    for plateforme, regles in valeur.items():
        if not isinstance(regles, dict) or not regles or set(regles) - set(c):
            raise ValueError(f"{champ}.{plateforme} : {', '.join(c)} (au moins un)")
        sortie[plateforme] = {cle: _entier(v, f"{champ}.{plateforme}.{cle}", c[cle]) for cle, v in regles.items()}
        mini, maxi = sortie[plateforme].get("longueur_min"), sortie[plateforme].get("longueur_max")
        if mini is not None and maxi is not None and mini > maxi:
            raise ValueError(f"{champ}.{plateforme} : longueur_min dépasse longueur_max")
    return sortie


def _validation(valeur: Any, champ: str) -> dict[str, dict[str, str]]:
    permis = set(champs_valides_par_proprietaire())
    if not isinstance(valeur, dict) or set(valeur) - permis:
        raise ValueError(f"{champ} : champs validables seulement ({', '.join(sorted(permis))})")
    sortie = {}
    for nom, entree in valeur.items():
        if (
            not isinstance(entree, dict)
            or set(entree) != {"statut", "par", "le"}
            or entree["statut"] not in (STATUT_VALIDE, STATUT_A_VALIDER)
        ):
            raise ValueError(f"{champ}.{nom} : {{statut: valide|a_valider, par, le}}")
        sortie[nom] = {
            "statut": entree["statut"],
            "par": _ligne(entree["par"], f"{champ}.{nom}.par", max_len=64),
            "le": _ligne(entree["le"], f"{champ}.{nom}.le", max_len=40),
        }
    return sortie


def valider_extension(profil: dict[str, Any]) -> dict[str, Any]:
    """Valide les champs étendus PRÉSENTS du profil et rend les valeurs normalisées (`{champ: valeur}`). Un champ
    inconnu du contrat v2 n'est pas touché (le v1 tolère des champs supplémentaires JSON). `ValueError` au premier
    champ hors forme : le message dit le champ, jamais la valeur."""
    sortie: dict[str, Any] = {}
    for nom, defn in champs().items():
        if nom not in profil:
            continue
        valeur = profil[nom]
        kind = defn["kind"]
        if kind == "texte":
            sortie[nom] = _ligne(valeur, nom, max_len=defn["max_len"])
        elif kind == "liste_textes":
            sortie[nom] = _liste(valeur, nom, defn)
        elif kind == "objections":
            sortie[nom] = _objections(valeur, nom, defn)
        elif kind == "voix":
            sortie[nom] = _voix(valeur, nom)
        elif kind == "style_plateforme":
            sortie[nom] = _style(valeur, nom)
        else:
            sortie[nom] = _validation(valeur, nom)
    return sortie


def assainir(profil: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Lecture TOLÉRANTE d'un profil déjà enregistré : chaque champ étendu est validé seul ; un champ hors forme (écrit
    avant l'existence du contrat v2 sous un nom qui est devenu un champ étendu) est RETIRÉ de la lecture et nommé,
    jamais
    deviné ni appliqué. Rend `(profil sans les champs invalides, noms ignorés)`. Un profil sans champ invalide est rendu
    tel quel (même objet logique, donc même empreinte)."""
    ignores: list[str] = []
    propre = dict(profil)
    for nom in champs():
        if nom not in profil:
            continue
        try:
            valider_extension({nom: profil[nom]})
        except ValueError:
            ignores.append(nom)
            del propre[nom]
    return propre, ignores


def normaliser(profil: dict[str, Any]) -> dict[str, Any]:
    """Le profil avec ses champs étendus normalisés (espaces retirés). Lève `ValueError` comme `valider_extension`."""
    return {**profil, **valider_extension(profil)}


# -- lecture ------------------------------------------------------------------------------------------------------
def version_de_lecture(profil: dict[str, Any]) -> str:
    """`v2` si au moins un champ étendu est déclaré, sinon `v1` : le profil à cinq champs reste lisible tel quel."""
    return "v2" if any(nom in profil for nom in champs()) else "v1"


def est_valide(profil: dict[str, Any], champ: str) -> bool:
    """Vrai seulement si le propriétaire a VALIDÉ ce champ positif (statut `valide`). Fail-closed : tout le reste est
    « à valider »."""
    validation = profil.get("validation_champs")
    entree = validation.get(champ) if isinstance(validation, dict) else None
    return isinstance(entree, dict) and entree.get("statut") == STATUT_VALIDE


def etat_champ(profil: dict[str, Any], champ: str) -> str:
    defn = champs()[champ]
    present = profil.get(champ)
    if present in (None, "", [], {}):
        return ETAT_ABSENT
    if defn["famille"] == "positif":
        return ETAT_VALIDE if est_valide(profil, champ) else ETAT_A_VALIDER
    return ETAT_ACTIF


_A_FOURNIR = {
    "promesse": "la promesse de la marque, en une phrase que tu assumes",
    "avantages": "les avantages que l'entreprise accepte de citer",
    "zones_desservies": "les villes ou régions desservies",
    "valeurs": "les valeurs de l'entreprise",
    "objections_frequentes": "les objections fréquentes des clients et la réponse que tu acceptes de donner",
    "preuve_sociale": "les énoncés de preuve sociale que tu acceptes de citer (aucun nombre inventé)",
    "mentions_requises": "les mentions que tout contenu public doit porter (ex. licence)",
    "garanties_a_valider": "les garanties envisagées mais pas encore validées (elles ne seront jamais citées)",
    "mots_interdits": "les mots que la marque ne dit jamais",
    "messages_interdits": "les messages ou formules que la marque ne dit jamais",
    "voix": "la voix : vouvoiement ou tutoiement, limite d'exclamations, de majuscules, d'émojis",
    "style_plateforme": "le style par plateforme : longueurs, nombre de mots-clics, d'émojis",
}
# Ce que chaque dimension de conformité exige du profil pour être évaluable.
DIMENSIONS_ET_CHAMPS = {
    "mots_interdits": ("mots_interdits",),
    "messages_interdits": ("messages_interdits",),
    "ton": ("voix",),
    "style_plateforme": ("style_plateforme",),
    "mentions_requises": ("mentions_requises",),
}


def completude(profil: dict[str, Any]) -> dict[str, Any]:
    """L'état de chaque champ étendu (absent, déclaré à valider, validé, ou en vigueur) et, pour chaque champ absent,
    ce qu'il faut demander au propriétaire. Aucune valeur par défaut : `a_fournir` est une liste de questions."""
    etats = {nom: etat_champ(profil, nom) for nom in champs() if nom != "validation_champs"}
    return {
        "version_de_lecture": version_de_lecture(profil),
        "champs": etats,
        "a_fournir": [f"{nom} : {_A_FOURNIR[nom]}" for nom, etat in etats.items() if etat == ETAT_ABSENT],
        "a_valider_par_le_proprietaire": [nom for nom, etat in etats.items() if etat == ETAT_A_VALIDER],
    }
