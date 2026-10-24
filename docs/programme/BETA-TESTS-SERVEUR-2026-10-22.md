# OPSYS — corrections et bêta-tests des capacités serveur

Instruction de Nathan du 21 octobre 2026 à Montréal, conservée le 22 octobre UTC.
Référence initiale : `54d89d355555ba29c51a05828bb2ee9b8abbfc1d`, PR623 fusionnée.
Ce programme indique le travail et ses critères ; il ne certifie pas son achèvement.

## Cible et ordre

Les ambitions de la [définition produit](../produit/DEFINITION-PRODUIT.md) sont maintenues :
dix départements complets, plusieurs agents configurables, autonomie sous permissions,
mémoire avant/après, sources déterministes et valeur métier mesurée. Le serveur doit pouvoir
s'installer sur VPS Linux sans l'infrastructure personnelle de Nathan ; un serveur dédié est
une alternative à justifier par des mesures. PC1 est une ressource de qualification et de
modèles, pas une dépendance obligatoire du produit livré.

Le mobile est reporté en dernière phase, après les grandes exigences serveur. Les quatre
profils et le fonctionnement hors ligne restent au programme. Windows/macOS ne sont pas requis.

## Premier lot de corrections

- **M6, quantité fractionnaire** : accepter une consommation de `0.1 + 0.2` contre `0.3`
  disponible, refuser une vraie surconsommation sans epsilon, préserver le contrat de sortie,
  le WCT canonique, l'idempotence et l'atomicité SQL.
- **M4, revue humaine** : l'ancien outil de revue ne peut pas exécuter une décision sans
  approbation humaine réelle, même en mode autonome ; l'approbation légitime et les refus
  d'appareil restent vérifiés. Les autres opérations autonomes gardent leur contrat.
- **Agents de base, budgets** : les agents de département doivent utiliser une admission
  réelle avec politiques, réservations et réconciliation d'usage. Le provisionnement et ses
  limites sont explicites ; un identifiant de profil inexistant n'est pas une correction.
  L'usage de tokens ne constitue pas une facture fournisseur.

Une absence de profil dans une installation ancienne doit produire un état de préparation
nommé et une marche à suivre, sans laisser le fournisseur être appelé sans admission.

## Équipe et séparation des rôles

Codex coordonne et vérifie la jonction. Les sous-agents possèdent chacun une surface de code.
Claude Code et LiteLLM/PC1 explorent des scénarios distincts et des entrées difficiles ; leurs
réponses ne décident pas du verdict. Les invariants proviennent des contrats et de références
indépendantes. Les tests existants sont réutilisés lorsqu'ils couvrent réellement la question.

Les rôles QA représentent client entrant, vendeur, employé, manager, finance, administrateur
et propriétaire. Une seconde affaire et une seconde personne servent aux contrôles négatifs.
Un administrateur autorisé à deux affaires ne prouve pas une isolation entre clients ou tenants.

## Parcours à couvrir

| Surface | Parcours et oracles attendus | Ce qui reste distinct |
|---|---|---|
| M1 | Demande, injection, plainte, consentement, transfert, prochaine action ; provenance et refus de faux engagement | Fournisseur SMS/voix réel et qualité audio |
| M2 | Propriétaire du lead, doublon sans fusion arbitraire, segments existants, relance et passage à l'estimation | Calibration commerciale et canaux externes |
| M3 | Prix depuis sources, marges configurées, incertitude, approbation, comparaison estimé/réel | Mesure sur photos réelles et géospatial à qualifier |
| M4 | Cédule, complétion, preuves, revue humaine, cascades et reprises | Capture GPS/caméra sur mobile en phase finale |
| M5 | Brouillons, créances, obligations, rapprochement, absence de cash inventé, droits et refus de doublon | Banque, paie complète et validations professionnelles |
| M6 | Réception, disponibilité, consommation fractionnaire, réservations, variance, coût et rejeu | Fournisseur et commande réellement transmise |
| M7 | Consentement, médias, publication approuvée, retrait et attribution sourcée | Export manuel/dry-run ne vaut pas publication réelle |
| M8 | Métrique et source, fraîcheur, trous de données, droits et absence de zéro inventé | Une corrélation n'est pas une attribution causale |
| M9 | Dossier de décision, citations, contradictions, scénarios, actions autorisées et bilan | Une citation correcte ne suffit pas à prouver un conseil utile |
| M10 | Capture minimisée, affaire, autorité courante, révocation, révision, non-oubli et restitution | Mémoire relationnelle, contexte Core et RAG sont des compositions distinctes |
| Serveur | Installation épinglée, console/Gateway/Python, redémarrage, export/restauration sur instance neuve | CI Linux, PC1 et VPS sont des environnements différents |
| Agents | Outils permis, budget, refus avant fournisseur, latence, qualité et coût observés | Coût proxy estimé, tokens et facture réelle sont distingués |

