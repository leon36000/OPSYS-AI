"""Capacités d'agent du département M2 Revenue CRM.

Chaque outil enveloppe une fonction métier déterministe existante : aucune n'est
réécrite. `m2_ingerer_lead` compose la chaîne complète (validation structurelle et
frontières → écriture → dédoublonnage → statut → readiness) en un seul appel, ce
qui évite à l'agent plusieurs allers-retours et garantit l'ordre des contrôles —
en particulier qu'un doublon probable est toujours signalé à l'ingestion
(correctif d'audit), jamais fusionné : la fusion n'existe nulle part dans ce
paquet, l'arbitrage humain se limite à confirmer deux dossiers distincts.

État partagé : ce module tient le registre du département, partagé par tous les
outils (ingestion, statuts, doublons, interactions, readiness, digest). En
production, il est adossé au stockage durable de l'instance (ADR-0009) via
`opsys.stockage.maillons(...)`, relu à chaque appel et jamais touché au
chargement du module. `reinitialiser_registre()` (réservé aux tests) le bascule
sur un registre EN MÉMOIRE vide ; `utiliser_stockage_durable()` revient au
stockage durable. Ce module est l'unique endroit du département qui connaît
`opsys` au-delà du contrat `Outil` — `registre.py` reste pur (ni `opsys` ni
SQLAlchemy).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Outil

from . import contrats, digest, doublons, ingestion, interactions, readiness, statuts
from .registre import Registre

_DEPARTEMENT = "m02-revenue-crm"
_NOM_REGISTRE = "principal"

_registre_memoire = Registre()
_stockage_durable_actif = True


def reinitialiser_registre() -> None:
    """Réinitialise le registre partagé du département sur un registre EN MÉMOIRE vide
    (réservé aux tests). Annule aussi un éventuel branchement sur le stockage durable :
    après cet appel, `_obtenir_registre()` revient toujours à la mémoire."""
    global _registre_memoire, _stockage_durable_actif
    _registre_memoire = Registre()
    _stockage_durable_actif = False


def utiliser_stockage_durable() -> None:
    """Revient au registre de production, adossé au stockage durable de l'instance (ADR-0009) :
    `opsys.stockage.maillons("m02-revenue-crm", "principal")`, dans la base et la transaction de
    l'appel courant (`opsys.outils.executer_atomique` en ouvre une autour de chaque appel
    d'outil). C'est l'état au chargement du module ; les tests l'utilisent après
    `reinitialiser_registre()`."""
    global _stockage_durable_actif
    _stockage_durable_actif = True


def _obtenir_registre() -> Registre:
    if _stockage_durable_actif:
        # Jamais de cache ici, à dessein (même principe que `opsys.stockage.maillons`) : une
        # instance fraîche à chaque appel relit l'état réel depuis la base, pour ne jamais figer
        # une empreinte devenue périmée entre deux appels d'outil (concurrence, autre processus).
        return Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    return _registre_memoire


# ---------------------------------------------------------------------------
# Fonctions enveloppes — chacune appelle le code métier existant tel quel.
# ---------------------------------------------------------------------------


def ingerer_lead(contrat: dict[str, Any], horodatage: str) -> dict[str, Any]:
    """Ingestion de bout en bout : validation + frontières (ingestion.ingerer),
    dédoublonnage (chaque doublon détecté à l'ingestion est signalé, jamais
    fusionné — correctif d'audit PRD §2b), statut courant, readiness pour M3."""
    reg = _obtenir_registre()
    accuse, verdict = ingestion.ingerer(contrat, reg, horodatage)
    if verdict is not None:
        return {"etape": "ingestion", "accepte": False, "verdict": verdict}

    lead_id = contrat["lead_id"]
    doublons_signales = []
    for autre_lead_id in accuse["doublons_detectes"]:
        signalement, verdict_doublon = doublons.signaler(reg, lead_id, autre_lead_id, horodatage)
        if verdict_doublon is None:
            doublons_signales.append(signalement)

    return {
        "etape": "complet",
        "accepte": True,
        "lead_id": lead_id,
        "accuse_ingestion": accuse,
        "doublons_signales": doublons_signales,
        "statut": statuts.statut_courant(reg, lead_id),
        "pret_pour_m3": readiness.evaluer(reg, lead_id),
    }


def transitionner_statut(
    lead_id: str,
    statut_cible: str,
    horodatage: str,
    owner: str | None = None,
    prochaine_action: dict[str, Any] | None = None,
    reference_devis_m3: str | None = None,
    motif: str | None = None,
) -> dict[str, Any]:
    accuse, verdict = statuts.transitionner(
        lead_id, statut_cible, _obtenir_registre(), horodatage,
        owner=owner, prochaine_action=prochaine_action,
        reference_devis_m3=reference_devis_m3, motif=motif,
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": accuse}


def detecter_doublons(lead_id: str) -> list[str]:
    return doublons.detecter(_obtenir_registre(), lead_id)


def signaler_doublon(lead_id_a: str, lead_id_b: str, horodatage: str) -> dict[str, Any]:
    signalement, verdict = doublons.signaler(_obtenir_registre(), lead_id_a, lead_id_b, horodatage)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": signalement}


def arbitrer_doublon(signalement_id: str, decision: str, horodatage: str) -> dict[str, Any]:
    accuse, verdict = doublons.arbitrer(_obtenir_registre(), signalement_id, decision, horodatage)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": accuse}


def enregistrer_interaction(lead_id: str, auteur: str, resume: str, horodatage: str) -> dict[str, Any]:
    accuse, verdict = interactions.enregistrer(lead_id, auteur, resume, _obtenir_registre(), horodatage)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": accuse}


def marquer_chantier_termine(
    lead_id: str,
    horodatage: str,
    prochaine_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Chorégraphie « travaux terminés » côté M2 (DEFINITION-PRODUIT §6, cascade, ligne M2 :
    « Marque le chantier terminé, écrit l'activité, définit la prochaine action »).

    Transitionne le lead de 'chantier' à 'facture' (statuts.transitionner porte déjà, pour ce
    chemin, la condition prochaine_action — REJ-ACTION-ABSENTE sinon, avant toute écriture),
    puis écrit une interaction système (auteur 'system:m4', jamais un humain ni un texte libre
    généré par un modèle) dont le résumé est composé par ce module depuis les seuls champs
    reçus (lead_id, prochaine_action).

    Exactement deux maillons en cas de succès (transition puis interaction), zéro en cas de
    rejet : la validation de statuts.transitionner précède toute écriture, et par construction
    rien dans ce chemin ne peut faire échouer l'interaction une fois la transition acceptée
    (même horodatage déjà validé, lead désormais non terminal — la correction des statuts
    ci-dessus le garantit —, auteur et résumé non vides par construction) : sinon RuntimeError,
    jamais un maillon orphelin. Le registre est obtenu une seule fois et réutilisé pour les deux
    écritures (même patron que ingerer_lead), et — appelé via opsys.outils.executer_atomique,
    comme tout outil — les deux écritures partagent la transaction de base ouverte par cet
    appel (ADR-0009) : tout est annulé ensemble si quoi que ce soit échoue."""
    reg = _obtenir_registre()
    transition, verdict = statuts.transitionner(
        lead_id, "facture", reg, horodatage, prochaine_action=prochaine_action,
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}

    resume = (
        f"Chantier terminé (lead {lead_id}). Prochaine action : "
        f"{prochaine_action['description']} (échéance {prochaine_action['echeance']})."
    )
    interaction, verdict_interaction = interactions.enregistrer(
        lead_id, "system:m4", resume, reg, horodatage,
    )
    if verdict_interaction is not None:
        raise RuntimeError(
            "interaction système refusée après une transition chantier->facture réussie "
            f"(incohérence interne, pas un refus métier normal) : {verdict_interaction}"
        )
    return {"accepte": True, "resultat": {"transition": transition, "interaction": interaction}}


# ---------------------------------------------------------------------------
# Consommateur d'événements (ADR-0009 §3, PLAN T1.2-c) : m4.travaux_termines
# ---------------------------------------------------------------------------
# La complétion d'un chantier (WCT de M4) prouve que la cédule et le chantier ont eu lieu :
# DEFINITION-PRODUIT §6, cascade « travaux terminés », ligne M2 « Marque le chantier terminé,
# écrit l'activité, définit la prochaine action ». Un lead introuvable, ou dont le statut
# commercial est incompatible avec une complétion de chantier, est une incohérence de données
# entre M4 et M2 : les deux exceptions nommées ci-dessous en sont la preuve pour le répartiteur
# (ADR-0009 §3) — jamais un refus métier silencieux, jamais une écriture partielle.


class LeadIntrouvable(LookupError):
    """m4.travaux_termines : lead_id absent du registre M2 — incohérence de données entre M4 et
    M2 (DEFINITION-PRODUIT §7 M2 : « Aucun lead sans statut, propriétaire, prochaine action ou
    historique »). Jamais un refus métier normal : le répartiteur réessaie puis met en
    quarantaine (ADR-0009 §3), sans qu'aucune écriture n'ait eu lieu."""


class StatutIncompatibleAvecCompletion(ValueError):
    """m4.travaux_termines : le lead existe mais son statut commercial est incompatible avec une
    complétion de chantier — antérieur à la conversion (nouveau, qualifie), clos sans avoir
    jamais été converti (perdu : statuts.STATUTS_TERMINAUX n'admet aucune transition sortante) ou
    déjà postérieur au chantier (facture, paiement, avis : la complétion a déjà été appliquée par
    un événement antérieur). Incohérence de données (DEFINITION-PRODUIT §7 M2 « Cycle de vie
    couvert »), jamais un refus métier normal : le répartiteur réessaie puis met en quarantaine
    (ADR-0009 §3), sans écriture."""


# Table de règles déterministe : statut commercial courant du lead -> étapes de transition à
# parcourir avant `marquer_chantier_termine` (DEFINITION-PRODUIT §6 cascade « travaux terminés »,
# ligne M2 ; §7 M2 « Cycle de vie couvert » : ...converti → cédule → chantier → facture...).
# Chaque étape est un couple déjà autorisé SANS condition additionnelle par
# statuts.TRANSITIONS_AUTORISEES (seul chantier->facture, parcouru par marquer_chantier_termine
# juste après, exige prochaine_action). Un statut absent de cette table est, par définition,
# incompatible avec une complétion de chantier (StatutIncompatibleAvecCompletion ci-dessus).
_ETAPES_VERS_CHANTIER: dict[str, tuple[str, ...]] = {
    "converti": ("cedule", "chantier"),
    "cedule": ("chantier",),
    "chantier": (),
}


def _regle_prochaine_action(charge: dict[str, Any]) -> dict[str, Any]:
    """Table de règles déterministe pour la prochaine action après complétion (PLAN T1.2-c ;
    DEFINITION-PRODUIT §6 cascade « travaux terminés », ligne M2 « ...définit la prochaine
    action » ; §7 M2, règles dures : « jamais...laisser un lead sans prochaine action »).

    La description est un texte FIXE choisi ci-dessous (jamais généré par un modèle) ;
    l'échéance est l'horodatage RÉEL du WCT (horodatage_completion) — jamais une date inventée
    ni calculée depuis une horloge ambiante.

    - Règle 1 (client_satisfait est False) : segment M2.11 `complaint_risk` (§7 M2) — traiter
      le risque de plainte avant toute autre relance.
    - Règle 2 (client_satisfait est True) : relances M2.7 « avis, référence » et segment M2.11
      `referral_candidate` (§7 M2).
    - Règle 3 (client_satisfait absent de la charge, ou explicitement null — jamais déduit) :
      repli par défaut sur le segment M2.11 `invoice_pending`, cohérent avec le statut
      `facture` que la transition vient d'atteindre.
    """
    lead_id = charge["lead_id"]
    echeance = charge["horodatage_completion"]
    client_satisfait = charge.get("client_satisfait")
    if client_satisfait is False:
        description = (
            f"Traiter le risque de plainte du lead {lead_id} avant toute relance "
            "(client insatisfait signalé au WCT — DEFINITION-PRODUIT §7 M2.11 complaint_risk)."
        )
    elif client_satisfait is True:
        description = (
            f"Lancer la relance avis et référence du lead {lead_id} "
            "(client satisfait signalé au WCT — DEFINITION-PRODUIT §7 M2.7, M2.11 referral_candidate)."
        )
    else:
        description = (
            f"Assurer le suivi de la facture du lead {lead_id} jusqu'au paiement "
            "(client_satisfait non recueilli au WCT — DEFINITION-PRODUIT §7 M2.11 invoice_pending)."
        )
    return {"description": description, "echeance": echeance}


def _recevoir_travaux_termines(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme m4.travaux_termines (ADR-0009 §3, PLAN T1.2-c ; DEFINITION-PRODUIT §6 cascade
    « travaux terminés », ligne M2). Retrouve le lead (lead_id du WCT) et le fait avancer de
    façon déterministe : s'il est à `converti` ou `cedule`, il avance jusqu'à `chantier`
    (`_ETAPES_VERS_CHANTIER`), puis applique `marquer_chantier_termine` (chantier -> facture,
    interaction système, prochaine action tirée de `_regle_prochaine_action`).

    Un lead introuvable ou dans un statut incompatible est une incohérence de données : cette
    fonction lève une erreur NOMMÉE (`LeadIntrouvable` ou `StatutIncompatibleAvecCompletion`),
    jamais une écriture partielle — le répartiteur livre chaque paire (événement, consommateur)
    dans son propre point de sauvegarde (ADR-0009 §3) : un lever ici annule toute transition déjà
    amorcée par CET appel, et le répartiteur réessaie puis met en quarantaine après 5 échecs,
    visible par un humain.

    Idempotent : le répartiteur n'appelle cette fonction qu'une fois par (evenement_id,
    consommateur) traité avec succès (`EVENEMENTS_RECUS` UNIQUE, ADR-0009 §3) — une relivraison
    de la même publication ne la rappelle jamais.
    """
    lead_id = charge["lead_id"]
    horodatage = charge["horodatage_completion"]
    reg = _obtenir_registre()

    statut = statuts.statut_courant(reg, lead_id)
    if statut is None:
        raise LeadIntrouvable(f"m4.travaux_termines : lead {lead_id!r} introuvable au registre M2")

    etapes = _ETAPES_VERS_CHANTIER.get(statut)
    if etapes is None:
        raise StatutIncompatibleAvecCompletion(
            f"m4.travaux_termines : lead {lead_id!r} au statut {statut!r}, incompatible avec une "
            "complétion de chantier (attendu converti, cedule ou chantier)"
        )

    depuis = statut
    for statut_cible in etapes:
        _, verdict = statuts.transitionner(lead_id, statut_cible, reg, horodatage)
        if verdict is not None:
            # Jamais attendu : _ETAPES_VERS_CHANTIER ne propose que des couples autorisés sans
            # condition additionnelle par statuts.py — défense en profondeur, même patron que
            # marquer_chantier_termine ci-dessus pour son écriture d'interaction.
            raise RuntimeError(
                f"m4.travaux_termines : transition {depuis}->{statut_cible} refusée de façon "
                f"inattendue pour le lead {lead_id!r} : {verdict}"
            )
        depuis = statut_cible

    prochaine_action = _regle_prochaine_action(charge)
    resultat = marquer_chantier_termine(lead_id, horodatage, prochaine_action)
    if not resultat["accepte"]:
        raise RuntimeError(
            "m4.travaux_termines : marquer_chantier_termine refusé après une transition validée "
            f"pour le lead {lead_id!r} : {resultat['verdict']}"
        )
    return {
        "traite": True,
        "lead_id": lead_id,
        "wct_id": charge.get("wct_id"),
        "statut_final": resultat["resultat"]["transition"]["statut"],
        "prochaine_action": prochaine_action,
    }


def consommateurs() -> dict[str, Callable[[dict], dict]]:
    """Types d'événements consommés par M2 (ADR-0009 §3) — voir `department.yaml/evenements`."""
    return {"m4.travaux_termines": _recevoir_travaux_termines}


def evaluer_readiness(lead_id: str, horodatage: str) -> dict[str, Any]:
    """Émet le marqueur de readiness (aucune écriture au registre) : soit le lead
    satisfait déjà les quatre conditions et le marqueur est signé, soit un
    verdict détaille précisément ce qui manque."""
    marqueur, verdict = readiness.emettre_marqueur(_obtenir_registre(), lead_id, horodatage)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": marqueur}


def produire_digest(date_jour: str, horodatage: str) -> str:
    return digest.produire_digest(_obtenir_registre(), date_jour, horodatage)


# ---------------------------------------------------------------------------
# Schémas JSON partagés
# ---------------------------------------------------------------------------

_CONTACT = {
    "type": "object",
    "properties": {cle: {"type": "string"} for cle in contrats.CLES_CONTACT},
    "additionalProperties": False,
}
_CONTRAT = {
    "type": "object",
    "description": "Contrat gelé transmis par le module amont (les sept champs exacts, aucun de plus).",
    "properties": {
        "lead_id": {"type": "string"},
        "conversation_id": {"type": "string"},
        "contact": _CONTACT,
        "type_travaux": {"type": "string", "enum": list(contrats.TYPES_TRAVAUX)},
        "ville": {"type": "string"},
        "urgence_declaree": {"type": "boolean"},
        "canal": {"type": "string", "enum": list(contrats.CANAUX)},
    },
    "required": list(contrats.CHAMPS_CONTRAT_GELE),
    "additionalProperties": False,
}
_HORODATAGE = {"type": "string", "description": "ISO-8601 avec fuseau horaire, fourni par l'appelant"}
_PROCHAINE_ACTION = {
    "type": ["object", "null"],
    "description": "{description (non vide), echeance (ISO-8601 avec fuseau)} — jamais générée par ce module",
}
_PROCHAINE_ACTION_OBLIGATOIRE = {
    "type": "object",
    "description": (
        "{description (non vide), echeance (ISO-8601 avec fuseau)} — jamais générée par ce "
        "module, obligatoire pour cet outil (jamais de lead sans prochaine action)."
    ),
}


def outils() -> tuple[Outil, ...]:
    """Capacités exposées aux agents (fonction : les constantes publiques du paquet sont des énumérés)."""
    return (
        Outil(
            nom="m2_ingerer_lead",
            description=(
                "Ingère un lead qualifié de bout en bout : validation structurelle et frontières de "
                "vérité, écriture au registre, détection ET signalement des doublons probables (jamais "
                "de fusion), statut courant, readiness pour M3."
            ),
            parametres={
                "type": "object",
                "properties": {"contrat": _CONTRAT, "horodatage": _HORODATAGE},
                "required": ["contrat", "horodatage"],
                "additionalProperties": False,
            },
            fonction=ingerer_lead,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m2_transitionner_statut",
            description=(
                "Transitionne le statut d'un lead (nouveau→qualifie, qualifie→converti, "
                "qualifie→perdu, nouveau→perdu). Chaque transition exige les données humaines "
                "correspondantes (owner+prochaine_action, ou reference_devis_m3, ou motif) ; jamais "
                "générées par cet outil."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "statut_cible": {"type": "string", "enum": list(statuts.STATUTS)},
                    "horodatage": _HORODATAGE,
                    "owner": {"type": ["string", "null"]},
                    "prochaine_action": _PROCHAINE_ACTION,
                    "reference_devis_m3": {"type": ["string", "null"]},
                    "motif": {"type": ["string", "null"]},
                },
                "required": ["lead_id", "statut_cible", "horodatage"],
                "additionalProperties": False,
            },
            fonction=transitionner_statut,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m2_detecter_doublons",
            description="Liste les lead_id déjà ingérés qui sont des doublons probables du lead donné (lecture pure).",
            parametres={
                "type": "object",
                "properties": {"lead_id": {"type": "string"}},
                "required": ["lead_id"],
                "additionalProperties": False,
            },
            fonction=detecter_doublons,
        ),
        Outil(
            nom="m2_signaler_doublon",
            description="Inscrit un signalement de doublon potentiel entre deux leads, en attente d'arbitrage humain.",
            parametres={
                "type": "object",
                "properties": {
                    "lead_id_a": {"type": "string"},
                    "lead_id_b": {"type": "string"},
                    "horodatage": _HORODATAGE,
                },
                "required": ["lead_id_a", "lead_id_b", "horodatage"],
                "additionalProperties": False,
            },
            fonction=signaler_doublon,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m2_arbitrer_doublon",
            description=(
                "Consigne l'arbitrage humain d'un signalement de doublon. Seule décision possible en "
                "v1 : 'distincts_confirmes' (les deux leads restent des dossiers séparés)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "signalement_id": {"type": "string"},
                    "decision": {"type": "string", "enum": ["distincts_confirmes"]},
                    "horodatage": _HORODATAGE,
                },
                "required": ["signalement_id", "decision", "horodatage"],
                "additionalProperties": False,
            },
            fonction=arbitrer_doublon,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m2_enregistrer_interaction",
            description="Enregistre une interaction commerciale humaine réelle pour un lead actif (non clos).",
            parametres={
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "auteur": {"type": "string"},
                    "resume": {"type": "string"},
                    "horodatage": _HORODATAGE,
                },
                "required": ["lead_id", "auteur", "resume", "horodatage"],
                "additionalProperties": False,
            },
            fonction=enregistrer_interaction,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m2_evaluer_readiness",
            description=(
                "Évalue si un lead qualifié est prêt pour M3 (owner, type de travaux valide, ville, "
                "interaction post-qualification). Émet un marqueur signé si oui, sinon un verdict "
                "détaillant précisément ce qui manque. Ne modifie jamais le registre."
            ),
            parametres={
                "type": "object",
                "properties": {"lead_id": {"type": "string"}, "horodatage": _HORODATAGE},
                "required": ["lead_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=evaluer_readiness,
        ),
        Outil(
            nom="m2_produire_digest",
            description="Produit le digest déterministe du pipeline commercial, reconstruit à la date_jour donnée.",
            parametres={
                "type": "object",
                "properties": {"date_jour": {"type": "string"}, "horodatage": _HORODATAGE},
                "required": ["date_jour", "horodatage"],
                "additionalProperties": False,
            },
            fonction=produire_digest,
        ),
        Outil(
            nom="m2_marquer_chantier_termine",
            description=(
                "Marque le chantier d'un lead converti comme terminé (statut chantier→facture) et "
                "écrit l'interaction système correspondante (auteur system:m4, résumé factuel "
                "construit depuis les champs reçus, jamais un texte libre). prochaine_action est "
                "obligatoire : jamais de lead sans prochaine action."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "horodatage": _HORODATAGE,
                    "prochaine_action": _PROCHAINE_ACTION_OBLIGATOIRE,
                },
                "required": ["lead_id", "horodatage", "prochaine_action"],
                "additionalProperties": False,
            },
            fonction=marquer_chantier_termine,
            autonomie=Autonomie.T1,
        ),
    )
