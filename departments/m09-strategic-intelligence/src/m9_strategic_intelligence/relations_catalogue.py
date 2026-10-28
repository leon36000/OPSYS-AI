"""Catalogue versionné des relations du graphe d'impacts M9.2 : quelles lignes de quelles lectures relient quels objets.

Module pur. Chaque règle relie deux champs de LA MÊME ligne d'une réponse réelle de producteur (constatée par
``tests/test_m9_graphe_reel.py`` sur des captures produites par les vrais outils M2–M8). ``LIMITES`` dit, règle par
règle, ce que le champ ne permet pas. Rien n'est inféré : aucune ligne ne porte à la fois un matériau et un devis, un
chantier ou un lead, donc le matériau n'est PAS un nœud du graphe (manque nommé, voir ``MANQUES``). Une relation sans
preuve de lecture n'a pas sa place ici.
"""

from __future__ import annotations

from .graphe_impacts import Regle

CATALOGUE_RELATIONS_VERSION = "2026-10-28.1"
_R = "resultat.resultat"  # la réponse du dispatcher est {"ok": true, "resultat": <réponse de l'outil>}

REGLES: tuple[Regle, ...] = (
    Regle("m6_reservation_devis_chantier", "reserve_pour", "m6.disponibilite", f"{_R}.reservations_actives[*]",
          "devis", "devis_id", "chantier", "chantier_id"),
    # M4, liste v1 (sans pagination : la racine de la réponse est la liste) puis page {interventions, page}.
    Regle("m4_devis_intervention", "execute_par", "m4.interventions", "resultat[*]",
          "devis", "devis_id", "intervention", "intervention_id"),
    Regle("m4_intervention_lead", "concerne", "m4.interventions", "resultat[*]",
          "intervention", "intervention_id", "lead", "lead_id"),
    Regle("m4_page_devis_intervention", "execute_par", "m4.interventions", "resultat.interventions[*]",
          "devis", "devis_id", "intervention", "intervention_id"),
    Regle("m4_page_intervention_lead", "concerne", "m4.interventions", "resultat.interventions[*]",
          "intervention", "intervention_id", "lead", "lead_id"),
    Regle("m4_cedule_intervention_lead", "concerne", "m4.cedule_semaine", f"{_R}.interventions[*]",
          "intervention", "intervention_id", "lead", "lead_id"),
    Regle("m4_cedule_intervention_equipe", "cedule_a", "m4.cedule_semaine", f"{_R}.interventions[*]",
          "intervention", "intervention_id", "equipe", "equipe_id"),
    Regle("m3_devis_wct", "mesure_sur", "m3.ecarts", f"{_R}[*]", "devis", "devis_id", "wct", "wct_id"),
    Regle("m3_intervention_wct", "complete_par", "m3.ecarts", f"{_R}[*]",
          "intervention", "intervention_id", "wct", "wct_id"),
    Regle("m8_devis_wct", "mesure_sur", "m8.mesures_chantier", "resultat", "devis", "devis_id", "wct", "wct_id"),
    Regle("m5_devis_chantier", "facture_pour", "m5.rentabilite_chantier", f"{_R}.chantiers[*]",
          "devis", "devis_id", "chantier", "chantier_id"),
    Regle("m5_chantier_rentabilite", "rentabilite_de", "m5.rentabilite_chantier", f"{_R}.chantiers[*]",
          "chantier", "chantier_id", "rentabilite", "chantier_id"),
    Regle("m5_chantier_po", "achete_par", "m5.comptes_a_payer", f"{_R}.comptes[*]",
          "chantier", "chantier_id", "po", "po_id"),
    Regle("m2_lead_proprietaire", "suivi_par", "m2.leads", f"{_R}.leads[*]",
          "lead", "lead_id", "personne", "proprietaire"),
)  # fmt: skip

LIMITES: dict[str, str] = {
    "m6_reservation_devis_chantier": "reservations_actives[*].devis_id/chantier_id ; ne nomme pas le matériau (il est "
    "dans lignes_manquantes[*], sans devis) ; seulement les réservations ACTIVES, 15 articles par lecture.",
    "m4_devis_intervention": "m4_lister_interventions, liste v1 : devis_id nul tant que l'intervention n'est pas née "
    "d'un devis accepté (planifiée à la main).",
    "m4_intervention_lead": "lead_id de la liste M4 v1 ; M4 n'expose ni client ni coordonnées ici.",
    "m4_page_devis_intervention": "même champ que la liste v1, lu dans la page {interventions, page} (taille_page).",
    "m4_page_intervention_lead": "même champ que la liste v1, lu dans la page {interventions, page} (taille_page).",
    "m4_cedule_intervention_lead": "lead_id du créneau daté ; 200 créneaux et 50 non datés au plus (`tronque`).",
    "m4_cedule_intervention_equipe": "equipe_id du créneau ; l'équipe n'est pas une personne, aucun technicien nommé.",
    "m3_devis_wct": "devis_id/wct_id d'une ligne d'écart ; n'existe qu'une fois le chantier terminé (WCT publié).",
    "m3_intervention_wct": "intervention_id/wct_id d'une ligne d'écart ; M3 ne porte aucun lead_id ici.",
    "m8_devis_wct": "devis_id/wct_id de m8_lire_mesures_chantier ; une capture par WCT (argument wct_id).",
    "m5_devis_chantier": "chantier_id/devis_id de la rentabilité ; `limite` tronque (reste) ; ni lead ni WCT chez M5.",
    "m5_chantier_rentabilite": "le chantier est la clé de la rentabilité (même champ des deux côtés).",
    "m5_chantier_po": "comptes[*].chantier_id/po_id ; vient de la réception du PO, pas du devis ; pas de matériau.",
    "m2_lead_proprietaire": "leads[*].proprietaire ; M2 n'expose pas le devis (statut seulement) ; pagine (decalage).",
}

MANQUES: tuple[str, ...] = (
    "materiau : aucune ligne d'aucune lecture ne porte un matériau avec un devis, un chantier ou un lead",
    "lead -> devis : M2 n'expose pas le devis ; seul M4 relie lead et intervention",
    "wct -> lead : aucune lecture ne les relie directement (le chemin passe par l'intervention)",
)

if {regle.id for regle in REGLES} != set(LIMITES):  # pragma: no cover - garde de construction
    raise ValueError("chaque règle du catalogue doit dire sa limite")
