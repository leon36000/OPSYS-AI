# Audit de direction OPSYS-AI — 4 octobre 2026

Référence utilisateur : soirée du 4 octobre, America/Toronto. Les campagnes et fichiers
portant `2026-10-05` emploient l'heure UTC. Audit ciblé transversal du checkout local,
consolidé par ROOT après trois lectures indépendantes. Ce document ne certifie pas une
lecture exhaustive de chaque fichier ni un déploiement. Les preuves locales ne valent
que pour les octets et les cas indiqués dans leurs rapports.

## Décision de direction

L'ambition reste correcte : donner à une PME dix départements IA profonds, plusieurs
agents configurables, une mémoire d'entreprise, des outils spécialisés, un mobile
multirôle et une autonomie sous permissions. Il faut maintenant réduire l'écart entre
les capacités techniques et les résultats observables de l'entreprise. Le produit global
reste **PARTIEL**. Aucun pourcentage de complétion ou d'assimilation n'est calculable.

La priorité suivante est une verticale métier avec preuve des raccords, de la reprise et
des autorisations. La recherche de briques reste obligatoire avant une capacité majeure;
elle doit aboutir à un choix documenté et à une intégration, sans empiler les frameworks.
Les validations humaines des actes financiers, fiscaux, contractuels et publics restent
applicables. Aucun consensus de trois modèles ni attente d'un modèle extérieur n'est requis.

Sources d'intention : [directives Nathan](../produit/DIRECTIVES-NATHAN.md),
[définition produit](../produit/DEFINITION-PRODUIT.md),
[périmètre détaillé](../produit/PERIMETRE-MODULES.md) et
[entreprise apprenante](../produit/VISION-ENTREPRISE-APPRENANTE.md).
Les anciens prompts Forge décrivent la profondeur cible; leurs numéros de routes,
chemins et statuts ne sont pas des constats du dépôt OPSYS actuel.

## État par département et dimension

| Domaine | Existant constaté | Écart qui reste à fermer |
|---|---|---|
| M1 Front Office | Registres, qualification, plaintes/transferts, canaux et pont HTTP interne signé vers M2 | Formulaire public non connecté; réception vocale et reprise émetteur qualifiées seulement sur leurs tranches, pas téléphonie client complète |
| M2 CRM | Dossier client, opportunités, événements et accès par rôle; consommation M1 réelle | Ne pas reconstruire; démontrer une même demande jusqu'à soumission/exécution/facturation dans les surfaces des utilisateurs |
| M3 Estimation | Orchestrateur, devis durable, revues et calibration temporelle M4 raccordée/versionnée | Validation empirique manquante; pixels/géospatial de mesure non qualifiés; boucle matériaux/coûts/finalité encore incomplète |
| M4 Terrain | Pointages, WCT, localisation confirmée, cédule et raccords matériels | Le temps écoulé d'intervention ne vaut pas heures-personnes ni paie; exploitation terrain et couverture corpus à qualifier |
| M5 FinanceCore | Factures, AR/AP, taxes préparatoires, rentabilité, cash libre/prévision, imports financiers et candidats OCR | CFO complet, paie officielle et connecteurs externes non qualifiés; brouillon/finalité ne doivent pas être confondus dans les données de retour |
| M6 Matériaux | Besoins, disponibilités, réception, consommation et variance raccordée | Variance calculable ne signifie pas cause confirmée; unités inconnues excluent un apprentissage quantitatif |
| M7 Marketing | Chantier→contenus, consentement/revue/export manuel, attribution UTM et revue mobile texte | Les onze fonctions du département CMO ne sont pas toutes achevées; coûts Ads/ROI, OAuth et publication restent à prouver séparément |
| M8 Analytics | Faits et métriques provenant de plusieurs départements | Couverture, finalité et fraîcheur à rendre explicites; ne pas inventer ROI ou marges définitives |
| M9 Direction | Arbitrages/demandes et lecture de faits des départements | Ne constitue pas encore une direction autonome couvrant toutes les opérations d'entreprise |
| M10 Mémoire | Registres, droits, provenance, imports/reprises et store PostgreSQL/pgvector; hooks Core existants | Hooks optionnels; dépôt postflight perdu après échec sans reprise durable démontrée; corpus d'entreprise et qualité retrieval à évaluer |
| Agents / tokens | Profils versionnés, budgets, admissions et réserves transactionnelles, outils limités | Synchronisation de config ≠ tâche active; déclencheurs spécialistes partiellement déclaratifs; budgets historiques et coûts monétaires incomplets |
| Fusion de données | Filières procédures TXT/MD, CSV banque et PDF Finance, provenance et états persistants | Pas d'ingestion universelle massive, classification générale ou note d'assimilation fiable; OCR candidat ≠ facture comptabilisée |
| Avatar | Renderer Three.js/GLTF réel dans le Core | Audio, visèmes, interruption, ACE et mobile audiovisuel non qualifiés; le rendu statique ne démontre pas la conversation |
| Installation autonome | Installateurs natifs et Compose; scripts sauvegarde/restauration | VPS agents bloqués par raccord sandbox absent; redémarrage du processus ≠ reprise du travail; restauration complète réelle à qualifier |

