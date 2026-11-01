"""Les FAITS d'entrée du score de lead, lus des registres de M2 (M2.4) : booléens et compteurs seulement.

Ce module est la couture entre les registres (leads, interactions, doublons, consentements, profils de propriété,
valeurs déclarées) et le modèle pur (`scoring.py`). Il ne rend JAMAIS une valeur personnelle : la présence d'un
courriel, pas le courriel ; la présence d'un nom, pas le nom. C'est ce qui rend le score insensible à l'identité d'une
personne.

Module sans entrée-sortie : les registres lui sont passés déjà lus.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Any

from . import consentements, contrats, doublons, liste_leads, propriete, readiness, segments, valeurs

__all__ = ["Contexte", "construire_contexte", "faits_du_lead"]

_SECONDES_PAR_JOUR = 86400
_AUTEUR_SYSTEME = "system:"


@dataclasses.dataclass(frozen=True)
class Contexte:
    maintenant: str
    fiches: Mapping[str, Any]
    opportunites: Mapping[str, list[str]]
    doublons_en_attente: frozenset[str]
    retraits: Sequence[Mapping[str, Any]]
    valeurs: Mapping[str, int]
    bandes: list[int] | None
    seuil_dormant: int | None
    devis_envoyes: frozenset[str] | None
    profils: Mapping[str, Mapping[str, Any]]
    maillons: list[dict[str, Any]]
    # Leads dont M7 connaît une source normalisée (conversions hors ligne importées) : lecture seule.
    sources_marketing: frozenset[str] = frozenset()


def _doublons_en_attente(maillons: list[dict[str, Any]]) -> frozenset[str]:
    derniers: dict[str, dict] = {}
    for signalement in doublons.lister_signalements(liste_leads.Vue(maillons)):
        derniers[signalement["signalement_id"]] = signalement
    leads: set[str] = set()
    for signalement in derniers.values():
        if signalement["arbitrage"] == "en_attente":
            leads.update((signalement["lead_id_a"], signalement["lead_id_b"]))
    return frozenset(leads)


def _profils(maillons_propriete: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """`{client_id: {confirme, completude, photos}}` d'après les profils CONFIRMÉS seulement (un brouillon n'est pas un
    fait) : complétude du meilleur profil, photos liées au total."""
    vue = liste_leads.Vue(list(maillons_propriete))
    par_client: dict[str, list[str]] = {}
    for m in maillons_propriete:
        if m.get("type_entree") == propriete.TYPE_ENTREE:
            lot = par_client.setdefault(m["client_id"], [])
            if m["propriete_id"] not in lot:
                lot.append(m["propriete_id"])
    sortie: dict[str, dict[str, Any]] = {}
    for client_id, ids in par_client.items():
        confirmes = [etat["confirme"] for pid in ids if (etat := propriete.etat(vue, pid))["confirme"] is not None]
        sortie[client_id] = {
            "confirme": bool(confirmes),
            "completude": max((propriete.completude(c["champs"])["pourcentage"] for c in confirmes), default=0),
            "photos": sum(len(c["champs"].get("photos_liees", {}).get("valeur", [])) for c in confirmes),
        }
    return sortie


def construire_contexte(
    maillons: list[dict[str, Any]],
    *,
    maintenant: str,
    retraits: Sequence[Mapping[str, Any]],
    maillons_valeurs: Sequence[Mapping[str, Any]],
    maillons_propriete: Sequence[dict[str, Any]],
    bandes: Any,
    seuils: Mapping[str, Mapping[str, Any]],
    devis: Sequence[Mapping[str, Any]] | None,
    sources_marketing: frozenset[str] = frozenset(),
) -> Contexte:
    """Une lecture des registres, partagée par tous les leads d'un classement."""
    seuil = seuils.get(segments.CLE_JOURS_DORMANT, {}).get("valeur")
    return Contexte(
        maintenant=maintenant,
        fiches=liste_leads.fiches_des_leads(maillons),
        opportunites=liste_leads.opportunites_par_client(maillons),
        doublons_en_attente=_doublons_en_attente(maillons),
        retraits=list(retraits),
        valeurs=valeurs.courantes(maillons_valeurs),
        bandes=valeurs.lire_bandes(bandes),
        seuil_dormant=seuil if type(seuil) is int else None,
        devis_envoyes=(
            None if devis is None else frozenset(d.get("lead_id") for d in devis if d.get("statut_devis") == "envoye")
        ),
        profils=_profils(maillons_propriete),
        maillons=maillons,
        sources_marketing=sources_marketing,
    )


