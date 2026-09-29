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
l'inscription au registre) : c'est ainsi qu'il atteint M2, qui n'est pas un outil que l'agent M1 voit. M2 le
consomme (`m1.lead_qualifie`, PLAN T2.1-b) : il ne lui est jamais appelé directement.

Qualification par conversation (PLAN T2.1-b, `conversation.py`) : quand le profil d'entreprise déclare une fenêtre
(`fenetre_conversation_minutes`), les messages d'un même client dans cette fenêtre se rassemblent, par du code, et le
lead naît quand service et ville sont connus, un seul par conversation ouverte. Sans fenêtre déclarée, la
qualification reste message par message et la réponse le dit (`conversation.verdict`). Ce qui est demandé au client
est un brouillon (`brouillon_reponse`) : il ne part que par `m1_emettre_notification` (N4), après approbation.

Qualification complète (PLAN T4.4, `docs/departements/M1-canaux.md` §9) : le rejet nomme chaque champ manquant
(`champs_manquants`) ; les questions obligatoires du service viennent du profil d'entreprise (`questions.py`, jamais du
code) ; la demande de photos reste fermée tant que la politique « photos » n'est pas validée (`photos.py`) ; le score de
lead est calculé par règles avec les poids du profil (`score.py`) et reste au registre de M1, le contrat v2 est intact ;
une conversation ouverte a une prochaine action datée au registre (`suivi.py`), de l'heure de la plateforme et de la fin
de la fenêtre, jamais d'une horloge.

