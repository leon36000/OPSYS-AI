"""Capacités d'agent du département M1 Front Office.

Chaque outil enveloppe une fonction métier déterministe existante : aucune n'est
réécrite. `m1_traiter_demande_entrante` compose la chaîne complète (provenance →
registre anti-perte → consentement → qualification) en un seul appel, ce qui évite
à l'agent plusieurs allers-retours et garantit l'ordre des contrôles — en
particulier que TOUT signal entrant laisse une ligne au registre, qualifié ou non
(M1-R-10), et qu'aucun contenu externe n'est traité avant d'être passé par le
filtre de provenance (M1-R-08).

État partagé : ce module tient un registre, partagé par tous les outils qui
écrivent ou lisent l'historique du département (signal unique par demande,
phases voix, digest). En production, ce registre est adossé au stockage
durable de l'instance (`opsys.stockage`, ADR-0009) : `registre.py` reste pur
(aucun import `opsys`/SQLAlchemy) et ignore que ses maillons survivent au
redémarrage — c'est cet adaptateur, seul, qui fait le lien.
`reinitialiser_registre()` n'est pas un outil d'agent : c'est un point
d'entrée réservé aux tests, pour repartir d'un registre EN MÉMOIRE propre
entre deux scénarios (comportement inchangé pour les tests unitaires du
département, qui ne montent pas de base) ; `utiliser_stockage_durable()` revient au registre de production.

Canaux du core (PLAN T2.1-a, `docs/departements/M1-canaux.md`) : `m1_recevoir_message_canal` reçoit un message
que l'extension `sms` livre à l'agent M1. Les champs de la plateforme (canal, expéditeur, identifiant, heure)
passent par `reception.py`, qui en tire l'identité, la conversation, le signal et le contact ; puis la chaîne
ci-dessus qualifie le message. Un lead qualifié est publié au bus (`m1.lead_qualifie`, dans la transaction de
l'inscription au registre) : c'est ainsi qu'il atteint M2, qui n'est pas un outil que l'agent M1 voit.
"""

from __future__ import annotations

from typing import Any

from opsys import evenements, stockage, taxonomie
from opsys.outils import Autonomie, Niveau, Outil

from . import (
    adaptateurs,
    consentement,
    contrats,
    digest,
    garde_fou,
    phases_voix,
    provenance,
    qualification,
    reception,
)
from .phases_voix import TransitionInterdite
from .registre import Registre

_CANAUX = ("telephone", "courriel", "formulaire", "texte")
_DEPARTEMENT = "m01-front-office"
_NOM_REGISTRE = "principal"


def _registre_durable() -> Registre:
    """Registre de production : maillons portés par `opsys.stockage` (ADR-0009),
    dans la transaction que `Capacites.appeler` ouvre pour chaque appel d'outil."""
    return Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))


_registre = _registre_durable()
# Vrai tant que le registre est celui de production (base de l'instance) : c'est alors seulement que le bus
# d'événements existe (base migrée, transaction de l'appel), comme pour M2. En mémoire (tests unitaires), rien
# n'est publié.
_stockage_durable_actif = True

TYPE_EVENEMENT_LEAD = "m1.lead_qualifie"


def reinitialiser_registre() -> None:
    """Réinitialise le registre partagé du département à un registre EN MÉMOIRE
    (réservé aux tests unitaires du département, qui ne montent pas de base)."""
    global _registre, _stockage_durable_actif
    _registre = Registre()
    _stockage_durable_actif = False


def utiliser_stockage_durable() -> None:
    """Revient au registre de production, adossé à la base de l'instance (ADR-0009) : l'état au chargement du
    module, que les tests rétablissent après `reinitialiser_registre()` quand ils montent une base."""
    global _registre, _stockage_durable_actif
    _registre = _registre_durable()
    _stockage_durable_actif = True


def _publier_lead(lead: dict[str, Any], horodatage: str, signal_id: str) -> None:
    """Publie le lead qualifié au bus (`m1.lead_qualifie`), dans la transaction courante, SEULEMENT avec le
    registre de production. L'identifiant de l'événement vient du `lead_id` : un lead rejoué ne s'y ajoute pas
    deux fois (`opsys.evenements.publier`, idempotent)."""
    if not _stockage_durable_actif:
        return
    evenements.publier(
        TYPE_EVENEMENT_LEAD,
        _DEPARTEMENT,
        {"lead": lead, "horodatage": horodatage, "signal_id": signal_id},
        evenement_id=f"m1-lead-qualifie-{lead['lead_id']}",
    )


