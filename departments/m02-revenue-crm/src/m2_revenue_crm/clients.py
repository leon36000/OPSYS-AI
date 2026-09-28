"""Client 360 (PLAN T2.2 ; DEFINITION-PRODUIT §7 M2, M2.2) : une entité CLIENT distincte du lead.

Un client peut porter PLUSIEURS leads/opportunités dans le temps (affaire répétée, M2.14) — le
lead reste l'unité de la machine à états commerciale (statuts.py, inchangée), le CLIENT est une
identité stable qui les regroupe. Module PUR (ni ``opsys`` ni SQLAlchemy, comme le reste du
paquet hors ``outils.py``) : le lien lead->client n'est qu'un NOUVEAU TYPE D'ENTRÉE
(``client_associe``) dans le MÊME registre append-only que tout le reste — donc durable par
``opsys.stockage.maillons`` sans aucun stockage séparé à opérer.

Identité du client — ``identifiant_client`` : fonction PURE du seul ``contact`` du lead, selon le
critère ``contact_identique`` de ``doublons.py`` (réutilisé tel quel, jamais réécrit ici) —
JAMAIS ``ville_et_travaux`` seul : deux clients distincts de la même ville qui demandent le même
type de travaux ne sont pas le même client, ce serait fusionner deux personnes sur un critère
trop faible pour de l'identité. Aucun compteur, aucun tirage, aucune consultation du registre
n'est nécessaire pour CALCULER l'identifiant : deux ingestions du même contact (au sens strict de
``contact_identique``, égalité exacte du dict) produisent le même ``client_id`` sans avoir besoin
de se souvenir de quoi que ce soit — la seule chose que le registre sert à répondre, c'est « quelles
opportunités porte ce client ».

Loi 25 — minimisation : ce module ne COPIE ni n'INVENTE aucun renseignement personnel. La vue 360
(``vue_360``) est une PROJECTION en lecture du contrat déjà ingéré (contact, ville) : rien de plus
n'est stocké pour la construire, et l'identifiant client lui-même n'est qu'une empreinte SHA256 du
contact (irréversible), jamais le contact en clair.
"""

from __future__ import annotations

from datetime import UTC, datetime

from . import encodage, verdicts
from . import horodatage as _horodatage
from .doublons import contact_identique
from .statuts import statut_courant

__all__ = [
    "TYPE_ENTREE",
    "client_de_lead",
    "identifiant_client",
    "lier_lead",
    "obtenir_vue_360",
    "opportunites_du_client",
    "vue_360",
]

TYPE_ENTREE = "client_associe"

# Préfixe versionné de l'empreinte (comme les autres identifiants dérivés du paquet) : un
# changement futur de convention se ferait sous un nouveau préfixe, jamais en place, pour ne
# jamais faire correspondre silencieusement un même contact à deux client_id incompatibles.
_PREFIXE_IDENTIFIANT = "m2-client-v1"


def identifiant_client(contrat: dict) -> str:
    """``client_id`` : empreinte canonique du seul ``contact`` (PLAN T2.2).

    Lève ``ValueError`` si ``contrat`` n'a pas de contact exploitable — ne devrait jamais arriver
    pour un contrat déjà accepté par ``contrats.valider_structure`` (qui exige un contact non
    vide), mais cette fonction reste appelable isolément (fail-closed, pas de suppose-vide).
    """
    contact = contrat.get("contact")
    if not isinstance(contact, dict) or not contact:
        raise ValueError("identifiant_client : contrat sans contact exploitable")
    return encodage.encoder_canonique(_PREFIXE_IDENTIFIANT, contact)


def _maillons_client_associe(registre_cible) -> list:
    return [m for m in registre_cible.lire() if m.get("type_entree") == TYPE_ENTREE]


