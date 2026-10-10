"""Capacités d'agent du département M10 Mémoire.

Chaque outil enveloppe une fonction métier déterministe existante. `m10_journaliser_decision`
compose validation → écriture au registre Affaires → référence vérifiable en un seul appel ;
`m10_contexte_preflight` est le PREFLIGHT (D-014, docs/research/R4-memory-rag.md §10) qui
vérifie si un dossier de contexte est suffisant et, sinon, trace le refus au registre — sans
jamais interrompre l'appelant. PLAN T3.3 ajoute trois capacités : `m10_paquet_contexte_affaire`
(paquets de contexte en couches, `paquets.py`), `m10_consolider_affaire` (consolidation nocturne
idempotente, `consolidation.py`) et `m10_auditer_non_oubli` (audit « non-oubli », `audit.py`), plus
la consommation de `m6.variance_chantier` (`variance.py`, même registre Événements que le WCT).
PLAN T1.5-d ajoute la consommation de `m5.rentabilite_chantier` (`rentabilite.py`, même registre, entrée marquée
`FINANCIAL` : la marge d'un chantier ne sort dans aucun paquet de contexte).
PLAN T4.18 ajoute la consommation de l'AMONT d'une affaire (`amont.py`, `etapes.py`) : `m1.lead_qualifie`,
`m2.client_associe`, `m3.devis_accepte` et `m3.devis_sans_reponse`, mémorisés au même registre Événements (identifiants
et faits d'étape seulement ; le contact du lead n'est jamais copié ; le prix et le coût d'un devis accepté vont dans un
maillon `FINANCIAL`, le client associé est `CLIENT_PRIVATE`). Les consommateurs sont produits par la table de
`etapes.py` : une étape de plus (`m3.devis_envoye`) est une entrée de cette table et une ligne du manifeste.
PLAN T3.3-suite ajoute `m10_deposer_faits_candidats` (`faits_candidats.py`) : le POSTFLIGHT du moteur de
contexte du core y dépose ce que les outils ont fait pendant un tour d'agent ; `m10_paquet_contexte_affaire`
en est la lecture (PREFLIGHT).
PLAN T3.3-suite-b ajoute cinq capacités : `m10_lister_signaux`, `m10_prendre_en_compte_signal` et
`m10_clore_signal` (cycle de vie des signaux critiques, `signaux.py`), `m10_lier_session_affaire` et
`m10_affaire_de_la_session` (l'affaire vient de la session, `liaison.py`). Les trois écritures (prise en
compte, clôture, liaison) sont des décisions HUMAINES : `_acteur_humain` établit qui décide (jeton d'appareil
confirmé en base, ou approbation humaine en cours d'exécution) et refuse tout le reste, y compris un appel
direct d'agent dans un mode où l'approbation n'est pas requise.
PLAN T4.18-b : l'affaire a UNE forme commune au core et à M10 (`affaire.py` : un lead, ou l'opportunité
`<lead>~opp~<wct_id>` que M2 ouvre) ; le paquet de contexte porte, en plus de ses quatre couches, un bloc `affaire`
(connue ou non, origine reçue, verdict) et un bloc `consolidation` (les jours omis à consolider).

Deux registres DISTINCTS (CA-M10-06), chacun un singleton du processus de ce département, câblés
sur le stockage durable de l'instance (ADR-0009 décision 2, ADR-0010 décision 2) via
`opsys.stockage.maillons` : `_REGISTRE_EVENEMENTS` pour les événements opérationnels (Work
Completion Trigger de M4 et variance matériaux de M6 — registre anciennement nommé « Forge »,
renommé pour ne plus prêter à confusion avec l'outillage de développement), `_REGISTRE_AFFAIRES`
pour les décisions, révisions, traces de préflight et faits consolidés. Aucune fonction ci-dessous
n'accepte les deux registres en argument. Tous les autres modules du paquet restent purs : c'est
ici, et seulement ici, que le paquet touche `opsys` (stockage et bus).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection

from opsys import approbations, idempotence, jetons, stockage
from opsys import contexte as contexte_appel
from opsys.outils import Autonomie, Niveau, Outil, depuis_couple

from . import (
    amont,
    audit,
    catalogue_references,
    classification,
    consolidation,
    contexte,
    contrats,
    decisions,
    documents_affaire,
    dossier_revision,
    etapes,
    faits_candidats,
    humain,
    liaison,
    paquets,
    recherche_affaire,
    registre,
    rentabilite,
    revision,
    signaux,
    validation,
    variance,
    wct,
)
from . import confidentialite as regle_confidentialite

_REGISTRE_EVENEMENTS = registre.Registre(maillons=stockage.maillons("m10-memoire", "evenements"))
_REGISTRE_AFFAIRES = registre.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
_REGISTRES_NOMMES = {"evenements": _REGISTRE_EVENEMENTS, "affaires": _REGISTRE_AFFAIRES}

_DECISION = {
    "type": "object",
    "properties": {
        "decision_id": {"type": "string"},
        "raison": {"type": "string", "description": "Obligatoire, non vide — règle 4 de la fiche source."},
        "statut": {"type": "string", "enum": list(contrats.STATUT_DECISION)},
        "options_ecartees": {"type": "string"},
    },
    "required": sorted(contrats.CHAMPS_DECISION),
    "additionalProperties": False,
}
_WCT = {
    "type": "object",
    "description": (
        "WorkCompletionTriggerV1 gelé par M4 (m4_field_ops/outbox.py), reçu TEL QUEL (12 "
        "champs exacts) — hash_maillon est la preuve de M4, JAMAIS recalculée par M10."
    ),
}
_DOSSIER_CONTEXTE = {
    "type": "object",
    "properties": {
        "evenement": {"type": "string"},
        "resume": {"type": "string"},
        "preuves": {"type": "string"},
        "impact": {"type": "string"},
        "prochaine_action": {"type": "string"},
        "references_decisions": {"type": "array", "items": {"type": "string"}},
    },
    "required": sorted(contrats.CHAMPS_EVENEMENT_MEMOIRE) + ["references_decisions"],
    "additionalProperties": False,
}
_REFERENCE_MEMOIRE = {
    "type": "object",
    "properties": {
        "ligne_id": {"type": "string"},
        "registre": {"type": "string", "enum": sorted(_REGISTRES_NOMMES)},
        "hash_tete": {"type": ["string", "null"]},
    },
    "required": sorted(contrats.CHAMPS_REFERENCE_MEMOIRE),
    "additionalProperties": False,
}
_FAIT_CANDIDAT = {
    "type": "object",
    "description": (
        "Ce qu'UN outil a fait pendant le tour, lu par le core dans la réponse structurée de l'outil "
        "(jamais un texte de modèle). Forme fermée : quatre champs, aucun texte libre."
    ),
    "properties": {
        "cle": {"type": "string", "description": "Clé de dépôt stable pour un même appel d'outil (idempotence)."},
        "outil": {"type": "string", "description": "Nom de l'outil de département appelé (mN_...)."},
        "resultat": {"type": "string", "enum": ["ok", "refus"]},
        "code": {"type": ["string", "null"], "description": "Code de refus ou de verdict de l'outil, sinon null."},
    },
    "required": sorted(faits_candidats.CHAMPS_FAIT_CANDIDAT),
    "additionalProperties": False,
}
_IDENTIFIANT_ATTENDU = {
    "type": "object",
    "properties": {
        "type_evenement": {"type": "string", "enum": list(audit.types_audites())},
        "identifiant": {
            "type": "string",
            "description": (
                "wct_id (WCT), evenement_id (variance, rentabilité), lead_id (m1.lead_qualifie, "
                "m2.client_associe) ou devis_id (m3.devis_accepte, m3.devis_sans_reponse)."
            ),
        },
    },
    "required": ["type_evenement", "identifiant"],
    "additionalProperties": False,
}


_AFFAIRE_ID = {
    "type": "string",
    "description": (
        "L'affaire : le lead_id du lead, ou <lead>~opp~<wct_id> pour l'opportunité que M2 ouvre quand un client "
        "revient (lettres, chiffres et ._:-, 197 caractères au plus)."
    ),
}
_CONFIDENTIALITE = {
    "type": "string",
    "enum": sorted(regle_confidentialite.niveaux_connus()),
    "description": "Niveau de confidentialité de la décision (7 niveaux). Absent : INTERNAL.",
}
_MOTIF_HUMAIN = {
    "type": "string",
    "description": (
        f"Pourquoi, {humain.MOTIF_MIN_CARACTERES} à {humain.MOTIF_MAX_CARACTERES} caractères. Obligatoire : "
        "il est écrit avec le nom de la personne qui décide."
    ),
}


def journaliser_decision(
    decision: dict[str, Any], horodatage: str, confidentialite: str | None = None
) -> dict[str, Any]:
    """Chaîne complète : validation (raison, statut) → écriture (registre Affaires) → référence.

    N'écrit rien si la décision est refusée (raison absente, statut hors énuméré, niveau de confidentialité
    inconnu). `confidentialite` (PLAN T3.3-suite-b) marque la décision ; absent, elle se lit `INTERNAL`.
    """
    maillon, code = decisions.enregistrer_decision(decision, _REGISTRE_AFFAIRES, horodatage, confidentialite)
    if maillon is None:
        return {"etape": "validation", "accepte": False, "verdict": code}
    reference = contexte.construire_reference(maillon, "affaires", _REGISTRE_AFFAIRES)
    return {"etape": "complet", "accepte": True, "decision": maillon, "reference": reference}


def contexte_preflight(dossier: dict[str, Any], horodatage: str) -> dict[str, Any]:
    """PREFLIGHT (D-014) : vérifie qu'un dossier de contexte est suffisant.

    Si insuffisant, trace le refus au registre Affaires et rend la main — n'interrompt jamais
    l'appelant, ne bloque aucune action à sa place (le hook applicatif est un GATED futur).
    """
    trace, code = contexte.tracer_refus_contexte(dossier, _REGISTRE_AFFAIRES, horodatage)
    if trace is None and code is None:
        return {"suffisant": True, "verdict": None, "trace": None}
    return {"suffisant": False, "verdict": code, "trace": trace}


def memoriser_wct(wct_recu: dict[str, Any]) -> dict[str, Any]:
    return depuis_couple(wct.memoriser_wct(wct_recu, _REGISTRE_EVENEMENTS))


# ---------------------------------------------------------------------------
# Consommateur d'événements (ADR-0009 §3, PLAN T1.2-c) : m4.travaux_termines
# ---------------------------------------------------------------------------
# Seul producteur déclaré au catalogue socle pour ce type (src/opsys/evenements/catalogue/
# m4.travaux_termines.json : « Émis par M4... ») — constante, jamais lue depuis la charge, qui
# ne la porte pas (voir docstring de _recevoir_travaux_termines ci-dessous).
_PRODUCTEUR_TRAVAUX_TERMINES = "m04-field-ops"


class WctRefuse(ValueError):
    """m4.travaux_termines : le WCT extrait de la charge est refusé par `wct.valider_wct`
    (contrat figé `contrats.CHAMPS_WCT` — champ manquant, champ inattendu, ou 'M10' absent de
    `consommateurs_cibles`). Incohérence de données entre le catalogue du socle et le contrat
    M10, jamais un refus métier normal : le répartiteur réessaie puis met en quarantaine
    (ADR-0009 §3), visible par un humain."""


def _recevoir_travaux_termines(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme m4.travaux_termines (ADR-0009 §3, PLAN T1.2-c ; docs/architecture/DEPARTEMENTS.md
    « Événements »). Mémorise le WCT au registre Événements par la logique EXISTANTE
    (`memoriser_wct` / `wct.valider_wct` / `contrats.CHAMPS_WCT`, inchangées) : seuls les 12
    champs exacts du contrat WCT figé sont extraits de la charge, qui porte aussi `statut`
    (ajouté au catalogue par T1.1-b) et les champs optionnels réservés à M7 — hors du contrat
    M10, jamais transmis à `valider_wct` (qui rejette tout champ inattendu).

    Provenance de l'événement : le WCT EST l'événement mémorisé — `wct_id` (déjà l'un des 12
    champs du contrat, donc déjà conservé tel quel dans le maillon écrit) en est l'identifiant.
    La charge elle-même ne porte jamais `evenements_sortants.evenement_id` : cette colonne est une
    propriété du répartiteur, hors de portée du consommateur par construction
    (`repartiteur._livrer_une_paire` n'appelle `fonction` qu'avec la charge décodée — API figée,
    docs/architecture/DEPARTEMENTS.md, hors du périmètre M2/M10 de cette tâche). `producteur` est
    donc rendu ici comme la constante déclarée au catalogue socle (seul éditeur de ce type).

    Idempotent : le répartiteur n'appelle cette fonction qu'une fois par (evenement_id,
    consommateur) traité avec succès (`EVENEMENTS_RECUS` UNIQUE, ADR-0009 §3) — une relivraison
    de la même publication ne la rappelle jamais, donc jamais un second maillon pour le même WCT.
    """
    wct_extrait = {champ: charge[champ] for champ in contrats.CHAMPS_WCT}
    reponse = memoriser_wct(wct_extrait)
    if not reponse["accepte"]:
        raise WctRefuse(
            f"m4.travaux_termines : WCT {charge.get('wct_id')!r} refusé par M10 : {reponse['verdict']}"
        )
    maillon = reponse["resultat"]
    return {
        "memorise": True,
        "wct_id": maillon["wct_id"],
        "ligne_id": maillon["ligne_id"],
        "evenement_id": maillon["wct_id"],
        "producteur": _PRODUCTEUR_TRAVAUX_TERMINES,
    }


