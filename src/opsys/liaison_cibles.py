"""Tickets privés qui lient une mutation à une affaire vérifiée.

Le ticket brut circule uniquement dans `_meta` entre OPSYS-CORE et le répartiteur Python.
Cette première interface est volontairement petite : les vérifications de portée et la
consommation transactionnelle appartiennent aux fonctions d'émission et d'exécution ci-dessous.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
import secrets
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, insert, select, update

from . import idempotence, stockage
from .stockage.schema import APPROBATIONS, EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, LIAISONS_TICKETS

TICKET_CIBLE_META = "opsys/cibleTicket"
OUTIL_LECTURE_SUCCES_M9 = "opsys_contexte_lire_succes_m9"
_LONGUEUR_MAX_TICKET = 4096
TTL_SECONDES = 120

_OUTILS_M2 = frozenset({
    "m2_transitionner_statut",
    "m2_reassigner_lead",
    "m2_enregistrer_interaction",
    "m2_preparer_relance",
    "m2_enregistrer_consentement_contact",
    "m2_marquer_chantier_termine",
})
_OUTILS_M3 = frozenset({"m3_marquer_devis_accepte", "m3_demander_envoi_devis"})
_OUTILS_M3_CREATION = frozenset({"m3_creer_devis"})
OUTILS_CIBLES = _OUTILS_M2 | _OUTILS_M3 | _OUTILS_M3_CREATION
_OUTILS_SUIVI_M9 = frozenset({"m9_ouvrir_suivi_decision"})
_OUTILS_CLOTURE_M9 = frozenset({"m9_clore_suivi_decision"})
# La proposition native M9 conserve son approbation dédiée sans ticket de transport.
# Tous ses appels MCP, même /mcp sans département, exigent en revanche une cible vérifiée.
# La clôture peut recevoir un ticket natif dédié. Sa configuration Core reste
# inconnue tant que son observation finale et sa réconciliation ne sont pas qualifiées.
OUTILS_CIBLES_CORE_TICKETS = OUTILS_CIBLES | _OUTILS_SUIVI_M9
OUTILS_CIBLES_CORE = OUTILS_CIBLES_CORE_TICKETS | _OUTILS_CLOTURE_M9
_CHAMPS_CIBLES = frozenset({
    "lead_id", "devis_id", "facture_id", "wct_id", "client_id", "chantier_id",
    "intervention_id", "po_id", "signal_id", "contenu_id", "avis_id", "creneau_id",
    "ligne_id", "plan_id", "session_id", "agent_id", "reference_devis_m3", "lead_ids",
    "lead_id_a", "lead_id_b", "devis_ids", "wct_ids", "chantier_ids", "facture_ids",
})


class CibleRefusee(ValueError):
    """L'outil et ses arguments ne désignent pas exactement une cible du périmètre approuvé."""


@dataclasses.dataclass(frozen=True)
class TicketValide:
    empreinte: str
    ligne: Mapping[str, Any]
    reponse_rejouee: dict[str, Any] | None = None


def cible_de_l_outil(nom_outil: str, arguments: Mapping[str, Any]) -> tuple[str, str, str]:
    """Projette une mutation autorisée sur son unique identifiant explicite.

    Cette vérification de forme ne prouve pas que l'objet existe ni qu'il est relié à l'affaire;
    ces contrôles sont faits à l'émission et à l'exécution depuis les registres canoniques.
    """
    if nom_outil in _OUTILS_CLOTURE_M9:
        suivi_id = arguments.get("suivi_id")
        if (
            set(arguments) != {"suivi_id", "empreinte_suivi", "evenement_id", "empreinte_preuve", "bilan"}
            or not isinstance(suivi_id, str) or not suivi_id.strip()
        ):
            raise CibleRefusee("la clôture exige son suivi unique et ses seuls arguments contractuels")
        return "m09-strategic-intelligence", suivi_id, "suivi_m9"
    if nom_outil in _OUTILS_SUIVI_M9:
        evenement_id = arguments.get("evenement_id")
        if (
            set(arguments) != {"evenement_id", "empreinte_source", "action", "responsable_id", "echeance"}
            or not isinstance(evenement_id, str) or not evenement_id.strip()
        ):
            raise CibleRefusee("le suivi exige sa preuve unique et ses seuls arguments contractuels")
        return "m09-strategic-intelligence", evenement_id, "alerte_m8"
    if nom_outil in _OUTILS_M2:
        departement, champ, genre = "m02-revenue-crm", "lead_id", "lead"
    elif nom_outil in _OUTILS_M3:
        departement, champ, genre = "m03-estimation", "devis_id", "devis"
    elif nom_outil in _OUTILS_M3_CREATION:
        departement, champ, genre = "m03-estimation", "lead_id", "lead"
        devis_id = arguments.get("devis_id")
        chantier_id = arguments.get("chantier_id")
        cibles_creation = {"devis_id", "lead_id", "chantier_id"}
        if (
            not isinstance(devis_id, str) or not devis_id.strip()
            or "chantier_id" not in arguments
            or (chantier_id is not None and chantier_id != arguments.get("lead_id"))
            or {cle for cle in arguments if cle in _CHAMPS_CIBLES} != cibles_creation
        ):
            raise CibleRefusee("la création exige un devis, un lead et un chantier nul ou égal au lead")
    else:
        raise CibleRefusee("outil hors du périmètre de liaison des cibles")
    identifiant = arguments.get(champ)
    cibles_fournies = {cle for cle in arguments if cle in _CHAMPS_CIBLES}
    if nom_outil in _OUTILS_M3_CREATION:
        if cibles_fournies != {"devis_id", "lead_id", "chantier_id"}:
            raise CibleRefusee("la création exige exactement devis_id, lead_id et chantier_id")
    elif cibles_fournies != {champ}:
        raise CibleRefusee("une cible unique et explicite est requise")
    if not isinstance(identifiant, str) or not identifiant.strip():
        raise CibleRefusee("une cible unique et explicite est requise")
    return departement, identifiant, genre


