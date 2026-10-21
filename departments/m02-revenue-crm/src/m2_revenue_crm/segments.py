"""Segmentation des leads (PLAN T4.6 ; DEFINITION-PRODUIT §7 M2, M2.11).

Module PUR : aucun import d'``opsys``, aucune horloge, aucun aléa, aucune lecture de fichier. L'instant de
référence (``faits["maintenant"]``), les seuils et tous les faits viennent de l'appelant (``liste_leads.py``
et ``outils.py``, seuls à lire le registre et ``department.yaml``). Une même entrée donne toujours la même
sortie.

Les 14 segments de M2.11, dans l'ordre de la définition. Chacun est dans un de ces trois états, jamais un
quatrième :
  - **appliqué** : la règle est citée (``regle``, texte dans ``REGLES``) avec la donnée qui la déclenche
    (``donnee``) ;
  - **non appliqué** : le segment est calculable et la règle ne se déclenche pas ;
  - **non calculable** : « non calculable, manque X ». Aucun segment n'est deviné.

Huit segments se calculent des faits que M2 tient déjà : ``hot_lead``, ``estimate_ready``, ``quote_stale``,
``won_pending_schedule``, ``active_job``, ``invoice_pending``, ``past_customer``, ``dormant_lead``. Les six
autres (``needs_photos``, ``quote_sent``, ``high_value_customer``, ``referral_candidate``, ``complaint_risk``,
``seasonal_opportunity``) reposent sur une donnée qui n'atteint pas M2 : ils rendent ce qui manque, pour
tous les leads.

Deux segments dépendent d'un SEUIL de ``department.yaml`` (``configuration.segments``) : ``dormant_lead``
(jours d'inactivité) et ``quote_stale`` (jours depuis l'envoi d'un devis). Les seuils sont VIDES par
défaut : sans seuil, ces deux segments sont non calculables (« seuil à configurer »), jamais évalués avec
une valeur inventée. Même discipline que M6 (seuils de variance) et M8 (``seuils_alerte``).

Ce que chaque règle lit (les définitions sont celles de ce module, à valider par le propriétaire : le
document de définition nomme les segments, il ne les définit pas) :
  - le statut courant et la donnée d'ingestion du lead (``urgence_declaree``) ;
  - la readiness M3 (``readiness.evaluer``, jamais recalculée ici) ;
  - les devis sans réponse que M3 a publiés (``m3.devis_sans_reponse``, registre ``relances_devis_recues``) ;
  - la date de la dernière activité humaine du lead ;
  - les opportunités du même client que l'appelant a le droit de voir (T1.4-k2 : un vendeur ne voit d'un
    client que ses opportunités, donc ``past_customer`` ne lit jamais le lead d'un autre vendeur).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

__all__ = [
    "CHEMIN_SEUILS",
    "CLE_JOURS_DORMANT",
    "CLE_JOURS_PERIMEE",
    "REGLES",
    "SEGMENTS",
    "SEGMENTS_CALCULABLES",
    "SEGMENTS_NON_CALCULABLES",
    "instant_utc",
    "lire_seuils",
    "manque_du_segment",
    "segmenter",
    "segments_non_calculables",
]

# Ordre de DEFINITION-PRODUIT §7 M2.11. C'est aussi l'ordre de toute sortie de ce module.
SEGMENTS = (
    "hot_lead",
    "needs_photos",
    "estimate_ready",
    "quote_sent",
    "quote_stale",
    "won_pending_schedule",
    "active_job",
    "invoice_pending",
    "past_customer",
    "high_value_customer",
    "referral_candidate",
    "complaint_risk",
    "dormant_lead",
    "seasonal_opportunity",
)

# Statuts lus par les règles (statuts.STATUTS). `test_segments.py` vérifie que chacun existe encore : un statut
# renommé ou retiré de la machine à états fait échouer le test, il ne rend pas une règle muette.
_STATUTS_OUVERTS = ("nouveau", "qualifie")
_STATUT_QUALIFIE = "qualifie"
_STATUT_CONVERTI = "converti"
_STATUTS_CHANTIER = ("cedule", "chantier")
_STATUTS_FACTURE = ("facture", "paiement")
_STATUT_PAYE = "avis"

_SECONDES_PAR_JOUR = 86400

CLE_JOURS_DORMANT = "jours_inactivite_dormant"
CLE_JOURS_PERIMEE = "jours_soumission_perimee"
CHEMIN_SEUILS = "configuration.segments"
_CLES_SEUILS = (CLE_JOURS_DORMANT, CLE_JOURS_PERIMEE)

ETAT_SEUIL_OK = "ok"
ETAT_SEUIL_A_CONFIGURER = "a_configurer"
ETAT_SEUIL_INVALIDE = "invalide"

# Règles citées : identifiant stable -> énoncé. Un segment appliqué porte l'identifiant ; l'énoncé se lit
# ici (et dans `regles` de la réponse de `m2_lister_leads`).
_REGLE_DE_SEGMENT = {
    "hot_lead": "urgence_declaree_lead_ouvert",
    "estimate_ready": "readiness_m3_satisfaite",
    "quote_stale": "devis_envoye_sans_reponse_perime",
    "won_pending_schedule": "soumission_acceptee_a_planifier",
    "active_job": "chantier_cedule_ou_en_cours",
    "invoice_pending": "chantier_facture_paiement_non_confirme",
    "past_customer": "client_avec_chantier_paye",
    "dormant_lead": "lead_ouvert_sans_activite",
}
REGLES = {
    "urgence_declaree_lead_ouvert": (
        "Urgence déclarée à l'ingestion (contrat : urgence_declaree) sur un lead encore ouvert "
        "(statut nouveau ou qualifie)."
    ),
    "readiness_m3_satisfaite": (
        "Lead qualifié dont la readiness M3 est satisfaite : owner, service (ou type de travaux) valide, "
        "ville et interaction après la qualification (readiness.evaluer)."
    ),
    "devis_envoye_sans_reponse_perime": (
        "Lead qualifié dont un devis envoyé est resté sans réponse (m3.devis_sans_reponse, statut envoye) "
        f"depuis au moins {CLE_JOURS_PERIMEE} jours ({CHEMIN_SEUILS}.{CLE_JOURS_PERIMEE})."
    ),
    "soumission_acceptee_a_planifier": (
        "Lead converti : la soumission est acceptée et le chantier reste à planifier par M4 "
        "(règle planifier_chantier)."
    ),
    "chantier_cedule_ou_en_cours": "Lead au statut cedule ou chantier : le chantier est cédulé ou en cours (M4).",
    "chantier_facture_paiement_non_confirme": (
        "Lead au statut facture ou paiement : chantier facturé, paiement non confirmé (M2.8, lien M5)."
    ),
    "client_avec_chantier_paye": (
        "Le client a une opportunité au statut avis : un chantier terminé et payé. Seules les opportunités "
        "que l'appelant a le droit de voir comptent (un vendeur : les siennes)."
    ),
    "lead_ouvert_sans_activite": (
        "Lead ouvert (nouveau ou qualifie) sans activité humaine (ingestion, transition, interaction d'une "
        f"personne) depuis au moins {CLE_JOURS_DORMANT} jours ({CHEMIN_SEUILS}.{CLE_JOURS_DORMANT})."
    ),
}

# Segments qui reposent sur une donnée que M2 n'a pas : le manque est le même pour tous les leads.
_MANQUES_STRUCTURELS = {
    "needs_photos": "non calculable, manque l'état des photos du lead (M3 les qualifie, rien n'atteint M2)",
    "quote_sent": "non calculable, manque le fait « devis envoyé » de M3 (m3.devis_envoye, T4.7)",
    "high_value_customer": "non calculable, manque la valeur du client (montants à M3 et à M5) et un seuil de valeur",
    "referral_candidate": (
        "non calculable, manque la satisfaction du client (client_satisfait de M4, non gardé par M2)"
    ),
    "complaint_risk": "non calculable, manque les plaintes et la satisfaction du client (M1 T4.5, M4)",
    "seasonal_opportunity": (
        "non calculable, manque le calendrier saisonnier des services et l'historique par saison"
    ),
}
SEGMENTS_NON_CALCULABLES = tuple(s for s in SEGMENTS if s in _MANQUES_STRUCTURELS)
SEGMENTS_CALCULABLES = tuple(s for s in SEGMENTS if s not in _MANQUES_STRUCTURELS)


# ---------------------------------------------------------------------------------------------------------
# Seuils
# ---------------------------------------------------------------------------------------------------------
def _seuil_valide(valeur: Any) -> bool:
    """Un nombre entier de jours, au moins 1. Un booléen n'est pas un nombre de jours."""
    return isinstance(valeur, int) and not isinstance(valeur, bool) and valeur >= 1


