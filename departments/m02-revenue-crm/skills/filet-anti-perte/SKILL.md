---
name: filet-anti-perte
description: Procédure pour lire le filet anti-perte de M2 (violations SLA, anomalies d'intégrité, plan de réparation) sans jamais prendre une règle non évaluée pour une absence de problème, et sans rien exécuter ni envoyer.
---

# Filet anti-perte

Le filet répond à une question : « quel lead est en train de se perdre, et pourquoi ? ». Il LIT les registres de M2 ; il
n'écrit rien, n'envoie rien, ne fusionne rien. Les trois outils sont réservés à l'agent et à l'administrateur (tous les
leads) : un vendeur n'y a pas accès.

1. `m2_scanner_sla` (instant courant `horodatage`) : les violations des sept règles SLA, une page à la fois, chacune avec
   sa règle (énoncé dans `enonces`), sa raison, depuis quand (`depuis`) et le seuil déclaré. Lis TOUJOURS `regles` avant
   `violations` : une règle `non_evaluee` n'a PAS de violation, elle n'a pas de délai déclaré. Relaie son `manque`
   (« déclarer heures_lead_chaud … dans configuration.sla de department.yaml ») ; ne propose jamais une valeur comme si
   elle était décidée, c'est une décision du propriétaire. Une règle `partielle` n'a vérifié que ses incohérences
   immédiates.
2. `m2_auditer_integrite` : les huit contrôles d'intégrité des données (lead sans statut, client sans contact, tâche sans
   propriétaire, soumission orpheline, activité sans lead, lead sans client, pipeline incohérent, doublon probable). Un
   doublon probable est une SUGGESTION d'arbitrage : n'en fusionne jamais un, M2 ne fusionne rien.
3. `m2_planifier_reparations` : le plan, par urgence (plainte, lead chaud, lead sans propriétaire, …). Chaque action est
   PROPOSÉE (`execute: false`) ; celles qui disent `approbation_requise: true` passent par une personne dans le sas
   d'approbation. La prochaine meilleure action existante accompagne chaque lead (règle citée).
4. Lis page par page : tant que `suivant` n'est pas nul, rappelle l'outil avec `decalage = suivant`.
5. Un constat planifié (`m2_constater_filet`) publie chaque jour les COMPTES pour M8 (mesures `m8_violations_sla_commercial` et
   `m8_anomalies_integrite_crm`) ; ne l'appelle pas toi-même : le planificateur durable s'en charge, une fois activé par
   l'administrateur.
