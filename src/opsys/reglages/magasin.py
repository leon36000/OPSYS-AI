"""Magasin des valeurs ADOPTÉES : un registre append-only et CHAÎNÉ (qui, quand, ancienne valeur, nouvelle valeur,
raison, version), avec retour arrière en une opération.

Un maillon = un geste de la direction sur UN réglage (`adoption` ou `retour_arriere`). Chaque maillon porte
l'empreinte du précédent et la sienne : toute modification, suppression, insertion ou réordonnancement d'un maillon
casse la chaîne, et une chaîne cassée n'est SERVIE À PERSONNE (`lecture.adoptees` : les départements retombent sur
ce qu'ils faisaient sans elle ; `adopter` et `revenir` refusent d'ajouter). La valeur en vigueur d'un réglage est
le sommet d'une PILE rejouée depuis la chaîne : une adoption empile, un retour arrière dépile ; pile vide = aucune
valeur adoptée (le fichier du département, puis l'absence, décident).

Ce module ne décide pas QUI a le droit d'adopter : il enregistre un geste déjà approuvé par un humain au niveau requis
(`outils_reglages` de M9, qui lit l'approbateur en base). Il ne lit pas d'horloge : l'instant est celui de la
décision, fourni par l'appelant. Stockage : `registres_maillons` (SQLite et PostgreSQL), département de stockage
`opsys-reglages` ; aucune table ni migration de plus.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .. import stockage
from ..stockage.maillons import EcritureConcurrente
from .declaration import Reglage, ReglageRefuse, valider_valeur

SCHEMA_MAILLON = "opsys.reglage.maillon/v1"
DEPARTEMENT_STOCKAGE = "opsys-reglages"
REGISTRE = "adoptions"
HASH_INITIAL = ""
TYPE_ADOPTION = "adoption"
TYPE_RETOUR = "retour_arriere"
TYPES_MAILLON = (TYPE_ADOPTION, TYPE_RETOUR)
ORIGINE_PROPOSITION = "proposition"
ORIGINE_SAISIE = "saisie"
ORIGINE_RETOUR = "retour_arriere"
RAISON_MIN, RAISON_MAX = 3, 300
CHAMPS_MAILLON = frozenset({
    "schema", "rang", "type", "cle", "departement", "version", "ancienne_valeur", "nouvelle_valeur", "origine", "par",
    "role", "approbation_id", "raison", "quand", "precedent", "empreinte",
})
_HEX = re.compile(r"^[0-9a-f]{64}$")
_ID_COURT = re.compile(r"^[\w.@-]{1,64}$")


class ChaineInvalide(ReglageRefuse):
    """La chaîne des adoptions ne se rejoue pas : aucune valeur adoptée n'est servie, aucun geste n'est accepté."""

    def __init__(self, detail: str):
        super().__init__("REJ-REGLAGE-CHAINE-INVALIDE", detail)


def canonique(valeur: Any) -> str:
    return json.dumps(valeur, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def empreinte(corps: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonique({k: v for k, v in corps.items() if k != "empreinte"}).encode("utf-8")).hexdigest()


def _instant_valide(texte: Any) -> bool:
    if type(texte) is not str or len(texte) > 40:
        return False
    try:
        return dt.datetime.fromisoformat(texte).tzinfo is not None
    except ValueError:
        return False


# ---------------------------------------------------------------------------------------------------------
# Rejeu et vérification de la chaîne (pur)
# ---------------------------------------------------------------------------------------------------------
def rejouer(chaine: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Vérifie la chaîne ET rend, par clé, `{pile, version, dernier}` ; lève `ChaineInvalide` au premier maillon fautif.

    Contrôles par maillon : champs exacts, schéma, rang contigu, empreinte du précédent, empreinte propre, type
    connu, version = nombre de maillons de la clé + 1, ancienne valeur = sommet de la pile, nouvelle valeur cohérente
    avec le geste (une
    adoption empile une valeur différente du sommet, un retour arrière dépile et rend l'avant-dernière)."""
    par_cle: dict[str, dict[str, Any]] = {}
    precedent = HASH_INITIAL
    for rang, maillon in enumerate(chaine):
        def faute(raison: str, rang: int = rang) -> ChaineInvalide:
            return ChaineInvalide(f"maillon {rang} : {raison}")

        if not isinstance(maillon, Mapping) or set(maillon) != CHAMPS_MAILLON:
            raise faute("champs inattendus")
        if maillon["schema"] != SCHEMA_MAILLON or maillon["rang"] != rang or type(maillon["rang"]) is not int:
            raise faute("schéma ou rang")
        if maillon["precedent"] != precedent:
            raise faute("lien avec le maillon précédent rompu")
        if not isinstance(maillon["empreinte"], str) or not _HEX.match(maillon["empreinte"]) \
                or maillon["empreinte"] != empreinte(maillon):
            raise faute("empreinte")
        if maillon["type"] not in TYPES_MAILLON or not isinstance(maillon["cle"], str):
            raise faute("type ou clé")
        if not _instant_valide(maillon["quand"]):
            raise faute("instant")
        etat = par_cle.setdefault(maillon["cle"], {"pile": [], "version": 0, "dernier": None})
        pile = etat["pile"]
        sommet = pile[-1] if pile else None
        if maillon["version"] != etat["version"] + 1 or type(maillon["version"]) is not int:
            raise faute("version")
        if maillon["ancienne_valeur"] != sommet:
            raise faute("ancienne valeur différente de la valeur en vigueur")
        if maillon["type"] == TYPE_ADOPTION:
            if maillon["nouvelle_valeur"] is None or maillon["nouvelle_valeur"] == sommet:
                raise faute("adoption sans changement")
            pile.append(maillon["nouvelle_valeur"])
        else:
            if not pile:
                raise faute("retour arrière sans adoption à annuler")
            pile.pop()
            if maillon["nouvelle_valeur"] != (pile[-1] if pile else None):
                raise faute("retour arrière vers une autre valeur que la précédente")
        etat["version"] = maillon["version"]
        etat["dernier"] = rang
        precedent = maillon["empreinte"]
    return par_cle


