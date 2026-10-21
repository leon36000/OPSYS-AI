# Réception admin M1 — Toronto, 2026-10-07

OPSYS-AI reste **PARTIEL**. Cette tranche T4.26 part du parent M10 `91d95c0a510a74e389ebf721dcde4a403f561f55`. Les 24 sources M1 sont rapprochées de leurs préimages ; vingt fichiers sans chevauchement sont conservés, quatre fichiers communs sont fusionnés avec le parent. Les réceptions natives sous parent21 restent des preuves historiques distinctes. Aucun graphe de dépendances nouveau n’est adopté.

## Comportement

L’écran Réception admin lit deux objets indépendants : le digest déterministe d’une date calendaire choisie et la fiche d’un transfert sélectionné dans les attentes existantes. Les liens depuis À voir et les pages suivantes des attentes reprennent seulement les vrais IDs `tr-<20hex>` M1 ; aucune référence n’est reconstruite depuis une conversation ou un lead.

Le digest conserve les mots et compteurs du serveur. Il compte des événements datés et des suivis courants, sans promettre des clients uniques ni un snapshot historique atomique. Son cache informatif est personnel et lié à la date. La date saisie concerne ce digest ; la fiche indépendante conserve sa propre source et date de lecture.

Contacts et messages de transfert restent exclusivement au serveur, sans ouverture KV ni cache de fiche. L’écran montre les références transfert/conversation/lead, le résumé et son origine, le destinataire inconnu ou son refus, les catégories, messages et omissions, le retrait STOP, le suivi de rappel et le brouillon non envoyé. Aucun bouton d’envoi, clôture ou prise en charge n’est ajouté.

La garde confirme l’admin actif avant données et cache. Les appels internes sans identité gardent leur contrat ; le propriétaire confirmé en console garde son rôle réel et sa provenance serveur. Un argument ou `_meta` ne peut forger cette provenance. Retrait de rôle, autre époque et fermeture d’écran écartent les réponses tardives ; la déconnexion masque les contacts et demande une relecture serveur. Les refus et données illisibles restent distincts d’une absence de données.

## Qualification

Les cinq contrôles principaux intégrés ont le même digest avant/après : `2037dec36a7bfee47aaeaa10e3b2822ae21353704843fab51cfeb4e547af72b1`.

- **3 205 tests mobiles, 160 suites**, TypeScript entier ; contrats stricts, lecteur, service, liens, rendus et langues.
- **1 672 tests Python**, sans skip sur le département, HTTP MCP/SQLite et console réception.
- Ruff global pertinent et vérificateur : **10 départements, 219 outils, 127 déclarations d’appareil**.
- Gateway Node réelle sur le parent91d : **18 appels, 13 groupes**, DEVICE opaque appairé, digest DIRECT et trois transferts COUPLE. Employee/seller, usurpation de deviceId, dates invalides et source console forgée sont refusés. Rôle retiré/inactivité refusent avant registre. Toutes les tables restent inchangées à chaque lecture ; le transfert est identique après redémarrage du backend.
- Deux tentatives Core de catalogue externe sont bloquées par la garde du test, sans garantie réseau globale de la machine. Les processus sont arrêtés ; données/configs/tokens restent dans les environnements privés, hors allowlist publique.

Les 18 réponses natives sous parent21 sont rejouées par le vrai client mobile et ses lecteurs, avec leurs codes de refus exacts : ce rejeu Jest reste distinct de la capture Node sur parent91d et d’un téléphone physique. Les fixtures Python antérieures sont encore distinctes. L’export Android JavaScript combiné sur le principal passe avec **1 556 modules**, sans bytecode ; son digest avant/après est `45b1a5a6430718ddbad2884a1892f01aa7655921c0a948fb608d919ac924393b`. Cette empreinte diffère de celle des cinq contrôles seulement après ajout des documents d’audit.

La revue indépendante confirme les 24 empreintes et passe 58 tests ciblés ; aucun finding matériel n’est relevé dans ce périmètre. Le soupçon lié à une date de digest invalide est retiré : cette date ne change pas l’identité de la fiche indépendante.

## Continuité et limites

Une commande `pnpm exec` a déclenché une installation implicite. Son verrou incident est conservé hors source ; le graphe mobile a été rétabli par `npm ci` depuis `package-lock.json` inchangé, puis les suites et TypeScript ont été requalifiés. Le runtime verrouillé existant est conservé. Les erreurs d’invocation et l’assertion du harnais qui supposait `envoye` sur un rappel sont gardées avec leurs dispositions ; elles ne sont pas des défauts métier.

Le socle complet local M10 r3 reste rouge : 4 367 réussites, 224 skips, deux oracles sans cpu.max et une assertion Hermes UTC corrigée, puis 95 tests voisins verts. La CI du parent91d et celle du prochain commit exact sont des preuves distinctes. Aucun succès global M1 n’est déduit en additionnant les contrôles ciblés.

Téléphone, Expo SQLite et Hermes natifs ne sont pas qualifiés. Les canaux réels, voicemail authentifié, rappels jusqu’au contact, prise en charge, réponse approuvée et activation de prestataires restent ouverts avec ADR-0011. Les 104 preuves exclues du transfert, son supplément généré et les conversations absentes restent tracés sans disponibilité ni réexécution inventée. Les dix départements profonds et la verticale M7→M1→M2→M3→M4/M6→M5→M8/M9/M10 restent requis. Aucun paiement, envoi externe, force-push, fusion ou déploiement.