Plaintes, urgences et transfert humain (PLAN T4.5, `docs/departements/M1-canaux.md` §10) : AVANT toute qualification,
les règles (`plaintes.py`, vocabulaire du profil d'entreprise) reconnaissent une plainte ou une urgence de sécurité
dans le texte filtré. La plainte prime : un tel message n'ouvre jamais de lead ; il ouvre un TRANSFERT à un humain
(`transferts.py`), au registre, qui devient une attente lisible dans « À voir » (`attentes()`) jusqu'à ce qu'une
personne le clôt (`m1_clore_transfert`, décision humaine). `m1_transferer` et `m1_escalader_plainte` sont la voie de
l'agent (jugement, ou type hors plainte) ; ils écrivent la même chose, en N2 (tâche interne : jamais refusés faute
d'affaire liée). Aucune réponse n'est envoyée : le gabarit empathique est un brouillon, l'envoi reste
`m1_emettre_notification` (N4).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from opsys import approbations, evenements, identite, stockage, taxonomie
from opsys import contexte as contexte_appel
from opsys.outils import Autonomie, Niveau, Outil
from opsys.stockage.schema import APPROBATIONS

from . import (
    adaptateurs,
    consentement,
    contrats,
    conversation,
    digest,
    garde_fou,
    phases_voix,
    photos,
    plaintes,
    provenance,
    qualification,
    questions,
    reception,
    score,
    suivi,
    transferts,
    verdicts,
)
from .phases_voix import TransitionInterdite
from .registre import Registre

_CANAUX = ("telephone", "courriel", "formulaire", "texte")
_DEPARTEMENT = "m01-front-office"
_NOM_REGISTRE = "principal"

# La politique Loi 25 « photos » (T3), dont M1 lit le statut : dérivé de __file__, jamais du répertoire courant (même
# discipline que M3). parents[4] depuis src/m1_front_office/outils.py atteint la racine du dépôt.
_CHEMIN_POLITIQUE_PHOTOS = (
    Path(__file__).resolve().parents[4]
    / "docs" / "compliance" / "politiques" / "POLITIQUE-photos-non-contractuelles.md"
)


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


def _politique_photos_texte() -> str:
    """Le texte réel de la politique « photos », seul point de M1 à toucher le système de fichiers pour cette garde
    (`photos.py` reste pur). Un fichier absent ou illisible rend une chaîne vide : statut absent, donc fermée."""
    try:
        return _CHEMIN_POLITIQUE_PHOTOS.read_text(encoding="utf-8")
    except OSError:
        return ""


def _questions_du_service(service: str | None, contenu: str) -> questions.EtatQuestions:
    """L'état des questions obligatoires du service, lues du profil d'entreprise (jamais dans le code)."""
    if service is None:
        return questions.evaluer(None, (), None, contenu)
    liste, verdict = taxonomie.charger_questions_du_service(service)
    return questions.evaluer(service, liste, verdict, contenu)


def _demandes_de_photos(etat: questions.EtatQuestions) -> tuple[dict[str, Any] | None, tuple[Any, ...]]:
    """`(bloc photos de la réponse, demandes que M1 peut proposer)`. Une demande de photos déclarée par le profil reste
    FERMÉE tant que la politique « photos » n'est pas validée : aucune ne sort, le bloc dit pourquoi."""
    if not etat.photos:
        return None, ()
    verdict = photos.verifier_demande_autorisee(_politique_photos_texte())
    codes = [q.code for q in etat.photos]
    if verdict is not None:
        return {"statut": "fermee", "verdict": verdict, "questions": codes}, ()
    return {"statut": "ouverte", "questions": codes}, etat.photos


def _qualifier_la_conversation(
    reg: Registre,
    *,
    ouverte: conversation.ConversationOuverte,
    fenetre_minutes: int,
    canal: str,
    source: str | None,
    conversation_id: str,
    signal_id: str,
    horodatage: str,
    etabli: dict[str, Any],
    contenu: str,
    libelles: dict[str, str],
    lead_id: str | None,
    nouveau_lead: bool,
) -> dict[str, Any]:
    """Ce que M1 ajoute à la réponse d'une conversation à fenêtre, par des règles (rien n'est laissé au modèle) :
    les questions du service (profil), la demande de photos (fermée sans politique validée), le score (poids du
    profil), le brouillon de ce qui reste à demander, et la PROCHAINE ACTION datée, inscrite au registre avec le score
    (`suivi_conversation`, une ligne par message). Rien n'est envoyé.

    `etabli` : ce que la conversation établit (`qualification.diagnostiquer`, ou celui du lead quand il existe).
    `contenu` : tous les messages rassemblés. Tant qu'un champ du lead manque, le brouillon ne demande que celui-là ;
    ensuite, les questions du service, puis les photos (seulement au message qui qualifie le lead, ou avec une
    question encore sans réponse : jamais pour une demande photos seule qui reviendrait à chaque message).
    """
    etat_questions = _questions_du_service(etabli["service"], contenu)
    bloc_photos, photos_ouvertes = _demandes_de_photos(etat_questions)
    manque = qualification.champs_manquants(etabli)
    fragments: dict[str, Any] = {"questions": etat_questions.bloc()}
    if bloc_photos is not None:
        fragments["photos"] = bloc_photos
    if manque or etat_questions.restantes or (nouveau_lead and photos_ouvertes):
        fragments.update(conversation.proposer_precisions(
            etabli, libelles, ouverte.retire, etat_questions.restantes, photos_ouvertes))

    poids, verdict_poids = taxonomie.charger_poids_score_lead()
    if poids is None:
        fragments["score"] = score.sans_poids(verdict_poids)
    else:
        repondues, attendues = len(etat_questions.repondues), len(etat_questions.repondues) + len(
            etat_questions.restantes)
        champs = len(qualification.CHAMPS_DU_LEAD)
        fragments["score"] = score.calculer(
            urgence=etabli["urgence_declaree"], zone=etabli["ville"] is not None,
            elements_etablis=champs - len(manque) + repondues, elements_attendus=champs + attendues, poids=poids)

    ouverture = conversation.instant_iso(ouverte.ouverture or horodatage)
    action = suivi.prochaine_action(
        manque, [q.code for q in etat_questions.restantes], ouverte.retire, horodatage,
        conversation.expiration(ouverture, fenetre_minutes))
    fragments["prochaine_action"] = action
    fragments["suivi_ligne_id"] = reg.ajouter(suivi.ligne(
        canal=canal, source=source, conversation_id=conversation_id, signal_id=signal_id, horodatage=horodatage,
        ouverte_le=ouverture, connu=conversation.connu(etabli), champs_manquants=manque,
        questions=fragments["questions"], score=fragments["score"], action=action, lead_id=lead_id))
    return fragments


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
    fenetre_minutes: int | None = None,
) -> dict[str, Any]:
    # 0. Configuration avant tout effet : sans service déclaré par l'instance, on refuse ici,
    #    avant d'écrire au registre (fail-closed, le message dit quoi configurer).
    services, verdict_profil = taxonomie.charger_services()
    if verdict_profil is not None:
        raise ValueError(f"{verdict_profil['code']}: {verdict_profil['detail']}")

    reg = _obtenir_registre()
    lignes = reg.lire()

    # 0 bis. Conversation ouverte (seulement si l'instance déclare une fenêtre) : lue AVANT d'écrire ce message,
    #        pour savoir si la conversation est déjà qualifiée et ce qu'elle a rassemblé. Les messages qu'un transfert
    #        à un humain couvre (une plainte) ne s'y rassemblent jamais : la plainte prime, même une fois le transfert
    #        clos, et ses mots n'ouvriront pas un lead plus tard.
    ouverte = None
    if fenetre_minutes is not None:
        exclus = transferts.signaux_exclus(lignes)
        qualifiables = [
            ligne for ligne in lignes
            if not (ligne.get("type_entree") == "signal" and ligne.get("signal_id") in exclus)
        ]
        ouverte = conversation.lire(qualifiables, conversation_id, horodatage, fenetre_minutes)

    # 1. Provenance : neutralise toute tentative d'injection AVANT tout traitement
    #    (M1-R-08 — un contenu externe n'est jamais fiable tel quel).
    contenu_filtre, sain = provenance.filtrer(contenu_brut)

    # 1 bis. Plainte ou urgence de sécurité (PLAN T4.5), sur le texte filtré et AVANT la qualification : elle prime.
    #        Un message reconnu, ou qui arrive dans une conversation dont un transfert est encore ouvert, n'ouvre
    #        jamais de lead : il est inscrit, rattaché à un transfert à un humain, et rien d'autre n'est décidé.
    signaux_plainte, verdict_signaux = taxonomie.charger_signaux_plainte()
    detection = plaintes.detecter(contenu_filtre, signaux_plainte, verdict_signaux)
    etats_transferts = transferts.lire(lignes)
    if detection.reconnu or transferts.ouverts_de(etats_transferts, conversation_id):
        return _transferer_le_message(
            reg, lignes, etats_transferts, detection, contenu_filtre=contenu_filtre, sain=sain, canal=canal,
            source=source, conversation_id=conversation_id, signal_id=signal_id, horodatage=horodatage,
            contact_canal=contact_canal, cle_session=cle_session, fenetre_minutes=fenetre_minutes)

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
    if ouverte is not None and ouverte.lead is not None:
        signal["rattache_au_lead"] = ouverte.lead["lead"]["lead_id"]
    ligne_id_signal = reg.ajouter(signal)

    # 2 bis. Conversation déjà qualifiée : un seul lead par conversation ouverte. Le message est inscrit (une ligne,
    #        rien n'est perdu) et rattaché au lead ; il n'en crée pas un second.
    if ouverte is not None and ouverte.lead is not None:
        return _avec_detection(_complement_de_conversation(
            reg, ouverte, fenetre_minutes, ligne_id_signal, sain, contenu_filtre, canal, source, conversation_id,
            signal_id, horodatage, zone_desservie, services, contact_canal,
        ), detection)

    # 3. Consentement : uniquement pertinent pour un canal vocal (M1-R-07).
    verdict_consentement = None
    if canal == "telephone":
        verdict_consentement = consentement.verifier_consentement(
            {"consentement_enregistrement": consentement_enregistrement},
            registre=reg,
            horodatage=horodatage,
        )

    # 4. Qualification par règles déterministes, zéro LLM, zéro ville inventée. Avec une fenêtre, elle porte sur
    #    tous les messages de la conversation ouverte (le lead naît quand service et ville sont connus) ; sinon, sur
    #    ce message seul.
    contenu_a_qualifier, identite_lead, signaux, diagnostic = contenu_filtre, None, [signal_id], None
    services_lus, ecartes = services, []
    if ouverte is not None:
        contenu_a_qualifier = conversation.contenu_rassemble(ouverte, contenu_filtre)
        signaux = conversation.signaux_rassembles(ouverte, signal_id)
        identite_lead = signaux[0]  # deux conversations de même texte n'ont pas le même lead
        # Le client qui répond « lequel ? » choisit : le service qu'il nomme seul remplace ceux qu'il avait listés.
        services_lus = conversation.services_retenus(
            [m["contenu_filtre"] for m in ouverte.messages] + [contenu_filtre], services)
        retenus = {un.code for un in services_lus}
        ecartes = [c for c in qualification.services_evoques(contenu_a_qualifier, services) if c not in retenus]
        diagnostic = qualification.diagnostiquer(contenu_a_qualifier, zone_desservie, services_lus, contact_canal)
    resultat_qualif = qualification.qualifier(
        contenu_a_qualifier, canal, conversation_id, zone_desservie,
        services=services_lus, source=source, utm=utm, campagne=campagne, contact_canal=contact_canal,
        identite_lead=identite_lead,
    )
    if "verdict" in resultat_qualif:
        reponse_precisions: dict[str, Any] = {
            "etape": "qualification",
            "accepte": True,
            "signal_ligne_id": ligne_id_signal,
            "provenance_saine": sain,
            "consentement": verdict_consentement,
            "qualifie": False,
            "verdict_qualification": resultat_qualif["verdict"],
            "champs_manquants": resultat_qualif["champs_manquants"],
            "decision": "DEMANDER_PRECISIONS",
        }
        if ouverte is not None:
            reponse_precisions["conversation"] = conversation.decrire(
                ouverte, horodatage, fenetre_minutes, signaux, diagnostic, ecartes)
            reponse_precisions.update(_qualifier_la_conversation(
                reg, ouverte=ouverte, fenetre_minutes=fenetre_minutes, canal=canal, source=source,
                conversation_id=conversation_id, signal_id=signal_id, horodatage=horodatage, etabli=diagnostic,
                contenu=contenu_a_qualifier, libelles={un.code: un.libelle for un in services}, lead_id=None,
                nouveau_lead=False))
        return _avec_detection(reponse_precisions, detection)

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
    if ouverte is not None:
        lead_emis["signaux_rassembles"] = signaux
        if ecartes:
            lead_emis["services_ecartes"] = ecartes
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
    if ouverte is not None:
        reponse["conversation"] = conversation.decrire(
            ouverte, horodatage, fenetre_minutes, signaux, diagnostic, ecartes)
        # Le lead est complet et part chez M2 ; ce que le service demande encore est un brouillon, jamais envoyé.
        reponse.update(_qualifier_la_conversation(
            reg, ouverte=ouverte, fenetre_minutes=fenetre_minutes, canal=canal, source=source,
            conversation_id=conversation_id, signal_id=signal_id, horodatage=horodatage, etabli=diagnostic,
            contenu=contenu_a_qualifier, libelles={un.code: un.libelle for un in services},
            lead_id=resultat_qualif["lead_id"], nouveau_lead=True))
    return _avec_detection(reponse, detection)