def lire_chaine() -> list[dict[str, Any]]:
    """Les maillons tels que stockés (sans les juger), dans la transaction courante."""
    return [dict(m) for m in stockage.maillons(DEPARTEMENT_STOCKAGE, REGISTRE)]


def chaine_verifiee() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    chaine = lire_chaine()
    return chaine, rejouer(chaine)


def valeur_en_vigueur(rejeu: Mapping[str, Mapping[str, Any]], cle: str) -> Any:
    etat = rejeu.get(cle)
    return etat["pile"][-1] if etat and etat["pile"] else None


def version_de(rejeu: Mapping[str, Mapping[str, Any]], cle: str) -> int:
    etat = rejeu.get(cle)
    return etat["version"] if etat else 0


# ---------------------------------------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------------------------------------
def valider_raison(raison: Any) -> str:
    """Une raison de 3 à 300 caractères imprimables, SANS renseignement personnel détectable (courriel, téléphone, NAS,
    adresse…) : le magasin est un journal durable, pas un endroit où ranger une personne."""
    if not isinstance(raison, str):
        raise ReglageRefuse("REJ-REGLAGE-RAISON", "une raison de texte est requise")
    propre = " ".join(raison.split())
    if not RAISON_MIN <= len(propre) <= RAISON_MAX or not propre.isprintable():
        raise ReglageRefuse("REJ-REGLAGE-RAISON", f"raison imprimable de {RAISON_MIN} à {RAISON_MAX} caractères")
    from ..observabilite.pii import MasqueurMotifs

    if MasqueurMotifs(bytes(32)).contient_pii(propre):
        raise ReglageRefuse(
            "REJ-REGLAGE-RAISON-PII",
            "la raison semble contenir un renseignement personnel (courriel, téléphone, adresse, nom…) : le retirer",
        )
    return propre


def _exiger_connexion(cnx: Any) -> None:
    if cnx is None or cnx is not stockage.connexion_courante():
        raise ReglageRefuse("REJ-REGLAGE-TRANSACTION", "transaction courante requise")


def _verifier_gestes(par: Any, role: Any, approbation_id: Any, quand: Any) -> None:
    if not (isinstance(par, str) and _ID_COURT.match(par) and isinstance(role, str) and _ID_COURT.match(role)
            and isinstance(approbation_id, str) and _ID_COURT.match(approbation_id)):
        raise ReglageRefuse("REJ-REGLAGE-SIGNATURE", "personne, rôle et demande approuvée requis")
    if not _instant_valide(quand):
        raise ReglageRefuse("REJ-REGLAGE-INSTANT", "instant RFC 3339 à fuseau explicite requis")


