"""Registre append-only générique de M10 : la chaîne de hash, rien d'autre.

Module pur (DA-M10-08) : aucun import d'``opsys`` ni de SQLAlchemy. ``Registre`` ne sait pas où
vivent ses maillons — en mémoire (une simple liste, valeur par défaut) ou dans le stockage
durable de l'instance (``opsys.stockage.maillons(...)``, qui se comporte comme une liste). Tout
état dérivé (tête, validité de la chaîne) est recalculé à chaque appel depuis les maillons reçus,
jamais mis en cache : le module reste correct quel que soit l'objet injecté.
"""

from __future__ import annotations

import copy
from datetime import datetime

from . import encodage

__all__ = ["Registre"]

_TYPE_ENTREE_VALIDES = {
    "evenement_memorise",
    "decision_enregistree",
    "revision_signalee",
}


def _valider_horodatage_local(chaine):
    try:
        dt = datetime.fromisoformat(chaine)
    except Exception:
        raise ValueError("horodatage invalide (format ISO 8601 avec fuseau requis)")
    if dt.tzinfo is None:
        raise ValueError("horodatage invalide (fuseau horaire absent)")


class Registre:
    def __init__(self, maillons=None):
        """``maillons`` : la liste (ou tout objet compatible liste, cf. docstring du module) où
        vivent les maillons. ``None`` (par défaut) garde le comportement historique : une liste
        Python en mémoire, perdue à l'arrêt du processus — c'est le mode des tests unitaires.
        """
        self._chain = maillons if maillons is not None else []

    def ajouter(self, entree):
        if not isinstance(entree, dict):
            raise TypeError("L'entrée doit être un dictionnaire.")

        type_entree = entree.get("type_entree")
        if type_entree not in _TYPE_ENTREE_VALIDES:
            raise ValueError(
                f"type_entree non reconnu : {type_entree!r}. "
                f"Attendu l'un de {sorted(_TYPE_ENTREE_VALIDES)}."
            )

        if "horodatage" not in entree:
            raise KeyError("horodatage")
        _valider_horodatage_local(entree["horodatage"])

        entree_copy = copy.deepcopy(entree)
        entree_copy.pop("ligne_id", None)
        entree_copy.pop("precedent_ligne_id", None)

        precedent = self._chain[-1]["ligne_id"] if self._chain else None
        ligne_id = encodage.empreinte(entree_copy, precedent)

        maillon = dict(entree_copy)
        maillon["ligne_id"] = ligne_id
        maillon["precedent_ligne_id"] = precedent

        self._chain.append(maillon)
        return ligne_id

    def lire(self):
        return copy.deepcopy(self._chain)

    def tete(self):
        return self._chain[-1]["ligne_id"] if self._chain else None

    def valider_chaine(self):
        precedent_attendu = None
        for maillon in self._chain:
            if maillon["precedent_ligne_id"] != precedent_attendu:
                return False, f"maillon invalide : {maillon['ligne_id']}"
            corps = {
                k: v
                for k, v in maillon.items()
                if k not in ("ligne_id", "precedent_ligne_id")
            }
            ligne_id_attendu = encodage.empreinte(corps, precedent_attendu)
            if maillon["ligne_id"] != ligne_id_attendu:
                return False, f"maillon invalide : {maillon['ligne_id']}"
            precedent_attendu = maillon["ligne_id"]
        return True, ""
