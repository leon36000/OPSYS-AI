"""Adaptateur de l'entrepôt de M8 vers la base de l'instance (tables ``m8_ent_*``, migration 0046).

C'est le SEUL fichier du chemin de l'entrepôt qui touche SQLAlchemy et le socle (comme ``outils.py`` pour les
registres) :
``entrepot.py`` reste pur. La connexion est celle de la transaction courante (``opsys.stockage``) : une construction est
atomique avec le reste de l'appel d'outil ; un échec ne laisse jamais un entrepôt à moitié reconstruit.

Règles :

* La construction COURANTE remplace les tables courantes en bloc (suppression puis insertion, dans la même
transaction) ;
  l'historique des mesures et le journal des constructions ne font que s'ajouter.
* Une reconstruction sur le même état (même schéma, même catalogue, mêmes registres) est ``inchangee`` : rien n'est
écrit.
* Chaque ligne insérée a exactement les colonnes de la table (contrôle avant l'écriture) : une colonne en trop ou
  manquante est un refus, jamais une valeur ignorée.
* L'entrepôt est rendu EN LECTURE par ``lire_*`` ; ``etat`` compare l'empreinte des registres actuels à celle de la
  dernière construction pour dire qu'il est en retard.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, Table, delete, insert, select
from sqlalchemy.exc import IntegrityError

from opsys.stockage.schema import (
    M8_ENT_CONSTRUCTIONS,
    M8_ENT_DIM_CHANTIER,
    M8_ENT_DIM_LEAD,
    M8_ENT_FAIT_DEVIS,
    M8_ENT_MART_CONTENUS,
    M8_ENT_MESURES_COURANTES,
    M8_ENT_MESURES_HIST,
)

from . import entrepot, moteur_mesures

_TABLES = {
    entrepot.TABLE_MESURES: M8_ENT_MESURES_COURANTES,
    entrepot.TABLE_CHANTIER: M8_ENT_DIM_CHANTIER,
    entrepot.TABLE_LEAD: M8_ENT_DIM_LEAD,
    entrepot.TABLE_DEVIS: M8_ENT_FAIT_DEVIS,
    entrepot.TABLE_CONTENUS: M8_ENT_MART_CONTENUS,
    entrepot.TABLE_HISTORIQUE: M8_ENT_MESURES_HIST,
}
# Ordre d'insertion qui respecte les clés étrangères (la construction d'abord) et ordre inverse pour supprimer.
_ORDRE_ECRITURE = (
    entrepot.TABLE_MESURES,
    entrepot.TABLE_CHANTIER,
    entrepot.TABLE_LEAD,
    entrepot.TABLE_DEVIS,
    entrepot.TABLE_CONTENUS,
    entrepot.TABLE_HISTORIQUE,
)
# Les identifiants que les faits reçus du bus portent jusque dans une colonne `VARCHAR(n)` de l'entrepôt. SQLite ne
# mesure
# pas ; PostgreSQL refuse (`value too long`), et une seule valeur trop longue, rangée au registre (append-only), aurait
# fait échouer chaque construction à vie. La limite est donc posée À LA RÉCEPTION (`verifier_identifiants`), pas à la
# construction : un identifiant que l'entrepôt ne peut pas porter n'entre jamais au registre.
_COLONNES_IDENTIFIANTS = {
    "lead_id": (M8_ENT_DIM_LEAD, M8_ENT_FAIT_DEVIS),
    "devis_id": (M8_ENT_DIM_CHANTIER, M8_ENT_FAIT_DEVIS),
    "wct_id": (M8_ENT_DIM_CHANTIER, M8_ENT_MART_CONTENUS),
    "contenu_id": (M8_ENT_MART_CONTENUS,),
    "utm_content": (M8_ENT_DIM_LEAD, M8_ENT_MART_CONTENUS),
}
LONGUEURS_IDENTIFIANTS = {
    cle: min(table.c[cle].type.length for table in tables_) for cle, tables_ in _COLONNES_IDENTIFIANTS.items()
}
STATUT_CONSTRUIT = "construit"
STATUT_INCHANGE = "inchange"
STATUT_CONCURRENT = "concurrent"


def verifier_identifiants(fait: dict[str, Any]) -> None:
    """Refuse (`ValueError`, donc un refus déterministe que le bus réessaie puis met en quarantaine, visible) un
    fait dont
    un identifiant dépasse la colonne de l'entrepôt qui le portera. Rien n'est tronqué : un identifiant tronqué
    serait un
    autre identifiant."""
    for cle, longueur in LONGUEURS_IDENTIFIANTS.items():
        valeur = fait.get(cle)
        if isinstance(valeur, str) and len(valeur) > longueur:
            raise ValueError(
                f"REJ-ENTREPOT-IDENTIFIANT-TROP-LONG : {cle} de {len(valeur)} caractères (au plus {longueur})"
            )


def tables() -> dict[str, Table]:
    """Les tables de l'entrepôt, par nom (le pont BI et les tests les lisent par ici)."""
    return dict(_TABLES)


def _colonnes_ecrites(table: Table) -> set[str]:
    return {colonne.name for colonne in table.columns}


def _verifier_lignes(nom: str, lignes: list[dict[str, Any]]) -> None:
    attendu = _colonnes_ecrites(_TABLES[nom])
    for ligne in lignes:
        if set(ligne) != attendu:
            raise ValueError(
                f"REJ-ENTREPOT-COLONNES : {nom} : colonnes en trop {sorted(set(ligne) - attendu)} "
                f"ou manquantes {sorted(attendu - set(ligne))}"
            )


