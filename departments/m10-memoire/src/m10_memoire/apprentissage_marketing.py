"""Mémoire marketing de M10 (M7-MEMOIRE) : les observations d'apprentissage que M7 annonce après son rapport
hebdomadaire,
rangées telles quelles, puis regroupées pour que `opsys.mnemo.lecons` en tire des LEÇONS GOUVERNÉES.

M7 publie `m7.apprentissage_marketing_constate` : une observation MINIMALE et agrégée (genre, canal, clé de mesure
d'un contenu
ou catégorie d'avis, comptes entiers, empreinte du rapport). Aucun texte de contenu, d'avis ou de client, aucune
coordonnée,
aucun identifiant de lead ou de chantier : M10 ne reçoit rien de personnel et n'en reconstitue pas.

Règles :

* LISTE BLANCHE, FORMES FERMÉES. Chaque champ gardé a une forme ; un champ de plus, manquant ou hors forme est un
refus nommé
  qui dit le CHAMP, jamais la valeur (même patron que les dossiers de période scellés) ;
* IDEMPOTENCE. Un maillon par ``observation_id`` (déterministe chez M7) : une relivraison, ou la même observation sous
un autre
  ``evenement_id``, n'ajoute rien. Le MÊME ``observation_id`` avec un AUTRE contenu est une contradiction : refus
  nommé, la
  première observation reste ;
* CONFIDENTIALITÉ. Entrée ``INTERNAL`` : des comptes d'entreprise, jamais une donnée de client ;
* UNE OBSERVATION N'EST PAS UNE LEÇON. ``groupes_pour_lecons`` compte seulement des observations DISTINCTES (semaines
  différentes) ; la leçon, son évaluation hors ligne et sa décision humaine sont dans ``opsys.mnemo.lecons``.

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from . import confidentialite, validation

TYPE_EVENEMENT = "m7.apprentissage_marketing_constate"
TYPE_ENTREE = "fait_marketing"
PRODUCTEUR = "m07-marketing"

REJ_FAIT_MARKETING_CHAMP_INVALIDE = "REJ-FAIT-MARKETING-CHAMP-INVALIDE"
REJ_FAIT_MARKETING_CONTRADICTOIRE = "REJ-FAIT-MARKETING-CONTRADICTOIRE"

_GENRES = ("contenu_gagnant", "contenu_faible", "objection_frequente", "avis_constate")
_CANAUX = ("facebook", "instagram", "fiche_google", "video_courte", "demande_temoignage", "avis_clients")
SEMAINES_MIN = 3  # une leçon candidate exige des observations de ce nombre de semaines distinctes
_OBSERVATION_ID = re.compile(r"^m7-appr-[0-9a-f]{40}$")
_JOUR = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_CLE_MESURE = re.compile(r"^[a-z0-9_-]{1,80}$")
_EMPREINTE = re.compile(r"^[0-9a-f]{64}$")
_CLES = frozenset(
    {"observation_id", "semaine", "genre_observation", "canal", "cle_mesure", "resultat", "rapport_empreinte"}
)
_CLES_RESULTAT = frozenset(
    {"leads", "devis_envoyes", "devis_acceptes", "occurrences", "avis_positifs", "avis_negatifs"}
)
_MAX_COMPTE = 1_000_000


def genres_observation() -> tuple[str, ...]:
    """Les genres d'observation que M7 annonce (liste fermée, jamais un énuméré public du paquet)."""
    return _GENRES


def canaux() -> tuple[str, ...]:
    return _CANAUX