def empreinte_ticket(jeton: str) -> str:
    """Empreinte du secret; le jeton brut ne doit jamais être persisté ni journalisé."""
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


def _iso(instant: dt.datetime) -> str:
    if instant.tzinfo is None:
        raise ValueError("l'heure du ticket doit porter un fuseau")
    return instant.astimezone(dt.UTC).isoformat(timespec="seconds")


def _sqlite_uniquement(cnx: Connection) -> None:
    if cnx.dialect.name != "sqlite":
        raise CibleRefusee("liaison de cible temporairement désactivée hors de SQLite")


def _registre_m10():
    from m10_memoire import registre

    reg = registre.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
    try:
        valide, _ = reg.valider_chaine()
    except Exception:
        raise CibleRefusee("chaîne du registre canonique M10 invalide") from None
    if valide is not True:
        raise CibleRefusee("chaîne du registre canonique M10 invalide")
    return reg


def _exiger_chaine_m2_valide(registre_cible: Any) -> None:
    """Refuse une décision de cible fondée sur un registre M2 altéré ou mal formé."""
    try:
        valide = registre_cible.valider_chaine()
    except Exception:
        raise CibleRefusee("chaîne du registre canonique M2 invalide") from None
    if valide is not True:
        raise CibleRefusee("chaîne du registre canonique M2 invalide")


def _publication_traitee(
    cnx: Connection, evenement_id: str, type_evenement: str, producteur: str, consommateur: str,
) -> dict[str, Any]:
    """Lit une publication et son reçu par leurs clés, sans scanner une cohorte du bus."""
    from .stockage import codec

    ligne = cnx.execute(select(
        EVENEMENTS_SORTANTS.c.type_evenement, EVENEMENTS_SORTANTS.c.producteur,
        EVENEMENTS_SORTANTS.c.charge,
    ).where(EVENEMENTS_SORTANTS.c.evenement_id == evenement_id)).mappings().one_or_none()
    if ligne is None or (ligne["type_evenement"], ligne["producteur"]) != (type_evenement, producteur):
        raise CibleRefusee("publication canonique absente ou provenance discordante")
    statut = cnx.execute(select(EVENEMENTS_RECUS.c.statut).where(
        EVENEMENTS_RECUS.c.evenement_id == evenement_id,
        EVENEMENTS_RECUS.c.consommateur == consommateur,
    )).scalar_one_or_none()
    if statut != "traite":
        raise CibleRefusee("reçu canonique absent ou non traité")
    try:
        charge = codec.decoder(ligne["charge"])
    except (ValueError, TypeError):
        raise CibleRefusee("charge de publication canonique invalide") from None
    if type(charge) is not dict:
        raise CibleRefusee("charge de publication canonique invalide")
    return charge


