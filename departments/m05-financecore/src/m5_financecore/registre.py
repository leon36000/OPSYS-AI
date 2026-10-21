from __future__ import annotations

import copy
from datetime import datetime

from . import encodage, validation

__all__ = ["Registre", "enregistrer_mouvement"]

# Module pur (ADR-0009) : aucun import d'`opsys` ni de SQLAlchemy. `Registre` ne sait pas où
# vivent ses maillons — une liste Python en mémoire par défaut (comportement historique, celui
# que gardent les tests unitaires existants), ou tout objet qui s'en comporte comme une (`len`,
# index positif et négatif, tranche, itération, `append`, `extend`, copie profonde en liste),
# notamment `opsys.stockage.MaillonsDurables` — c'est `outils.py` (l'adaptateur, seul) qui fait
# ce choix pour le registre de production des mouvements. Tout état dérivé (tête, validité de la
# chaîne) est déjà recalculé DEPUIS `self._chain` à chaque appel (`tete()`, `valider_chaine()`) :
# aucun cache séparé à invalider, une instance construite sur un registre durable déjà peuplé
# (relecture après redémarrage) reflète donc immédiatement l'état réel dès sa création.

_TYPE_ENTREE_VALIDES = {
    "declaration_obligation_preparee",
    "retrait_obligation_preparee",
    "mouvement_enregistre",
    "demande_creee",
    "transition_approbation",
    # M5.2 (facturation.py) : troisième famille sur le même registre générique, patron déjà
    # établi par les deux premières (mouvements, approbations) — aucune validation spécifique
    # ici, exactement comme "demande_creee"/"transition_approbation" : facturation.py valide
    # avant d'appeler `ajouter`.
    "facture_creee",
    "transition_facture",
    # M5.2 comptes à payer (PLAN T4.15) : quatrième famille, sur son propre registre. `comptes_a_payer.py` valide
    # avant d'appeler `ajouter`, comme facturation.py. Aucun de ces deux types n'est un mouvement financier.
    "reception_recue",
    "facture_fournisseur_saisie",
    # PLAN T4.15-c : la facture d'origine n'est JAMAIS modifiée. Une correction ou une annulation est une pièce de plus,
    # chaînée au registre, qui porte le motif, la personne et l'avant/après ; l'état courant d'une facture est relu de
    # ces pièces (`comptes_a_payer._etats_factures`). Aucun de ces types n'est un mouvement financier.
    "correction_facture_fournisseur",
    "annulation_facture_fournisseur",
    # M5.4.a : contrats horaires individuels, dans un flux durable propre aux salaires;
    # ces pièces ne sont jamais des mouvements financiers.
    "contrat_horaire_enregistre",
    "contrat_horaire_revoque",
    # M5.8a : échéanciers contractuels saisis et révocations; registre distinct des mouvements.
    "echeancier_contrat_enregistre",
    "echeancier_contrat_revoque",
    # Répartitions analytiques humaines, dans leur registre propre ; aucun mouvement financier.
    "affectation_cout_marketing_enregistree",
    "affectation_cout_marketing_retiree",
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
    except Exception as exc:
        raise ValueError("horodatage invalide (format ISO 8601 avec fuseau requis)") from exc
    if dt.tzinfo is None:
        raise ValueError("horodatage invalide (fuseau horaire absent)")


class Registre:
    def __init__(self, maillons=None):
        """`maillons` : la suite où vivent les maillons (protocole liste, cf. docstring du
        module). `None` (par défaut) garde le comportement historique : une liste Python en
        mémoire, vide au départ."""
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

        if type_entree == "mouvement_enregistre":
            corps_mouvement = {
                cle: valeur
                for cle, valeur in entree.items()
                if cle not in ("type_entree", "ligne_id", "precedent_ligne_id")
            }
            valide, verdict = validation.valider_mouvement(corps_mouvement)
            if not valide:
                raise validation.MouvementInvalide(verdict)

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

    def taille(self):
        return len(self._chain)

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
