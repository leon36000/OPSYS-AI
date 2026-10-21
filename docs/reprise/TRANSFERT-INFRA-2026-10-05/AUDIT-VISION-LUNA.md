# Audit de transfert — vision produit OPSYS-AI

Périmètre : lecture des sept fichiers demandés dans `/workspace/OPSYS-AI-recent`. Constat limité à ce corpus documentaire ; aucune inspection de code ni vérification d’exécution. Les documents expriment une ambition et des critères, pas une preuve de livraison.

## Conclusions par thème

- **Profondeur M1–M10 — exigence explicite.** `DIRECTIVES-NATHAN.md` § « Départements profonds… » détaille M1, M5, M7, M10 et affirme que M2, M3, M4, M6, M8 et M9 restent des départements complets. `DEFINITION-PRODUIT.md` §7 définit les dix départements et leurs preuves de complétion. `PERIMETRE-MODULES.md` décline plusieurs capacités vérifiables (notamment M1 §M1.1–M1.20 et M10 §M10.1–M10.15). Ce sont les périmètres cibles, non une affirmation que tout est livré.
- **Agents, modèles, outils spécialisés — exigence explicite, livraison non établie.** `DIRECTIVES-NATHAN.md` § « Agents, dashboard et économie » demande plusieurs agents configurables par département, chacun avec modèle, outils, droits, mémoire, budget et limites. `INSTRUCTION-NATHAN-2026-10-02.md` demande des capacités et outils de premier ordre adaptés au métier. La vision § « Architecture retenue » précise configuration par responsabilité, modèle, budget et autorisation. Cela n’impose pas un consensus de plusieurs modèles : AGENTS.md et les directives rejettent le consensus obligatoire de trois modèles.
- **Mémoire premium, ingestion massive, apprentissage — ambition explicite avec nuances.** L’instruction du 2 octobre demande une « mémoire premium », ingestion massive classée et apprentissage initial puis continu. `VISION-ENTREPRISE-APPRENANTE.md` § « Fusion opérationnelle » et § « Mémoire premium et apprentissage » traduit cela en pipeline gouverné, mesures et calibration; elle précise que l’ingestion massive et la note générale d’assimilation ne sont pas prouvées par les lots cités (R21–R25). `DEFINITION-PRODUIT.md` §7.10 exige une mémoire gouvernée et évaluable; le « premium » ne signifie pas abonnement premium obligatoire. La profondeur M10 est un objectif, pas un état certifié.
- **Avatar audio/3D — exigence explicite, non livré selon la vision.** L’instruction le demande par avatar audiovisuel de type NVIDIA ACE. Vision § « Interaction par avatar » définit le parcours multimodal, mais dit que GPU/ACE est une option et qu’aucune dépendance, clé NGC ou licence n’est installée par cette décision.
- **Autonomie sur VPS — exigence explicite, livrabilité conditionnelle.** `DIRECTIVES-NATHAN.md` § « Cœur maintenu par OPSYS » exige un produit autonome installable sur VPS sans infrastructure personnelle obligatoire. La vision § « Architecture retenue » rend les ressources GPU optionnelles et autorisées. `DEFINITION-PRODUIT.md` §9 et §14 documente VPS et sécurité de conception; cela ne prouve pas un déploiement opérationnel.
- **Économie des tokens — exigence explicite.** Directives § « Agents… » demande contexte ciblé, résultats réutilisés, cache isolé/frais, modèles adaptés, appels composés, budgets et mesure coûts/qualité/latence. `DEFINITION-PRODUIT.md` §7.10 confirme les paquets en couches pour économiser les tokens.
- **Recherche GitHub/GitLab — exigence de méthode explicite, résultats non présumés.** `AGENTS.md` § « Briques open source » exige d’inspecter GitHub et GitLab pour les capacités importantes. `DIRECTIVES-NATHAN.md` § « Construire à partir… » exige qualification licence, maintenance, tests et coût. `VISION-ENTREPRISE-APPRENANTE.md` § « Critères communs » rappelle qu’une recherche seule ne vaut pas adoption. Le prompt retrouvé (début) confirme cette préférence; ses suggestions ne sont pas une liste de briques adoptées.

## Indications d’état

`DEFINITION-PRODUIT.md` §7 contient des « états connus » historiques ; §7.1–7.10 et §8.14 séparent état observé, cible et preuve de complétion. Plusieurs mentions anciennes `STUB` sont explicitement datées/historiques, pas un inventaire courant. `PERIMETRE-MODULES.md` avertit dès l’introduction que ses capacités décrivent la cible et que l’état initial est historique. La vision (§ introduction et § Dashboard) dit elle-même ne pas certifier de capacité nouvelle et nomme connecteurs comptables, vision métrique, géospatial de mesure et avatar comme restant à construire à la date de sa rédaction. Aucune conclusion ici ne promet la conservation de tout historique absent : l’instruction source reconnaît que le message antérieur n’est pas récupéré; le prompt du 1er octobre est une copie retransmise et adaptée au dépôt.

## Fichiers lus et SHA-256

- `AGENTS.md` — `2cd33157c33a8c75cde4d83c10b4180224fb365bbd1ebb69427a17eb03350cc1`
- `docs/produit/DIRECTIVES-NATHAN.md` — `65a284812aadeee8684717a052b567769a86c297c230dc09a52550f218bba2a3`
- `docs/produit/DEFINITION-PRODUIT.md` — `187205e887aecc6e7f127581b7ece1fed44d92b0e48528fb8bfbfad163d6cd98`
- `docs/produit/PERIMETRE-MODULES.md` — `4159e03692d46d93d0472873741a2d0c1a32cc61f8a1898a0688c475a0fe78ae`
- `docs/produit/VISION-ENTREPRISE-APPRENANTE.md` — `88e7824afe178a89a5158600cccc475ca208cd7ad069ade2b7a059f16fb14e73`
- `docs/produit/INSTRUCTION-NATHAN-2026-10-02.md` — `4bb25ea62d9fcd336d4f32fd6b056b085559d3b5beab11066961ae8dd3b7acf7`
- `docs/produit/PROMPT-NATHAN-RECUPERE-2026-10-01.txt` — `e16d45ce779bf1af2030b886daf653400089cbe0527a2220410c0da349fb0419`
