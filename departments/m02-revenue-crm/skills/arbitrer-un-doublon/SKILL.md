---
name: arbitrer-un-doublon
description: Procédure pour présenter un signalement de doublon potentiel à un humain et consigner sa décision, sans jamais fusionner deux leads.
---

# Arbitrer un doublon signalé

1. Un signalement de doublon (`m2_detecter_doublons` ou celui produit automatiquement par
   `m2_ingerer_lead`) porte un critère : `contact_identique` ou `ville_et_travaux`. Présente
   les deux leads concernés à un humain avec ce critère, sans conclure toi-même qu'il s'agit
   du même client.
2. La seule décision possible en v1 est `distincts_confirmes` : les deux leads restent des
   dossiers séparés, pour toujours. Il n'existe aucune option de fusion — si un humain
   demande une fusion, explique que ce n'est pas une capacité de ce département.
3. Une fois la décision humaine obtenue, appelle `m2_arbitrer_doublon` avec le
   `signalement_id` exact et la décision. N'arbitre jamais un signalement de ta propre
   initiative.
4. Le digest quotidien liste les signalements encore `en_attente` : c'est ta rappel pour
   relancer un humain si un arbitrage traîne.
