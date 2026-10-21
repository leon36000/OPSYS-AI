"""Lectures bornées des sources de réception M4→M3, réservées au diagnostic.

Le bus ne livre que des identités de publication, jamais ses charges.
Le lecteur ne certifie ni le contenu WCT, ni la mesure terrain ni sa complétude.
"""

from __future__ import annotations

import hashlib
import json
import re

from sqlalchemy import LargeBinary, case, cast, func, select

from .. import stockage
from ..stockage.schema import EVENEMENTS_SORTANTS, REGISTRES

MAX_PUBLICATIONS = 2_000
MAX_MAILLONS_M3 = 20_000
_IDENTITE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)


class InventaireRefuse(ValueError):
    """Refus nommé de l'ensemble du diagnostic, sans valeur source exposée."""


def identite_valide(valeur: object) -> bool:
    return isinstance(valeur, str) and _IDENTITE.fullmatch(valeur) is not None


def empreinte_identites(identites: list[str]) -> str:
    contenu = json.dumps(identites, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(contenu.encode("ascii")).hexdigest()


def _connexion():
    cnx = stockage.connexion_courante()
    if cnx is None or not cnx.in_transaction():
        raise InventaireRefuse("transaction_lecture_requise")
    if cnx.dialect.name != "sqlite":
        raise InventaireRefuse("backend_source_non_qualifie")
    return cnx


def lire_publications_m4() -> dict:
    """IDs internes du bus, LIMIT +1 et ID borné avant transfert SQL.

    La clé suit le contrat M4 courant (event_id=wct_id), sans attester
    cette concordance dans le contenu : ce n'est pas une admission de faits.
    """
    cnx = _connexion()
    table = EVENEMENTS_SORTANTS
    requete = select(
        case((func.length(table.c.evenement_id) <= 128, table.c.evenement_id), else_=None).label("identite"),
        (table.c.producteur == "m04-field-ops").label("producteur_conforme"),
    ).where(table.c.type_evenement == "m4.travaux_termines").order_by(
        table.c.evenement_id,
    ).limit(MAX_PUBLICATIONS + 1)
    lignes = list(cnx.execute(requete).mappings())
    if len(lignes) > MAX_PUBLICATIONS:
        raise InventaireRefuse("limite_publications_m4_depassee")
    identites = []
    for ligne in lignes:
        if ligne["producteur_conforme"] is not True:
            raise InventaireRefuse("producteur_publication_m4_invalide")
        if not identite_valide(ligne["identite"]):
            raise InventaireRefuse("identite_publication_m4_invalide")
        identites.append(ligne["identite"])
    identites.sort()  # Ordre ASCII stable, indépendant de la collation SQL.
    if len(set(identites)) != len(identites):
        raise InventaireRefuse("identites_publication_m4_ambigues")
    return {"version": "publications-m4-identites/1", "identites": identites,
            "sha256": empreinte_identites(identites)}


def lire_receptions_m3() -> list:
    """Bornes SQL avant décodage des maillons canoniques, sans autre stockage."""
    cnx = _connexion()
    table = REGISTRES
    filtre = (table.c.departement == "m03-estimation") & (table.c.registre == "estime_vs_reel")
    longueurs = select(func.length(cast(table.c.maillon, LargeBinary)).label("octets")).where(
        filtre,
    ).limit(MAX_MAILLONS_M3 + 1).subquery()
    nombre, maxi, total = cnx.execute(select(
        func.count(), func.coalesce(func.max(longueurs.c.octets), 0),
        func.coalesce(func.sum(longueurs.c.octets), 0),
    ).select_from(longueurs)).one()
    if (type(nombre) is not int or nombre > MAX_MAILLONS_M3
            or type(maxi) is not int or maxi > 65_536
            or type(total) is not int or total > 4_000_000):
        raise InventaireRefuse("limite_reception_m3_depassee")
    lignes = list(stockage.maillons("m03-estimation", "estime_vs_reel"))
    if len(lignes) != nombre:
        raise InventaireRefuse("sources_modifiees_pendant_lecture")
    return lignes
