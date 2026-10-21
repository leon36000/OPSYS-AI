---
name: plan-de-contenu-saisonnier
description: Procédure pour composer un plan de contenu à partir du calendrier saisonnier québécois (fenêtres marketing actives) et le déposer en brouillon dans la file d'approbation.
---

# Planifier le contenu saisonnier

1. Détermine la date de référence réelle (jamais une date supposée) et appelle
   `m7_planifier_campagne_saisonniere` avec cette date.
2. Si `fenetres_actives` est vide : rapporte-le tel quel (« aucune fenêtre marketing active
   pour cette période »). N'invente jamais une campagne hors saison.
3. Chaque entrée de `items_proposes` porte un `content_item` avec `approval_status: "PROPOSE"`
   — c'est un brouillon, jamais un contenu publié. Présente au propriétaire : le thème, la
   fenêtre marketing (`fenetre_id`), le titre et le corps composés.
4. Pour un besoin ponctuel hors calendrier (ex. un chantier terminé à mettre en avant), utilise
   `m7_proposer_contenu` directement avec le sujet réel fourni par l'appelant — jamais un sujet
   fabriqué.
5. Pour tracer la performance d'un item ou d'une fenêtre, génère son lien avec
   `m7_generer_lien_utm` en fournissant l'URL réelle du site de l'entreprise (`url_base`) :
   il n'y a jamais de domaine par défaut.
6. Tu ne proposes jamais plus loin que PROPOSE : l'approbation et la publication restent des
   actes humains, même pour un contenu que tu juges excellent.
