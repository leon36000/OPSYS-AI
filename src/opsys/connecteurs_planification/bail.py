"""Bail par ressource : un seul exécuteur à la fois pour un compte courriel, un site WordPress ou un compte social.

Un bail est une ligne de `planificateur_baux` (porteur, jeton de fencing croissant, expiration). `acquerir` est
atomique (transaction d'écriture : `BEGIN IMMEDIATE` sur SQLite, verrou de ligne sur PostgreSQL) : deux fils ou deux
processus qui se disputent la même ressource ne l'obtiennent jamais tous les deux. Un bail expiré (processus mort) se
reprend avec un jeton plus grand ; l'ancien porteur le voit au renouvellement suivant (`renouveler` rend `False`) et
s'arrête. Le bail ne remplace pas les gardes métier (sas d'approbation, consommation par comparaison-échange) : il évite
que deux exécuteurs travaillent ensemble, ces gardes empêchent qu'ils agissent deux fois.

Appeler HORS d'une transaction métier (chaque opération ouvre la sienne et la valide aussitôt).
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from .. import stockage
from ..stockage.schema import PLANIFICATEUR_BAUX

DUREE_DEFAUT_S = 120


@dataclasses.dataclass(frozen=True)
class Bail:
    ressource: str
    porteur: str
    jeton: int
    expire_epoch: int


def acquerir(ressource: str, porteur: str, duree_s: int = DUREE_DEFAUT_S, *,
             horloge: Callable[[], float] = time.time) -> Bail | None:
    """Le bail, ou `None` si un autre porteur en détient un qui n'a pas expiré."""
    if not ressource or len(ressource) > 160 or not porteur or len(porteur) > 80 or type(duree_s) is not int \
            or not 1 <= duree_s <= 3600:
        raise ValueError("bail : ressource (160), porteur (80) et durée de 1 à 3600 s requis")
    maintenant = int(horloge())
    try:
        with stockage.transaction() as cnx:
            ligne = cnx.execute(select(PLANIFICATEUR_BAUX).where(
                PLANIFICATEUR_BAUX.c.ressource == ressource).with_for_update()).mappings().first()
            if ligne is None:
                cnx.execute(insert(PLANIFICATEUR_BAUX).values(
                    ressource=ressource, porteur=porteur, jeton=1, acquis_epoch=maintenant,
                    expire_epoch=maintenant + duree_s))
                return Bail(ressource, porteur, 1, maintenant + duree_s)
            if ligne["expire_epoch"] > maintenant and ligne["porteur"] != porteur:
                return None
            jeton = ligne["jeton"] + (0 if ligne["porteur"] == porteur and ligne["expire_epoch"] > maintenant else 1)
            cnx.execute(update(PLANIFICATEUR_BAUX).where(PLANIFICATEUR_BAUX.c.ressource == ressource).values(
                porteur=porteur, jeton=jeton, acquis_epoch=maintenant, expire_epoch=maintenant + duree_s))
            return Bail(ressource, porteur, jeton, maintenant + duree_s)
    except IntegrityError:
        return None  # une autre connexion vient d'insérer le bail : elle le détient


def renouveler(bail: Bail, duree_s: int = DUREE_DEFAUT_S, *, horloge: Callable[[], float] = time.time) -> Bail | None:
    """Prolonge le bail SI ce porteur en est toujours le détenteur au même jeton ; `None` sinon (bail perdu)."""
    maintenant = int(horloge())
    with stockage.transaction() as cnx:
        resultat = cnx.execute(update(PLANIFICATEUR_BAUX).where(
            PLANIFICATEUR_BAUX.c.ressource == bail.ressource, PLANIFICATEUR_BAUX.c.porteur == bail.porteur,
            PLANIFICATEUR_BAUX.c.jeton == bail.jeton, PLANIFICATEUR_BAUX.c.expire_epoch > maintenant,
        ).values(expire_epoch=maintenant + duree_s))
        if resultat.rowcount != 1:
            return None
    return dataclasses.replace(bail, expire_epoch=maintenant + duree_s)


def liberer(bail: Bail) -> None:
    """Rend le bail (sans effet si un autre porteur l'a repris)."""
    with stockage.transaction() as cnx:
        cnx.execute(delete(PLANIFICATEUR_BAUX).where(
            PLANIFICATEUR_BAUX.c.ressource == bail.ressource, PLANIFICATEUR_BAUX.c.porteur == bail.porteur,
            PLANIFICATEUR_BAUX.c.jeton == bail.jeton))


def detenu(ressource: str, *, horloge: Callable[[], float] = time.time) -> dict[str, object] | None:
    """Lecture (console, tests) : le bail courant non expiré, ou `None`."""
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(PLANIFICATEUR_BAUX).where(
            PLANIFICATEUR_BAUX.c.ressource == ressource)).mappings().first()
    if ligne is None or ligne["expire_epoch"] <= int(horloge()):
        return None
    return dict(ligne)