def _obtenir_registre() -> Registre:
    return _registre


# ---------------------------------------------------------------------------
# Fonctions enveloppes — chacune appelle le code métier existant tel quel.
# ---------------------------------------------------------------------------


def filtrer_provenance(contenu_brut: str) -> dict[str, Any]:
    contenu_filtre, sain = provenance.filtrer(contenu_brut)
    return {"contenu_filtre": contenu_filtre, "sain": sain}


def qualifier_signal(
    contenu_filtre: str,
    canal: str,
    conversation_id: str,
    zone_desservie: list[str],
    source: str | None = None,
    utm: dict[str, str] | None = None,
    campagne: str | None = None,
) -> dict[str, Any]:
    return qualification.qualifier(
        contenu_filtre, canal, conversation_id, zone_desservie,
        source=source, utm=utm, campagne=campagne,
    )


def verifier_garde_fou(texte: str) -> dict[str, Any]:
    return garde_fou.verifier_sortie(texte)


def verifier_consentement_signal(consentement_enregistrement: str | None = None) -> dict[str, Any]:
    return consentement.verifier_consentement({"consentement_enregistrement": consentement_enregistrement})


def ouvrir_conversation(signal_id: str, horodatage: str) -> dict[str, Any]:
    resultat = phases_voix.ouvrir_conversation(signal_id, horodatage, _obtenir_registre())
    if "conversation_id" not in resultat:
        # phases_voix renvoie un verdict nu (pas un couple) sur horodatage invalide.
        return {"accepte": False, "verdict": resultat}
    return {"accepte": True, "resultat": resultat}


def transitionner_phase(conversation: dict[str, Any], phase_cible: int, horodatage: str) -> dict[str, Any]:
    """Fait progresser une conversation d'une phase. `conversation` est l'objet
    renvoyé par `m1_ouvrir_conversation` (ou une transition précédente), à
    reporter tel quel — jamais reconstruit de mémoire par l'agent."""
    try:
        verdict = phases_voix.transitionner(conversation, phase_cible, horodatage, _obtenir_registre())
    except TransitionInterdite as exc:
        # phases_voix lève sur violation plutôt que de renvoyer un couple : on
        # traduit ici vers le même patron (accepte, verdict) que le reste des
        # outils, pour que l'agent n'ait qu'une seule forme de réponse à lire.
        return {"accepte": False, "verdict": exc.verdict, "conversation": conversation}
    if verdict.get("code") != "OK":
        return {"accepte": False, "verdict": verdict, "conversation": conversation}
    return {"accepte": True, "verdict": verdict, "conversation": conversation}


def abandonner_conversation(conversation: dict[str, Any], horodatage: str) -> dict[str, Any]:
    verdict = phases_voix.abandonner(conversation, horodatage, _obtenir_registre())
    if verdict.get("code") != "OK":
        return {"accepte": False, "verdict": verdict, "conversation": conversation}
    return {"accepte": True, "verdict": verdict, "conversation": conversation}


def produire_digest(date_reference: str) -> str:
    return digest.produire_digest(_obtenir_registre().lire(), date_reference)


def emettre_notification(canal: str, message: str) -> dict[str, Any]:
    """Émet un message vers un canal externe (bus de notification en mode ombre).
    Action T2 : réversible, mais externe — jamais présentée comme faite avant
    l'approbation humaine effective en mode ombre/supervisé."""
    bus = adaptateurs.creer_bus(mode_ombre=True)
    resultat = bus.emettre(canal, message)
    if isinstance(resultat, dict):
        return {"accepte": False, "verdict": resultat}
    return {"accepte": True, "resultat": {"message_id": resultat}}


def traiter_demande_entrante(
    contenu_brut: str,
    canal: str,
    conversation_id: str,
    signal_id: str,
    horodatage: str,
    zone_desservie: list[str],
    consentement_enregistrement: str | None = None,
    source: str | None = None,
    utm: dict[str, str] | None = None,
    campagne: str | None = None,
) -> dict[str, Any]:
    """Chaîne complète d'une demande entrante : provenance → registre anti-perte
    → consentement (si vocal) → qualification → décision de routage.

    Chaque signal produit exactement une ligne au registre anti-perte (M1-R-10),
    qu'il soit qualifié ou non : un client qui ne fournit pas assez d'informations
    n'est jamais perdu, seulement redirigé vers une demande de précisions.

    Le lead émis est un `LeadQualifie` v2 (`service` de la taxonomie du socle, lu dans le profil
    d'entreprise de l'instance). Sans service déclaré par l'instance, l'appel est refusé
    (ValueError qui dit quoi configurer) et rien n'est écrit : c'est une configuration à faire,
    pas une demande à préciser. `source`, `utm`, `campagne` sont transmis tels que fournis.
    Ici, tous les champs viennent de l'appelant (voix transcrite, saisie manuelle) : pour un message
    qu'un canal du core livre, `recevoir_message_canal` les tire de la plateforme.
    """
    return _traiter(
        contenu_brut, canal, conversation_id, signal_id, horodatage, zone_desservie,
        consentement_enregistrement, source, utm, campagne,
    )


