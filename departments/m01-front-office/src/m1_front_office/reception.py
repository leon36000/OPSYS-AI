"""Réception d'un message que le core livre à M1 par un canal (PLAN T2.1-a).

Le canal (extension `sms` d'OPSYS-CORE, plus tard `imap`) route le message vers l'agent M1 et lui donne, dans
des blocs que la plateforme génère, le canal, l'expéditeur, l'identifiant du message et l'heure de réception.
Ces champs sont recopiés par l'agent dans l'outil `m1_recevoir_message_canal` ; ce module en tire, par du
code, tout ce que l'agent ne doit pas inventer :

- l'identité du correspondant (numéro E.164 ou adresse), validée, jamais lue dans le texte du client ;
- l'identifiant de conversation, stable par correspondant et par canal, sans renseignement personnel ;
- l'identifiant du signal, qui rend la réception idempotente ;
- le contact du lead (l'identité du canal, seule : M2 en tire le `client_id`, il ne doit pas varier avec ce
  que le client écrit) ;
- la clé de session du core, que M10 lie à l'affaire ;
- le retrait de consentement (STOP), reconnu sur le message entier.

Module pur : aucune horloge, aucun accès à la base ni au réseau. Chaque refus est un `ValueError` qui dit
quoi corriger ; rien n'a été écrit quand il est levé.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from email.utils import parseaddr

from opsys import canaux

from . import horodatage

DEPARTEMENT = "m01-front-office"

# Canal du core (celui que la plateforme donne à l'agent) -> valeur du champ `canal` du contrat M1 -> M2.
# Un SMS est du « texte » ; `source` du lead garde, lui, l'identifiant du canal du core.
CANAL_DU_CONTRAT = {"sms": "texte", "courriel": "courriel"}

TAILLE_MAX_TEXTE = 20_000  # octets d'un courriel que l'extension imap transmet (`maxBytes`, 20 000 par défaut)
TAILLE_MAX_IDENTIFIANT = 200

# Même forme que `looksLikeSmsPhoneNumber` de l'extension sms (`core/extensions/sms/src/phone.ts`).
_E164 = re.compile(r"^\+[1-9]\d{6,14}$")
_ADRESSE = re.compile(r"^[a-z0-9._%+'-]{1,64}@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")
_IDENTIFIANT = re.compile(rf"^[^\s\x00-\x1f\x7f]{{1,{TAILLE_MAX_IDENTIFIANT}}}$")
# Mots que les opérateurs traitent comme un retrait (STOP de Twilio et équivalents français), sur le message ENTIER.
_MOTS_DE_RETRAIT = "stop|stopall|arret|arreter|desabonner|desabonnement|unsubscribe|cancel|end|quit"
_RETRAIT = re.compile(rf"^[\W_]*({_MOTS_DE_RETRAIT})[\W_]*$")


# Heure telle que le core l'écrit au modèle dans « Conversation info » (`core/src/infra/format-time/
# format-datetime.ts`, `formatZonedTimestamp`) : « Tue 2026-09-29 09:15:30 EDT », semaine incluse « pour que les
# modèles n'aient pas à la déduire ». Le modèle la recopie ; c'est ce code, pas lui, qui la convertit en ISO-8601.
_HEURE_DE_PLATEFORME = re.compile(
    r"^(?:(?P<jour>Mon|Tue|Wed|Thu|Fri|Sat|Sun) )?(?P<date>\d{4}-\d{2}-\d{2}) (?P<heure>\d{2}:\d{2}(?::\d{2})?)"
    r" (?P<zone>[A-Z]{3,4}|(?:GMT|UTC)[+-]\d{1,2}(?::\d{2})?)$"
)
_ZONES_NOMMEES = {"UTC": 0, "GMT": 0, "EST": -300, "EDT": -240}  # minutes ; Québec : EST l'hiver, EDT l'été


@dataclass(frozen=True)
class MessageRecu:
    """Un message de canal, prêt à traiter : tout ici vient de la plateforme ou d'un calcul, rien du client."""

    canal: str
    canal_contrat: str
    correspondant: str
    contact: dict[str, str]
    conversation_id: str
    signal_id: str
    horodatage: str
    contenu: str
    retrait: bool
    cle_session: str | None