def _revalider_suivi_m9(cnx: Connection, arguments: Mapping[str, Any], affaire_id: str) -> str:
    from m9_strategic_intelligence import suivi_decisions
    from m10_memoire import classification, contrats, encodage, registre, wct

    try:
        source = suivi_decisions.preparer_source(
            stockage.maillons("m09-strategic-intelligence", "alertes_m8"), arguments["evenement_id"],
        )
    except (ValueError, TypeError, KeyError):
        raise CibleRefusee("preuve M8 reçue absente ou invalide") from None
    if source["empreinte_source"] != arguments["empreinte_source"]:
        raise CibleRefusee("empreinte de la preuve M8 discordante")
    publication_m8 = _publication_traitee(
        cnx, source["evenement_id"], "m8.alerte_proposee", "m08-analytics", "m09-strategic-intelligence",
    )
    if encodage.empreinte(publication_m8) != encodage.empreinte(source["alerte"]):
        raise CibleRefusee("preuve reçue différente de la publication M8 canonique")
    wct_id = source["alerte"]["preuve"]["wct_id"]
    publication_m4 = _publication_traitee(
        cnx, wct_id, "m4.travaux_termines", "m04-field-ops", "m10-memoire",
    )
    if publication_m4.get("wct_id") != wct_id:
        raise CibleRefusee("WCT publié discordant")
    reg = registre.Registre(maillons=stockage.maillons("m10-memoire", "evenements"))
    try:
        valide, _ = reg.valider_chaine()
    except Exception:
        raise CibleRefusee("chaîne du registre canonique M10 événements invalide") from None
    if valide is not True:
        raise CibleRefusee("chaîne du registre canonique M10 événements invalide")
    candidats = [m for m in reg.lire() if classification.type_evenement(m) == classification.TYPE_WCT
                 and m.get("wct_id") == wct_id]
    if len(candidats) != 1 or not all(champ in candidats[0] for champ in contrats.CHAMPS_WCT):
        raise CibleRefusee("WCT canonique absent, incomplet ou ambigu")
    if not all(champ in publication_m4 for champ in contrats.CHAMPS_WCT):
        raise CibleRefusee("WCT publié incomplet")
    memorise = {champ: candidats[0][champ] for champ in contrats.CHAMPS_WCT}
    publie = {champ: publication_m4[champ] for champ in contrats.CHAMPS_WCT}
    if wct.valider_wct(publie)[0] is not True or encodage.empreinte(memorise) != encodage.empreinte(publie):
        raise CibleRefusee("WCT mémorisé différent de la publication M4 canonique")
    # Le lead_id est déjà la représentation canonique M4/M10, opportunité comprise.
    # Ne jamais fabriquer un identifiant d'affaire à partir de la seule forme du WCT.
    if memorise["lead_id"] != affaire_id:
        raise CibleRefusee("la preuve M8 appartient à une autre affaire")
    return source["evenement_id"]


def _revalider_cloture_m9(cnx: Connection, arguments: Mapping[str, Any], affaire_id: str) -> str:
    from m9_strategic_intelligence import suivi_decisions
    from m9_strategic_intelligence.encodage import empreinte

    try:
        plan = suivi_decisions.trouver_plan(
            stockage.maillons("m09-strategic-intelligence", "suivi_decisions"), arguments["suivi_id"],
        )
        cloture = suivi_decisions.trouver_cloture(
            stockage.maillons("m09-strategic-intelligence", "clotures_suivi_decisions"), arguments["suivi_id"],
        )
        alertes = list(stockage.maillons("m09-strategic-intelligence", "alertes_m8"))
        preparation = suivi_decisions.preparer_cloture(plan, cloture, alertes, arguments["evenement_id"])
        if (preparation["empreinte_suivi"], preparation["preuve"]["empreinte_source"]) != (
            arguments["empreinte_suivi"], arguments["empreinte_preuve"],
        ):
            raise ValueError("empreintes de clôture discordantes")
        suivi_decisions.texte(arguments["bilan"], "bilan", 2000)
        origine = suivi_decisions.preparer_source(alertes, plan["source"]["evenement_id"])
        if empreinte(plan["source"]) != empreinte(origine):
            raise ValueError("source d'origine du plan discordante")
    except (ValueError, TypeError, KeyError, RecursionError):
        raise CibleRefusee("plan ou preuves de clôture absents, altérés ou invalides") from None
    # Le hash du plan ne prouve pas sa provenance. Les deux sources doivent aussi
    # rejoindre la publication, son reçu traité et le WCT canonique de cette affaire.
    for source in (origine, preparation["preuve"]):
        _revalider_suivi_m9(cnx, {
            "evenement_id": source["evenement_id"], "empreinte_source": source["empreinte_source"],
        }, affaire_id)
    return arguments["suivi_id"]