# ---------------------------------------------------------------------------
# Plaintes, urgences et transferts à un humain (PLAN T4.5)
# ---------------------------------------------------------------------------

_ROLES_HUMAINS = frozenset({identite.Role.ADMIN.value, identite.Role.NATHAN_OWNER.value})
_VOIE_APPAREIL = "appareil"
_VOIE_APPROBATION = "approbation"
_TYPES_AVEC_GABARIT = (plaintes.TYPE_PLAINTE, plaintes.TYPE_URGENCE)
_RAISON_AUTRE = "autre"
_RAISONS = (*plaintes.CATEGORIES, _RAISON_AUTRE)

_CONSIGNE_PLAINTE = (
    "Une plainte est reconnue : elle est escaladée à une personne (transfert ouvert au registre, attente « À voir »), "
    "aucun lead n'est ouvert. N'écris pas toi-même au client, ne promets rien, ne reconnais aucun tort, ne donne aucun "
    "avis. Si `brouillon_reponse` est un texte, c'est la réponse à proposer avec `m1_emettre_notification` : une "
    "personne doit l'approuver, ne dis jamais qu'elle est partie. Sinon `sans_brouillon` dit pourquoi. Dis à une "
    "personne qu'un transfert est ouvert."
)
_CONSIGNE_URGENCE = (
    "Une urgence de sécurité est reconnue et escaladée tout de suite à une personne (transfert ouvert, attente "
    "« À voir »), aucun lead n'est ouvert. Ne donne AUCUN conseil de sécurité, ne promets AUCUNE intervention, "
    "n'écris pas toi-même au client. Si `brouillon_reponse` est un texte, il ne dit que le signalement : propose-le "
    "avec `m1_emettre_notification` (approbation). Dis-le tout de suite à une personne."
)
_CONSIGNE_EN_COURS = (
    "Cette conversation a un transfert ouvert : ce message y est rattaché, aucun lead ne s'ouvre. Ne réponds pas "
    "toi-même au client, ne promets rien. Si une personne doit savoir quelque chose de plus, dis-le dans ta réponse "
    "finale."
)
_CONSIGNE_TRANSFERT = (
    "Le transfert est ouvert au registre et attend une personne (attente « À voir »). Ne dis pas qu'il est traité : "
    "seule une personne le clôt. N'écris pas toi-même au client."
)


def _avec_detection(reponse: dict[str, Any], detection: plaintes.Detection) -> dict[str, Any]:
    """La réponse, avec le bloc `plainte` quand les règles n'ont PAS pu s'appliquer (vocabulaire à configurer ou
    invalide) : son absence ne dit jamais « rien reconnu » quand la détection n'a pas tourné, et le verdict dit où
    l'écrire."""
    if detection.statut in (plaintes.STATUT_NON_CONFIGURE, plaintes.STATUT_PROFIL_INVALIDE):
        reponse["plainte"] = detection.bloc()
    return reponse


def _contact_du_message(
    contact_canal: dict[str, str] | None, contenu_filtre: str
) -> tuple[dict[str, str] | None, str | None]:
    """`(contact, source)` : l'identité que la plateforme a vérifiée (`canal`), sinon ce que le client a écrit
    (`texte`), sinon rien. Le transfert le porte à part : c'est ainsi que la personne sait qui rappeler."""
    if contact_canal:
        return dict(contact_canal), "canal"
    ecrit = qualification.contact_du_texte(contenu_filtre)
    return (ecrit, "texte") if ecrit else (None, None)


def _bloc_transfert(etat: transferts.EtatTransfert, *, nouveau: bool) -> dict[str, Any]:
    """Le bloc `transfert` d'une réponse. Le détail du verdict « destinataire à configurer » (long) n'est dit qu'à
    l'ouverture ; ensuite, son code suffit (`m1_lire_transfert` rend le détail)."""
    ouverture = etat.ouverture
    verdict = ouverture["verdict_destinataire"]
    if verdict is not None and not nouveau:
        verdict = {"code": verdict["code"]}
    return {
        "transfert_id": etat.identifiant,
        "type_transfert": ouverture["type_transfert"],
        "niveau": ouverture["niveau"],
        "statut": "ouvert" if etat.ouvert else "clos",
        "nouveau": nouveau,
        "destinataire": ouverture["destinataire"],
        "verdict_destinataire": verdict,
    }


def _decision_de_transfert(type_transfert: str, nouveau: bool) -> str:
    if not nouveau:
        return "TRANSFERT_EN_COURS"
    return "ESCALADE_URGENCE" if type_transfert == plaintes.TYPE_URGENCE else "ESCALADE_PLAINTE"


def _fermer_le_suivi(
    reg: Registre, lignes: list[dict[str, Any]], *, canal: str, source: str | None, conversation_id: str,
    signal_id: str, horodatage: str,
) -> None:
    """Une conversation dont un transfert vient de s'ouvrir n'est plus « à suivre » par M1 : une personne l'a. Sa
    dernière ligne de suivi (T4.4), si elle est encore ouverte, est fermée (motif `transfert_humain`) : le digest ne la
    compte pas parmi les conversations « sans suivi », puisqu'une attente de « À voir » la porte. Sans ligne de suivi
    ouverte, rien n'est écrit."""
    derniere = None
    for ligne in lignes:
        if ligne.get("type_entree") == suivi.TYPE_SUIVI and ligne.get("conversation_id") == conversation_id:
            derniere = ligne
    if derniere is None or derniere.get("statut") != suivi.STATUT_OUVERTE:
        return
    reg.ajouter(suivi.ligne_de_fermeture(
        canal=canal, source=source, conversation_id=conversation_id, signal_id=signal_id, horodatage=horodatage,
        ouverte_le=derniere["ouverte_le"], motif=suivi.MOTIF_TRANSFERT))