Pour chaque parcours : état avant, entrée, résultat métier attendu, effets SQL/événements,
refus sans effet, panne/reprise et état après. Les parcours passent progressivement de la
fonction réelle au dispatcher, au transport MCP/Core puis à l'interface serveur réelle.

## Outils existants et décision de réutilisation

**Playwright 1.63.0**, déjà présent dans le Core, fournit une base navigateur sans nouvelle
dépendance produit. Ses agents officiels planner/generator savent explorer puis produire des
tests pour Claude Code et Codex. Les assertions métier, reçus et refus restent sous revue.
Le healer ne doit ni transformer un défaut en skip ni assouplir un invariant pour obtenir du vert.
[Agents officiels](https://playwright.dev/docs/test-agents),
[licence Apache-2.0](https://github.com/microsoft/playwright/blob/v1.63.0/LICENSE).

**Schemathesis** est candidat pour les contrats HTTP OpenAPI et leurs séquences ; il ne déduit
pas à lui seul l'autorité d'une affaire ou le sens métier d'un appel MCP.
[Tests avec état](https://github.com/schemathesis/schemathesis/blob/master/docs/guides/stateful-testing.md),
[licence MIT](https://github.com/schemathesis/schemathesis/blob/master/LICENSE).

**Inspect AI** est candidat pour orchestrer des évaluations d'agents avec limites, traces,
outils et évaluateurs indépendants. Son adoption demande une version épinglée, ses dépendances
et une preuve d'intégration ; aucun résultat Inspect n'est encore revendiqué.
[Documentation](https://inspect.aisi.org.uk/agents.html),
[licence MIT](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/LICENSE).

Browser-use a également été examiné comme explorateur navigateur
([dépôt](https://github.com/browser-use/browser-use),
[licence MIT](https://github.com/browser-use/browser-use/blob/main/LICENSE)). Son ajout n'est
pas nécessaire pour le premier parcours, puisque Playwright est déjà disponible.
La recherche a aussi couvert les ressources GitLab :
[Duo Agent Platform](https://docs.gitlab.com/user/get_started/get_started_agent_platform/),
[QA du projet GitLab](https://gitlab.com/gitlab-org/gitlab/-/tree/master/qa).
Elles n'établissent pas l'existence d'un outil universel déjà adapté aux contrats OPSYS.

## Preuves et clôture

Chaque lancement a une commande et une intention conservées avant exécution, des données QA,
des homes et temporaires privés avant imports, des limites de ressources et un propriétaire
responsable de son terminal et de ses enfants. Réseau isolé pour les tests déterministes ;
appels de modèles explicitement bornés et séparés des effets métier. Les clés ne sont jamais
copiées dans les prompts, arguments de commande ou rapports.

Classer distinctement : défaut reproduit, risque statique, préparation refusée, prérequis
absent, capacité incomplète et résultat non acquis. Conserver les anciens rouges et les
enveloppes inconnues ; ne pas répéter aveuglément une préparation identique. Une limite
d'environnement ne réduit pas la cible produit et ne devient pas un défaut de code.

Une tranche est livrée avec son diff et ses preuves intégrées. Le programme entier ne devient
pas une condition de fusion de chaque correctif ; inversement, une tranche verte ne déclare
pas toutes les grandes exigences atteintes. Aucun déploiement de production ni effet réel
financier, fournisseur ou client n'est induit par ces essais.