# ---------------------------------------------------------------------------
# Consommateur d'événements (ADR-0009 §3, PLAN T3.3) : m6.variance_chantier
# ---------------------------------------------------------------------------
# Seul producteur déclaré au catalogue socle pour ce type (src/opsys/evenements/catalogue/
# m6.variance_chantier.json : « Émis par M6... »).
_PRODUCTEUR_VARIANCE_CHANTIER = "m06-material-control"


def _recevoir_variance_chantier(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme m6.variance_chantier (ADR-0009 §3, PLAN T3.3 ; catalogue socle stable, neuf champs
    tous requis). Mémorise la charge TELLE QUELLE au registre Événements (`variance.py`, même
    registre et même `type_entree` que le WCT — `classification.py` distingue les deux à la
    lecture). Contrairement au WCT, aucun contrat M10 séparé ne restreint les champs acceptés :
    le catalogue socle (`additionalProperties: false`) est la seule source de vérité pour ce type,
    donc aucun chemin de refus ici (à la différence de `WctRefuse` ci-dessus).

    Idempotent : le répartiteur n'appelle cette fonction qu'une fois par (evenement_id,
    consommateur) traité avec succès (`EVENEMENTS_RECUS` UNIQUE, ADR-0009 §3) ; M6 peut en outre
    republier un `evenement_id` DISTINCT pour le même `wct_id` si `statut_variance` change (ex.
    `declaration_absente` → `evaluee`) — chaque publication distincte est alors un NOUVEAU
    maillon, représentant fidèlement l'état qui a évolué, jamais un doublon du même fait.
    """
    maillon, _ = variance.memoriser_variance(dict(charge), _REGISTRE_EVENEMENTS)
    return {
        "memorise": True,
        "evenement_id": maillon["evenement_id"],
        "wct_id": maillon["wct_id"],
        "ligne_id": maillon["ligne_id"],
        "producteur": _PRODUCTEUR_VARIANCE_CHANTIER,
    }


# ---------------------------------------------------------------------------
# Consommateur d'événements (ADR-0009 §3, PLAN T1.5-d) : m5.rentabilite_chantier
# ---------------------------------------------------------------------------
# Seul producteur déclaré au catalogue socle pour ce type (src/opsys/evenements/catalogue/
# m5.rentabilite_chantier.json : « Émis par M5... »).
_PRODUCTEUR_RENTABILITE_CHANTIER = "m05-financecore"


def _recevoir_rentabilite_chantier(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme m5.rentabilite_chantier (ADR-0009 §3, PLAN T1.5-d ; catalogue socle, schéma fermé, seize
    champs tous requis). Mémorise la charge TELLE QUELLE au registre Événements (`rentabilite.py`, même registre
    et même `type_entree` que le WCT et la variance — `classification.py` distingue les trois à la lecture),
    marquée `FINANCIAL` : c'est la leçon de l'affaire (l'écart entre la marge prévue et la marge réelle), lisible
    ici et chez M5, jamais rendue dans un paquet de contexte. Aucun montant n'est recalculé, aucune marge n'est
    déduite : un coût partiel n'en porte pas, et M10 n'en ajoute pas.

    Idempotent : le répartiteur n'appelle cette fonction qu'une fois par (evenement_id, consommateur) traité avec
    succès (`EVENEMENTS_RECUS` UNIQUE, ADR-0009 §3) ; M5 publie un `evenement_id` DISTINCT à chaque nouvelle
    version de ses entrées — chaque publication est un NOUVEAU maillon, qui représente fidèlement l'état qui a
    évolué (le plus grand `sequence` est le dernier), jamais un doublon du même fait.
    """
    maillon, _ = rentabilite.memoriser_rentabilite(dict(charge), _REGISTRE_EVENEMENTS)
    return {
        "memorise": True,
        "evenement_id": maillon["evenement_id"],
        "wct_id": maillon["wct_id"],
        "ligne_id": maillon["ligne_id"],
        "producteur": _PRODUCTEUR_RENTABILITE_CHANTIER,
    }


# ---------------------------------------------------------------------------
# Consommateurs d'événements (ADR-0009 §3, PLAN T4.18) : l'amont d'une affaire
# ---------------------------------------------------------------------------
class AmontRefuse(ValueError):
    """Un fait de l'amont est refusé par `amont.memoriser` : champ absent, hors de sa forme fermée, instant sans
    fuseau. Incohérence entre le catalogue du socle et ce que M10 accepte de garder, jamais un refus métier normal :
    le répartiteur réessaie puis met en quarantaine (ADR-0009 §3), visible par un humain. Le message nomme le CHAMP,
    jamais sa valeur (elle pourrait être une donnée personnelle)."""


def _consommateur_amont(type_evenement: str) -> Callable[[dict], dict]:
    """Le consommateur d'un type de l'amont, tiré de la table de `etapes.py`. Mémorise par la clé du fait
    (`amont.memoriser`) : idempotent, sans ordre imposé, sans affaire inventée. Le résultat, gardé par le répartiteur
    au reçu de l'événement, dit si le fait était déjà là (`deja_memorise`), s'il portait les mêmes faits
    (`identique`) et si l'origine de l'affaire (`m1.lead_qualifie`) est connue (`origine_recue`, `verdict`)."""
    producteur = etapes.etape(type_evenement).producteur

    def recevoir(charge: dict[str, Any]) -> dict[str, Any]:
        resultat, verdict = amont.memoriser(type_evenement, dict(charge), _REGISTRE_EVENEMENTS)
        if resultat is None:
            raise AmontRefuse(f"{type_evenement} : fait refusé par M10 : {verdict['code']} ({verdict['detail']})")
        maillon = resultat["maillon"]
        return {
            "memorise": True,
            "type_evenement": type_evenement,
            "identifiant": classification.identifiant(maillon),
            "lead_id": maillon["lead_id"],
            "ligne_id": maillon["ligne_id"],
            "producteur": producteur,
            "deja_memorise": resultat["deja_memorise"],
            "identique": resultat["identique"],
            "origine_recue": resultat["affaire"]["origine_recue"],
            "verdict": resultat["affaire"]["verdict"],
        }

    recevoir.__name__ = "recevoir_" + type_evenement.replace(".", "_")
    return recevoir


def consommateurs() -> dict[str, Callable[[dict], dict]]:
    """Types d'événements consommés par M10 (ADR-0009 §3) — voir `department.yaml/evenements`."""
    return {
        "m4.travaux_termines": _recevoir_travaux_termines,
        "m6.variance_chantier": _recevoir_variance_chantier,
        "m5.rentabilite_chantier": _recevoir_rentabilite_chantier,
        **{type_evenement: _consommateur_amont(type_evenement) for type_evenement in etapes.types_consommes()},
    }


def signaler_revision(ligne_id_a: str, ligne_id_b: str, horodatage: str) -> dict[str, Any]:
    return depuis_couple(
        revision.signaler_revision(_REGISTRE_AFFAIRES, ligne_id_a, ligne_id_b, horodatage)
    )


def arbitrer_revision(revision_ligne_id: str, statut: str, horodatage: str) -> dict[str, Any]:
    acteur, refus = _acteur_humain("m10_arbitrer_revision")
    if acteur is None:
        return refus or _verdict(humain.REJ_HUMAIN_REQUIS, "acteur humain introuvable")
    return depuis_couple(
        revision.arbitrer_revision(
            _REGISTRE_AFFAIRES, revision_ligne_id, statut, _horodatage_faisant_foi(horodatage), acteur=acteur
        )
    )


def statut_decision(decision_id: str) -> dict[str, Any]:
    """Statut courant, TOUJOURS calculé par relecture de la chaîne (jamais un champ positionnable)."""
    refus = _refus_lecture_admin()
    if refus is not None:
        return refus
    return {"statut": decisions.statut_courant(_REGISTRE_AFFAIRES, decision_id)}


def statut_revision(revision_ligne_id: str) -> dict[str, Any]:
    refus = _refus_lecture_admin()
    if refus is not None:
        return refus
    return {"statut": revision.statut_revision(_REGISTRE_AFFAIRES, revision_ligne_id)}


def verifier_reference(reference: dict[str, Any]) -> dict[str, Any]:
    """Vérifie une ReferenceMemoireM10 contre le registre qu'elle nomme (evenements ou affaires)."""
    nom_registre = reference.get("registre") if isinstance(reference, dict) else None
    registre_cible = _REGISTRES_NOMMES.get(nom_registre)
    if registre_cible is None:
        return {"accepte": False, "verdict": "REJ-REFERENCE-REGISTRE-INCONNU-DE-L-OUTIL"}
    return depuis_couple(contexte.verifier_reference(reference, registre_cible))


def paquet_contexte_affaire(affaire_id: str, horodatage: str) -> dict[str, Any]:
    """Paquet de contexte en 4 couches ordonnées pour une affaire (PLAN T3.3, `paquets.py`) : budget
    de caractères fixé par le code (non exposé à l'appelant — P11, économie de tokens).

    Le destinataire est fixé par le répartiteur dans le contexte d'appel OPSYS. En dehors de ce contexte,
    le filtre prend la vue la plus restrictive."""
    return paquets.assembler_paquet_contexte(
        affaire_id, horodatage, _REGISTRE_EVENEMENTS, _REGISTRE_AFFAIRES,
        agent=contexte_appel.departement_origine_appelante(),
    )


def lire_paquet_affaire_appareil(affaire_id: str, horodatage: str) -> dict[str, Any]:
    """Lecture admin distincte du contexte privé Core : filtre restrictif et sortie sans artefact."""
    if contexte_appel.identite_appelante() is None:
        return _verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE", "cette lecture exige une personne admin active confirmée en base"
        )
    refus = _refus_lecture_admin()
    if refus is not None:
        return refus
    paquet = paquets.assembler_paquet_contexte(
        affaire_id, horodatage, _REGISTRE_EVENEMENTS, _REGISTRE_AFFAIRES, agent=None,
    )
    # Capacites mesure l'enveloppe entière. Le budget des faits du Core reste inchangé.
    taille = len(json.dumps({"ok": True, "resultat": paquet}, ensure_ascii=False))
    if taille > jetons.LIMITE_SORTIE_DEFAUT - 100:
        return _verdict(
            "REJ-PAQUET-AFFAIRE-SORTIE-TROP-VOLUMINEUSE",
            "le paquet dépasse la borne de lecture appareil ; aucun détail partiel n'est transmis",
        )
    return paquet