def _revalider_cible(cnx: Connection, outil: str, arguments: Mapping[str, Any], affaire_id: str,
                     ligne_liaison_id: str) -> tuple[str, str]:
    """Résout M2/M3 ou la preuve M9 et exige sa concordance avec le lien M10 courant."""
    departement, cible, genre_cible = cible_de_l_outil(outil, arguments)
    from m10_memoire import affaire as affaire_m10

    if not affaire_m10.valide(affaire_id) or affaire_m10.genre(affaire_id) is None:
        raise CibleRefusee("affaire invalide")
    if outil in _OUTILS_CLOTURE_M9:
        return _revalider_cloture_m9(cnx, arguments, affaire_id), genre_cible
    if outil in _OUTILS_SUIVI_M9:
        return _revalider_suivi_m9(cnx, arguments, affaire_id), genre_cible
    # La clé de session est validée et comparée dans les fonctions d'émission/exécution.
    # Ici, le demandeur transmet la ligne attendue, jamais une autorité alternative.
    if genre_cible == "lead":
        if affaire_m10.genre(affaire_id) != affaire_m10.GENRE_LEAD or cible != affaire_id:
            raise CibleRefusee("le lead cible ne correspond pas à l'affaire")
        from m2_revenue_crm import registre as registre_m2
        from m2_revenue_crm import statuts

        departement_m2 = "m02-revenue-crm" if outil in _OUTILS_M3_CREATION else departement
        reg = registre_m2.Registre(maillons=stockage.maillons(departement_m2, "principal"))
        _exiger_chaine_m2_valide(reg)
        if statuts.statut_courant(reg, cible) is None:
            raise CibleRefusee("lead absent du registre canonique M2")
        if outil in _OUTILS_M3_CREATION:
            from m3_estimation import devis_durable

            devis_id = arguments["devis_id"]
            etat_devis, verdict = devis_durable.lire_devis(
                stockage.maillons("m03-estimation", "devis"), devis_id
            )
            if verdict is not None:
                if etat_devis is not None or verdict.get("code") != "REJ-DEVIS-INTROUVABLE":
                    raise CibleRefusee("impossible de vérifier l'identifiant du devis dans M3")
            elif etat_devis is not None:
                if etat_devis.get("lead_id") != cible:
                    raise CibleRefusee("le devis existant appartient à un autre lead")
                chantier_existant = etat_devis.get("chantier_id")
                if chantier_existant is not None and chantier_existant != cible:
                    raise CibleRefusee("le chantier du devis existant ne concorde pas avec le lead")
            else:
                raise CibleRefusee("impossible de vérifier l'identifiant du devis dans M3")
            return cible, genre_cible
        return cible, genre_cible

    from m3_estimation import devis_durable

    etat_devis, verdict = devis_durable.lire_devis(stockage.maillons(departement, "devis"), cible)
    if verdict is not None or etat_devis is None:
        raise CibleRefusee("devis absent du registre canonique M3")
    lead_id = etat_devis.get("lead_id")
    if not isinstance(lead_id, str) or not lead_id:
        raise CibleRefusee("le devis ne porte pas de lead canonique")
    chantier_id = etat_devis.get("chantier_id")
    if chantier_id is not None and chantier_id != lead_id:
        # M4 porte encore le chantier sous l'identifiant du lead en v1. Aucun résolveur WCT
        # canonique ne permet de prouver une autre valeur : garder cette référence inconnue bloquée.
        raise CibleRefusee("le chantier du devis ne concorde pas avec le lead canonique")
    from m2_revenue_crm import registre as registre_m2
    from m2_revenue_crm import statuts

    reg = registre_m2.Registre(maillons=stockage.maillons("m02-revenue-crm", "principal"))
    _exiger_chaine_m2_valide(reg)
    if statuts.statut_courant(reg, lead_id) is None:
        raise CibleRefusee("lead du devis absent du registre canonique M2")
    genre_affaire = affaire_m10.genre(affaire_id)
    if genre_affaire == affaire_m10.GENRE_LEAD:
        if lead_id != affaire_id:
            raise CibleRefusee("le devis appartient à un autre lead")
        if outil == "m3_marquer_devis_accepte":
            statut = statuts.statut_courant(reg, lead_id)
            if statut != "qualifie" and statuts.reference_devis(reg, lead_id) != cible:
                raise CibleRefusee("le lead n'est pas qualifié pour ce devis ou est converti par un autre devis")
        return lead_id, genre_cible
    raise CibleRefusee("une opportunité M10 exige encore une preuve WCT canonique non disponible")


def _ligne_liaison_active(cle_session: str, ligne_attendue: str) -> str | None:
    from m10_memoire import liaison as liaison_m10

    active = liaison_m10.liaison_courante(cle_session, _registre_m10())
    return active.get("ligne_id") if active is not None and active.get("ligne_id") == ligne_attendue else None


