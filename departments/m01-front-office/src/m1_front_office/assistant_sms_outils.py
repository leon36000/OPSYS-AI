"""Outils de l'assistant SMS de M1 (M1.7) : préparer le message exact, le demander au sas, lire la session.

Aucun outil n'envoie : l'envoi d'un SMS est une demande N4 sur l'outil existant `m1_emettre_notification` (file
d'approbation d'une personne), avec le TEXTE EXACT du brouillon. Au moment où une personne approuve, `garde_execution`
revérifie que la conversation n'est pas retirée (STOP) et que le message est bien un brouillon demandé : un STOP
arrivé entre la demande et l'approbation annule l'envoi. Le transport SMS réel n'existe pas ici :
`m1_emettre_notification` écrit sur un bus en mode ombre, donc « envoyé » veut dire « approuvé par une personne et
remis au bus de test », jamais « livré ».
"""

from __future__ import annotations

import re
from typing import Any

from opsys import approbations, stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import assistant_sms as sms
from . import gabarits as gb
from . import horodatage as controle_horodatage
from . import outils as _o

DEPARTEMENT = "m01-front-office"
REGISTRE = "sms_assistant"
PREFIXE_CANAL = "sms:"
_CONVERSATION = re.compile(r"^sms-[0-9a-f]{24}$")


def _reg() -> Any:
    return stockage.maillons(DEPARTEMENT, REGISTRE)


def _refus(code: str, detail: str) -> Any:
    """Un refus typé : `ValueError("CODE: détail")`, que le répartiteur d'outils rend en refus métier (même idiome que
    `courriel_outils`). Ne rend jamais : l'agent lit le code et corrige."""
    raise ValueError(f"{code}: {detail}")


def _traduire(exc: Exception) -> dict[str, Any]:
    code, _, detail = str(exc).partition(": ")
    return _refus(code, detail)


def _statuts(cnx: Any, lignes: list[dict[str, Any]]) -> dict[str, str]:
    res = {}
    for m in lignes:
        if m["type_entree"] == sms.TYPE_DEMANDE:
            d = approbations.lire(cnx, m["demande_id"])
            if d is not None:
                res[m["demande_id"]] = d["statut"]
    return res


def _etat(conversation_id: str, maintenant: str) -> tuple[sms.EtatSms, dict[str, dict[str, Any]]]:
    cnx = stockage.connexion_courante()
    if cnx is None:
        raise ValueError("REJ-SMS-BASE: l'assistant SMS vit dans la base de l'instance")
    lignes = list(_reg())
    statuts = _statuts(cnx, lignes)
    e = sms.etat_conversation(_o._obtenir_registre().lire(), lignes, conversation_id, maintenant, statuts)
    return e, sms.brouillons(lignes, conversation_id, statuts)


def _instant(horodatage: str) -> str:
    quand = _o._horodatage_faisant_foi(horodatage)
    controle_horodatage.valider_horodatage(quand)
    return quand


def _actives(gabarit_id: str, cle: str) -> tuple[str, ...]:
    from . import apprentissage, tri_courriel_outils

    return apprentissage.phrases_gabarit(tri_courriel_outils.etat_apprentissage(), gabarit_id, cle)


