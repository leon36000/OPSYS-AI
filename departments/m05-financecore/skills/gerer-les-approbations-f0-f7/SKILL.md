---
name: gerer-les-approbations-f0-f7
description: Procédure pour créer une demande d'approbation F0-F7 et enregistrer la décision d'un humain — F6 (argent réel) et F7 (position fiscale) exigent une preuve structurée, jamais une chaîne libre.
---

# Gérer les approbations F0-F7

1. Crée la demande avec `m5_creer_demande_approbation` : identifiant unique,
   palier F0-F7 choisi par le demandeur (pas déduit), description de l'action,
   horodatage. Un palier hors F0-F7 est refusé.
2. La décision (`APPROUVE` ou `REFUSE`) appartient toujours à un humain — tu ne la
   prends jamais. Un fois le nom de l'approbateur connu, appelle
   `m5_decider_approbation`. C'est une action T3 : elle passe par la file
   d'approbation même si la décision affichée vient déjà d'un humain nommé.
3. Pour F0-F5, un `approbateur` non vide suffit.
4. Pour F6 (argent réel) ou F7 (position fiscale — mention CPA), `preuve` est
   OBLIGATOIRE et doit être une chaîne JSON portant exactement trois clés :
   `methode`, `horodatage` (ISO 8601 avec fuseau) et `identifiant_approbateur`.
   Exemple : `{"methode": "MFA_TOTP", "horodatage": "2026-08-03T12:00:00-04:00",
   "identifiant_approbateur": "EMP-042"}`. N'invente jamais un fournisseur MFA
   précis dans la méthode : nomme seulement ce que l'humain a réellement utilisé.
5. Une preuve absente, vide, ou en chaîne libre non structurée est refusée
   (`REJ-PREUVE-ABSENTE` ou `REJ-PREUVE-STRUCTURE-INVALIDE`) : redemande la preuve
   correctement formée, ne la fabrique jamais.
6. Le statut courant d'une demande se relit toujours depuis la chaîne du registre
   (`approbations_historique`) — jamais un champ que tu positionnerais toi-même.