def _traiter(
    contenu_brut: str,
    canal: str,
    conversation_id: str,
    signal_id: str,
    horodatage: str,
    zone_desservie: list[str],
    consentement_enregistrement: str | None,
    source: str | None,
    utm: dict[str, str] | None,
    campagne: str | None,
    contact_canal: dict[str, str] | None = None,
    cle_session: str | None = None,
) -> dict[str, Any]:
    # 0. Configuration avant tout effet : sans service déclaré par l'instance, on refuse ici,
    #    avant d'écrire au registre (fail-closed, le message dit quoi configurer).
    services, verdict_profil = taxonomie.charger_services()
    if verdict_profil is not None:
        raise ValueError(f"{verdict_profil['code']}: {verdict_profil['detail']}")

    reg = _obtenir_registre()

    # 1. Provenance : neutralise toute tentative d'injection AVANT tout traitement
    #    (M1-R-08 — un contenu externe n'est jamais fiable tel quel).
    contenu_filtre, sain = provenance.filtrer(contenu_brut)

    # 2. Registre anti-perte : une ligne immuable, qualifié ou non.
    signal: dict[str, Any] = {
        "type_entree": "signal",
        "canal": canal,
        "conversation_id": conversation_id,
        "signal_id": signal_id,
        "horodatage": horodatage,
        "contenu_filtre": contenu_filtre,
        "provenance_saine": sain,
    }
    if source is not None:
        signal["source"] = source
    ligne_id_signal = reg.ajouter(signal)

    # 3. Consentement : uniquement pertinent pour un canal vocal (M1-R-07).
    verdict_consentement = None
    if canal == "telephone":
        verdict_consentement = consentement.verifier_consentement(
            {"consentement_enregistrement": consentement_enregistrement},
            registre=reg,
            horodatage=horodatage,
        )

    # 4. Qualification par règles déterministes, zéro LLM, zéro ville inventée.
    resultat_qualif = qualification.qualifier(
        contenu_filtre, canal, conversation_id, zone_desservie,
        services=services, source=source, utm=utm, campagne=campagne, contact_canal=contact_canal,
    )
    if "verdict" in resultat_qualif:
        return {
            "etape": "qualification",
            "accepte": True,
            "signal_ligne_id": ligne_id_signal,
            "provenance_saine": sain,
            "consentement": verdict_consentement,
            "qualifie": False,
            "verdict_qualification": resultat_qualif["verdict"],
            "decision": "DEMANDER_PRECISIONS",
        }

    # 5. Décision : lead conforme au contrat gelé M1->M2 v2 (vérification défensive :
    #    qualifier() garantit déjà la conformité, valider_lead le confirme et
    #    lèverait sinon — fail-closed, jamais silencieux).
    contrats.valider_lead(resultat_qualif, services=services)

    lead_emis: dict[str, Any] = {
        "type_entree": "lead_emis",
        "canal": canal,
        "conversation_id": conversation_id,
        "signal_id": signal_id,
        "horodatage": horodatage,
        "lead": resultat_qualif,
    }
    if cle_session is not None:
        lead_emis["cle_session"] = cle_session
    ligne_id_lead = reg.ajouter(lead_emis)
    _publier_lead(resultat_qualif, horodatage, signal_id)

    reponse = {
        "etape": "decision",
        "accepte": True,
        "signal_ligne_id": ligne_id_signal,
        "provenance_saine": sain,
        "consentement": verdict_consentement,
        "qualifie": True,
        "lead": resultat_qualif,
        "lead_ligne_id": ligne_id_lead,
        "decision": "TRANSMETTRE_M2",
    }
    if cle_session is not None:
        reponse["cle_session"] = cle_session
    return reponse


