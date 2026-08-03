import copy

from . import encodage

HASH_PREDECESSEUR_INITIAL = ""


class RegistreSnapshots:
    def __init__(self):
        self._maillons = []

    def ajouter(self, mouvement):
        index = len(self._maillons)
        hash_precedent = (
            self._maillons[-1]["hash_maillon"]
            if self._maillons
            else HASH_PREDECESSEUR_INITIAL
        )
        hash_maillon = encodage.empreinte(
            index,
            mouvement["module_source"],
            mouvement["horodatage"],
            mouvement["valeurs"],
            hash_precedent,
        )
        maillon = {
            "index": index,
            "module_source": mouvement["module_source"],
            "horodatage": mouvement["horodatage"],
            "valeurs": mouvement["valeurs"],
            "hash_precedent": hash_precedent,
            "hash_maillon": hash_maillon,
        }
        self._maillons.append(maillon)
        return copy.deepcopy(maillon), None

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
                maillon["module_source"],
                maillon["horodatage"],
                maillon["valeurs"],
                maillon["hash_precedent"],
            )
            if maillon["hash_maillon"] != hash_attendu:
                return False, f"maillon invalide à l'index {index}"

            hash_precedent_attendu = maillon["hash_maillon"]

        return True, ""
