"""Données FICTIVES de M8 : une entreprise inventée, déterministe, pour les tests, la démonstration et la calibration.

``fictif: true`` — aucune donnée réelle : des identifiants (``lead-fictif-001``…), des instants et des montants
inventés,
sans aucun nom de personne, de client ni de technicien réel (le technicien d'un fait de chantier est ``tech-fictif``).
Module PUR : aucune horloge, aucun hasard (les nombres viennent des paramètres), aucun import d'``opsys``. Les faits
sont
construits par les VRAIS constructeurs de M8 (``entonnoir.fait_*``, ``mesures_chantier.fait_*``,
``contenus.fait_*``, ``cash_libre.fait_constat``) : ce que les tests lisent est la forme que les registres portent.

Aucun chemin de production n'importe ce module : il sert ``tests/``, ``evals/`` et la calibration du score de santé
(``sante.calibrer``), qui doit se mesurer sur des entreprises dont on connaît l'état.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import cash_libre, contenus, entonnoir, mesures_chantier

FICTIF = True

_FUSEAU = "-04:00"
_DUREE_ESTIMEE_MINUTES = 100


def _instant(jour: str, heure: int, minute: int = 0) -> str:
    return f"{jour}T{heure:02d}:{minute:02d}:00{_FUSEAU}"


def _id(prefixe: str, rang: int) -> str:
    return f"{prefixe}-fictif-{rang:03d}"


def registres_fictifs(
    *,
    jour: str = "2026-10-30",
    leads: int = 20,
    qualifies: int = 16,
    envoyes: int = 12,
    acceptes: int = 6,
    sans_reponse: int = 2,
    chantiers: int = 4,
    ecart_duree_pct: int = 10,
    signaux_materiaux: int = 0,
    avec_variance: bool = True,
    cash_libre_cad: str | None = "25000.00",
    contenus_exportes: int = 3,
    prix_devis: str = "12500.00",
    delai_acceptation_jours: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    """Les quatre registres (``chantier``, ``entonnoir``, ``contenus``, ``cash_libre``) d'une entreprise fictive.

    Les comptes sont des paramètres, jamais calculés au hasard : ``leads`` reçus, dont ``qualifies`` qualifiés ;
    ``envoyes`` devis envoyés, dont ``acceptes`` acceptés et ``sans_reponse`` constatés sans réponse ; ``chantiers``
    terminés (les premiers devis acceptés), de durée estimée 100 minutes et réelle 100 + ``ecart_duree_pct`` ;
    ``signaux_materiaux`` d'entre eux avec un signal critique de M6. ``cash_libre_cad=None`` : M5 a constaté « non
    calculable ». ``delai_acceptation_jours`` avance l'arrivée des leads de ce nombre de jours (le délai du lead à
    l'acceptation). Les contenus exportés par M7 sont rapportés par les leads de M1 (clé ``utm_content``)."""
    if not (0 <= qualifies <= leads and 0 <= envoyes <= leads and 0 <= acceptes <= envoyes):
        raise ValueError("comptes incohérents : qualifies ≤ leads, envoyes ≤ leads, acceptes ≤ envoyes")
    if not 0 <= sans_reponse <= envoyes - acceptes or not 0 <= chantiers <= acceptes:
        raise ValueError("comptes incohérents : sans_reponse ≤ envoyes − acceptes, chantiers ≤ acceptes")
    if not 0 <= signaux_materiaux <= chantiers:
        raise ValueError("comptes incohérents : signaux_materiaux ≤ chantiers")
    faits_entonnoir: list[dict[str, Any]] = []
    arrivee = (date.fromisoformat(jour) - timedelta(days=delai_acceptation_jours)).isoformat()
    for rang in range(1, leads + 1):
        faits_entonnoir.append(
            entonnoir.fait_lead_recu(
                {
                    "lead_id": _id("lead", rang),
                    "client_id": "a" * 64,
                    "horodatage_association": _instant(arrivee, 8, rang % 60),
                }
            )
        )
    for rang in range(1, qualifies + 1):
        faits_entonnoir.append(
            entonnoir.fait_lead_qualifie(
                {
                    "lead_id": _id("lead", rang),
                    "horodatage_assignation": _instant(jour, 9, rang % 60),
                }
            )
        )
    for rang in range(1, envoyes + 1):
        faits_entonnoir.append(
            entonnoir.fait_devis_envoye(
                {
                    "devis_id": _id("devis", rang),
                    "lead_id": _id("lead", rang),
                    "horodatage_envoi": _instant(jour, 10, rang % 60),
                }
            )
        )
    for rang in range(1, acceptes + 1):
        faits_entonnoir.append(
            entonnoir.fait_devis_accepte(
                {
                    "devis_id": _id("devis", rang),
                    "lead_id": _id("lead", rang),
                    "prix_total": prix_devis,
                    "horodatage_acceptation": _instant(jour, 11, rang % 60),
                }
            )
        )
    for rang in range(acceptes + 1, acceptes + sans_reponse + 1):
        faits_entonnoir.append(
            entonnoir.fait_devis_sans_reponse(
                {
                    "devis_id": _id("devis", rang),
                    "lead_id": _id("lead", rang),
                    "statut": "envoye",
                    "horodatage_devis": _instant(jour, 10, rang % 60),
                    "horodatage_reference": _instant(jour, 12, 0),
                    "delai_relance_jours": 7,
                }
            )
        )

    faits_chantier: list[dict[str, Any]] = []
    for rang in range(1, chantiers + 1):
        wct_id = _id("wct", rang)
        faits_chantier.append(
            mesures_chantier.fait_devis(
                {
                    "devis_id": _id("devis", rang),
                    "prix_total": prix_devis,
                    "cout_total": "9000.00",
                    "horodatage_acceptation": _instant(jour, 11, rang % 60),
                    "duree_estimee_minutes": _DUREE_ESTIMEE_MINUTES,
                }
            )
        )
        faits_chantier.append(
            mesures_chantier.fait_wct(
                {
                    "wct_id": wct_id,
                    "intervention_id": _id("int", rang),
                    "devis_id": _id("devis", rang),
                    "technicien_id": "tech-fictif",
                    "horodatage_completion": _instant(jour, 13, rang % 60),
                    "duree_reelle_minutes": _DUREE_ESTIMEE_MINUTES + ecart_duree_pct,
                    "statut": "completed_verified",
                }
            )
        )
        if avec_variance:
            critique = rang <= signaux_materiaux
            faits_chantier.append(
                mesures_chantier.fait_variance(
                    {
                        "wct_id": wct_id,
                        "statut_variance": "evaluee",
                        "signal_critique": critique,
                        "seuil_pourcentage": 0.3,
                        "lignes": [
                            {
                                "materiau": "materiau-fictif",
                                "unite": "pi",
                                "quantite_prevue": "40",
                                "quantite_reelle": "56" if critique else "41",
                                "ecart_pourcentage": "0.4" if critique else "0.025",
                                "critique": critique,
                            }
                        ],
                    }
                )
            )
        faits_chantier.append(
            mesures_chantier.fait_rentabilite(
                {
                    "wct_id": wct_id,
                    "devis_id": _id("devis", rang),
                    "sequence": 1,
                    "verdict": "CALCULEE",
                    "marge_reelle_cad": "3000.00",
                    "cout_reel_complet": True,
                    "manque": [],
                }
            )
        )

    faits_cash: list[dict[str, Any]] = []
    if cash_libre_cad is not None:
        faits_cash.append(
            cash_libre.fait_constat(
                {
                    "evenement_id": f"m5-cash-libre-1-{jour}-fictif",
                    "sequence": 1,
                    "date_reference": jour,
                    "devise": "CAD",
                    "statut": "CALCULE",
                    "cash_libre_cad": cash_libre_cad,
                    "au_plus_cad": None,
                    "en_deficit": False,
                    "manque": [],
                    "reserves": [],
                }
            )
        )
    else:
        faits_cash.append(
            cash_libre.fait_constat(
                {
                    "evenement_id": f"m5-cash-libre-1-{jour}-fictif",
                    "sequence": 1,
                    "date_reference": jour,
                    "devise": "CAD",
                    "statut": "NON_CALCULABLE",
                    "cash_libre_cad": None,
                    "au_plus_cad": None,
                    "en_deficit": None,
                    "manque": [{"composante": "solde", "code": "REJ-CASH-SOLDE-ABSENT"}],
                    "reserves": [],
                }
            )
        )

    faits_contenus: list[dict[str, Any]] = []
    for rang in range(1, contenus_exportes + 1):
        faits_contenus.append(
            contenus.fait_contenu_exporte(
                {
                    "contenu_id": _id("contenu", rang),
                    "wct_id": _id("wct", rang),
                    "canal": "facebook",
                    "utm_content": f"utm-fictif-{rang:03d}",
                    "lien_de_suivi": True,
                    "exporte_le": _instant(jour, 7, rang % 60),
                }
            )
        )
    for rang in range(1, min(leads, contenus_exportes * 2) + 1):
        cle = f"utm-fictif-{(rang - 1) % contenus_exportes + 1:03d}" if contenus_exportes else None
        faits_contenus.append(
            contenus.fait_lead_m1(
                {
                    "lead": {"lead_id": _id("lead", rang), "utm": {"utm_content": cle} if cle else None},
                    "horodatage": _instant(jour, 8, rang % 60),
                }
            )
        )
    return {
        "chantier": faits_chantier,
        "entonnoir": faits_entonnoir,
        "contenus": faits_contenus,
        "cash_libre": faits_cash,
    }


