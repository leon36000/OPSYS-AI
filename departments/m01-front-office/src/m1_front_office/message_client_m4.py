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

RETRAIT DU CONSENTEMENT DE SUIVI (`m4.consentement_suivi_retire`, Loi 25 : le retrait vaut tout de suite pour ce que M1
n'a pas envoyé). M4 seul connaît ce retrait ; il le publie, M1 le range (`retrait_suivi_m4`, append-only) et :

- refuse de créer un brouillon, ou d'en demander l'envoi, pour un message que ce retrait vise (ligne `suivi_retire`) ;
- marque `suivi_retire` les messages déjà rangés qui ne sont pas partis et, si leur brouillon attend une demande ou une
  approbation, le fait retomber en `BROUILLON` (l'approbation devient caduque : `modifier_brouillon` sans changer le
  texte) ; la demande N3 déjà ouverte reste dans le sas (une ligne du socle ne se réécrit pas) mais ne peut plus
  s'exécuter, et l'attente `suivi_retire_a_refuser` le dit à la direction. Un message déjà réservé, envoyé ou d'issue
  incertaine ne se rappelle pas : la ligne dit `neutralise: false` et l'état d'envoi au retrait ;
- ne lève jamais un retrait : il n'existe aucun événement qui le défasse. Un nouveau consentement recueilli APRÈS le
  retrait donne un autre brouillon (publié après), que ce retrait ne vise pas.

Quels messages un retrait vise-t-il ? L'ordre de livraison du bus n'est pas garanti : on ne se fie ni à l'ordre
d'arrivée ni à une horloge de M1. Un message est visé si (a) il s'appuie sur le consentement que le retrait termine
(`consentement_ligne_id` égaux), OU (b) il a été PUBLIÉ avant ou à l'instant de PUBLICATION du retrait (instant
donné par le bus), OU (c) l'un des deux instants manque (fail-closed). Le brouillon publié après un retrait suppose
un nouveau consentement (M4 ne prépare rien sans consentement actif).

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
from opsys.evenements.repartiteur import horodatage_livraison, instant_publication_livre

from . import courriel_outils, retrait
from . import outils as _o
from .registre import TYPE_REPONSE_COURRIEL

DEPARTEMENT = "m01-front-office"
REGISTRE = "messages_clients_m4"
TYPE_ENTREE = "message_client_m4"
PREFIXE_SIGNAL = "eta:"
OBJET = "Votre fenêtre d'arrivée estimée"
TYPE_RETRAIT = "retrait_suivi_m4"
STATUT_RETIRE = "suivi_retire"
CODE_RETIRE = "REJ-M1-MESSAGE-SUIVI-RETIRE"
ETAPE_RETIRE = "suivi_retire"
TYPE_ATTENTE = "suivi_retire_a_refuser"
# États du sas d'envoi à partir desquels un brouillon ne se rappelle plus.
_ENVOI_ENGAGE = ("ENVOI_RESERVE", "ENVOYE", "INCERTAIN", "ECHEC", "REFUSE")


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
            "consentement_ligne_id": charge.get("consentement_ligne_id"),
            "publie_le": instant_publication_livre(),
            **plus,
        }
    )