def _jours(depuis: str | None, maintenant: str) -> int:
    if depuis is None:
        return 0
    ecart = (segments.instant_utc(maintenant) - segments.instant_utc(depuis)).total_seconds()
    return max(0, int(ecart // _SECONDES_PAR_JOUR))


def faits_du_lead(contexte: Contexte, lead_id: str) -> dict[str, Any] | None:
    """Les faits d'un lead OUVERT (nouveau, qualifié), ou `None` : lead inconnu ou clos."""
    fiche = contexte.fiches.get(lead_id)
    if fiche is None or fiche.statut not in ("nouveau", "qualifie"):
        return None
    contrat = fiche.contrat
    contact = contrat.get("contact") if isinstance(contrat.get("contact"), dict) else {}
    travaux = (
        contrat.get("service")
        if contrat.get("schema_version") == contrats.VERSION_CONTRAT_V2
        else contrat.get("type_travaux")
    )

    def present(valeur: Any) -> bool:
        return isinstance(valeur, str) and bool(valeur.strip())

    humaines = sum(
        1
        for m in fiche.vue.lire()
        if m.get("type_entree") == "interaction" and not str(m.get("auteur", "")).startswith(_AUTEUR_SYSTEME)
    )
    conditions = readiness.conditions(fiche.vue, lead_id) if fiche.statut == "qualifie" else None
    profil = contexte.profils.get(fiche.client_id or "", {"confirme": False, "completude": 0, "photos": 0})
    personne = frozenset({lead_id, *contexte.opportunites.get(fiche.client_id or "", ())})
    retire = any(
        consentements.etat_du_canal(canal, personne, [], contexte.retraits)["etat"] == consentements.ETAT_RETIRE
        for canal in consentements.CANAUX_ECRITS
    )
    return {
        "contact_courriel": present(contact.get("courriel")),
        "contact_telephone": present(contact.get("telephone")),
        "contact_nom": present(contact.get("nom")),
        "ville": present(contrat.get("ville")),
        "service": present(travaux),
        "canal_connu": contrat.get("canal") in contrats.CANAUX,
        # La source du contrat de M2, OU celle que M7 a normalisée pour ce lead (lecture : le contrat n'est pas
        # modifié).
        "source_connue": any(contrat.get(cle) for cle in contrats.CHAMPS_CONTRAT_OPTIONNELS)
        or lead_id in contexte.sources_marketing,
        "completude_propriete_pct": profil["completude"],
        "urgence_declaree": contrat.get("urgence_declaree") is True,
        "jours_depuis_ingestion": _jours(fiche.ingere_le, contexte.maintenant),
        "statut": fiche.statut,
        "interactions_humaines": humaines,
        "jours_depuis_activite": _jours(fiche.derniere_activite or fiche.ingere_le, contexte.maintenant),
        "devis_envoye": None if contexte.devis_envoyes is None else lead_id in contexte.devis_envoyes,
        "readiness_proprietaire": None if conditions is None else bool(conditions["owner_valide"]),
        "readiness_service": None if conditions is None else bool(conditions["travaux_valide"]),
        "readiness_ville": None if conditions is None else bool(conditions["ville_valide"]),
        "readiness_interaction": None if conditions is None else bool(conditions["interaction_ok"]),
        "profil_propriete_confirme": bool(profil["confirme"]),
        "photos_liees": profil["photos"],
        "valeur_declaree_cents": contexte.valeurs.get(lead_id),
        "bandes_valeur_cents": contexte.bandes,
        "doublon_en_attente": lead_id in contexte.doublons_en_attente,
        "retrait_consentement": retire,
        "seuil_dormant_jours": contexte.seuil_dormant,
    }