Cette matrice est qualitative. « Existant » décrit des composants et tranches observés,
pas le département cible complet. Les manifests déclarent de vrais contrats mais ne
prouvent pas, à eux seuls, la livraison effective d'une cascade entière.

## Écarts prioritaires

1. **Preuve du parcours métier.** Plusieurs E2E existent déjà. Il faut enchaîner les vrais
   points d'entrée et distinguer serveur réel, porte mobile simulée, Core et navigateur.
   Première correction de qualification : remplacer l'hypothèse du récepteur par la vraie
   route HTTP dans un trajet M7→M1→M2→M8, avec recréation de console et rejeu.
2. **Vérité financière pour apprendre.** `cout_reel.calculer_rentabilite` connaît
   `prix_definitif`; la charge `m5.rentabilite_chantier` ne le transporte pas. Un coût complet
   et une facture brouillon peuvent produire `CALCULEE`. Ajouter l'indication sans modifier
   les montants ni réécrire les anciennes charges. Absence historique = finalité inconnue.
3. **Continuité des agents et de la mémoire.** Qualifier un déclencheur réel, son admission,
   le travail et sa capture mémoire à travers panne/reprise. Ne pas ouvrir la sandbox VPS
   ou libérer automatiquement un usage fournisseur incertain pour obtenir un vert.
4. **Assimilation exploitable.** Réunir inventaire, source, état de revue, erreurs/reprises et
   prochaine action d'un lot borné. Conserver explicitement la distinction extrait/candidat/
   validé. Mesurer le rappel sur un corpus consenti avant tout score marketing.
5. **Apprentissage chantier.** Réutiliser les jointures WCT/devis/hash et afficher
   durée/matériaux/rentabilité avec exclusions. Ne pas recalibrer les prix depuis une facture
   brouillon, des unités inconnues ou une cause non classée.
6. **Interfaces et exploitation.** Montrer activation/synchronisation/tâche exécutée
   séparément; réunir état des connecteurs, permissions, budgets et repli. Tester une
   restauration isolée avant RPO/RTO. L'audiovisuel reste une tranche propre, sans perdre
   l'objectif d'un avatar par département.

## Revue du travail hérité et des conclusions des sous-agents

Le fork OpenClaw, les contrats déterministes, le socle transactionnel et les scénarios métier
sont des fondations utiles. Il faut les conserver. La documentation et les preuves montrent
cependant plusieurs écarts entre « composant testé » et « département utilisable ». La suite
doit privilégier les raccords métier et la récupération après incident, pas une nouvelle
reconstruction du CRM, de la finance ou du Core.