def rechercher_affaire_appareil(
    affaire_id: str, requete: str = "", limite: int = 8, decalage: int = 0
) -> dict[str, Any]:
    """Recherche métier restrictive, identité admin actuelle avant les deux snapshots."""
    if contexte_appel.identite_appelante() is None:
        return _verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE", "cette lecture exige une personne admin active confirmée en base"
        )
    refus = _refus_lecture_admin()
    if refus is not None:
        return refus
    return recherche_affaire.rechercher(
        affaire_id, requete, limite, decalage, _REGISTRE_EVENEMENTS, _REGISTRE_AFFAIRES
    )


def consolider_affaire(affaire_id: str, jour: str, horodatage: str) -> dict[str, Any]:
    """Consolidation nocturne d'une affaire (PLAN T3.3, `consolidation.py`) : idempotente tant que
    l'ensemble des sources du jour n'a pas changé; reprend les événements arrivés tard."""
    return consolidation.consolider_affaire(affaire_id, jour, horodatage, _REGISTRE_EVENEMENTS, _REGISTRE_AFFAIRES)


def deposer_faits_candidats(
    affaire_id: str, departement: str, faits: list[dict[str, Any]], horodatage: str
) -> dict[str, Any]:
    """Dépôt POSTFLIGHT (PLAN T3.3-suite, `faits_candidats.py`) : ce que les outils ont fait pendant un tour
    d'agent, en statut `candidat` au registre Affaires. Idempotent par clé de dépôt ; un lot invalide est refusé
    en entier (verdict nommé, rien d'écrit). Jamais une vérité : hors du paquet de contexte."""
    return depuis_couple(
        faits_candidats.deposer_faits_candidats(affaire_id, departement, faits, horodatage, _REGISTRE_AFFAIRES)
    )