def client_de_lead(registre_cible, lead_id: str) -> str | None:
    """``client_id`` déjà associé à ce ``lead_id`` (None si jamais lié)."""
    trouve = None
    for m in _maillons_client_associe(registre_cible):
        if m.get("lead_id") == lead_id:
            trouve = m.get("client_id")
    return trouve


def opportunites_du_client(registre_cible, client_id: str) -> list[str]:
    """Tous les ``lead_id`` (opportunités, au sens FSM de statuts.py) liés à ce client, dans
    l'ordre du registre, sans répétition."""
    vus: list[str] = []
    for m in _maillons_client_associe(registre_cible):
        if m.get("client_id") == client_id and m.get("lead_id") not in vus:
            vus.append(m.get("lead_id"))
    return vus


def _dernier_contrat(registre_cible, lead_id: str) -> dict | None:
    """Contrat gelé du lead (copié tel quel dans son maillon ``lead_ingere``), ou None."""
    trouve = None
    for m in registre_cible.lire():
        if m.get("type_entree") == "lead_ingere" and m.get("lead_id") == lead_id:
            trouve = m.get("contrat")
    return trouve


def _client_id_pour_contact_existant(registre_cible, contrat: dict) -> str | None:
    """Balaie les leads déjà liés à un client et retourne le ``client_id`` du premier dont le
    contrat est ``contact_identique`` (``doublons.py``, réutilisé tel quel) à celui-ci — None si
    aucun. Défense en profondeur pour ``lier_lead`` : ``identifiant_client`` est déjà une fonction
    PURE du contact (deux contacts identiques produisent nécessairement le même identifiant), donc
    ce balayage ne DEVRAIT jamais découvrir un désaccord ; il le détecterait s'il survenait un jour
    (ex. régression de ``encodage.encoder_canonique``) plutôt que de fragmenter silencieusement un
    même client en deux identifiants distincts.
    """
    for maillon in _maillons_client_associe(registre_cible):
        contrat_existant = _dernier_contrat(registre_cible, maillon.get("lead_id"))
        if contrat_existant is not None and contact_identique(contrat, contrat_existant):
            return maillon.get("client_id")
    return None


def lier_lead(registre_cible, lead_id: str, contrat: dict, horodatage: str) -> tuple[dict | None, dict | None]:
    """Calcule le ``client_id`` de ce contact et écrit le lien ``lead_id -> client_id``.

    Idempotent : si CE ``lead_id`` porte déjà un lien (ne devrait jamais arriver — le contact d'un
    lead ne change jamais après ingestion, et ``outils.ingerer_lead`` n'appelle cette fonction
    qu'une fois par lead — mais un module pur reste défensif), aucun second maillon n'est écrit ;
    le lien existant est retourné tel quel, jamais recalculé silencieusement sur un contact qui
    aurait divergé.
    """
    try:
        horodatage_valide = _horodatage.valider_horodatage(horodatage)
    except ValueError as exc:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE", detail=str(exc))

    existant = client_de_lead(registre_cible, lead_id)
    if existant is not None:
        return {"lead_id": lead_id, "client_id": existant, "deja_associe": True}, None

    client_id = identifiant_client(contrat)
    client_id_par_contact = _client_id_pour_contact_existant(registre_cible, contrat)
    if client_id_par_contact is not None and client_id_par_contact != client_id:
        raise RuntimeError(
            "clients.lier_lead : incohérence interne — un contact identique (doublons."
            f"contact_identique) pointe déjà vers le client {client_id_par_contact!r}, mais "
            f"identifiant_client calcule {client_id!r} pour ce même contact. Ne devrait jamais "
            "arriver (identifiant_client est une fonction pure du contact) : signale une "
            "régression d'encodage, jamais une donnée normale."
        )

    entree = {
        "type_entree": TYPE_ENTREE,
        "horodatage": horodatage_valide,
        "lead_id": lead_id,
        "client_id": client_id,
    }
    ligne_id = registre_cible.ajouter(entree)
    return {
        "lead_id": lead_id,
        "client_id": client_id,
        "ligne_id": ligne_id,
        "deja_associe": False,
    }, None


