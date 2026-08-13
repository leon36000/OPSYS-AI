import copy

from . import encodage

TYPES_MOUVEMENT_VALIDES = frozenset(
    {"RECEPTION", "CONSOMMATION", "VARIANCE_INVENTAIRE"}
)
HASH_PREDECESSEUR_INITIAL = ""

_CHAMPS_MOUVEMENT_REQUIS = {"type_mouvement", "chantier_id", "materiau_id", "quantite", "cout_unitaire"}


class Registre:
    def __init__(self):
        self._maillons = []

    def _construire_maillon(self, mouvement, index, hash_precedent):
        hash_maillon = encodage.empreinte(
            index,
            mouvement["type_mouvement"],
            mouvement["chantier_id"],
            mouvement["materiau_id"],
            mouvement["quantite"],
            mouvement["cout_unitaire"],
            hash_precedent,
        )
        return {
            "index": index,
            "type_mouvement": mouvement["type_mouvement"],
            "chantier_id": mouvement["chantier_id"],
            "materiau_id": mouvement["materiau_id"],
            "quantite": mouvement["quantite"],
            "cout_unitaire": mouvement["cout_unitaire"],
            "hash_precedent": hash_precedent,
            "hash_maillon": hash_maillon,
        }

    def ajouter(self, mouvement):
        if not _CHAMPS_MOUVEMENT_REQUIS.issubset(mouvement.keys()):
            return None, "REJ-MOUVEMENT-STRUCTURE-INVALIDE"
        if mouvement["type_mouvement"] not in TYPES_MOUVEMENT_VALIDES:
            return None, "REJ-MOUVEMENT-TYPE-INVALIDE"

        hash_precedent = (
            self._maillons[-1]["hash_maillon"]
            if self._maillons
            else HASH_PREDECESSEUR_INITIAL
        )
        maillon = self._construire_maillon(mouvement, len(self._maillons), hash_precedent)
        self._maillons.append(maillon)
        return copy.deepcopy(maillon), None

    def ajouter_lot(self, mouvements):
        for mouvement in mouvements:
            if not _CHAMPS_MOUVEMENT_REQUIS.issubset(mouvement.keys()):
                return None, "REJ-MOUVEMENT-STRUCTURE-INVALIDE"
            if mouvement["type_mouvement"] not in TYPES_MOUVEMENT_VALIDES:
                return None, "REJ-MOUVEMENT-TYPE-INVALIDE"

        maillons_construits = []
        hash_precedent = (
            self._maillons[-1]["hash_maillon"]
            if self._maillons
            else HASH_PREDECESSEUR_INITIAL
        )
        for i, mouvement in enumerate(mouvements):
            maillon = self._construire_maillon(mouvement, len(self._maillons) + i, hash_precedent)
            maillons_construits.append(maillon)
            hash_precedent = maillon["hash_maillon"]
        self._maillons.extend(maillons_construits)
        return copy.deepcopy(maillons_construits), None

    def lire(self):
        return copy.deepcopy(self._maillons)

    def hash_tete(self):
        if not self._maillons:
            return HASH_PREDECESSEUR_INITIAL
        return self._maillons[-1]["hash_maillon"]

    def valider_chaine(self):
        hash_precedent_attendu = HASH_PREDECESSEUR_INITIAL

        for index, maillon in enumerate(self._maillons):
            if maillon["hash_precedent"] != hash_precedent_attendu:
                return False, f"maillon invalide à l'index {index}"

            hash_attendu = encodage.empreinte(
                maillon["index"],
                maillon["type_mouvement"],
                maillon["chantier_id"],
                maillon["materiau_id"],
                maillon["quantite"],
                maillon["cout_unitaire"],
                maillon["hash_precedent"],
            )
            if maillon["hash_maillon"] != hash_attendu:
                return False, f"maillon invalide à l'index {index}"

            hash_precedent_attendu = maillon["hash_maillon"]

        return True, ""
