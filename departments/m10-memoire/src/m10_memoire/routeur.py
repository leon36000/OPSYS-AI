"""Noyau pur de fusion RRF pour M10-07.

Ce module ne lit aucune source, ne vérifie aucune autorisation et ne sépare pas les profils. L'appelant doit
fournir des listes déjà filtrées par ses adaptateurs autorisés; cela ne constitue pas une preuve de droits.
Avant toute exposition comme outil, un orchestrateur devra encore contrôler l'identité, les permissions,
l'isolation du domaine et les règles de confidentialité AVANT d'appeler les sources.

La fusion ne fait qu'un RRF pondéré par source : les poids et k sont obligatoires, donc aucune priorité métier
n'est implicite. Les facteurs de statut, fraîcheur, autorité et module prévus au backlog restent à définir.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

DOMAINES = frozenset({"affaires", "developpement"})
_IDENTIFIANT = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_CHAMPS_CANDIDAT = frozenset({
    "domaine", "source", "reference", "rang", "contenu", "citation", "statut", "fraicheur", "autorite", "module"
})


class RefusRouteur(ValueError):
    """Entrée de fusion ambiguë ou hors contrat."""


def _entier_positif(valeur: Any, nom: str) -> int:
    if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur <= 0:
        raise RefusRouteur(f"{nom} doit être un entier strictement positif")
    return valeur


def _texte(valeur: Any, nom: str) -> str:
    if not isinstance(valeur, str) or not valeur.strip():
        raise RefusRouteur(f"{nom} doit être un texte non vide")
    return valeur


def _poids(valeur: Any, nom: str) -> float:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        raise RefusRouteur(f"{nom} doit être un nombre fini non négatif")
    try:
        resultat = float(valeur)
    except (OverflowError, ValueError):
        raise RefusRouteur(f"{nom} doit être un nombre fini non négatif") from None
    if not math.isfinite(resultat) or resultat < 0:
        raise RefusRouteur(f"{nom} doit être un nombre fini non négatif")
    return resultat


def _valider_candidat(candidat: Any, domaine: str, source: str) -> dict[str, Any]:
    if not isinstance(candidat, Mapping) or set(candidat) != _CHAMPS_CANDIDAT:
        raise RefusRouteur("candidat : champs requis exacts attendus")
    if candidat["domaine"] != domaine:
        raise RefusRouteur("domaine candidat incohérent")
    if candidat["source"] != source:
        raise RefusRouteur("source candidate incohérente avec sa liste")
    reference = _texte(candidat["reference"], "reference")
    if reference != reference.strip():
        raise RefusRouteur("reference entouree d'espaces")
    _entier_positif(candidat["rang"], "rang")
    _texte(candidat["contenu"], "contenu")
    for champ in ("statut", "fraicheur", "autorite", "module"):
        _texte(candidat[champ], champ)
    citation = candidat["citation"]
    if not isinstance(citation, Mapping) or not citation:
        raise RefusRouteur("citation structurelle requise")
    if citation.get("reference") != reference or citation.get("source") != source:
        raise RefusRouteur("source ou référence de citation incohérente")
    if any(not isinstance(cle, str) or not cle or not isinstance(v, str) or not v.strip()
           for cle, v in citation.items()):
        raise RefusRouteur("provenance de citation ambiguë")
    if not any(cle in citation for cle in ("sha256", "hash", "line_id", "version", "id")):
        raise RefusRouteur("citation sans ancre déclarée")
    return dict(candidat)


def fusionner(
    *,
    domaine: str,
    listes: Mapping[str, Sequence[Mapping[str, Any]]],
    k: int,
    poids_sources: Mapping[str, float],
    limite: int,
    max_caracteres_extraits: int,
) -> dict[str, Any]:
    """Fusionne des candidats préfiltrés selon ``somme(poids/(k+rang))``.

    Le poids de chaque source est exigé explicitement. Les références sont les clés de dédoublonnage; une même
    référence provenant de plusieurs voies n'est fusionnée que si contenu, citation et métadonnées concordent.
    Les résultats sont départagés par référence puis source, indépendamment de l'ordre d'entrée.

    ``max_caracteres_extraits`` borne uniquement la somme des extraits ``contenu``. Citations, références et autres
    métadonnées sont conservées intactes : cette limite ne borne PAS la taille sérialisée de la réponse complète.
    """
    if not isinstance(domaine, str) or domaine not in DOMAINES:
        raise RefusRouteur("domaine fermé attendu : affaires ou developpement")
    k = _entier_positif(k, "k")
    limite = _entier_positif(limite, "limite")
    max_caracteres_extraits = _entier_positif(max_caracteres_extraits, "max_caracteres_extraits")
    if not isinstance(listes, Mapping) or not listes:
        raise RefusRouteur("au moins une liste source non vide est requise")
    if not isinstance(poids_sources, Mapping) or set(poids_sources) != set(listes):
        raise RefusRouteur("un poids explicite est requis pour chaque source, sans source supplémentaire")

    poids = {}
    for source in listes:
        if not isinstance(source, str) or not _IDENTIFIANT.fullmatch(source):
            raise RefusRouteur("identifiant de source invalide")
        poids[source] = _poids(poids_sources[source], f"poids {source}")
    if not any(valeur > 0 for valeur in poids.values()):
        raise RefusRouteur("au moins un poids de source positif est requis")

    par_reference: dict[str, dict[str, Any]] = {}
    for source in sorted(listes):
        candidats = listes[source]
        if not isinstance(candidats, Sequence) or isinstance(candidats, (str, bytes)) or not candidats:
            raise RefusRouteur(f"liste de candidats non vide requise pour {source}")
        rangs: set[int] = set()
        references_source: set[str] = set()
        for brut in candidats:
            candidat = _valider_candidat(brut, domaine, source)
            rang = candidat["rang"]
            if rang in rangs:
                raise RefusRouteur(f"rang en double pour {source}")
            rangs.add(rang)
            reference = candidat["reference"]
            if reference in references_source:
                raise RefusRouteur(f"reference en double dans la source {source}")
            references_source.add(reference)
            try:
                contribution = poids[source] / (k + rang)
            except (OverflowError, ZeroDivisionError):
                raise RefusRouteur("score RRF non fini") from None
            if not math.isfinite(contribution):
                raise RefusRouteur("score RRF non fini")
            if poids[source] > 0 and contribution == 0:
                raise RefusRouteur("contribution RRF positive devenue nulle par sous-flux")
            existant = par_reference.get(reference)
            if existant is None:
                par_reference[reference] = {
                    "candidat": candidat,
                    "score": contribution,
                    "sources": {source},
                    "citations": {source: dict(candidat["citation"])},
                }
                continue
            precedent = existant["candidat"]
            champs_comparaison = _CHAMPS_CANDIDAT - {"source", "rang", "citation"}
            if any(precedent[champ] != candidat[champ] for champ in champs_comparaison):
                raise RefusRouteur("collision de référence avec contenu, citation ou métadonnées divergents")
            citation_precedente = {k: v for k, v in precedent["citation"].items() if k != "source"}
            citation_courante = {k: v for k, v in candidat["citation"].items() if k != "source"}
            if citation_precedente != citation_courante:
                raise RefusRouteur("ancres de citation divergentes pour une même référence")
            score = existant["score"] + contribution
            if not math.isfinite(score):
                raise RefusRouteur("score RRF non fini")
            existant["score"] = score
            existant["sources"].add(source)
            existant["citations"][source] = dict(candidat["citation"])

    ordonnes = sorted(
        par_reference.values(),
        key=lambda entree: (-entree["score"], entree["candidat"]["reference"], entree["candidat"]["source"]),
    )
    resultats: list[dict[str, Any]] = []
    caracteres = 0
    tronque = len(ordonnes) > limite
    for entree in ordonnes[:limite]:
        candidat = entree["candidat"]
        restant = max_caracteres_extraits - caracteres
        if restant <= 0:
            tronque = True
            break
        contenu = candidat["contenu"]
        rendu = contenu[:restant]
        est_tronque = len(rendu) < len(contenu)
        tronque = tronque or est_tronque
        caracteres += len(rendu)
        resultats.append({
            **candidat,
            "contenu": rendu,
            "score": entree["score"],
            "sources": sorted(entree["sources"]),
            "citations": [entree["citations"][source] for source in sorted(entree["citations"])],
            "tronque": est_tronque,
        })
    return {
        "domaine": domaine,
        "resultats": resultats,
        "tronque": tronque,
        "caracteres_extraits": caracteres,
        "autorisation_verifiee": False,
        "profil_isole": False,
        "avertissement": (
            "Noyau de fusion seulement : aucune autorisation, isolation de profil ni lecture de source "
            "n'est effectuée. "
            "La limite ne borne que les extraits, pas la sérialisation complète. "
            "Ne pas exposer comme outil avant implémentation des contrôles et d'une borne de réponse globale."
        ),
    }
