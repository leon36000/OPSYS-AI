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

__all__ = ["Registre", "types_entree"]

_TYPE_ENTREE_VALIDES = {
    "evenement_memorise",
    "decision_enregistree",
    "revision_signalee",
    "fait_consolide",  # PLAN T3.3 : consolidation.py, un fait durable qui cite ses sources
    "fait_candidat",  # PLAN T3.3-suite : faits_candidats.py, dépôt POSTFLIGHT du core, jamais une vérité
    "signal_traite",  # PLAN T3.3-suite-b : signaux.py, passage d'un signal critique par un humain identifié
    "session_affaire_liee",  # PLAN T3.3-suite-b : liaison.py, l'affaire d'une session, écrite par un humain
    "session_affaire_revoquee",  # retrait humain CAS d'une liaison de session, historique append-only
    "memoire_developpement",  # Tranche mémoire dev : événements, sources et relations dans le registre durable
    "provenance_documentaire",  # source métier autonome, sans affaire client implicite
    "fait_analytique",  # M8.18 : analytique.py, consolidation des mesures d'entreprise publiée par M8 (registre dédié)
    # Mnémo (docs/architecture/M10-SOI-GRAPHE.md) : modèle de soi (registre `soi`) et leçons (registre `lecons`).
    # Le contenu et les règles de ces entrées vivent dans `opsys.mnemo` ; ce registre n'en connaît que le type.
    "soi_enonce", "soi_decision", "soi_corroboration", "soi_derive",
    "lecon_proposee", "lecon_evaluation", "lecon_decision",
    "fait_strategique",  # Athéna : strategique.py, décision, résultat mesuré ou leçon publiés par M9 (registre dédié)
    "rapport_routine",  # routines planifiées (routines.py) : audit « non-oubli » et KPI, registre `rapports_routine`
    "dossier_cpa_scelle",  # interconnexion M5 -> M10 : dossiers_cpa.py, mémoire des périodes scellées (registre dédié)
    "fait_marketing",  # M7-MEMOIRE : apprentissage_marketing.py, observations minimales de M7 (registre dédié)
    # M10-04 (contradictions.py) : registres `affirmations` et `contradictions`, append-only, état rejoué.
    "affirmation_enregistree", "affirmation_retiree",
    "contradiction_detectee", "contradiction_marque", "contradiction_demande", "contradiction_decidee",
    # Mémoire d'expérience des agents, jalon J1 (opsys.mnemo.experience) : registre `experiences`.
    "experience_proposee", "experience_refusee",
}


def types_entree() -> tuple[str, ...]:
    """Les types d'entrée qu'un registre accepte, dans un ordre stable.

    C'est le contrat d'écriture de ``Registre.ajouter``, exposé pour qu'un lecteur (la batterie
    M10-05, par exemple) puisse refuser un maillon qui n'en est pas un sans réimplémenter la liste.
    """
    return tuple(sorted(_TYPE_ENTREE_VALIDES))


def _valider_horodatage_local(chaine):
    try:
        dt = datetime.fromisoformat(chaine)
    except Exception as erreur:
        raise ValueError("horodatage invalide (format ISO 8601 avec fuseau requis)") from erreur
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
                f"type_entree non reconnu : {type_entree!r}. Attendu l'un de {sorted(_TYPE_ENTREE_VALIDES)}."
            )

        if "horodatage" not in entree:
            raise KeyError("horodatage")
        _valider_horodatage_local(entree["horodatage"])

        entree_copy = copy.deepcopy(entree)
        entree_copy.pop("ligne_id", None)
        entree_copy.pop("precedent_ligne_id", None)

        # La tête et la précondition d'append viennent de la même lecture de longueur. Un
        # registre durable refuse l'append si un autre écrivain a inséré entre-temps ; les
        # listes en mémoire gardent leur append historique.
        rang_attendu = len(self._chain)
        precedent = self._chain[rang_attendu - 1]["ligne_id"] if rang_attendu else None
        ligne_id = encodage.empreinte(entree_copy, precedent)

        maillon = dict(entree_copy)
        maillon["ligne_id"] = ligne_id
        maillon["precedent_ligne_id"] = precedent

        append_attendu = getattr(self._chain, "append_avec_rang_attendu", None)
        if callable(append_attendu):
            append_attendu(maillon, rang_attendu=rang_attendu)
        else:
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
            corps = {k: v for k, v in maillon.items() if k not in ("ligne_id", "precedent_ligne_id")}
            ligne_id_attendu = encodage.empreinte(corps, precedent_attendu)
            if maillon["ligne_id"] != ligne_id_attendu:
                return False, f"maillon invalide : {maillon['ligne_id']}"
            precedent_attendu = maillon["ligne_id"]
        return True, ""
