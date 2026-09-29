"""Suggestion déterministe de prochaine meilleure action (PLAN T2.2 ; DEFINITION-PRODUIT §7 M2,
M2.6 « Prochaine meilleure action, avec explication »). Nommé ``suggestions.py`` (pas
``prochaine_action.py``) à dessein : ``prochaine_action`` est déjà le nom d'un paramètre et d'une
variable locale très utilisés ailleurs dans le paquet (``statuts.py``, ``outils.py``) — un module
du même nom s'y serait fait masquer silencieusement.

Complète ce qui existe déjà — ``statuts.transitionner`` exige déjà une ``prochaine_action``
HUMAINE aux deux transitions qui en portent une, et ``outils._regle_prochaine_action`` calcule
celle du chantier terminé (PLAN T1.2-c) — par une fonction de LECTURE SEULE (T0), jamais appliquée
automatiquement au registre : une SUGGESTION que l'humain (vendeur, admin) peut suivre ou ignorer,
en appelant lui-même ``m2_transitionner_statut``/``m2_marquer_chantier_termine`` avec SA propre
``prochaine_action``. Ce module n'écrit jamais dans le registre et ne fixe jamais la valeur
réelle utilisée par la FSM (AGENTS.md : « le code calcule, le LLM orchestre » — ici, le code
calcule une RECOMMANDATION, jamais une décision commerciale).

Écart comblé (``docs/departements/M2-audit.md`` §1.3, M2.6) : « stockage d'une action fournie par
un humain seulement, jamais générée [...] Aucun moteur de suggestion ». La table de règles
ci-dessous est déterministe et citée : chaque branche ne relit que des faits déjà écrits au
registre (statut courant, signalements de doublons, readiness) — jamais un modèle, jamais une
donnée inventée.
"""

from __future__ import annotations

from . import horodatage as _horodatage
from .doublons import lister_signalements
from .readiness import emettre_marqueur
from .statuts import STATUTS, STATUTS_TERMINAUX, statut_courant
from .verdicts import construire_verdict

__all__ = [
    "REGLE_PLANIFIER_CHANTIER",
    "prochaine_action_planifier_chantier",
    "suggerer",
    "suggerer_relance_devis_sans_reponse",
]

# Statuts couverts par chaque règle, dans l'ordre de priorité où la table est parcourue —
# STATUTS_ATTENTE_CYCLE et STATUTS_POST_FACTURATION nommés pour que la table reste lisible et que
# `suggerer` puisse vérifier, en fin de fonction, qu'elle a bien couvert tous les statuts non
# terminaux connus de statuts.STATUTS (défense en profondeur : un neuvième statut ajouté un jour
# à la FSM sans mise à jour de cette table lève, au lieu d'être décrit silencieusement comme
# « avis »).
_STATUTS_CHANTIER_EN_COURS = ("cedule", "chantier")
_STATUTS_POST_FACTURATION = ("facture", "paiement")

# PLAN T4.10-a : la soumission est acceptée, le chantier reste à planifier par M4. UNE seule règle, citée, pour la
# prochaine action que la conversion consigne (`prochaine_action_planifier_chantier`) ET pour la suggestion d'un
# lead `converti` (`suggerer`) : les deux ne peuvent pas diverger. Aucune date n'est promise au client (§7 M4 :
# « Ne jamais promettre une date ni confirmer un chantier sans la confirmation de M4 »).
REGLE_PLANIFIER_CHANTIER = "planifier_chantier"
_CONSIGNE_PLANIFIER_CHANTIER = (
    "Planifier le chantier avec M4 : la soumission est acceptée. "
    "Aucune date ni aucun créneau n'est promis au client avant la confirmation de M4."
)
_MOTIF_PLANIFIER_CHANTIER = "Soumission acceptée, chantier à planifier (§6 flux principal, §7 M2.8)."


def _doublon_en_attente_pour(registre_cible, lead_id: str) -> str | None:
    """``signalement_id`` du premier doublon dont l'ARBITRAGE LE PLUS RÉCENT est encore
    ``en_attente`` et implique ce lead (M2.12), ou None. Réutilise ``doublons.lister_signalements``
    tel quel, jamais un second index — mais un même ``signalement_id`` porte PLUSIEURS maillons
    dans le temps (le signalement original ``en_attente``, puis un éventuel arbitrage,
    ``doublons.arbitrer`` n'écrasant jamais l'original) : seul le DERNIER maillon de chaque
    ``signalement_id`` fait foi, jamais le premier rencontré dans l'ordre du registre — même
    discipline que ``digest.py`` pour la même donnée."""
    derniers: dict[str, dict] = {}
    for signalement in lister_signalements(registre_cible):
        derniers[signalement["signalement_id"]] = signalement
    for signalement_id, signalement in derniers.items():
        if signalement["arbitrage"] != "en_attente":
            continue
        if lead_id in (signalement["lead_id_a"], signalement["lead_id_b"]):
            return signalement_id
    return None