def auditer_non_oubli(identifiants_attendus: list[dict[str, str]]) -> dict[str, Any]:
    """Audit « non-oubli » (PLAN T3.3, `audit.py`) : intégrité des deux chaînes + liste compacte des
    faits attendus sans trace au registre Événements."""
    return audit.auditer_non_oubli(identifiants_attendus, _REGISTRE_EVENEMENTS, _REGISTRE_AFFAIRES)


# ---------------------------------------------------------------------------
# Écritures HUMAINES (PLAN T3.3-suite-b) : qui décide ?
# ---------------------------------------------------------------------------
_DEPARTEMENT = "m10-memoire"


def _verdict(code: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "verdict": validation.construire_verdict(code, detail)}


def _refus_lecture_admin() -> dict[str, Any] | None:
    """Préserve la lecture interne ; confirme l'admin d'appareil avant tout registre."""
    appelante = contexte_appel.identite_appelante()
    if appelante is None:
        return None
    cnx = stockage.connexion_courante()
    confirmee = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
    if confirmee is None or confirmee.role != humain.ROLE_ADMIN:
        return _verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE", "cette lecture exige une personne admin active confirmée en base"
        )
    return None


def _acteur_humain(nom_outil: str) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """Qui décide : `({par, role, source}, None)` si c'est un humain identifié, sinon `(None, réponse de refus)`.

    Deux voies, jamais une troisième, et jamais un texte de modèle ni un argument :
    1. un appel d'appareil dont l'identité (posée par le core d'après un jeton vérifié, `_meta`) est
       CONFIRMÉE en base à l'instant même (personne active portant encore ce rôle), de rôle `admin` ;
    2. l'exécution d'une demande qu'un humain vient d'approuver dans la file d'approbation : le SOCLE dit qui l'a
       approuvée (`approbations.approbateur_en_cours`, PLAN T4.15-d ; demande relue en base, personne active portant
       encore son rôle), et l'outil ne reconnaît que `admin` et `nathan_owner` (`humain.roles_humains()`), même si la
       politique du département s'élargit. Les arguments ne sont pas comparés : `decider` rejoue les arguments EXACTS
       enregistrés et lui seul pose la demande en cours.
    Tout le reste est refusé : un appel d'agent qui n'a pas passé par l'approbation (un département en mode
    `supervise` ou `autonome` exécute un N3 sans file), un appel en ligne de commande, un appel hors
    transaction où rien n'est vérifiable. Ne lit JAMAIS les arguments comme identité."""
    cnx = stockage.connexion_courante()
    appelante = contexte_appel.identite_appelante()
    if appelante is not None:
        confirmee = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
        if confirmee is None:
            return None, _verdict(
                humain.REJ_HUMAIN_IDENTITE_INVALIDE,
                f"personne {appelante.personne!r} inconnue, inactive, ou ne porte plus le rôle "
                f"{appelante.role!r} du jeton d'appareil (ou identité non vérifiable hors transaction)",
            )
        if confirmee.role != humain.ROLE_ADMIN:
            return None, _verdict(
                humain.REJ_HUMAIN_ROLE_INSUFFISANT, "cette écriture est réservée au rôle admin depuis un appareil"
            )
        return {"par": confirmee.personne, "role": confirmee.role, "source": humain.SOURCE_APPAREIL}, None
    approbateur = approbations.approbateur_en_cours(cnx, nom_outil, _DEPARTEMENT, roles=humain.roles_humains())
    if approbateur is not None:
        return {"par": approbateur.personne, "role": approbateur.role, "source": humain.SOURCE_APPROBATION}, None
    return None, _verdict(
        humain.REJ_HUMAIN_REQUIS,
        "cette écriture est une décision humaine : un agent ne peut pas la faire seul. Fais-la depuis l'app "
        "admin (jeton d'appareil), ou propose-la et attends qu'un humain approuve la demande dans la console "
        "OPSYS (rôle admin ou propriétaire). Ne la présente pas comme faite.",
    )


