# Directives durables de Nathan — OPSYS-AI

Source : instruction explicite du propriétaire dans la conversation du 30 septembre 2026.
Ce fichier en conserve la synthèse opérationnelle dans le dépôt. Il est destiné à la mémoire
versionnée du projet ; la reprise est publiée dans la [PR privée #623](https://github.com/leon36000/OPSYS-AI/pull/623),
sans fusion ni déploiement.
Il ne prétend pas être déjà ingéré par M10 ni conservé dans la mémoire personnelle d'un modèle.

## Construire à partir de briques existantes

Avant de développer une capacité importante, rechercher ce qui fonctionne déjà dans OPSYS,
puis les dépôts GitHub et GitLab, bibliothèques et protocoles qui peuvent fournir cette capacité.
La réutilisation est le premier chemin à examiner : adapter des composants matures peut économiser
beaucoup de travail. Le chef de projet mène la recherche ; les suggestions de Nathan sont des
candidates, pas une liste fermée.

Qualifier chaque candidate par son code réel, sa licence et celle de ses dépendances/poids,
sa maintenance, ses tests, son coût d'exploitation, son interface et le travail d'adaptation.
Comparer bibliothèque, extraction sous licence, fork, service séparé et développement ciblé.
Décider sur le coût total et le comportement attendu ; ne pas annoncer des heures économisées
sans mesure. Réutiliser l'existant utile avant de remplacer une partie d'OPSYS.

## Cœur maintenu par OPSYS

OPSYS doit être un produit autonome qui s'installe sur un VPS, sans infrastructure personnelle
Forge obligatoire. Le fork OpenClaw présent dans `core/` est la base disponible. Hermes Agent
est une source de composants à examiner, y compris pour la mémoire, les skills et la compression.
Les composants retenus peuvent être profondément adaptés : OPSYS assume leur maintenance future.
Conserver licences, provenance et veille de sécurité ; aucune synchronisation amont automatique.

## Départements profonds, autonomes et interconnectés

Les prompts retransmis sont une exigence de profondeur fonctionnelle, adaptée au dépôt actuel :

- **M1 Front Office IA** : réception et adjointe, omnicanal, vocal, qualification, appels manqués,
  messages vocaux, plaintes, suivi, agenda, transferts avec contexte et liens CRM/finance/mémoire.
- **M5 FinanceCore** : opérations comptables, paie préparatoire Québec/Canada, fiscalité sourcée,
  CPA, réserves et cash libre, contrats/cédule, projections, rentabilité, CFO, décisions d'achat
  de camion/équipement/bâtisse, dette, financement, investissements et stratégie préparatoire.
- **M7 Marketing & Croissance IA** : marque, contenu, social, croissance, réputation, SEO local,
  publicité, attribution et rentabilité, concurrence, marketing local et conseiller CMO.
- **M10 Mémoire & intelligence opérationnelle** : mémoire d'affaires et mémoire du développement,
  séparées par permissions ; événements, sources, prompts, plans, décisions, code, tests, erreurs,
  liens temporels, contexte avant/après action, consolidation, contradictions et évaluations.

M2, M3, M4, M6, M8 et M9 restent des départements complets. Une façade, un outil de démonstration
ou un fichier existant ne remplace pas leur périmètre métier. Les anciens chemins `grs_api/`, les
chiffres de juin et les anciennes routes ne prouvent pas ce qui existe dans ce dépôt de septembre.

## Agents, dashboard et économie

Le dashboard doit permettre de configurer plusieurs agents spécialisés selon les besoins d'un
département : modèle, outils, droits, mémoire, budget, déclencheurs, tâches, limites et escalade.
Les départements communiquent par événements, contrats et contexte autorisé, avec responsabilités
claires et reprise après erreur. Leur autonomie s'exerce dans les permissions accordées.

Économiser les tokens à la conception : calculs et automatisations déterministes, contexte ciblé,
réutilisation des résultats, cache avec isolation et fraîcheur, appels composés, modèles adaptés,
déclenchement sur événement, budgets et limites de tours/retries. Mesurer coûts, qualité et latence
sur des parcours métier. Plusieurs agents disponibles ne signifie pas tous les appeler à chaque tâche.

## Productivité et qualité

Nathan autorise le ménage, la restructuration et la mise à jour des documents et règles devenus
obsolètes ou contre-productifs. La fusion ne dépend pas d'un consensus de trois modèles, d'un
fournisseur extérieur ni d'une attente de validation d'un autre modèle. Une revue supplémentaire
est possible si elle répond à un risque précis ; elle n'est pas une obligation administrative.

Les contrôles techniques sont proportionnés au changement : preuve métier, tests de régression,
autorisations, cohérence, migration et restauration quand elles sont concernées. Documenter ce qui
est implémenté, ce qui est testé, ce qui est démontré en réel et ce qui reste à faire. Ne pas appeler
« complet » une ambition dont les critères de sortie ne sont pas tous prouvés.

La poursuite autonome et la délégation utile sont explicitement autorisées. Depuis cet
environnement cloud, Nathan a demandé d'utiliser les sous-agents GPT-6 Luna disponibles en
remplacement des modèles LiteLLM de PC1. Le chef de projet décide des choix techniques, évite
les demandes de confirmation routinières et reste responsable des contrôles qualité et des
preuves d'intégration. Cette autorisation ne vaut pas autorisation de publication ou d'action
financière réelle.

Les validations humaines demandées dans les prompts restent en vigueur pour l'argent réel,
la paie finale, les déclarations officielles, les engagements légaux, les achats majeurs, les
campagnes payantes et les publications/actions sensibles. Supprimer un contrôle de développement
inutile n'autorise pas une action financière, publique ou irréversible du produit.

Adaptation détaillée : [périmètre des modules](PERIMETRE-MODULES.md).
Décision d'application : [ADR-0012](../decisions/ADR-0012-reutilisation-profondeur-productivite.md).

## Reprise et précisions du 2 octobre 2026 UTC

Nathan confie la reprise du travail d'Opus au chef de projet jusqu'à nouvel avis. La
[nouvelle instruction conservée](INSTRUCTION-NATHAN-2026-10-02.md) exige notamment les avatars
3D audiovisuels par département, l'espace des API/connecteurs, l'estimation photographique et
géospatiale mesurée, l'assimilation initiale et continue des données et les améliorations fondées
sur les chantiers réels. La [vision d'entreprise apprenante](VISION-ENTREPRISE-APPRENANTE.md)
adapte ces exigences au socle existant. Ces documents ne certifient pas leur implémentation.

## Prompt retrouvé le 1er octobre 2026, heure de Toronto

Nathan a retransmis le fichier exact du prompt évoqué dans la conversation. La
[copie originale](PROMPT-NATHAN-RECUPERE-2026-10-01.txt) contient la directive de réutilisation,
de restructuration productive et les exigences détaillées M7 jusqu'au ROI/attribution.
Elle confirme ces décisions; elle n'annule pas les exigences M1, M5, M10 ou les précisions
audio/3D, mémoire et apprentissage reçues séparément. Son état historique Forge/GRS est
adapté au dépôt OPSYS actuel, sans réintroduire ses chemins ni ses statuts de juin comme faits.
La poursuite de l'implémentation et la délégation utile restent autorisées sans confirmations
routinières. Les actions publiques, financières et irréversibles gardent leurs limites explicites.

## Poursuite et consignes aux agents — 5 octobre 2026 UTC

Nathan demande de poursuivre de façon autonome et d’utiliser le prompt engineering. Le
[brief de travail versionné](../programme/BRIEFS-OUVRIERS-2026-10-05.md) traduit cette demande
en consignes courtes : parcours métier, sources exactes, contrats, permissions, preuves et limites.
Les ouvriers préparent des tranches indépendantes; le chef de projet contrôle la jonction réelle,
les droits, les erreurs de reprise et les résultats avant intégration. Une réponse bien formulée
ou un rapport d’agent ne remplace pas une preuve d’exécution.

Cette instruction maintient l’autorisation de poursuite et de délégation utile, sans ajouter
un consensus obligatoire ni une promesse de fonctionnement continu de 24 heures. Les étapes
de publication suivent les autorisations et les accès réellement disponibles de la session.

## Transmission à Codex sur l’infra — 5 octobre 2026, Toronto

Nathan demande un pack complet et un prompt pour reprendre sur son infrastructure connectée à GitHub. Le [cahier consolidé](CAHIER-AMBITIONS-TRANSMISSION-2026-10-05.md) affirme explicitement que chaque département octroie aux agents des capacités/outils/logiciels métier de premier ordre, avec profondeur, autonomie sous permissions et critères mesurables. Le [guide de transmission](../reprise/TRANSFERT-INFRA-2026-10-05/README.md) distingue snapshot local/distant, fichiers originaux/adaptations et ambitions/livraison; il transporte les derniers changements non poussés. Aucun archivage intégral de conversations non reçues, état global terminé ou opération de production n’est induit par ce transfert.

## Corrections et bêta-tests — 21 octobre 2026, Montréal

Après les deux audits indépendants du commit de fusion PR623, Nathan demande de corriger les
constats établis et d'essayer les capacités d'OPSYS avec une équipe de bêta-testeurs composée
de Codex, de ses sous-agents, de Claude Code CLI et des agents LiteLLM de PC1. Ces ressources
peuvent être utilisées après vérification des accès, des budgets et des propriétaires de tests.
Il demande de rechercher les outils existants de test par agents avant d'en construire un.

**L'ambition n'est pas réduite.** Les dix départements profonds, leur autonomie sous permissions,
leurs intégrations, la mémoire, le dashboard et les exigences produit restent la cible à atteindre
et à dépasser par des améliorations démontrées. Une première tranche utilisable ne remplace pas
cette cible. Les refus corrects et les exports manuels sont des replis, pas la livraison des
connecteurs ou capacités avancées encore absents.

**Ordre de réalisation précisé : serveur Linux d'abord ; application mobile en dernière phase**,
après les grandes exigences OPSYS. Cette priorité remplace le calendrier historique « mobile
d'abord », sans supprimer les quatre profils, le fonctionnement hors ligne ou les exigences
terrain du produit. VPS Linux prioritaire ; serveur dédié Linux si les contraintes mesurées le
justifient. Windows et macOS ne sont pas des conditions requises de livraison.

Les essais doivent conserver leurs entrées, oracles, effets, refus et reprises : une proposition
de scénario par un modèle n'est pas une exécution, et un navigateur qui ouvre une page ne prouve
pas son workflow métier. Les données restent fictives dans les bases QA. Aucun achat,
déploiement de production, envoi sensible ou mouvement financier réel n'est autorisé par cette
campagne. Le [programme de bêta-tests serveur](../programme/BETA-TESTS-SERVEUR-2026-10-22.md)
précise les parcours et les critères de preuve.
