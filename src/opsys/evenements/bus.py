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

from sqlalchemy import (
    Connection,
    DateTime,
    Integer,
    LargeBinary,
    Text,
    and_,
    case,
    cast,
    func,
    literal,
    null,
    or_,
    select,
    union_all,
)
from sqlalchemy.exc import SQLAlchemyError

from ..stockage import codec, connexion_courante, inserer, transaction
from ..stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS
from .schemas import TypeEvenementInconnu, erreurs_charge, schema

__all__ = ["ChargeInvalide", "ConflitPublication", "TypeEvenementInconnu", "charge_publiee", "deja_publie", "publier"]


class ChargeInvalide(ValueError):
    """La charge ne respecte pas le schéma JSON du catalogue pour ce type : rien n'est écrit."""


class ConflitPublication(ValueError):
    """An event identifier already names a different immutable publication envelope."""


def _charge_canonique(texte_codec: str) -> str:
    # Keep codec type tags and scalar representations; only mapping order is irrelevant.
    return json.dumps(json.loads(texte_codec), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


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
    producteur (`UNIQUE` en clé primaire) : la même enveloppe (type, producteur, charge typée)
    sous le même id est un no-op qui conserve la première publication, date comprise. Seul l'ordre
    des clés d'objet est ignoré ; les représentations scalaires et étiquettes du codec sont conservées.
    Une enveloppe différente lève `ConflitPublication`, sans exposer les charges dans l'erreur,
    afin que la transaction métier appelante soit annulée. L'idempotence du bus ne déduplique pas
    les écritures métier d'un appelant : leur clé d'opération reste distincte.
    """
    if not producteur or not producteur.strip():
        raise ValueError("producteur requis")
    erreurs = erreurs_charge(type_evenement, charge)  # TypeEvenementInconnu si absent du catalogue
    if erreurs:
        raise ChargeInvalide(f"{type_evenement} : charge invalide : {'; '.join(erreurs)}")
    ident = evenement_id or uuid.uuid4().hex
    charge_encodee = codec.encoder(dict(charge))
    with transaction() as cnx:
        insertion = inserer(cnx)(EVENEMENTS_SORTANTS).values(
            evenement_id=ident,
            type_evenement=type_evenement,
            producteur=producteur,
            charge=charge_encodee,
            cree_le=dt.datetime.now(dt.UTC).isoformat(),
        )
        ajoute = cnx.execute(insertion.on_conflict_do_nothing(
            index_elements=[EVENEMENTS_SORTANTS.c.evenement_id],
        ).returning(EVENEMENTS_SORTANTS.c.evenement_id)).scalar_one_or_none()
        if ajoute is None:
            # Read the committed winner on the same connection after INSERT resolves its conflict.
            ligne = cnx.execute(select(
                EVENEMENTS_SORTANTS.c.type_evenement, EVENEMENTS_SORTANTS.c.producteur,
                EVENEMENTS_SORTANTS.c.charge,
            ).where(EVENEMENTS_SORTANTS.c.evenement_id == ident)).first()
            if ligne is None:
                raise ConflitPublication(f"conflit de publication {ident} : première enveloppe introuvable")
            differences = []
            if ligne.type_evenement != type_evenement:
                differences.append("type_evenement")
            if ligne.producteur != producteur:
                differences.append("producteur")
            if _charge_canonique(ligne.charge) != _charge_canonique(charge_encodee):
                differences.append("charge")
            if differences:
                raise ConflitPublication(f"conflit de publication {ident} : {', '.join(differences)}")
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


class RegistreProvenanceInvalide(ValueError):
    """Le registre copié est invalide, sans détail partiel."""


class BudgetProvenanceDepasse(ValueError):
    """La cohorte source dépasse une borne fixe, sans payload partiel."""


_PROVENANCE_M5_M8 = {
    "m5.cash_libre_constate": "faits_cash_libre",
    "m5.rentabilite_chantier": "faits_chantier",
}
_PROVENANCE_LIGNES = 10000
_PROVENANCE_LIGNE_OCTETS = 65536
_PROVENANCE_OCTETS = 16777216


def _requete_cohorte_m5_m8(type_evenement: str, dialecte: str):
    from ..stockage.schema import REGISTRES

    types = {
        "kind": Integer(), "evenement_id": Text(), "type_evenement": Text(), "producteur": Text(),
        "charge": Text(), "publication_date": Text(), "consommateur": Text(), "statut": Text(),
        "tentatives": Integer(), "prochaine_tentative": Text(), "resultat": Text(), "rang": Integer(),
        "maillon_date": DateTime(timezone=True), "maillon": Text(),
    }

    def colonnes(**valeurs):
        return [valeurs.get(nom, cast(null(), typ)).label(nom) for nom, typ in types.items()]

    publications = select(*colonnes(
        kind=literal(0), evenement_id=EVENEMENTS_SORTANTS.c.evenement_id,
        type_evenement=EVENEMENTS_SORTANTS.c.type_evenement, producteur=EVENEMENTS_SORTANTS.c.producteur,
        charge=EVENEMENTS_SORTANTS.c.charge, publication_date=EVENEMENTS_SORTANTS.c.cree_le,
    )).where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
    recus = select(*colonnes(
        kind=literal(1), evenement_id=EVENEMENTS_RECUS.c.evenement_id,
        consommateur=EVENEMENTS_RECUS.c.consommateur, statut=EVENEMENTS_RECUS.c.statut,
        tentatives=EVENEMENTS_RECUS.c.tentatives, prochaine_tentative=EVENEMENTS_RECUS.c.prochaine_tentative,
        resultat=EVENEMENTS_RECUS.c.resultat,
    )).select_from(EVENEMENTS_RECUS.join(EVENEMENTS_SORTANTS,
        EVENEMENTS_SORTANTS.c.evenement_id == EVENEMENTS_RECUS.c.evenement_id)).where(
        EVENEMENTS_SORTANTS.c.type_evenement == type_evenement,
        EVENEMENTS_RECUS.c.consommateur == "m08-analytics",
    )
    faits = select(*colonnes(
        kind=literal(2), rang=REGISTRES.c.rang, maillon_date=REGISTRES.c.cree_le, maillon=REGISTRES.c.maillon,
    )).where(REGISTRES.c.departement == "m08-analytics",
             REGISTRES.c.registre == _PROVENANCE_M5_M8[type_evenement])
    raw = union_all(publications, recus, faits).subquery("sources_m5_m8")
    prefixe = select(raw).order_by(raw.c.kind, raw.c.evenement_id, raw.c.rang).limit(
        _PROVENANCE_LIGNES + 1).cte("cohorte_m5_m8")
    champs = {
        0: ("evenement_id", "type_evenement", "producteur", "charge", "publication_date"),
        1: ("evenement_id", "consommateur", "statut", "prochaine_tentative", "resultat"),
        2: ("maillon", "maillon_date"),
    }
    nullable = {"prochaine_tentative", "resultat"}
    tailles, invalides = [], []
    for kind, noms in champs.items():
        for nom in noms:
            col = prefixe.c[nom]
            texte = cast(col, Text()) if nom == "maillon_date" else col
            taille = (func.length(cast(texte, LargeBinary)) if dialecte == "sqlite"
                      else func.octet_length(texte))
            tailles.append(case((prefixe.c.kind == kind, func.coalesce(taille, 0)), else_=0))
            mauvais = col.is_(None) if nom not in nullable else literal(False)
            if dialecte == "sqlite":
                mauvais = or_(mauvais, and_(col.is_not(None), func.typeof(col) != "text"))
            invalides.append(and_(prefixe.c.kind == kind, mauvais))
    # Entiers natifs signés64 : jamais TEXT/BLOB/REAL malgré l'affinité SQLite.
    # Huit octets fixes de budget par métadonnée entière métier (kind est synthétique).
    for kind, nom in ((1, "tentatives"), (2, "rang")):
        col = prefixe.c[nom]
        mauvais = or_(col.is_(None), col < -(2**63), col > 2**63 - 1)
        if dialecte == "sqlite":
            mauvais = or_(mauvais, func.typeof(col) != "integer")
        invalides.append(and_(prefixe.c.kind == kind, mauvais))
        tailles.append(case((prefixe.c.kind == kind, 8), else_=0))
    invalide = or_(*invalides)
    taille_ligne = sum(tailles)
    stats = select(
        func.count().label("nombre"), func.coalesce(func.sum(taille_ligne), 0).label("octets"),
        func.coalesce(func.max(taille_ligne), 0).label("maximum_octets"),
        func.coalesce(func.sum(case((invalide, 1), else_=0)), 0).label("invalides"),
        func.coalesce(func.sum(case((and_(prefixe.c.kind == 2, invalide), 1), else_=0)),
                      0).label("invalides_registre"),
    ).select_from(prefixe).cte("admission_m5_m8")
    admissible = and_(stats.c.nombre <= _PROVENANCE_LIGNES, stats.c.octets <= _PROVENANCE_OCTETS,
                      stats.c.maximum_octets <= _PROVENANCE_LIGNE_OCTETS, stats.c.invalides == 0)
    # Une seule déclaration/snapshot : aucune valeur métier sort du SQL si la cohorte est refusée.
    return select(*stats.c,
        case((admissible, taille_ligne), else_=None).label("ligne_octets"),
        case((admissible, cast(prefixe.c.maillon_date, Text())), else_=None).label("maillon_date_texte"), *[
        case((admissible, prefixe.c[nom]), else_=None).label(nom) for nom in types
    ]).select_from(stats.outerjoin(prefixe, admissible)).order_by(prefixe.c.kind, prefixe.c.evenement_id,
                                                               prefixe.c.rang)


def copier_cohorte_provenance_m5_m8(cnx: Connection, *, type_evenement: str):
    """Cohorte complète bornée dans un SELECT ; mêmes copies/hashes, aucun chiffre recalculé.

    Plafonds fixes nouveaux : 10000 lignes, 64 KiB UTF8/ligne, 16 MiB UTF8 au total.
    Ils bornent transfert/décodage, pas les allocations internes ou le planner SQL.
    """
    from ..stockage.maillons import MaillonLu, SnapshotMaillons

    if (not isinstance(cnx, Connection) or cnx is not connexion_courante() or cnx.closed
            or not cnx.in_transaction()):
        raise ValueError("lecture de provenance hors connexion canonique")
    if type(type_evenement) is not str or type_evenement not in _PROVENANCE_M5_M8:
        raise ValueError("source de provenance invalide")
    dialecte = cnx.dialect.name
    if dialecte not in ("sqlite", "postgresql"):
        raise ValueError("dialecte de provenance invalide")
    try:
        encoding = (cnx.exec_driver_sql("PRAGMA encoding").scalar_one() if dialecte == "sqlite"
                    else cnx.execute(select(func.current_setting("server_encoding"))).scalar_one())
        if type(encoding) is not str or encoding.upper().replace("-", "") != "UTF8":
            raise ValueError("encodage de provenance invalide")
        rows = cnx.execute(_requete_cohorte_m5_m8(type_evenement, dialecte)).mappings().all()
        stats = rows[0]
        if (stats["nombre"] > _PROVENANCE_LIGNES or stats["octets"] > _PROVENANCE_OCTETS
                or stats["maximum_octets"] > _PROVENANCE_LIGNE_OCTETS):
            raise BudgetProvenanceDepasse("borne de source dépassée")
        if stats["invalides"]:
            if stats["invalides"] == stats["invalides_registre"]:
                raise RegistreProvenanceInvalide("source de registre invalide")
            raise ValueError("source de provenance invalide")
        lignes = [] if stats["nombre"] == 0 else rows
        if len(lignes) != stats["nombre"]:
            raise ValueError("cohorte source incomplète")
        # Valider tous les textes UTF8 et métadonnées AVANT le premier décodage.
        total_utf8 = 0
        for row in lignes:
            octets_utf8 = 8 if row["kind"] in (1, 2) else 0
            for nom in ("evenement_id", "type_evenement", "producteur", "charge", "publication_date",
                        "consommateur", "statut", "prochaine_tentative", "resultat", "maillon"):
                v = row[nom]
                if v is not None and (type(v) is not str or len(v.encode("utf-8", errors="strict"))
                                      > _PROVENANCE_LIGNE_OCTETS):
                    raise ValueError("texte source invalide")
                if v is not None:
                    octets_utf8 += len(v.encode("utf-8", errors="strict"))
            if row["maillon_date_texte"] is not None:
                octets_utf8 += len(row["maillon_date_texte"].encode("utf-8", errors="strict"))
            if octets_utf8 != row["ligne_octets"] or octets_utf8 > _PROVENANCE_LIGNE_OCTETS:
                raise ValueError("taille UTF8 source incohérente")
            total_utf8 += octets_utf8
            if row["kind"] == 1 and (type(row["tentatives"]) is not int
                                     or not -(2**63) <= row["tentatives"] <= 2**63 - 1):
                raise ValueError("métadonnée de reçu invalide")
            if row["kind"] == 2 and (type(row["rang"]) is not int
                                     or not -(2**63) <= row["rang"] <= 2**63 - 1
                                     or not isinstance(row["maillon_date"], dt.datetime)):
                raise RegistreProvenanceInvalide("métadonnées de registre invalides")
        if total_utf8 != stats["octets"] or total_utf8 > _PROVENANCE_OCTETS:
            raise ValueError("taille UTF8 de cohorte incohérente")
        p_raw, r_raw, m_raw = [], [], []
        for row in lignes:
            if row["kind"] == 0:
                p_raw.append({"evenement_id": row["evenement_id"], "type_evenement": row["type_evenement"],
                              "producteur": row["producteur"], "charge": row["charge"],
                              "cree_le": row["publication_date"]})
            elif row["kind"] == 1:
                r_raw.append({"evenement_id": row["evenement_id"], "consommateur": row["consommateur"],
                              "statut": row["statut"], "tentatives": row["tentatives"],
                              "prochaine_tentative": row["prochaine_tentative"], "resultat": row["resultat"]})
            else:
                m_raw.append({"rang": row["rang"], "cree_le": row["maillon_date"].isoformat(),
                              "maillon": row["maillon"]})
        publications = []
        for row in p_raw:
            charge = codec.decoder(row["charge"])
            if type(charge) is not dict:
                raise ValueError("objet de publication requis")
            publications.append(PublicationLue(row["evenement_id"], row["type_evenement"], row["producteur"],
                                              charge, row["cree_le"]))
        recus = tuple(RecuLu(row["evenement_id"], row["consommateur"], row["statut"], row["tentatives"],
                            row["prochaine_tentative"],
                            codec.decoder(row["resultat"]) if row["resultat"] is not None else None)
                      for row in r_raw)
        try:
            maillons = tuple(MaillonLu(row["rang"], dt.datetime.fromisoformat(row["cree_le"]),
                                      codec.decoder(row["maillon"])) for row in m_raw)
        except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError):
            raise RegistreProvenanceInvalide("copie du registre invalide") from None
        return (SnapshotBus(tuple(publications), recus, _empreinte_copie_bus(p_raw), _empreinte_copie_bus(r_raw)),
                SnapshotMaillons("m08-analytics", _PROVENANCE_M5_M8[type_evenement], maillons,
                                 _empreinte_copie_bus(m_raw)))
    except (BudgetProvenanceDepasse, RegistreProvenanceInvalide):
        raise
    except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError, SQLAlchemyError):
        raise ValueError("copie de provenance invalide") from None
