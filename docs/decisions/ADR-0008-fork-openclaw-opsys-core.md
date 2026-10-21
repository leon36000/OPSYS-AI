# ADR-0008 — OpenClaw devient OPSYS-CORE (fork dur) et l'architecture produit s'unifie

- Statut : **Accepté** (ingénieur en chef, mandat du propriétaire du 2026-09-28 : « carte blanche »,
  « utilise openclaw2 comme base », « OpenClaw doit devenir OPSYS-AI », « c'est nous qui ferons les
  mises à jour »).
- Remplace : l'ADR-0007 (OpenClaw épinglé et configuré de l'extérieur) et le point 1 de l'ADR-0006.
- Référence du QUOI : [définition produit](../produit/DEFINITION-PRODUIT.md) (révision 3). Elle tranchait
  « OpenClaw2 ou Hermes Agent » par comparaison documentée (§3) : cet ADR est cette comparaison.

## Contexte

La définition produit (§1, §3) fixe le but : un système d'exploitation d'entreprise, **autonome,
installable sur un VPS**, avec un core construit sur le code source d'OpenClaw2 ou de Hermes Agent,
**lourdement modifié, sans dépendance à leurs mises à jour**. L'ADR-0007 avait fait l'inverse
(consommer l'image officielle d'OpenClaw et la configurer) : c'était une infrastructure IA de plus,
exactement ce que la définition exclut (§1, « Ce qu'OPSYS-AI n'est PAS »).

## Comparatif (mesuré le 2026-09-28 sur les sources)

| Critère (§3) | OpenClaw v2026.9.6 | Hermes Agent (main du 2026-09-27) |
|---|---|---|
| Licence | MIT (© 2026 OpenClaw Foundation) : modification et redistribution commerciale permises, avis à conserver | MIT |
| Taille | 48 575 fichiers ; ≈ 4,3 M lignes TypeScript, 0,45 M Swift, 0,13 M Kotlin | 16 545 fichiers ; ≈ 0,88 M lignes Python, 0,61 M TypeScript |
| Mémoire | paliers, provenance à l'écriture, consolidation « dreaming » à portes déterministes, rappel en 2 voies, index SQLite hybride (FTS5 + sqlite-vec), embedding local GGUF, slots `memory` et `contextEngine` | MEMORY.md/USER.md, recherche FTS5 des sessions, profil utilisateur via Honcho (service externe) |
| Canaux | plus de 40, dont SMS, WhatsApp, Teams, Signal, Slack, Telegram, iMessage, Google Chat | moins nombreux |
| Interfaces | Control UI web, apps iOS/Android/macOS, Windows Hub | TUI, web ; Android via Termux seulement |
| Installation | une commande (macOS, Linux, Windows), service de fond | une commande |
| Multi-modèles | fournisseurs cloud et locaux natifs (Ollama, LM Studio, llama.cpp, compatibles OpenAI) | oui |

Verdict : **OpenClaw**. Les pièces les plus coûteuses à construire (mémoire, canaux, installateurs,
interface web, protocole des appareils) n'existent à ce niveau que chez lui. L'avantage de Hermes (le
Python, comme nos départements) ne compense pas. Hermes sort du projet : l'adaptateur
`hermes_plugin.py` et `profils.py` seront retirés quand le core forké les rendra inutiles.

## Décisions

1. **Fork dur.** La release `v2026.9.6` (tag annoté `ce5bbdc2`, commit `eb377ac5`) est importée en
   instantané dans `core/`, sans historique amont. Ensuite :
   - élagage de ce qu'OPSYS n'utilise pas ;
   - renommage complet : marque, CLI `opsys`, dossier `~/.opsys`, paquets, variables d'environnement ;
   - greffe native des services OPSYS.
   Aucune synchronisation automatique avec l'amont. Une veille mensuelle des avis de sécurité
   d'OpenClaw décide, correctif par correctif, s'il faut le reporter à la main. L'avis MIT et le
   copyright d'OpenClaw sont conservés dans `core/NOTICE`.
2. **Trois couches, une seule installation.**
   - **OPSYS-CORE** (TypeScript, le fork) : passerelle, seul point d'entrée HTTP/WebSocket
     (authentification, appairage des appareils) ; runtime d'agents (un agent par département, plus
     des sous-agents) ; canaux ; mémoire et moteur de contexte ; fournisseurs de modèles ;
     planificateur ; dashboard web (la Control UI étendue).
   - **Moteur métier OPSYS** (Python) : les sources de vérité et les moteurs déterministes des dix
     départements, plus les services partagés de §4 (approbations N0–N5, autorisation, audit, gates,
     notifications, métriques). Le core le lance et le supervise. Il est exposé aux agents par MCP et
     aux interfaces par l'API du core. Pourquoi Python : les briques décisives y sont (OR-Tools et
     PyVRP, SAM2 et OpenCV, Monte Carlo, Docling, DuckDB), et 77 outils déterministes plus
     3 156 tests y existent déjà.
   - **Interfaces** : une app mobile unique à quatre profils et le dashboard web.