def _transferer_le_message(
    reg: Registre,
    lignes: list[dict[str, Any]],
    etats: list[transferts.EtatTransfert],
    detection: plaintes.Detection,
    *,
    contenu_filtre: str,
    sain: bool,
    canal: str,
    source: str | None,
    conversation_id: str,
    signal_id: str,
    horodatage: str,
    contact_canal: dict[str, str] | None,
    cle_session: str | None,
    fenetre_minutes: int | None,
) -> dict[str, Any]:
    """Un message reconnu comme plainte ou urgence de sécurité, ou reçu dans une conversation dont un transfert est
    encore ouvert : il est inscrit, rattaché à un transfert, et n'ouvre JAMAIS de lead (la plainte prime).

    - Reconnu, et aucun transfert ouvert de CE type : un transfert s'ouvre (`urgence` dès qu'une urgence de sécurité est
      reconnue, sinon `plainte`), résumé composé par le code, destinataire lu du profil (absent : « à configurer »).
    - Sinon : le message est rattaché au transfert ouvert (la personne le relit avec `m1_lire_transfert`).

    Un refus de la préparation ne peut pas se produire ici (aucun résumé d'agent, message présent) ; s'il se produisait,
    il lèverait plutôt que de perdre une plainte en silence (rien ne serait écrit, l'appelant peut rejouer)."""
    type_detecte = detection.type_transfert
    ouverts = transferts.ouverts_de(etats, conversation_id)
    du_type = [e for e in ouverts if e.ouverture["type_transfert"] == type_detecte] if type_detecte else []
    nouvelle: dict[str, Any] | None = None
    if type_detecte is not None and not du_type:
        contact, contact_source = _contact_du_message(contact_canal, contenu_filtre)
        destinataire, verdict_destinataire = taxonomie.charger_destinataire_du_transfert(type_detecte)
        nouvelle, refus = transferts.preparer_ouverture(
            lignes, type_transfert=type_detecte, categories=detection.categories, termes=detection.termes,
            declenche_par=transferts.DECLENCHE_PAR_REGLES, canal=canal, source=source, conversation_id=conversation_id,
            message_courant={"signal_id": signal_id, "horodatage": horodatage, "contenu_filtre": contenu_filtre},
            contact=contact, contact_source=contact_source, destinataire=destinataire,
            verdict_destinataire=verdict_destinataire, fenetre_minutes=fenetre_minutes,
        )
        if nouvelle is None:
            raise ValueError(f"{refus['code']}: {refus['detail']}" if refus else "transfert non préparé")
        etat = transferts.EtatTransfert(nouvelle, None, ())
    else:
        etat = (du_type or ouverts)[0]
    signal: dict[str, Any] = {
        "type_entree": "signal",
        "canal": canal,
        "conversation_id": conversation_id,
        "signal_id": signal_id,
        "horodatage": horodatage,
        "contenu_filtre": contenu_filtre,
        "provenance_saine": sain,
        transferts.MARQUE: etat.identifiant,
    }
    if source is not None:
        signal["source"] = source
    ligne_id_signal = reg.ajouter(signal)
    ligne_id_transfert = reg.ajouter(nouvelle) if nouvelle is not None else None
    if nouvelle is not None:
        _fermer_le_suivi(reg, lignes, canal=canal, source=source, conversation_id=conversation_id,
                         signal_id=signal_id, horodatage=horodatage)
    type_courant = etat.ouverture["type_transfert"]
    reponse: dict[str, Any] = {
        "etape": "transfert",
        "accepte": True,
        "signal_ligne_id": ligne_id_signal,
        "provenance_saine": sain,
        "consentement": None,
        "qualifie": False,
        "decision": _decision_de_transfert(type_courant, nouvelle is not None),
        "plainte": detection.bloc(),
        "transfert": _bloc_transfert(etat, nouveau=nouvelle is not None),
    }
    if cle_session is not None:
        reponse["cle_session"] = cle_session
    if ligne_id_transfert is not None:
        reponse["transfert_ligne_id"] = ligne_id_transfert
        if type_courant in _TYPES_AVEC_GABARIT:
            reponse.update(plaintes.brouillon(
                type_courant, etat.ouverture["categories"], transferts.retire(lignes, conversation_id)))
    if nouvelle is None:
        reponse["consigne"] = _CONSIGNE_EN_COURS
    else:
        reponse["consigne"] = _CONSIGNE_URGENCE if type_courant == plaintes.TYPE_URGENCE else _CONSIGNE_PLAINTE
    return reponse