def lire_seuils(brut: Any) -> dict[str, dict[str, Any]]:
    """Les deux seuils de ``configuration.segments``, chacun ``{"etat", "valeur"}``.

    ``etat`` : ``ok`` (entier ≥ 1, ``valeur`` le porte), ``a_configurer`` (clé absente ou nulle : le bloc
    est vide à dessein) ou ``invalide`` (tout le reste, dont un bloc qui n'est pas un dictionnaire).
    ``valeur`` est ``None`` hors ``ok`` : jamais un défaut. Une clé inconnue est ignorée."""
    bloc_illisible = brut is not None and not isinstance(brut, dict)
    seuils: dict[str, dict[str, Any]] = {}
    for cle in _CLES_SEUILS:
        valeur = brut.get(cle) if isinstance(brut, dict) else None
        if bloc_illisible:
            etat = ETAT_SEUIL_INVALIDE
        elif valeur is None:
            etat = ETAT_SEUIL_A_CONFIGURER
        elif _seuil_valide(valeur):
            etat = ETAT_SEUIL_OK
        else:
            etat = ETAT_SEUIL_INVALIDE
        seuils[cle] = {"etat": etat, "valeur": valeur if etat == ETAT_SEUIL_OK else None}
    return seuils


def _manque_seuil(cle: str, seuils: dict[str, dict[str, Any]]) -> str | None:
    """Ce qui manque pour le seuil ``cle`` (``None`` : le seuil est valide)."""
    etat = seuils.get(cle, {}).get("etat", ETAT_SEUIL_A_CONFIGURER)
    if etat == ETAT_SEUIL_OK:
        return None
    if etat == ETAT_SEUIL_INVALIDE:
        return (
            f"non calculable, manque un seuil {cle} valide : seuil invalide ({CHEMIN_SEUILS}, entier de jours ≥ 1)"
        )
    return f"non calculable, manque le seuil {cle} : seuil à configurer ({CHEMIN_SEUILS}, entier de jours ≥ 1)"


