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
from decimal import Decimal
from typing import Any

from . import cash_libre, contenus, entonnoir, mesures_chantier, operations_recues

FICTIF = True

_FUSEAU = "-04:00"
_DUREE_ESTIMEE_MINUTES = 100
# D6 : la source UTM de certains leads (un quart de Google, un quart de Facebook ; les autres n'en ont pas).
_SOURCE_UTM_FICTIVE = {1: "google", 2: "facebook"}
CANAUX_FICTIFS = {"google_ads": ["google", "google-ads"], "meta": ["facebook", "instagram"]}


def _instant(jour: str, heure: int, minute: int = 0) -> str:
    return f"{jour}T{heure:02d}:{minute:02d}:00{_FUSEAU}"


def _composante_fictive(identifiant: str, montant: str) -> dict[str, Any]:
    return {"id": identifiant, "statut": "CALCULE", "montant_cad": montant, "plancher_cad": None}


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
    avec_operations: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Les registres (``chantier``, ``entonnoir``, ``contenus``, ``cash_libre``, ``operations`` et, avec
    ``avec_operations``, les
    ``declarations`` du propriétaire) d'une entreprise
    fictive (``operations`` est vide ici : voir ``operations_fictives`` pour les constats de M5, M6 et M7).

    Les comptes sont des paramètres, jamais calculés au hasard : ``leads`` reçus, dont ``qualifies`` qualifiés ;
    ``envoyes`` devis envoyés, dont ``acceptes`` acceptés et ``sans_reponse`` constatés sans réponse ; ``chantiers``
    terminés (les premiers devis acceptés), de durée estimée 100 minutes et réelle 100 + ``ecart_duree_pct`` ;
    ``signaux_materiaux`` d'entre eux avec un signal critique de M6. ``cash_libre_cad=None`` : M5 a constaté « non
    calculable ». ``delai_acceptation_jours`` avance l'arrivée des leads de ce nombre de jours (le délai du lead à
    l'acceptation). Les contenus exportés par M7 sont rapportés par les leads de M1 (clé ``utm_content``).

    ``avec_operations`` : ajoute les constats de M5, M6 et M7 du registre ``operations`` (``operations_fictives``) et
    rend les traces de rentabilité de M5 définitives (prix facturé définitif, coût réel complet), pour que les mesures
    interdépartements aient de quoi se calculer. Par défaut rien n'est ajouté : les mesures qui en dépendent sont
    alors non
    calculables, comme dans une instance où ces départements n'ont encore rien publié."""
    if not (0 <= qualifies <= leads and 0 <= envoyes <= leads and 0 <= acceptes <= envoyes):
        raise ValueError("comptes incohérents : qualifies ≤ leads, envoyes ≤ leads, acceptes ≤ envoyes")
    if not 0 <= sans_reponse <= envoyes - acceptes or not 0 <= chantiers <= acceptes:
        raise ValueError("comptes incohérents : sans_reponse ≤ envoyes − acceptes, chantiers ≤ acceptes")
    if not 0 <= signaux_materiaux <= chantiers:
        raise ValueError("comptes incohérents : signaux_materiaux ≤ chantiers")
    faits_entonnoir: list[dict[str, Any]] = []
    arrivee = (date.fromisoformat(jour) - timedelta(days=delai_acceptation_jours)).isoformat()
    for rang in range(1, leads + 1):
        charge_lead: dict[str, Any] = {
            "lead_id": _id("lead", rang),
            "client_id": "a" * 64,
            "horodatage_association": _instant(arrivee, 8, rang % 60),
        }
        if avec_operations and rang % 4 in _SOURCE_UTM_FICTIVE:
            charge_lead["utm"] = {"utm_source": _SOURCE_UTM_FICTIVE[rang % 4]}
        faits_entonnoir.append(entonnoir.fait_lead_recu(charge_lead))
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
                    **({"prix_definitif": True} if avec_operations else {}),
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
                    **(
                        {
                            "solde": _composante_fictive("solde", "37654.33"),
                            "composantes": [
                                _composante_fictive("taxes_a_remettre", "1981.69"),
                                _composante_fictive("comptes_a_payer", "459.91"),
                            ],
                        }
                        if avec_operations
                        else {}
                    ),
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
        "operations": operations_fictives(jour) if avec_operations else [],
        "declarations": declarations_fictives() if avec_operations else [],
    }


