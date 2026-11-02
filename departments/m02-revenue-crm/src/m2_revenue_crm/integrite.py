"""Audit d'intégrité des données du CRM (M2-C1 ; DEFINITION-PRODUIT §7 M2.1 « Intégrité et audit du CRM »).

Module PUR : aucune entrée-sortie, aucune horloge, aucun aléa. Il LIT les registres de M2 déjà lus par l'appelant et ne
corrige RIEN : aucune réparation, aucune fusion, aucune suppression. Il dit ce qui cloche, où, et pourquoi ; le plan de
réparation (`reparation.py`) propose, une personne décide.

HUIT CONTRÔLES, dans cet ordre :
  1. `lead_sans_statut` : un lead ingéré dont le statut courant manque ou n'est pas dans la machine à états ;
  2. `client_sans_contact` : un client sans téléphone ni courriel utilisable (nom seul : le client est injoignable) ;
  3. `tache_sans_proprietaire` : un lead ouvert, au-delà de `nouveau`, dont la prochaine action n'a aucun propriétaire ;
  4. `soumission_orpheline` : un devis (M3) dont le lead n'est connu d'aucun registre de M2 ;
  5. `activite_sans_lead` : une activité (transition, note, réassignation, lien client, signalement de doublon) dont le
     lead n'a jamais été ingéré ;
  6. `lead_sans_client` : un lead ingéré qui n'est lié à aucun client (Client 360) ;
  7. `pipeline_incoherent` : un lead dont l'historique viole la machine à états (chaîne rompue, transition illégale,
     converti sans devis, perdu sans motif, qualifié sans propriétaire ni prochaine action, facturé sans action) ;
  8. `doublon_probable` : deux leads que la détection de l'ingestion rapproche (MÊME critère, MÊME fenêtre de 7 jours)
  et
     qu'aucun signalement ne couvre. Les doublons déjà signalés et encore en attente d'arbitrage sont LISTÉS (jamais
     comptés comme anomalie) ; ceux qu'un humain a arbitrés « distincts » sont écartés. Aucune fusion, jamais.

Un contrôle dont la source est illisible (`soumission_orpheline` sans les registres de devis) est « non évalué » :
jamais un
zéro. Le contrôle des doublons est « partiel » quand son borne de travail est atteinte (dit).

Rien de personnel ne sort : des identifiants de lead et de client, des natures d'anomalie et des compteurs. Ni nom, ni
courriel, ni téléphone, ni texte d'une note.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from . import clients, doublons, encodage, segments, statuts

__all__ = [
    "CONTROLES",
    "ETAT_EVALUE",
    "ETAT_NON_EVALUE",
    "ETAT_PARTIEL",
    "MAX_PAIRES_EXAMINEES",
    "auditer",
]

ETAT_EVALUE = "evalue"
ETAT_PARTIEL = "partiel"
ETAT_NON_EVALUE = "non_evalue"

C_STATUT = "lead_sans_statut"
C_CONTACT = "client_sans_contact"
C_PROPRIETAIRE = "tache_sans_proprietaire"
C_SOUMISSION = "soumission_orpheline"
C_ACTIVITE = "activite_sans_lead"
C_CLIENT = "lead_sans_client"
C_PIPELINE = "pipeline_incoherent"
C_DOUBLON = "doublon_probable"
CONTROLES = (C_STATUT, C_CONTACT, C_PROPRIETAIRE, C_SOUMISSION, C_ACTIVITE, C_CLIENT, C_PIPELINE, C_DOUBLON)

ENONCES = {
    C_STATUT: "Un lead ingéré a un statut courant connu de la machine à états.",
    C_CONTACT: "Un client a au moins un téléphone ou un courriel (sinon il est injoignable).",
    C_PROPRIETAIRE: "La prochaine action d'un lead ouvert au-delà de nouveau a un propriétaire.",
    C_SOUMISSION: "Chaque devis reçu de M3 se rattache à un lead ingéré.",
    C_ACTIVITE: "Chaque activité se rattache à un lead ingéré.",
    C_CLIENT: "Chaque lead ingéré est lié à un client (Client 360).",
    C_PIPELINE: "L'historique d'un lead respecte la machine à états et ses conditions.",
    C_DOUBLON: "Deux leads rapprochés par la détection de l'ingestion sont couverts par un signalement.",
}

# Le travail de rapprochement des doublons est borné : au-delà, le contrôle est « partiel » et le dit.
MAX_PAIRES_EXAMINEES = 200_000
MAX_DOUBLONS_LISTES = 100

_T_INGESTION = "lead_ingere"
_T_TRANSITION = statuts.TYPE_ENTREE
_T_INTERACTION = "interaction"
_T_REASSIGNATION = "reassignation"
_T_CLIENT = clients.TYPE_ENTREE
_T_DOUBLON = doublons.TYPE_ENTREE
_TYPES_PAR_LEAD = (_T_TRANSITION, _T_INTERACTION, _T_REASSIGNATION, _T_CLIENT)
_STATUTS_OUVERTS = tuple(s for s in statuts.STATUTS if s not in statuts.STATUTS_TERMINAUX)


def _anomalie(
    controle: str, nature: str, *, lead_id: str | None = None, client_id: str | None = None, **donnee: Any
) -> dict[str, Any]:
    return {"controle": controle, "nature": nature, "lead_id": lead_id, "client_id": client_id, "donnee": donnee}


def _action_valide(action: Any) -> bool:
    """Une prochaine action utilisable : une description non vide et une échéance lisible avec fuseau."""
    if not isinstance(action, Mapping):
        return False
    description = action.get("description")
    if not isinstance(description, str) or not description.strip():
        return False
    try:
        segments.instant_utc(action.get("echeance"))
    except (ValueError, TypeError):
        return False
    return True


def _statut_dit(valeur: Any) -> str:
    """Un statut dit dans une anomalie : seulement s'il est de la machine à états. Un statut inconnu vient d'un registre
    (donnée non fiable) : il n'est jamais recopié, `inconnu` le remplace."""
    return valeur if isinstance(valeur, str) and valeur in statuts.STATUTS else "inconnu"


