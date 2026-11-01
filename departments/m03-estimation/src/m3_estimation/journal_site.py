"""Journal append-only hash-chaîné du contexte de site et de la gouvernance des mesures issues de la vision (M3.2,
M3.3, M3.5 ; `docs/architecture/M3-M4-MATHIS-GABRIEL.md`).

Pourquoi un journal à part : le registre d'estimation (`registre.py`) exige les six clés d'une charge `EstimationV1`
et le registre des devis (`devis_durable.py`) porte des lignes commerciales ; ni l'un ni l'autre ne doit recevoir un
contexte de site ou la décision d'un humain sur une mesure candidate. Ce journal est une collection distincte
(`opsys.stockage.maillons("m03-estimation", "site_vision")`), même mécanisme (liste-protocole, rang attendu).

Trois types de maillons, fermés :

    ``contexte_site``     une version du contexte de site d'un lead (voir `contexte_site.py`) ;
    ``candidat_vision``   un candidat de mesure produit par un détecteur de vision, avec le verdict de gouvernance ;
    ``decision_vision``   la décision d'un humain ou d'une mesure de référence sur un candidat (une seule par candidat).

Module pur : aucun import `opsys`, aucune horloge, aucun aléa, aucun réseau. Les horodatages viennent de l'appelant.
Aucun flottant n'entre au journal (les grandeurs sont des textes décimaux) : un flottant est refusé. Comme le registre
d'estimation, la chaîne détecte l'altération d'un maillon suivi d'un autre ; elle ne prouve ni l'authenticité métier
des charges, ni la réécriture cohérente de la chaîne entière (mitigation : épingler `hash_tete()` hors du journal).
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

__all__ = ["HASH_INITIAL", "JournalSite", "empreinte_canonique", "TYPE_CONTEXTE", "TYPE_CANDIDAT", "TYPE_DECISION"]

FORMAT = "m3.journal_site/v1"
HASH_INITIAL = "0" * 64
TYPE_CONTEXTE = "contexte_site"
TYPE_CANDIDAT = "candidat_vision"
TYPE_DECISION = "decision_vision"
_TYPES = frozenset({TYPE_CONTEXTE, TYPE_CANDIDAT, TYPE_DECISION})
_CLES_MAILLON = frozenset({"rang", "type_entree", "charge", "hash_precedent", "hash_maillon", "format"})
_PROFONDEUR_MAX = 12


def _controler(valeur: Any, profondeur: int = 0) -> None:
    """Lève `TypeError` hors des types JSON exacts : un flottant, un `Decimal` ou une date n'entrent pas au journal."""
    if profondeur > _PROFONDEUR_MAX:
        raise TypeError("charge trop profonde")
    if valeur is None or type(valeur) in (str, bool, int):
        return
    if isinstance(valeur, (list, tuple)):
        for element in valeur:
            _controler(element, profondeur + 1)
        return
    if isinstance(valeur, dict):
        for cle, element in valeur.items():
            if type(cle) is not str:
                raise TypeError("clé non textuelle")
            _controler(element, profondeur + 1)
        return
    raise TypeError(f"type interdit au journal : {type(valeur).__name__}")


def empreinte_canonique(*valeurs: Any) -> str:
    """SHA-256 d'une forme canonique INJECTIVE (longueur + JSON trié, comme `registre.py`) : deux suites de valeurs
    différentes n'ont jamais la même forme."""
    segments = []
    for valeur in valeurs:
        _controler(valeur)
        texte = json.dumps(valeur, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        segments.append(f"{len(texte)}:{texte}")
    return hashlib.sha256("".join(segments).encode("ascii")).hexdigest()


def _hash_maillon(rang: int, type_entree: str, hash_precedent: str, charge: Any) -> str:
    return empreinte_canonique(FORMAT, rang, type_entree, hash_precedent, charge)


class JournalSite:
    """Journal des maillons du site et de la vision. `maillons` : liste, ou support durable
    (`opsys.stockage.MaillonsDurables`) ; l'adaptateur `outils_site_vision.py` choisit."""

    def __init__(self, maillons: Any = None) -> None:
        self._maillons = maillons if maillons is not None else []

    def ajouter(self, type_entree: str, charge: dict[str, Any]) -> dict[str, Any]:
        """Ajoute un maillon et le rend. `ValueError` si le type est inconnu ou la charge n'est pas du JSON exact."""
        if type_entree not in _TYPES:
            raise ValueError(f"type de maillon inconnu : {type_entree!r}")
        if not isinstance(charge, dict):
            raise ValueError("la charge doit être un objet")
        try:
            copie = copy.deepcopy(charge)
            _controler(copie)
        except (TypeError, RecursionError) as exc:
            raise ValueError(f"charge non canonique : {exc}") from None
        rang = len(self._maillons)
        precedent = HASH_INITIAL if rang == 0 else self._maillons[-1]["hash_maillon"]
        maillon = {
            "format": FORMAT,
            "rang": rang,
            "type_entree": type_entree,
            "charge": copie,
            "hash_precedent": precedent,
            "hash_maillon": _hash_maillon(rang, type_entree, precedent, copie),
        }
        if isinstance(self._maillons, list):
            self._maillons.append(maillon)
        else:
            self._maillons.append(maillon, rang_attendu=rang)
        return copy.deepcopy(maillon)

    def lire(self, type_entree: str | None = None) -> list[dict[str, Any]]:
        """Copie profonde des maillons (d'un type, ou tous), du plus ancien au plus récent."""
        tous = copy.deepcopy(list(self._maillons))
        return [m for m in tous if type_entree is None or m["type_entree"] == type_entree]

    def hash_tete(self) -> str:
        return HASH_INITIAL if not self._maillons else self._maillons[-1]["hash_maillon"]

    def valider_chaine(self) -> tuple[bool, str]:
        """`(True, "")` si la chaîne est intacte, sinon `(False, "rang N")` au premier maillon fautif."""
        attendu = HASH_INITIAL
        for rang, maillon in enumerate(self._maillons):
            try:
                if (
                    not isinstance(maillon, dict)
                    or set(maillon) != _CLES_MAILLON
                    or maillon["format"] != FORMAT
                    or type(maillon["rang"]) is not int
                    or maillon["rang"] != rang
                    or maillon["type_entree"] not in _TYPES
                    or maillon["hash_precedent"] != attendu
                    or maillon["hash_maillon"]
                    != _hash_maillon(rang, maillon["type_entree"], maillon["hash_precedent"], maillon["charge"])
                ):
                    return False, f"rang {rang}"
            except (KeyError, TypeError, ValueError, RecursionError):
                return False, f"rang {rang}"
            attendu = maillon["hash_maillon"]
        return True, ""
