import type { InterventionM4, StatutInterventionM4 } from "../m4/interventions";

/**
 * « Chantiers du jour » (`today.tsx`, M4.7, R12 §5 étape 3) : sélection des interventions à
 * montrer à l'employé — LIMITE ASSUMÉE ET DOCUMENTÉE (voir aussi MOBILE.md).
 *
 * `m4_lister_interventions` (lu dans `outils.py`, `etats.lister_interventions`) ne renvoie NI
 * date/fenêtre de cédule NI `technicien_id` assigné par intervention — seulement
 * `{intervention_id, statut, lead_id, type_travaux, devis_id}` (aucune donnée de contact non
 * plus, structurellement). Il est donc IMPOSSIBLE de filtrer par « aujourd'hui » (aucune date) ni
 * par « mes chantiers » (aucun technicien) sans INVENTER un champ que le serveur ne fournit pas —
 * interdit par AGENTS.md. `filtrerChantiersActifs` ci-dessous retient donc les interventions dont
 * le statut représente un travail EN COURS OU À DÉMARRER (`ETATS_ACTIFS_AUJOURDHUI`), un proxy
 * assumé pour « aujourd'hui » en l'absence de cédule exposée au mobile — pas une date réelle.
 * `reportee` (reportée) en est délibérément exclue : elle est sortie du flux du jour tant qu'un
 * nouveau `planifiee` (légal, `etats.py` `reportee -> planifiee`) ne l'y remet pas — l'y laisser
 * afficherait une information périmée comme si elle était actionnable aujourd'hui.
 */
export const ETATS_ACTIFS_AUJOURDHUI: readonly StatutInterventionM4[] = [
  "en_route",
  "sur_site",
  "en_revue",
  "planifiee",
];

/** Ordre d'affichage : le plus urgent/actionnable en premier (un technicien déjà en route ou sur
 * place avant un chantier pas encore commencé), puis par `intervention_id` pour un résultat
 * stable et déterministe (même discipline que `etats.lister_interventions` côté serveur). Choix
 * de présentation, pas une donnée métier. */
const PRIORITE_AFFICHAGE: Readonly<Record<StatutInterventionM4, number>> = {
  en_route: 0,
  sur_site: 1,
  en_revue: 2,
  planifiee: 3,
  reportee: 4,
  completed_pending_review: 5,
  completed_verified: 6,
  annulee: 7,
};

export function filtrerChantiersActifs(interventions: readonly InterventionM4[]): InterventionM4[] {
  return interventions
    .filter((intervention) => ETATS_ACTIFS_AUJOURDHUI.includes(intervention.statut))
    .slice()
    .sort((a, b) => {
      const diff = PRIORITE_AFFICHAGE[a.statut] - PRIORITE_AFFICHAGE[b.statut];
      if (diff !== 0) {
        return diff;
      }
      return a.intervention_id < b.intervention_id ? -1 : a.intervention_id > b.intervention_id ? 1 : 0;
    });
}
