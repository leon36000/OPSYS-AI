"""Coût unitaire d'une SORTIE de stock, résolu au niveau de l'ARTICLE (C1, défaut F1 de l'analyse M6).

Avant : la déclaration de fin de chantier était refusée EN ENTIER (`REJ-COUT-UNITAIRE-INTROUVABLE`) dès qu'une
ligne concernait un article jamais reçu SOUS CE chantier. L'achat sur place d'un article inédit, l'article non
prévu inédit et la sortie du dépôt vers un autre chantier étaient donc impossibles : ce que l'employé a utilisé
attendait un prix. Une quantité sortie est un fait de terrain ; le prix en est une donnée à fournir, pas une
condition d'acceptation.

Maintenant, le coût d'une ligne vient d'une source ORDONNÉE et DITE (`origine_cout`, rangée sur le mouvement et
entrant dans son empreinte) :

  1. `RECEPTION_CHANTIER` : la dernière réception de l'article sous CE chantier (le comportement d'avant) ;
  2. `RECEPTION_ARTICLE`  : à défaut, la dernière réception de l'article ailleurs (dépôt, autre chantier) ;
  3. `LIVRE_PRIX`         : à défaut, le livre de prix de M6, comme M5 le lit pour le coût réel (`cout_reel.py`) :
                           pour chaque fournisseur, la dernière entrée applicable au jour du WCT, dans l'UNITÉ de la
                           ligne (une unité absente ou différente n'est jamais présumée égale), en CAD ; plusieurs
                           fournisseurs au même prix : ce prix ; à des prix différents : AMBIGU, aucun prix choisi ;
  4. `INCONNU`           : sinon, `cout_unitaire` est `None` et le motif est dit. La déclaration est ACCEPTÉE ; l'admin
                           voit ce qu'il faut déclarer (`attentes`).

Un prix du livre porte son `marquage` : `SOURCE_DECLAREE` (un document est cité, jamais authentifié ici) ou
`FALLBACK_PRICE_BOOK` (aucun document). Aucune source ne rend un coût « validé » : ce mot n'existe pas ici, la
validation d'un coût appartient à la finance (M5) et à un humain.

Module pur (AGENTS.md, ADR-0009) : aucun import `opsys`, aucune horloge, aucun réseau. Le jour du WCT est celui de
`horodatage_completion`, fourni par l'appelant.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any

from . import livre_prix

__all__ = [
    "SOURCE_INCONNU",
    "SOURCE_LIVRE_PRIX",
    "SOURCE_RECEPTION_ARTICLE",
    "SOURCE_RECEPTION_CHANTIER",
    "attentes_cout_inconnu",
    "jour_du_wct",
    "resoudre",
]

SOURCE_RECEPTION_CHANTIER = "RECEPTION_CHANTIER"
SOURCE_RECEPTION_ARTICLE = "RECEPTION_ARTICLE"
SOURCE_LIVRE_PRIX = "LIVRE_PRIX"
SOURCE_INCONNU = "INCONNU"

MOTIF_AUCUN_PRIX = "AUCUN_PRIX"
MOTIF_UNITE = "UNITE_NON_CONFIRMEE"
MOTIF_AMBIGU = "PRIX_AMBIGU"
MOTIF_DATE = "DATE_ILLISIBLE"

_DEVISE = "CAD"
TYPE_ATTENTE_COUT_INCONNU = "cout_sortie_inconnu"
NIVEAU_ATTENTE = "N2"  # alerte interne : rien ne s'exécute seul

_MOTIFS_LISIBLES = {
    MOTIF_AUCUN_PRIX: "aucun prix connu pour cet article (ni réception, ni livre de prix)",
    MOTIF_UNITE: (
        "le livre de prix a un prix pour cet article mais pas dans l'unité {unite!r} (ou sans unité confirmée)"
    ),
    MOTIF_AMBIGU: (
        "le livre de prix donne des prix différents selon le fournisseur et le fournisseur du stock utilisé "
        "n'est pas connu"
    ),
    MOTIF_DATE: "le jour du chantier n'est pas lisible : aucun prix du livre ne peut être daté",
}


def jour_du_wct(horodatage_completion: Any) -> date | None:
    """Jour civil de complétion du WCT, dans le fuseau écrit (comme M5), ou `None` si illisible ou sans fuseau."""
    if not isinstance(horodatage_completion, str):
        return None
    try:
        instant = datetime.fromisoformat(horodatage_completion)
    except ValueError:
        return None
    return instant.date() if instant.tzinfo is not None else None


def _jour_tarif(brut: Any) -> date | None:
    if not isinstance(brut, str) or len(brut) != 10 or brut[4:5] != "-" or brut[7:8] != "-":
        return None
    try:
        return date.fromisoformat(brut)
    except ValueError:
        return None


def _prix_utilisable(valeur: Any) -> float | None:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None
    if isinstance(valeur, float) and not math.isfinite(valeur):
        return None
    return float(valeur) if valeur > 0 else None


def _cout_de_reception(mouvements: Iterable[Mapping[str, Any]], materiau_id: str,
                       chantier_id: str | None) -> tuple[Mapping[str, Any] | None, float | None]:
    """La dernière RECEPTION de l'article (sous `chantier_id` si fourni, sinon n'importe où) dont le coût et la quantité
    sont des nombres strictement positifs. Une réception au prix indéterminé (`None`) ou de quantité nulle ne sert
    jamais de coût."""
    trouve = None
    for maillon in mouvements:
        if (
            maillon.get("type_mouvement") == "RECEPTION"
            and maillon.get("materiau_id") == materiau_id
            and (chantier_id is None or maillon.get("chantier_id") == chantier_id)
            and _prix_utilisable(maillon.get("cout_unitaire")) is not None
            # Une livraison de zéro (la ligne d'un PO pas encore arrivée) n'est pas une réception : son prix
            # ne dit rien de ce qui a été payé et ne doit pas remplacer celui de la vraie livraison.
            and _prix_utilisable(maillon.get("quantite")) is not None
        ):
            trouve = maillon
    return (trouve, _prix_utilisable(trouve["cout_unitaire"])) if trouve is not None else (None, None)


def _inconnu(motif: str) -> dict[str, Any]:
    return {"cout_unitaire": None, "origine": {"source": SOURCE_INCONNU, "motif": motif, "marquage": None}}


def _depuis_le_livre(materiau_id: str, unite: Any, jour: date | None, livre: Iterable[Mapping[str, Any]]) -> dict[str,
                                                                                                                  Any]:
    if jour is None:
        return _inconnu(MOTIF_DATE)
    derniere: dict[str, Mapping[str, Any]] = {}
    for entree in livre:
        if not isinstance(entree, Mapping) or entree.get("materiau_id") != materiau_id:
            continue
        effet = _jour_tarif(entree.get("date_effet"))
        if effet is None or effet > jour:
            continue  # tarif futur, ou date illisible : ne s'applique pas à ce jour-là
        derniere[str(entree.get("fournisseur_id"))] = entree
    if not derniere:
        return _inconnu(MOTIF_AUCUN_PRIX)
    utilisables: dict[str, tuple[float, Mapping[str, Any]]] = {}
    unite_refusee = False
    for fournisseur in sorted(derniere):
        entree = derniere[fournisseur]
        unite_prix = entree.get("unite")
        unite_confirmee = (
            isinstance(unite_prix, str) and isinstance(unite, str)
            and unite_prix.strip() != "" and unite_prix.strip() == unite.strip()
        )
        if not unite_confirmee:
            unite_refusee = True
            continue
        devise = entree.get("devise")
        prix = _prix_utilisable(entree.get("prix_unitaire"))
        if prix is None or not isinstance(devise, str) or devise.strip().upper() != _DEVISE:
            continue
        utilisables[fournisseur] = (prix, entree)
    if not utilisables:
        return _inconnu(MOTIF_UNITE if unite_refusee else MOTIF_AUCUN_PRIX)
    if len({prix for prix, _ in utilisables.values()}) > 1:
        return _inconnu(MOTIF_AMBIGU)
    entrees = [e for _, e in (utilisables[f] for f in sorted(utilisables))]
    tous_sources = all(livre_prix.marquage_source_document(e.get("source_document")) == "SOURCE_DECLAREE" for e in
    entrees)
    (prix_unique,) = {prix for prix, _ in utilisables.values()}
    return {
        "cout_unitaire": prix_unique,
        "origine": {
            "source": SOURCE_LIVRE_PRIX,
            "marquage": "SOURCE_DECLAREE" if tous_sources else "FALLBACK_PRICE_BOOK",
            "prix": [
                {"fournisseur_id": f, "source_document": utilisables[f][1].get("source_document"),
                 "date_effet": utilisables[f][1].get("date_effet")}
                for f in sorted(utilisables)
            ],
        },
    }


def resoudre(
    chantier_id: str,
    materiau_id: str,
    unite: Any,
    jour: date | None,
    mouvements: Iterable[Mapping[str, Any]],
    livre: Iterable[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """`{"cout_unitaire": float | None, "origine": {...}}` pour une ligne de sortie, selon l'ordre du module.

    `mouvements` : les maillons du registre de stock ; `livre` : le livre de prix (`None` : pas de livre lu, les deux
    premières sources seulement). Ne lève jamais pour une donnée manquante : le résultat dit pourquoi il n'y a pas de
    coût."""
    mouvements = list(mouvements)
    maillon, cout = _cout_de_reception(mouvements, materiau_id, chantier_id)
    if maillon is not None:
        return {"cout_unitaire": cout, "origine": {
            "source": SOURCE_RECEPTION_CHANTIER, "reference": maillon.get("hash_maillon"), "marquage": None}}
    maillon, cout = _cout_de_reception(mouvements, materiau_id, None)
    if maillon is not None:
        return {"cout_unitaire": cout, "origine": {
            "source": SOURCE_RECEPTION_ARTICLE, "reference": maillon.get("hash_maillon"), "marquage": None}}
    if livre is None:
        return _inconnu(MOTIF_AUCUN_PRIX)
    return _depuis_le_livre(materiau_id, unite, jour, livre)


def attentes_cout_inconnu(mouvements: Iterable[Mapping[str, Any]], livre: Iterable[Mapping[str, Any]],
                          jour_de: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Les attentes de l'admin pour les sorties dont le coût est resté INCONNU : une par article, tant que le
    livre de prix d'AUJOURD'HUI ne donne toujours pas de coût pour ce même article, dans la même unité. Déclarer un
    prix fait disparaître l'attente ; le mouvement d'alors, lui, n'est jamais réécrit (le registre est append-only).

    `jour_de` : `wct_id` -> jour du WCT (ou `None`). `depuis` : le jour du plus ancien WCT concerné."""
    livre = list(livre)
    mouvements = list(mouvements)
    par_article: dict[str, dict[str, Any]] = {}
    for maillon in mouvements:
        origine = maillon.get("origine_cout")
        if not isinstance(origine, Mapping) or origine.get("source") != SOURCE_INCONNU:
            continue
        courant = par_article.setdefault(maillon["materiau_id"], {"unite": maillon.get("unite"), "wct": [],
                                                                  "motif": origine.get("motif")})
        courant["wct"].append(maillon.get("wct_id"))
        courant["motif"] = origine.get("motif")
    attentes = []
    for materiau_id in sorted(par_article):
        info = par_article[materiau_id]
        jours = [jour_de.get(w) for w in info["wct"] if jour_de.get(w) is not None]
        resolution = resoudre("", materiau_id, info["unite"], max(jours) if jours else None, [], livre)
        if resolution["cout_unitaire"] is not None:
            continue
        unite = info["unite"]
        motif = _MOTIFS_LISIBLES.get(resolution["origine"]["motif"], "").format(unite=unite)
        attentes.append({
            "type": TYPE_ATTENTE_COUT_INCONNU,
            "id": f"{TYPE_ATTENTE_COUT_INCONNU}:{materiau_id}",
            "resume": (
                f"Coût de sortie inconnu : {materiau_id} ({unite}) a été déclaré utilisé, mais {motif}. "
                "La quantité est comptée ; seul le coût manque."
            ),
            "niveau": NIVEAU_ATTENTE,
            "depuis": min(jour.isoformat() for jour in jours) if jours else "",
            "action_proposee": (
                f"Déclarer le prix : m6_enregistrer_prix (matériau {materiau_id}, fournisseur, prix, devise CAD, "
                f"date d'effet, unité {unite}, et le document source s'il existe). Sans document, le prix reste "
                "marqué FALLBACK_PRICE_BOOK."
            ),
        })
    return attentes