def _non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and bool(valeur.strip())


# ---------------------------------------------------------------------------------------------------------
# Lecture du registre
# ---------------------------------------------------------------------------------------------------------
def _par_lead(
    maillons: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], dict[Any, list[Mapping[str, Any]]]]:
    """`(ingeres, maillons par lead)` : le maillon d'ingestion de chaque lead (le premier) et tous les maillons portant
    un `lead_id`, dans l'ordre du registre."""
    ingeres: dict[str, Mapping[str, Any]] = {}
    par_lead: dict[Any, list[Mapping[str, Any]]] = {}
    for maillon in maillons:
        if "lead_id" not in maillon:
            continue
        lead_id = maillon["lead_id"]
        try:
            par_lead.setdefault(lead_id, []).append(maillon)
        except TypeError:  # un lead_id illisible (non hachable) n'est le lead de personne
            par_lead.setdefault(repr(lead_id), []).append(maillon)
            continue
        if maillon.get("type_entree") == _T_INGESTION and isinstance(lead_id, str) and lead_id not in ingeres:
            ingeres[lead_id] = maillon
    return ingeres, par_lead


def _statut_courant(maillons_du_lead: Iterable[Mapping[str, Any]]) -> Any:
    statut = None
    for m in maillons_du_lead:
        if m.get("type_entree") in (_T_INGESTION, _T_TRANSITION):
            statut = m.get("statut")
    return statut


# ---------------------------------------------------------------------------------------------------------
# Les contrôles
# ---------------------------------------------------------------------------------------------------------
def _controle_statut(ingeres: Mapping[str, Any], par_lead: Mapping[Any, list]) -> list[dict[str, Any]]:
    trouvees = []
    for lead_id in sorted(ingeres):
        statut = _statut_courant(par_lead[lead_id])
        if statut is None:
            trouvees.append(_anomalie(C_STATUT, "statut_absent", lead_id=lead_id))
        elif statut not in statuts.STATUTS:
            trouvees.append(
                _anomalie(
                    C_STATUT, "statut_inconnu", lead_id=lead_id, empreinte_statut=encodage.empreinte(str(statut))[:12]
                )
            )
    return trouvees


def _contact_utilisable(contact: Any) -> bool:
    return isinstance(contact, Mapping) and (_non_vide(contact.get("telephone")) or _non_vide(contact.get("courriel")))