def preparer_message_sms(
    conversation_id: str, gabarit_id: str, variables: dict[str, str], horodatage: str
) -> dict[str, Any]:
    if not _CONVERSATION.fullmatch(conversation_id or ""):
        return _refus("REJ-SMS-CONVERSATION", "identifiant de conversation SMS invalide")
    maintenant = _instant(horodatage)
    g = gb.GABARITS.get(gabarit_id)
    if g is None:
        return _refus("REJ-M1-GABARIT-INCONNU", "gabarit inconnu")
    e, drafts = _etat(conversation_id, maintenant)
    try:
        sms.autoriser(e, g, drafts)
        _, texte = gb.rendre(gabarit_id, variables, _actives(gabarit_id, f"{conversation_id}|{gabarit_id}"))
    except (sms.RefusSms, gb.RefusGabarit) as exc:
        return _traduire(exc)
    bid = sms.identifiant_brouillon(conversation_id, gabarit_id, texte)
    existant = drafts.get(bid)
    if existant is not None and existant["statut"] != "REFUSE":
        return {
            "accepte": True,
            "resultat": {"brouillon_id": bid, "statut": existant["statut"], "texte": texte, "deja_prepare": True},
        }
    _reg().append(
        {
            "type_entree": sms.TYPE_BROUILLON,
            "horodatage": maintenant,
            "conversation_id": conversation_id,
            "brouillon_id": bid,
            "gabarit_id": gabarit_id,
            "gabarit_version": g.version,
            "texte": texte,
        }
    )
    return {
        "accepte": True,
        "resultat": {
            "brouillon_id": bid,
            "statut": "BROUILLON",
            "texte": texte,
            "deja_prepare": False,
            "etat": e.etat,
            "consigne": "Brouillon rangé, rien n'est envoyé. Demande l'envoi avec m1_sms_demander_envoi : une personne "
            "approuve le texte exact.",
        },
    }


def demander_envoi_sms(brouillon_id: str, conversation_id: str, horodatage: str) -> dict[str, Any]:
    if not _CONVERSATION.fullmatch(conversation_id or ""):
        return _refus("REJ-SMS-CONVERSATION", "identifiant de conversation SMS invalide")
    maintenant = _instant(horodatage)
    e, drafts = _etat(conversation_id, maintenant)
    b = drafts.get(brouillon_id)
    if b is None:
        return _refus("REJ-SMS-BROUILLON-INCONNU", "ce brouillon n'existe pas pour cette conversation")
    if b["statut"] != "BROUILLON":
        return _refus(
            "REJ-SMS-DEJA-DEMANDE",
            f"brouillon « {b['statut']} » : un envoi n'est jamais redemandé ni rejoué ; "
            "un nouveau message est un nouveau brouillon",
        )
    try:
        sms.autoriser(e, gb.GABARITS[b["gabarit_id"]], drafts)
    except sms.RefusSms as exc:
        if not str(exc).startswith("REJ-SMS-DIVULGATION-DEJA"):  # le brouillon de divulgation lui-même est celui-ci
            return _traduire(exc)
    demande = approbations.creer_demande(
        stockage.connexion_courante(),
        DEPARTEMENT,
        "m1_emettre_notification",
        {"canal": PREFIXE_CANAL + conversation_id, "message": b["texte"]},
        niveau=Niveau.N4,
        motif=f"SMS préparé par M1 (gabarit {b['gabarit_id']}) : approuver le texte EXACT ; aucun envoi réel n'existe.",
    )
    _reg().append(
        {
            "type_entree": sms.TYPE_DEMANDE,
            "horodatage": maintenant,
            "conversation_id": conversation_id,
            "brouillon_id": brouillon_id,
            "demande_id": demande,
        }
    )
    return {
        "accepte": True,
        "resultat": {
            "statut": "en_attente_approbation",
            "demande_id": demande,
            "brouillon_id": brouillon_id,
            "consigne": "Demande déposée dans la file d'approbation (N4) : rien n'est envoyé. "
            "Ne la présente pas comme faite.",
        },
    }


def lire_session_sms(conversation_id: str, horodatage: str) -> dict[str, Any]:
    if not _CONVERSATION.fullmatch(conversation_id or ""):
        return _refus("REJ-SMS-CONVERSATION", "identifiant de conversation SMS invalide")
    e, drafts = _etat(conversation_id, _instant(horodatage))
    permis = []
    for g in gb.GABARITS.values():
        if g.canal != "sms":
            continue
        try:
            sms.autoriser(e, g, drafts)
            permis.append(g.identifiant)
        except sms.RefusSms:
            continue
    return {
        "accepte": True,
        "resultat": {
            **e.vers_json(),
            "gabarits_permis": permis,
            "brouillons": [
                {"brouillon_id": k, "gabarit_id": v["gabarit_id"], "statut": v["statut"]} for k, v in drafts.items()
            ],
            "limite": "Le transport SMS réel n'existe pas : « ENVOYE_INCONNU » veut dire approuvé et remis au bus "
            "de test.",
        },
    }