def _ouvrir_pour_l_agent(
    type_transfert: str, raison: str | None, canal: str, expediteur: str, resume: str | None
) -> dict[str, Any]:
    """Ouvre un transfert à la demande de l'AGENT (un jugement que les règles n'ont pas fait, ou un type hors plainte).

    L'agent recopie le canal et l'expéditeur (comme pour un message reçu) ; le code en tire la conversation, le contact
    (celui que la plateforme a vérifié) et ce qu'elle porte au registre. Une conversation sans aucun message est refusée
    (rien à transférer). Jamais deux transferts ouverts du même type pour une conversation : le second appel rend le
    premier. Une plainte dont le texte évoque une urgence de sécurité devient une `urgence` (on ne sous-classe jamais).
    Le transfert est daté du dernier message du client, heure de la plateforme : aucune horloge.
    """
    correspondant, contact = reception.correspondant_du_canal(canal, expediteur)
    fenetre, verdict_fenetre = taxonomie.charger_fenetre_conversation()
    if verdict_fenetre is not None and verdict_fenetre["code"] != taxonomie.VERDICT_FENETRE_NON_CONFIGUREE:
        # Une valeur cassée n'est jamais lue comme une valeur absente : refus, rien n'est écrit (comme la réception).
        raise ValueError(f"{verdict_fenetre['code']}: {verdict_fenetre['detail']}")
    canal_contrat = reception.CANAL_DU_CONTRAT[canal]
    conversation_id = reception.identifiant_de_conversation(canal, correspondant)
    reg = _obtenir_registre()
    lignes = reg.lire()
    messages = transferts.messages_de(lignes, conversation_id)
    exclus = transferts.signaux_exclus(lignes)
    libres = [m for m in messages if m["signal_id"] not in exclus] or messages
    signaux, verdict_signaux = taxonomie.charger_signaux_plainte()
    detection = plaintes.detecter(
        "\n".join(m["contenu_filtre"] for m in libres[-transferts.MESSAGES_MAX:]), signaux, verdict_signaux)
    categories: tuple[str, ...] = ()
    if type_transfert in _TYPES_AVEC_GABARIT:
        demandees = set(detection.categories)
        if raison is not None and raison != _RAISON_AUTRE:
            demandees.add(raison)
        categories = tuple(c for c in plaintes.CATEGORIES if c in demandees)
        type_transfert = plaintes.TYPE_URGENCE if (
            type_transfert == plaintes.TYPE_URGENCE or plaintes.CATEGORIE_URGENCE in categories
        ) else plaintes.TYPE_PLAINTE
    deja = transferts.ouverts_de(transferts.lire(lignes), conversation_id, type_transfert)
    if deja:
        return {"accepte": True, "resultat": {
            "deja_ouvert": True, "transfert": _bloc_transfert(deja[0], nouveau=False), "envoye": False,
            "consigne": _CONSIGNE_EN_COURS}}
    destinataire, verdict_destinataire = taxonomie.charger_destinataire_du_transfert(type_transfert)
    ligne, refus = transferts.preparer_ouverture(
        lignes, type_transfert=type_transfert, categories=categories,
        termes={c: t for c, t in detection.termes.items() if c in categories},
        declenche_par=transferts.DECLENCHE_PAR_AGENT, canal=canal_contrat, source=canal,
        conversation_id=conversation_id, message_courant=None, contact=contact, contact_source="canal",
        destinataire=destinataire,
        verdict_destinataire=verdict_destinataire, fenetre_minutes=fenetre, resume_agent=resume,
        resume_fourni=resume is not None,
    )
    if ligne is None:
        return {"accepte": False, "verdict": refus}
    ligne_id = reg.ajouter(ligne)
    _fermer_le_suivi(reg, lignes, canal=canal_contrat, source=canal, conversation_id=conversation_id,
                     signal_id=ligne["signal_id"], horodatage=ligne["horodatage"])
    etat = transferts.EtatTransfert(ligne, None, ())
    resultat: dict[str, Any] = {
        "deja_ouvert": False,
        "transfert": _bloc_transfert(etat, nouveau=True),
        "transfert_ligne_id": ligne_id,
        "resume_origine": ligne["resume_origine"],
    }
    if type_transfert in _TYPES_AVEC_GABARIT:
        resultat.update(plaintes.brouillon(type_transfert, categories, transferts.retire(lignes, conversation_id)))
        resultat["consigne"] = _CONSIGNE_URGENCE if type_transfert == plaintes.TYPE_URGENCE else _CONSIGNE_PLAINTE
    else:
        resultat["envoye"] = False
        resultat["consigne"] = _CONSIGNE_TRANSFERT
    return {"accepte": True, "resultat": resultat}


def transferer(type_transfert: str, canal: str, expediteur: str, resume: str | None = None) -> dict[str, Any]:
    """Transfère une conversation à un humain : type fermé, résumé OBLIGATOIRE (composé par le code si `resume` est
    absent ; fourni, il est contrôlé : non vide, sans contact, garde-fou). Tâche interne (N2) : n'écrit rien au
    client."""
    return _ouvrir_pour_l_agent(type_transfert, None, canal, expediteur, resume)


def escalader_plainte(raison: str, canal: str, expediteur: str, resume: str | None = None) -> dict[str, Any]:
    """Escalade une plainte que l'agent juge telle (les règles n'ont pas déclenché) : `raison` de l'ensemble fermé des
    catégories (`autre` : aucune). Même transfert que celui des règles, plus le brouillon empathique (jamais envoyé)."""
    return _ouvrir_pour_l_agent(plaintes.TYPE_PLAINTE, raison, canal, expediteur, resume)


def _decision_approuvee_en_cours(cnx: Any, nom_outil: str, arguments: dict[str, Any]) -> tuple[str, str] | None:
    """`(personne, rôle)` de l'humain qui a APPROUVÉ la demande que cet appel exécute, sinon `None`.

    `approbations.decider` réserve la demande (`en_attente` -> `en_cours`, avec `decide_par` et `decide_role`) puis
    exécute l'outil avec les arguments EXACTS enregistrés, dans la même transaction : cet appel EST une décision humaine
    si et seulement si une demande `en_cours` de cet outil, de ce département, porte exactement ces arguments et un
    approbateur de rôle humain toujours actif. Un agent ne peut pas fabriquer une telle ligne (il ne peut que créer une
    demande `en_attente`). Même garde que M10 (`m10_clore_signal`). Lecture seule."""
    if cnx is None:
        return None
    lignes = cnx.execute(
        select(APPROBATIONS.c.arguments, APPROBATIONS.c.decide_par, APPROBATIONS.c.decide_role).where(
            APPROBATIONS.c.statut == "en_cours",
            APPROBATIONS.c.outil == nom_outil,
            APPROBATIONS.c.departement == _DEPARTEMENT,
        )
    ).all()
    for arguments_enregistres, decide_par, decide_role in lignes:
        if not decide_par or decide_role not in _ROLES_HUMAINS:
            continue
        if json.loads(arguments_enregistres) != arguments:
            continue
        personne = identite.personne_active(cnx, decide_par)
        if personne is not None and decide_role in personne.roles:
            return decide_par, decide_role
    return None


def _verdict_refus(code: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "verdict": verdicts.construire_verdict(code, detail=detail)}


def _acteur_humain(nom_outil: str, arguments: dict[str, Any]) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """Qui décide : `({par, role, voie}, None)` si c'est un humain identifié, sinon `(None, réponse de refus)`.

    Clore un transfert est une décision de personne : un agent ne l'a jamais seul (la file « À voir » ne se viderait
    plus d'elle-même). Deux voies, jamais une troisième, jamais un texte de modèle ni un argument :
    1. un appel d'appareil dont l'identité (posée par le core d'après un jeton vérifié) est CONFIRMÉE en base à
       l'instant même (personne active portant encore ce rôle), de rôle `admin` ;
    2. l'exécution d'une demande qu'un humain vient d'approuver dans la file d'approbation.
    Tout le reste est refusé, y compris un appel d'agent dans un mode où l'approbation n'est pas requise."""
    cnx = stockage.connexion_courante()
    appelante = contexte_appel.identite_appelante()
    if appelante is not None:
        confirmee = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
        if confirmee is None:
            return None, _verdict_refus(
                "REJ-HUMAIN-IDENTITE-INVALIDE",
                f"personne {appelante.personne!r} inconnue, inactive, ou ne porte plus le rôle {appelante.role!r} du "
                "jeton d'appareil (ou identité non vérifiable hors transaction)",
            )
        if confirmee.role != identite.Role.ADMIN.value:
            return None, _verdict_refus(
                "REJ-HUMAIN-ROLE-INSUFFISANT", "cette décision est réservée au rôle admin depuis un appareil")
        return {"par": confirmee.personne, "role": confirmee.role, "voie": _VOIE_APPAREIL}, None
    approbateur = _decision_approuvee_en_cours(cnx, nom_outil, arguments)
    if approbateur is not None:
        return {"par": approbateur[0], "role": approbateur[1], "voie": _VOIE_APPROBATION}, None
    return None, _verdict_refus(
        "REJ-HUMAIN-REQUIS",
        "clore un transfert est une décision humaine : un agent ne peut pas la prendre seul. Fais-la depuis l'app "
        "admin (jeton d'appareil), ou propose-la et attends qu'une personne approuve la demande dans la console "
        "OPSYS. Ne la présente pas comme faite.",
    )


