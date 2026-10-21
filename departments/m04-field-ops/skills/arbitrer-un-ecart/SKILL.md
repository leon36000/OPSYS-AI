---
name: arbitrer-un-ecart
description: Procédure pour consulter la file des demandes de revue en attente (écarts métier et anomalies de pointage) et faire arbitrer leur résolution par un humain, sans jamais décider soi-même.
---

# Arbitrer un écart

1. Consulte `m4_lister_pending_review` (filtre optionnel par type : `ecart_metier` ou
   `anomalie_pointage`) ou `m4_volumetrie_pending_review` pour la vue d'ensemble.
2. Présente à l'humain les DEUX versions des faits (prévue et déclarée) pour un écart métier, ou
   les causes possibles neutres pour une anomalie de pointage. Ne choisis jamais à sa place.
3. Une fois la décision humaine obtenue, appelle `m4_resoudre_demande` avec `decision` exactement
   `validee` ou `rejetee` :
   - un écart métier `validee` COMPLÈTE l'intervention (Work Completion Trigger émis) ;
   - une anomalie de pointage `validee` fait REPRENDRE l'intervention (retour sur_site, le
     technicien continue son travail — aucun WCT n'est émis, rien n'est terminé) ;
   - toute décision `rejetee` ANNULE l'intervention, quel que soit le type de la demande.
   Ces deux issues de `validee` sont différentes : ne les confonds jamais, et ne présume jamais
   laquelle s'applique sans lire `type_demande` dans la demande listée à l'étape 1.
4. `accepte: false` → le `verdict` nomme la faute (demande déjà résolue, introuvable,
   transition impossible) : rapporte-le à l'humain sans réessayer une autre décision en silence.
