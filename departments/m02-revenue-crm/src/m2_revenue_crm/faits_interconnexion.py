"""Ce que M7, M5 et M3 apprennent à M2 par le bus, lu SANS jamais écraser un fait de M2 (interconnexion).

Module PUR : aucune entrée-sortie, aucune horloge. `outils.py` reçoit les événements, range les faits (un registre par
type, une clé de CONTENU par fait : le même constat sous un autre `evenement_id` n'ajoute rien) et passe les registres
lus à ces fonctions.

- `m7.conversion_hors_ligne_importee` : une issue (appel, rendez-vous, soumission signée, vente) rattachée par M7 à une
  source normalisée (convention UTM gelée). Elle sert le score en LECTURE : un lead dont M7 connaît la source normalisée
  a une source connue (`sources_marketing`), même si son contrat n'en portait pas. Le contrat du lead n'est jamais
  réécrit, aucune source de M2 n'est remplacée, aucune causalité n'est affirmée (une conversion importée compte une
  issue, elle n'explique pas son origine) ;
- `m5.creance_relance_preparee` : M5 a PRÉPARÉ la relance d'une facture client en retard (rien n'est envoyé, M5 ne
  porte ni nom ni coordonnée). M2 en tire un avertissement de COORDINATION sur les relances COMMERCIALES du même
  client : ne pas relancer pour vendre quelqu'un qui doit déjà une facture sans que l'humain le sache. Aucune relance
  commerciale n'est supprimée ni retardée automatiquement ;
- `m5.facture_emise_constatee` (statut `PAYEE` ou `ANNULEE` seulement) : la facture n'est plus due. M2 en garde le FAIT
  (identifiant de facture et statut, aucun montant ni client) et LÈVE la relance de créance de cette facture : elle ne
  compte plus pour l'avertissement. Le fait est terminal : aucun événement ne le défait (un `ENVOYEE` plus ancien rejoué
  après le paiement n'est même pas rangé), et il se lit à la lecture, donc l'ordre de livraison ne compte pas (la
  relance peut arriver APRÈS le paiement). Un paiement PARTIEL n'est jamais `PAYEE` chez M5 : la relance reste ;
- `m4.travaux_termines` (champ `client_satisfait` SEULEMENT) : la satisfaction que le client a dite à la fin d'un
chantier,
  vraie ou fausse, gardée avec l'identifiant du chantier (`wct_id`) et celui du lead. Un `null` ou une absence n'est
  jamais
  rangé (rien n'est déduit). Ni nom, ni contact, ni note : un booléen et des identifiants. Elle débloque les segments
  `referral_candidate` et `complaint_risk` (`segments.py`) et la règle « plainte escaladée » du filet anti-perte ;
- `m3.contexte_site_pret` : la dernière version du contexte de site d'un lead (facteurs connus, inconnus, à vérifier,
  en conflit), dite au coach comme un FAIT daté. Rien n'est comblé ni tranché ici.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

REGISTRE_CONVERSIONS = "conversions_hors_ligne_recues"
REGISTRE_CREANCES = "creances_relances_recues"
REGISTRE_CONTEXTES_SITE = "contextes_site_recus"
REGISTRE_FACTURES_CLOSES = "factures_closes_recues"
REGISTRE_SATISFACTIONS = "satisfactions_recues"

TYPE_CONVERSION = "conversion_hors_ligne_recue"
TYPE_CREANCE = "creance_relance_recue"
TYPE_CONTEXTE_SITE = "contexte_site_recu"
TYPE_FACTURE_CLOSE = "facture_close_recue"
TYPE_SATISFACTION = "satisfaction_recue"
# Les seuls statuts de `m5.facture_emise_constatee` qui lèvent une relance de créance : la facture n'est plus due.
STATUTS_FACTURE_CLOSE = ("PAYEE", "ANNULEE")


def fait_conversion(charge: Mapping[str, Any]) -> dict[str, Any]:
    """La conversion telle que M7 l'a publiée, sans le moindre champ de plus (le catalogue est fermé)."""
    return {"type_entree": TYPE_CONVERSION, **charge}


def fait_creance(charge: Mapping[str, Any]) -> dict[str, Any]:
    return {"type_entree": TYPE_CREANCE, **charge}


def fait_contexte_site(charge: Mapping[str, Any]) -> dict[str, Any]:
    """Le contexte de site, réduit à ce que M2 lit : le lead, la version, l'empreinte et les COMPTES par statut (les
    valeurs sourcées restent chez M3, qui en est le propriétaire)."""
    statuts: dict[str, int] = {}
    for facteur in charge["facteurs"]:
        statuts[facteur["statut"]] = statuts.get(facteur["statut"], 0) + 1
    return {
        "type_entree": TYPE_CONTEXTE_SITE,
        "lead_id": charge["lead_id"],
        "service": charge["service"],
        "version": charge["version"],
        "empreinte": charge["empreinte"],
        "date_reference": charge["date_reference"],
        "facteurs_par_statut": dict(sorted(statuts.items())),
        "inconnus": len(charge["inconnus"]),
        "a_verifier": len(charge["a_verifier"]),
        "conflits": len(charge["conflits"]),
    }


def fait_facture_close(charge: Mapping[str, Any]) -> dict[str, Any] | None:
    """Le fait « facture soldée ou annulée » (identifiant et statut, rien d'autre), ou `None` si le constat ne lève rien
    (`ENVOYEE` : la facture est émise, donc due)."""
    if charge.get("statut") not in STATUTS_FACTURE_CLOSE:
        return None
    return {"type_entree": TYPE_FACTURE_CLOSE, "facture_id": charge["facture_id"], "statut": charge["statut"]}