def garde_execution(canal: str, message: str) -> None:
    """Appelée par `m1_emettre_notification` quand le canal est `sms:<conversation>` : LÈVE un refus typé si le
    correspondant s'est retiré (STOP) ou si le message n'est pas un brouillon demandé (le texte exact approuvé). Si elle
    rend, l'envoi peut continuer."""
    conversation_id = canal[len(PREFIXE_CANAL) :]
    if not _CONVERSATION.fullmatch(conversation_id):
        _refus("REJ-SMS-CONVERSATION", "identifiant de conversation SMS invalide")
    cnx = stockage.connexion_courante()
    if cnx is None:
        _refus("REJ-SMS-BASE", "garde d'envoi SMS hors transaction : refus")
    lignes = list(_reg())
    statuts = _statuts(cnx, lignes)
    e = sms.etat_conversation(
        _o._obtenir_registre().lire(), lignes, conversation_id, "9999-12-31T00:00:00+00:00", statuts
    )
    if e.etat == "retire":
        _refus("REJ-SMS-RETRAIT", "le correspondant s'est retiré (STOP) : l'envoi approuvé est annulé")
    drafts = sms.brouillons(lignes, conversation_id, statuts)
    if not any(b["texte"] == message and b["statut"] == "DEMANDE" for b in drafts.values()):
        _refus("REJ-SMS-MESSAGE-NON-APPROUVE", "le message n'est pas un brouillon demandé de cette conversation")


_HORO = {"type": "string", "description": "ISO-8601 avec fuseau ; l'heure du serveur fait foi pour un appareil."}
_CONV = {
    "type": "string",
    "pattern": "^sms-[0-9a-f]{24}$",
    "description": "Identifiant de conversation SMS (rendu par la réception d'un message de canal).",
}


def outils_sms() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m1_sms_preparer_message",
            description=(
                "Prépare le message SMS EXACT d'un gabarit fixe (divulgation et demande d'opt-in, accusé de "
                "photos, « je vais vérifier avec l'équipe », paiement par l'équipe, rappel de rendez-vous), après "
                "contrôle de l'état de la conversation : divulgation d'abord, opt-in exprès pour un rappel, STOP "
                "prime, fenêtre de réponse. Rien n'est envoyé."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "conversation_id": _CONV,
                    "gabarit_id": {
                        "type": "string",
                        "enum": [g.identifiant for g in gb.GABARITS.values() if g.canal == "sms"],
                    },
                    "variables": {"type": "object", "additionalProperties": {"type": "string", "maxLength": 120}},
                    "horodatage": _HORO,
                },
                "required": ["conversation_id", "gabarit_id", "variables", "horodatage"],
                "additionalProperties": False,
            },
            fonction=preparer_message_sms,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m1_sms_demander_envoi",
            description=(
                "DEMANDE l'envoi (N4) du texte exact d'un brouillon SMS : dépose une demande dans la file "
                "d'approbation d'une personne. Rien n'est envoyé par cet outil ; un envoi n'est jamais redemandé "
                "ni rejoué (issue inconnue)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "brouillon_id": {"type": "string", "pattern": "^sb-[0-9a-f]{16}$"},
                    "conversation_id": _CONV,
                    "horodatage": _HORO,
                },
                "required": ["brouillon_id", "conversation_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=demander_envoi_sms,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m1_lire_session_sms",
            description=(
                "État d'une conversation SMS : inconnue, ouverte, opt-in demandé, opt-in exprès ou retirée (STOP), "
                "gabarits permis maintenant, brouillons et leur statut. Lecture."
            ),
            parametres={
                "type": "object",
                "properties": {"conversation_id": _CONV, "horodatage": _HORO},
                "required": ["conversation_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=lire_session_sms,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
    )
