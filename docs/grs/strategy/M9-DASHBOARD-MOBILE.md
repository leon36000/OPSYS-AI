# M9.21–22 — tableau de bord `/direction` et contrat mobile admin

Statut : M9.21 **DONE_VERIFIED** ; M9.22 **PHASE_MOBILE_FINALE** (contrat
serveur prêt et testé, aucun écran ; l'écran mobile figure parmi les gates de l'audit §7).
[Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) · [salle de guerre](M9-DAILY-WAR-ROOM.md) ·
[contrat mobile](../../reprise/M9-COMPLETION-20261028/CONTRAT-MOBILE-ADMIN-M9.md) ·
[table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Donner à Nathan, dans la console OPSYS existante, une vue de direction lisible sur bureau comme sur téléphone, où
chaque chiffre renvoie à sa preuve ; et fixer côté serveur ce que l'app mobile admin pourra appeler.

## Pourquoi

Le cahier prévoyait un tableau BI séparé (Superset) et un écran mobile. La console a déjà sessions, CSRF, en-têtes de
sécurité et rendu échappé : M9 l'étend (ADR-0012). L'app mobile est un pilier du produit (§9) mais son écran admin M9
appartient à la phase mobile ; le serveur doit être prêt sans prétendre que l'écran l'est.

## État actuel

**Console (`direction_ui.py`)** — 16 routes sur 15 chemins, admin seulement :

- `/direction` : formulaire sans date préremplie (instant de connaissance + jour civil), puis sept panneaux
  indépendants : « Briefing — salle de guerre », « Risques », « Indicateurs exécutifs », « Prévisions des
  propriétaires », « Plans et suites », « Actions proposées et approbations », « Veille ». Un panneau refusé affiche son
  code `REJ-…` sans masquer les autres.
- Détail : `/direction/risques`, `/sources`, `/plans` (+ POST `/plans/suivi`, `/plans/annuler`), `/actions`,
  `/conseil` (hors barre de navigation), `/revues`, `/revue`, `/veille`, `/indicateurs`, `/decision`, `/tendances`,
  `/scenarios` (GET + POST).
- Pas de page pour les occasions (M9.13), les playbooks (M9.15), les expériences (M9.18) ni la mémoire M10 (M9.20).

**Contrat mobile** : `CONTRAT-MOBILE-ADMIN-M9.md`, généré depuis le manifeste réel et prouvé par
`tests/test_m9_contrat_mobile_admin.py` : lectures N0, écritures internes N1/N2, trois outils fermés aux appareils, règles
(admin seul, bornes, vue périmée, dates fournies). **Aucun écran, aucun mode hors ligne, aucun test sur appareil réel.**

## Architecture

Sécurité de la console :

- session obligatoire (anonyme redirigé vers la connexion) ; rôle `admin` vérifié sur la session, puis rôle relu en base
  par `metier.executer` à chaque lecture ; un refus d'identité devient 403 ;
- paramètres en liste fermée par page : inconnu, répété ou trop long → 400 sans lecture ; formats d'instant, de jour,
  d'identifiant et de départ contrôlés ;
- deux commandes POST seulement (suivi et annulation de plan) : jeton CSRF (`verifier_formulaire`), corps borné,
  `mutation_id` idempotent (même identifiant et autres données → 409), confirmation explicite de l'annulation ;
  horodatage posé par le serveur ; le POST de scénarios ne fait que calculer ;
- rendu générique entièrement échappé, borné en profondeur (6), en éléments (60) et en texte (400, reste compté) ;
  page au-delà de 256 Kio refusée (`REJ-DIRECTION-BORNE`, 409), jamais tronquée en silence ;
- en-têtes de la console : `Cache-Control: no-store`, CSP `default-src 'none'` ; aucun script inline.

Mobile : seul `admin` appelle un outil M9 depuis un appareil ; vendeur, employé et client sont refusés ; lectures bornées
à 5 900 caractères (`BORNE_TELEPHONE` du test) et paginées par `depart`.

## Fichiers

[direction_ui.py](../../../src/opsys/console/direction_ui.py), `src/opsys/console/application.py` (montage du routeur),
`src/opsys/console/metier.py` (exécution des outils),
[CONTRAT-MOBILE-ADMIN-M9.md](../../reprise/M9-COMPLETION-20261028/CONTRAT-MOBILE-ADMIN-M9.md).

## Outils et pages de console

Lectures du tableau : `m9_salle_de_guerre`, `m9_radar_risques`, `m9_indicateurs_executifs`, `m9_previsions_consolidees`,
`m9_lire_plans`, `m9_lire_actions`, `m9_lire_veille` ; détail : `m9_couverture_strategique`, `m9_lister_captures`,
`m9_lire_conseil`, `m9_lire_rapport_conseil`, `m9_lister_revues`, `m9_lire_revue`, `m9_cadrer_decision`,
`m9_projeter_tendance`, `m9_evaluer_scenarios` ; commandes : `m9_noter_suivi_plan`, `m9_annuler_plan`. Les approbations
se décident dans la file native `/approbations`.

## Données et registres

La console ne lit que par les outils M9 ; elle n'écrit que dans le registre `plans` (suivi, annulation). Aucun état
propre.

## Workflows

1. Ouvrir `/direction`, saisir l'instant et le jour ; lire les panneaux et suivre « Voir le détail et les preuves ».
2. Noter un suivi ou annuler un plan (confirmation) ; retour sur la même vue.
3. Mobile (à construire) : mêmes lectures, recharger sur `REJ-VUE-PERIMEE`.

## Intégrations

Sessions et CSRF de la console, file d'approbation native, Core pour la portée d'appareil (`roles_appareil`).

## Risques

- Le lien de détail du panneau « Prévisions des propriétaires » pointe vers `/direction/risques`, pas vers une page de
  prévisions.
- Champ POST répété accepté en silence (limite connue du rapport de livraison ; non exploitable sans CSRF valide).
- La QA navigateur archivée a vu six panneaux : le panneau « Indicateurs exécutifs » a été ajouté après et n'est vérifié
  que par HTTP.
- Contrat mobile : la description de `m9_lister_playbooks` y dit encore « six gabarits » (17 dans le code).

## Gates Nathan

Écran mobile admin (phase mobile) ; choix des panneaux supplémentaires (occasions, playbooks).

## Tests

`tests/test_console_direction_m9.py` (formulaire sans date, panneaux indépendants, en-têtes, XSS, rôles courants,
paramètres invalides ou répétés, lectures sans écriture, CSRF/idempotence/confirmation, corps borné, scénarios,
pagination des sources, code de refus de repli, tableau : risques et changements depuis la veille) ;
`tests/test_m9_contrat_mobile_admin.py` (portées du manifeste, quatre profils, sortie bornée).
Navigateur : `preuves-navigateur/` (Chromium par Playwright, 1280 px et 390 px, aucun débordement horizontal, XSS rendu en
texte, suivi puis annulation, aucune erreur de console).

## Statut

M9.21 DONE_VERIFIED (HTTP et navigateur, données fictives) ; M9.22 PHASE_MOBILE_FINALE : serveur prêt, aucun écran.

## Prochaines étapes

1. Phase mobile : écran admin, hors ligne, rechargement sur vue périmée, tests appareil réels.
2. Corriger le lien du panneau « Prévisions des propriétaires » et rejouer la QA navigateur avec sept panneaux.