class ChampRefuse(ValueError):
    """Un champ manque ou sort de sa forme fermée. ``code`` est le verdict, ``detail`` le CHAMP (jamais sa valeur)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail

    def verdict(self) -> dict[str, Any]:
        return validation.construire_verdict(self.code, self.detail)


def _texte(valeur: Any, champ: str, motif: re.Pattern[str]) -> str:
    if not isinstance(valeur, str) or not motif.fullmatch(valeur):
        raise ChampRefuse(REJ_FAIT_MARKETING_CHAMP_INVALIDE, champ)
    return valeur


def _compte(valeur: Any, champ: str) -> int | None:
    if valeur is None:
        return None
    if isinstance(valeur, bool) or not isinstance(valeur, int) or not 0 <= valeur <= _MAX_COMPTE:
        raise ChampRefuse(REJ_FAIT_MARKETING_CHAMP_INVALIDE, champ)
    return valeur


def extraire(charge: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(charge, Mapping) or set(charge) != _CLES:
        raise ChampRefuse(REJ_FAIT_MARKETING_CHAMP_INVALIDE, "(racine)")
    resultat = charge["resultat"]
    if not isinstance(resultat, Mapping) or set(resultat) != _CLES_RESULTAT:
        raise ChampRefuse(REJ_FAIT_MARKETING_CHAMP_INVALIDE, "resultat")
    if charge["genre_observation"] not in _GENRES:
        raise ChampRefuse(REJ_FAIT_MARKETING_CHAMP_INVALIDE, "genre_observation")
    if charge["canal"] not in _CANAUX:
        raise ChampRefuse(REJ_FAIT_MARKETING_CHAMP_INVALIDE, "canal")
    cle = charge["cle_mesure"]
    return {
        "observation_id": _texte(charge["observation_id"], "observation_id", _OBSERVATION_ID),
        "semaine": _texte(charge["semaine"], "semaine", _JOUR),
        "genre_observation": charge["genre_observation"],
        "canal": charge["canal"],
        "cle_mesure": None if cle is None else _texte(cle, "cle_mesure", _CLE_MESURE),
        "resultat": {k: _compte(resultat[k], f"resultat.{k}") for k in sorted(resultat)},
        "rapport_empreinte": _texte(charge["rapport_empreinte"], "rapport_empreinte", _EMPREINTE),
    }


def entree(champs: Mapping[str, Any]) -> dict[str, Any]:
    """Le maillon à écrire : les champs extraits, puis ce que M10 pose (jamais la charge)."""
    return {
        **champs,
        "type_entree": TYPE_ENTREE,
        "producteur": PRODUCTEUR,
        "confidentialite": confidentialite.NIVEAU_INTERNE,
        # La semaine est un JOUR et M10 n'a pas d'horloge : le registre exige un instant avec fuseau, c'est le début de
        # ce jour en UTC, jamais l'heure de la réception.
        "horodatage": f"{champs['semaine']}T00:00:00+00:00",
    }


def memoriser(charge: Mapping[str, Any], registre_cible: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Mémorise une observation ; rend ``(resultat, None)`` ou ``(None, verdict)``, sans rien écrire au refus.
    ``resultat`` : ``{maillon, deja_memorise}``. Un seul maillon par ``observation_id``."""
    try:
        champs = extraire(charge)
    except ChampRefuse as refus:
        return None, refus.verdict()
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") == TYPE_ENTREE and maillon.get("observation_id") == champs["observation_id"]:
            if any(maillon.get(k) != v for k, v in champs.items()):
                return None, validation.construire_verdict(REJ_FAIT_MARKETING_CONTRADICTOIRE, "observation_id")
            return {"maillon": maillon, "deja_memorise": True}, None
    ligne_id = registre_cible.ajouter(entree(champs))
    maillon = next(m for m in registre_cible.lire() if m["ligne_id"] == ligne_id)
    return {"maillon": maillon, "deja_memorise": False}, None


def groupes_pour_lecons(maillons: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Les groupes d'observations qui peuvent fonder une leçon, comptés en semaines DISTINCTES.

    Un groupe : ``(genre_observation, canal)`` pour un contenu gagnant ou faible, ``(genre, canal, catégorie)`` pour
    un signal
    d'objection ; un avis n'est un groupe que les semaines où les avis défavorables dépassent les favorables. Seuls
    les groupes
    d'au moins ``SEMAINES_MIN`` semaines distinctes sont rendus. Rien n'est jugé ici : ce sont des comptes."""
    groupes: dict[tuple[str, str, str], dict[str, Any]] = {}
    for m in maillons:
        if m.get("type_entree") != TYPE_ENTREE:
            continue
        genre, canal, cle, res = m["genre_observation"], m["canal"], m["cle_mesure"], m["resultat"]
        if genre == "avis_constate":
            if (res["avis_negatifs"] or 0) <= (res["avis_positifs"] or 0):
                continue
            cle_groupe = ""
        elif genre == "objection_frequente":
            cle_groupe = cle or ""
        else:
            cle_groupe = ""
        g = groupes.setdefault(
            (genre, canal, cle_groupe),
            {
                "genre_observation": genre,
                "canal": canal,
                "categorie": cle_groupe or None,
                "semaines": set(),
                "observations": 0,
                "leads": 0,
                "occurrences": 0,
                "cles_mesure": set(),
                "lignes": [],
            },
        )
        g["semaines"].add(m["semaine"])
        g["observations"] += 1
        g["leads"] += res["leads"] or 0
        g["occurrences"] += res["occurrences"] or 0
        if genre in ("contenu_gagnant", "contenu_faible") and cle:
            g["cles_mesure"].add(cle)
        g["lignes"].append(m["ligne_id"])
    sortie = []
    for cle_groupe in sorted(groupes):
        g = groupes[cle_groupe]
        if len(g["semaines"]) < SEMAINES_MIN:
            continue
        sortie.append(
            {
                "genre_observation": g["genre_observation"],
                "canal": g["canal"],
                "categorie": g["categorie"],
                "semaines_distinctes": len(g["semaines"]),
                "observations": g["observations"],
                "leads": g["leads"],
                "occurrences": g["occurrences"],
                "cles_mesure": sorted(g["cles_mesure"])[:10],
                "lignes": sorted(g["lignes"])[:5],
            }
        )
    return sortie
