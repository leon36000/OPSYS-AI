"""Assistant SMS de M1 (M1.7) : la machine d'états d'une conversation SMS et sa gouvernance. Module pur.

Ce que ce module garantit (hors ligne, sur doubles) ; ce qu'il ne garantit PAS est dit dans
docs/architecture/M1-M6-LEA-ROSALIE.md :

- **Divulgation d'abord** (même contrat que la session voix, `opsys.avatars_voix.session`) : le premier message
sortant d'une conversation est la divulgation « assistant virtuel (intelligence artificielle) », produite par un
gabarit, pas par un modèle ; aucun autre message ne part avant qu'elle ait été livrée.
- **Opt-in exprès pour tout ce qui est proactif** : un rappel n'est permis qu'après la divulgation ET une réponse OUI du
  correspondant. Une réponse à un message du client est permise dans la fenêtre de réponse (24 h), pas au-delà.
- **STOP prime sur tout** : après un retrait, aucun message n'est préparé, demandé ni envoyé. Un STOP qui arrive
entre la demande et l'approbation annule l'envoi (garde à l'exécution).
- **Message exact approuvé, jamais rejoué** : un brouillon (texte, empreinte) est demandé UNE fois au sas
d'approbation ; son issue après approbation est « envoyé, résultat inconnu » : il n'est jamais redemandé ni renvoyé.
- **Rien n'est une preuve de livraison** : le transport SMS réel n'existe pas dans ce dépôt (le bus d'émission est un
double).

Aucune horloge, aucune base : l'adaptateur fournit les lignes et l'instant.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

from .conversation import MARQUEUR_RETRAIT
from .gabarits import GABARITS, Gabarit

ETATS = ("inconnu", "ouverte", "opt_in_demande", "opt_in", "retire")
FENETRE_REPONSE_H = 24
TYPE_BROUILLON = "sms_brouillon"
TYPE_DEMANDE = "sms_demande"
TYPE_CLOTURE = "sms_cloture"
STATUTS_BROUILLON = ("BROUILLON", "DEMANDE", "ENVOYE_INCONNU", "REFUSE", "ECHEC_INCONNU", "ANNULE_RETRAIT")
_OUI = re.compile(r"^[\W_]*(oui|yes|ok|d'accord|daccord)[\W_]*$")


class RefusSms(ValueError):
    """Refus typé `REJ-SMS-…` : le message commence par le code."""


def _sans_accent(texte: str) -> str:
    d = unicodedata.normalize("NFKD", texte.lower().replace("’", "'"))
    return "".join(c for c in d if not unicodedata.combining(c)).strip()


def est_oui(texte: str) -> bool:
    return _OUI.fullmatch(_sans_accent(texte)) is not None


def _t(v: str) -> dt.datetime:
    return dt.datetime.fromisoformat(v)


def identifiant_brouillon(conversation_id: str, gabarit_id: str, texte: str) -> str:
    return "sb-" + hashlib.sha256(f"{conversation_id}|{gabarit_id}|{texte}".encode()).hexdigest()[:16]


@dataclasses.dataclass(frozen=True)
class EtatSms:
    conversation_id: str
    etat: str
    dernier_entrant_le: str | None
    divulgation_livree: bool
    divulgation_demandee: bool
    opt_in_le: str | None
    retire_le: str | None
    reponse_possible: bool

    def vers_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def brouillons(
    lignes_sms: Iterable[Mapping[str, Any]], conversation_id: str, statuts_demandes: Mapping[str, str]
) -> dict[str, dict[str, Any]]:
    """Les brouillons d'une conversation avec leur statut courant. `statuts_demandes` : statut de chaque demande du sas
    (en_attente, executee, refusee, echec), lu par l'adaptateur."""
    res: dict[str, dict[str, Any]] = {}
    for m in lignes_sms:
        if m.get("conversation_id") != conversation_id:
            continue
        if m["type_entree"] == TYPE_BROUILLON:
            res[m["brouillon_id"]] = {**m, "statut": "BROUILLON", "demande_id": None}
        elif m["type_entree"] == TYPE_DEMANDE and m["brouillon_id"] in res:
            res[m["brouillon_id"]]["statut"] = "DEMANDE"
            res[m["brouillon_id"]]["demande_id"] = m["demande_id"]
        elif m["type_entree"] == TYPE_CLOTURE and m["brouillon_id"] in res:
            res[m["brouillon_id"]]["statut"] = m["statut"]
    for b in res.values():
        if b["statut"] == "DEMANDE":
            s = statuts_demandes.get(b["demande_id"])
            b["statut"] = {"executee": "ENVOYE_INCONNU", "refusee": "REFUSE", "echec": "ECHEC_INCONNU"}.get(
                s, "DEMANDE"
            )
    return res