def _horodatage_faisant_foi(horodatage: str) -> str:
    """Pendant un appel d'appareil idempotent, l'heure de RÉCEPTION du serveur fait foi, jamais l'horloge de
    l'appareil ni l'`horodatage` fourni (même patron que `m4_pointer`, T1.4-d)."""
    reception = contexte_appel.horodatage_reception()
    return reception.recu_le.isoformat() if reception is not None else horodatage


def _traiter_signal(action: str, nom_outil: str, signal_id: str, motif: str, horodatage: str) -> dict[str, Any]:
    acteur, refus = _acteur_humain(nom_outil)
    if acteur is None:
        return refus or _verdict(humain.REJ_HUMAIN_REQUIS, "acteur humain introuvable")
    return depuis_couple(
        signaux.traiter_signal(
            action,
            signal_id,
            acteur["par"],
            acteur["role"],
            acteur["source"],
            motif,
            _horodatage_faisant_foi(horodatage),
            _REGISTRE_EVENEMENTS,
            _REGISTRE_AFFAIRES,
        )
    )


def prendre_en_compte_signal(signal_id: str, motif: str, horodatage: str) -> dict[str, Any]:
    """Un HUMAIN prend connaissance d'un signal critique (`ouvert` -> `pris_en_compte`), avec son motif."""
    return _traiter_signal(
        signaux.ACTION_PRISE_EN_COMPTE, "m10_prendre_en_compte_signal", signal_id, motif, horodatage
    )


def clore_signal(signal_id: str, motif: str, horodatage: str) -> dict[str, Any]:
    """Un HUMAIN clôt un signal critique pris en compte (`pris_en_compte` -> `clos`), avec son motif."""
    return _traiter_signal(signaux.ACTION_CLOTURE, "m10_clore_signal", signal_id, motif, horodatage)


def lister_signaux(affaire_id: str | None = None) -> dict[str, Any]:
    """Les signaux critiques (d'une affaire, ou de toutes), ouverts d'abord (PLAN T3.3-suite-b)."""
    refus = _refus_lecture_admin()
    if refus is not None:
        return refus
    return signaux.lister(affaire_id, _REGISTRE_EVENEMENTS.lire(), _REGISTRE_AFFAIRES.lire())


def lire_revision(revision_ligne_id: str) -> dict[str, Any]:
    """Dossier métier complet : deux faits exacts, jamais un fragment de comparaison."""
    refus = _refus_lecture_admin()
    if refus is not None:
        return refus
    snapshot = registre.Registre(maillons=_REGISTRE_AFFAIRES.lire())
    return depuis_couple(dossier_revision.lire_revision(snapshot, revision_ligne_id))


def lister_references(limite: int = 8, decalage: int = 0) -> dict[str, Any]:
    """Catalogue métier : une copie des Affaires après confirmation de l'admin d'appareil."""
    refus = _refus_lecture_admin()
    if refus is not None:
        return refus
    if type(limite) is not int or not 1 <= limite <= 8 or type(decalage) is not int or decalage < 0:
        return _verdict(
            "REJ-CATALOGUE-PAGINATION-INVALIDE", "limite entière de 1 à 8 et décalage entier positif ou nul"
        )
    snapshot = registre.Registre(maillons=_REGISTRE_AFFAIRES.lire())
    return depuis_couple(catalogue_references.lister_references(snapshot, limite, decalage))


def lier_session_affaire(cle_session: str, affaire_id: str, motif: str, horodatage: str) -> dict[str, Any]:
    """Un HUMAIN lie une session (clé composée par le core) à une affaire : ce que le moteur de contexte lira
    à la place du texte de la demande (PLAN T3.3-suite-b, `liaison.py`)."""
    acteur, refus = _acteur_humain("m10_lier_session_affaire")
    if acteur is None:
        return refus or _verdict(humain.REJ_HUMAIN_REQUIS, "acteur humain introuvable")
    return depuis_couple(
        liaison.lier_session_affaire(
            cle_session,
            affaire_id,
            acteur["par"],
            acteur["role"],
            acteur["source"],
            motif,
            _horodatage_faisant_foi(horodatage),
            _REGISTRE_AFFAIRES,
        )
    )


def affaire_de_la_session(cle_session: str) -> dict[str, Any]:
    """L'affaire liée à cette session, ou `{"lie": false}` : jamais une affaire par défaut (lecture)."""
    return liaison.affaire_de_la_session(cle_session, _REGISTRE_AFFAIRES)


@dataclass(frozen=True)
class _InvocationDocumentaire:
    cnx: Connection
    meta: idempotence.Meta
    quota: int
    mode_manifeste: str


_INVOCATION_DOCUMENTAIRE: ContextVar[_InvocationDocumentaire | None] = ContextVar(
    "m10_invocation_documentaire_appareil",
    default=None,
)


