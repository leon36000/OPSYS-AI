"""Gabarits FIXES des relances : ce que M2 prépare, jamais ce qu'il envoie (PLAN T4.9 ; DEFINITION-PRODUIT §7 M2, règles
dures « pas de spam, pas d'agressivité, opt-in respecté, fréquence limitée, validation humaine au départ »).

Module PUR : aucune entrée-sortie, aucune horloge, aucun modèle. Un gabarit est un texte écrit ici, une fois, par (règle
de relance, canal) : rien n'y est composé, rien n'y est substitué. Aucun nom de client, aucun identifiant, aucun prix,
aucune date, aucune promesse : c'est ce que le garde-fou de texte partagé du socle (`opsys.garde_fou_texte`, PLAN
T4.17-c) refuse à un texte destiné à un client, et il le REFUSE ICI AU CHARGEMENT : un gabarit qui viole une règle
empêche le département de se charger (`verifier_gabarits`), il ne se découvre pas chez un client. Le contexte du
contrôle vient du département, jamais de l'appelant.

Trois natures de texte, un gabarit par règle et par canal :
  - `appel` : les points de l'appel, à l'usage du vendeur (une consigne INTERNE : elle n'est pas lue par le client, donc
    le garde-fou des textes de client ne s'y applique pas) ;
  - `sms` et `courriel` : le message à un client. Il porte la mention de retrait (STOP) de la politique de consentement
    (POLITIQUE-consentement-sms §4 : « le destinataire peut répondre STOP »), que M1 reconnaît comme un retrait.

Ce que ces textes ne règlent pas, et qu'ils laissent à la validation de Nathan (T3) et du juriste : l'identification de
l'expéditeur dans le corps du message et la formule de désabonnement du courriel (fédéral, CASL : « à vérifier »,
POLITIQUE §8.1). Rien n'est envoyé d'ici : l'envoi réel est T2.1-c (N4, humain).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opsys import garde_fou_texte

from .consentements import CANAL_APPEL, CANAUX_ECRITS

__all__ = [
    "GABARITS",
    "NATURE_MESSAGE",
    "NATURE_POINTS_D_APPEL",
    "PROFIL_RELANCE_CLIENT",
    "SMS_MAX_CARACTERES",
    "gabarit",
    "verifier_gabarits",
]

NATURE_POINTS_D_APPEL = "points_d_appel"
NATURE_MESSAGE = "message"

# Un SMS de deux segments au plus.
SMS_MAX_CARACTERES = 320

# Ce qu'un texte destiné à un client ne dit jamais, pour une relance. Aucun prix, aucune date ni promesse de délai,
# aucun engagement ferme, aucun aveu, aucun avis légal, aucune adresse, aucun contact, aucun nom, aucun identifiant
# interne, aucun lien, aucune exagération. L'ordre d'évaluation est celui du catalogue du socle.
PROFIL_RELANCE_CLIENT = garde_fou_texte.profil(
    "m2_relance_client",
    (
        garde_fou_texte.TEXTE_VIDE,
        garde_fou_texte.LIEN,
        garde_fou_texte.ADRESSE,
        garde_fou_texte.COORDONNEES,
        garde_fou_texte.NOM_CLIENT,
        garde_fou_texte.IDENTIFIANT_INTERNE,
        garde_fou_texte.PRIX_MONTANT,
        garde_fou_texte.DATE_EXECUTION,
        garde_fou_texte.PROMESSE_DE_DATE,
        garde_fou_texte.EXAGERATION,
        garde_fou_texte.ENGAGEMENT,
        garde_fou_texte.AVEU,
        garde_fou_texte.AVIS_LEGAL,
    ),
)

_MENTION_STOP_SMS = "Pour ne plus recevoir de messages, répondez STOP."
_MENTION_STOP_COURRIEL = "Pour ne plus recevoir de courriels de notre part, répondez STOP à ce message."

# Clé : (règle de relance, canal). Les règles sont celles de `relances.REGLES` ; un test vérifie que chaque couple
# (règle, canal) a son gabarit, ni un de plus ni un de moins.
GABARITS: Mapping[tuple[str, str], Mapping[str, Any]] = {
    ("relance_devis_sans_reponse", CANAL_APPEL): {
        "id": "relance_devis_appel", "version": 1, "nature": NATURE_POINTS_D_APPEL,
        "texte": (
            "1. Demander si le client a bien reçu la soumission.\n"
            "2. Demander s'il a des questions ou des ajustements à discuter.\n"
            "3. Demander si le projet est toujours d'actualité.\n"
            "4. Ne rien promettre : ni prix, ni date, ni garantie.\n"
            "5. Noter le résultat au dossier (interaction)."
        ),
    },
    ("relance_devis_sans_reponse", "sms"): {
        "id": "relance_devis_sms", "version": 1, "nature": NATURE_MESSAGE,
        "texte": (
            "Bonjour, nous faisons suite à la soumission que nous vous avons transmise. Avez-vous des questions ? "
            f"Nous serons heureux d'en discuter avec vous. {_MENTION_STOP_SMS}"
        ),
    },
    ("relance_devis_sans_reponse", "courriel"): {
        "id": "relance_devis_courriel", "version": 1, "nature": NATURE_MESSAGE,
        "texte": (
            "Objet : Suivi de votre soumission\n\n"
            "Bonjour,\n\n"
            "Nous faisons suite à la soumission que nous vous avons transmise. Avez-vous des questions ou des "
            "ajustements à discuter ? Nous serons heureux d'en parler avec vous.\n\n"
            "Cordialement,\nL'équipe\n\n"
            f"{_MENTION_STOP_COURRIEL}"
        ),
    },
    ("relance_lead_dormant", CANAL_APPEL): {
        "id": "relance_dormant_appel", "version": 1, "nature": NATURE_POINTS_D_APPEL,
        "texte": (
            "1. Demander si le projet est toujours d'actualité.\n"
            "2. Demander s'il manque une information pour avancer (photos, précisions).\n"
            "3. Ne rien promettre : ni prix, ni date, ni garantie.\n"
            "4. Noter le résultat au dossier (interaction)."
        ),
    },
    ("relance_lead_dormant", "sms"): {
        "id": "relance_dormant_sms", "version": 1, "nature": NATURE_MESSAGE,
        "texte": (
            "Bonjour, nous avons reçu votre demande il y a quelque temps. Votre projet est-il toujours d'actualité ? "
            f"N'hésitez pas à nous répondre. {_MENTION_STOP_SMS}"
        ),
    },
    ("relance_lead_dormant", "courriel"): {
        "id": "relance_dormant_courriel", "version": 1, "nature": NATURE_MESSAGE,
        "texte": (
            "Objet : Votre projet est-il toujours d'actualité ?\n\n"
            "Bonjour,\n\n"
            "Nous avons reçu votre demande il y a quelque temps. Votre projet est-il toujours d'actualité ? "
            "S'il vous manque une information, répondez simplement à ce message.\n\n"
            "Cordialement,\nL'équipe\n\n"
            f"{_MENTION_STOP_COURRIEL}"
        ),
    },
}


def gabarit(regle: str, canal: str) -> Mapping[str, Any] | None:
    """Le gabarit de cette règle pour ce canal, ou `None` : jamais un texte de repli."""
    return GABARITS.get((regle, canal))


def verifier_gabarits(gabarits: Mapping[tuple[str, str], Mapping[str, Any]]) -> list[str]:
    """Les défauts des gabarits donnés, un texte par défaut (liste vide : tout est sain).

    Un gabarit destiné à un client (`sms`, `courriel`) est passé par le garde-fou de texte partagé : chaque règle violée
    est dite avec son code de refus. Un SMS ne dépasse pas `SMS_MAX_CARACTERES`. Un message de client porte la mention
    STOP. Un gabarit sans texte, sans identifiant ou sans version est refusé."""
    defauts: list[str] = []
    for (regle, canal), modele in sorted(gabarits.items()):
        cle = f"{regle}/{canal}"
        texte = modele.get("texte")
        if not isinstance(texte, str) or not texte.strip():
            defauts.append(f"{cle} : texte vide")
            continue
        if not modele.get("id") or not isinstance(modele.get("version"), int):
            defauts.append(f"{cle} : identifiant ou version manquant")
        if canal not in CANAUX_ECRITS:
            continue
        defauts.extend(
            f"{cle} : {violation.regle} ({violation.detail})"
            for violation in garde_fou_texte.controler(texte, PROFIL_RELANCE_CLIENT)
        )
        if canal == "sms" and len(texte) > SMS_MAX_CARACTERES:
            defauts.append(f"{cle} : {len(texte)} caractères, {SMS_MAX_CARACTERES} au plus")
        if "STOP" not in texte:
            defauts.append(f"{cle} : la mention de retrait (STOP) manque")
    return defauts


# Un gabarit qui viole une règle empêche le département de se charger : on ne le découvre pas chez un client.
_DEFAUTS_AU_CHARGEMENT = verifier_gabarits(GABARITS)
if _DEFAUTS_AU_CHARGEMENT:
    raise ValueError("gabarits de relance refusés : " + " ; ".join(_DEFAUTS_AU_CHARGEMENT))
