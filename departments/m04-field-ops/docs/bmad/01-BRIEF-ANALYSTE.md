# BRIEF ANALYSTE — MODULE M4 (FIELD OPS)

> Analyste : Qwen3.7-Max (prose, rôle respecté). Cadrage rédigé APRÈS M7/M1/M2, AVANT M3
> (ordre ratifié ADR-0003) — toute référence à un devis M3 est un champ optionnel gelé plus tard.


Rédigé par : Analyste BMAD | Statut : PROPOSÉ | Date : 2025-01-XX

## 1. BESOIN MÉTIER

M4 est le chef d'orchestre de l'exécution terrain, garantissant que chaque intervention planifiée est tracée de son assignation jusqu'au déclenchement transactionnel de sa complétion, sans jamais empiéter sur les calculs financiers ou logistiques des modules aval. Son mandat unique est la maîtrise de la cédule et la capture probante de l'effort terrain : M4 transforme un lead qualifié et prêt (readiness M2) en une intervention planifiée, suit le technicien par un pointage horodaté et géolocalisé, et émet le Work Completion Trigger (WCT) qui notifiera l'ensemble du système de la fin des travaux. Les bénéficiaires directs sont les techniciens terrain (qui reçoivent une cédule claire et un outil de pointage robuste), le répartiteur ou l'administrateur (qui supervise les statuts et arbitre les écarts via la file d'attente de revue), et les six modules aval (M6, M5, M2, M7, M8, M10) qui dépendent du WCT pour déclencher leurs propres workflows (déstockage, facturation, mise à jour du pipeline, archivage, etc.). M4 ne calcule jamais de prix (rôle de M3), ne génère jamais de facture ou de transaction financière (rôle de M5), et ne déduit jamais de stock (rôle de M6) : M4 est le déclencheur factuel et horodaté, il ne substitue jamais son jugement aux moteurs de calcul spécialisés.

## 2. CONTRAINTES NON NÉGOCIABLES

La cédule ne peut exister sans readiness : aucune intervention n'est planifiable si le lead sous-jacent n'a pas franchi la gate M2. La géolocalisation (GPS) est strictement bornée aux heures de travail déclarées et le lien vers le client final doit être systématiquement tokenisé pour respecter la Loi 25 sur la protection des renseignements personnels ; M4 ne stocke ni ne transmet l'adresse résidentielle en clair dans ses événements de cascade. Le scoring de performance des techniciens est autorisé à des fins d'optimisation de la cédule, mais le profilage comportemental et toute sanction automatique sont formellement interdits. 

La gestion des écarts (différence entre le prévu et le réalisé, que ce soit en temps, en matériaux ou en périmètre) obéit à une philosophie de transparence absolue : le serveur est autoritaire, mais en cas de conflit sur des données sensibles, l'état passe immédiatement en `pending_review`. Les deux versions (prévue et déclarée) sont présentées à l'administrateur, et M4 ne procède jamais à un écrasement silencieux. Le pointage (punch) est un événement local signé, capturant l'horodatage, le fix GPS et l'attestation d'appareil au moment exact du tap. En cas d'anomalie (ex: GPS incohérent, horodatage impossible), le système exige une revue humaine et ne formule jamais d'accusation automatique de fraude (conformité R-020). Enfin, le Work Completion Trigger est le point de défaillance le plus critique du système : un crash à mi-cascade ne doit jamais laisser un état partiel invisible (ex: stock ajusté mais facture non créée). La cascade du WCT doit être strictement transactionnelle via le patron outbox, garantissant la reprise intégrale en cas d'interruption.

## 3. PROUVABLE MAINTENANT vs GATED/T3

En mode ombre, prouvable en CI Python (stdlib + PyYAML, zéro réseau, zéro horloge interne), M4 déploie son identité de paquet sous `src/m4_field_ops/` avec des imports internes relatifs. Le registre des interventions est append-only et hash-chaîné. La machine à états de l'intervention est modélisée par un énuméré fermé que l'analyste propose ainsi : `planifiee`, `en_route`, `en_cours`, `completed_pending_review`, `terminee`, `annulee` (le PM tranchera la nomenclature finale). La cédule est générée de manière déterministe par des règles pures appliquées sur les données fournies par l'appelant, sans aucun recours à un moteur de routage routier (VRP) réel. Le punch est simulé en acceptant un fix GPS et un horodatage strictement fournis par l'appelant (fixtures avec `fictif: true`). Le WCT en mode ombre se matérialise par l'écriture d'événements de cascade dans un OUTBOX append-only, consommable théoriquement par les 6 modules aval, sans aucun appel réseau réel. Tout écart détecté route vers un registre `pending_review`.

Sont explicitement repoussés en phase GATED/T3 (nécessitant éditeurs de CI, réseau, et matériel) : le routage routier réel (API VRP ou self-hosted), l'API météo pour validation des conditions terrain, le temps réel WebSocket/push pour la mise à jour dynamique de la cédule, le polling GPS matériel réel, l'attestation d'appareil cryptographique réelle, et l'envoi de notifications push aux techniciens.

## 4. CE QUE M4 CONSOMME ET PRODUIT

M4 consomme exclusivement le lead enrichi ayant franchi la readiness gate M2, c'est-à-dire un contrat gelé comprenant : statut `qualifie`, owner humain confirmé, `type_travaux` validé, `ville`, au moins une interaction humaine post-qualification, et la disponibilité déclarée du client (champ optionnel, jamais une date ferme imposée par M2). 

M4 produit trois artefacts majeurs : le Work Completion Trigger (contrat d'événement de cascade à geler pour les 6 consommateurs aval : M6, M5, M2, M7, M8, M10), les demandes d'arbitrage `pending_review` (avec double version des faits), et le statut d'intervention consultable par le répartiteur. 

Concernant le flux avec M3 (Estimation) : il est acté comme OPTIONNEL et son contrat sera gelé ultérieurement. L'ordre de construction ratifié (M7 -> M1 -> M2 -> M4 -> M3) dicte que M3 n'existe pas encore lorsque M4 est bâti. La cédule v1 se fonde donc uniquement sur la readiness M2. Toute référence à un devis M3 accepté dans les données d'intervention de M4 est traitée comme un champ optionnel, comblé par un identifiant nul ou fictif en v1, en attente de l'implémentation de M3.

## 5. RISQUES ET ANGLES MORTS

Le risque majeur est la cascade partielle du WCT : si l'outbox n'est pas strictement atomique avec le changement d'état de l'intervention, un module aval pourrait manquer son déclenchement. Ce risque est mitigeable uniquement par une implémentation rigoureuse du patron outbox couplé au registre hash-chaîné. 

La gestion des fuseaux horaires et des transitions heure d'été/heure d'hiver (DST) sur la cédule est un angle mort historique (leçon M2-S007) : le fuseau doit être une donnée obligatoire et explicite attachée à chaque événement, et M4 ne doit jamais inférer l'heure à partir de l'horloge ambiante du serveur ou de l'appareil. 

Les risques opérationnels incluent le double punch (mitigé par la machine à états qui refuse les transitions illégales), le punch sans intervention planifiée (rejeté à la frontière), et la tentation du scoring punitif (interdit par conception, mais qui nécessite une vigilance constante lors des itérations futures sur les algorithmes de cédule). Enfin, la file `pending_review` risque de s'engorger si les écarts ne sont jamais revus par l'administration, transformant un mécanisme de sécurité en cimetière de données ; une alerte de volumétrie de la file devra être exposée dans le digest quotidien. La collision d'identifiants d'interventions ou d'événements outbox est prévenue par l'encodage canonique injectif (préfixage par longueur) hérité des modules M1 et M2.
