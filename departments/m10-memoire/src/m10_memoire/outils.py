"""Capacités d'agent du département M10 Mémoire.

Chaque outil enveloppe une fonction métier déterministe existante. `m10_journaliser_decision`
compose validation → écriture au registre Affaires → référence vérifiable en un seul appel ;
`m10_contexte_preflight` est le PREFLIGHT (D-014, docs/research/R4-memory-rag.md §10) qui
vérifie si un dossier de contexte est suffisant et, sinon, trace le refus au registre — sans
jamais interrompre l'appelant. PLAN T3.3 ajoute trois capacités : `m10_paquet_contexte_affaire`
(paquets de contexte en couches, `paquets.py`), `m10_consolider_affaire` (consolidation nocturne
idempotente, `consolidation.py`) et `m10_auditer_non_oubli` (audit « non-oubli », `audit.py`), plus
la consommation de `m6.variance_chantier` (`variance.py`, même registre Événements que le WCT).

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

from collections.abc import Callable
from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Outil, depuis_couple

from . import audit, consolidation, contexte, contrats, decisions, paquets, registre, revision, variance, wct

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
_IDENTIFIANT_ATTENDU = {
    "type": "object",
    "properties": {
        "type_evenement": {"type": "string", "enum": ["m4.travaux_termines", "m6.variance_chantier"]},
        "identifiant": {"type": "string", "description": "wct_id (WCT) ou evenement_id (variance)."},
    },
    "required": ["type_evenement", "identifiant"],
    "additionalProperties": False,
}


def journaliser_decision(decision: dict[str, Any], horodatage: str) -> dict[str, Any]:
    """Chaîne complète : validation (raison, statut) → écriture (registre Affaires) → référence.

    N'écrit rien si la décision est refusée (raison absente, statut hors énuméré).
    """
    maillon, code = decisions.enregistrer_decision(decision, _REGISTRE_AFFAIRES, horodatage)
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


def consommateurs() -> dict[str, Callable[[dict], dict]]:
    """Types d'événements consommés par M10 (ADR-0009 §3) — voir `department.yaml/evenements`."""
    return {
        "m4.travaux_termines": _recevoir_travaux_termines,
        "m6.variance_chantier": _recevoir_variance_chantier,
    }


def signaler_revision(ligne_id_a: str, ligne_id_b: str, horodatage: str) -> dict[str, Any]:
    return depuis_couple(
        revision.signaler_revision(_REGISTRE_AFFAIRES, ligne_id_a, ligne_id_b, horodatage)
    )


def arbitrer_revision(revision_ligne_id: str, statut: str, horodatage: str) -> dict[str, Any]:
    return depuis_couple(
        revision.arbitrer_revision(_REGISTRE_AFFAIRES, revision_ligne_id, statut, horodatage)
    )


def statut_decision(decision_id: str) -> dict[str, Any]:
    """Statut courant, TOUJOURS calculé par relecture de la chaîne (jamais un champ positionnable)."""
    return {"statut": decisions.statut_courant(_REGISTRE_AFFAIRES, decision_id)}


def statut_revision(revision_ligne_id: str) -> dict[str, Any]:
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
    de caractères fixé par le code (non exposé à l'appelant — P11, économie de tokens)."""
    return paquets.assembler_paquet_contexte(affaire_id, horodatage, _REGISTRE_EVENEMENTS, _REGISTRE_AFFAIRES)


def consolider_affaire(affaire_id: str, jour: str, horodatage: str) -> dict[str, Any]:
    """Consolidation nocturne d'une affaire pour un jour donné (PLAN T3.3, `consolidation.py`) :
    idempotente (`ecrit=False, deja_consolide=True` si déjà faite pour ce `(affaire_id, jour)`)."""
    return consolidation.consolider_affaire(affaire_id, jour, horodatage, _REGISTRE_EVENEMENTS, _REGISTRE_AFFAIRES)


def auditer_non_oubli(identifiants_attendus: list[dict[str, str]]) -> dict[str, Any]:
    """Audit « non-oubli » (PLAN T3.3, `audit.py`) : intégrité des deux chaînes + liste compacte des
    faits attendus sans trace au registre Événements."""
    return audit.auditer_non_oubli(identifiants_attendus, _REGISTRE_EVENEMENTS, _REGISTRE_AFFAIRES)


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
                "properties": {"decision": _DECISION, "horodatage": {"type": "string"}},
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
                "règles de l'entreprise → faits durables de l'affaire → événements récents → "
                "signaux critiques non résolus. Budget de caractères et troncature calculés par "
                "le code ; une couche vide est déclarée vide, jamais absente en silence."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "affaire_id": {"type": "string", "description": "lead_id de l'affaire."},
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
            nom="m10_consolider_affaire",
            description=(
                "Consolidation nocturne : condense les événements d'une affaire pour un jour "
                "donné en UN fait durable au registre Affaires, sans perdre la trace vers ses "
                "sources. Idempotente : rejouer le même (affaire_id, jour) ne crée rien de plus."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "affaire_id": {"type": "string", "description": "lead_id de l'affaire."},
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
            nom="m10_auditer_non_oubli",
            description=(
                "Audit « non-oubli » : intégrité des deux chaînes (registre.valider_chaine) et, "
                "pour chaque fait ATTENDU fourni (WCT ou variance), vérifie sa trace au registre "
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
    )