def _horodatage_faisant_foi(horodatage: str) -> str:
    """Pendant un appel d'appareil idempotent, l'heure de RÉCEPTION du serveur fait foi, jamais l'horloge de l'appareil
    ni l'`horodatage` fourni (même patron que M10 et `m4_pointer`)."""
    reception_serveur = contexte_appel.horodatage_reception()
    return reception_serveur.recu_le.isoformat() if reception_serveur is not None else horodatage


def _etat_du_transfert(lignes: list[dict[str, Any]], transfert_id: str) -> transferts.EtatTransfert | None:
    return next((e for e in transferts.lire(lignes) if e.identifiant == transfert_id), None)


def lire_transfert(transfert_id: str) -> dict[str, Any]:
    """Ce qu'une personne lit d'un transfert : résumé, destinataire, contact, messages, et le brouillon de réponse d'une
    plainte ou d'une urgence encore ouverte (jamais envoyé). Lecture seule."""
    reg = _obtenir_registre()
    lignes = reg.lire()
    etat = _etat_du_transfert(lignes, transfert_id)
    if etat is None:
        return _verdict_refus("REJ-TRANSFERT-INCONNU", f"aucun transfert {transfert_id!r} au registre")
    resultat = transferts.vue(etat, lignes)
    retire = transferts.retire(lignes, etat.ouverture["conversation_id"])
    resultat["client_retire_des_messages"] = retire
    type_transfert = etat.ouverture["type_transfert"]
    if etat.ouvert and type_transfert in _TYPES_AVEC_GABARIT:
        resultat.update(plaintes.brouillon(type_transfert, etat.ouverture["categories"], retire))
    return {"accepte": True, "resultat": resultat}


def clore_transfert(transfert_id: str, motif: str, horodatage: str) -> dict[str, Any]:
    """Une PERSONNE clôt un transfert ouvert, avec son motif : il sort de la file « À voir ». Décision humaine : refusée
    à un agent qui n'a pas passé par l'approbation ou par un jeton d'appareil `admin`."""
    acteur, refus = _acteur_humain(
        "m1_clore_transfert", {"transfert_id": transfert_id, "motif": motif, "horodatage": horodatage})
    if acteur is None:
        return refus or _verdict_refus("REJ-HUMAIN-REQUIS", "acteur humain introuvable")
    reg = _obtenir_registre()
    etat = _etat_du_transfert(reg.lire(), transfert_id)
    if etat is None:
        return _verdict_refus("REJ-TRANSFERT-INCONNU", f"aucun transfert {transfert_id!r} au registre")
    if not etat.ouvert:
        return _verdict_refus("REJ-TRANSFERT-DEJA-CLOS", f"le transfert {transfert_id!r} est déjà clos")
    quand = _horodatage_faisant_foi(horodatage)
    verdict = transferts.verifier_cloture(motif, quand)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    ligne_id = reg.ajouter(transferts.ligne_de_cloture(
        etat, par=acteur["par"], role=acteur["role"], voie=acteur["voie"], motif=motif, horodatage=quand))
    return {"accepte": True, "resultat": {
        "transfert_id": transfert_id, "statut": "clos", "clos_par": acteur["par"], "role": acteur["role"],
        "voie": acteur["voie"], "clos_le": quand, "ligne_id": ligne_id}}


def _complement_de_conversation(
    reg: Registre,
    ouverte: conversation.ConversationOuverte,
    fenetre_minutes: int,
    ligne_id_signal: str,
    sain: bool,
    contenu_filtre: str,
    canal: str,
    source: str | None,
    conversation_id: str,
    signal_id: str,
    horodatage: str,
    zone_desservie: list[str],
    services,
    contact_canal: dict[str, str] | None,
) -> dict[str, Any]:
    """Un message qui arrive dans une conversation DÉJÀ qualifiée : aucun second lead. Ce que le lead transmis à M2
    ne porte pas (une urgence, un autre service évoqué) est dit dans la réponse, pour qu'une personne le voie.

    L'urgence se cumule sur TOUS les messages de la conversation, avant et après le lead : `complement.urgence_declaree`
    est vraie quand la conversation la déclare et que le lead transmis ne la porte pas (le contrat v2 est gelé, il ne
    se met pas à jour). `services_evoques` et `autre_service_evoque` disent ce que CE message évoque. Les questions du
    service, le score et la prochaine action se recalculent sur toute la conversation (`_qualifier_la_conversation`)."""
    ligne_lead = ouverte.lead
    lead = ligne_lead["lead"]
    contenu = conversation.contenu_rassemble(ouverte, contenu_filtre)
    diagnostic = qualification.diagnostiquer(contenu_filtre, zone_desservie, services)
    cumul = qualification.diagnostiquer(contenu, zone_desservie, services, contact_canal)
    autres = [code for code in diagnostic["services_evoques"] if code != lead["service"]]
    # Ce que la conversation établit, c'est ce que le lead transmis porte (service, ville, contact) ; l'urgence
    # est cumulée.
    etabli = {
        **cumul, "service": lead["service"], "ville": lead["ville"], "contact": "canal" if contact_canal else "texte",
    }
    reponse: dict[str, Any] = {
        "etape": "conversation",
        "accepte": True,
        "signal_ligne_id": ligne_id_signal,
        "provenance_saine": sain,
        "consentement": None,
        "qualifie": True,
        "nouveau_lead": False,
        "lead": lead,
        "lead_ligne_id": ligne_lead["ligne_id"],
        "decision": "CONVERSATION_DEJA_QUALIFIEE",
        "complement": {
            "urgence_declaree": cumul["urgence_declaree"] and not lead["urgence_declaree"],
            "services_evoques": diagnostic["services_evoques"],
            "autre_service_evoque": bool(autres),
        },
        "conversation": conversation.decrire(
            ouverte, horodatage, fenetre_minutes, conversation.signaux_rassembles(ouverte, signal_id), etabli),
        "consigne": (
            "La conversation est déjà qualifiée : ce message est inscrit et rattaché à son lead, aucun second lead "
            "n'est créé. Si `complement.urgence_declaree` ou `complement.autre_service_evoque` est vrai, dis-le à "
            "une personne dans ta réponse finale : le lead transmis à M2 ne le porte pas."
        ),
    }
    reponse.update(_qualifier_la_conversation(
        reg, ouverte=ouverte, fenetre_minutes=fenetre_minutes, canal=canal, source=source,
        conversation_id=conversation_id, signal_id=signal_id, horodatage=horodatage, etabli=etabli, contenu=contenu,
        libelles={un.code: un.libelle for un in services}, lead_id=lead["lead_id"], nouveau_lead=False))
    return reponse