def etat_conversation(
    lignes_m1: Iterable[Mapping[str, Any]],
    lignes_sms: Iterable[Mapping[str, Any]],
    conversation_id: str,
    maintenant: str,
    statuts_demandes: Mapping[str, str],
) -> EtatSms:
    lignes_m1 = list(lignes_m1)
    entrants = [
        m
        for m in lignes_m1
        if m.get("type_entree") == "signal" and m.get("source") == "sms" and m.get("conversation_id") == conversation_id
    ]
    retrait = next(
        (
            m
            for m in lignes_m1
            if m.get("type_entree") == "alerte"
            and m.get("marqueur") == MARQUEUR_RETRAIT
            and m.get("conversation_id") == conversation_id
        ),
        None,
    )
    lignes_sms = list(lignes_sms)
    drafts = brouillons(lignes_sms, conversation_id, statuts_demandes)
    divulgations = [b for b in drafts.values() if GABARITS[b["gabarit_id"]].divulgation]
    livree = [b for b in divulgations if b["statut"] == "ENVOYE_INCONNU"]
    demandee = [b for b in divulgations if b["statut"] in ("DEMANDE", "ENVOYE_INCONNU")]
    opt_in_le = None
    if livree:
        t0 = _t(min(b["horodatage"] for b in livree))
        oui = [m for m in entrants if _t(m["horodatage"]) >= t0 and est_oui(m.get("contenu_filtre", ""))]
        opt_in_le = oui[0]["horodatage"] if oui else None
    dernier = max((m["horodatage"] for m in entrants), key=_t, default=None)
    now = _t(maintenant)
    fenetre = dernier is not None and _t(dernier) <= now <= _t(dernier) + dt.timedelta(hours=FENETRE_REPONSE_H)
    if retrait is not None:
        etat = "retire"
    elif opt_in_le is not None:
        etat = "opt_in"
    elif demandee:
        etat = "opt_in_demande"
    elif entrants:
        etat = "ouverte"
    else:
        etat = "inconnu"
    return EtatSms(
        conversation_id,
        etat,
        dernier,
        bool(livree),
        bool(demandee),
        opt_in_le,
        None if retrait is None else retrait["horodatage"],
        fenetre and retrait is None,
    )


def autoriser(e: EtatSms, g: Gabarit, drafts: Mapping[str, Mapping[str, Any]]) -> None:
    """Lève `RefusSms` si ce gabarit ne peut pas être préparé maintenant."""
    if g.canal != "sms":
        raise RefusSms("REJ-SMS-CANAL: ce gabarit n'est pas un gabarit SMS")
    if e.etat == "retire":
        raise RefusSms("REJ-SMS-RETRAIT: le correspondant s'est retiré (STOP) : aucun message n'est préparé")
    if e.etat == "inconnu":
        raise RefusSms("REJ-SMS-AUCUN-ENTRANT: M1 n'écrit par SMS qu'à un correspondant qui lui a écrit")
    if g.divulgation:
        if e.divulgation_demandee:
            raise RefusSms("REJ-SMS-DIVULGATION-DEJA: la divulgation est déjà demandée ou livrée")
        if not e.reponse_possible:
            raise RefusSms("REJ-SMS-FENETRE: la fenêtre de réponse de 24 h est échue")
        return
    if not e.divulgation_livree:
        raise RefusSms(
            "REJ-SMS-DIVULGATION-REQUISE: la divulgation « assistant virtuel » doit être livrée avant tout "
            "autre message"
        )
    if g.proactif:
        if e.etat != "opt_in":
            raise RefusSms("REJ-SMS-OPT-IN-REQUIS: un message proactif exige la réponse OUI du correspondant")
    elif not e.reponse_possible:
        raise RefusSms("REJ-SMS-FENETRE: la fenêtre de réponse de 24 h est échue")