3. **App mobile : React Native / Expo, nouvelle app.** L'ancienne « forge-app » est hors d'atteinte :
   les dépôts Forge sont mis de côté. Les apps natives d'OpenClaw sont des compagnons de
   conversation (Swift + Kotlin, deux codes) ; l'app OPSYS est une app métier, hors ligne d'abord.
   On réutilise leur protocole et leur appairage, pas leur code d'interface. Détail de la pile :
   R12.
4. **Modèles.** Les modèles cloud et locaux se configurent dans le dashboard, par les fournisseurs
   natifs du core. Le routage par difficulté (P11) = un modèle par agent de département, plus des
   chaînes de repli. LiteLLM quitte le chemin par défaut : une brique de moins à installer.
5. **Installation.** Une commande, dérivée de l'installateur d'OpenClaw. Elle installe le core,
   puis le moteur métier Python via `uv`, qui fournit son propre Python, puis le service de fond.
   Docker Compose reste une option pour les serveurs.
6. **Données.** Une seule vérité par département (§8), dans la base du moteur métier. Moteur sans
   serveur par défaut, pour s'installer partout ; serveur de base de données pour les grosses
   installations et le SaaS. Choix précis (SQLite ou PostgreSQL, événements, workflows) : ADR-0009,
   après l'étude R13.
7. **Mémoire.** La mémoire native d'OpenClaw est la base de la mémoire des agents. M10 gouverne la
   mémoire d'entreprise (portées, statuts, confidentialité, Loi 25, ordre de vérité) et l'injecte
   par un moteur de contexte OPSYS : la « RAM », une mémoire de travail bornée en tokens et composée
   à chaque tour. Détail : ADR-0010, après l'audit M10.

## Réponses aux points ouverts de la définition (§13)

| Point | Décision |
|---|---|
| 1. Chemins hérités | La numérotation `departments/m01…m10` fait foi. Fait. |
| 4. Nom commercial | Paramètre du profil d'entreprise, jamais codé en dur. « Synergy » ou « Lanaudière » : **à confirmer par Nathan** avant de figer les scripts et les messages. |
| 5. Mémoire « usine » | Hors produit. La mémoire de développement vit dans le dépôt (ADR, docs, plans), pas dans le M10 livré. |
| 6. Ordre de développement | Par tranches verticales rattachées aux flux de §6, pas département par département : voir `docs/programme/PLAN.md`. |
| 7. M2 et M5 existants | Le code Forge est inaccessible et mis de côté. M2 et M5 sont reconstruits dans OPSYS. Les contrats d'API connus (`/api/crm`, `/compta`) sont conservés comme contrats. |
| 9. App mobile | Expo, nouvelle app (décision 3). |
| 10. M6 dépend de M1 | Repli manuel documenté : brouillon de courriel, copie en un geste, confirmation saisie par l'admin. |
| 11. Seuils | Configurables dans le dashboard. Chaque département documente ses valeurs par défaut. |
| 2, 3, 8 | Tranchés dans la définition (numérotation M5.1–M5.20, seconde mention). Portée SaaS de M5 : **à confirmer par Nathan**. |

## Conséquences

- On maintient nous-mêmes un core volumineux. L'élagage est donc la première tâche après
  l'import, et la veille de sécurité est une tâche récurrente du plan.
- Deux runtimes (Node et Python), unifiés par l'installateur, le superviseur du core, une seule
  authentification et une seule base par instance.
- Le bac à sable de développement n'exécute pas le code amont : la construction et les tests du
  core tournent en CI GitHub.
- `core/UPSTREAM.md`, `src/opsys/openclaw.py` (configuration externe) et l'adaptateur Hermes
  deviennent obsolètes à mesure que les greffes natives arrivent. Ils sont retirés quand leur
  remplaçant est testé.
- La licence d'OPSYS lui-même (`LICENSE` Apache-2.0 ou « propriétaire » selon l'ADR-0003) reste une
  **décision de Nathan**. Le fork MIT permet l'une ou l'autre, avis d'OpenClaw conservé.