def emettre_ticket(
    cnx: Connection,
    *,
    departement: str,
    agent_id: str,
    cle_session: str,
    affaire_id: str,
    origine_affaire: str,
    outil: str,
    arguments: Mapping[str, Any],
    maintenant: dt.datetime | None = None,
) -> dict[str, str]:
    """Émet un ticket opaque lié à l'agent/session, l'affaire, l'outil et ses arguments finaux."""
    _sqlite_uniquement(cnx)
    if origine_affaire not in {"demande", "session"}:
        raise CibleRefusee("origine d'affaire invalide")
    if not isinstance(agent_id, str) or not agent_id or not isinstance(cle_session, str):
        raise CibleRefusee("agent ou session invalide")
    if not cle_session.startswith(f"agent:{agent_id}:"):
        raise CibleRefusee("la session ne correspond pas à l'agent")
    from m10_memoire import liaison as liaison_m10

    active = liaison_m10.liaison_courante(cle_session, _registre_m10())
    if active is None or active.get("affaire_id") != affaire_id:
        raise CibleRefusee("aucune liaison M10 active vers cette affaire")
    attendu, _, _ = cible_de_l_outil(outil, arguments)
    if attendu != departement:
        raise CibleRefusee("l'outil n'appartient pas au département d'origine")
    from m10_memoire import affaire as affaire_m10

    genre_affaire = affaire_m10.genre(affaire_id)
    if genre_affaire is None:
        raise CibleRefusee("affaire invalide")
    _revalider_cible(cnx, outil, arguments, affaire_id, active["ligne_id"])
    maintenant = maintenant or dt.datetime.now(dt.UTC)
    cree_le = _iso(maintenant)
    expire_le = _iso(maintenant + dt.timedelta(seconds=TTL_SECONDES))
    jeton = secrets.token_urlsafe(32)
    cnx.execute(insert(LIAISONS_TICKETS).values(
        ticket_hash=empreinte_ticket(jeton), cree_le=cree_le, expire_le=expire_le,
        departement=departement, agent_id=agent_id, cle_session=cle_session,
        affaire_id=affaire_id, genre_affaire=genre_affaire, ligne_liaison_id=active["ligne_id"],
        outil=outil, empreinte_arguments=idempotence.empreinte_arguments(arguments),
        statut="disponible",
    ))
    resultat = {"ticket": jeton, "expire_le": expire_le}
    if outil in _OUTILS_SUIVI_M9:
        resultat["instance_id"] = _instance_native(cnx)
    return resultat


def verifier_ticket(
    cnx: Connection,
    meta: TicketMeta,
    *,
    departement: str,
    outil: str,
    arguments: Mapping[str, Any],
    agent_id: str | None = None,
    cle_session: str | None = None,
    demande_id: str | None = None,
    maintenant: dt.datetime | None = None,
) -> TicketValide:
    """Vérifie le binding, l'expiration et les liens vivants dans la transaction d'exécution."""
    _sqlite_uniquement(cnx)
    empreinte = empreinte_ticket(meta.jeton)
    ligne = cnx.execute(select(LIAISONS_TICKETS).where(
        LIAISONS_TICKETS.c.ticket_hash == empreinte
    )).mappings().one_or_none()
    if ligne is None:
        raise CibleRefusee("ticket inconnu ou inutilisable")
    departement_cible, _, _ = cible_de_l_outil(outil, arguments)
    empreinte_args = idempotence.empreinte_arguments(arguments)
    if (ligne["departement"], ligne["outil"], ligne["empreinte_arguments"]) != (
        departement, outil, empreinte_args
    ) or departement_cible != departement:
        raise CibleRefusee("ticket lié à une autre route, un autre outil ou d'autres arguments")
    if agent_id is not None and ligne["agent_id"] != agent_id:
        raise CibleRefusee("ticket lié à un autre agent")
    if cle_session is not None and ligne["cle_session"] != cle_session:
        raise CibleRefusee("ticket lié à une autre session")
    if demande_id is not None:
        if ligne["statut"] != "scelle" or ligne["demande_id"] != demande_id:
            raise CibleRefusee("ticket non scellé à cette demande d'approbation")
    elif ligne["statut"] in {"scelle", "consomme"}:
        reponse = json.loads(ligne["reponse"]) if ligne["reponse"] else None
        return TicketValide(empreinte, ligne, reponse)
    instant = maintenant or dt.datetime.now(dt.UTC)
    if demande_id is None and instant >= dt.datetime.fromisoformat(ligne["expire_le"]):
        raise CibleRefusee("ticket expiré")
    from m10_memoire import liaison as liaison_m10

    active = liaison_m10.liaison_courante(ligne["cle_session"], _registre_m10())
    if active is None or (active.get("affaire_id"), active.get("ligne_id")) != (
        ligne["affaire_id"], ligne["ligne_liaison_id"]
    ):
        raise CibleRefusee("liaison de session révoquée ou remplacée")
    _revalider_cible(cnx, outil, arguments, ligne["affaire_id"], ligne["ligne_liaison_id"])
    return TicketValide(empreinte, ligne)