def derniere_construction(cnx: Connection) -> dict[str, Any] | None:
    ligne = (
        cnx.execute(select(M8_ENT_CONSTRUCTIONS).order_by(M8_ENT_CONSTRUCTIONS.c.rang.desc()).limit(1))
        .mappings()
        .first()
    )
    if ligne is None:
        return None
    construction = dict(ligne)
    construction["comptes"] = json.loads(construction["comptes"])
    return construction


def reconstruire(
    cnx: Connection,
    registres: dict[str, Any],
    catalogue: dict[str, Any],
    construit_le: str,
) -> dict[str, Any]:
    """Reconstruit l'entrepôt depuis les registres. Rend ``{statut, construction}`` ; ``statut`` vaut ``construit``,
    ``inchange`` (même état que la dernière construction : rien n'est écrit) ou ``concurrent`` (une autre construction a
    écrit en même temps : réessayer ; rien n'est écrit par celle-ci)."""
    precedente = derniere_construction(cnx)
    empreinte = moteur_mesures.empreinte_registres(registres)
    if entrepot.meme_etat(precedente, catalogue["version_catalogue"], empreinte):
        return {"statut": STATUT_INCHANGE, "construction": precedente}
    rang_precedent = 0 if precedente is None else precedente["rang"]
    resultat = entrepot.construire(registres, catalogue, construit_le=construit_le, rang_precedent=rang_precedent)
    for nom, lignes in resultat["tables"].items():
        _verifier_lignes(nom, lignes)
    construction = resultat["construction"]
    try:
        with cnx.begin_nested():
            for nom in reversed(_ORDRE_ECRITURE[:-1]):
                cnx.execute(delete(_TABLES[nom]))
            cnx.execute(
                insert(M8_ENT_CONSTRUCTIONS).values(
                    construction_id=construction["construction_id"],
                    version_schema=construction["version_schema"],
                    version_catalogue=construction["version_catalogue"],
                    empreinte_registres=construction["empreinte_registres"],
                    construit_le=construction["construit_le"],
                    nb_mesures=construction["nb_mesures"],
                    comptes=json.dumps(construction["comptes"], sort_keys=True, ensure_ascii=False),
                )
            )
            for nom in _ORDRE_ECRITURE:
                if resultat["tables"][nom]:
                    cnx.execute(insert(_TABLES[nom]), resultat["tables"][nom])
    except IntegrityError:
        return {"statut": STATUT_CONCURRENT, "construction": precedente}
    return {"statut": STATUT_CONSTRUIT, "construction": derniere_construction(cnx)}


def etat(cnx: Connection, registres: dict[str, Any], catalogue: dict[str, Any]) -> dict[str, Any]:
    """L'état de l'entrepôt face aux registres ACTUELS : ``absent`` (jamais construit), ``a_jour`` (même schéma, même
    catalogue, mêmes registres) ou ``en_retard`` (les registres ou le catalogue ont changé depuis, ou le schéma est
    d'une autre version). Dit pourquoi ; ne construit rien."""
    derniere = derniere_construction(cnx)
    if derniere is None:
        return {
            "statut": "absent",
            "construction": None,
            "raison": "aucune construction : l'entrepôt n'a jamais été bâti",
        }
    empreinte = moteur_mesures.empreinte_registres(registres)
    if entrepot.meme_etat(derniere, catalogue["version_catalogue"], empreinte):
        return {"statut": "a_jour", "construction": derniere, "raison": "mêmes registres, même catalogue, même schéma"}
    raisons = []
    if derniere["empreinte_registres"] != empreinte:
        raisons.append("les registres ont changé depuis la construction")
    if derniere["version_catalogue"] != catalogue["version_catalogue"]:
        raisons.append("le catalogue a changé")
    if derniere["version_schema"] != entrepot.VERSION_SCHEMA:
        raisons.append("la version du schéma a changé")
    return {"statut": "en_retard", "construction": derniere, "raison": " ; ".join(raisons)}


def lire_table(cnx: Connection, nom: str) -> list[dict[str, Any]]:
    """Toutes les lignes d'une table de l'entrepôt (lecture pure), dans l'ordre de sa clé primaire."""
    table = _TABLES[nom]
    cles = [colonne for colonne in table.primary_key.columns]
    requete = select(table).order_by(*cles)
    return [dict(ligne) for ligne in cnx.execute(requete).mappings()]


def lire_mesures_courantes(cnx: Connection) -> list[dict[str, Any]]:
    return lire_table(cnx, entrepot.TABLE_MESURES)


def lire_historique(cnx: Connection, metric_id: str, limite: int = 200) -> list[dict[str, Any]]:
    """L'historique d'une mesure, du plus récent au plus ancien, borné (jamais tout l'historique)."""
    if type(limite) is not int or not 1 <= limite <= 1000:
        raise ValueError("REJ-ENTREPOT-LIMITE : la limite d'historique est un entier de 1 à 1000")
    requete = (
        select(M8_ENT_MESURES_HIST)
        .where(M8_ENT_MESURES_HIST.c.metric_id == metric_id)
        .order_by(M8_ENT_MESURES_HIST.c.construit_le.desc(), M8_ENT_MESURES_HIST.c.construction_id)
        .limit(limite)
    )
    return [dict(ligne) for ligne in cnx.execute(requete).mappings()]


__all__ = [
    "STATUT_CONCURRENT",
    "STATUT_CONSTRUIT",
    "STATUT_INCHANGE",
    "derniere_construction",
    "etat",
    "lire_historique",
    "lire_mesures_courantes",
    "lire_table",
    "reconstruire",
    "tables",
    "verifier_identifiants",
]
