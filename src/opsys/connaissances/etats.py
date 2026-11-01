"""États d'une version : toujours le DERNIER événement de `connaissances_etats` (jamais un champ modifiable).

Une transition est un INSERT conditionnel atomique : elle n'écrit que si l'état courant est encore celui que l'appelant
a lu. Deux soumissions simultanées de la même transition (double clic, rejeu) n'en produisent donc qu'une.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, bindparam, func, insert, literal, select

from ..stockage.schema import CONNAISSANCES_ETATS as ETATS_T
from ..stockage.schema import CONNAISSANCES_SOURCES as SOURCES_T
from ..stockage.schema import CONNAISSANCES_VERSIONS as VERSIONS_T
from .codes import RAISON_REQUISE, TRANSITION_INTERDITE, ErreurConnaissances
from .modele import ETAT_RETIRE, RAISON_MAX, RAISON_MIN, TRANSITIONS


def etat_courant(cnx: Connection, version_id: str) -> str | None:
    return cnx.execute(
        select(ETATS_T.c.etat).where(ETATS_T.c.version_id == version_id).order_by(ETATS_T.c.id.desc()).limit(1)
    ).scalar_one_or_none()


def historique(cnx: Connection, version_id: str) -> list[dict[str, Any]]:
    lignes = cnx.execute(select(ETATS_T).where(ETATS_T.c.version_id == version_id).order_by(ETATS_T.c.id)).mappings()
    return [{"etat": r["etat"], "par": r["par"], "mode": r["mode"], "role": r["role"], "raison": r["raison"],
             "quand": r["quand"], "controles": json.loads(r["controles"]) if r["controles"] else None}
            for r in lignes]


def valider_raison(raison: object, *, requise: bool) -> str | None:
    if raison is None or (isinstance(raison, str) and not raison.strip()):
        if requise:
            raise ErreurConnaissances(RAISON_REQUISE, f"raison obligatoire ({RAISON_MIN} à {RAISON_MAX} caractères)")
        return None
    if not isinstance(raison, str) or not RAISON_MIN <= len(raison.strip()) <= RAISON_MAX or not raison.isprintable():
        raise ErreurConnaissances(RAISON_REQUISE, f"raison : {RAISON_MIN} à {RAISON_MAX} caractères imprimables")
    return raison.strip()


def ajouter_etat(cnx: Connection, version_id: str, nouvel_etat: str, *, attendu: str | None, par: str, mode: str,
                 role: str | None, raison: str | None, controles: dict[str, Any] | None, quand: str) -> None:
    """Ajoute l'événement `nouvel_etat` si l'état courant est `attendu` ET que la transition est permise."""
    if nouvel_etat not in TRANSITIONS.get(attendu, frozenset()):
        raise ErreurConnaissances(TRANSITION_INTERDITE, f"{attendu or 'aucun état'} → {nouvel_etat} n'est pas permis")
    if nouvel_etat == ETAT_RETIRE:
        raison = valider_raison(raison, requise=True)
    courant = (select(ETATS_T.c.etat).where(ETATS_T.c.version_id == version_id)
               .order_by(ETATS_T.c.id.desc()).limit(1).scalar_subquery())
    valeurs = {"version_id": version_id, "etat": nouvel_etat, "par": par, "mode": mode, "role": role, "raison": raison,
               "controles": json.dumps(controles, ensure_ascii=False, sort_keys=True) if controles else None,
               "quand": quand}
    if attendu is None:
        if etat_courant(cnx, version_id) is not None:
            raise ErreurConnaissances(TRANSITION_INTERDITE, "cette version a déjà un état")
        cnx.execute(insert(ETATS_T).values(**valeurs))
        return
    # PostgreSQL (READ COMMITTED) : sans verrou, deux transactions lisent TOUTES DEUX l'état « attendu » (l'événement
    # de l'autre n'est pas encore validé) et écrivent chacune leur transition : une version retirée pouvait redevenir
    # « revue ». Le verrou de ligne de la version sérialise les transitions ; le second écrivain attend, puis relit
    # l'état validé par le premier (nouvel instantané à chaque instruction) et se voit refuser. SQLite : sans effet
    # (écrivain unique).
    cnx.execute(select(VERSIONS_T.c.version_id).where(VERSIONS_T.c.version_id == version_id).with_for_update())
    colonnes = list(valeurs)
    sel = select(*(literal(valeurs[c]) if valeurs[c] is not None else literal(None) for c in colonnes)).where(
        courant == bindparam("attendu", attendu))
    # RETURNING plutôt que `rowcount` : sur PostgreSQL (psycopg), `rowcount` d'un INSERT … SELECT vaut -1, ce qui
    # rejetait TOUTE transition légitime. Une ligne rendue = la condition « état courant == attendu » tenait au moment
    # de l'écriture.
    resultat = cnx.execute(insert(ETATS_T).from_select(colonnes, sel).returning(ETATS_T.c.id))
    if resultat.first() is None:
        raise ErreurConnaissances(
            TRANSITION_INTERDITE, f"l'état courant n'est plus « {attendu} » : transition {nouvel_etat} non appliquée")


def versions_eligibles(cnx: Connection, departements: Sequence[str], etats: Sequence[str], instant: str
                       ) -> list[dict[str, Any]]:
    """Pour chaque source des bases `departements` : la version de plus grand numéro dont l'état À `instant` figure dans
    `etats`. L'état à `instant` est le dernier événement dont `quand <= instant` : on peut ainsi relire une base telle
    qu'elle était publiée à une date passée."""
    if not departements or not etats:
        return []
    dernier = (select(func.max(ETATS_T.c.id)).where(ETATS_T.c.version_id == VERSIONS_T.c.version_id,
                                                    ETATS_T.c.quand <= instant).correlate(VERSIONS_T).scalar_subquery())
    lignes = cnx.execute(
        select(VERSIONS_T, SOURCES_T.c.departement, SOURCES_T.c.cle, SOURCES_T.c.titre, SOURCES_T.c.domaine,
               ETATS_T.c.etat.label("etat"))
        .join(SOURCES_T, SOURCES_T.c.source_id == VERSIONS_T.c.source_id)
        .join(ETATS_T, ETATS_T.c.id == dernier)
        .where(SOURCES_T.c.departement.in_(list(departements)), ETATS_T.c.etat.in_(list(etats)))
        .order_by(VERSIONS_T.c.source_id, VERSIONS_T.c.numero.desc())
    ).mappings()
    retenues: dict[str, dict[str, Any]] = {}
    for ligne in lignes:
        retenues.setdefault(ligne["source_id"], dict(ligne))  # tri : le plus grand numéro d'abord
    return list(retenues.values())
