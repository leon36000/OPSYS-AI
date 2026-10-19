"""Lecture des observations WCT par période, sans effet métier (M9, tranche « observations de chantier »).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge, aucune base. La période ``[debut, fin)`` est
fournie par l'appelant, avec fuseaux, et comparée en instants ; aucune semaine devinée, aucun jour calendaire.

Deux entrées, fournies par l'adaptateur natif :

1. le registre COMPLET des snapshots M9, dont la chaîne est déjà validée ; les rangs entiers exacts sont
   recontrôlés ici avant tout filtre ;
2. la correspondance ``evenement_id -> charge`` des premières publications ``m8.snapshot_chantier`` du bus,
   chacune déjà validée contre le schéma du catalogue par l'adaptateur (jamais revalidée ici).

Tout snapshot dont une clé de ``valeurs`` commence par ``m8_snapshot_`` se déclare transporté : hors période
comprise, il doit porter EXACTEMENT les trois métadonnées (identifiant, rang texte canonique, empreinte), venir
de ``m04-field-ops`` et projeter exactement la charge publiée sous cet identifiant (même instant d'origine, mêmes
valeurs M4, rien de plus). Un identifiant ou un WCT présent deux fois est refusé, même à l'identique : un
snapshot générique T1 peut recopier ces métadonnées. Un snapshot sans ce marqueur n'est pas un fait de cette
vue : il est compté globalement dans ``snapshots_generiques_non_couverts``, sa date n'est jamais lue.

La liaison au bus n'authentifie pas M8 : chaque observation dit ``source_bus_liee`` et
``authentification_producteur = NON_PROUVEE``. Observations connues à la lecture, filtrées sur l'instant
métier d'origine ; ni instant de réception, ni état historique.

``vue`` : empreinte du registre complet, de la correspondance exacte des publications et des bornes reçues ;
tout ajout, hors période ou générique compris, périme une reprise. Taille de la réponse ENTIÈRE mesurée,
maillons, publications et ``manques`` compris, avant chaque observation ajoutée : jamais de troncature.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any

from .echeancier_suivis import _EMPREINTE, _instant, _taille
from .encodage import empreinte

__all__ = ["ORDRE_OBSERVATIONS", "lister_observations_chantier"]

_TYPE = "OBSERVATIONS_CHANTIER_PERIODE"
ORDRE_OBSERVATIONS = "instant métier d'origine croissant (fuseaux comparés), puis evenement_id"
_MARQUEUR = "m8_snapshot_"
_CHAMP_ID = "m8_snapshot_evenement_id"
_CHAMP_INDEX = "m8_snapshot_index"
_CHAMP_HASH = "m8_snapshot_hash_maillon"
_METADONNEES = frozenset({_CHAMP_ID, _CHAMP_INDEX, _CHAMP_HASH})
_PREFIXE = "m8-snapshot-chantier-"
_MODULE_SOURCE = "m04-field-ops"
_INDEX_TEXTE = re.compile(r"0|[1-9][0-9]*")
_MANQUES_PERMANENTS = (
    {
        "section": "authentification_producteur",
        "constat": "chaque observation est liée par identifiant, empreinte et charge exacte à la première "
                   "publication m8.snapshot_chantier du bus ; aucune signature de M8",
        "verifie": "NON_PROUVEE : source_bus_liee seulement",
    },
    {
        "section": "snapshots_generiques",
        "constat": "snapshots sans métadonnées m8_snapshot_* comptés sur tout le registre, hors période comprise ; "
                   "leurs dates ne sont pas lues",
        "verifie": "NON_COUVERT : aucun fait de période tiré des snapshots génériques",
    },
    {
        "section": "reception_observations",
        "constat": "filtre sur l'instant métier d'origine. Observations connues à la lecture : un WCT transporté "
                   "plus tard, d'instant dans la période, s'ajoute et change total et vue",
        "verifie": "NON_COUVERT : aucun instant de réception ni état historique lu",
    },
    {
        "section": "couverture",
        "constat": "premiers WCT durables transportés après activation seulement ; ni rattrapage, ni M1-M8 "
                   "complet, ni total financier, ni rapport hebdomadaire",
        "verifie": "NON_COUVERT : aucune couverture complète prétendue",
    },
)


def _nom(valeur: Any) -> str:
    """Identifiant cité dans un refus, borné : jamais le contenu du snapshot."""
    return repr(valeur[:200] if isinstance(valeur, str) else type(valeur).__name__)


def _borne(valeur: Any, nom: str) -> datetime:
    """Borne ISO 8601 à fuseau explicite, aucun repli UTC."""
    if not isinstance(valeur, str):
        raise ValueError(f"REJ-OBSERVATIONS-PERIODE : {nom} chaîne ISO 8601 avec fuseau explicite attendue")
    try:
        instant = _instant(valeur, nom)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"REJ-OBSERVATIONS-PERIODE : {nom} illisible ou sans fuseau explicite") from exc
    if instant.utcoffset() is None:
        raise ValueError(f"REJ-OBSERVATIONS-PERIODE : {nom} sans fuseau explicite")
    return instant


def _lier(rang: int, maillon: dict[str, Any], publications: dict[str, Any]) -> tuple[str, str, datetime]:
    """Snapshot qui se déclare transporté : métadonnées exactes, liaison au bus exacte, instant à fuseau.
    Rend ``(evenement_id, wct_id, instant)`` ou lève un refus nommé ; hors période compris."""
    valeurs = maillon["valeurs"]
    if {cle for cle in valeurs if cle.startswith(_MARQUEUR)} != _METADONNEES:
        raise ValueError(
            f"REJ-OBSERVATIONS-TRANSPORT : snapshot de rang {rang} sans exactement les trois métadonnées m8_snapshot_*"
        )
    evenement_id, index, hash_maillon = valeurs[_CHAMP_ID], valeurs[_CHAMP_INDEX], valeurs[_CHAMP_HASH]
    if not (
        isinstance(hash_maillon, str) and _EMPREINTE.fullmatch(hash_maillon)
        and isinstance(index, str) and _INDEX_TEXTE.fullmatch(index)
        and evenement_id == _PREFIXE + hash_maillon
    ):
        raise ValueError(f"REJ-OBSERVATIONS-TRANSPORT : métadonnées non canoniques au rang {rang}")
    if maillon.get("module_source") != _MODULE_SOURCE:
        raise ValueError(f"REJ-OBSERVATIONS-TRANSPORT : snapshot transporté de rang {rang} hors {_MODULE_SOURCE}")
    publication = publications.get(evenement_id)
    if publication is None:
        raise ValueError(
            f"REJ-OBSERVATIONS-BUS-ABSENT : aucune publication m8.snapshot_chantier {_nom(evenement_id)} "
            f"(rang {rang})"
        )
    projection = {cle: valeur for cle, valeur in valeurs.items() if cle not in _METADONNEES}
    source = publication.get("source_m8") if isinstance(publication, dict) else None
    fait = publication.get("snapshot") if isinstance(publication, dict) else None
    if not (
        isinstance(publication, dict) and publication.get("evenement_id") == evenement_id
        and isinstance(source, dict) and set(source) == {"index", "hash_maillon"}
        and type(source["index"]) is int and str(source["index"]) == index
        and source["hash_maillon"] == hash_maillon
        and isinstance(fait, dict) and fait.get("module_source") == _MODULE_SOURCE
        and fait.get("horodatage") == maillon.get("horodatage")
        and fait.get("valeurs") == projection
    ):
        raise ValueError(
            f"REJ-OBSERVATIONS-BUS-DIVERGENT : snapshot de rang {rang} ne projette pas exactement la publication "
            f"{_nom(evenement_id)}"
        )
    wct_id = projection.get("m4_wct_id")
    if not isinstance(wct_id, str) or not wct_id:
        raise ValueError(f"REJ-OBSERVATIONS-TRANSPORT : m4_wct_id absent ou vide au rang {rang}")
    horodatage = maillon.get("horodatage")
    try:
        if not isinstance(horodatage, str):
            raise TypeError(horodatage)
        instant = _instant(horodatage, "horodatage")
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"REJ-OBSERVATIONS-FUSEAU : instant d'origine illisible ou sans fuseau explicite pour "
            f"{_nom(evenement_id)}, aucun repli UTC"
        ) from exc
    if instant.utcoffset() is None:
        raise ValueError(
            f"REJ-OBSERVATIONS-FUSEAU : instant d'origine sans fuseau explicite pour {_nom(evenement_id)}"
        )
    return evenement_id, wct_id, instant


def _controler(
    maillons: list[dict[str, Any]] | tuple[dict[str, Any], ...], publications: dict[str, Any],
) -> tuple[list[tuple[datetime, str, dict[str, Any]]], int]:
    """Tout le registre, hors période comprise, avant tout filtre : rangs, liaisons, doublons, correspondance."""
    liees: list[tuple[datetime, str, dict[str, Any]]] = []
    generiques = 0
    identifiants: set[str] = set()
    wcts: set[str] = set()
    for rang, maillon in enumerate(maillons):
        if not isinstance(maillon, dict) or type(maillon.get("index")) is not int or maillon["index"] != rang:
            raise ValueError(f"REJ-OBSERVATIONS-REGISTRE : rang entier exact absent au rang {rang}")
        valeurs = maillon.get("valeurs")
        if not isinstance(valeurs, dict) or not all(isinstance(cle, str) for cle in valeurs):
            raise ValueError(f"REJ-OBSERVATIONS-REGISTRE : valeurs non objet au rang {rang}")
        if not any(cle.startswith(_MARQUEUR) for cle in valeurs):
            generiques += 1
            continue
        evenement_id, wct_id, instant = _lier(rang, maillon, publications)
        if evenement_id in identifiants or wct_id in wcts:
            raise ValueError(
                f"REJ-OBSERVATIONS-DOUBLON : événement {_nom(evenement_id)} ou WCT {_nom(wct_id)} lié plusieurs "
                f"fois (rang {rang}), même à l'identique"
            )
        identifiants.add(evenement_id)
        wcts.add(wct_id)
        liees.append((instant, evenement_id, maillon))
    if set(publications) != identifiants:
        raise ValueError("REJ-OBSERVATIONS-BUS-DIVERGENT : publications fournies sans snapshot transporté lié")
    return liees, generiques


def lister_observations_chantier(
    maillons: list[dict[str, Any]],
    publications: dict[str, Any],
    debut: str,
    fin: str,
    depart: int = 0,
    vue_attendue: str | None = None,
    *,
    budget_caracteres: int,
) -> dict[str, Any]:
    """Une page de ``OBSERVATIONS_CHANTIER_PERIODE`` pour ``[debut, fin)`` : snapshots transportés liés au bus
    dont l'instant d'origine tombe dans la période, dans l'ordre de ``ORDRE_OBSERVATIONS`` à partir de
    ``depart``, autant d'observations complètes que ``budget_caracteres`` en laisse tenir. ``debut``/``fin``
    sont rendus tels que reçus. Les entrées ne sont jamais modifiées ; maillons et publications rendus sont
    des copies profondes des originaux, inchangés."""
    if isinstance(depart, bool) or not isinstance(depart, int) or depart < 0:
        raise ValueError(f"REJ-OBSERVATIONS-ARGUMENT : depart entier supérieur ou égal à 0 attendu, reçu {depart!r}")
    if isinstance(budget_caracteres, bool) or not isinstance(budget_caracteres, int) or budget_caracteres < 1:
        raise ValueError("REJ-OBSERVATIONS-ARGUMENT : budget_caracteres entier strictement positif attendu")
    if vue_attendue is not None and (not isinstance(vue_attendue, str) or not _EMPREINTE.fullmatch(vue_attendue)):
        raise ValueError("REJ-OBSERVATIONS-ARGUMENT : vue_attendue empreinte hexadécimale de 64 caractères attendue")
    if depart > 0 and vue_attendue is None:
        raise ValueError("REJ-OBSERVATIONS-VUE : vue_attendue de la page précédente requise pour depart > 0")
    borne_debut = _borne(debut, "debut")
    borne_fin = _borne(fin, "fin")
    if not borne_debut < borne_fin:
        raise ValueError("REJ-OBSERVATIONS-PERIODE : debut strictement antérieur à fin requis (instants comparés)")
    if not isinstance(maillons, (list, tuple)):
        raise ValueError("REJ-OBSERVATIONS-ARGUMENT : registre complet des snapshots attendu")
    if not isinstance(publications, dict) or not all(isinstance(cle, str) for cle in publications):
        raise ValueError("REJ-OBSERVATIONS-ARGUMENT : correspondance evenement_id -> publication attendue")

    liees, generiques = _controler(maillons, publications)
    vue = empreinte({
        "type": _TYPE, "debut": debut, "fin": fin, "maillons": list(maillons),
        "publications": [[evenement_id, publications[evenement_id]] for evenement_id in sorted(publications)],
    })
    if vue_attendue is not None and vue_attendue != vue:
        raise ValueError(
            "REJ-OBSERVATIONS-VUE-PERIMEE : registre, publications ou bornes ont changé ; reprendre à depart=0"
        )

    retenues = [
        {
            "maillon": copy.deepcopy(maillon),
            "publication": copy.deepcopy(publications[evenement_id]),
            "nature": "source_bus_liee",
            "authentification_producteur": "NON_PROUVEE",
        }
        for instant, evenement_id, maillon in sorted(liees, key=lambda liee: (liee[0], liee[1]))
        if borne_debut <= instant < borne_fin
    ]
    total = len(retenues)
    if depart > total:
        raise ValueError(f"REJ-OBSERVATIONS-ARGUMENT : depart {depart} au-delà de la fin ({total} observation(s))")
    manques = [dict(manque) for manque in _MANQUES_PERMANENTS]
    if not total:
        manques.append({"section": "observations_periode",
                        "constat": "aucun snapshot transporté lié d'instant d'origine dans [debut, fin)",
                        "verifie": "VIDE : aucune observation retenue par le filtre de période"})

    def page(nombre: int) -> dict[str, Any]:
        dernier = depart + nombre
        reste = total - dernier
        return {
            "type": _TYPE,
            "debut": debut,
            "fin": fin,
            "vue": vue,
            "total": total,
            "depart": depart,
            "affichees": nombre,
            "reste": reste,
            "prochain_depart": dernier if reste else None,
            "ordre": ORDRE_OBSERVATIONS,
            "observations": retenues[depart:dernier],
            "snapshots_generiques_non_couverts": generiques,
            "manques": manques,
            "statut": "NON_VALIDE",
            "actualite_metier": "NON_EVALUEE",
            "rapport_complet": False,
        }

    if _taille(page(0)) > budget_caracteres:
        raise ValueError(
            f"REJ-OBSERVATIONS-BORNE : squelette et manques au-delà de la borne de {budget_caracteres} caractères"
        )
    nombre = 0
    while depart + nombre < total and _taille(page(nombre + 1)) <= budget_caracteres:
        nombre += 1
    if depart < total and nombre == 0:
        raise ValueError(
            f"REJ-OBSERVATIONS-BORNE : l'observation "
            f"{_nom(retenues[depart]['publication']['evenement_id'])} dépasse à elle seule la borne de "
            f"{budget_caracteres} caractères avec ses preuves, aucune troncature autorisée"
        )
    return page(nombre)
