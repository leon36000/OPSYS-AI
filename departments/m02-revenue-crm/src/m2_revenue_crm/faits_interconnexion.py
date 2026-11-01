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
- `m3.contexte_site_pret` : la dernière version du contexte de site d'un lead (facteurs connus, inconnus, à vérifier,
  en conflit), dite au coach comme un FAIT daté. Rien n'est comblé ni tranché ici.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

REGISTRE_CONVERSIONS = "conversions_hors_ligne_recues"
REGISTRE_CREANCES = "creances_relances_recues"
REGISTRE_CONTEXTES_SITE = "contextes_site_recus"

TYPE_CONVERSION = "conversion_hors_ligne_recue"
TYPE_CREANCE = "creance_relance_recue"
TYPE_CONTEXTE_SITE = "contexte_site_recu"


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


CLES_UNICITE = {
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
