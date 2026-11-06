"""Projection strictement fermée de l'état d'une déclaration de matériaux M6."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, select

from ..stockage import codec
from ..stockage.portabilite import nb_octets
from ..stockage.schema import MUTATIONS_APPLIQUEES

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_OUTILS = frozenset({
    "m6_declarer_materiaux_utilises",
    "m6_declarer_materiaux_avec_preuves_appareil",
})
_INDETERMINEE = "indeterminee"


def _identifiant_valide(valeur: object) -> bool:
    if type(valeur) is not str or not valeur.strip() or len(valeur) > 128:
        return False
    if any(unicodedata.category(caractere) in {"Cc", "Cs"} for caractere in valeur):
        return False
    try:
        valeur.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return True


def projeter(ligne: Mapping[str, Any] | None) -> str:
    """Projette un claim M6 sur trois états fermés, sans exposer l'accusé stocké."""
    if ligne is None or ligne.get("outil") not in _OUTILS:
        return _INDETERMINEE
    texte = ligne.get("reponse")
    if type(texte) is not str or len(texte) > 16_384:
        return _INDETERMINEE
    try:
        reponse = codec.decoder_strict(texte, profondeur_max=16)
    except ValueError:
        return _INDETERMINEE
    if type(reponse) is not dict:
        return _INDETERMINEE

    statut = ligne.get("statut")
    if statut == "ok":
        if set(reponse) != {"ok", "resultat"} or reponse["ok"] is not True:
            return _INDETERMINEE
        resultat = reponse["resultat"]
        if type(resultat) is not dict or type(resultat.get("accepte")) is not bool:
            return _INDETERMINEE
        if resultat["accepte"] is False:
            verdict = resultat.get("verdict")
            code = verdict.get("code") if type(verdict) is dict else None
            return "refusee" if (
                set(resultat) == {"accepte", "verdict"}
                and type(code) is str and code.startswith("REJ-")
            ) else _INDETERMINEE
        registre = resultat.get("registre")
        details = resultat.get("resultat")
        if (
            set(resultat) != {"accepte", "resultat", "registre"}
            or type(details) is not dict
            or type(registre) is not dict
            or set(registre) != {"taille", "hash_tete"}
            or type(registre.get("taille")) is not int or registre["taille"] < 0
            or (registre.get("hash_tete") is not None
                and (type(registre["hash_tete"]) is not str or _HASH.fullmatch(registre["hash_tete"]) is None))
        ):
            return _INDETERMINEE
        return "acceptee"

    if statut == "refus_metier":
        erreur = reponse.get("erreur")
        details = reponse.get("details")
        if (
            set(reponse) == {"ok", "erreur", "details"}
            and reponse.get("ok") is False
            and type(erreur) is str
            and erreur in {"arguments_invalides", "refus_metier", "hors_portee_role"}
            and ((type(details) is str) or (type(details) is list and all(type(x) is str for x in details)))
        ):
            return "refusee"
    return _INDETERMINEE


def lire_etat(cnx: Connection, appareil: object, cle: object) -> str:
    """Lit une paire exacte et borne la réponse avant de la charger dans l'application."""
    if not _identifiant_valide(appareil) or not _identifiant_valide(cle):
        return _INDETERMINEE
    condition = (
        (MUTATIONS_APPLIQUEES.c.appareil == appareil)
        & (MUTATIONS_APPLIQUEES.c.cle_idempotence == cle)
    )
    octets = nb_octets(MUTATIONS_APPLIQUEES.c.reponse)
    ligne = cnx.execute(
        select(
            MUTATIONS_APPLIQUEES.c.outil,
            MUTATIONS_APPLIQUEES.c.statut,
            MUTATIONS_APPLIQUEES.c.reponse,
        ).where(condition & octets.between(1, 16_384))
    ).mappings().one_or_none()
    return projeter(ligne)