def _manques_globaux(seuils: dict[str, dict[str, Any]], devis_lisibles: bool) -> dict[str, str]:
    """``{segment: manque}`` des segments non calculables pour TOUS les leads."""
    manques = dict(_MANQUES_STRUCTURELS)
    manque_dormant = _manque_seuil(CLE_JOURS_DORMANT, seuils)
    if manque_dormant is not None:
        manques["dormant_lead"] = manque_dormant
    manque_perimee = _manque_seuil(CLE_JOURS_PERIMEE, seuils)
    if manque_perimee is not None:
        manques["quote_stale"] = manque_perimee
    elif not devis_lisibles:
        manques["quote_stale"] = (
            "non calculable, manque la lecture des devis sans réponse reçus de M3 (registre relances_devis_recues)"
        )
    return manques


def segments_non_calculables(
    seuils: dict[str, dict[str, Any]], devis_lisibles: bool = True
) -> list[dict[str, str]]:
    """Les segments non calculables pour tous les leads, dans l'ordre de ``SEGMENTS``, chacun
    ``{"segment", "manque"}``. Les six segments sans donnée en font toujours partie ; ``dormant_lead`` et
    ``quote_stale`` s'y ajoutent tant que leur seuil est absent ou invalide (``quote_stale`` aussi quand les
    devis reçus de M3 ne sont pas lisibles)."""
    manques = _manques_globaux(seuils, devis_lisibles)
    return [{"segment": s, "manque": manques[s]} for s in SEGMENTS if s in manques]