def _verifier_version(attendue: Any, courante: int) -> None:
    if attendue is None:
        return
    if type(attendue) is not int or attendue < 0:
        raise ReglageRefuse("REJ-REGLAGE-VERSION", "version attendue : entier positif ou nul")
    if attendue != courante:
        raise ReglageRefuse(
            "REJ-REGLAGE-VERSION",
            f"le réglage a changé depuis la lecture (version attendue {attendue}, courante {courante}) : relire",
        )


def _ajouter(chaine: Sequence[Mapping[str, Any]], corps: dict[str, Any]) -> dict[str, Any]:
    precedent = chaine[-1]["empreinte"] if chaine else HASH_INITIAL
    maillon = {"schema": SCHEMA_MAILLON, "rang": len(chaine), "precedent": precedent, **corps}
    maillon["empreinte"] = empreinte(maillon)
    try:
        stockage.maillons(DEPARTEMENT_STOCKAGE, REGISTRE).append(maillon, rang_attendu=len(chaine))
    except EcritureConcurrente:
        raise ReglageRefuse("REJ-REGLAGE-CONCURRENCE", "un autre geste vient d'être enregistré : relire") from None
    return maillon


def adopter(
    cnx: Any, reglage: Reglage, valeur_brute: Any, *, par: str, role: str, approbation_id: str, raison: Any, quand: str,
    version_attendue: int | None = None,
) -> dict[str, Any]:
    """Adopte la valeur d'un réglage. Idempotent : adopter la valeur déjà en vigueur ne change rien (`deja_adopte`,
    aucun maillon). Valide d'abord (type et bornes de la déclaration), vérifie la chaîne, puis écrit UN maillon."""
    _exiger_connexion(cnx)
    valeur = valider_valeur(reglage, valeur_brute)
    raison = valider_raison(raison)
    _verifier_gestes(par, role, approbation_id, quand)
    chaine, rejeu = chaine_verifiee()
    courante = valeur_en_vigueur(rejeu, reglage.cle)
    version = version_de(rejeu, reglage.cle)
    if courante == valeur:
        return {"statut": "deja_adopte", "cle": reglage.cle, "version": version, "valeur": valeur}
    _verifier_version(version_attendue, version)
    proposee = reglage.proposition is not None and reglage.proposition.valeur == valeur
    maillon = _ajouter(chaine, {
        "type": TYPE_ADOPTION, "cle": reglage.cle, "departement": reglage.departement, "version": version + 1,
        "ancienne_valeur": courante, "nouvelle_valeur": valeur,
        "origine": ORIGINE_PROPOSITION if proposee else ORIGINE_SAISIE, "par": par, "role": role,
        "approbation_id": approbation_id, "raison": raison, "quand": quand,
    })
    return {"statut": "adopte", "cle": reglage.cle, "version": maillon["version"], "valeur": valeur,
            "ancienne_valeur": courante, "rang": maillon["rang"], "empreinte": maillon["empreinte"],
            "origine": maillon["origine"]}


def revenir(
    cnx: Any, reglage: Reglage, *, par: str, role: str, approbation_id: str, raison: Any, quand: str,
    version_attendue: int | None = None,
) -> dict[str, Any]:
    """Retour arrière en UNE opération : retire la valeur en vigueur et rétablit la précédente (ou aucune : le
    fichier du département, puis l'absence, reprennent). Refusé s'il n'y a rien à annuler."""
    _exiger_connexion(cnx)
    raison = valider_raison(raison)
    _verifier_gestes(par, role, approbation_id, quand)
    chaine, rejeu = chaine_verifiee()
    etat = rejeu.get(reglage.cle)
    if not etat or not etat["pile"]:
        raise ReglageRefuse("REJ-REGLAGE-RIEN-A-ANNULER", "aucune valeur adoptée pour ce réglage : rien à annuler")
    _verifier_version(version_attendue, etat["version"])
    pile = etat["pile"]
    maillon = _ajouter(chaine, {
        "type": TYPE_RETOUR, "cle": reglage.cle, "departement": reglage.departement, "version": etat["version"] + 1,
        "ancienne_valeur": pile[-1], "nouvelle_valeur": pile[-2] if len(pile) > 1 else None, "origine": ORIGINE_RETOUR,
        "par": par, "role": role, "approbation_id": approbation_id, "raison": raison, "quand": quand,
    })
    return {"statut": "retour_arriere", "cle": reglage.cle, "version": maillon["version"],
            "valeur": maillon["nouvelle_valeur"], "ancienne_valeur": maillon["ancienne_valeur"],
            "rang": maillon["rang"], "empreinte": maillon["empreinte"]}