def verifier_ticket_scelle(
    cnx: Connection,
    empreinte: str,
    demande_id: str,
    *,
    departement: str,
    outil: str,
    arguments: Mapping[str, Any],
) -> TicketValide:
    """Revalide un ticket lié à l'approbation, sans exiger le secret brut une seconde fois."""
    _sqlite_uniquement(cnx)
    ligne = cnx.execute(select(LIAISONS_TICKETS).where(
        LIAISONS_TICKETS.c.ticket_hash == empreinte,
        LIAISONS_TICKETS.c.demande_id == demande_id,
        LIAISONS_TICKETS.c.statut == "scelle",
    )).mappings().one_or_none()
    if ligne is None or (ligne["departement"], ligne["outil"], ligne["empreinte_arguments"]) != (
        departement, outil, idempotence.empreinte_arguments(arguments)
    ):
        raise CibleRefusee("ticket absent ou non scellé à cette demande")
    from m10_memoire import liaison as liaison_m10

    active = liaison_m10.liaison_courante(ligne["cle_session"], _registre_m10())
    if active is None or (active.get("affaire_id"), active.get("ligne_id")) != (
        ligne["affaire_id"], ligne["ligne_liaison_id"]
    ):
        raise CibleRefusee("liaison M10 révoquée ou remplacée depuis la demande")
    _revalider_cible(cnx, outil, arguments, ligne["affaire_id"], ligne["ligne_liaison_id"])
    return TicketValide(empreinte, ligne)


def sceller_ticket(cnx: Connection, ticket: TicketValide, demande_id: str,
                   reponse: Mapping[str, Any]) -> None:
    """Scelle le ticket à la demande créée par ce call, dans la même transaction."""
    resultat = cnx.execute(update(LIAISONS_TICKETS).where(
        LIAISONS_TICKETS.c.ticket_hash == ticket.empreinte,
        LIAISONS_TICKETS.c.statut == "disponible",
    ).values(statut="scelle", demande_id=demande_id,
             reponse=json.dumps(dict(reponse), ensure_ascii=False)))
    if resultat.rowcount != 1:
        raise CibleRefusee("ticket déjà utilisé")


def consommer_ticket(cnx: Connection, ticket: TicketValide, reponse: Mapping[str, Any]) -> None:
    """Consomme le ticket et cache la réponse finale pour les renvois après perte de transport."""
    resultat = cnx.execute(update(LIAISONS_TICKETS).where(
        LIAISONS_TICKETS.c.ticket_hash == ticket.empreinte,
        LIAISONS_TICKETS.c.statut == "disponible",
    ).values(statut="consomme", reponse=json.dumps(dict(reponse), ensure_ascii=False),
             consomme_le=_iso(dt.datetime.now(dt.UTC))))
    if resultat.rowcount != 1:
        raise CibleRefusee("ticket déjà utilisé")


def terminer_ticket_scelle(cnx: Connection, ticket_hash: str, demande_id: str,
                           reponse: Mapping[str, Any]) -> None:
    """Finalise un ticket scellé par l'approbation exacte; seul le dispatcher l'appelle."""
    resultat = cnx.execute(update(LIAISONS_TICKETS).where(
        LIAISONS_TICKETS.c.ticket_hash == ticket_hash,
        LIAISONS_TICKETS.c.demande_id == demande_id,
        LIAISONS_TICKETS.c.statut == "scelle",
    ).values(statut="consomme", reponse=json.dumps(dict(reponse), ensure_ascii=False),
             consomme_le=_iso(dt.datetime.now(dt.UTC))))
    if resultat.rowcount != 1:
        raise CibleRefusee("ticket scellé invalide ou déjà utilisé")


def _instance_native(cnx: Connection) -> str:
    # Reuse the existing logical Native identity; a copied database keeps this UUID.
    # It is neither physical endpoint attestation nor permission to merge forked histories.
    from .agent_cfo_grants import instance_id

    try:
        valeur = instance_id(cnx)
        if str(uuid.UUID(valeur)) != valeur:
            raise ValueError("non canonical UUID")
        return valeur
    except (PermissionError, TypeError, ValueError, AttributeError):
        raise CibleRefusee("identité logique Native indisponible") from None