def recevoir_message_client_brouillon(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur de `m4.message_client_brouillon_pret` (voir le module)."""
    registre = _reg()
    ident = cle(charge)
    if any(m.get("cle") == ident for m in registre):
        return {"deja_prepare": True}
    publie_le = instant_publication_livre()
    if _retraits_visant(
        registre, charge["intervention_id"], charge["canal"], charge.get("consentement_ligne_id"), publie_le
    ):
        _ranger(charge, STATUT_RETIRE, code=CODE_RETIRE, neutralise=True, etat_envoi_au_retrait=None)
        return {"statut": STATUT_RETIRE, "refuse": CODE_RETIRE}
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


# ------------------------------------------------------------------------------------------------ le retrait de M4
def _instant_iso(texte: Any) -> dt.datetime | None:
    try:
        d = dt.datetime.fromisoformat(texte) if isinstance(texte, str) else None
    except ValueError:
        return None
    return d if d is not None and d.tzinfo is not None else None


def vise(
    consentement_ligne_id: Any, publie_le: Any, retrait: dict[str, Any]
) -> bool:
    """Ce retrait vise-t-il un message qui s'appuie sur `consentement_ligne_id` et a été publié à `publie_le` ? Voir le
    module : même consentement, OU publié avant ou à l'instant de publication du retrait, OU un instant manque."""
    if consentement_ligne_id is not None and consentement_ligne_id == retrait.get("consentement_ligne_id"):
        return True
    message, fin = _instant_iso(publie_le), _instant_iso(retrait.get("publie_le"))
    return message is None or fin is None or message <= fin


def _retraits_visant(
    registre: Any, intervention_id: str, canal: str, consentement_ligne_id: Any, publie_le: Any
) -> bool:
    return any(
        m.get("type_entree") == TYPE_RETRAIT
        and m.get("intervention_id") == intervention_id
        and m.get("canal") == canal
        and vise(consentement_ligne_id, publie_le, m)
        for m in registre
    )


def _dernier_par_cle(registre: Any) -> dict[str, dict[str, Any]]:
    """Le DERNIER état de chaque message (ligne `message_client_m4` de même `cle`)."""
    dernier: dict[str, dict[str, Any]] = {}
    for m in registre:
        if m.get("type_entree") == TYPE_ENTREE and isinstance(m.get("cle"), str):
            dernier[m["cle"]] = m
    return dernier


def _neutraliser(ligne: dict[str, Any]) -> dict[str, Any]:
    """Ce qu'on peut encore faire du brouillon d'un message retiré : rien s'il est déjà dans le sas d'envoi (réservé,
    envoyé, incertain), sinon le faire retomber en `BROUILLON` s'il attendait une approbation. LÈVE si le sas refuse :
    le bus réessaie, M1 ne dit jamais « retiré » d'un brouillon qu'il n'a pas pu neutraliser."""
    brouillon_id = ligne.get("brouillon_id")
    if not isinstance(brouillon_id, str):
        return {"neutralise": True, "etat_envoi_au_retrait": None, "demande_id": None}
    cnx = stockage.connexion_courante()
    statut = envoi.statut_brouillon(cnx, brouillon_id)
    etat = statut["statut"]
    if etat in _ENVOI_ENGAGE:
        return {"neutralise": False, "etat_envoi_au_retrait": etat, "demande_id": statut["demande_id"]}
    if etat in ("DEMANDE", "APPROUVE"):
        try:
            envoi.modifier_brouillon(
                cnx, DEPARTEMENT, brouillon_id, revision_attendue=statut["revision"]
            )
        except ErreurCourriel as exc:
            raise ValueError(
                f"{exc.code}: {exc.detail} (suivi retiré : le brouillon n'a pas pu être neutralisé)"
            ) from None
    return {"neutralise": True, "etat_envoi_au_retrait": etat, "demande_id": statut["demande_id"]}


def recevoir_consentement_suivi_retire(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur de `m4.consentement_suivi_retire` (voir le module). Atomique avec la livraison : si la
    neutralisation d'un brouillon échoue, rien n'est rangé et le bus réessaie."""
    registre = _reg()
    cle_retrait = "|".join(
        (charge["intervention_id"], charge["canal"], charge["retire_le"], charge["consentement_ligne_id"] or "")
    )
    if any(m.get("type_entree") == TYPE_RETRAIT and m.get("cle_retrait") == cle_retrait for m in registre):
        return {"deja_enregistre": True}
    retrait = {
        "type_entree": TYPE_RETRAIT,
        "horodatage": courriel_outils._horodatage(),
        "cle_retrait": cle_retrait,
        "intervention_id": charge["intervention_id"],
        "lead_id": charge["lead_id"],
        "canal": charge["canal"],
        "retire_le": charge["retire_le"],
        "consentement_ligne_id": charge["consentement_ligne_id"],
        "publie_le": instant_publication_livre(),
    }
    retires = neutralises = 0
    nouvelles: list[dict[str, Any]] = []
    for ligne in _dernier_par_cle(registre).values():
        if (
            ligne["statut"] not in ("brouillon", "sms_a_reprendre")
            or ligne["intervention_id"] != charge["intervention_id"]
            or ligne["canal"] != charge["canal"]
            or not vise(ligne.get("consentement_ligne_id"), ligne.get("publie_le"), retrait)
        ):
            continue
        issue = _neutraliser(ligne)
        nouvelles.append(
            {
                "type_entree": TYPE_ENTREE,
                "horodatage": courriel_outils._horodatage(),
                "cle": ligne["cle"],
                "intervention_id": ligne["intervention_id"],
                "lead_id": ligne["lead_id"],
                "canal": ligne["canal"],
                "statut": STATUT_RETIRE,
                "consentement_ligne_id": ligne.get("consentement_ligne_id"),
                "publie_le": ligne.get("publie_le"),
                "brouillon_id": ligne.get("brouillon_id"),
                "compte_id": ligne.get("compte_id"),
                "code": CODE_RETIRE,
                "retire_le": charge["retire_le"],
                **issue,
            }
        )
        retires += 1
        neutralises += int(issue["neutralise"] and ligne.get("brouillon_id") is not None)
    registre.append(retrait)
    for nouvelle in nouvelles:
        registre.append(nouvelle)
        brouillon_id = nouvelle.get("brouillon_id")
        if isinstance(brouillon_id, str):
            sas = envoi.statut_brouillon(stockage.connexion_courante(), brouillon_id)
            _o._obtenir_registre().ajouter(
                {
                    "type_entree": TYPE_REPONSE_COURRIEL,
                    "horodatage": courriel_outils._horodatage(),
                    "signal_id": PREFIXE_SIGNAL + nouvelle["intervention_id"] + ":" + nouvelle["cle"].rsplit("|", 1)[1],
                    "etape": ETAPE_RETIRE,
                    "brouillon_id": brouillon_id,
                    "revision": sas["revision"],
                    "empreinte": sas["empreinte"],
                    "compte_id": nouvelle.get("compte_id"),
                }
            )
    return {"retrait_enregistre": True, "messages_retires": retires, "brouillons_neutralises": neutralises}


def message_retire(brouillon_id: str) -> dict[str, Any] | None:
    """La ligne `suivi_retire` du message dont c'est le brouillon, ou `None` : lu par `m1_demander_envoi_courriel` et
    `m1_lire_reponse_courriel`."""
    trouve = None
    for ligne in _dernier_par_cle(_reg()).values():
        if ligne.get("brouillon_id") == brouillon_id and ligne["statut"] == STATUT_RETIRE:
            trouve = ligne
    return trouve


def attentes() -> list[dict[str, Any]]:
    """Une attente par demande N3 d'envoi encore ouverte pour un message dont le suivi a été retiré : la direction
    doit la REFUSER (elle ne peut plus s'exécuter). Aucun contact ni texte ; disparaît quand la demande est décidée.
    """
    cnx = stockage.connexion_courante()
    if cnx is None:
        return []
    from opsys import approbations

    items = []
    for ligne in _dernier_par_cle(_reg()).values():
        demande_id = ligne.get("demande_id")
        if ligne["statut"] != STATUT_RETIRE or not isinstance(demande_id, str) or not ligne.get("neutralise"):
            continue
        demande = approbations.lire(cnx, demande_id)
        if demande is None or demande["statut"] != "en_attente":
            continue
        items.append(
            {
                "type": TYPE_ATTENTE,
                "id": demande_id,
                "resume": (
                    "Le client a retiré son consentement au suivi de la fenêtre d'arrivée : cette demande d'envoi ne "
                    "doit PAS être approuvée (elle ne peut plus s'exécuter). Rien n'a été envoyé."
                ),
                "niveau": "N3",
                "depuis": ligne["retire_le"],
                "action_proposee": "refuser la demande",
            }
        )
    return items
