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

Formulaire d'un site et UTM (PLAN T4.17-e3, `docs/departements/M1-canaux.md` §13) : `formulaire` est un canal de
`m1_recevoir_message_canal` (l'adresse ou le numéro que le visiteur a écrit, jamais vérifiée) et le seul qui porte un
`utm`, les paramètres du lien que le visiteur a suivi. Ils sont validés comme M2 les valide (`contrats.utm_invalide`),
portés tels quels par le lead que le message fait naître, jamais devinés ni complétés. Un `utm` invalide, ou fourni
pour un canal sans lien (SMS, courriel, appel), est refusé avant toute écriture, avec un verdict qui dit quoi corriger
(`contrats.exiger_utm`). Quand un `utm` est fourni, la réponse dit s'il est porté par un lead (`utm.statut`) : un `utm`
qu'aucun lead ne porte ne disparaît jamais en silence.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from opsys import approbations, evenements, identite, stockage, taxonomie
from opsys import contexte as contexte_appel
from opsys.outils import Autonomie, Niveau, Outil
from opsys.stockage import lecture_m1
from opsys.stockage.maillons import copier_maillons_avec_metadonnees

from . import (
    adaptateurs,
    consentement,
    contrats,
    conversation,
    digest,
    garde_fou,
    horodatage,
    phases_voix,
    photos,
    plaintes,
    provenance,
    qualification,
    questions,
    reception,
    retrait,
    score,
    suivi,
    transferts,
    verdicts,
)
from . import horodatage as controle_horodatage
from .phases_voix import TransitionInterdite
from .registre import Registre

_CANAUX = ("telephone", "courriel", "formulaire", "texte")
_DEPARTEMENT = "m01-front-office"
_NOM_REGISTRE = "principal"
_FOURNISSEURS_APPEL_HOTE = frozenset({"mock", "twilio", "telnyx", "plivo"})

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


def _voicemail_stt_accepte(
    lignes: Sequence[dict[str, Any]], source: str, evenement_id: str, appel_id: str
) -> dict[str, Any] | None:
    return next(
        (
            ligne for ligne in reversed(lignes)
            if ligne.get("type_entree") in {"appel_importe", "appel_voicemail_enrichi"}
            and ligne.get("source") == source
            and ligne.get("evenement_id") == evenement_id
            and ligne.get("appel_id") == appel_id
            and ligne.get("statut") == "voicemail"
            and isinstance(ligne.get("reponse"), dict)
            and ligne["reponse"].get("transcription_conservee") is True
        ),
        None,
    )


def rechercher_rejeu_voicemail_stt(
    empreinte_requete: str, source: str, evenement_id: str, appel_id: str
) -> dict[str, Any] | None:
    """Rend une réponse d'import déjà terminée pour un upload STT strictement identique.

    Seuls les maillons privés écrits par le routeur après un STT réussi servent de preuve de cache.
    L'audio et le texte ne sont ni copiés ni renvoyés ici.
    """
    source, evenement_id, appel_id = source.strip(), evenement_id.strip(), appel_id.strip()
    lignes = _obtenir_registre().lire()
    appel = _voicemail_stt_accepte(lignes, source, evenement_id, appel_id)
    if appel is None:
        return None
    preuve = next(
        (
            ligne for ligne in reversed(lignes)
            if ligne.get("type_entree") == "voicemail_stt_termine"
            and ligne.get("empreinte_requete") == empreinte_requete
            and ligne.get("empreinte_import") == appel.get("empreinte")
        ),
        None,
    )
    return dict(appel["reponse"]) if preuve is not None else None


def enregistrer_rejeu_voicemail_stt(empreinte_requete: str, source: str, evenement_id: str, appel_id: str) -> bool:
    """Ajoute la preuve opaque après import accepté; aucun résultat incertain n'est cacheable."""
    source, evenement_id, appel_id = source.strip(), evenement_id.strip(), appel_id.strip()
    reg = _obtenir_registre()
    lignes = reg.lire()
    appel = _voicemail_stt_accepte(lignes, source, evenement_id, appel_id)
    if appel is None:
        return False
    if any(
        ligne.get("type_entree") == "voicemail_stt_termine"
        and ligne.get("empreinte_requete") == empreinte_requete
        and ligne.get("empreinte_import") == appel.get("empreinte")
        for ligne in lignes
    ):
        return True
    reg.ajouter(
        {
            "type_entree": "voicemail_stt_termine",
            "version": 1,
            "horodatage": dt.datetime.now(dt.UTC).isoformat(timespec="microseconds"),
            "empreinte_requete": empreinte_requete,
            "empreinte_import": appel["empreinte"],
        }
    )
    return True


def importer_appel_manuellement(
    source: str,
    evenement_id: str,
    appel_id: str,
    recu_le: str,
    telephone: str,
    statut: str,
    transcription: str | None = None,
    consentement_enregistrement: str | None = None,
) -> dict[str, Any]:
    """Importe manuellement un appel ou une arrivée tardive de transcription, sans fournisseur vocal.

    `source` décrit explicitement le journal/export consulté ; les identifiants d'événement et d'appel sont ceux de
    cette source. Le même appel peut recevoir ensuite un événement `voicemail` après `manque`. Le texte n'entre dans
    la qualification que si le consentement explicite est `accorde`; aucun média/audio n'est accepté ou conservé.
    Une demande qualifiée passe par l'événement M1→M2 existant. Sinon une tâche de rappel durable apparaît dans « À
    voir ». Aucun appel ni message sortant n'est émis.
    """
    if isinstance(source, str) and source.strip().startswith("voice-call:"):
        raise ValueError("REJ-SOURCE-RESERVEE: cette provenance appartient à l'hôte téléphonique")
    return _importer_appel(
        source, evenement_id, appel_id, recu_le, telephone, statut, transcription,
        consentement_enregistrement, declenchement="appel_manuel",
        prefixe_signal="appel-manuel", source_contact="numéro de téléphone importé manuellement",
    )


def importer_appel_manque_hote(
    provider: str, event_id: str, call_id: str, recu_le: str, telephone: str,
) -> dict[str, Any]:
    """Import host-only d'un appel manqué. L'hôte vérifie webhook/provider; M1 n'en vérifie pas la signature."""
    if not _stockage_durable_actif:
        raise ValueError("REJ-STOCKAGE-NON-DURABLE: l'import de l'hôte exige le registre de production")
    if not isinstance(provider, str) or provider not in _FOURNISSEURS_APPEL_HOTE:
        raise ValueError("REJ-FOURNISSEUR-INVALIDE: provider d'appel non pris en charge")
    return _importer_appel(
        f"voice-call:{provider}", event_id, call_id, recu_le, telephone, "manque", None, None,
        declenchement="appel_operateur", prefixe_signal="appel-hote",
        source_contact="numéro transmis par l'hôte",
    )


def _reprendre_voicemail_sans_transcription(
    reg: Registre, lignes: list[dict[str, Any]], existant: dict[str, Any], contenu: dict[str, Any],
    empreinte: str, transcription: str,
) -> dict[str, Any]:
    """Ajoute une transcription à un fallback voicemail prouvé; conserve son transfert humain append-only."""
    source, appel_id = contenu["source"], contenu["appel_id"]
    deja = [ligne for ligne in lignes if ligne.get("type_entree") == "appel_voicemail_enrichi"
            and ligne.get("source") == source and ligne.get("appel_id") == appel_id]
    if len(deja) > 1:
        raise ValueError("REJ-APPEL-CONTRADICTOIRE: plusieurs enrichissements de ce voicemail")
    if deja:
        if deja[0].get("empreinte") == empreinte:
            return dict(deja[0]["reponse"])
        raise ValueError("REJ-APPEL-CONTRADICTOIRE: transcription reprise différente")

    bases = [ligne for ligne in lignes if ligne.get("type_entree") == "appel_importe"
             and ligne.get("source") == source and ligne.get("appel_id") == appel_id
             and ligne.get("statut") == "voicemail"]
    if len(bases) != 1 or bases[0] is not existant:
        raise ValueError("REJ-APPEL-REPRISE-PREUVE-ABSENTE: historique voicemail ambigu")
    base = bases[0]
    reponse_base = base.get("reponse")
    if not isinstance(reponse_base, dict) or reponse_base.get("transcription_conservee") is not False:
        raise ValueError("REJ-APPEL-REPRISE-ETAT-INVALIDE: le voicemail initial n'est pas un fallback")
    if source.startswith("voice-call:"):
        raise ValueError("REJ-SOURCE-RESERVEE: seule l'import hôte peut porter cette origine")

    # L'empreinte initiale prouve l'appel, le numéro et l'heure sans supposer que l'ancien maillon stocke ces champs
    # en clair. L'ID de livraison est omis par le contrat d'idempotence.
    fallback = {
        "source": source, "appel_id": appel_id, "recu_le": contenu["recu_le"],
        "telephone": contenu["telephone"], "statut": "voicemail",
        "transcription": None, "consentement_enregistrement": None,
    }
    empreinte_fallback = hashlib.sha256(
        json.dumps(fallback, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    if base.get("empreinte") != empreinte_fallback or base.get("horodatage") != contenu["recu_le"]:
        raise ValueError("REJ-APPEL-REPRISE-PREUVE-INVALIDE: source, téléphone ou heure différente")

    tache = reponse_base.get("tache_rappel")
    transfert_id = tache.get("transfert_id") if isinstance(tache, dict) else None
    if not isinstance(transfert_id, str) or not transfert_id:
        raise ValueError("REJ-APPEL-REPRISE-TRANSFERT-ABSENT: tâche initiale introuvable")
    signal_initial_id = f"appel-manuel:{source}:{base.get('evenement_id')}"
    signal_initial = next((ligne for ligne in lignes if ligne.get("type_entree") == "signal"
                           and ligne.get("signal_id") == signal_initial_id), None)
    conversation_id = reception.identifiant_de_conversation("sms", contenu["telephone"])
    if (signal_initial is None or signal_initial.get("canal") != "telephone"
            or signal_initial.get("conversation_id") != conversation_id
            or signal_initial.get("horodatage") != contenu["recu_le"]
            or signal_initial.get("contenu_filtre") !=
                "Message vocal reçu; contenu non conservé faute de consentement explicite."):
        raise ValueError("REJ-APPEL-REPRISE-PREUVE-INVALIDE: origine du fallback non démontrée")
    etat = next((e for e in transferts.lire(lignes) if e.identifiant == transfert_id), None)
    if (etat is None or etat.ouverture.get("conversation_id") != conversation_id
            or etat.ouverture.get("type_transfert") != "ventes"
            or not isinstance(etat.ouverture.get("contact"), dict)
            or etat.ouverture["contact"].get("telephone") != contenu["telephone"]
            or (signal_initial_id not in etat.ouverture.get("signaux", ())
                and signal_initial.get(transferts.MARQUE) != transfert_id)):
        raise ValueError("REJ-APPEL-REPRISE-PREUVE-INVALIDE: transfert sans lien exact avec l'appel")

    # Consentement refusé/absent ne passe jamais ce point. La trace ne contient que longueur et conversation,
    # pas le texte.
    verdict_consentement = consentement.conserver_enregistrement(
        {"consentement_enregistrement": contenu["consentement_enregistrement"], "id": conversation_id},
        transcription, registre=reg, horodatage=contenu["recu_le"],
    )
    if verdict_consentement.get("code") != "OK":
        raise ValueError("REJ-CONSENTEMENT-ABSENT: transcription non conservée")

    signal_id = "appel-manuel-reprise:" + hashlib.sha256(
        f"{len(source)}:{source}{len(appel_id)}:{appel_id}{empreinte}".encode()
    ).hexdigest()
    contenu_filtre, sain = provenance.filtrer(transcription)
    signaux_plainte, verdict_signaux = taxonomie.charger_signaux_plainte()
    detection = plaintes.detecter(contenu_filtre, signaux_plainte, verdict_signaux)
    if etat.ouvert or detection.reconnu:
        zone, verdict_zone = taxonomie.charger_zone_desservie()
        if verdict_zone is not None:
            raise ValueError(f"{verdict_zone['code']}: {verdict_zone['detail']}")
        fenetre, verdict_fenetre = taxonomie.charger_fenetre_conversation()
        if verdict_fenetre is not None and verdict_fenetre["code"] != taxonomie.VERDICT_FENETRE_NON_CONFIGUREE:
            raise ValueError(f"{verdict_fenetre['code']}: {verdict_fenetre['detail']}")
        traitement = _traiter(
            transcription, "telephone", conversation_id, signal_id, contenu["recu_le"], list(zone),
            "accorde", "appel_manuel", None, None, contact_canal={"telephone": contenu["telephone"]},
            fenetre_minutes=fenetre,
        )
        transfert = traitement.get("transfert", {})
        if detection.reconnu:
            prioritaire = next((e for e in transferts.lire(reg.lire())
                                if e.identifiant == transfert.get("transfert_id")), None)
            decision_prioritaire = ("ESCALADE_URGENCE" if detection.type_transfert == plaintes.TYPE_URGENCE
                                    else "ESCALADE_PLAINTE")
            if (traitement.get("decision") not in {decision_prioritaire, "TRANSFERT_EN_COURS"}
                    or transfert.get("type_transfert") != detection.type_transfert
                    or prioritaire is None or not prioritaire.ouvert
                    or prioritaire.ouverture.get("type_transfert") != detection.type_transfert
                    or prioritaire.ouverture.get("conversation_id") != conversation_id):
                raise ValueError("REJ-APPEL-REPRISE-ROUTAGE-INATTENDU: escalade canonique non démontrée")
        elif (traitement.get("decision") != "TRANSFERT_EN_COURS"
              or transfert.get("transfert_id") != transfert_id):
            raise ValueError("REJ-APPEL-REPRISE-ROUTAGE-INATTENDU: le handoff humain doit rester prioritaire")
        traitement["qualification_en_attente"] = "transfert_humain_ouvert"
        # La nouvelle alerte est dans traitement.transfert ; l'origine ventes reste inchangée.
        tache_reprise = ({"transfert_id": transfert_id, "statut": "ouvert",
                          "deja_ouvert": True, "envoi_automatique": False} if etat.ouvert else
                         {"transfert_id": transfert_id, "statut": "clos",
                          "deja_traite": True, "envoi_automatique": False})
        signal_final_id = signal_id
    else:
        # Dossier clos : une note tardive rejoint le même historique; elle ne rouvre ni ne recrée de tâche.
        reg.ajouter({
            "type_entree": "signal", "canal": "telephone", "conversation_id": conversation_id,
            "signal_id": signal_id, "horodatage": contenu["recu_le"], "contenu_filtre": contenu_filtre,
            "provenance_saine": sain, transferts.MARQUE: transfert_id, "source": "appel_manuel",
        })
        signal_final_id = signal_id
        traitement = {
            "etape": "transfert", "accepte": True, "decision": "TRANSFERT_CLOS_NOTE_AJOUTEE",
            "transfert_id": transfert_id, "qualification_en_attente": "dossier humain déjà traité",
        }
        tache_reprise = {"transfert_id": transfert_id, "statut": "clos",
                         "deja_traite": True, "envoi_automatique": False}

    reponse = {
        "accepte": True, "source": source, "appel_id": appel_id, "evenement_id": contenu["evenement_id"],
        "statut": "voicemail", "transcription_conservee": True, "traitement": traitement,
        "tache_rappel": tache_reprise, "envoi_automatique": False,
    }
    reg.ajouter({
        "type_entree": "appel_voicemail_enrichi", "source": source, "evenement_id": contenu["evenement_id"],
        "appel_id": appel_id, "horodatage": contenu["recu_le"], "statut": "voicemail",
        "empreinte_fallback": empreinte_fallback, "empreinte": empreinte,
        "empreinte_transcription": hashlib.sha256(transcription.encode("utf-8")).hexdigest(),
        "consentement_enregistrement": "accorde", "transfert_id": transfert_id,
        "signal_id": signal_final_id, "reponse": reponse,
    })
    return reponse


def _importer_appel(
    source: str,
    evenement_id: str,
    appel_id: str,
    recu_le: str,
    telephone: str,
    statut: str,
    transcription: str | None = None,
    consentement_enregistrement: str | None = None,
    *,
    declenchement: str,
    prefixe_signal: str,
    source_contact: str,
) -> dict[str, Any]:
    """Owner partagé de l'import M1; toutes les provenances sont fixées par wrappers internes."""
    if not isinstance(source, str) or not source.strip() or len(source) > 120:
        raise ValueError("REJ-SOURCE-INVALIDE: source explicite requise (ex. export manuel de journal d'appels)")
    if not isinstance(evenement_id, str) or not evenement_id.strip() or len(evenement_id) > 200:
        raise ValueError("REJ-EVENEMENT-INVALIDE: identifiant d'événement source requis")
    if not isinstance(appel_id, str) or not appel_id.strip() or len(appel_id) > 200:
        raise ValueError("REJ-APPEL-INVALIDE: identifiant métier d'appel requis")
    if statut not in {"manque", "voicemail"}:
        raise ValueError("REJ-STATUT-INVALIDE: statut attendu `manque` ou `voicemail`")
    if not isinstance(telephone, str) or re.fullmatch(r"\+[1-9][0-9]{6,14}", telephone.strip()) is None:
        raise ValueError("REJ-TELEPHONE-INVALIDE: numéro E.164 requis")
    telephone = telephone.strip()
    horodatage.valider_horodatage(recu_le)
    if transcription is not None and (not isinstance(transcription, str) or not transcription.strip()):
        raise ValueError("REJ-TRANSCRIPTION-INVALIDE: transcription absente ou vide")
    if statut == "manque" and transcription:
        raise ValueError("REJ-STATUT-INVALIDE: un appel manqué ne porte pas de transcription")
    if statut == "voicemail" and transcription and consentement_enregistrement != "accorde":
        # On ne rejette pas l'événement source : le message vocal est bien reçu, mais son contenu reste hors registre.
        transcription_a_traiter = None
    else:
        transcription_a_traiter = transcription

    contenu = {
        "source": source.strip(), "evenement_id": evenement_id.strip(), "appel_id": appel_id.strip(),
        "recu_le": recu_le, "telephone": telephone, "statut": statut,
        "transcription": transcription,
        "consentement_enregistrement": consentement_enregistrement,
    }
    # L'identifiant de transport varie lors d'un nouvel envoi : l'idempotence du fait métier est
    # portée par (source, appel_id, statut) et l'empreinte du contenu métier, jamais par cet ID.
    contenu_metier = {cle: valeur for cle, valeur in contenu.items() if cle != "evenement_id"}
    if prefixe_signal == "appel-hote":
        # Le contenu d'un ancien import manuel ne prouve pas un import de l'hôte,
        # même s'il revendiquait la même source. Son empreinte historique reste intacte.
        contenu_metier["origine_import"] = "hote_voix_v1"
    empreinte_historique = hashlib.sha256(
        json.dumps(contenu_metier, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    import_manuel = (prefixe_signal == "appel-manuel" and declenchement == "appel_manuel"
                     and source_contact == "numéro de téléphone importé manuellement")
    fallback_v2 = statut == "voicemail" and transcription_a_traiter is None and import_manuel
    empreinte = empreinte_historique
    empreinte_reception = None
    if fallback_v2:
        # Dérivée déclarée de la réception originale, pas une signature fournisseur ; aucun texte brut persisté.
        empreinte_reception = hashlib.sha256(json.dumps(
            {"representation": "voicemail_reception_v2", "contenu": contenu_metier},
            sort_keys=True, ensure_ascii=False,
        ).encode()).hexdigest()
        contenu_fallback = {**contenu_metier, "transcription": None, "consentement_enregistrement": None}
        empreinte = hashlib.sha256(
            json.dumps(contenu_fallback, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
    reg = _obtenir_registre()
    lignes = reg.lire()
    existant = next((ligne for ligne in lignes if ligne.get("type_entree") == "appel_importe"
                     and ligne.get("source") == contenu["source"]
                     and ligne.get("appel_id") == contenu["appel_id"]
                     and ligne.get("statut") == statut), None)
    if existant is not None:
        representation_v2 = "representation_fallback" in existant or "empreinte_reception" in existant
        if representation_v2:
            preuve_reception = existant.get("empreinte_reception")
            if (existant.get("representation_fallback") != "voicemail_manuel_v2"
                    or not isinstance(preuve_reception, str)
                    or re.fullmatch(r"[0-9a-f]{64}", preuve_reception) is None
                    or not import_manuel or statut != "voicemail"
                    or not isinstance(existant.get("reponse"), dict)
                    or existant["reponse"].get("transcription_conservee") is not False):
                raise ValueError("REJ-APPEL-REPRISE-PREUVE-INVALIDE: représentation fallback inconnue ou incomplète")
        else:
            # Les anciens maillons gardent leur empreinte et leurs refus, sans guérison implicite.
            empreinte = empreinte_historique
        if existant.get("empreinte") == empreinte:
            if representation_v2 and preuve_reception != empreinte_reception:
                raise ValueError("REJ-APPEL-CONTRADICTOIRE: réception non consentie différente")
            return dict(existant["reponse"])
        if (statut == "voicemail" and transcription_a_traiter is not None
                and consentement_enregistrement == "accorde"
                and isinstance(existant.get("reponse"), dict)
                and existant["reponse"].get("transcription_conservee") is False
                and prefixe_signal == "appel-manuel"
                and declenchement == "appel_manuel"
                and source_contact == "numéro de téléphone importé manuellement"):
            return _reprendre_voicemail_sans_transcription(
                reg, lignes, existant, contenu, empreinte, transcription_a_traiter,
            )
        raise ValueError("REJ-APPEL-CONTRADICTOIRE: ce fait d'appel existe avec un contenu différent")

    conversation_id = reception.identifiant_de_conversation("sms", telephone)
    signal_id = f"{prefixe_signal}:{contenu['source']}:{contenu['evenement_id']}"
    texte = transcription_a_traiter or (
        "Appel manqué, rappel demandé." if statut == "manque"
        else "Message vocal reçu; contenu non conservé faute de consentement explicite."
    )
    zone, verdict_zone = taxonomie.charger_zone_desservie()
    if verdict_zone is not None:
        raise ValueError(f"{verdict_zone['code']}: {verdict_zone['detail']}")
    fenetre, verdict_fenetre = taxonomie.charger_fenetre_conversation()
    if verdict_fenetre is not None and verdict_fenetre["code"] != taxonomie.VERDICT_FENETRE_NON_CONFIGUREE:
        raise ValueError(f"{verdict_fenetre['code']}: {verdict_fenetre['detail']}")
    resultat = _traiter(
        texte, "telephone", conversation_id, signal_id, recu_le, list(zone),
        consentement_enregistrement if transcription_a_traiter else None, declenchement, None, None,
        contact_canal={"telephone": telephone}, fenetre_minutes=fenetre,
    )
    # Les appels manqués et les messages non qualifiés deviennent une tâche humaine durable. Une plainte/urgence
    # garde la priorité de son transfert existant ; un lead qualifié est déjà transmis au vrai CRM M2.
    transfert_resultat = None
    if resultat.get("decision") not in {"TRANSMETTRE_M2", "ESCALADE_PLAINTE", "ESCALADE_URGENCE", "TRANSFERT_EN_COURS"}:
        signal = next((ligne for ligne in reg.lire() if ligne.get("type_entree") == "signal"
                       and ligne.get("signal_id") == signal_id), None)
        if signal is not None:
            destinataire, verdict_destinataire = taxonomie.charger_destinataire_du_transfert("ventes")
            ligne, refus = transferts.preparer_ouverture(
                reg.lire(), type_transfert="ventes", categories=(), termes={},
                declenche_par=transferts.DECLENCHE_PAR_REGLES, canal="telephone", source=declenchement,
                conversation_id=conversation_id, message_courant=signal, contact={"telephone": telephone},
                contact_source=source_contact, destinataire=destinataire,
                verdict_destinataire=verdict_destinataire, fenetre_minutes=None,
            )
            if ligne is not None:
                ligne_id = reg.ajouter(ligne)
                transfert_resultat = {"transfert_id": ligne["transfert_id"], "statut": "ouvert",
                                      "ligne_id": ligne_id, "envoi_automatique": False}
    elif resultat.get("decision") == "TRANSFERT_EN_COURS":
        transfert_ouvert = resultat.get("transfert", {})
        if transfert_ouvert.get("type_transfert") == "ventes":
            transfert_resultat = {"transfert_id": transfert_ouvert["transfert_id"], "statut": "ouvert",
                                  "deja_ouvert": True, "envoi_automatique": False}
    reponse = {
        "accepte": True, "source": contenu["source"], "appel_id": contenu["appel_id"],
        "evenement_id": contenu["evenement_id"], "statut": statut,
        "transcription_conservee": transcription_a_traiter is not None,
        "traitement": resultat, "tache_rappel": transfert_resultat,
        "envoi_automatique": False,
    }
    trace_import = {"type_entree": "appel_importe", "source": contenu["source"],
                    "evenement_id": contenu["evenement_id"], "appel_id": contenu["appel_id"],
                    "statut": statut, "empreinte": empreinte, "horodatage": recu_le, "reponse": reponse}
    if fallback_v2:
        trace_import.update({"representation_fallback": "voicemail_manuel_v2",
                             "empreinte_reception": empreinte_reception})
    reg.ajouter(trace_import)
    return reponse


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


def _publier_lead(
    lead: dict[str, Any], horodatage: str, signal_id: str, lignes: Sequence[dict[str, Any]] = ()
) -> None:
    """Publie le lead qualifié au bus (`m1.lead_qualifie`), dans la transaction courante, SEULEMENT avec le
    registre de production. L'identifiant de l'événement vient du `lead_id` : un lead rejoué ne s'y ajoute pas
    deux fois (`opsys.evenements.publier`, idempotent).

    `lignes` : le registre tel qu'il était avant ce message. Si le correspondant s'est déjà retiré (STOP), le retrait
    de son consentement vaut aussi pour ce lead : il part au bus, pour ce lead seul (`retrait.py`)."""
    if not _stockage_durable_actif:
        return
    evenements.publier(
        TYPE_EVENEMENT_LEAD,
        _DEPARTEMENT,
        {"lead": lead, "horodatage": horodatage, "signal_id": signal_id},
        evenement_id=f"m1-lead-qualifie-{lead['lead_id']}",
    )
    alerte = retrait.alerte_de_retrait(lignes, lead["conversation_id"])
    if alerte is not None:
        _publier_retrait(alerte, (lead["lead_id"],))


def _publier_retrait(alerte: dict[str, Any], lead_ids: Sequence[str]) -> str | None:
    """Publie le retrait du consentement (`m1.retrait_consentement`) pour ces leads, dans la transaction courante,
    SEULEMENT avec le registre de production ; rend l'identifiant de l'événement, ou `None` si rien n'est publié
    (registre en mémoire, ou aucun lead : sans lead, un consommateur n'a rien à retirer). L'identifiant vient du
    signal du STOP et des leads : un STOP rejoué ne s'y ajoute pas deux fois. Aucun contact n'est porté
    (`retrait.py`)."""
    if not _stockage_durable_actif or not lead_ids:
        return None
    identifiant = retrait.identifiant_evenement(alerte["signal_id"], lead_ids)
    evenements.publier(
        retrait.TYPE_EVENEMENT, _DEPARTEMENT, retrait.charge(alerte, lead_ids), evenement_id=identifiant
    )
    return identifiant


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
# Formulaire d'un site : le UTM et l'identité déclarée (PLAN T4.17-e3)
# ---------------------------------------------------------------------------

_DECISIONS_DE_TRANSFERT = frozenset({"ESCALADE_PLAINTE", "ESCALADE_URGENCE", "TRANSFERT_EN_COURS"})
_UTM_NON_PORTE = {
    "transfert_humain": (
        "ce message est une plainte, une urgence, ou suit un transfert ouvert : aucun lead ne s'ouvre, donc aucun lead "
        "ne porte cet utm. Dis-le à une personne."
    ),
    "lead_deja_emis": (
        "la conversation a déjà son lead (contrat v2 gelé) et ce lead ne porte pas cet utm. Dis-le à une personne."
    ),
    "aucun_lead_ouvert": (
        "ce message n'ouvre aucun lead (de quoi le qualifier manque) : aucun lead ne porte cet utm. Le lead qui naîtra "
        "d'un message suivant portera l'utm de ce message-là, s'il en donne un. Dis-le à une personne."
    ),
}


def _bloc_utm(reponse: dict[str, Any], utm: dict[str, str]) -> dict[str, Any]:
    """Ce que devient un `utm` fourni, dit à l'agent : porté par le lead de la réponse, ou par aucun, et pourquoi.

    Le verdict se lit sur la réponse finie, jamais sur une intention : `porte_par_le_lead` seulement quand le lead de la
    réponse porte exactement cet `utm` (le lead qu'un rejeu rend, ou celui que ce message vient d'ouvrir). Sinon
    `non_porte`, avec la raison : un transfert humain, un lead déjà émis (gelé) sans cet `utm`, ou aucun lead ouvert."""
    lead = reponse.get("lead")
    if isinstance(lead, dict) and lead.get("utm") == utm:
        return {"statut": "porte_par_le_lead"}
    if reponse.get("decision") in _DECISIONS_DE_TRANSFERT:
        raison = "transfert_humain"
    elif isinstance(lead, dict):
        raison = "lead_deja_emis"
    else:
        raison = "aucun_lead_ouvert"
    return {"statut": "non_porte", "raison": raison, "detail": _UTM_NON_PORTE[raison]}


def _avec_bloc_utm(reponse: dict[str, Any], utm: dict[str, str] | None) -> dict[str, Any]:
    """La réponse, avec le bloc `utm` quand l'appelant en a fourni un (`_bloc_utm`) ; sans `utm` fourni, inchangée."""
    if utm is not None:
        reponse["utm"] = _bloc_utm(reponse, utm)
    return reponse


def _etiquette_du_contact(canal: str, contact_canal: dict[str, str] | None) -> str:
    """D'où vient le contact du lead, tel que la réponse le dit : `canal` (la plateforme a vérifié l'identité du
    correspondant) ou `texte` (le client l'a écrite). Celle d'un formulaire est écrite par le visiteur, sans aucune
    vérification (`reception.CANAUX_A_IDENTITE_DECLAREE`) : `texte`, même si le lead la porte comme champ du canal."""
    return "canal" if contact_canal and canal not in reception.CANAUX_A_IDENTITE_DECLAREE else "texte"


def _etiqueter_le_diagnostic(diagnostic: dict[str, Any], canal: str) -> dict[str, Any]:
    """Le diagnostic d'une conversation, dont la source du contact suit `_etiquette_du_contact` : seule l'étiquette
    change, jamais ce qui est établi ni ce qui manque."""
    if diagnostic["contact"] == "canal" and canal in reception.CANAUX_A_IDENTITE_DECLAREE:
        return {**diagnostic, "contact": "texte"}
    return diagnostic


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
    contrats.exiger_utm(canal, utm)
    return qualification.qualifier(
        contenu_filtre, canal, conversation_id, zone_desservie,
        source=source, utm=None if utm is None else dict(utm), campagne=campagne,
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


def _conversation_voix_canonique(conversation_fournie: Any) -> dict[str, Any] | None:
    """Relit et reconstruit l'état vocal depuis les maillons ; l'objet envoyé par le modèle n'est qu'une référence."""
    if not isinstance(conversation_fournie, dict) or not isinstance(conversation_fournie.get("conversation_id"), str):
        return None
    lignes = _obtenir_registre().lire()
    identifiant = conversation_fournie["conversation_id"]
    transitions = [ligne for ligne in lignes if ligne.get("type_entree") == "transition_phase"
                   and ligne.get("payload", {}).get("conversation_id") == identifiant]
    if not transitions:
        return None
    ouverture = transitions[0]
    payload_ouverture = ouverture.get("payload", {})
    if payload_ouverture.get("motif") != "ouverture" or payload_ouverture.get("phase_cible") != 0:
        return None
    conv = {
        "conversation_id": identifiant,
        "signal_id": conversation_fournie.get("signal_id"),
        "statut": "ouverte",
        "phases": [{"numero": 0, "horodatage_debut": ouverture["horodatage"],
                    "horodatage_fin": None, "statut": "ouverte"}],
        "phase_courante": 0,
        "dernier_ligne_id": ouverture.get("ligne_id"),
    }
    for ligne in transitions[1:]:
        payload = ligne.get("payload", {})
        source, cible = payload.get("phase_source"), payload.get("phase_cible")
        if conv["statut"] != "ouverte" or source != conv["phase_courante"] or cible not in (source + 1,):
            abandon_valide = (
                payload.get("motif") == "abandon" and conv["statut"] == "ouverte"
                and source == conv["phase_courante"] and cible == 5
            )
            if abandon_valide:
                phase = conv["phases"][source]
                phase.update(statut="close_abandon", horodatage_fin=ligne["horodatage"])
                conv["phases"].append({"numero": 5, "horodatage_debut": ligne["horodatage"],
                                       "horodatage_fin": ligne["horodatage"], "statut": "close_abandon"})
                conv.update(statut="close_abandon", phase_courante=5, dernier_ligne_id=ligne.get("ligne_id"))
                continue
            return None
        phase = conv["phases"][source]
        statut_phase = "close_normale"
        phase.update(statut=statut_phase, horodatage_fin=ligne["horodatage"])
        fin = cible == 5
        conv["phases"].append({"numero": cible, "horodatage_debut": ligne["horodatage"],
                              "horodatage_fin": None, "statut": "close_normale" if fin else "ouverte"})
        conv.update(phase_courante=cible, dernier_ligne_id=ligne.get("ligne_id"))
        if fin:
            conv["statut"] = "close_normale"
    violations = [ligne for ligne in lignes if ligne.get("type_entree") == "alerte"
                  and ligne.get("code") == "EVT-PHASE-VIOLATION"
                  and ligne.get("payload", {}).get("conversation_id") == identifiant]
    if violations and conv["statut"] == "ouverte":
        conv["phases"][conv["phase_courante"]]["statut"] = "close_erreur"
        conv["statut"] = "close_erreur"
    # Les anciens maillons ne portaient pas signal_id dans payload ; l'identifiant déterministe lie alors
    # l'assertion à l'heure d'ouverture. Les ouvertures nouvelles conservent aussi le signal explicitement.
    signal_id = payload_ouverture.get("signal_id", conversation_fournie.get("signal_id"))
    if payload_ouverture.get("signal_id") not in (None, conversation_fournie.get("signal_id")):
        return None
    if phases_voix._generer_conversation_id(signal_id, ouverture["horodatage"]) != identifiant:
        return None
    conv["signal_id"] = signal_id
    return conv


def _refuser_conversation_voix(non_canonique: bool = True) -> dict[str, Any]:
    code = "REJ-CONVERSATION-NON-CANONIQUE" if non_canonique else "REJ-CONVERSATION-INCONNUE"
    return verdicts.construire_verdict(code, detail="relis une conversation M1 ouverte depuis le registre vocal")


def transitionner_phase(conversation: dict[str, Any], phase_cible: int, horodatage: str) -> dict[str, Any]:
    """Fait progresser une conversation d'une phase. `conversation` est l'objet
    renvoyé par `m1_ouvrir_conversation` (ou une transition précédente), à
    reporter tel quel — jamais reconstruit de mémoire par l'agent."""
    canonique = _conversation_voix_canonique(conversation)
    if canonique is None or canonique != conversation:
        return {"accepte": False, "verdict": _refuser_conversation_voix(), "conversation": conversation}
    try:
        verdict = phases_voix.transitionner(canonique, phase_cible, horodatage, _obtenir_registre())
    except TransitionInterdite as exc:
        # phases_voix lève sur violation plutôt que de renvoyer un couple : on
        # traduit ici vers le même patron (accepte, verdict) que le reste des
        # outils, pour que l'agent n'ait qu'une seule forme de réponse à lire.
        return {"accepte": False, "verdict": exc.verdict, "conversation": canonique}
    if verdict.get("code") != "OK":
        return {"accepte": False, "verdict": verdict, "conversation": canonique}
    return {"accepte": True, "verdict": verdict, "conversation": canonique}


def abandonner_conversation(conversation: dict[str, Any], horodatage: str) -> dict[str, Any]:
    canonique = _conversation_voix_canonique(conversation)
    if canonique is None or canonique != conversation:
        return {"accepte": False, "verdict": _refuser_conversation_voix(), "conversation": conversation}
    verdict = phases_voix.abandonner(canonique, horodatage, _obtenir_registre())
    if verdict.get("code") != "OK":
        return {"accepte": False, "verdict": verdict, "conversation": canonique}
    return {"accepte": True, "verdict": verdict, "conversation": canonique}


def _refus_lecture_admin() -> dict[str, Any] | None:
    """Confirme l'admin actif ou le propriétaire réel de console avant de lire le registre.

    La provenance console est posée par l'adaptateur serveur, jamais par les arguments ou
    le `_meta` MCP. Un appel interne sans identité conserve sa voie existante.
    """
    appelante = contexte_appel.identite_appelante()
    if appelante is None:
        return None
    cnx = stockage.connexion_courante()
    confirmee = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
    if confirmee is None or not (
        confirmee.role == "admin"
        or (confirmee.role == "nathan_owner" and confirmee.source == "console")
    ):
        return _verdict_refus(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            "lecture réservée à une personne admin active ou au propriétaire confirmé de la console",
        )
    return None


def produire_digest(date_reference: str) -> str | dict[str, Any]:
    refus = _refus_lecture_admin()
    if refus is not None:
        return refus
    try:
        if (not isinstance(date_reference, str)
                or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date_reference, re.ASCII) is None
                or dt.date.fromisoformat(date_reference).isoformat() != date_reference):
            raise ValueError
    except ValueError:
        return _verdict_refus("REJ-DIGEST-DATE-INVALIDE", "date_reference doit être une date calendaire YYYY-MM-DD")
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

    `utm` : seul le canal `formulaire` en porte un (`contrats.CANAUX_AVEC_UTM`), validé comme M2 le valide. Fourni pour
    un appel, un SMS ou un courriel, ou invalide, il est refusé avant toute écriture (`ValueError`, verdict qui dit
    quoi corriger) : jamais ignoré, jamais un lead sans lui en silence.
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
    """Le chemin d'une demande, de la provenance au lead. `utm` (PLAN T4.17-e3) est vérifié AVANT tout effet : refusé,
    il n'écrit rien. Copié, il n'est jamais partagé avec l'appelant. Fourni, il est dit à l'agent (`utm.statut`), porté
    ou non par un lead : la réponse ne le laisse jamais disparaître en silence."""
    contrats.exiger_utm(canal, utm)
    utm_recu = None if utm is None else dict(utm)
    reponse = _traiter_le_signal(
        contenu_brut, canal, conversation_id, signal_id, horodatage, zone_desservie, consentement_enregistrement,
        source, utm_recu, campagne, contact_canal, cle_session, fenetre_minutes,
    )
    return _avec_bloc_utm(reponse, utm_recu)


def _traiter_le_signal(
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
    contact_canal: dict[str, str] | None,
    cle_session: str | None,
    fenetre_minutes: int | None,
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
            contact_canal=contact_canal, cle_session=cle_session, fenetre_minutes=fenetre_minutes, utm=utm)

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
    if utm is not None:
        signal["utm"] = utm  # ce que le visiteur a déclaré reste au registre, même quand aucun lead ne le porte
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
        diagnostic = _etiqueter_le_diagnostic(
            qualification.diagnostiquer(contenu_a_qualifier, zone_desservie, services_lus, contact_canal), canal)
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
    _publier_lead(resultat_qualif, horodatage, signal_id, lignes)

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
    canal: str, contact_canal: dict[str, str] | None, contenu_filtre: str
) -> tuple[dict[str, str] | None, str | None]:
    """`(contact, source)` : l'identité que la plateforme a vérifiée (`canal`), sinon ce que le client a écrit
    (`texte`, dont l'adresse ou le numéro d'un formulaire : rien ne l'a vérifiée), sinon rien. Le transfert le porte à
    part : c'est ainsi que la personne sait qui rappeler."""
    if contact_canal:
        return dict(contact_canal), _etiquette_du_contact(canal, contact_canal)
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
    utm: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Un message reconnu comme plainte ou urgence de sécurité, ou reçu dans une conversation dont un transfert est
    encore ouvert : il est inscrit, rattaché à un transfert, et n'ouvre JAMAIS de lead (la plainte prime). Un `utm`
    qu'il porte reste sur la ligne de son signal : aucun lead ne s'ouvre pour le porter.

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
        contact, contact_source = _contact_du_message(canal, contact_canal, contenu_filtre)
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
    if utm is not None:
        signal["utm"] = utm
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
        conversation_id=conversation_id, message_courant=None, contact=contact,
        contact_source=_etiquette_du_contact(canal, contact),
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


def _verdict_refus(code: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "verdict": verdicts.construire_verdict(code, detail=detail)}


def _acteur_humain(nom_outil: str) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """Qui décide : `({par, role, voie}, None)` si c'est un humain identifié, sinon `(None, réponse de refus)`.

    Clore un transfert est une décision de personne : un agent ne l'a jamais seul (la file « À voir » ne se viderait
    plus d'elle-même). Deux voies, jamais une troisième, jamais un texte de modèle ni un argument :
    1. un appel d'appareil dont l'identité (posée par le core d'après un jeton vérifié) est CONFIRMÉE en base à
       l'instant même (personne active portant encore ce rôle), de rôle `admin` ;
    2. l'exécution d'une demande qu'un humain vient d'approuver dans la file d'approbation : le SOCLE dit qui l'a
       approuvée (`approbations.approbateur_en_cours`, PLAN T4.15-d ; demande relue en base, personne active portant
       encore son rôle), et l'outil ne reconnaît que `admin` et `nathan_owner` (`_ROLES_HUMAINS`), même si la politique
       du département s'élargit. Les arguments ne sont pas comparés : `decider` rejoue les arguments EXACTS
       enregistrés et lui seul pose la demande en cours.
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
    approbateur = approbations.approbateur_en_cours(cnx, nom_outil, _DEPARTEMENT, roles=_ROLES_HUMAINS)
    if approbateur is not None:
        return {"par": approbateur.personne, "role": approbateur.role, "voie": _VOIE_APPROBATION}, None
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


def _refus_suivi_rappel(code: str, detail: str) -> dict[str, Any]:
    return _verdict_refus(code, detail)


def _lire_registre_suivi_rappel() -> tuple[Registre, list[dict[str, Any]]]:
    """Vérifie le port durable, la connexion d'écriture SQLite et la chaîne avant lecture/mutation de suivi."""
    cnx = stockage.connexion_courante()
    reg = _obtenir_registre()
    maillons = getattr(reg, "_entrees", None)
    if (
        not _stockage_durable_actif
        or cnx is None
        or stockage.connexion_courante() is not cnx
        or not cnx.in_transaction()
        or cnx.dialect.name != "sqlite"
        or not isinstance(maillons, stockage.MaillonsDurables)
        or maillons.departement != _DEPARTEMENT
        or maillons.registre != _NOM_REGISTRE
    ):
        raise ValueError("REJ-SUIVI-RAPPEL-STOCKAGE-NON-QUALIFIE")
    lecture_m1.borner(cnx)
    lignes = reg.lire()
    valide, _verdict_chaine = Registre(lignes).valider_chaine()
    if not valide:
        raise ValueError("REJ-SUIVI-RAPPEL-CHAINE-ALTEREE")
    return reg, lignes


def _acteur_suivi_rappel() -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """Autorité humaine de console, revalidée en base sous transaction."""
    cnx = stockage.connexion_courante()
    appelante = contexte_appel.identite_appelante()
    if cnx is None or not cnx.in_transaction() or appelante is None:
        return None, _refus_suivi_rappel(
            "REJ-SUIVI-RAPPEL-HUMAIN-REQUIS", "Identité humaine authentifiée requise; aucune action n'a été inscrite."
        )
    if appelante.source != "console":
        return None, _refus_suivi_rappel(
            "REJ-SUIVI-RAPPEL-HUMAIN-REQUIS", "Cette action exige une session humaine authentifiée."
        )
    confirmee = approbations.signataire_valide(cnx, appelante)
    if confirmee is None:
        return None, _refus_suivi_rappel(
            "REJ-SUIVI-RAPPEL-IDENTITE-INVALIDE", "Identité inactive ou rôle retiré; aucune action n'a été inscrite."
        )
    if confirmee.role not in {identite.Role.ADMIN.value, "nathan_owner"}:
        return None, _refus_suivi_rappel(
            "REJ-SUIVI-RAPPEL-ROLE-INSUFFISANT", "Rôle humain propriétaire ou admin requis."
        )
    return {"par": confirmee.personne, "role": confirmee.role, "voie": appelante.source}, None


def consigner_suivi_rappel(
    transfert_id: str,
    action: str,
    snapshot_attendu: str,
    horodatage: str,
    prochaine_tentative_le: str | None = None,
) -> dict[str, Any]:
    """Attribue une tâche d'appel manqué ou consigne une tentative déclarée sans contact, sans effet externe."""
    acteur, refus = _acteur_suivi_rappel()
    if acteur is None:
        return refus or _refus_suivi_rappel(
            "REJ-SUIVI-RAPPEL-HUMAIN-REQUIS", "Identité humaine authentifiée requise."
        )
    if action not in {transferts.EVT_PRISE_EN_CHARGE, transferts.EVT_TENTATIVE_SANS_CONTACT}:
        return _refus_suivi_rappel("REJ-SUIVI-RAPPEL-ACTION-INVALIDE", "Action de suivi inconnue.")
    if not isinstance(snapshot_attendu, str) or re.fullmatch(r"[0-9a-f]{64}", snapshot_attendu) is None:
        return _refus_suivi_rappel("REJ-SUIVI-RAPPEL-SNAPSHOT-INVALIDE", "Révision du dossier invalide.")
    if action == transferts.EVT_PRISE_EN_CHARGE and prochaine_tentative_le is not None:
        return _refus_suivi_rappel(
            "REJ-SUIVI-RAPPEL-ECHEANCE-INATTENDUE", "Une prise en charge ne porte pas d'échéance de tentative."
        )

    quand = _horodatage_faisant_foi(horodatage)
    try:
        # Le paramètre homonyme est une chaîne; le validateur est celui du module.
        controle_horodatage.valider_horodatage(quand)
    except (TypeError, ValueError):
        return _refus_suivi_rappel("REJ-SUIVI-RAPPEL-HORODATAGE-INVALIDE", "Heure serveur invalide.")
    prochaine = None
    if action == transferts.EVT_TENTATIVE_SANS_CONTACT:
        try:
            prochaine = transferts.normaliser_echeance_rappel(prochaine_tentative_le, quand)
        except ValueError as exc:
            return _refus_suivi_rappel(str(exc), "Échéance future explicite requise.")
    elif prochaine_tentative_le is not None:
        return _refus_suivi_rappel(
            "REJ-SUIVI-RAPPEL-ECHEANCE-INATTENDUE", "Une prise en charge ne porte pas d'échéance de tentative."
        )

    reponse, _ligne_id = _appliquer_suivi_rappel(
        acteur, transfert_id, action, snapshot_attendu, quand, prochaine,
    )
    return reponse


def _appliquer_suivi_rappel_brut(
    acteur, transfert_id, action, snapshot_attendu, quand, prochaine, *, champs_appareil=None,
):
    """Application partagée ; console conserve ses refus/retours, DEVICE garde son propre ACK."""
    try:
        reg, lignes = _lire_registre_suivi_rappel()
    except ValueError as exc:
        return _refus_suivi_rappel(str(exc), "Le registre de suivi n'est pas disponible ou est altéré.")
    etat = _etat_du_transfert(lignes, transfert_id)
    if etat is None:
        return _refus_suivi_rappel("REJ-SUIVI-RAPPEL-CONFLIT-TRANSFERT-INCONNU", "Dossier de rappel indisponible.")
    sources = transferts.sources_appel_rappel(lignes, transfert_id)
    if not sources:
        return _refus_suivi_rappel(
            "REJ-SUIVI-RAPPEL-CONFLIT-SOURCE-APPEL-ABSENTE", "Une source canonique d'appel manqué est requise."
        )
    if etat.ouverture.get("type_transfert") != "ventes":
        return _refus_suivi_rappel(
            "REJ-SUIVI-RAPPEL-CONFLIT-TYPE-INELIGIBLE", "Seul un rappel de ventes importé est admissible."
        )
    if not etat.ouvert:
        return _refus_suivi_rappel("REJ-SUIVI-RAPPEL-CONFLIT-TRANSFERT-CLOS", "Ce dossier est déjà clos.")
    courant = transferts.projection_suivi_rappel(lignes, transfert_id)
    if courant is None:
        return _refus_suivi_rappel(
            "REJ-SUIVI-RAPPEL-CONFLIT-SOURCE-APPEL-ABSENTE", "Source canonique de rappel introuvable."
        )
    if courant["snapshot_suivi"] != snapshot_attendu:
        return _refus_suivi_rappel(
            "REJ-SUIVI-RAPPEL-CONFLIT-SNAPSHOT-PERIME", "Le dossier a changé; rechargez-le avant de réessayer."
        )
    if action == transferts.EVT_PRISE_EN_CHARGE:
        if courant["responsable"] is not None:
            return _refus_suivi_rappel(
                "REJ-SUIVI-RAPPEL-CONFLIT-DEJA-ATTRIBUE", "Cette tâche est déjà prise en charge."
            )
    elif courant["responsable"] != acteur["par"]:
        return _refus_suivi_rappel(
            "REJ-SUIVI-RAPPEL-CONFLIT-NON-ATTRIBUTAIRE", "Seule la personne responsable peut consigner la tentative."
        )

    ligne: dict[str, Any] = {
        "type_entree": transferts.TYPE_ENTREE,
        "evenement": action,
        "transfert_id": transfert_id,
        "par": acteur["par"],
        "role": acteur["role"],
        "voie": acteur["voie"],
        "horodatage": quand,
    }
    if prochaine is not None:
        ligne["prochaine_tentative_le"] = prochaine
    if champs_appareil is not None:
        ligne.update(champs_appareil)
    ligne_id = reg.ajouter(ligne)
    lecture_m1.borner(stockage.connexion_courante())
    apres = reg.lire()
    valide, _verdict_chaine = Registre(apres).valider_chaine()
    projection = transferts.projection_suivi_rappel(apres, transfert_id) if valide else None
    if projection is None:
        raise ValueError("REJ-SUIVI-RAPPEL-CHAINE-ALTEREE")
    return {"accepte": True, "resultat": {"suivi_rappel": projection}}, ligne_id


def _appliquer_suivi_rappel(
    acteur, transfert_id, action, snapshot_attendu, quand, prochaine, *, champs_appareil=None,
):
    r = _appliquer_suivi_rappel_brut(
        acteur, transfert_id, action, snapshot_attendu, quand, prochaine, champs_appareil=champs_appareil,
    )
    return r if isinstance(r, tuple) else (r, None)


def lire_transfert(transfert_id: str) -> dict[str, Any]:
    """Ce qu'une personne lit d'un transfert : résumé, destinataire, contact, messages, et le brouillon de réponse d'une
    plainte ou d'une urgence encore ouverte (jamais envoyé). Lecture seule."""
    refus = _refus_lecture_admin()
    if refus is not None:
        return refus
    reg = _obtenir_registre()
    lignes = reg.lire()
    etat = _etat_du_transfert(lignes, transfert_id)
    if etat is None:
        return _verdict_refus("REJ-TRANSFERT-INCONNU", f"aucun transfert {transfert_id!r} au registre")
    resultat = transferts.vue(etat, lignes)
    if _stockage_durable_actif and transferts.source_appel_revendiquee(lignes, transfert_id):
        try:
            _reg_durable, lignes_durables = _lire_registre_suivi_rappel()
            projection = transferts.projection_suivi_rappel(lignes_durables, transfert_id)
            if projection is None:
                raise ValueError("REJ-SUIVI-RAPPEL-SOURCE-INDISPONIBLE")
            resultat["suivi_rappel"] = projection
        except ValueError as exc:
            raise ValueError("REJ-SUIVI-RAPPEL-SOURCE-INDISPONIBLE") from exc
    retire = transferts.retire(lignes, etat.ouverture["conversation_id"])
    resultat["client_retire_des_messages"] = retire
    type_transfert = etat.ouverture["type_transfert"]
    if etat.ouvert and type_transfert in _TYPES_AVEC_GABARIT:
        resultat.update(plaintes.brouillon(type_transfert, etat.ouverture["categories"], retire))
    return {"accepte": True, "resultat": resultat}


def clore_transfert(transfert_id: str, motif: str, horodatage: str) -> dict[str, Any]:
    """Une PERSONNE clôt un transfert ouvert, avec son motif : il sort de la file « À voir ». Décision humaine : refusée
    à un agent qui n'a pas passé par l'approbation ou par un jeton d'appareil `admin`."""
    acteur, refus = _acteur_humain("m1_clore_transfert")
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
        **cumul, "service": lead["service"], "ville": lead["ville"],
        "contact": _etiquette_du_contact(canal, contact_canal),
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


def _signal_deja_recu(
    reg: Registre, message: reception.MessageRecu
) -> dict[str, Any] | None:
    """Retourne la réponse d'un rejeu identique; un même ID avec des données métier différentes est refusé.

    L'identifiant de message seul ne suffit pas : les registres M1 sont la frontière anti-perte et un fournisseur ou
    une intégration peut réutiliser un ID avec un autre expéditeur, corps ou horodatage. Comparer avant toute mutation
    évite de faire passer le second contenu pour le premier ou de créer une autre interaction.
    """
    signal_id = message.signal_id
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
    contenu_filtre, provenance_saine = provenance.filtrer(message.contenu)
    champs_attendus = {
        "canal": message.canal_contrat,
        "source": message.canal,
        "conversation_id": message.conversation_id,
        "signal_id": message.signal_id,
        "horodatage": message.horodatage,
        "contenu_filtre": contenu_filtre,
        "provenance_saine": provenance_saine,
    }
    divergent = [nom for nom, valeur in champs_attendus.items() if signal.get(nom) != valeur]
    if divergent:
        raise ValueError(
            "REJ-SIGNAL-CONTRADICTOIRE: ce message_id existe déjà avec des données différentes "
            f"({', '.join(divergent)})"
        )
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
    alerte = {
        "type_entree": "alerte",
        "marqueur": "retrait_consentement",
        "canal": message.canal_contrat,
        "source": message.canal,
        "conversation_id": message.conversation_id,
        "signal_id": message.signal_id,
        "horodatage": message.horodatage,
    }
    leads_du_correspondant = retrait.leads_de_la_conversation(reg.lire(), message.conversation_id)
    ligne_alerte = reg.ajouter(alerte)
    evenement_retrait = _publier_retrait(alerte, leads_du_correspondant)
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
        # Le retrait est aussi dit au bus (`m1.retrait_consentement`), par le `lead_id` des leads déjà ouverts pour ce
        # correspondant : M7 s'en sert pour ne plus rien publier de ses chantiers. Aucun contact n'y est porté.
        "retrait_publie": {"leads": len(leads_du_correspondant), "evenement_id": evenement_retrait},
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
    utm: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Un message qu'un canal (SMS, courriel, ou le formulaire d'un site) livre à l'agent M1, de bout en bout.

    Les cinq premiers paramètres sont recopiés par l'agent des blocs que la plateforme génère ; `reception.py`
    en tire ce qui compte, jamais le texte du client : le correspondant validé, la conversation (empreinte, sans
    numéro), le signal (`<canal>:<message_id>`, qui rend la réception idempotente), le contact du lead (l'identité
    du canal, seule), la clé de session du core. La zone desservie vient du profil de l'instance : l'agent ne la
    fournit pas. `source` du lead est le canal.

    `utm` (PLAN T4.17-e3) : les paramètres `utm_*` du lien que le visiteur d'un formulaire a suivi, tels que le
    formulaire les a transmis. Le seul canal qui en porte un est `formulaire` ; validé comme M2 le valide, le lead que
    ce message fait naître le porte tel quel, jamais complété ni deviné. Absent, le lead n'en porte pas.

    Refus (`ValueError`, rien d'écrit) : champ de plateforme invalide, `utm` invalide ou fourni pour un canal qui n'en
    a pas (SMS, courriel), service ou zone non déclarés par l'instance, fenêtre de conversation déclarée mais
    invalide. Sinon : un retrait (STOP) est inscrit sans être qualifié ; un message déjà reçu rend sa réponse sans
    rien écrire ; tout autre passe par `_traiter` (provenance → registre → qualification → lead → bus).

    Fenêtre de conversation (PLAN T2.1-b) : déclarée par le profil d'entreprise, elle rassemble les messages d'un même
    client (`conversation.py`) ; absente, la qualification reste message par message et `conversation.verdict` le dit,
    avec où la déclarer. Jamais une durée par défaut.
    """
    message = reception.preparer(canal, expediteur, message_id, recu_le, texte, objet)
    return _recevoir_message_prepare(message, utm)


def _recevoir_message_prepare(message: reception.MessageRecu, utm, *, rejeu_admis: bool = True):
    """Même pipeline pour la voie legacy et la réception interne liée à son reçu."""
    contrats.exiger_utm(message.canal, utm)  # avant tout : un SMS ou un STOP qui porte un `utm` n'écrit rien
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
    if not rejeu_admis and any(
        ligne.get("type_entree") == "signal" and ligne.get("signal_id") == message.signal_id for ligne in reg.lire()
    ):
        raise ValueError("REJ-M1-SMS-PROVENANCE-CONFLICTUELLE")
    deja = _signal_deja_recu(reg, message)
    if deja is not None:
        return _avec_bloc_utm(deja, None if utm is None else dict(utm))
    if message.retrait:
        reponse = _enregistrer_retrait(reg, message, fenetre)
    else:
        reponse = _traiter(
            message.contenu, message.canal_contrat, message.conversation_id, message.signal_id, message.horodatage,
            list(zone), None, message.canal, utm, None,
            contact_canal=message.contact, cle_session=message.cle_session, fenetre_minutes=fenetre,
        )
    if fenetre is None:
        reponse["conversation"] = {"mode": "message_par_message", "verdict": verdict_fenetre}
    return reponse


def registre_sms_hote():
    """Source entière canonique : borne, rangs réels et chaîne avant toute recherche."""
    cnx = stockage.connexion_courante()
    reg = _obtenir_registre()
    port = getattr(reg, "_entrees", None)
    if (not _stockage_durable_actif or cnx is None or not cnx.in_transaction()
            or cnx.engine.url != stockage.moteur().url
            or cnx.dialect.name != "sqlite" or not isinstance(port, stockage.MaillonsDurables)
            or port.departement != _DEPARTEMENT or port.registre != _NOM_REGISTRE):
        raise ValueError("REJ-M1-SMS-SOURCE-NON-QUALIFIEE")
    lecture_m1.borner(cnx)
    snapshot = copier_maillons_avec_metadonnees(cnx, departement=_DEPARTEMENT, registre=_NOM_REGISTRE)
    if [m.rang for m in snapshot.lignes] != list(range(len(snapshot.lignes))):
        raise ValueError("REJ-M1-SMS-SOURCE-NON-QUALIFIEE")
    lignes = [m.maillon for m in snapshot.lignes]
    Registre(lignes).assert_chaine()
    return reg, lignes


def recevoir_sms_hote(*, expediteur: str, message_id: str, recu_le: str, texte: str, cle_session: str):
    """Entrée interne sans outil public neuf ; session capturée avant tout append natif."""
    registre_sms_hote()
    message = reception.preparer("sms", expediteur, message_id, recu_le, texte)
    message = dataclasses.replace(message, cle_session=cle_session)
    return _recevoir_message_prepare(message, None, rejeu_admis=False)


def inscrire_recu_sms_hote(maillon):
    """Ajout par le propriétaire Registre, jamais par append SQL/hash privé."""
    reg, _lignes = registre_sms_hote()
    return reg.ajouter(maillon)


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
    "description": (
        "Optionnel : paramètres UTM du lien que le visiteur a suivi, tels que le formulaire les a transmis "
        "(utm_source, utm_medium, utm_campaign, utm_content ; aucune autre clé, aucune valeur vide). Seul le canal "
        "`formulaire` en porte un : fourni pour un autre canal, ou invalide, il est refusé. Jamais composé ni déduit "
        "du texte ; absent (null) quand le lien n'en portait aucun."
    ),
}
_CAMPAGNE = {"type": ["string", "null"], "description": "Optionnel : campagne marketing déclarée, jamais devinée."}
_CONVERSATION = {
    "type": "object",
    "description": "Objet conversation renvoyé par m1_ouvrir_conversation ou une transition précédente.",
}
_CANAL_DU_CORE = {
    "type": "string",
    "enum": sorted(reception.CANAL_DU_CONTRAT),
    "description": (
        "Canal du core (champ channel du bloc Message Context : sms, courriel) ou `formulaire` (le formulaire du "
        "site), tel que la plateforme le donne. Jamais deviné."
    ),
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



def autoriser_prise_rappel_appareil(arguments: dict, *, nom: str):
    from . import rappels_appareil
    return rappels_appareil.admettre(arguments, nom=nom)


def verifier_rejeu_prise_rappel_appareil(arguments: dict, reponse: dict):
    from . import rappels_appareil
    return rappels_appareil.verifier_rejeu(arguments, reponse)


def lister_rappels_appareil(apres_transfert_id=None, taille_page=8):
    from . import rappels_appareil
    return rappels_appareil.lister(apres_transfert_id, taille_page)


def prendre_en_charge_rappel_appareil(transfert_id, snapshot_attendu):
    from . import rappels_appareil
    return rappels_appareil.prendre(transfert_id, snapshot_attendu)


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
                "Reçoit un message qu'un canal (sms, courriel, formulaire du site) livre à cet agent : recopie tel "
                "quel le canal, l'expéditeur, l'identifiant et l'heure de réception que la plateforme donne, et le "
                "texte du client. L'outil filtre la provenance, inscrit le signal au registre anti-perte (un message "
                "rejoué ne s'ajoute pas), reconnaît un retrait (STOP), qualifie par règles (service, ville de la "
                "zone, expéditeur comme contact) et transmet le lead à M2 par le bus. Avec une fenêtre de "
                "conversation déclarée, les messages du même client se rassemblent : un seul lead par conversation. "
                "Formulaire seulement : `utm`, les paramètres du lien suivi, que le lead porte tels quels (la "
                "réponse le dit). Le code ajoute, sans modèle : les champs manquants, les questions du service, la "
                "demande de photos (fermée sans politique validée), le score (poids de l'entreprise), la prochaine "
                "action datée, et un brouillon de ce qu'il reste à demander, jamais envoyé."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "canal": {
                        "type": "string",
                        "enum": sorted(reception.CANAL_DU_CONTRAT),
                        "description": (
                            "Canal du core, champ channel du bloc Message Context (sms, courriel), ou `formulaire` "
                            "pour le formulaire du site. Jamais deviné."
                        ),
                    },
                    "expediteur": {
                        "type": "string",
                        "description": (
                            "Numéro E.164 (sms) ou adresse (courriel) du bloc Conversation info (sender) ; pour un "
                            "formulaire, l'adresse courriel (ou le numéro E.164) écrite par le visiteur, non vérifiée."
                        ),
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
                    "utm": _UTM,
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
            nom="m1_importer_appel_manuellement",
            description=(
                "Importe un appel manqué ou un message vocal depuis une source explicitement nommée (journal/export "
                "manuel). Ce n'est pas une intégration opérateur et aucun audio n'est accepté. Le texte vocal n'est "
                "traité/conservé qu'avec consentement explicite `accorde`; sinon seul le fait d'appel est inscrit et "
                "une tâche de rappel peut être créée. Un lead qualifié rejoint M2 par le contrat existant. Aucun "
                "appel, SMS ou courriel n'est envoyé. Un événement tardif `voicemail` peut compléter un appel `manque`."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "source": {"type": "string"}, "evenement_id": {"type": "string"},
                    "appel_id": {"type": "string"}, "recu_le": {"type": "string"},
                    "telephone": {"type": "string"},
                    "statut": {"type": "string", "enum": ["manque", "voicemail"]},
                    "transcription": {"type": ["string", "null"]},
                    "consentement_enregistrement": {"type": ["string", "null"]},
                },
                "required": ["source", "evenement_id", "appel_id", "recu_le", "telephone", "statut"],
                "additionalProperties": False,
            },
            fonction=importer_appel_manuellement,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
            roles_appareil=frozenset({"admin"}),
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
            description=(
                "Vérifie qu'un texte destiné au client ne contient ni prix, ni date, ni engagement, ni aveu, ni avis "
                "légal. Un refus nomme la règle (REJ-INTERDIT-*) et dit quoi retirer."
            ),
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
            nom="m1_consigner_suivi_rappel",
            description=(
                "Consigne une prise en charge ou une tentative déclarée sans contact sur un rappel issu d'un appel "
                "manqué importé. La tâche reste ouverte; aucun appel, contact, message ou rendez-vous n'est créé. "
                "L'identité et l'heure viennent du contexte authentifié et du serveur."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "transfert_id": _TRANSFERT_ID,
                    "action": {"type": "string", "enum": [
                        transferts.EVT_PRISE_EN_CHARGE, transferts.EVT_TENTATIVE_SANS_CONTACT,
                    ]},
                    "snapshot_attendu": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "horodatage": {"type": "string", "description": "Heure de réception fixée par le serveur."},
                    "prochaine_tentative_le": {
                        "type": "string", "minLength": 20, "maxLength": 40,
                        "description": "Échéance future explicitement choisie, ISO-8601 avec offset.",
                    },
                },
                "required": ["transfert_id", "action", "snapshot_attendu", "horodatage"],
                "additionalProperties": False,
            },
            fonction=consigner_suivi_rappel,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
            # Le rejeu N2 appareil doit être qualifié avant ouverture de cette portée.
            roles_appareil=frozenset(),
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
        Outil(
            nom="m1_lister_rappels_appareil",
            description="File courante des rappels réellement importés ; aucune donnée de contact ni effet.",
            parametres={"type": "object", "properties": {
                "apres_transfert_id": {"type": ["string", "null"], "pattern": "^tr-[0-9a-f]{20}$"},
                "taille_page": {"type": "integer", "minimum": 1, "maximum": 8},
            }, "additionalProperties": False},
            fonction=lister_rappels_appareil, autonomie=Autonomie.T0, niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m1_prendre_en_charge_rappel_appareil",
            description="Prise interne à soi d'un rappel importé ; aucun appel ou message envoyé.",
            parametres={"type": "object", "properties": {
                "transfert_id": {"type": "string", "pattern": "^tr-[0-9a-f]{20}$"},
                "snapshot_attendu": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            }, "required": ["transfert_id", "snapshot_attendu"], "additionalProperties": False},
            fonction=prendre_en_charge_rappel_appareil, autonomie=Autonomie.T1, niveau=Niveau.N2,
            roles_appareil=frozenset({"admin"}),
        ),
    )