def _objet_journal(valeur: Any) -> dict[str, Any]:
    # Bound parsing, not every allocation made by the database driver.
    if not isinstance(valeur, str) or len(valeur) > 65_536:
        raise CibleRefusee("journal de résultat invalide")
    try:
        resultat = json.loads(valeur)
    except (ValueError, RecursionError):
        raise CibleRefusee("journal de résultat invalide") from None
    if type(resultat) is not dict:
        raise CibleRefusee("journal de résultat invalide")
    return resultat


def lire_succes_m9(
    cnx: Connection, *, departement: str, agent_id: str, cle_session: str,
    affaire_id: str, empreinte_ticket: str, demande_id: str,
) -> dict[str, Any]:
    """Read one exact historical success under its still-current private M10 liaison.

    No dispatcher, approval, ticket replay or business function is called. A false confirmation
    is not a final refusal of the original operation. The caller must establish which Native
    history its authenticated route is authorized to consult before completing any Core intent.
    """
    _sqlite_uniquement(cnx)
    if (
        departement != "m09-strategic-intelligence"
        or not isinstance(agent_id, str) or not 1 <= len(agent_id) <= 64
        or not isinstance(cle_session, str) or not 1 <= len(cle_session) <= 256
        or not cle_session.startswith(f"agent:{agent_id}:")
        or not isinstance(affaire_id, str) or not 1 <= len(affaire_id) <= 197
        or not isinstance(empreinte_ticket, str) or re.fullmatch(r"[0-9a-f]{64}", empreinte_ticket) is None
        or not isinstance(demande_id, str) or re.fullmatch(r"[0-9a-f]{12}", demande_id) is None
    ):
        raise CibleRefusee("référence privée de succès invalide")
    ticket = cnx.execute(select(LIAISONS_TICKETS).where(
        LIAISONS_TICKETS.c.ticket_hash == empreinte_ticket,
        LIAISONS_TICKETS.c.demande_id == demande_id,
    )).mappings().one_or_none()
    if ticket is None or (
        ticket["departement"], ticket["agent_id"], ticket["cle_session"], ticket["affaire_id"], ticket["outil"]
    ) != (departement, agent_id, cle_session, affaire_id, "m9_ouvrir_suivi_decision"):
        raise CibleRefusee("référence privée de succès non concordante")
    from m10_memoire import liaison as liaison_m10

    active = liaison_m10.liaison_courante(cle_session, _registre_m10())
    if active is None or (active.get("affaire_id"), active.get("ligne_id")) != (
        affaire_id, ticket["ligne_liaison_id"]
    ):
        raise CibleRefusee("liaison M10 révoquée ou remplacée")
    demande = cnx.execute(select(APPROBATIONS).where(
        APPROBATIONS.c.id == demande_id,
        APPROBATIONS.c.ticket_cible_hash == empreinte_ticket,
        APPROBATIONS.c.departement == departement,
        APPROBATIONS.c.outil == ticket["outil"],
    )).mappings().one_or_none()
    if demande is None:
        raise CibleRefusee("demande privée non concordante")
    arguments = _objet_journal(demande["arguments"])
    if idempotence.empreinte_arguments(arguments) != ticket["empreinte_arguments"]:
        raise CibleRefusee("arguments privés non concordants")
    recu = {"schema": 1, "confirme": False, "instance_id": _instance_native(cnx),
            "demande_id": demande_id, "outil": ticket["outil"]}
    if (demande["statut"], ticket["statut"]) in {
        ("en_attente", "scelle"), ("en_cours", "scelle"),
        ("refusee", "consomme"), ("echec", "consomme"),
    }:
        return recu
    if (demande["statut"], ticket["statut"]) != ("executee", "consomme"):
        raise CibleRefusee("journaux privés de succès discordants")
    resultat = _objet_journal(demande["resultat"])
    # Python equality conflates JSON booleans and numbers, including inside nested caches.
    try:
        concordants = json.dumps(resultat, sort_keys=True, allow_nan=False) == json.dumps(
            _objet_journal(ticket["reponse"]), sort_keys=True, allow_nan=False,
        )
    except (ValueError, RecursionError):
        raise CibleRefusee("journal de résultat invalide") from None
    if not concordants:
        raise CibleRefusee("journaux privés de succès discordants")
    contenu = resultat.get("resultat")
    suivi = contenu.get("suivi") if type(contenu) is dict else None
    decision = suivi.get("decision") if type(suivi) is dict else None
    source = suivi.get("source") if type(suivi) is dict else None
    if (
        resultat.get("ok") is not True or type(contenu) is not dict or contenu.get("accepte") is not True
        or type(suivi) is not dict or type(suivi.get("schema")) is not int
        or suivi.get("schema") != 1 or suivi.get("suivi_id") != demande_id
        or suivi.get("statut") != "planifiee"
        or any(suivi.get(champ) != arguments.get(champ) for champ in ("action", "responsable_id", "echeance"))
        or type(source) is not dict
        or any(source.get(champ) != arguments.get(champ) for champ in ("evenement_id", "empreinte_source"))
        or type(decision) is not dict or decision.get("demande_id") != demande_id
        or demande["decide_role"] != "nathan_owner" or not demande["decide_par"] or not demande["decide_le"]
        or any(decision.get(champ) != demande[champ] for champ in ("decide_par", "decide_role", "decide_le"))
    ):
        raise CibleRefusee("succès métier M9 non confirmé")
    # Never revalidate the old owner's present role: this is a committed historical effect.
    return {**recu, "confirme": True}


