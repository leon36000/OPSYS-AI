"""Le canal de M1 pour les messages à un client préparés par M4 (M4.14 côté M1, interconnexion M4 -> M1).

`m4.message_client_brouillon_pret` : M4 a estimé la fenêtre d'arrivée d'une équipe chez un client qui a un
consentement de
suivi ACTIF (finalité, chantier et canal), et a préparé un texte FIXE qui a passé le garde-fou de texte (une fenêtre de
temps, l'avertissement « estimation, pas une promesse », le moyen de se retirer). M4 n'envoie rien et n'a aucune
coordonnée.
M1, qui détient les coordonnées par `lead_id`, le reprend :

- canal `courriel` : un BROUILLON dans le sas d'envoi ordinaire (`courriel_connecteurs.envoi`), depuis un compte
connecté
  qui permet l'envoi, vers l'adresse que le lead a donnée à M1. L'envoi reste une demande N3
  (`m1_demander_envoi_courriel`)
  qu'une PERSONNE approuve sur l'empreinte exacte : rien ne part ici ;
- canal `sms` : l'assistant SMS de M1 ne sait préparer que ses gabarits fixes (conversation, consentement,
divulgation) ;
  un texte venu d'un autre département n'y entre pas. Le message est rangé `sms_a_reprendre` (journal), jamais envoyé ni
  déposé ailleurs : un humain ou un futur gabarit le reprend.

M1 ne retouche ni le texte ni la fenêtre (source de vérité : M4) et vérifie, de son côté, ce que M4 ne voit pas : que le
correspondant ne s'est pas retiré depuis (STOP rangé par M1), que le lead existe chez lui et porte une adresse, que le
message n'est pas échu (`conserve_jusqu_au`, comparé à l'instant de la livraison du bus - aucune horloge ici).

Idempotent : une clé de CONTENU (intervention, canal, empreinte du texte et de la fenêtre) ; le même message sous un
autre
`evenement_id` n'écrit rien. Indisponibilité (aucun compte d'envoi connecté) : le consommateur LÈVE, le bus réessaie
avec
recul puis met l'événement en quarantaine visible (même patron que la commande de M6) ; un refus déterministe est rangé.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

from opsys import stockage
from opsys.courriel_connecteurs import comptes, envoi
from opsys.courriel_connecteurs.erreurs import ErreurCourriel
from opsys.evenements.repartiteur import horodatage_livraison

from . import courriel_outils, retrait
from . import outils as _o
from .registre import TYPE_REPONSE_COURRIEL

DEPARTEMENT = "m01-front-office"
REGISTRE = "messages_clients_m4"
TYPE_ENTREE = "message_client_m4"
PREFIXE_SIGNAL = "eta:"
OBJET = "Votre fenêtre d'arrivée estimée"


def _reg() -> Any:
    return stockage.maillons(DEPARTEMENT, REGISTRE)


def cle(charge: dict[str, Any]) -> str:
    empreinte = hashlib.sha256(
        "|".join((charge["texte"], charge["fenetre_debut"], charge["fenetre_fin"])).encode("utf-8")
    ).hexdigest()[:24]
    return f"{charge['intervention_id']}|{charge['canal']}|{empreinte}"


def _compte_d_envoi() -> str | None:
    cnx = stockage.connexion_courante()
    candidats = [c for c in comptes.lister(cnx) if c["usage"] == "lecture_envoi" and c["etat"] == "connecte"]
    return candidats[0]["compte_id"] if candidats else None


def _lead(lignes: list[dict[str, Any]], lead_id: str) -> dict[str, Any] | None:
    trouve = None
    for ligne in lignes:
        lead = ligne.get("lead")
        if ligne.get("type_entree") == "lead_emis" and isinstance(lead, dict) and lead.get("lead_id") == lead_id:
            trouve = ligne
    return trouve


def _echu(conserve_jusqu_au: str, maintenant: dt.datetime | None) -> bool:
    if maintenant is None:
        return False
    try:
        limite = dt.datetime.fromisoformat(conserve_jusqu_au)
    except ValueError:
        return True  # une échéance illisible n'est jamais présumée valide
    return limite.tzinfo is None or limite <= maintenant


def _ranger(charge: dict[str, Any], statut: str, **plus: Any) -> None:
    _reg().append(
        {
            "type_entree": TYPE_ENTREE,
            "horodatage": courriel_outils._horodatage(),
            "cle": cle(charge),
            "intervention_id": charge["intervention_id"],
            "lead_id": charge["lead_id"],
            "canal": charge["canal"],
            "statut": statut,
            **plus,
        }
    )


def recevoir_message_client_brouillon(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur de `m4.message_client_brouillon_pret` (voir le module)."""
    registre = _reg()
    ident = cle(charge)
    if any(m.get("cle") == ident for m in registre):
        return {"deja_prepare": True}
    if _echu(charge["conserve_jusqu_au"], horodatage_livraison()):
        _ranger(charge, "echu")
        return {"statut": "echu"}
    lignes = _o._obtenir_registre().lire()
    ligne_lead = _lead(lignes, charge["lead_id"])
    if ligne_lead is None:
        _ranger(charge, "refuse", code="REJ-M1-MESSAGE-LEAD-INCONNU")
        return {"refuse": "REJ-M1-MESSAGE-LEAD-INCONNU"}
    if retrait.alerte_de_retrait(lignes, ligne_lead.get("conversation_id", "")) is not None:
        _ranger(charge, "refuse", code="REJ-M1-MESSAGE-RETRAIT-CONSENTEMENT")
        return {"refuse": "REJ-M1-MESSAGE-RETRAIT-CONSENTEMENT"}
    if charge["canal"] == "sms":
        _ranger(charge, "sms_a_reprendre")
        return {"statut": "sms_a_reprendre"}
    contact = ligne_lead["lead"].get("contact") if isinstance(ligne_lead["lead"].get("contact"), dict) else {}
    adresse = contact.get("courriel")
    if not isinstance(adresse, str) or not adresse.strip():
        _ranger(charge, "refuse", code="REJ-M1-MESSAGE-SANS-COURRIEL")
        return {"refuse": "REJ-M1-MESSAGE-SANS-COURRIEL"}
    compte_id = _compte_d_envoi()
    if compte_id is None:
        raise ValueError(
            "REJ-M1-MESSAGE-AUCUN-COMPTE: aucun compte courriel connecté avec l'usage lecture_envoi : connecter un "
            "compte (console, Plateforme > Connecteurs) puis laisser le bus réessayer"
        )
    try:
        brouillon = envoi.creer_brouillon(
            stockage.connexion_courante(),
            DEPARTEMENT,
            compte_id,
            a=[adresse.strip()],
            objet=OBJET,
            corps=charge["texte"],
        )
    except ErreurCourriel as exc:
        _ranger(charge, "refuse", code=exc.code)
        return {"refuse": exc.code}
    _o._obtenir_registre().ajouter(
        {
            "type_entree": TYPE_REPONSE_COURRIEL,
            "horodatage": courriel_outils._horodatage(),
            "signal_id": PREFIXE_SIGNAL + charge["intervention_id"] + ":" + ident.rsplit("|", 1)[1],
            "etape": "preparee",
            "brouillon_id": brouillon.brouillon_id,
            "revision": brouillon.revision,
            "empreinte": brouillon.empreinte,
            "compte_id": compte_id,
        }
    )
    _ranger(charge, "brouillon", brouillon_id=brouillon.brouillon_id, compte_id=compte_id)
    return {"brouillon_id": brouillon.brouillon_id, "statut": "brouillon"}
