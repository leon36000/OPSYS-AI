import copy

from . import encodage

# PLAN T1.1-d2 : RETOUR/PERTE/BRIS, écrits uniquement par materiel.soumettre_materiaux_utilises
# (garde_ecriture_stock de conformite.py l'autorise explicitement, DESIGNATION_TYPE_MOUVEMENT).
TYPES_MOUVEMENT_VALIDES = frozenset(
    {"RECEPTION", "CONSOMMATION", "VARIANCE_INVENTAIRE", "RETOUR", "PERTE", "BRIS"}
)
HASH_PREDECESSEUR_INITIAL = ""

_CHAMPS_MOUVEMENT_REQUIS = {"type_mouvement", "chantier_id", "materiau_id", "quantite", "cout_unitaire"}


class Registre:
    """Registre append-only hash-chaîné de M6.

    Module pur : aucun import `opsys` ni SQLAlchemy (AGENTS.md, docs/decisions/ADR-0009-socle-
    metier.md). `Registre` ignore où vivent ses maillons — une liste Python en mémoire
    (`maillons=None`, comportement historique, perdue à l'arrêt du processus) ou tout objet qui
    s'en comporte comme une : `len`, index positif/négatif, tranche, itération, `append`,
    `extend`, copie profonde en liste. `opsys.stockage.maillons(...)` (ADR-0009) satisfait ce
    protocole ; c'est `outils.py`, seul, qui l'y branche pour le registre de production. Aucun
    état dérivé (tête, taille) n'est mis en cache : tout est relu ou recalculé depuis les
    maillons à chaque appel, donc rien n'est jamais supposé vide ou petit.
    """

    def __init__(self, maillons=None):
        self._maillons = [] if maillons is None else maillons

    def _construire_maillon(self, mouvement, index, hash_precedent):
        # PLAN T1.1-d2 : wct_id est OPTIONNEL et rétrocompatible à dessein — présent
        # seulement quand materiel.soumettre_materiaux_utilises le fournit (idempotence
        # par wct_id, lecture ciblée par variance_chantier.comparer_depuis_registre).
        # Absent (tout appelant antérieur : RECEPTION/CONSOMMATION historique/
        # VARIANCE_INVENTAIRE), la forme du maillon et son hash restent IDENTIQUES
        # bit à bit à avant ce changement : ni la clé ni sa valeur n'entrent dans
        # encodage.empreinte(...) ; test_registre.py (huit clés exactes) le prouve déjà
        # sans modification.
        wct_id = mouvement.get("wct_id")
        valeurs_hash = [
            index,
            mouvement["type_mouvement"],
            mouvement["chantier_id"],
            mouvement["materiau_id"],
            mouvement["quantite"],
            mouvement["cout_unitaire"],
            hash_precedent,
        ]
        if wct_id is not None:
            valeurs_hash.append(wct_id)
        # Extension étiquetée : les anciens maillons sans unité gardent leur empreinte.
        if "unite" in mouvement:
            valeurs_hash.append({"unite_declaree": mouvement["unite"]})
        hash_maillon = encodage.empreinte(*valeurs_hash)

        maillon = {
            "index": index,
            "type_mouvement": mouvement["type_mouvement"],
            "chantier_id": mouvement["chantier_id"],
            "materiau_id": mouvement["materiau_id"],
            "quantite": mouvement["quantite"],
            "cout_unitaire": mouvement["cout_unitaire"],
            "hash_precedent": hash_precedent,
            "hash_maillon": hash_maillon,
        }
        if wct_id is not None:
            maillon["wct_id"] = wct_id
        if "unite" in mouvement:
            maillon["unite"] = mouvement["unite"]
        return maillon

    def ajouter(self, mouvement):
        if not _CHAMPS_MOUVEMENT_REQUIS.issubset(mouvement.keys()):
            return None, "REJ-MOUVEMENT-STRUCTURE-INVALIDE"
        if mouvement["type_mouvement"] not in TYPES_MOUVEMENT_VALIDES:
            return None, "REJ-MOUVEMENT-TYPE-INVALIDE"
        if "unite" in mouvement and (not isinstance(mouvement["unite"], str) or not mouvement["unite"].strip()):
            return None, "REJ-MOUVEMENT-UNITE-INVALIDE"

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
            if "unite" in mouvement and (not isinstance(mouvement["unite"], str) or not mouvement["unite"].strip()):
                return None, "REJ-MOUVEMENT-UNITE-INVALIDE"

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

    def taille(self):
        return len(self._maillons)

    def hash_tete(self):
        if not self._maillons:
            return HASH_PREDECESSEUR_INITIAL
        return self._maillons[-1]["hash_maillon"]

    def valider_chaine(self):
        hash_precedent_attendu = HASH_PREDECESSEUR_INITIAL

        for index, maillon in enumerate(self._maillons):
            if maillon["hash_precedent"] != hash_precedent_attendu:
                return False, f"maillon invalide à l'index {index}"

            # Symétrique de _construire_maillon : wct_id entre dans le hash seulement
            # s'il est présent sur CE maillon (PLAN T1.1-d2).
            valeurs_hash = [
                maillon["index"],
                maillon["type_mouvement"],
                maillon["chantier_id"],
                maillon["materiau_id"],
                maillon["quantite"],
                maillon["cout_unitaire"],
                maillon["hash_precedent"],
            ]
            if "wct_id" in maillon:
                valeurs_hash.append(maillon["wct_id"])
            if "unite" in maillon:
                valeurs_hash.append({"unite_declaree": maillon["unite"]})
            hash_attendu = encodage.empreinte(*valeurs_hash)
            if maillon["hash_maillon"] != hash_attendu:
                return False, f"maillon invalide à l'index {index}"

            hash_precedent_attendu = maillon["hash_maillon"]

        return True, ""
