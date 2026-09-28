"""`publier()` : outbox durcie (ADR-0009 §3) — écriture métier et événement, une seule transaction.

`publier` n'ouvre PAS elle-même de transaction indépendante : `stockage.transaction()` réutilise la
transaction déjà ouverte par l'outil appelant (`outils.executer_atomique`) sous forme de point de
sauvegarde, ou en ouvre une nouvelle si appelée hors de tout outil (tests, CLI). Si l'outil échoue
après avoir publié, la transaction entière — écriture métier et événement — est annulée.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select

from ..stockage import codec, inserer, transaction
from ..stockage.schema import EVENEMENTS_SORTANTS
from .schemas import TypeEvenementInconnu, erreurs_charge

__all__ = ["ChargeInvalide", "TypeEvenementInconnu", "deja_publie", "publier"]


class ChargeInvalide(ValueError):
    """La charge ne respecte pas le schéma JSON du catalogue pour ce type : rien n'est écrit."""


def publier(
    type_evenement: str,
    producteur: str,
    charge: Mapping[str, Any],
    *,
    evenement_id: str | None = None,
) -> str:
    """Publie un événement dans `evenements_sortants`, dans la transaction courante.

    Lève `TypeEvenementInconnu` si `type_evenement` n'est pas au catalogue, ou `ChargeInvalide` si
    `charge` ne respecte pas son schéma JSON, objets et tableaux imbriqués compris
    (`schemas.erreurs_charge`) : dans les deux cas, rien n'est écrit. Les deux erreurs héritent de
    `ValueError`, donc un outil de département qui appelle `publier` en cours d'exécution obtient un
    `refus_metier` normal (`outils.executer`) plutôt qu'une panne.

    `evenement_id` : `uuid4().hex` par défaut. Fourni par l'appelant, il porte l'idempotence du
    producteur (`UNIQUE` en clé primaire) : publier deux fois le même id est un no-op qui rend le
    même id, sans créer de second événement — utile pour un producteur qui rejoue un appel après une
    panne réseau, jamais pour republier un événement déjà accepté sous un autre id.
    """
    if not producteur or not producteur.strip():
        raise ValueError("producteur requis")
    erreurs = erreurs_charge(type_evenement, charge)  # TypeEvenementInconnu si absent du catalogue
    if erreurs:
        raise ChargeInvalide(f"{type_evenement} : charge invalide : {'; '.join(erreurs)}")
    ident = evenement_id or uuid.uuid4().hex
    with transaction() as cnx:
        insertion = inserer(cnx)(EVENEMENTS_SORTANTS).values(
            evenement_id=ident,
            type_evenement=type_evenement,
            producteur=producteur,
            charge=codec.encoder(dict(charge)),
            cree_le=dt.datetime.now(dt.UTC).isoformat(),
        )
        cnx.execute(insertion.on_conflict_do_nothing(index_elements=[EVENEMENTS_SORTANTS.c.evenement_id]))
    return ident


def deja_publie(evenement_id: str) -> bool:
    """Vrai si `evenements_sortants` porte déjà cet `evenement_id`, lu dans la transaction courante.

    Pour un producteur dont l'identifiant d'événement encode un état terminal (ex. M6,
    `m6-variance-<wct_id>-evaluee`) : il évite de recalculer ce qu'il sait déjà publié. Les
    départements passent par cette fonction plutôt que par la table du bus, qui reste au socle.
    """
    with transaction() as cnx:
        ligne = cnx.execute(
            select(EVENEMENTS_SORTANTS.c.evenement_id).where(EVENEMENTS_SORTANTS.c.evenement_id == evenement_id)
        ).first()
    return ligne is not None
