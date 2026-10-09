"""`publier()` : outbox durcie (ADR-0009 §3) — écriture métier et événement, une seule transaction.

`publier` n'ouvre PAS elle-même de transaction indépendante : `stockage.transaction()` réutilise la
transaction déjà ouverte par l'outil appelant (`outils.executer_atomique`) sous forme de point de
sauvegarde, ou en ouvre une nouvelle si appelée hors de tout outil (tests, CLI). Si l'outil échoue
après avoir publié, la transaction entière — écriture métier et événement — est annulée.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from sqlalchemy import Connection, select
from sqlalchemy.exc import SQLAlchemyError

from ..stockage import codec, connexion_courante, inserer, transaction
from ..stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS
from .schemas import TypeEvenementInconnu, erreurs_charge, schema

__all__ = ["ChargeInvalide", "TypeEvenementInconnu", "charge_publiee", "deja_publie", "publier"]


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


def charge_publiee(type_evenement: str, evenement_id: str) -> dict[str, Any] | None:
    """Charge d'un événement déjà publié, lue dans `evenements_sortants` (la source de vérité du
    bus, jamais une copie tenue par un consommateur), ou `None` si ce couple (type, id) n'y est pas.

    Sert à un département qui doit se fier à un fait publié par un autre plutôt qu'à ce qu'un
    appelant lui affirme : M6 relit ainsi le WCT `m4.travaux_termines` de `wct_id` au lieu de
    l'accepter en argument (AGENTS.md : un fait vient de sa source de vérité). Lue dans la
    transaction courante, donc cohérente avec ce que cette transaction vient de publier ; en
    lecture seule, jamais rien n'est écrit. Le type est vérifié : un `evenement_id` qui existe
    sous un AUTRE type rend `None`, jamais la charge d'un événement qui n'est pas celui demandé.

    Lève `TypeEvenementInconnu` si `type_evenement` n'est pas au catalogue (erreur de
    programmation, comme pour `publier` : un type qui n'existe pas n'a jamais rien publié). La
    charge rendue est décodée à chaque appel : la modifier ne touche jamais le bus.
    """
    schema(type_evenement)  # TypeEvenementInconnu si absent du catalogue
    with transaction() as cnx:
        ligne = cnx.execute(
            select(EVENEMENTS_SORTANTS.c.charge).where(
                EVENEMENTS_SORTANTS.c.evenement_id == evenement_id,
                EVENEMENTS_SORTANTS.c.type_evenement == type_evenement,
            )
        ).first()
    return None if ligne is None else codec.decoder(ligne[0])


@dataclass(frozen=True)
class PublicationLue:
    """Enveloppe réellement stockée ; charge décodée indépendante, sans donnée dérivée."""

    evenement_id: str
    type_evenement: str
    producteur: str
    charge: dict[str, Any]
    cree_le: str


@dataclass(frozen=True)
class RecuLu:
    """Reçu existant pour une paire, sans le champ privé `derniere_erreur`."""

    evenement_id: str
    consommateur: str
    statut: str
    tentatives: int
    prochaine_tentative: str | None
    resultat: Any


@dataclass(frozen=True)
class SnapshotBus:
    """Copies ordonnées et empreintes calculées ; aucune preuve de complétude financière."""

    publications: tuple[PublicationLue, ...]
    recus: tuple[RecuLu, ...]
    empreinte_publications_calculee: str
    empreinte_recus_calculee: str


def _empreinte_copie_bus(lignes: list[dict[str, Any]]) -> str:
    texte = json.dumps(lignes, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return sha256(texte.encode("utf-8")).hexdigest()


def copier_publications_et_recus(
    cnx: Connection, *, type_evenement: str, consommateur: str,
) -> SnapshotBus:
    """Copie source et reçus dans la connexion canonique déjà admise par la façade.

    Aucun rôle n'est déduit ici : l'appelant applique son admission AVANT cette lecture.
    Pas de transaction propre, cache, répartition ou écriture. Les empreintes conservent
    les textes codec SQL, même si deux encodages se décodent en objets identiques.
    Les dictionnaires décodés sont des copies ; `frozen` ne les rend pas profondément immuables.
    """
    if not isinstance(cnx, Connection) or cnx is not connexion_courante() or cnx.closed:
        raise ValueError("lecture du bus hors connexion canonique")
    if type(type_evenement) is not str or not type_evenement.strip():
        raise ValueError("type de publication invalide")
    if type(consommateur) is not str or not consommateur.strip():
        raise ValueError("consommateur de publication invalide")
    schema(type_evenement)
    try:
        lignes_publications = cnx.execute(select(
            EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.type_evenement,
            EVENEMENTS_SORTANTS.c.producteur, EVENEMENTS_SORTANTS.c.charge, EVENEMENTS_SORTANTS.c.cree_le,
        ).where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
          .order_by(EVENEMENTS_SORTANTS.c.evenement_id)).mappings().all()
        publications = []
        for ligne in lignes_publications:
            charge = codec.decoder(ligne["charge"])
            if type(charge) is not dict:
                raise ValueError("objet de publication requis")
            publications.append(PublicationLue(
                ligne["evenement_id"], ligne["type_evenement"], ligne["producteur"], charge, ligne["cree_le"],
            ))
        ids = {publication.evenement_id for publication in publications}
        lignes_recus = []
        if ids:
            # La jointure évite une liste de paramètres SQL de la taille de l'historique.
            # Le filtre Python lie strictement les reçus aux IDs de la copie précédente.
            candidats = cnx.execute(select(
                EVENEMENTS_RECUS.c.evenement_id, EVENEMENTS_RECUS.c.consommateur,
                EVENEMENTS_RECUS.c.statut, EVENEMENTS_RECUS.c.tentatives,
                EVENEMENTS_RECUS.c.prochaine_tentative, EVENEMENTS_RECUS.c.resultat,
            ).join(EVENEMENTS_SORTANTS,
                   EVENEMENTS_SORTANTS.c.evenement_id == EVENEMENTS_RECUS.c.evenement_id)
              .where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement,
                     EVENEMENTS_RECUS.c.consommateur == consommateur)
              .order_by(EVENEMENTS_RECUS.c.evenement_id, EVENEMENTS_RECUS.c.consommateur)).mappings().all()
            lignes_recus = [ligne for ligne in candidats if ligne["evenement_id"] in ids]
        recus = tuple(RecuLu(
            ligne["evenement_id"], ligne["consommateur"], ligne["statut"], ligne["tentatives"],
            ligne["prochaine_tentative"],
            codec.decoder(ligne["resultat"]) if ligne["resultat"] is not None else None,
        ) for ligne in lignes_recus)
        return SnapshotBus(
            tuple(publications), recus,
            _empreinte_copie_bus([dict(ligne) for ligne in lignes_publications]),
            _empreinte_copie_bus([dict(ligne) for ligne in lignes_recus]),
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError, SQLAlchemyError):
        raise ValueError("copie de provenance du bus invalide") from None