def _derniere_prochaine_action(registre_cible, lead_id: str) -> dict | None:
    """Le dernier ``prochaine_action`` porté par une transition de CE lead (les deux seuls
    chemins qui en portent une : nouveau->qualifie et chantier->facture — statuts.py). None si
    aucune n'a encore été fournie par un humain : jamais inventée ici."""
    trouve = None
    for m in registre_cible.lire():
        if (
            m.get("type_entree") == "transition_statut"
            and m.get("lead_id") == lead_id
            and m.get("prochaine_action") is not None
        ):
            trouve = m.get("prochaine_action")
    return trouve


def _interactions_du_lead(registre_cible, lead_id: str) -> list[dict]:
    return [
        {"lead_id": lead_id, "auteur": m["auteur"], "resume": m["resume"], "horodatage": m["horodatage"]}
        for m in registre_cible.lire()
        if m.get("type_entree") == "interaction" and m.get("lead_id") == lead_id
    ]


def _instant_utc(horodatage_str: str) -> datetime:
    # Les horodatages du registre sont déjà validés (tz-aware) à l'écriture (horodatage.py) :
    # aucune donnée falsifiée hors API ne passe par ici en usage normal.
    return datetime.fromisoformat(horodatage_str).astimezone(UTC)


_MAX_INTERACTIONS_RECENTES = 10


def vue_360(registre_cible, client_id: str) -> dict | None:
    """Vue 360 compacte (§7 M2, M2.2) : leads/opportunités, statuts, prochaines actions connues,
    interactions récentes. PROJECTION pure du registre existant — aucune nouvelle donnée
    personnelle stockée (Loi 25, minimisation) : contact/ville proviennent du contrat déjà ingéré,
    jamais dupliqués ni enrichis ici. None si ``client_id`` ne correspond à aucun lead connu.
    """
    leads = opportunites_du_client(registre_cible, client_id)
    if not leads:
        return None

    contact = None
    opportunites = []
    interactions_toutes: list[dict] = []
    for lead_id in leads:
        contrat = _dernier_contrat(registre_cible, lead_id)
        if contrat is None:
            continue
        if contact is None:
            contact = contrat.get("contact")
        opportunites.append(
            {
                "lead_id": lead_id,
                "statut": statut_courant(registre_cible, lead_id),
                "ville": contrat.get("ville"),
                # Lead v1 : `type_travaux` ; lead v2 : `service` (PLAN T0.13). L'autre vaut None,
                # jamais une valeur devinée.
                "type_travaux": contrat.get("type_travaux"),
                "service": contrat.get("service"),
                "canal": contrat.get("canal"),
                # PLAN T2.2 — lead structuré : absents pour tout contrat qui ne les fournit pas
                # (le contrat gelé v1 du front office ne les porte pas encore) — jamais devinés.
                "source": contrat.get("source"),
                "campagne": contrat.get("campagne"),
                "utm": contrat.get("utm"),
                "prochaine_action": _derniere_prochaine_action(registre_cible, lead_id),
            }
        )
        interactions_toutes.extend(_interactions_du_lead(registre_cible, lead_id))

    interactions_toutes.sort(key=lambda item: _instant_utc(item["horodatage"]))

    return {
        "client_id": client_id,
        "contact": contact,
        "opportunites": opportunites,
        "interactions_recentes": interactions_toutes[-_MAX_INTERACTIONS_RECENTES:],
    }


def obtenir_vue_360(registre_cible, client_id: str) -> tuple[dict | None, dict | None]:
    """(resultat, verdict) — même patron que le reste du module : verdict NOMMÉ si ``client_id``
    est introuvable, jamais une vue vide rendue comme si elle était valide."""
    vue = vue_360(registre_cible, client_id)
    if vue is None:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE", detail=f"client_id introuvable : {client_id!r}"
        )
    return vue, None
