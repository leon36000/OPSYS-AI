"""Registre de snapshots chaîné, append-only, pour M9 Strategic Intelligence.

Module pur (ADR-0009) : aucun import d'``opsys`` ni de SQLAlchemy. ``RegistreSnapshots`` ne sait
pas où vivent ses maillons — une liste Python en mémoire par défaut (perdue à l'arrêt du
processus, comportement historique), ou tout objet qui s'en comporte comme une (``len``, index
positif et négatif, tranche, itération, ``append``), notamment ``opsys.stockage.MaillonsDurables``
— c'est `outils.py` (l'adaptateur, seul) qui fait ce choix pour le registre de production. Aucun
état n'est mis en cache séparément des maillons reçus : ``hash_tete`` et ``valider_chaine``
relisent ``self._maillons`` à chaque appel, donc une instance rouverte sur un registre durable
déjà peuplé (redémarrage du processus) reflète immédiatement l'état réel.
"""
import copy

from . import encodage

HASH_PREDECESSEUR_INITIAL = ""


class RegistreSnapshots:
    def __init__(self, maillons=None):
        """``maillons`` : la suite où vivent les maillons (protocole liste, cf. docstring du
        module). ``None`` (par défaut) garde le comportement historique : une liste Python en
        mémoire, vide au départ."""
        self._maillons = maillons if maillons is not None else []

    def ajouter(self, snapshot):
        index = len(self._maillons)
        hash_precedent = (
            self._maillons[-1]["hash_maillon"]
            if self._maillons
            else HASH_PREDECESSEUR_INITIAL
        )
        hash_maillon = encodage.empreinte(
            index,
            snapshot["module_source"],
            snapshot["horodatage"],
            snapshot["valeurs"],
            hash_precedent,
        )
        maillon = {
            "index": index,
            "module_source": snapshot["module_source"],
            "horodatage": snapshot["horodatage"],
            "valeurs": copy.deepcopy(snapshot["valeurs"]),
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