def _signal_deja_recu(reg: Registre, signal_id: str) -> dict[str, Any] | None:
    """La réponse déjà donnée à ce signal, ou `None` s'il est nouveau. Un message que la plateforme livre deux fois
    (reprise après panne, nouvel essai de l'agent) ne laisse pas une seconde ligne : exactement une par signal."""
    signal = lead = alerte = None
    for maillon in reg.lire():
        if maillon.get("signal_id") != signal_id:
            continue
        type_entree = maillon.get("type_entree")
        if type_entree == "signal":
            signal = maillon
        elif type_entree == "lead_emis":
            lead = maillon
        elif type_entree == "alerte" and maillon.get("marqueur") == "retrait_consentement":
            alerte = maillon
    if signal is None:
        return None
    reponse: dict[str, Any] = {
        "etape": "doublon",
        "accepte": True,
        "doublon": True,
        "signal_ligne_id": signal["ligne_id"],
        "qualifie": lead is not None,
        "decision": "DEMANDER_PRECISIONS",
    }
    if lead is not None:
        reponse.update(lead=lead["lead"], lead_ligne_id=lead["ligne_id"], decision="TRANSMETTRE_M2")
        if "cle_session" in lead:
            reponse["cle_session"] = lead["cle_session"]
    elif alerte is not None:
        reponse.update(alerte_ligne_id=alerte["ligne_id"], decision="RETRAIT_CONSENTEMENT")
    return reponse


def _enregistrer_retrait(reg: Registre, message: reception.MessageRecu) -> dict[str, Any]:
    """Un client écrit STOP : le signal est inscrit (une ligne par signal), une alerte dit qu'il ne veut plus de
    messages, et rien n'est qualifié ni émis. Aucune réponse n'est proposée : le retrait s'applique tel quel
    (POLITIQUE-consentement-sms.md §4)."""
    contenu_filtre, sain = provenance.filtrer(message.contenu)
    ligne_signal = reg.ajouter({
        "type_entree": "signal",
        "canal": message.canal_contrat,
        "source": message.canal,
        "conversation_id": message.conversation_id,
        "signal_id": message.signal_id,
        "horodatage": message.horodatage,
        "contenu_filtre": contenu_filtre,
        "provenance_saine": sain,
    })
    ligne_alerte = reg.ajouter({
        "type_entree": "alerte",
        "marqueur": "retrait_consentement",
        "canal": message.canal_contrat,
        "source": message.canal,
        "conversation_id": message.conversation_id,
        "signal_id": message.signal_id,
        "horodatage": message.horodatage,
    })
    return {
        "etape": "consentement",
        "accepte": True,
        "signal_ligne_id": ligne_signal,
        "alerte_ligne_id": ligne_alerte,
        "provenance_saine": sain,
        "qualifie": False,
        "decision": "RETRAIT_CONSENTEMENT",
        "consigne": "Le client se retire : n'envoie aucun message à ce correspondant, ne propose aucune réponse.",
    }


def recevoir_message_canal(
    canal: str,
    expediteur: str,
    message_id: str,
    recu_le: str,
    texte: str,
    objet: str | None = None,
) -> dict[str, Any]:
    """Un message qu'un canal du core (SMS, plus tard courriel) livre à l'agent M1, de bout en bout.

    Les cinq premiers paramètres sont recopiés par l'agent des blocs que la plateforme génère ; `reception.py`
    en tire ce qui compte, jamais le texte du client : le correspondant validé, la conversation (empreinte, sans
    numéro), le signal (`<canal>:<message_id>`, qui rend la réception idempotente), le contact du lead (l'identité
    du canal, seule), la clé de session du core. La zone desservie vient du profil de l'instance : l'agent ne la
    fournit pas. `source` du lead est le canal du core.

    Refus (`ValueError`, rien d'écrit) : champ de plateforme invalide, service ou zone non déclarés par l'instance.
    Sinon : un retrait (STOP) est inscrit sans être qualifié ; un message déjà reçu rend sa réponse sans rien
    écrire ; tout autre passe par `_traiter` (provenance → registre → qualification → lead → bus).
    """
    message = reception.preparer(canal, expediteur, message_id, recu_le, texte, objet)
    zone, verdict_zone = taxonomie.charger_zone_desservie()
    if verdict_zone is not None:
        raise ValueError(f"{verdict_zone['code']}: {verdict_zone['detail']}")
    _, verdict_profil = taxonomie.charger_services()
    if verdict_profil is not None:
        raise ValueError(f"{verdict_profil['code']}: {verdict_profil['detail']}")
    reg = _obtenir_registre()
    deja = _signal_deja_recu(reg, message.signal_id)
    if deja is not None:
        return deja
    if message.retrait:
        return _enregistrer_retrait(reg, message)
    return _traiter(
        message.contenu, message.canal_contrat, message.conversation_id, message.signal_id, message.horodatage,
        list(zone), None, message.canal, None, None,
        contact_canal=message.contact, cle_session=message.cle_session,
    )


