/**
 * `checklist.tsx` (R12 §5 étape 4, PLAN T1.4-e). AUCUN catalogue d'items de checklist n'existe
 * côté serveur : `preuves.py`/`outils.py` n'attendent qu'un BOOLÉEN (`checklist_complete`,
 * `CLES_PREUVES_COMPLETION`) — le contenu détaillé (quelles étapes, dans quel ordre) n'est
 * modélisé NULLE PART dans le produit (`DEFINITION-PRODUIT.md` ne liste aucune liste d'étapes
 * par service). Inventer une liste fixe d'étapes de pose (gouttières, revêtement…) serait de la
 * donnée métier inventée (interdit, AGENTS.md) : cet écran laisse donc l'EMPLOYÉ composer sa
 * propre liste pour le chantier (ajouter/cocher/retirer un item texte libre), persistée
 * localement par chantier — `checklist_complete` n'est vrai QUE si la liste n'est pas vide ET que
 * tous les items sont cochés (fail-closed, même esprit que `photos_apres` non vide côté serveur :
 * une checklist VIDE n'est jamais « terminée »). Voir MOBILE.md pour la décision documentée.
 */
export interface ItemChecklist {
  readonly id: string;
  readonly texte: string;
  readonly fait: boolean;
}