def _verifier_invocation_documentaire(invocation):
    try:
        if (
            type(invocation) is not _InvocationDocumentaire
            or not isinstance(invocation.cnx, Connection)
            or invocation.cnx is not stockage.connexion_courante()
            or invocation.cnx.closed
            or not invocation.cnx.in_transaction()
            or invocation.cnx.get_nested_transaction() is None
            or type(invocation.meta) is not idempotence.Meta
            or type(invocation.quota) is not int
            or invocation.quota < 40
            or type(invocation.mode_manifeste) is not str
            or invocation.mode_manifeste not in ("ombre", "supervise", "autonome")
        ):
            raise RuntimeError("CONFIRMATION-INCONNUE")
        for valeur in (invocation.meta.appareil, invocation.meta.cle):
            if type(valeur) is not str or not valeur.strip() or len(valeur) > 128:
                raise RuntimeError("CONFIRMATION-INCONNUE")
            valeur.encode("utf-8", "strict")
        hora = invocation.meta.horodatage_appareil
        if type(hora) is not str or len(hora) > 40 or not humain.horodatage_valide(hora):
            raise RuntimeError("CONFIRMATION-INCONNUE")
        hora.encode("utf-8", "strict")
    except Exception:
        raise RuntimeError("CONFIRMATION-INCONNUE") from None


@contextmanager
def invocation_documentaire_appareil(cnx, *, meta, quota, mode_manifeste):
    """Liaison privée du caller nommé ; ni autorité SQL ni permission DEVICE fabriquée."""
    if _INVOCATION_DOCUMENTAIRE.get() is not None:
        raise RuntimeError("CONFIRMATION-INCONNUE") from None
    invocation = _InvocationDocumentaire(cnx, meta, quota, mode_manifeste)
    _verifier_invocation_documentaire(invocation)
    token = _INVOCATION_DOCUMENTAIRE.set(invocation)
    try:
        yield
    finally:
        _INVOCATION_DOCUMENTAIRE.reset(token)


def _executer_documentaire_appareil(operation, arguments):
    invocation = _INVOCATION_DOCUMENTAIRE.get()
    if invocation is None:
        raise RuntimeError("CONFIRMATION-INCONNUE") from None
    _verifier_invocation_documentaire(invocation)
    try:
        commande = documents_affaire.valider_commande(operation, arguments)
    except Exception:
        raise RuntimeError("CONFIRMATION-INCONNUE") from None
    # Import seulement après la liaison et l'admission pure, aucun fallback générique.
    from opsys.documents_affaire_transactions import muter_document_m10

    return muter_document_m10(
        invocation.cnx,
        operation,
        commande,
        meta=invocation.meta,
        quota=invocation.quota,
        mode_manifeste=invocation.mode_manifeste,
    )


def deposer_version_document_appareil(
    affaire_id,
    document_ref,
    version_precedente,
    titre,
    corps,
    confidentialite,
):
    return _executer_documentaire_appareil(
        "deposer",
        {
            "affaire_id": affaire_id,
            "document_ref": document_ref,
            "version_precedente": version_precedente,
            "titre": titre,
            "corps": corps,
            "confidentialite": confidentialite,
        },
    )


def activer_version_document_appareil(
    affaire_id,
    document_ref,
    version_source,
    activation_attendue,
):
    return _executer_documentaire_appareil(
        "activer",
        {
            "affaire_id": affaire_id,
            "document_ref": document_ref,
            "version_source": version_source,
            "activation_attendue": activation_attendue,
        },
    )


def retirer_document_appareil(affaire_id, document_ref, activation_attendue, code_motif):
    return _executer_documentaire_appareil(
        "retirer",
        {
            "affaire_id": affaire_id,
            "document_ref": document_ref,
            "activation_attendue": activation_attendue,
            "code_motif": code_motif,
        },
    )


