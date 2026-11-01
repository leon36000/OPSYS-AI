"""Registre des comptes sociaux du client (une Page, un compte, une chaîne) que le sas peut viser.

Registre append-only à chaîne de hachage : `compte_enregistre`, `compte_desactive`. Il ne contient JAMAIS un jeton
d'accès :
seulement `secret_ref` (le NOM du secret dans le coffre). L'exécuteur résout le jeton au moment d'écrire sur le réseau.
Un compte inconnu ou désactivé ne reçoit aucune publication (`REJ-SOCIAL-COMPTE-INCONNU`). Les exigences d'accès de
chaque
réseau (niveau d'application, revue, mode A/B) sont consignées dans `docs/architecture/M7-WORDPRESS-SOCIAL.md` : ce
registre
ne dit pas que le compte est autorisé chez le réseau, seulement que l'entreprise l'a déclaré.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from .. import journal_chaine
from .reseaux import RESEAUX

M_ENREGISTRE = "compte_enregistre"
M_DESACTIVE = "compte_desactive"

REJ_RESEAU = "REJ-SOCIAL-COMPTE-RESEAU"
REJ_COMPTE = "REJ-SOCIAL-COMPTE-INVALIDE"
REJ_SECRET_REF = "REJ-SOCIAL-COMPTE-SECRET-REF"
REJ_EXISTANT = "REJ-SOCIAL-COMPTE-EXISTANT"
REJ_DESACTIVE = "REJ-SOCIAL-COMPTE-DESACTIVE"
REJ_INCONNU = "REJ-SOCIAL-COMPTE-INCONNU"
REJ_JOURNAL = "REJ-SOCIAL-COMPTE-JOURNAL-ALTERE"

_COMPTE = re.compile(r"[a-z0-9][a-z0-9._-]{1,63}")
_NOM_COFFRE = re.compile(r"[a-z0-9][a-z0-9._-]{2,79}")


def _refus(code: str, chemin: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "refus": [{"code": code, "chemin": chemin, "detail": detail}]}


def plier(journal: Iterable[Any]) -> dict[tuple[str, str], dict[str, Any]]:
    comptes: dict[tuple[str, str], dict[str, Any]] = {}
    for maillon in journal:
        if maillon["type"] == M_ENREGISTRE:
            comptes[(maillon["reseau"], maillon["compte"])] = {
                "secret_nom": maillon["secret_ref"]["nom"],
                "fictif": maillon["fictif"],
                "actif": True,
            }
        elif maillon["type"] == M_DESACTIVE:
            comptes[(maillon["reseau"], maillon["compte"])]["actif"] = False
    return comptes


def actifs(journal: Iterable[Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {cle: valeur for cle, valeur in plier(journal).items() if valeur["actif"]}


def enregistrer(
    journal: Any,
    reseau: Any,
    compte: Any,
    secret_ref: Any,
    fictif: Any,
    par: str,
    horodatage: str,
) -> dict[str, Any]:
    if reseau not in RESEAUX:
        return _refus(REJ_RESEAU, "$.reseau", f"un de {list(RESEAUX)} attendu")
    if not isinstance(compte, str) or not _COMPTE.fullmatch(compte):
        return _refus(REJ_COMPTE, "$.compte", "minuscules, chiffres, point, tiret, souligné ; 2 à 64 caractères")
    if type(fictif) is not bool:
        return _refus(REJ_COMPTE, "$.fictif", "booléen attendu")
    if (
        not isinstance(secret_ref, Mapping)
        or set(secret_ref) != {"nom"}
        or not isinstance(secret_ref["nom"], str)
        or not _NOM_COFFRE.fullmatch(secret_ref["nom"])
    ):
        return _refus(
            REJ_SECRET_REF, "$.secret_ref", "{nom} attendu : le NOM du secret dans le coffre, jamais le jeton"
        )
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return _refus(REJ_JOURNAL, "$", "; ".join(problemes[:3]))
    existant = plier(journal).get((reseau, compte))
    if existant is not None:
        if not existant["actif"]:
            return _refus(
                REJ_DESACTIVE, "$.compte", "compte désactivé : un autre identifiant pour un nouvel enregistrement"
            )
        if existant["secret_nom"] == secret_ref["nom"] and existant["fictif"] == fictif:
            return {"accepte": True, "reseau": reseau, "compte": compte, "deja_enregistre": True}
        return _refus(
            REJ_EXISTANT, "$.compte", "ce compte existe avec un autre enregistrement : un compte ne se modifie pas"
        )
    journal_chaine.ajouter(
        journal,
        M_ENREGISTRE,
        {
            "reseau": reseau,
            "compte": compte,
            "secret_ref": {"nom": secret_ref["nom"]},
            "fictif": fictif,
            "par": par,
        },
        horodatage,
    )
    return {"accepte": True, "reseau": reseau, "compte": compte, "deja_enregistre": False}


def desactiver(journal: Any, reseau: str, compte: str, par: str, motif: str, horodatage: str) -> dict[str, Any]:
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return _refus(REJ_JOURNAL, "$", "; ".join(problemes[:3]))
    courant = plier(journal).get((reseau, compte))
    if courant is None:
        return _refus(REJ_INCONNU, "$.compte", f"compte inconnu : {reseau}/{compte}")
    if not courant["actif"]:
        return {"accepte": True, "reseau": reseau, "compte": compte, "deja_desactive": True}
    journal_chaine.ajouter(
        journal, M_DESACTIVE, {"reseau": reseau, "compte": compte, "par": par, "motif": motif[:300]}, horodatage
    )
    return {"accepte": True, "reseau": reseau, "compte": compte, "deja_desactive": False}
