---
name: ingerer-un-lead
description: Procédure pour ingérer un lead qualifié transmis en amont, en détectant les doublons probables sans jamais les fusionner.
---

# Ingérer un lead

1. Réunis le contrat du lead tel que M1 l'a émis, avec sa version : v2 (`schema_version: 2`,
   champ `service`) ou v1 historique (sans `schema_version`, champ `type_travaux`) — jamais
   l'un déguisé en l'autre. Champs : lead_id, conversation_id, contact, service (v2) ou
   type_travaux (v1), ville, urgence_declaree, canal ; puis l'horodatage de l'appelant. N'en
   invente aucun champ : un champ manquant est un motif de demander la donnée, pas de la deviner.
2. Appelle `m2_ingerer_lead` une seule fois. L'outil valide la structure et les frontières de
   vérité (aucun prix, aucune date d'exécution dans le contrat), écrit le lead au registre,
   détecte les doublons probables et signale ceux qui existent, puis rapporte le statut et la
   readiness.
3. Lis la réponse :
   - `accepte: false` → un `verdict` explique le rejet (structure invalide, frontière
     violée, ou lead déjà ingéré). Corrige et réessaie, ou escalade.
   - `doublons_signales` non vide → informe un humain qu'un arbitrage est requis ; ne
     présume jamais lequel des deux dossiers est le bon.
   - `statut` vaut toujours `nouveau` juste après l'ingestion, et `pret_pour_m3` est
     `false` tant qu'aucun owner ni aucune interaction n'existe encore : c'est normal, pas
     une erreur.
4. Le lead reste en statut `nouveau` jusqu'à ce qu'un humain lui assigne un owner : c'est la
   skill « faire-progresser-vers-m3 » qui prend le relais.
