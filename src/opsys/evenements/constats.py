"""Constat rejoué avec une clé de contenu IDENTIQUE mais un contenu DIFFÉRENT : le dire, sans rien écraser.

Les consommateurs d'interconnexion sont idempotents par une clé de CONTENU (relance, relevé + révision, facture +
statut...) : le même constat rejoué sous un autre `evenement_id` n'écrit rien. Cette idempotence avait un angle
mort : la MÊME clé avec un contenu différent était ignorée comme si c'était un rejeu, sans alerte (revue adverse rvi).
Seul M10 nommait la contradiction de sceau (`REJ-DOSSIER-CPA-SCEAU-CONTRADICTOIRE`, refus nommé puis quarantaine).

Règle commune (M2, M5, M8), pure et sans accès à la base :

- le PREMIER état est gardé, rien n'est écrasé ni corrigé ;
- la contradiction est rangée dans le registre `constats_contradictoires` du destinataire (append-only) : le type du
  constat, sa clé, le NOM des champs qui diffèrent (jamais leur valeur) et deux empreintes (le premier contenu, le
  nouveau) ; le même constat contradictoire rejoué n'ajoute pas de seconde ligne ;
- le consommateur répond `contradiction` au bus (le reçu passe à `traite`, sans reprise : un refus déterministe n'est
  pas retenté) et le département l'expose dans son état de lecture existant ;
- le rejeu IDENTIQUE reste silencieux.

Ce module ne connaît aucun département : il compare des dictionnaires et fabrique la ligne d'audit.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

__all__ = [
    "CODE",
    "REGISTRE",
    "REGLE",
    "TYPE_ENTREE",
    "champs_differents",
    "compter",
    "deja_signalee",
    "empreinte_contenu",
    "ligne_contradiction",
]

REGISTRE = "constats_contradictoires"
TYPE_ENTREE = "constat_contradictoire"
REGLE = "meme_cle_contenu_different_premier_conserve/v1"
# Ce que le consommateur répond au bus (`contradiction`). Pas un refus `REJ-…` : le constat est rangé, pas rejeté.
CODE = "CONSTAT_CONTRADICTOIRE"


def _canonique(valeur: Any) -> str:
    return json.dumps(valeur, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def empreinte_contenu(contenu: Mapping[str, Any]) -> str:
    """Empreinte (32 hex) d'un contenu : indépendante de l'ordre des clés, des listes/tuples et du `evenement_id`."""
    return hashlib.sha256(_canonique(dict(contenu)).encode("utf-8")).hexdigest()[:32]


def champs_differents(existant: Mapping[str, Any], fait: Mapping[str, Any], ignorer: Iterable[str] = ()) -> list[str]:
    """Les NOMS des champs du `fait` dont la valeur diffère de celle de l'`existant` (les champs de chaîne ou de
    provenance, listés dans `ignorer`, ne comptent pas). Un champ absent de l'existant mais présent dans le fait
    diffère."""
    exclus = set(ignorer)
    return sorted(
        cle
        for cle, valeur in fait.items()
        if cle not in exclus and _canonique(existant.get(cle)) != _canonique(valeur)
    )


def ligne_contradiction(
    constat: str,
    cle: Mapping[str, Any],
    *,
    empreinte_premier: str,
    empreinte_nouveau: str,
    champs: list[str] | None,
    publie_le: str | None,
) -> dict[str, Any]:
    """La ligne d'audit à ranger. `champs` : les noms qui diffèrent (`None` quand le destinataire ne garde que
    l'empreinte du premier contenu). Jamais une valeur."""
    return {
        "type_entree": TYPE_ENTREE,
        "constat": constat,
        "cle": dict(cle),
        "champs": champs,
        "empreinte_premier": empreinte_premier,
        "empreinte_nouveau": empreinte_nouveau,
        "regle": REGLE,
        "publie_le": publie_le,
    }


def deja_signalee(registre: Iterable[Mapping[str, Any]], ligne: Mapping[str, Any]) -> bool:
    """Cette contradiction (même constat, même clé, même nouveau contenu) est-elle déjà rangée ?"""
    return any(
        m.get("type_entree") == TYPE_ENTREE
        and m.get("constat") == ligne["constat"]
        and m.get("cle") == ligne["cle"]
        and m.get("empreinte_nouveau") == ligne["empreinte_nouveau"]
        for m in registre
    )


def compter(registre: Iterable[Mapping[str, Any]]) -> int:
    """Le nombre de contradictions distinctes rangées (état de lecture du département)."""
    return sum(1 for m in registre if m.get("type_entree") == TYPE_ENTREE)