# ---------------------------------------------------------------------------
# Schémas JSON partagés
# ---------------------------------------------------------------------------

_CANAL = {"type": "string", "enum": list(_CANAUX)}
_ZONE_DESSERVIE = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Villes desservies par l'entreprise (configuration métier, jamais devinée).",
}
_SOURCE = {"type": ["string", "null"], "description": "Optionnel : canal d'acquisition déclaré, jamais deviné."}
_UTM = {
    "type": ["object", "null"],
    "description": "Optionnel : paramètres UTM tels que fournis (utm_source, utm_medium, utm_campaign, utm_content).",
}
_CAMPAGNE = {"type": ["string", "null"], "description": "Optionnel : campagne marketing déclarée, jamais devinée."}
_CONVERSATION = {
    "type": "object",
    "description": "Objet conversation renvoyé par m1_ouvrir_conversation ou une transition précédente.",
}


def outils() -> tuple[Outil, ...]:
    """Capacités exposées aux agents (fonction : les constantes publiques du paquet sont des énumérés)."""
    return (
        Outil(
            nom="m1_traiter_demande_entrante",
            description=(
                "Traite une demande entrante de bout en bout : filtre la provenance, inscrit le "
                "signal au registre anti-perte, vérifie le consentement si canal=telephone, qualifie "
                "par règles déterministes et décide du routage (précisions à demander ou transmission "
                "à M2). Aucune ville hors de zone_desservie n'est reconnue."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "contenu_brut": {"type": "string"},
                    "canal": _CANAL,
                    "conversation_id": {"type": "string"},
                    "signal_id": {"type": "string"},
                    "horodatage": {"type": "string", "description": "ISO-8601 avec fuseau horaire"},
                    "zone_desservie": _ZONE_DESSERVIE,
                    "consentement_enregistrement": {
                        "type": ["string", "null"],
                        "description": "'accorde' ou autre ; pertinent seulement si canal=telephone",
                    },
                    "source": _SOURCE,
                    "utm": _UTM,
                    "campagne": _CAMPAGNE,
                },
                "required": [
                    "contenu_brut", "canal", "conversation_id", "signal_id", "horodatage", "zone_desservie",
                ],
                "additionalProperties": False,
            },
            fonction=traiter_demande_entrante,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m1_recevoir_message_canal",
            description=(
                "Reçoit un message qu'un canal du core (sms, courriel) livre à cet agent : recopie tel quel le canal, "
                "l'expéditeur, l'identifiant et l'heure de réception que la plateforme donne, et le texte du client. "
                "L'outil filtre la provenance, inscrit le signal au registre anti-perte (une ligne par message, un "
                "message rejoué ne s'ajoute pas), reconnaît un retrait (STOP), qualifie par règles (service déclaré, "
                "ville de la zone de l'entreprise, expéditeur comme contact) et transmet le lead à M2 par le bus. "
                "Rien n'est envoyé au client."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "canal": {
                        "type": "string",
                        "enum": sorted(reception.CANAL_DU_CONTRAT),
                        "description": "Canal du core, champ channel du bloc Message Context. Jamais deviné.",
                    },
                    "expediteur": {
                        "type": "string",
                        "description": "Numéro E.164 (sms) ou adresse (courriel) du bloc Conversation info (sender).",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Identifiant du message, champ message_id du bloc Conversation info.",
                    },
                    "recu_le": {
                        "type": "string",
                        "description": (
                            "Heure de réception : le champ timestamp de « Conversation info », recopié tel quel "
                            "(ex. « Tue 2026-09-29 09:15:30 EDT ») ou en ISO-8601 avec fuseau. Jamais calculée."
                        ),
                    },
                    "texte": {"type": "string", "description": "Corps du message, tel que reçu, sans le résumer."},
                    "objet": {"type": ["string", "null"], "description": "Objet d'un courriel ; absent pour un SMS."},
                },
                "required": ["canal", "expediteur", "message_id", "recu_le", "texte"],
                "additionalProperties": False,
            },
            fonction=recevoir_message_canal,
            autonomie=Autonomie.T1,
            # T1 (écriture interne : registre anti-perte, bus) mais N2 « tâche interne » (ADR-0009 §4, automatique) et
            # non le défaut T1 -> N3 : c'est l'agent d'un canal client qui l'appelle à chaque message ; en N3, le mode
            # ombre mettrait chaque message reçu en attente d'approbation, et le garde du core (ADR-0010, N3+ exige
            # un contexte d'affaire) refuserait le premier message d'un client, dont la session n'a pas encore
            # d'affaire liée. L'outil ne décide rien et n'engage personne ; tout message vers le client reste
            # `m1_emettre_notification` (N4).
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m1_filtrer_provenance",
            description="Neutralise toute tentative d'injection dans un contenu externe brut.",
            parametres={
                "type": "object",
                "properties": {"contenu_brut": {"type": "string"}},
                "required": ["contenu_brut"],
                "additionalProperties": False,
            },
            fonction=filtrer_provenance,
        ),
        Outil(
            nom="m1_qualifier_signal",
            description=(
                "Extrait le service (déclaré par le profil d'entreprise), la ville (dans zone_desservie) "
                "et l'urgence déclarée d'un contenu déjà filtré. Ne renvoie qu'un lead v2 complet ou "
                "un verdict de rejet ; plusieurs services évoqués ou aucun : rejet, demander lequel."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "contenu_filtre": {"type": "string"},
                    "canal": _CANAL,
                    "conversation_id": {"type": "string"},
                    "zone_desservie": _ZONE_DESSERVIE,
                    "source": _SOURCE,
                    "utm": _UTM,
                    "campagne": _CAMPAGNE,
                },
                "required": ["contenu_filtre", "canal", "conversation_id", "zone_desservie"],
                "additionalProperties": False,
            },
            fonction=qualifier_signal,
        ),
        Outil(
            nom="m1_verifier_garde_fou",
            description="Vérifie qu'un texte destiné au client ne contient ni prix, ni date, ni engagement, ni aveu.",
            parametres={
                "type": "object",
                "properties": {"texte": {"type": "string"}},
                "required": ["texte"],
                "additionalProperties": False,
            },
            fonction=verifier_garde_fou,
        ),
        Outil(
            nom="m1_verifier_consentement",
            description="Vérifie si le consentement explicite à l'enregistrement a été accordé ('accorde' uniquement).",
            parametres={
                "type": "object",
                "properties": {
                    "consentement_enregistrement": {"type": ["string", "null"]},
                },
                "additionalProperties": False,
            },
            fonction=verifier_consentement_signal,
        ),
        Outil(
            nom="m1_ouvrir_conversation",
            description="Ouvre une conversation vocale en phase 0 et inscrit son ouverture au registre.",
            parametres={
                "type": "object",
                "properties": {
                    "signal_id": {"type": "string"},
                    "horodatage": {"type": "string"},
                },
                "required": ["signal_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=ouvrir_conversation,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m1_transitionner_phase",
            description=(
                "Fait progresser une conversation vocale vers la phase suivante (0→5), strictement "
                "linéaire : toute tentative de saut fige la conversation."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "conversation": _CONVERSATION,
                    "phase_cible": {"type": "integer"},
                    "horodatage": {"type": "string"},
                },
                "required": ["conversation", "phase_cible", "horodatage"],
                "additionalProperties": False,
            },
            fonction=transitionner_phase,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m1_abandonner_conversation",
            description="Clôt une conversation vocale abandonnée avant la phase 5, proprement tracée au registre.",
            parametres={
                "type": "object",
                "properties": {
                    "conversation": _CONVERSATION,
                    "horodatage": {"type": "string"},
                },
                "required": ["conversation", "horodatage"],
                "additionalProperties": False,
            },
            fonction=abandonner_conversation,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m1_produire_digest",
            description="Produit le digest déterministe du registre anti-perte pour une date de référence donnée.",
            parametres={
                "type": "object",
                "properties": {"date_reference": {"type": "string"}},
                "required": ["date_reference"],
                "additionalProperties": False,
            },
            fonction=produire_digest,
            # §9.5 M1 (appels manqués, rappels, messages urgents) : digest du registre anti-perte.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m1_emettre_notification",
            description=(
                "Envoie un message à un client ou un système externe via le bus de notification. "
                "Action externe réversible : en mode ombre, attend une approbation humaine."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "canal": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["canal", "message"],
                "additionalProperties": False,
            },
            fonction=emettre_notification,
            autonomie=Autonomie.T2,
        ),
    )
