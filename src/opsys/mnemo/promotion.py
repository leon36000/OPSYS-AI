"""Promotion gouvernée d'une proposition apprise : proposée → canari → complète, ou retour arrière, ou refusée.

C'est la généralisation propre du mécanisme de la boucle d'apprentissage de M1 (`m1_front_office.apprentissage.etat`,
M1.13), qui ne sait promouvoir que des règles de tri : mêmes états, mêmes transitions, même fonction de hachage pour le
canari, mais indépendant de ce qu'on promeut. Un test de parité (`tests/test_mnemo_promotion.py`) rejoue les mêmes
décisions dans les deux moteurs et exige les mêmes états.

Règles :

- le journal est l'unique source de vérité : l'état est TOUJOURS rejoué depuis les maillons, jamais lu dans un champ ;
- un seul canari à la fois (une part de 1 à 50 % des cas, choisie par une fonction de hachage de la clé d'application :
  un même cas tombe toujours du même côté) ;
- « complète » exige un canari en cours ; « retour arrière » vaut pour un canari ou une proposition complète ; «
  refusée » pour une proposition encore seulement proposée ;
- `ordre_strict` : dans M1, les propositions complètes s'empilent (le retour arrière défait la dernière seulement).
  Pour des propositions indépendantes (les leçons), on peut défaire n'importe laquelle, et c'est plus sûr : une leçon
  nocive se retire tout de suite, sans attendre qu'on défasse celles qui l'ont suivie ;
- aucune horloge, aucun réseau, aucun modèle ici. Module pur.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

from . import codes
from .codes import ErreurMnemo

ETAPES = ("canari", "complete", "retour_arriere", "refusee")
ETAT_PROPOSEE = "proposee"
ETAT_CANARI = "canari"
ETAT_COMPLETE = "complete"
ETAT_RETIREE = "retiree"
ETAT_REFUSEE = "refusee"
POURCENTAGE_MIN = 1
POURCENTAGE_MAX = 50


@dataclasses.dataclass(frozen=True)
class EtatPromotion:
    etats: Mapping[str, str]  # identifiant -> proposee | canari | complete | retiree | refusee
    pile: tuple[str, ...]  # identifiants complets, dans l'ordre de promotion
    canari: tuple[str, int] | None  # (identifiant, pourcentage)

    def actives(self) -> tuple[str, ...]:
        return self.pile


def dans_le_canari(cle_application: str, pourcentage: int, *, graine: str = "") -> bool:
    """Vrai si le cas `cle_application` tombe dans la part du canari. Pure et stable : un message rejoué reçoit la même
    réponse. Sans `graine`, c'est exactement la fonction de M1 (`apprentissage.dans_le_canari`)."""
    sel = "canari|" + (graine + "|" if graine else "") + cle_application
    return int(hashlib.sha256(sel.encode()).hexdigest()[:8], 16) % 100 < pourcentage


def transition(courant: str | None, etape: str, *, est_au_sommet: bool, canari_pris: bool, ordre_strict: bool) -> str:
    """Nouvel état après `etape`, ou `ErreurMnemo(LECON_TRANSITION)`. `courant` est None pour une proposition
    inconnue."""
    if courant is None:
        raise ErreurMnemo(codes.LECON_INCONNUE, "décision sur une proposition absente")
    if etape == "canari" and courant == ETAT_PROPOSEE:
        if canari_pris:
            raise ErreurMnemo(codes.LECON_TRANSITION, "un canari est déjà en cours : le conclure d'abord")
        return ETAT_CANARI
    if etape == "complete" and courant == ETAT_CANARI:
        return ETAT_COMPLETE
    if etape == "retour_arriere" and courant == ETAT_CANARI:
        return ETAT_RETIREE
    if etape == "retour_arriere" and courant == ETAT_COMPLETE and (est_au_sommet or not ordre_strict):
        return ETAT_RETIREE
    if etape == "refusee" and courant == ETAT_PROPOSEE:
        return ETAT_REFUSEE
    raise ErreurMnemo(codes.LECON_TRANSITION, f"« {etape} » illégal depuis « {courant} »")


def rejouer(
    maillons: Iterable[Mapping[str, Any]],
    *,
    type_proposition: str,
    type_decision: str,
    cle_id: str,
    ordre_strict: bool = False,
) -> EtatPromotion:
    """Rejoue le journal : l'état de chaque proposition. Une décision illégale (journal altéré ou écrit à la main) est
    un
    refus typé, jamais ignorée."""
    etats: dict[str, str] = {}
    pile: list[str] = []
    canari: tuple[str, int] | None = None
    for m in maillons:
        t = m.get("type_entree")
        if t == type_proposition:
            etats.setdefault(m[cle_id], ETAT_PROPOSEE)
        elif t == type_decision:
            ident, etape = m[cle_id], m["etape"]
            if etape not in ETAPES:
                raise ErreurMnemo(codes.LECON_TRANSITION, f"étape inconnue « {etape} »")
            nouveau = transition(
                etats.get(ident),
                etape,
                est_au_sommet=bool(pile) and pile[-1] == ident,
                canari_pris=canari is not None,
                ordre_strict=ordre_strict,
            )
            ancien = etats[ident]
            etats[ident] = nouveau
            if etape == "canari":
                pct = m.get("pourcentage")
                if type(pct) is not int or not POURCENTAGE_MIN <= pct <= POURCENTAGE_MAX:
                    raise ErreurMnemo(
                        codes.LECON_CANARI, f"le canari porte sur {POURCENTAGE_MIN} à {POURCENTAGE_MAX} %"
                    )
                canari = (ident, pct)
            elif etape == "complete":
                pile.append(ident)
                canari = None
            elif etape == "retour_arriere":
                if ancien == ETAT_CANARI:
                    canari = None
                elif ident in pile:
                    pile.remove(ident)
    return EtatPromotion(dict(etats), tuple(pile), canari)
