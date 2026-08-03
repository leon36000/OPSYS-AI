from __future__ import annotations

import copy
from datetime import datetime

from . import encodage

__all__ = ["Registre", "enregistrer_mouvement"]

_TYPE_ENTREE_VALIDES = {
    "mouvement_enregistre",
    "demande_creee",
    "transition_approbation",
}

_CHAMPS_MOUVEMENT = (
    "montant",
    "type_mouvement",
    "horodatage",
    "classe_retention",
    "source",
)


def _valider_horodatage_local(chaine):
    try:
        dt = datetime.fromisoformat(chaine)
    except Exception:
        raise ValueError("horodatage invalide (format ISO 8601 avec fuseau requis)")
    if dt.tzinfo is None:
        raise ValueError("horodatage invalide (fuseau horaire absent)")


class Registre:
    def __init__(self):
        self._chain = []

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


def enregistrer_mouvement(mouvement_valide, registre_cible):
    entree = {champ: mouvement_valide[champ] for champ in _CHAMPS_MOUVEMENT}
    entree["type_entree"] = "mouvement_enregistre"
    ligne_id = registre_cible.ajouter(entree)
    for maillon in registre_cible.lire():
        if maillon["ligne_id"] == ligne_id:
            return maillon
    raise RuntimeError("Maillon ajouté introuvable.")