def fait_satisfaction(charge: Mapping[str, Any], lead_applique: str | None) -> dict[str, Any] | None:
    """Le fait « satisfaction du client » d'un chantier terminé, ou `None` quand `client_satisfait` n'est pas un booléen
    (absent ou `null` : le client n'a rien dit, M2 ne le devine pas). `lead_id` est celui que M4 a publié ;
    `lead_id_applique` celui que M2 a fait avancer (ou `None` quand le chantier a ouvert une nouvelle opportunité) : la
    satisfaction se lit sur `lead_applique or lead_id`."""
    satisfait = charge.get("client_satisfait")
    if not isinstance(satisfait, bool):
        return None
    return {
        "type_entree": TYPE_SATISFACTION,
        "wct_id": charge["wct_id"],
        "lead_id": charge["lead_id"],
        "lead_id_applique": lead_applique,
        "client_satisfait": satisfait,
        "horodatage_completion": charge["horodatage_completion"],
    }


def satisfaction_par_lead(faits: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """`{lead_id: dernier fait de satisfaction}` : le chantier terminé le plus récemment fait foi (instants comparés en
    texte ISO normalisé quand ils se lisent, sinon l'ordre d'écriture). Un lead sans fait n'y figure pas."""
    meilleurs: dict[str, dict[str, Any]] = {}
    cle_de: dict[str, Any] = {}
    for fait in faits:
        if fait.get("type_entree") != TYPE_SATISFACTION:
            continue
        lead = fait.get("lead_id_applique") or fait["lead_id"]
        try:
            cle = datetime.fromisoformat(fait["horodatage_completion"]).timestamp()
        except (ValueError, TypeError, KeyError):
            cle = float("-inf")
        if lead not in meilleurs or cle >= cle_de[lead]:
            meilleurs[lead], cle_de[lead] = dict(fait), cle
    return meilleurs


CLES_UNICITE = {
    TYPE_SATISFACTION: ("wct_id",),
    TYPE_FACTURE_CLOSE: ("facture_id", "statut"),
    TYPE_CONVERSION: ("conversion_id",),
    TYPE_CREANCE: ("relance_id",),
    TYPE_CONTEXTE_SITE: ("lead_id", "version"),
}


def sources_marketing(conversions: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    """Les `lead_id` dont M7 connaît une source NORMALISÉE (source présente et normalisée)."""
    return frozenset(
        c["lead_id"]
        for c in conversions
        if c.get("type_entree") == TYPE_CONVERSION and c.get("source_normalisee") is True and c.get("utm_source")
    )


def creances_ouvertes(
    creances: Iterable[Mapping[str, Any]], factures_closes: Iterable[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    """Les relances de créance dont la facture n'est ni payée ni annulée. Calculé À LA LECTURE depuis les deux
    registres : ni l'ordre de livraison ni un rejeu ne peuvent la rouvrir."""
    closes = {f["facture_id"] for f in factures_closes if f.get("type_entree") == TYPE_FACTURE_CLOSE}
    return [c for c in creances if c.get("type_entree") != TYPE_CREANCE or c.get("facture_id") not in closes]


def creances_par_client(creances: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """`{client_id: relance de créance la plus avancée}` (le plus haut niveau, puis le plus de jours de retard)."""
    meilleures: dict[str, dict[str, Any]] = {}
    for c in creances:
        if c.get("type_entree") != TYPE_CREANCE:
            continue
        actuelle = meilleures.get(c["client_id"])
        if actuelle is None or (c["niveau"], c["jours_retard"]) > (actuelle["niveau"], actuelle["jours_retard"]):
            meilleures[c["client_id"]] = c
    return meilleures


def contexte_site_du_lead(contextes: Iterable[Mapping[str, Any]], lead_id: str) -> dict[str, Any] | None:
    """La version la plus récente (plus grand `version`) du contexte de site de ce lead, ou `None`."""
    versions = [c for c in contextes if c.get("type_entree") == TYPE_CONTEXTE_SITE and c.get("lead_id") == lead_id]
    return max(versions, key=lambda c: c["version"]) if versions else None


def phrase_creance(creance: Mapping[str, Any]) -> str:
    return (
        f"Le client a une facture en retard : M5 a préparé une relance de créance de niveau {creance['niveau']} "
        f"({creance['jours_retard']} jours de retard). À coordonner avec M5 avant toute relance commerciale ; rien "
        "n'est envoyé automatiquement."
    )


def phrase_contexte_site(contexte: Mapping[str, Any]) -> str:
    return (
        f"Contexte de site de M3 (version {contexte['version']} du {contexte['date_reference']}) : "
        f"{contexte['facteurs_par_statut'].get('connu', 0)} facteur(s) connu(s), {contexte['inconnus']} inconnu(s), "
        f"{contexte['a_verifier']} à vérifier, {contexte['conflits']} en conflit. Rien n'est comblé ni tranché par M2."
    )


def phrase_conversion(conversions: Iterable[Mapping[str, Any]], lead_id: str) -> str | None:
    """Une phrase fixe par lead quand M7 a importé des conversions hors ligne pour lui, sinon `None`."""
    siennes = [c for c in conversions if c.get("type_entree") == TYPE_CONVERSION and c.get("lead_id") == lead_id]
    if not siennes:
        return None
    types = ", ".join(sorted({c["type"] for c in siennes}))
    sources = sorted({c["utm_source"] for c in siennes if c.get("utm_source")})
    origine = f"source normalisée : {', '.join(sources)}" if sources else "source non normalisée"
    return (
        f"M7 a importé {len(siennes)} conversion(s) hors ligne pour ce lead ({types} ; {origine}). Elle compte une "
        "issue, elle n'établit aucune causalité."
    )