def _sans_accent_minuscule(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def est_retrait_de_consentement(texte: str) -> bool:
    """Vrai si le message ENTIER est un mot de retrait (« STOP », « Arrêt. »). Jamais une phrase qui en contient un :
    « arrêt de mes gouttières » est une demande."""
    return _RETRAIT.fullmatch(_sans_accent_minuscule(texte).strip()) is not None


def correspondant_du_canal(canal: str, expediteur: str) -> tuple[str, dict[str, str]]:
    """`(correspondant normalisé, contact)` : le numéro E.164 d'un SMS, l'adresse d'un courriel.

    Le contact ne porte que cette identité : pas de nom (celui d'un courriel est écrit par l'expéditeur), pas le
    numéro ou l'adresse que le texte pourrait mentionner. M2 tire le `client_id` du contact entier : un même
    correspondant doit toujours donner le même.
    """
    if canal not in CANAL_DU_CONTRAT:
        raise ValueError(f"canal inconnu {canal!r} (attendu : {', '.join(sorted(CANAL_DU_CONTRAT))})")
    if not isinstance(expediteur, str) or not expediteur.strip():
        raise ValueError("expediteur requis : recopie l'expéditeur du bloc « Conversation info » du message")
    if canal == "sms":
        numero = expediteur.strip()
        if not _E164.fullmatch(numero):
            raise ValueError(
                f"expediteur {expediteur!r} : un numéro au format E.164 est attendu pour un SMS (ex. +15145550142)"
            )
        return numero, {"telephone": numero}
    adresse = parseaddr(expediteur)[1].strip().lower()
    if not _ADRESSE.fullmatch(adresse):
        raise ValueError(f"expediteur {expediteur!r} : une adresse courriel valide est attendue")
    return adresse, {"courriel": adresse}


def identifiant_de_conversation(canal: str, correspondant: str) -> str:
    """Stable par (canal, correspondant), et sans le numéro ni l'adresse : c'est une empreinte."""
    empreinte = hashlib.sha256(f"{len(canal)}:{canal}|{len(correspondant)}:{correspondant}".encode()).hexdigest()
    return f"{canal}-{empreinte[:24]}"


def heure_de_reception(recu_le: str) -> str:
    """L'heure de réception en ISO-8601 avec fuseau : donnée déjà ISO telle quelle, ou l'heure de la plateforme
    (`Tue 2026-09-29 09:15:30 EDT`) convertie par ce code. Lève `ValueError` si elle n'est ni l'une ni l'autre :
    fuseau inconnu, jour de la semaine qui ne correspond pas à la date, date impossible.

    Le jour de la semaine, que la plateforme écrit pour qu'aucun modèle n'ait à le déduire, sert ici de contrôle : un
    texte recopié de travers ne passe pas.
    """
    if not isinstance(recu_le, str) or not recu_le.strip():
        raise ValueError("REJ-HORODATAGE-INVALIDE: recu_le requis (le champ timestamp de « Conversation info »)")
    brut = recu_le.strip()
    trouve = _HEURE_DE_PLATEFORME.fullmatch(brut)
    if trouve is None:
        horodatage.valider_horodatage(brut)  # ISO-8601 avec fuseau, sinon ValueError
        return brut
    zone = trouve["zone"]
    if zone in _ZONES_NOMMEES:
        minutes = _ZONES_NOMMEES[zone]
    elif zone[:3] in ("GMT", "UTC") and len(zone) > 3:
        signe = -1 if zone[3] == "-" else 1
        heures, _, reste = zone[4:].partition(":")
        minutes = signe * (int(heures) * 60 + int(reste or 0))
    else:
        raise ValueError(
            f"REJ-HORODATAGE-INVALIDE: fuseau {zone!r} non reconnu ; donne l'heure en ISO-8601 avec fuseau "
            "(ex. 2026-09-29T09:15:30-04:00)"
        )
    heure = trouve["heure"] if trouve["heure"].count(":") == 2 else trouve["heure"] + ":00"
    try:
        instant = dt.datetime.fromisoformat(f"{trouve['date']}T{heure}").replace(
            tzinfo=dt.timezone(dt.timedelta(minutes=minutes))
        )
    except (ValueError, OverflowError):
        raise ValueError(f"REJ-HORODATAGE-INVALIDE: {brut!r} n'est pas une date valide") from None
    if trouve["jour"] and instant.strftime("%a") != trouve["jour"]:
        raise ValueError(
            f"REJ-HORODATAGE-INVALIDE: {trouve['jour']} ne correspond pas au {trouve['date']} : "
            "recopie le champ timestamp tel quel"
        )
    return instant.isoformat()


def preparer(
    canal: str, expediteur: str, message_id: str, recu_le: str, texte: str, objet: str | None = None
) -> MessageRecu:
    """Valide un message de canal et en tire ce que le pipeline de M1 reçoit. Lève `ValueError` sinon."""
    correspondant, contact = correspondant_du_canal(canal, expediteur)
    if not isinstance(message_id, str) or not _IDENTIFIANT.fullmatch(message_id):
        raise ValueError(
            f"message_id requis : l'identifiant du message donné par la plateforme (sans espace, "
            f"{TAILLE_MAX_IDENTIFIANT} caractères au plus)"
        )
    recu_iso = heure_de_reception(recu_le)
    if not isinstance(texte, str) or not texte.strip():
        raise ValueError("texte requis : le corps du message, tel que reçu")
    if len(texte.encode("utf-8")) > TAILLE_MAX_TEXTE:
        raise ValueError(f"texte trop long (plus de {TAILLE_MAX_TEXTE} octets) : rien n'est traité")
    if objet is not None and not isinstance(objet, str):
        raise ValueError("objet : une chaîne est attendue")
    contenu = texte if not (objet and objet.strip()) else f"{objet.strip()}\n{texte}"
    un_canal = canaux.CANAUX.get(canal)
    par_correspondant = un_canal is not None and un_canal.session_par_correspondant
    return MessageRecu(
        canal=canal,
        canal_contrat=CANAL_DU_CONTRAT[canal],
        correspondant=correspondant,
        contact=contact,
        conversation_id=identifiant_de_conversation(canal, correspondant),
        signal_id=f"{canal}:{message_id}",
        horodatage=recu_iso,
        contenu=contenu,
        retrait=canal == "sms" and est_retrait_de_consentement(texte),
        cle_session=canaux.cle_session(DEPARTEMENT, canal, correspondant) if par_correspondant else None,
    )