def _controle_contact(ingeres: Mapping[str, Any], maillons: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    corrections = clients.corrections_courantes(list(maillons))
    leads_du_client: dict[str, list[str]] = {}
    for m in maillons:
        if m.get("type_entree") == _T_CLIENT and isinstance(m.get("client_id"), str):
            lot = leads_du_client.setdefault(m["client_id"], [])
            if m.get("lead_id") not in lot:
                lot.append(m.get("lead_id"))
    trouvees = []
    for client_id in sorted(leads_du_client):
        correction = corrections.get(client_id)
        if correction is not None:
            utilisable = _contact_utilisable(correction.get("contact"))
        else:
            utilisable = any(
                _contact_utilisable((ingeres[lead].get("contrat") or {}).get("contact"))
                for lead in leads_du_client[client_id]
                if lead in ingeres and isinstance(ingeres[lead].get("contrat"), Mapping)
            )
        if not utilisable:
            trouvees.append(
                _anomalie(
                    C_CONTACT,
                    "ni_telephone_ni_courriel",
                    client_id=client_id,
                    leads=sorted(str(lead) for lead in leads_du_client[client_id])[:5],
                )
            )
    return trouvees


def _prochaine_action(maillons_du_lead: Iterable[Mapping[str, Any]]) -> Any:
    action = None
    for m in maillons_du_lead:
        if m.get("type_entree") == _T_TRANSITION and m.get("prochaine_action") is not None:
            action = m["prochaine_action"]
    return action


def _proprietaire(maillons_du_lead: Iterable[Mapping[str, Any]]) -> str | None:
    """Le propriétaire courant d'un lead : celui de la dernière réassignation, sinon de la dernière qualification."""
    proprietaire = None
    for m in maillons_du_lead:
        if m.get("type_entree") == _T_TRANSITION and m.get("statut") == "qualifie" and _non_vide(m.get("owner")):
            proprietaire = m["owner"].strip()
        elif m.get("type_entree") == _T_REASSIGNATION and _non_vide(m.get("nouveau_proprietaire")):
            proprietaire = m["nouveau_proprietaire"].strip()
    return proprietaire


def _controle_proprietaire(ingeres: Mapping[str, Any], par_lead: Mapping[Any, list]) -> list[dict[str, Any]]:
    trouvees = []
    for lead_id in sorted(ingeres):
        siens = par_lead[lead_id]
        statut = _statut_courant(siens)
        if statut not in _STATUTS_OUVERTS or statut == "nouveau":
            continue
        if _prochaine_action(siens) is not None and _proprietaire(siens) is None:
            trouvees.append(_anomalie(C_PROPRIETAIRE, "action_sans_proprietaire", lead_id=lead_id, statut=statut))
    return trouvees


def _controle_soumission(ingeres: Mapping[str, Any], devis: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    vus: set[str] = set()
    trouvees = []
    for fait in devis:
        devis_id = str(fait.get("devis_id"))
        if devis_id in vus:
            continue
        lead_id = fait.get("lead_id")
        if not isinstance(lead_id, str) or lead_id not in ingeres:
            vus.add(devis_id)
            trouvees.append(
                _anomalie(
                    C_SOUMISSION,
                    "devis_sans_lead",
                    lead_id=lead_id if isinstance(lead_id, str) else None,
                    devis_id=devis_id,
                )
            )
    return sorted(trouvees, key=lambda a: (a["donnee"]["devis_id"], a["lead_id"] or ""))


def _controle_activite(
    ingeres: Mapping[str, Any], par_lead: Mapping[Any, list], maillons: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    orphelins: dict[str, dict[str, int]] = {}
    for lead_id, siens in par_lead.items():
        if lead_id in ingeres:
            continue
        for m in siens:
            if m.get("type_entree") in _TYPES_PAR_LEAD:
                lot = orphelins.setdefault(str(lead_id), {})
                lot[m["type_entree"]] = lot.get(m["type_entree"], 0) + 1
    for m in maillons:
        if m.get("type_entree") == _T_DOUBLON:
            for cle in ("lead_id_a", "lead_id_b"):
                lead = m.get(cle)
                if lead not in ingeres:
                    lot = orphelins.setdefault(str(lead), {})
                    lot[_T_DOUBLON] = lot.get(_T_DOUBLON, 0) + 1
    return [
        _anomalie(C_ACTIVITE, "activite_sans_lead", lead_id=lead_id, maillons=dict(sorted(types.items())))
        for lead_id, types in sorted(orphelins.items())
    ]


def _controle_client(ingeres: Mapping[str, Any], par_lead: Mapping[Any, list]) -> list[dict[str, Any]]:
    return [
        _anomalie(C_CLIENT, "lead_sans_client", lead_id=lead_id)
        for lead_id in sorted(ingeres)
        if not any(m.get("type_entree") == _T_CLIENT and _non_vide(m.get("client_id")) for m in par_lead[lead_id])
    ]


def _rejouer(lead_id: str, maillons_du_lead: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rejoue l'historique d'UN lead. UNE anomalie par nature : le premier maillon fautif la porte."""
    trouvees: dict[str, dict[str, Any]] = {}

    def noter(nature: str, **donnee: Any) -> None:
        trouvees.setdefault(nature, _anomalie(C_PIPELINE, nature, lead_id=lead_id, **donnee))

    courant: Any = None
    for m in maillons_du_lead:
        type_entree = m.get("type_entree")
        if type_entree == _T_INGESTION:
            courant = m.get("statut")
        elif type_entree == _T_TRANSITION:
            precedent, nouveau = m.get("statut_precedent"), m.get("statut")
            if precedent != courant:
                noter("chaine_rompue", attendu=_statut_dit(courant), recu=_statut_dit(precedent))
            elif (precedent, nouveau) not in statuts.TRANSITIONS_AUTORISEES:
                noter("transition_illegale", de=_statut_dit(precedent), vers=_statut_dit(nouveau))
            if nouveau == "converti" and not _non_vide(m.get("reference_devis_m3")):
                noter("converti_sans_devis")
            if nouveau == "perdu" and not _non_vide(m.get("motif")):
                noter("perdu_sans_motif")
            if nouveau == "qualifie" and not _non_vide(m.get("owner")):
                noter("qualifie_sans_proprietaire")
            if nouveau == "qualifie" and not _action_valide(m.get("prochaine_action")):
                noter("qualifie_sans_action")
            if nouveau == "facture" and not _action_valide(m.get("prochaine_action")):
                noter("facture_sans_action")
            courant = nouveau
    return list(trouvees.values())


def _controle_pipeline(ingeres: Mapping[str, Any], par_lead: Mapping[Any, list]) -> list[dict[str, Any]]:
    """Rejoue l'historique de chaque lead (machine à états et conditions de chaque transition)."""
    return [a for lead_id in sorted(ingeres) for a in _rejouer(lead_id, par_lead[lead_id])]


def _contrat_effectif(
    ingere: Mapping[str, Any], corrections: Mapping[str, Mapping[str, Any]], client_de: Mapping[str, str]
) -> Mapping[str, Any]:
    contrat = ingere.get("contrat") if isinstance(ingere.get("contrat"), Mapping) else {}
    correction = corrections.get(client_de.get(ingere.get("lead_id"), ""))
    if correction is not None and isinstance(correction.get("contact"), Mapping):
        return {**contrat, "contact": correction["contact"]}
    return contrat


def _controle_doublon(
    ingeres: Mapping[str, Any], maillons: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """`(anomalies, listes, partiel)`. Les mêmes critères et la même fenêtre que `doublons.detecter` (à l'ingestion),
    mais
    sur tout le registre, sans signaler : les paires non couvertes sont des anomalies, les paires signalées et en
    attente
    sont listées."""
    corrections = clients.corrections_courantes(list(maillons))
    client_de = {
        m["lead_id"]: m["client_id"]
        for m in maillons
        if m.get("type_entree") == _T_CLIENT
        and isinstance(m.get("lead_id"), str)
        and isinstance(m.get("client_id"), str)
    }
    contrats = {lead: _contrat_effectif(m, corrections, client_de) for lead, m in ingeres.items()}
    # le dernier état de chaque signalement (arbitrage), par paire de leads
    arbitrage_de_paire: dict[tuple[str, str], str] = {}
    for m in maillons:
        if (
            m.get("type_entree") == _T_DOUBLON
            and isinstance(m.get("lead_id_a"), str)
            and isinstance(m.get("lead_id_b"), str)
        ):
            arbitrage_de_paire[tuple(sorted((m["lead_id_a"], m["lead_id_b"])))] = str(m.get("arbitrage"))
    # regroupements candidats : contact identique, ou même ville et mêmes travaux
    groupes: dict[tuple, list[str]] = {}
    for lead, contrat in contrats.items():
        contact = contrat.get("contact")
        if contact:
            groupes.setdefault(
                ("contact", repr(sorted(contact.items())) if isinstance(contact, Mapping) else repr(contact)), []
            ).append(lead)
        travaux = doublons._travaux(contrat)  # noqa: SLF001 — même lecture que la détection de l'ingestion
        if doublons._non_vide(contrat.get("ville")) and travaux is not None:  # noqa: SLF001
            groupes.setdefault(("ville_travaux", contrat.get("ville"), travaux), []).append(lead)

    def jour(lead: str) -> datetime:
        try:
            return segments.instant_utc(ingeres[lead].get("horodatage"))
        except (ValueError, TypeError):
            return datetime.min.replace(tzinfo=UTC)

    paires: dict[tuple[str, str], str] = {}
    examinees = 0
    partiel = False
    for cle in sorted(groupes, key=repr):
        membres = sorted(set(groupes[cle]), key=lambda lead: (jour(lead), lead))
        for i, a in enumerate(membres):
            for b in membres[i + 1 :]:
                if jour(b) - jour(a) > timedelta(days=doublons.FENETRE_JOURS + 1):
                    break  # membres triés par date : les suivants sont plus loin encore
                examinees += 1
                if examinees > MAX_PAIRES_EXAMINEES:
                    partiel = True
                    break
                paire = tuple(sorted((a, b)))
                if paire in paires:
                    continue
                critere = doublons.critere_entre(contrats[a], contrats[b])
                if critere is not None and doublons.dans_fenetre(ingeres[a]["horodatage"], ingeres[b]["horodatage"]):
                    paires[paire] = critere
            if partiel:
                break
        if partiel:
            break
    anomalies: list[dict[str, Any]] = []
    listes: list[dict[str, Any]] = []
    for paire in sorted(paires):
        arbitrage = arbitrage_de_paire.get(paire)
        if arbitrage == "distincts_confirmes":
            continue
        entree = {
            "lead_id_a": paire[0],
            "lead_id_b": paire[1],
            "critere": paires[paire],
            "signale": arbitrage is not None,
            "arbitrage": arbitrage,
        }
        listes.append(entree)
        if arbitrage is None:
            anomalies.append(
                _anomalie(
                    C_DOUBLON, "doublon_non_signale", lead_id=paire[0], autre_lead_id=paire[1], critere=paires[paire]
                )
            )
    return anomalies, listes, partiel


# ---------------------------------------------------------------------------------------------------------
# L'audit
# ---------------------------------------------------------------------------------------------------------
def auditer(maillons: Sequence[Mapping[str, Any]], *, devis: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """L'audit d'intégrité : `{"leads_examines", "maillons_examines", "controles", "anomalies", "doublons_probables",
    "doublons_en_attente"}`.

    `maillons` : le registre principal de M2 (UNE lecture). `devis` : les devis connus de M2 (`devis_id`, `lead_id`),
    tous
    registres confondus ; `None` : illisibles, `soumission_orpheline` est alors non évalué (jamais « aucun orphelin »).

    `controles` : les huit contrôles dans l'ordre de `CONTROLES`, chacun `{controle, etat, manque, anomalies}` (`None`
    pour
    un contrôle non évalué). `anomalies` : triées par contrôle, puis par identifiants (ordre total). Aucune écriture."""
    maillons = list(maillons)
    ingeres, par_lead = _par_lead(maillons)
    par_controle: dict[str, list[dict[str, Any]]] = {
        C_STATUT: _controle_statut(ingeres, par_lead),
        C_CONTACT: _controle_contact(ingeres, maillons),
        C_PROPRIETAIRE: _controle_proprietaire(ingeres, par_lead),
        C_SOUMISSION: _controle_soumission(ingeres, devis) if devis is not None else [],
        C_ACTIVITE: _controle_activite(ingeres, par_lead, maillons),
        C_CLIENT: _controle_client(ingeres, par_lead),
        C_PIPELINE: _controle_pipeline(ingeres, par_lead),
    }
    anomalies_doublon, doublons_listes, partiel = _controle_doublon(ingeres, maillons)
    par_controle[C_DOUBLON] = anomalies_doublon
    controles = []
    for controle in CONTROLES:
        etat, manque = ETAT_EVALUE, None
        if controle == C_SOUMISSION and devis is None:
            etat, manque = (
                ETAT_NON_EVALUE,
                (
                    "la lecture des devis reçus de M3 est impossible (registres devis_envoyes_recus, "
                    "relances_devis_recues, "
                    "devis_acceptes_recus)"
                ),
            )
        elif controle == C_DOUBLON and partiel:
            etat, manque = (
                ETAT_PARTIEL,
                (
                    f"le rapprochement s'est arrêté après {MAX_PAIRES_EXAMINEES} paires : relancer sur un registre "
                    f"plus petit "
                    "ou le découper"
                ),
            )
        controles.append(
            {
                "controle": controle,
                "etat": etat,
                "manque": manque,
                "anomalies": None if etat == ETAT_NON_EVALUE else len(par_controle[controle]),
            }
        )
    anomalies = [a for controle in CONTROLES for a in par_controle[controle]]
    return {
        "leads_examines": len(ingeres),
        "maillons_examines": len(maillons),
        "controles": controles,
        "anomalies": anomalies,
        "doublons_probables": doublons_listes[:MAX_DOUBLONS_LISTES],
        "doublons_en_attente": sum(1 for d in doublons_listes if d["arbitrage"] == "en_attente"),
        "doublons_tronques": len(doublons_listes) > MAX_DOUBLONS_LISTES,
    }