def _signal_deja_recu(reg: Registre, signal_id: str) -> dict[str, Any] | None:
    """La réponse déjà donnée à ce signal, ou `None` s'il est nouveau. Un message que la plateforme livre deux fois
    (reprise après panne, nouvel essai de l'agent) ne laisse pas une seconde ligne : exactement une par signal."""
    signal = lead = alerte = None
    leads_par_id: dict[str, dict[str, Any]] = {}
    lignes = reg.lire()
    for maillon in lignes:
        if maillon.get("type_entree") == "lead_emis" and isinstance(maillon.get("lead"), dict):
            leads_par_id[maillon["lead"].get("lead_id")] = maillon
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
    if signal.get(transferts.MARQUE) is not None:
        # Message reçu dans une plainte ou une urgence : il était rattaché à un transfert, il n'a jamais créé de lead.
        etat = next((e for e in transferts.lire(lignes) if e.identifiant == signal[transferts.MARQUE]), None)
        reponse = {
            "etape": "doublon", "accepte": True, "doublon": True, "signal_ligne_id": signal["ligne_id"],
            "qualifie": False, "decision": "TRANSFERT_EN_COURS",
        }
        if etat is not None:
            declencheur = etat.ouverture["signal_id"] == signal_id
            reponse["decision"] = _decision_de_transfert(etat.ouverture["type_transfert"], declencheur)
            reponse["transfert"] = _bloc_transfert(etat, nouveau=False)
        return reponse
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
    elif signal.get("rattache_au_lead") is not None and signal["rattache_au_lead"] in leads_par_id:
        # Message reçu après le lead de sa conversation : il y était rattaché, il n'a jamais créé de lead.
        ligne_lead = leads_par_id[signal["rattache_au_lead"]]
        reponse.update(
            qualifie=True, nouveau_lead=False, lead=ligne_lead["lead"], lead_ligne_id=ligne_lead["ligne_id"],
            decision="CONVERSATION_DEJA_QUALIFIEE",
        )
    return reponse