# Bornes de démonstration FICTIVES du score de santé (pire = 0 point, cible = 100 points), pour la calibration
# seulement :
# AUCUNE n'est une recommandation ni une valeur de la configuration du propriétaire (qui les déclare, et que M8
# n'invente
# jamais).
BORNES_SANTE_FICTIVES: dict[str, dict[str, str]] = {
    "m8_cash_libre_cad": {"pire": "0", "cible": "50000"},
    "m8_taux_acceptation_pct": {"pire": "20", "cible": "60"},
    "m8_devis_sans_reponse": {"pire": "10", "cible": "0"},
    "m8_ecart_duree_equipe_pct": {"pire": "40", "cible": "0"},
    "m8_chantiers_signal_materiaux": {"pire": "5", "cible": "0"},
    "m8_delai_lead_acceptation_jours": {"pire": "30", "cible": "3"},
}

# Quatre entreprises fictives dont l'état est CONNU d'avance : la calibration vérifie que le score les ordonne comme on
# l'attend (saine > correcte > fragile) et que l'entreprise sans constat de cash est « indéterminée », pas notée.
SCENARIOS_SANTE_FICTIFS: dict[str, dict[str, Any]] = {
    "saine": {
        "leads": 30,
        "qualifies": 28,
        "envoyes": 20,
        "acceptes": 14,
        "sans_reponse": 1,
        "chantiers": 8,
        "ecart_duree_pct": 2,
        "signaux_materiaux": 0,
        "cash_libre_cad": "80000.00",
        "delai_acceptation_jours": 5,
    },
    "correcte": {
        "leads": 30,
        "qualifies": 22,
        "envoyes": 20,
        "acceptes": 10,
        "sans_reponse": 3,
        "chantiers": 6,
        "ecart_duree_pct": 12,
        "signaux_materiaux": 1,
        "cash_libre_cad": "30000.00",
        "delai_acceptation_jours": 12,
    },
    "fragile": {
        "leads": 30,
        "qualifies": 10,
        "envoyes": 20,
        "acceptes": 4,
        "sans_reponse": 9,
        "chantiers": 4,
        "ecart_duree_pct": 35,
        "signaux_materiaux": 3,
        "cash_libre_cad": "1500.00",
        "delai_acceptation_jours": 28,
    },
    "sans_constat_de_cash": {
        "leads": 30,
        "qualifies": 28,
        "envoyes": 20,
        "acceptes": 14,
        "sans_reponse": 1,
        "chantiers": 8,
        "ecart_duree_pct": 2,
        "signaux_materiaux": 0,
        "cash_libre_cad": None,
        "delai_acceptation_jours": 5,
    },
}


__all__ = ["BORNES_SANTE_FICTIVES", "FICTIF", "SCENARIOS_SANTE_FICTIFS", "registres_fictifs"]