def _suggestion(lead_id: str, statut: str, regle: str, suggestion: str, motif: str) -> dict:
    return {"lead_id": lead_id, "statut": statut, "regle": regle, "suggestion": suggestion, "motif": motif}


def suggerer(registre_cible, lead_id: str, horodatage: str) -> tuple[dict | None, dict | None]:
    """Suggère la prochaine meilleure action pour ``lead_id`` (§7 M2, M2.6), par la table de
    règles suivante, dans l'ordre (la première qui s'applique gagne) :

    1. ``lead_id`` introuvable -> verdict ``REJ-TRANSITION-ILLEGALE``.
    2. Statut terminal (``perdu``) -> verdict ``REJ-CONVERSATION-CLOSE`` (dossier clos, aucune
       action à suggérer).
    3. Un doublon signalé est EN ATTENTE d'arbitrage pour ce lead (M2.12) -> l'arbitrer d'abord :
       travailler un doublon probable avant de savoir s'il s'agit du même client serait un effort
       potentiellement perdu.
    4. Statut ``nouveau`` (owner jamais assigné — structurellement, statuts.py ne le fixe qu'à la
       transition vers ``qualifie``) -> assigner un représentant et qualifier (M2.13, SLA anti-
       perte de lead ; §7 M2 « jamais... laisser un lead sans prochaine action »).
    5. Statut ``qualifie``, readiness (M2.5) NON satisfaite -> reprend TEL QUEL le détail déjà
       produit par ``readiness.emettre_marqueur`` (jamais un second calcul divergent des mêmes
       conditions).
    6. Statut ``qualifie``, readiness satisfaite -> transmettre le dossier à M3 pour estimation.
    7. Statut ``converti`` -> planifier le chantier avec M4 (règle ``planifier_chantier``, PLAN T4.10-a).
    8. Statut ``cedule``/``chantier`` -> assurer le suivi du chantier jusqu'à sa complétion (M4).
    9. Statut ``facture``/``paiement`` -> assurer le suivi jusqu'à l'encaissement (M2.8, lien M5).
    10. Statut ``avis`` -> lancer la relance avis et référence (M2.7, M2.14).

    Fonction PURE (lecture seule, T0) : n'écrit jamais au registre, ne fixe jamais la
    ``prochaine_action`` réelle du lead — seul un humain le fait, via les outils d'écriture.
    """
    try:
        horodatage_valide = _horodatage.valider_horodatage(horodatage)
    except ValueError as exc:
        return None, construire_verdict("REJ-HORODATAGE-INVALIDE", detail=str(exc))

    statut = statut_courant(registre_cible, lead_id)
    if statut is None:
        return None, construire_verdict("REJ-TRANSITION-ILLEGALE", detail=f"lead {lead_id} introuvable")
    if statut in STATUTS_TERMINAUX:
        return None, construire_verdict(
            "REJ-CONVERSATION-CLOSE", statut=statut, detail=f"lead {lead_id} clos (statut={statut})"
        )

    signalement_id = _doublon_en_attente_pour(registre_cible, lead_id)
    if signalement_id is not None:
        return _suggestion(
            lead_id, statut, "doublon_en_attente",
            f"Arbitrer le doublon {signalement_id} avant de poursuivre.",
            "Un signalement de doublon probable est en attente d'arbitrage humain (M2.12).",
        ), None

    if statut == "nouveau":
        return _suggestion(
            lead_id, statut, "assigner_owner",
            "Assigner un représentant et qualifier ce lead.",
            "Aucun propriétaire assigné (M2.13 — jamais de lead sans prochaine action).",
        ), None

    if statut == "qualifie":
        _marqueur, verdict_readiness = emettre_marqueur(registre_cible, lead_id, horodatage_valide)
        if verdict_readiness is not None:
            return _suggestion(
                lead_id, statut, "completer_readiness",
                f"Compléter le dossier avant estimation : {verdict_readiness['detail']}",
                "Readiness M3 non satisfaite (M2.5).",
            ), None
        return _suggestion(
            lead_id, statut, "transmettre_m3",
            "Transmettre le dossier à M3 pour estimation.",
            "Readiness M3 satisfaite (M2.5) : owner, type de travaux, ville, interaction post-qualification.",
        ), None

    if statut == "converti":
        return _suggestion(
            lead_id, statut, REGLE_PLANIFIER_CHANTIER, _CONSIGNE_PLANIFIER_CHANTIER, _MOTIF_PLANIFIER_CHANTIER,
        ), None

    if statut in _STATUTS_CHANTIER_EN_COURS:
        return _suggestion(
            lead_id, statut, "suivre_chantier",
            "Assurer le suivi du chantier jusqu'à sa complétion (M4).",
            "Soumission acceptée, chantier en cours (§7 M2, cycle de vie couvert).",
        ), None

    if statut in _STATUTS_POST_FACTURATION:
        return _suggestion(
            lead_id, statut, "suivre_paiement",
            "Assurer le suivi de la facture jusqu'à l'encaissement.",
            "Chantier facturé, paiement non confirmé (M2.8, lien M5).",
        ), None

    if statut == "avis":
        return _suggestion(
            lead_id, statut, "relance_avis_reference",
            "Lancer la relance avis et référence.",
            "Chantier payé : fenêtre idéale pour l'avis et le référencement (M2.7, M2.14).",
        ), None

    # Défense en profondeur : un statut de statuts.STATUTS non couvert ci-dessus signifierait que
    # cette table a divergé de la FSM (ex. un dixième statut ajouté sans mise à jour ici) — mieux
    # vaut lever que décrire silencieusement un statut inconnu comme si c'était « avis ».
    raise RuntimeError(
        f"prochaine_action.suggerer : statut {statut!r} de statuts.STATUTS {STATUTS!r} non couvert "
        "par la table de règles — mise à jour requise, jamais une suggestion par défaut."
    )


