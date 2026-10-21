# Verticale d’une affaire durable — V1

Date Toronto : 2026-10-06T14:31:17.955303-04:00. Parent exact : `e9c886a56f33f38c4ea32de107b1522e5327cc21`. OPSYS-AI reste **PARTIEL**.

## Résultat borné

Sept scénarios composent les outils existants M7→M1→M2→M3→M4/M6→M5→M8/M9/M10. Le harnais appelle les vrais endpoints HTTP MCP et les consommateurs natifs. Une seule affaire fictive porte les identifiants canoniques ; aucun événement métier n’est inséré pour franchir les jonctions.

Le générateur UTM M7 alimente la réception M1 signée (signature invalide refusée sans mutation), puis qualification, interaction vendeur et devis M3 avec ticket privé C02. L’acceptation exige explicitement N5 ; sans attestation, la décision refuse sans mutation. L’attestation positive est fictive, via le backend console. Le devis accepté est livré à M4 dans un **processus Python neuf**, après arrêt HTTP et libération des connexions, sur la même base. L’intervention vient du reçu canonique du répartiteur.

Réception/réservation matériaux, profils équipe/météo déclarés et localisation validée rendent la préparation et la cédule possibles. Les gestes employés produisent pointages, photos PNG validées, completion, WCT et consommation réelle déclarée. La facture brouillon demeure provisoire ; son envoi interne exige N4 et décision du propriétaire. Cette transition ne démontre aucun transport de courriel ni mouvement d’argent.

Les attentes financières sont indépendantes : prix600, matériau8/unité, trois heures à50. Quantité42 donne marge114 ; quantité56 donne marge2 et variance critique40% au seuil30%. La lecture M9 conserve la décision humaine ; la revue de completion exige N4. Sans prix fournisseur, la marge demeure non calculable. M8 et M10 accusent réception des événements financiers du même WCT.

## Vérification et refus

- SQLite final : **7 scénarios réussis** ; 7 déclinaisons PostgreSQL ignorées localement parce que Docker est inaccessible.
- Après correction de revue : **22 réussis / 7 ignorés**, comprenant les 15 contrôles CI. Ruff des trois fichiers Python et diff whitespace verts.
- Régression élargie avant les assertions explicites N5/N4 : **267 réussis / 33 ignorés**, tous E2E et fichiers voisins C02/appareils/portées/cascade/CI. Sources figées pendant chaque campagne. Les campagnes se recouvrent et ne s’additionnent pas.
- Lectures et rejeu des mutations employé : empreinte du contenu de toutes les tables déclarées dans META avant/après, pas seulement des compteurs.
- Vendeur concurrent : verdict fermé identique à une ressource inconnue ; appareil révoqué :403 avant effet métier.
- Panne injectée au véritable point de publication financière : tous les registres métier et événements de rentabilité comparés restent inchangés, facture BROUILLON. La décision d’échec/audit est conservée ; aucune assertion de rollback intégral des autres tables n’est faite.
- CI : nouveau job PostgreSQL obligatoire dans `gates`, image canonique explicitement préparée, JUnit non vide et zéro skip/error/failure exigé. Cinq tests exécutent le vrai validateur contre des rapports positifs/négatifs. Résultat distant du nouveau commit encore **à obtenir**, jamais déduit du parent vert.

## Limites et suite conservée

La porte d’appareil du harnais est une réimplémentation Python ; cette V1 ne qualifie ni le Core TypeScript ni un téléphone réel. L’admission des profils runtime configurables, leurs quotas et leur révocation ne sont pas exercées : aucun runtimeProfile* n’est transmis. La reprise démontre le répartiteur métier après devis ; le rejeu employé est ensuite testé dans le processus courant, sans crash intermédiaire.

Les reçus M10 `traite` ne démontrent pas la restitution ultérieure autorisée, l’isolation mémoire ou l’amélioration du contexte. Le prix fictif ne qualifie pas photo→mesure→estimation. Le profil mobile client reste un écran squelette : pas de parcours client ni lien temporaire signé qualifié. Les trois autres rôles du harnais ne prouvent pas quatre profils mobiles livrés.

Profils météo déclarés ≠ prévision réelle. UTM généré ≠ contenu publié, lead public ni ROI. Fournisseur, professionnel, argent, appareils réels, restauration indépendante restent à qualifier. Les intentions réseau incertaines et leurs blocages Core restent dans les suites existantes ; aucune nouvelle garantie n’est revendiquée.

Les dix départements profonds, Core OpenClaw, dashboard, mobile hors ligne, avatars et mémoires métier/développement séparées restent dans la file existante avec dépendances et critères. Les104 preuves absentes du transfert léger demeurent absentes, références conservées. L’audit précédent au parent reste immuable.

## Traçabilité

[Registre et empreintes](REGISTRE-VERTICALE-2026-10-06-V1.json). [Tous les nouveaux rouges et verts](PREUVES-VERTICALE-2026-10-06-V1-r1.tar.xz), SHA256 `6cf157e08d6cb2ef89c6662d1d22854d8ee4eb9535d215cd9d89831bfacc50b7`. Revue indépendante : faiblesse de preuve N5 corrigée par niveau attendu explicite, puis réexécution positive. Aucun code métier, dépendance verrouillée ni garde de production modifié dans ce lot.