def declarations_fictives() -> list[dict[str, Any]]:
    """La correspondance canaux -> sources UTM que le propriétaire FICTIF a déclarée (D6)."""
    return [{"type_entree": "canaux_marketing", "canaux": {c: list(s) for c, s in CANAUX_FICTIFS.items()}}]


def operations_fictives(jour: str = "2026-10-30") -> list[dict[str, Any]]:
    """Les constats FICTIFS de M5, M6 et M7 du registre ``operations``, construits par le VRAI constructeur
    (``operations_recues.fait``) : trois jours de relevés de dépense Google Ads et un de Meta (hors taxes, sans trou),
    les signaux de M7 qui disent la fraîcheur de leurs sources, deux conversions hors ligne, trois anomalies (dont une
    critique), un constat comptable de M5 (créances de 7 210,55 $ dont rien à 90 jours et plus), trois réceptions de M6
    (dont une avec écart) et deux commandes envoyées par le canal de M1. Phase 2 : le constat de la dépense
    comptabilisée
    de M5 (300,00 $ pour 413,75 $ de relevés : l'écart de 113,75 $ est celui de deux brouillons en attente), trois
    factures émises (deux comptent, une est annulée), les valeurs de signaux de trois sources propres de M7, la capacité
    d'une semaine de M4 (80 h déclarées, 62 h planifiées), le pipeline de M2, la disponibilité du matériel de M6 et les
    plaintes de M1."""
    veille = (date.fromisoformat(jour) - timedelta(days=1)).isoformat()
    avant_veille = (date.fromisoformat(jour) - timedelta(days=2)).isoformat()
    lu = _instant(jour, 6)

    def depense(identifiant: str, canal: str, debut: str, montant: str) -> dict[str, Any]:
        return operations_recues.fait(
            operations_recues.TYPE_DEPENSE,
            {
                "releve_id": identifiant, "revision": 1, "canal": canal, "periode_debut": debut, "periode_fin": debut,
                "montant_cad": montant, "devise": "CAD", "base_taxes": "HORS_TAXES", "source": "RELEVE_PLATEFORME",
                "releve_le": lu,
            },
        )

    def signal(source: str, heures: int) -> dict[str, Any]:
        return operations_recues.fait(
            operations_recues.TYPE_SIGNAUX,
            {
                "source": source, "compte_ref": "compte-fictif-1", "flux": "depenses", "mode": "api_lecture",
                "periode_debut": avant_veille, "periode_fin": veille, "faits_nouveaux": 1, "faits_revises": 0,
                "faits_inchanges": 0, "derniere_lecture_reussie_le": lu, "donnees_jusqu_au": veille,
                "fraicheur_fenetre_h": heures, "fictif": False,
            },
        )

    def conversion(rang: int, type_: str) -> dict[str, Any]:
        return operations_recues.fait(
            operations_recues.TYPE_CONVERSION,
            {
                "conversion_id": _id("conv", rang), "lead_id": _id("lead", rang), "type": type_, "convertie_le": veille,
                "utm_source": "google", "utm_medium": "cpc", "utm_campaign": None, "valeur_cad": "4500.00",
                "source_normalisee": True, "importee_le": _instant(jour, 7, rang),
            },
        )

    def anomalie(rang: int, severite: str) -> dict[str, Any]:
        return operations_recues.fait(
            operations_recues.TYPE_ANOMALIE,
            {
                "anomalie_id": f"{rang:032x}", "canal": "google_ads", "campagne_ref": None, "regle": "DEP-01",
                "severite": severite, "valeur": "310.50", "seuil": "200.00", "unite": "CAD", "jour_debut": veille,
                "jour_fin": veille, "detectee_le": _instant(jour, 7, rang), "fictif": False,
            },
        )

    def reception(rang: int, verdict: str) -> dict[str, Any]:
        return operations_recues.fait(
            operations_recues.TYPE_RECEPTION,
            {
                "evenement_id": f"m6-reception-fictive-{rang}", "po_id": _id("po", rang),
                "horodatage_reception": _instant(jour, 9, rang), "verdict_reception": verdict, "statut_po": "received",
                "hash_maillon": f"{rang:064x}",
            },
        )

    def commande(rang: int) -> dict[str, Any]:
        return operations_recues.fait(
            operations_recues.TYPE_COMMANDE,
            {
                "po_id": _id("po", rang), "brouillon_id": _id("brouillon", rang), "empreinte": "e" * 64,
                "envoye_le": _instant(jour, 10, rang),
            },
        )

    def ordonne(type_entree: str, charge: dict[str, Any], heure: int) -> dict[str, Any]:
        return operations_recues.fait(type_entree, charge, _instant(jour, heure))

    def tresorerie_prevue(jour_constat: str, heure: int, soldes: list[str], sequence: int = 1) -> dict[str, Any]:
        horizon = len(soldes)
        montants = [Decimal(montant) for montant in soldes]
        minimal = min(montants)
        version = f"{sequence:064x}"
        serie = [
            {"semaine": rang, "statut": "CALCULE", "solde_fin_cad": montant}
            for rang, montant in enumerate(soldes, start=1)
        ]
        return ordonne(
            operations_recues.TYPE_TRESORERIE_PREVUE,
            {
                "evenement_id": f"m5-tresorerie-prevue-{sequence}-{jour_constat}-{version[:16]}",
                "sequence": sequence, "date_reference": jour_constat, "emise_le": _instant(jour_constat, heure),
                "version_donnees": version, "devise": "CAD", "prevision_id": version,
                "horizon_semaines": horizon, "statut_alerte": "SEUIL_A_CONFIGURER", "seuil_cad": None,
                "semaines_sous_seuil": [],
                "solde_minimal_prevu_cad": format(minimal, "f"),
                "semaine_solde_minimal": montants.index(minimal) + 1,
                "non_calculable_a_partir_de": None, "manque": [],
                "soldes_hebdo": serie, "mention": "Analyse préparatoire IA — validation Nathan/CPA/fiscaliste "
                "requise avant toute décision officielle ou action réelle.",
            },
            heure,
        )

    lundi = (date.fromisoformat(jour) - timedelta(days=date.fromisoformat(jour).weekday())).isoformat()
    il_y_a_six_jours = (date.fromisoformat(jour) - timedelta(days=6)).isoformat()

    def facture(identifiant: str, statut: str, avant: str, taxes: str, apres: str, heure: int) -> dict[str, Any]:
        return ordonne(
            operations_recues.TYPE_FACTURE_EMISE,
            {
                "evenement_id": f"m5-facture-emise-{identifiant}-{statut}", "facture_id": identifiant, "statut": statut,
                "emise_le": veille, "devise": "CAD", "montant_avant_taxes_cad": avant, "total_taxes_cad": taxes,
                "montant_apres_taxes_cad": apres,
            },
            heure,
        )

    def performance(
        source: str, clics: str | None, impressions: str | None, visites: str | None, couverts: int
    ) -> dict[str, Any]:
        return ordonne(
            operations_recues.TYPE_PERFORMANCE,
            {
                "evenement_id": f"m7-perf-{source}-fictif", "source": source, "compte_ref": "site-fictif",
                "periode_debut": il_y_a_six_jours, "periode_fin": jour, "jours_periode": 7, "jours_couverts": couverts,
                "clics": clics, "impressions": impressions, "visites": visites, "derniere_observation_le": lu,
                "fraicheur_fenetre_h": 24 if source == "umami" else 48, "fictif": False,
                "version_donnees": f"{source[:4].encode().hex():0<16}",
            },
            8,
        )

    return [
        depense("releve-g1", "google_ads", avant_veille, "120.00"),
        depense("releve-g2", "google_ads", veille, "135.50"),
        depense("releve-g3", "google_ads", jour, "98.25"),
        depense("releve-m1", "meta", veille, "60.00"),
        signal("google_ads", 48),
        signal("meta_ads", 72),
        conversion(1, "rendez_vous"),
        conversion(2, "vente"),
        anomalie(1, "critique"),
        anomalie(2, "attention"),
        anomalie(3, "info"),
        operations_recues.fait(
            operations_recues.TYPE_MESURES_COMPTABLES,
            {
                "date_reference": jour, "version_donnees": "0123456789abcdef",
                "creances": {
                    "nombre": 3, "total": "7210.55",
                    "par_tranche": {"0-30": "4000.00", "31-60": "2210.55", "61-90": "1000.00", "90+": "0.00"},
                },
                "relances_en_brouillon": 2, "brouillons_en_attente": 4, "ecritures_definitives": 12,
                "derniere_periode_close": "2026-09", "paiements_prepares": {"nombre": 1, "total": "459.91"},
                "rapprochements": {"prepares": 2, "confirmes": 1, "a_ecart": 0},
                "notes_de_credit": {"nombre": 0, "total": "0.00"}, "depenses_employes": {"nombre": 1, "total": "32.10"},
                "pieces_liees": 5,
            },
        ),
        reception(1, "CONFORME"),
        reception(2, "CONFORME"),
        reception(3, "RECEPTION_INFERIEURE"),
        commande(1),
        commande(2),
        ordonne(
            operations_recues.TYPE_DEPENSE_COMPTABILISEE,
            {
                "evenement_id": f"m5-depense-pub-1-{avant_veille}-{jour}-fictif", "sequence": 1, "date_reference": jour,
                "periode_debut": avant_veille, "periode_fin": jour, "version_donnees": "fedcba9876543210",
                "devise": "CAD",
                "base_taxes": "HORS_TAXES", "comptabilise_cad": "300.00", "ecritures_definitives": 3,
                "brouillons_en_attente": 2, "brouillons_en_attente_cad": "113.75",
            },
            7,
        ),
        facture("facture-fictive-1", "ENVOYEE", "10000.00", "1497.50", "11497.50", 9),
        facture("facture-fictive-1", "PAYEE", "10000.00", "1497.50", "11497.50", 11),
        facture("facture-fictive-2", "ENVOYEE", "2500.00", "374.38", "2874.38", 9),
        facture("facture-fictive-3", "ENVOYEE", "800.00", "119.84", "919.84", 9),
        facture("facture-fictive-3", "ANNULEE", "800.00", "119.84", "919.84", 12),
        performance("search_console", "120", "4300", None, 7),
        performance("bing_webmaster", "15", "600", None, 7),
        performance("umami", None, None, "410", 6),
        ordonne(
            operations_recues.TYPE_CAPACITE,
            {
                "evenement_id": f"m4-capacite-{lundi}-fictif", "semaine_debut": lundi,
                "portee": "journees_datees_seulement", "calculable": True, "heures_disponibles": "80",
                "heures_planifiees": "62", "manque": [], "constate_le": _instant(jour, 7),
                "version_donnees": "a1b2c3d4e5f60718",
            },
            7,
        ),
        ordonne(
            operations_recues.TYPE_PIPELINE,
            {
                "evenement_id": f"m2-pipeline-{jour}-fictif", "date_reference": jour, "constate_le": _instant(jour, 7),
                "version_donnees": "0f1e2d3c4b5a6978", "total": 40, "ouverts": 12,
                "par_statut": {"nouveau": 4, "qualifie": 8, "converti": 9, "perdu": 15, "annule": 4},
                "convertis_un_jour": 9, "perdus": 15, "resolus": 24, "taux_conversion_resolus_pct": "37.50",
                "valeur_ponderee_cad": "41250.00",
            },
            7,
        ),
        ordonne(
            operations_recues.TYPE_DISPONIBILITE,
            {
                "evenement_id": f"m6-disponibilite-{jour}-fictif", "date_reference": jour,
                "constate_le": _instant(jour, 7),
                "version_donnees": "1122334455667788", "articles_suivis": 42, "articles_en_rupture": 3,
                "articles_sur_reserves": 1, "reservations_actives": 5, "reservations_incompletes": 2,
            },
            7,
        ),
        ordonne(
            operations_recues.TYPE_FILET,
            {
                "evenement_id": f"m2-filet-{jour}-fictif", "date_reference": jour, "constate_le": _instant(jour, 7),
                "version_donnees": "99aabbccddeeff00", "leads_examines": 40,
                "violations_par_regle": {
                    "prochaine_action_obligatoire": 1, "lead_chaud_non_contacte": 2, "photos_non_recues": None,
                    "soumission_non_relancee": 0, "plainte_non_escaladee": 0, "lead_sans_proprietaire": 1,
                    "tache_en_retard": 3},
                "violations_total": 7, "regles_non_evaluees": ["photos_non_recues"], "regles_partielles": [],
                "anomalies_par_controle": {
                    "lead_sans_statut": 0, "client_sans_contact": 1, "tache_sans_proprietaire": 0,
                    "soumission_orpheline": 0, "activite_sans_lead": 0, "lead_sans_client": 0,
                    "pipeline_incoherent": 1, "doublon_probable": 0},
                "anomalies_total": 2, "controles_non_evalues": [],
            },
            7,
        ),
        ordonne(
            operations_recues.TYPE_PREAUDIT,
            {
                "evenement_id": f"m5-preaudit-{jour}-fictif", "date_reference": jour, "constate_le": _instant(jour, 7),
                "version_donnees": "5566778899aabbcc",
                "constats_par_regle": {
                    "FACTURE_SANS_PAIEMENT": 1, "PAIEMENT_SANS_FACTURE": 0, "DEPENSE_SANS_RECU": 2,
                    "TAXE_INCOHERENTE": 0, "DOUBLON_PROBABLE": 1, "TRANSACTION_HORS_NORME": None, "FACTURE_MODIFIEE": 0,
                    "CHANGEMENT_COMPTE_INHABITUEL": None, "PISTE_AUDIT_INCOMPLETE": 0, "DOCUMENT_MANQUANT": 0},
                "constats_total": 4, "constats_par_gravite": {"haute": 1, "moyenne": 3, "faible": 0},
                "regles_non_evaluees": ["TRANSACTION_HORS_NORME", "CHANGEMENT_COMPTE_INHABITUEL"],
                "regles_partielles": [],
            },
            7,
        ),
        ordonne(
            operations_recues.TYPE_PLAINTES,
            {
                "evenement_id": f"m1-plaintes-{jour}-30-fictif", "date_reference": jour, "jours": 30, "etat": "CONNUE",
                "nombre": 2, "empreinte_contenu": "ab" * 32,
            },
            7,
        ),
        tresorerie_prevue(jour, 7, ["19885.02", "15685.02", "22885.02", "100000.00"], sequence=2),
        tresorerie_prevue(il_y_a_six_jours, 7, ["36000.00", "18000.00", "22000.00", "25000.00"], sequence=1),
    ]


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


__all__ = [
    "BORNES_SANTE_FICTIVES",
    "CANAUX_FICTIFS",
    "FICTIF",
    "SCENARIOS_SANTE_FICTIFS",
    "declarations_fictives",
    "operations_fictives",
    "registres_fictifs",
]