def prochaine_action_planifier_chantier(devis_id: str, echeance: str) -> dict:
    """Prochaine action que consigne la conversion d'un lead par un devis accepté (PLAN T4.10-a, règle
    ``planifier_chantier``) : ``{description, echeance}``, la forme que ``statuts.transitionner`` exige. La
    description est un texte FIXE (jamais un modèle) qui cite la règle ; ``echeance`` est l'heure RÉELLE de
    l'acceptation, fournie par l'appelant : jamais une date inventée, calculée d'une horloge ambiante ni promise
    au client (l'échéance dit « depuis quand c'est à faire »)."""
    return {
        "description": (
            f"{_CONSIGNE_PLANIFIER_CHANTIER} Devis {devis_id} "
            f"(règle {REGLE_PLANIFIER_CHANTIER}, DEFINITION-PRODUIT §6 flux principal, §7 M2.8)."
        ),
        "echeance": echeance,
    }


def suggerer_relance_devis_sans_reponse(charge: dict) -> dict:
    """M2.7 (Relances) : suggestion déterministe tirée du fait `m3.devis_sans_reponse` (ADR-0009
    §3, catalogue ``src/opsys/evenements/catalogue/m3.devis_sans_reponse.json``), appelée par le
    consommateur d'événements de M2 (``outils._recevoir_devis_sans_reponse``) — jamais appliquée
    seule (§7 M2, règles dures : « pas de spam... validation humaine au départ »). Frontière T3 du
    socle : M2 ne relance jamais elle-même, elle PROPOSE ; un humain décide, M1 enverra plus tard.

    Fonction PURE (T0, même discipline que ``suggerer`` ci-dessus) : calcule uniquement depuis
    ``charge``, déjà validée par le schéma JSON du catalogue avant de quitter M3
    (``opsys.evenements.publier``) — ne relit, ne recalcule ni n'invente ni le délai
    (``delai_relance_jours``), ni les horodatages, ni le statut du devis : les trois viennent tels
    quels de la charge.

    Distingue exactement les deux statuts qu'un devis « sans réponse » peut porter (jamais
    ``accepte``, qui aurait reçu sa réponse — voir le catalogue) :

    - ``envoye`` : le devis a été transmis au client, qui n'a pas répondu dans le délai -> propose
      de RELANCER LE CLIENT (le vendeur propriétaire du lead, M2.7).
    - ``brouillon`` : le devis n'a JAMAIS été envoyé -> propose de décider de l'envoyer ou de
      l'abandonner — jamais de « relancer » un client qui n'a rien reçu.
    """
    devis_id = charge["devis_id"]
    lead_id = charge["lead_id"]
    statut_devis = charge["statut"]
    horodatage_devis = charge["horodatage_devis"]
    delai = charge["delai_relance_jours"]

    if statut_devis == "envoye":
        return {
            "lead_id": lead_id,
            "devis_id": devis_id,
            "statut_devis": statut_devis,
            "regle": "relancer_client_devis_envoye",
            "suggestion": f"Relancer le client au sujet du devis {devis_id}.",
            "motif": (
                f"Devis envoyé le {horodatage_devis}, resté sans réponse au moins {delai} "
                "jour(s) (M2.7)."
            ),
        }
    if statut_devis == "brouillon":
        return {
            "lead_id": lead_id,
            "devis_id": devis_id,
            "statut_devis": statut_devis,
            "regle": "decider_envoi_ou_abandon_devis_brouillon",
            "suggestion": f"Décider d'envoyer ou d'abandonner le devis {devis_id}.",
            "motif": (
                f"Devis créé le {horodatage_devis}, toujours en brouillon après au moins {delai} "
                "jour(s) — le client n'a encore rien reçu, aucune relance possible avant l'envoi "
                "(M2.7)."
            ),
        }
    # Défense en profondeur : le catalogue m3.devis_sans_reponse n'admet que "brouillon"/"envoye"
    # pour 'statut' (jsonschema valide la charge avant publication) — jamais atteint en usage
    # normal, même patron que suggerer() ci-dessus.
    raise RuntimeError(
        f"suggerer_relance_devis_sans_reponse : statut de devis {statut_devis!r} hors du "
        "catalogue m3.devis_sans_reponse ('brouillon'/'envoye') — mise à jour requise, jamais une "
        "suggestion par défaut."
    )