def manque_du_segment(
    segment: str, seuils: dict[str, dict[str, Any]], devis_lisibles: bool = True
) -> str | None:
    """« non calculable, manque X » du segment pour tous les leads, ou ``None`` s'il est calculable."""
    return _manques_globaux(seuils, devis_lisibles).get(segment)


# ---------------------------------------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------------------------------------
def instant_utc(valeur: Any) -> datetime:
    """Instant UTC d'un horodatage ISO-8601 AVEC fuseau. Sans fuseau, illisible ou pas du texte : refus
    (``ValueError`` ou ``TypeError``), jamais le fuseau de la machine."""
    instant = datetime.fromisoformat(valeur)
    if instant.tzinfo is None or instant.tzinfo.utcoffset(instant) is None:
        raise ValueError(f"horodatage sans fuseau : {valeur!r}")
    return instant.astimezone(UTC)


def _jours_entiers(secondes: float) -> int:
    return int(secondes // _SECONDES_PAR_JOUR)


# ---------------------------------------------------------------------------------------------------------
# Segmentation d'un lead
# ---------------------------------------------------------------------------------------------------------
def _applique(segment: str, donnee: dict[str, Any]) -> dict[str, Any]:
    return {"segment": segment, "regle": _REGLE_DE_SEGMENT[segment], "donnee": donnee}


def _devis_perime(
    devis_du_lead: list[dict[str, Any]], seuil_jours: int, maintenant: datetime
) -> tuple[dict[str, Any] | None, str | None]:
    """``(donnée, None)`` du devis envoyé le plus ancien qui dépasse le seuil, sinon ``(None, manque)`` si un
    devis envoyé a un horodatage illisible et qu'aucun autre ne dépasse, sinon ``(None, None)``."""
    perimes: list[tuple[float, str, dict[str, Any]]] = []
    illisibles: list[str] = []
    for devis in devis_du_lead:
        if devis.get("statut_devis") != "envoye":
            continue
        try:
            age = (maintenant - instant_utc(devis.get("horodatage_devis"))).total_seconds()
        except (ValueError, TypeError):
            illisibles.append(str(devis.get("devis_id")))
            continue
        if age >= seuil_jours * _SECONDES_PAR_JOUR:
            perimes.append((age, str(devis.get("devis_id")), devis))
    if perimes:
        age, devis_id, devis = sorted(perimes, key=lambda p: (-p[0], p[1]))[0]
        return {
            "devis_id": devis_id,
            "statut_devis": "envoye",
            "horodatage_devis": devis["horodatage_devis"],
            "jours_ecoules": _jours_entiers(age),
            "seuil_jours": seuil_jours,
        }, None
    if illisibles:
        return None, (
            f"non calculable, manque l'horodatage lisible du devis {sorted(illisibles)[0]} "
            "(m3.devis_sans_reponse)"
        )
    return None, None


def segmenter(lead: dict[str, Any], faits: dict[str, Any], seuils: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Les segments d'UN lead : ``{"lead_id", "segments", "non_calculables"}``.

    ``lead`` : ``lead_id``, ``statut``, ``urgence_declaree``, ``derniere_activite`` (horodatage de la dernière
    activité humaine, ``None`` si aucun n'est lisible), ``reference_devis_m3``.

    ``faits`` : ``maintenant`` (horodatage ISO-8601 avec fuseau, obligatoire : ``ValueError`` ou ``TypeError``
    sinon),
    ``pret_pour_m3`` (booléen de ``readiness.evaluer``, lu pour un lead qualifié), ``devis_sans_reponse`` (les
    faits de M3 de CE lead ; ``None`` : source illisible), ``opportunite_payee`` (le ``lead_id`` d'une
    opportunité du client au statut ``avis`` que l'appelant peut voir, sinon ``None``).

    ``seuils`` : ``lire_seuils(...)``.

    ``segments`` : les segments appliqués, dans l'ordre de ``SEGMENTS``, chacun avec sa règle et sa donnée.
    ``non_calculables`` : chaque segment que ce lead ne permet pas de calculer, avec ce qui manque (les
    manques de ``segments_non_calculables`` et ceux qui tiennent à la donnée de ce lead). Un segment n'est
    jamais dans les deux listes."""
    lead_id = lead["lead_id"]
    statut = lead["statut"]
    maintenant = instant_utc(faits["maintenant"])
    devis = faits.get("devis_sans_reponse")
    manques = _manques_globaux(seuils, devis is not None)
    appliques: dict[str, dict[str, Any]] = {}

    if lead.get("urgence_declaree") is True and statut in _STATUTS_OUVERTS:
        appliques["hot_lead"] = _applique("hot_lead", {"urgence_declaree": True, "statut": statut})

    if statut == _STATUT_QUALIFIE:
        pret = faits.get("pret_pour_m3")
        if pret is True:
            appliques["estimate_ready"] = _applique(
                "estimate_ready", {"statut": statut, "pret_pour_m3": True})
        elif pret is not False:
            manques["estimate_ready"] = "non calculable, manque l'évaluation de la readiness M3 de ce lead"

    if statut == _STATUT_QUALIFIE and "quote_stale" not in manques:
        donnee, manque = _devis_perime(devis or [], seuils[CLE_JOURS_PERIMEE]["valeur"], maintenant)
        if donnee is not None:
            appliques["quote_stale"] = _applique("quote_stale", donnee)
        elif manque is not None:
            manques["quote_stale"] = manque

    if statut == _STATUT_CONVERTI:
        appliques["won_pending_schedule"] = _applique(
            "won_pending_schedule",
            {"statut": statut, "reference_devis_m3": lead.get("reference_devis_m3")},
        )

    if statut in _STATUTS_CHANTIER:
        appliques["active_job"] = _applique("active_job", {"statut": statut})

    if statut in _STATUTS_FACTURE:
        appliques["invoice_pending"] = _applique("invoice_pending", {"statut": statut})

    payee = faits.get("opportunite_payee")
    if payee:
        appliques["past_customer"] = _applique(
            "past_customer", {"lead_paye": payee, "statut": _STATUT_PAYE})

    if statut in _STATUTS_OUVERTS and "dormant_lead" not in manques:
        try:
            ecoule = (maintenant - instant_utc(lead.get("derniere_activite"))).total_seconds()
        except (ValueError, TypeError):
            manques["dormant_lead"] = (
                "non calculable, manque la date de la dernière activité de ce lead (aucun horodatage lisible)"
            )
        else:
            seuil = seuils[CLE_JOURS_DORMANT]["valeur"]
            if ecoule >= seuil * _SECONDES_PAR_JOUR:
                appliques["dormant_lead"] = _applique("dormant_lead", {
                    "derniere_activite": lead["derniere_activite"],
                    "jours_ecoules": _jours_entiers(ecoule),
                    "seuil_jours": seuil,
                })

    return {
        "lead_id": lead_id,
        "segments": [appliques[s] for s in SEGMENTS if s in appliques],
        "non_calculables": [{"segment": s, "manque": manques[s]} for s in SEGMENTS if s in manques],
    }
