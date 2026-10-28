# Carte des lecteurs de temps et de visites — M4

Les sources sont les registres M4 `principal` et `visites_chantier` ; aucun ancien pointage n'est rattaché par proximité. Les conclusions ci-dessous portent sur la branche de mission, pas sur la base publiée ni une intégration M5.

| Lecteur | Source et comportement pour plusieurs visites | Statut / limite |
|---|---|---|
| `visites_chantier.calculer_faits_certifies` | Vérifie les prévisions, ouvertures, pointages et fermetures, calcule par session en UTC, puis additionne les minutes nettes, pauses et déplacements. | Calcul propriétaire utilisé pour un WCT segmenté ; les options de projection partielle sont réservées à la consultation et ne constituent pas un total WCT. |
| `outbox.calculer_duree_reelle`, `calculer_minutes_pause`, `calculer_minutes_deplacement` | Un marqueur ou fait étiqueté impose le registre de visites ; sans celui-ci ou si les sources sont incohérentes, refus. Deux arrivées legacy empêchent les calculs globaux ambigus. | Tests ciblés : oracle 390/30/60 et refus sans registre ; double départ legacy conservé. |
| `outbox.completer_intervention` et outil M4 | Appelle la durée certifiée lorsque les visites sont explicites, refuse les sources absentes ou ambiguës, écrit un seul WCT. | Parcours HTTP/outils et réouverture SQLite fictifs vérifiés. |
| `temps.produire_brouillon_temps` | Consomme le WCT puis appelle le déplacement sans registre de visites. | Refuse les WCT segmentés plutôt que d'attribuer leur total au dernier technicien ; aperçu non adapté, aucune ventilation calculée. |
| `heures_regulieres.previsualiser` et pont préparatoire M5 | Lisent les faits par technicien et exigent une paire unique par intervention et une identité non ambiguë. | Refus sur le scénario de deux équipes ; pas de déduction d'effectif ni de paie. |
| `calibration_projection.lire_projections` | Recalcule la durée sans registre de visites et refuse une divergence avant publication d'observation. | Les WCT segmentés ne sont pas admis comme observation ; la sémantique de calibration historique ne doit pas être modifiée implicitement. |
| `journal_quotidien` / T0 | Contrat historique avec `ancre_visite=None`; les faits restent affichés par source. | La console privée ajoute séparément des liens vérifiés, avec contrôle des deux snapshots et pagination ; le T0 partagé ne change pas. |
| Console `visites_chantier` | Prévisions, sessions fermées vérifiées, composition déclarée du jour, interruption et inconnus ; sessions ouvertes non totalisées. | Présence individuelle non inférée ; aucun total global si les faits anciens restent ambigus. |
| M5 `wct_recus` / `cout_reel` | Le récepteur existant recopie le WCT V1 et `cout_reel` multiplie sa durée scalaire par un taux fourni. | Il ne connaît pas la ventilation par visite ni les présences individuelles : risque d'interprétation en aval. Aucun changement M5 dans cette branche ; contrat V2 proposé dans `CRM01-16-CONTRAT-TEMPS-M5.md`, intégration et décision de consommation à coordonner. |

Les listes d'appels ont été contrôlées avec `rg` dans les sources et tests M4. Les tests des vues historiques se recoupent avec les régressions détaillées dans `CRM01-16-VISITES-CHANTIER.md` ; ils ne démontrent pas un fonctionnement productif ou une intégration aval complète.