def _enregistrer_retrait(
    reg: Registre, message: reception.MessageRecu, fenetre_minutes: int | None = None
) -> dict[str, Any]:
    """Un client écrit STOP : le signal est inscrit (une ligne par signal), une alerte dit qu'il ne veut plus de
    messages, et rien n'est qualifié ni émis. Aucune réponse n'est proposée : le retrait s'applique tel quel
    (POLITIQUE-consentement-sms.md §4). Avec une fenêtre, l'alerte ferme aussi la conversation ouverte : ce qui a été
    écrit avant STOP n'est jamais qualifié, et la réponse dit combien de messages restent sans lead."""
    ouverte = None
    if fenetre_minutes is not None:
        ouverte = conversation.lire(reg.lire(), message.conversation_id, message.horodatage, fenetre_minutes)
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
    if ouverte is not None and ouverte.messages:
        # La conversation ouverte se ferme : sans cette ligne, elle resterait « ouverte, à suivre » pour toujours.
        reg.ajouter(suivi.ligne_de_fermeture(
            canal=message.canal_contrat, source=message.canal, conversation_id=message.conversation_id,
            signal_id=message.signal_id, horodatage=message.horodatage, ouverte_le=ouverte.ouverture,
            motif=suivi.MOTIF_RETRAIT))
    reponse = {
        "etape": "consentement",
        "accepte": True,
        "signal_ligne_id": ligne_signal,
        "alerte_ligne_id": ligne_alerte,
        "provenance_saine": sain,
        "qualifie": False,
        "decision": "RETRAIT_CONSENTEMENT",
        "consigne": "Le client se retire : n'envoie aucun message à ce correspondant, ne propose aucune réponse.",
    }
    if ouverte is not None:
        reponse["conversation"] = {
            "mode": "fenetre",
            "fenetre_minutes": fenetre_minutes,
            "fermee_par_retrait": True,
            "messages_non_qualifies": 0 if ouverte.lead is not None else len(ouverte.messages),
        }
    return reponse


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

    Refus (`ValueError`, rien d'écrit) : champ de plateforme invalide, service ou zone non déclarés par l'instance,
    fenêtre de conversation déclarée mais invalide. Sinon : un retrait (STOP) est inscrit sans être qualifié ; un
    message déjà reçu rend sa réponse sans rien écrire ; tout autre passe par `_traiter` (provenance → registre →
    qualification → lead → bus).

    Fenêtre de conversation (PLAN T2.1-b) : déclarée par le profil d'entreprise, elle rassemble les messages d'un même
    client (`conversation.py`) ; absente, la qualification reste message par message et `conversation.verdict` le dit,
    avec où la déclarer. Jamais une durée par défaut.
    """
    message = reception.preparer(canal, expediteur, message_id, recu_le, texte, objet)
    zone, verdict_zone = taxonomie.charger_zone_desservie()
    if verdict_zone is not None:
        raise ValueError(f"{verdict_zone['code']}: {verdict_zone['detail']}")
    _, verdict_profil = taxonomie.charger_services()
    if verdict_profil is not None:
        raise ValueError(f"{verdict_profil['code']}: {verdict_profil['detail']}")
    fenetre, verdict_fenetre = taxonomie.charger_fenetre_conversation()
    if verdict_fenetre is not None and verdict_fenetre["code"] != taxonomie.VERDICT_FENETRE_NON_CONFIGUREE:
        # Une valeur cassée n'est jamais lue comme une valeur absente : refus, rien n'est écrit.
        raise ValueError(f"{verdict_fenetre['code']}: {verdict_fenetre['detail']}")
    reg = _obtenir_registre()
    deja = _signal_deja_recu(reg, message.signal_id)
    if deja is not None:
        return deja
    if message.retrait:
        reponse = _enregistrer_retrait(reg, message, fenetre)
    else:
        reponse = _traiter(
            message.contenu, message.canal_contrat, message.conversation_id, message.signal_id, message.horodatage,
            list(zone), None, message.canal, None, None,
            contact_canal=message.contact, cle_session=message.cle_session, fenetre_minutes=fenetre,
        )
    if fenetre is None:
        reponse["conversation"] = {"mode": "message_par_message", "verdict": verdict_fenetre}
    return reponse


# ---------------------------------------------------------------------------
# Attentes du propriétaire (ADR-0009 §5, PLAN T4.5)
# ---------------------------------------------------------------------------
# Même mécanisme de découverte que `consommateurs()` (`opsys.departements.Departement.charger_attentes`) : fonction
# module-level, sans argument, appelée par `approbations.file_proprietaire` et par `m9_lister_demandes_approbation`
# (section « À voir » de l'app admin) DANS une transaction déjà ouverte.
def attentes() -> list[dict[str, Any]]:
    """Une attente par transfert à un humain encore OUVERT (plainte, urgence de sécurité, ou tout autre type), telle
    que le registre de M1 la dit AUJOURD'HUI : `transferts.attente`, sans donnée personnelle (ni contact ni texte du
    client).
    Le niveau règle l'ordre de la file (N5 : urgence de sécurité et menace juridique ; N4 : plainte, propriétaire ; N3 :
    le reste), puis l'ancienneté (heure de réception du message déclencheur). Lecture seule : ne crée ni ne clôt rien.
    L'attente disparaît quand une personne clôt le transfert (`m1_clore_transfert`) : sans cet outil elle ne se viderait
    jamais. Sans transfert au registre, aucune attente."""
    return [transferts.attente(etat) for etat in transferts.lire(_obtenir_registre().lire()) if etat.ouvert]


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
_CANAL_DU_CORE = {
    "type": "string",
    "enum": sorted(reception.CANAL_DU_CONTRAT),
    "description": "Canal du core, champ channel du bloc Message Context. Jamais deviné.",
}
_EXPEDITEUR = {
    "type": "string",
    "description": "Numéro E.164 (sms) ou adresse (courriel) du bloc Conversation info (sender), tel quel.",
}
_RESUME = {
    "type": ["string", "null"],
    "description": (
        "Optionnel : ton résumé. Absent, le code le compose. Sans téléphone ni courriel, sans prix, date, promesse "
        "ni aveu."
    ),
}
_TRANSFERT_ID = {"type": "string", "description": "Identifiant du transfert (tr-…), tel que rendu par l'outil."}


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
                "L'outil filtre la provenance, inscrit le signal au registre anti-perte (un message rejoué ne s'ajoute "
                "pas), reconnaît un retrait (STOP), qualifie par règles (service, ville de la zone, expéditeur comme "
                "contact) et transmet le lead à M2 par le bus. Avec une fenêtre de conversation déclarée, les messages "
                "du même client se rassemblent : un seul lead par conversation. Le code ajoute, sans modèle : les "
                "champs manquants, les questions du service écrites par l'entreprise, la demande de photos (fermée "
                "sans politique validée), le score (poids de l'entreprise, sinon « poids à configurer »), la "
                "prochaine action datée au registre, et un brouillon de ce qu'il reste à demander, jamais envoyé."
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
            nom="m1_transferer",
            description=(
                "Transfère une conversation à une personne (type fermé). Le résumé est obligatoire : omets `resume` "
                "et le code le compose ; fourni, il est contrôlé (non vide, sans téléphone ni courriel, sans prix, "
                "date, promesse ni aveu). N'écrit rien au client : le transfert attend une personne dans « À voir »."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "type_transfert": {"type": "string", "enum": list(transferts.TYPES)},
                    "canal": _CANAL_DU_CORE,
                    "expediteur": _EXPEDITEUR,
                    "resume": _RESUME,
                },
                "required": ["type_transfert", "canal", "expediteur"],
                "additionalProperties": False,
            },
            fonction=transferer,
            autonomie=Autonomie.T1,
            # T1 (écriture interne : registre) mais N2 « tâche interne » (ADR-0009 §4, automatique) et non le défaut
            # T1 -> N3. Trois raisons. (1) Le transfert ne fait rien d'externe et n'engage personne : il met une
            # conversation devant une personne, qui décide (ADR-0009 §4 : N2 = tâche interne, N3 = action externe à
            # faible risque ou modification non finale). (2) En N3, le mode ombre mettrait la CRÉATION de l'alerte
            # d'une plainte en attente d'approbation : la plainte ne serait visible de personne avant qu'on approuve
            # qu'elle existe. (3) Le garde du core (ADR-0010, N3+ exige une affaire liée à la session) REFUSERAIT
            # l'appel dans la session d'un client dont l'affaire n'est pas liée, donc la plainte d'un client inconnu
            # serait perdue. Même choix que `m1_recevoir_message_canal`. La réponse au client reste
            # `m1_emettre_notification` (N4) ; la clôture reste une décision humaine (`m1_clore_transfert`).
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m1_escalader_plainte",
            description=(
                "Escalade une plainte que tu juges telle (les règles n'ont pas déclenché) : `raison` de l'ensemble "
                "fermé (`autre` si aucune). Même transfert que celui des règles, résumé composé par le code ou "
                "contrôlé, plus un brouillon empathique jamais envoyé. Une urgence de sécurité : aucun conseil, "
                "aucune promesse."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "raison": {"type": "string", "enum": list(_RAISONS)},
                    "canal": _CANAL_DU_CORE,
                    "expediteur": _EXPEDITEUR,
                    "resume": _RESUME,
                },
                "required": ["raison", "canal", "expediteur"],
                "additionalProperties": False,
            },
            fonction=escalader_plainte,
            autonomie=Autonomie.T1,
            # N2, pour les mêmes raisons que `m1_transferer` : c'est le même transfert, ouvert par le jugement de
            # l'agent.
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m1_lire_transfert",
            description=(
                "Lit un transfert : résumé, destinataire (ou « à configurer »), contact, messages du client, et "
                "brouillon de réponse d'une plainte ou d'une urgence ouverte. Lecture seule."
            ),
            parametres={
                "type": "object",
                "properties": {"transfert_id": _TRANSFERT_ID},
                "required": ["transfert_id"],
                "additionalProperties": False,
            },
            fonction=lire_transfert,
            # §9.5 M1 mobile (admin) : plaintes, transferts, « prendre en charge » : lire le contexte d'un transfert.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m1_clore_transfert",
            description=(
                "Une PERSONNE clôt un transfert ouvert, avec son motif : il sort de « À voir ». Décision humaine : "
                "refusée à un agent seul. L'heure est celle du serveur pour un appel d'appareil."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "transfert_id": _TRANSFERT_ID,
                    "motif": {"type": "string", "description": "Ce qui a été fait, 10 à 500 caractères."},
                    "horodatage": {"type": "string", "description": "ISO-8601 avec fuseau"},
                },
                "required": ["transfert_id", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=clore_transfert,
            autonomie=Autonomie.T1,
            # N3 (le défaut de T1, écriture interne non finale) : en `ombre`, un agent qui la propose attend une
            # personne ; un appel d'appareil `admin` s'exécute « au départ » (ADR-0009 §4, addendum T1.4-h). L'outil
            # refuse lui-même tout appel qui n'est pas une décision humaine (`_acteur_humain`), même en `supervise`.
            # §9.5 M1 mobile (admin) : plaintes, transferts, « prendre en charge ».
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