def outil_lecture_succes_m9(cnx_factory, departement: str):
    """Private T0 reader; only the M9 context route registers this capability."""
    from .outils import Autonomie, Outil

    def lire(agent_id: str, cle_session: str, affaire_id: str,
             empreinte_ticket: str, demande_id: str) -> dict[str, Any]:
        try:
            with cnx_factory() as cnx:
                return lire_succes_m9(
                    cnx, departement=departement, agent_id=agent_id, cle_session=cle_session,
                    affaire_id=affaire_id, empreinte_ticket=empreinte_ticket, demande_id=demande_id,
                )
        except CibleRefusee as exc:
            raise ValueError(f"REJ-LIAISON-SUCCES-M9: {exc}") from None

    proprietes = {nom: {"type": "string", "minLength": 1, "maxLength": maximum}
                  for nom, maximum in (("agent_id", 64), ("cle_session", 256), ("affaire_id", 197),
                                       ("empreinte_ticket", 64), ("demande_id", 12))}
    return Outil(
        nom=OUTIL_LECTURE_SUCCES_M9,
        description="Lecture privée du succès exact d'une demande M9, sans rejouer son effet.",
        parametres={"type": "object", "properties": proprietes,
                    "required": list(proprietes), "additionalProperties": False},
        fonction=lire, autonomie=Autonomie.T0,
    )


def outil_emission(cnx_factory, departement: str):
    """Construit l'outil T0 privé à une route de contexte, absent des manifestes publics."""
    from .outils import Autonomie, Outil

    schema = {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "cle_session": {"type": "string", "minLength": 1, "maxLength": 256},
            "affaire_id": {"type": "string", "minLength": 1, "maxLength": 197},
            "origine_affaire": {"type": "string", "enum": ["demande", "session"]},
            "outil": {"type": "string", "minLength": 1, "maxLength": 128},
            "arguments": {"type": "object"},
        },
        "required": ["agent_id", "cle_session", "affaire_id", "origine_affaire", "outil", "arguments"],
        "additionalProperties": False,
    }

    def creer(agent_id: str, cle_session: str, affaire_id: str, origine_affaire: str,
              outil: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        try:
            with cnx_factory() as cnx:
                resultat = emettre_ticket(
                    cnx, departement=departement, agent_id=agent_id, cle_session=cle_session,
                    affaire_id=affaire_id, origine_affaire=origine_affaire, outil=outil,
                    arguments=arguments,
                )
            return resultat
        except CibleRefusee as exc:
            raise ValueError(f"REJ-LIAISON-CIBLE: {exc}") from None

    return Outil(
        nom="opsys_contexte_creer_ticket_cible",
        description="Autorisation privée et temporaire d'une mutation liée à une affaire vérifiée.",
        parametres=schema,
        fonction=creer,
        autonomie=Autonomie.T0,
    )


@dataclasses.dataclass(frozen=True)
class TicketMeta:
    """Valeur opaque du ticket transmis dans les métadonnées MCP de `tools/call`."""

    jeton: str


def depuis_meta_mcp(meta: Mapping[str, Any] | None) -> TicketMeta | None:
    """Lit le ticket de cible privé de `_meta`, ou `None` lorsqu'il n'est pas présent.

    Une clé présente mais invalide est une erreur : le répartiteur ne doit jamais exécuter un
    outil cible en ignorant silencieusement un ticket tronqué ou mal formé. Le message ne reprend
    aucune partie de la valeur, qui est un secret porteur d'autorité.
    """
    if not meta or TICKET_CIBLE_META not in meta:
        return None
    jeton = meta[TICKET_CIBLE_META]
    if not isinstance(jeton, str) or not jeton.strip() or len(jeton) > _LONGUEUR_MAX_TICKET:
        raise ValueError(f"`{TICKET_CIBLE_META}` doit être une chaîne opaque valide")
    return TicketMeta(jeton)