L'auteur Git ou le nom d'un agent ne prouve pas le modèle réellement employé. Cet audit ne
peut donc attribuer chaque ligne à « Opus 5.5 » ni comparer objectivement deux modèles sans
leurs traces. L'appréciation porte sur le résultat logiciel et les preuves, pas sur cette attribution.

ROOT a corrigé les extrapolations des lectures indépendantes :

- L'audit initial OCR disant stockage/UI absents précède les tranches
  [stockage](../grs/compta/M5-OCR-STOCKAGE-2026-10-04.md) et
  [console](../grs/compta/M5-OCR-CONSOLE-2026-10-04.md). Ces composants sont qualifiés localement;
  l'AP automatique, les factures réelles et le VPS ne le sont pas.
- Le renderer 3D est présent dans
  `core/ui/src/pages/chat/components/chat-agent-3d-avatar.ts`. Le pipeline audiovisuel complet
  reste absent des preuves ciblées.
- Les constats M10 de septembre n'annulent pas les hooks/imports actuels. La CI M10 qui
  échouait au head26 n'est pas le résultat de la correction locale ultérieure :
  [qualification CI/M10](../research/REPRISE-2026-10-04/DEPENDANCES-SOCLE-M10.md).
- Le commentaire « until that graft is in » de `opsys-contexte-garde.ts` est lui aussi
  historique : `core/src/agents/agent-tools.before-tool-call.policy.ts` importe la garde
  et l'appelle dans les chemins d'autorisation, avec refus si blocage. Son raccord est
  présent dans le code; cet audit ne rejoue pas la qualification du runtime Core.
- L'[audit M3 récent](../grs/estimation/M3-APPRENTISSAGE-AUDIT-2026-10-05.md)
  remplace les constats historiques « aucun appelant » et « aucune boucle M4/M6 » pour
  la direction actuelle. L'audit historique demeure intact.

## Preuve ajoutée et limites

Campagne ROOT **r222** : les **6 cas complets** de
`tests/e2e/test_formulaire_utm_bout_en_bout.py` passent, avec Ruff et vérification des manifests;
sources gelées avant/après, aucun saut ni échec. Le nouveau cas passe par la vraie console
FastAPI, le stockage SQLite migré, les consommateurs M1/M2/M8 et le moteur MCP servi par uvicorn.
Il vérifie HMAC invalide, conservation UTM, lecture Client 360, recréation de l'application,
un seul événement/lead attribué après rejeu et absence de contact dans la vue M8.

Le modèle de porte appareil reste Python; le Core TypeScript, le navigateur et le téléphone
physique ne tournent pas dans ce scénario. La création de contenus est déclenchée par un WCT
fictif. La clé et les identités sont fictives; aucune publication ni communication client.
Le récepteur est interne et désactivé par défaut. Aucun retry émetteur hors délai n'est qualifié.

Première correction produit intégrée :
[finalité financière M5→M8/M10](../grs/compta/M5-FINALITE-EVENEMENT-RAPPORT-2026-10-05.md).
ROOT **r225 : 329/329 dans neuf fichiers complets**, sources gelées et stables, aucun saut,
Ruff et manifests verts. Cette campagne inclut les six E2E ci-dessus sur leur source finale.
Le premier essai r224 conserve son échec PostgreSQL dû au disque plein; reprise sur vrai
PostgreSQL éphémère en RAM, aucune assertion retirée. Cela ne démontre ni persistance PostgreSQL
sur disque, ni nouveau rapport de calibration M3, ni paie/CFO complet.

Publication privée : le dernier contrôle GitHub connu renvoie **401**. Le lot demeure local,
avec préparation isolée; aucun push, CI distante ou déploiement n'est annoncé.

Programme exécutable : [24 prochaines heures](PROGRAMME-24H-2026-10-04.md).
Les rapports bruts, corrections de revue, empreintes et reçus sont conservés dans les
preuves de cette reprise; ils restent des observations bornées et non une certification globale.