_REFERENCE_DOCUMENTAIRE = {
    "type": "object",
    "properties": {
        "registre": {"type": "string", "enum": ["documents_affaire"]},
        "index": {"type": "integer", "minimum": 0, "maximum": 511},
        "ligne_id": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
    "required": ["registre", "index", "ligne_id"],
    "additionalProperties": False,
}
_REFERENCE_DOCUMENTAIRE_NULLABLE = {**_REFERENCE_DOCUMENTAIRE, "type": ["object", "null"]}


def outils() -> tuple[Outil, ...]:
    """Capacités exposées aux agents (fonction : les constantes publiques du paquet sont des énumérés)."""
    return (
        Outil(
            nom="m10_journaliser_decision",
            description=(
                "Enregistre une décision motivée de bout en bout : validation (raison "
                "obligatoire, statut dans l'énuméré fermé) → écriture au registre Affaires → "
                "référence vérifiable. Refuse une décision sans raison non vide."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "decision": _DECISION,
                    "horodatage": {"type": "string"},
                    "confidentialite": _CONFIDENTIALITE,
                },
                "required": ["decision", "horodatage"],
                "additionalProperties": False,
            },
            fonction=journaliser_decision,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m10_contexte_preflight",
            description=(
                "PREFLIGHT : vérifie qu'un dossier de contexte (5 champs EvenementMemoire + au "
                "moins une référence de décision) est suffisant ; sinon trace le refus au "
                "registre et rend la main, sans jamais interrompre l'appelant."
            ),
            parametres={
                "type": "object",
                "properties": {"dossier": _DOSSIER_CONTEXTE, "horodatage": {"type": "string"}},
                "required": ["dossier", "horodatage"],
                "additionalProperties": False,
            },
            fonction=contexte_preflight,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m10_memoriser_wct",
            description=(
                "Consomme un Work Completion Trigger de M4 (12 champs exacts, 'M10' requis "
                "dans consommateurs_cibles) et le mémorise comme événement au registre "
                "Événements — le hash_maillon de M4 n'est jamais recalculé."
            ),
            parametres={
                "type": "object",
                "properties": {"wct_recu": _WCT},
                "required": ["wct_recu"],
                "additionalProperties": False,
            },
            fonction=memoriser_wct,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m10_signaler_revision",
            description=(
                "Signale une révision entre deux maillons EXISTANTS du registre Affaires (deux "
                "souvenirs qui se ressemblent, ou un fait devenu obsolète) — jamais une fusion."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "ligne_id_a": {"type": "string"},
                    "ligne_id_b": {"type": "string"},
                    "horodatage": {"type": "string"},
                },
                "required": ["ligne_id_a", "ligne_id_b", "horodatage"],
                "additionalProperties": False,
            },
            fonction=signaler_revision,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m10_arbitrer_revision",
            description=(
                "Consigne l'arbitrage humain d'une révision SIGNALÉE (jamais une fusion ni une "
                "mutation) ; refuse un statut hors énuméré ou une révision qui n'a jamais été "
                "signalée."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "revision_ligne_id": {"type": "string"},
                    "statut": {"type": "string", "enum": list(contrats.STATUT_REVISION)},
                    "horodatage": {"type": "string"},
                },
                "required": ["revision_ligne_id", "statut", "horodatage"],
                "additionalProperties": False,
            },
            fonction=arbitrer_revision,
            autonomie=Autonomie.T1,
            # §7 M10 mobile (admin : contradictions) ; arbitrage humain.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m10_statut_decision",
            description=(
                "Statut courant d'une décision, calculé par relecture du registre Affaires "
                "(jamais un champ positionnable)."
            ),
            parametres={
                "type": "object",
                "properties": {"decision_id": {"type": "string"}},
                "required": ["decision_id"],
                "additionalProperties": False,
            },
            fonction=statut_decision,
            # §7 M10 mobile (admin : décisions à valider).
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m10_statut_revision",
            description="Statut d'une révision (dernier arbitrage connu, ou 'en_attente' si seulement signalée).",
            parametres={
                "type": "object",
                "properties": {"revision_ligne_id": {"type": "string"}},
                "required": ["revision_ligne_id"],
                "additionalProperties": False,
            },
            fonction=statut_revision,
            # §7 M10 mobile (admin : contradictions).
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m10_verifier_reference",
            description=(
                "Vérifie qu'une ReferenceMemoireM10 désigne un maillon réellement écrit sur une "
                "chaîne intacte (registre, ligne_id et hash_tete cohérents) — détecte une "
                "référence forgée."
            ),
            parametres={
                "type": "object",
                "properties": {"reference": _REFERENCE_MEMOIRE},
                "required": ["reference"],
                "additionalProperties": False,
            },
            fonction=verifier_reference,
        ),
        Outil(
            nom="m10_paquet_contexte_affaire",
            description=(
                "Paquet de contexte en 4 couches ORDONNÉES pour une affaire (lead/chantier) : "
                "règles de l'entreprise → faits durables de l'affaire → événements récents (lead qualifié, "
                "client associé, devis accepté, devis sans réponse, travaux terminés, avec leur heure et leur "
                "provenance) → signaux critiques (ouverts d'abord, puis les derniers clos avec qui et pourquoi). "
                "Budget de caractères et troncature calculés par le code ; une couche vide est "
                "déclarée vide, jamais absente en silence ; les éléments CLIENT_PRIVATE ne sortent "
                "que vers les agents qui en ont besoin, et sont comptés quand ils sont retenus. Hors des couches, "
                "deux blocs : `affaire` (affaire connue ou inconnue, étape qui l'a ouverte reçue ou non, verdict : "
                "une affaire inconnue n'est jamais rendue comme un paquet vide) et `consolidation` (les jours dont "
                "l'historique a été omis par le budget et qu'aucun fait durable ne résume, chacun avec l'affaire : "
                "les arguments de m10_consolider_affaire)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "affaire_id": _AFFAIRE_ID,
                    "horodatage": {"type": "string"},
                },
                "required": ["affaire_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=paquet_contexte_affaire,
            # §7 M10 mobile (admin : recherche dans la mémoire).
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m10_lire_paquet_affaire_appareil",
            description=(
                "Lecture admin du dossier d'une affaire : quatre couches ordonnées, provenance, "
                "omissions et jours restant à consolider. Vue restrictive PUBLIC_INTERNAL/INTERNAL ; "
                "aucune consolidation ni écriture. Identité appareil admin actuelle obligatoire."
            ),
            parametres={
                "type": "object",
                "properties": {"affaire_id": _AFFAIRE_ID, "horodatage": {"type": "string"}},
                "required": ["affaire_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=lire_paquet_affaire_appareil,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m10_rechercher_affaire_appareil",
            description=(
                "Recherche littérale NFC/casefold dans les identifiants, sources et résumés métier "
                "visibles d'une affaire : événements et dernières consolidations avec provenance. "
                "Page courante bornée ; aucune écriture ni recherche documentaire. Admin appareil actif requis."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "affaire_id": _AFFAIRE_ID,
                    "requete": {"type": "string", "maxLength": 200},
                    "limite": {"type": "integer", "minimum": 1, "maximum": 8},
                    "decalage": {"type": "integer", "minimum": 0, "maximum": 10000},
                },
                "required": ["affaire_id", "requete", "limite", "decalage"],
                "additionalProperties": False,
            },
            fonction=rechercher_affaire_appareil,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m10_consolider_affaire",
            description=(
                "Consolidation nocturne : condense les événements d'une affaire pour un jour "
                "donné en UN fait durable au registre Affaires, sans perdre la trace vers ses "
                "sources. Idempotente : rejouer le même (affaire_id, jour) ne crée rien de plus."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "affaire_id": _AFFAIRE_ID,
                    "jour": {"type": "string", "description": "AAAA-MM-JJ, jour consolidé."},
                    "horodatage": {"type": "string"},
                },
                "required": ["affaire_id", "jour", "horodatage"],
                "additionalProperties": False,
            },
            fonction=consolider_affaire,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m10_deposer_faits_candidats",
            description=(
                "POSTFLIGHT du moteur de contexte du core : dépose, en statut candidat au registre "
                "Affaires, ce que des outils de département ont fait pendant un tour d'agent (outil, "
                "résultat ok ou refus, code), avec l'affaire et le département source. Jamais une "
                "vérité : hors du paquet de contexte, pas encore consolidé. Idempotent par clé ; un "
                "lot invalide est refusé en entier."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "affaire_id": _AFFAIRE_ID,
                    "departement": {"type": "string", "description": "Département source, ex. m03-estimation."},
                    "faits": {"type": "array", "items": _FAIT_CANDIDAT},
                    "horodatage": {"type": "string"},
                },
                "required": ["affaire_id", "departement", "faits", "horodatage"],
                "additionalProperties": False,
            },
            fonction=deposer_faits_candidats,
            autonomie=Autonomie.T1,
            # T1 (écriture interne : registre Affaires) mais N2 « tâche interne » (ADR-0009 §4,
            # automatique) et non le défaut T1 -> N3 : le core l'appelle après chaque tour d'un agent
            # de département, sans humain ; en N3 le mode ombre de M10 mettrait chaque tour en attente
            # d'approbation. Le dépôt ne décide rien et n'engage personne : append-only, statut
            # candidat, absent du paquet de contexte et de la consolidation. Même choix que
            # `m4_deposer_fichier`. Aucun rôle d'appareil : réservé au core (jeton du moteur).
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m10_lister_signaux",
            description=(
                "Liste les signaux critiques (variances matériaux au-dessus du seuil) d'une affaire, ou "
                "de toutes, avec leur état (ouvert, pris_en_compte, clos), qui les a traités et pourquoi. "
                "Ouverts d'abord ; ce qui dépasse la limite est dit (nb_omis)."
            ),
            parametres={
                "type": "object",
                "properties": {"affaire_id": {"type": "string", "description": "lead_id ; absent : toutes."}},
                "additionalProperties": False,
            },
            fonction=lister_signaux,
            # §7 M10 mobile (admin : alertes critiques, contradictions) ; lecture.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m10_lire_revision",
            description=(
                "Lit les deux faits métier exacts d'une révision signalée et son dernier statut, "
                "avec leurs références vérifiables. Refuse tout le dossier si une pièce est retenue, "
                "non comparable, non JSON ou si la sortie complète dépasse le budget."
            ),
            parametres={
                "type": "object",
                "properties": {"revision_ligne_id": {"type": "string"}},
                "required": ["revision_ligne_id"],
                "additionalProperties": False,
            },
            fonction=lire_revision,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m10_lister_references",
            description=(
                "Catalogue métier paginé des décisions et révisions visibles du registre Affaires : "
                "statuts courants et références vérifiables, sans textes libres ni tête privée. "
                "La mémoire de développement n'est pas consultée."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "limite": {"type": "integer", "minimum": 1, "maximum": 8, "default": 8},
                    "decalage": {"type": "integer", "minimum": 0, "default": 0},
                },
                "additionalProperties": False,
            },
            fonction=lister_references,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m10_prendre_en_compte_signal",
            description=(
                "DÉCISION HUMAINE : prend connaissance d'un signal critique ouvert (ouvert -> "
                "pris_en_compte), avec le motif, au nom de la personne authentifiée. Un agent ne peut pas "
                "la faire seul : depuis l'app admin, ou en attente d'approbation dans la console. Un signal "
                "ouvert bloque les actions N3 ou plus de l'affaire dans le moteur de contexte."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "signal_id": {"type": "string", "description": "evenement_id du signal (m10_lister_signaux)."},
                    "motif": _MOTIF_HUMAIN,
                    "horodatage": {"type": "string"},
                },
                "required": ["signal_id", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=prendre_en_compte_signal,
            autonomie=Autonomie.T1,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m10_clore_signal",
            description=(
                "DÉCISION HUMAINE : clôt un signal critique déjà pris en compte (pris_en_compte -> clos), "
                "avec le motif, au nom de la personne authentifiée. Définitif : un signal clos ne se "
                "rouvre pas. Un agent ne peut pas la faire seul : depuis l'app admin, ou en attente "
                "d'approbation dans la console."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "signal_id": {"type": "string", "description": "evenement_id du signal (m10_lister_signaux)."},
                    "motif": _MOTIF_HUMAIN,
                    "horodatage": {"type": "string"},
                },
                "required": ["signal_id", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=clore_signal,
            autonomie=Autonomie.T1,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m10_lier_session_affaire",
            description=(
                "DÉCISION HUMAINE : lie une session (clé composée par le core, "
                "agent:<agent>:<canal>:direct:<pair>) à une affaire (lead_id). Le moteur de contexte lira "
                "cette affaire à la place du texte de la demande, qu'un client peut écrire. Un agent ne "
                "peut pas la faire seul : depuis l'app admin, ou en attente d'approbation dans la console."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "cle_session": {"type": "string", "description": "Clé de session, telle que le core la compose."},
                    "affaire_id": _AFFAIRE_ID,
                    "motif": _MOTIF_HUMAIN,
                    "horodatage": {"type": "string"},
                },
                "required": ["cle_session", "affaire_id", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=lier_session_affaire,
            autonomie=Autonomie.T1,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m10_affaire_de_la_session",
            description=(
                "Lecture : l'affaire liée à une session par un humain (m10_lier_session_affaire), ou "
                "lie=false. Jamais une affaire par défaut. Appelée par le moteur de contexte du core."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "cle_session": {"type": "string", "description": "Clé de session, telle que le core la compose."}
                },
                "required": ["cle_session"],
                "additionalProperties": False,
            },
            fonction=affaire_de_la_session,
        ),
        Outil(
            nom="m10_auditer_non_oubli",
            description=(
                "Audit « non-oubli » : intégrité des deux chaînes (registre.valider_chaine) et, "
                "pour chaque fait ATTENDU fourni (WCT, variance, rentabilité, ou fait de l'amont : lead qualifié, "
                "client associé, devis accepté, devis sans réponse), vérifie sa trace au registre "
                "Événements. Rend une liste compacte des oublis, jamais une valeur par défaut."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "identifiants_attendus": {"type": "array", "items": _IDENTIFIANT_ATTENDU},
                },
                "required": ["identifiants_attendus"],
                "additionalProperties": False,
            },
            fonction=auditer_non_oubli,
        ),
        Outil(
            nom="m10_deposer_version_document_appareil",
            description=(
                "Dépôt documentaire interne par l'admin appareil : texte exact INTERNAL, nouvelle version, "
                "sans activation implicite. Le rôle SQL, le mode ombre, l'affaire et la preuve propre sont "
                'vérifiés dans la transaction nommée.'
            ),
            parametres={
                "type": "object",
                "properties": {
                    "affaire_id": _AFFAIRE_ID,
                    "document_ref": _REFERENCE_DOCUMENTAIRE_NULLABLE,
                    "version_precedente": _REFERENCE_DOCUMENTAIRE_NULLABLE,
                    "titre": {"type": "string", "minLength": 1, "maxLength": 120},
                    "corps": {"type": "string", "minLength": 1, "maxLength": 2000},
                    "confidentialite": {"type": "string", "enum": ["INTERNAL"]},
                },
                "required": ["affaire_id", "document_ref", "version_precedente", "titre", "corps", "confidentialite"],
                "additionalProperties": False,
            },
            fonction=deposer_version_document_appareil,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
            roles_appareil=frozenset({"admin"}),
            portee_contexte="affaire",
            cible_contexte=("affaire_id",),
            identite_contexte="affaire",
        ),
        Outil(
            nom="m10_activer_version_document_appareil",
            description=(
                "Activation explicite par l'admin appareil d'une version documentaire interne liée à son "
                "affaire. Aucune preuve de vérité métier n'est déduite de la fidélité du texte."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "affaire_id": _AFFAIRE_ID,
                    "document_ref": _REFERENCE_DOCUMENTAIRE,
                    "version_source": _REFERENCE_DOCUMENTAIRE,
                    "activation_attendue": _REFERENCE_DOCUMENTAIRE_NULLABLE,
                },
                "required": ["affaire_id", "document_ref", "version_source", "activation_attendue"],
                "additionalProperties": False,
            },
            fonction=activer_version_document_appareil,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
            roles_appareil=frozenset({"admin"}),
            portee_contexte="affaire",
            cible_contexte=("affaire_id",),
            identite_contexte="affaire",
        ),
        Outil(
            nom="m10_retirer_document_appareil",
            description=(
                "Retrait doux d'accès documentaire par l'admin appareil : ferme les corps/extraits de "
                "toutes les versions, conserve la chaîne et les copies d'audit existantes. Aucun effacement "
                "définitif n'est promis."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "affaire_id": _AFFAIRE_ID,
                    "document_ref": _REFERENCE_DOCUMENTAIRE,
                    "activation_attendue": _REFERENCE_DOCUMENTAIRE_NULLABLE,
                    "code_motif": {"type": "string", "enum": ["RETRAIT_ACCES"]},
                },
                "required": ["affaire_id", "document_ref", "activation_attendue", "code_motif"],
                "additionalProperties": False,
            },
            fonction=retirer_document_appareil,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
            roles_appareil=frozenset({"admin"}),
            portee_contexte="affaire",
            cible_contexte=("affaire_id",),
            identite_contexte="affaire",
        ),
    )
