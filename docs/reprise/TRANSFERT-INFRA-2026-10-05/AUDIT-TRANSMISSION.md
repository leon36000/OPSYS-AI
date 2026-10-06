# Audit de conservation et de transmission — ROOT

Date utilisateur : 5 octobre 2026, America/Toronto. L’audit documentaire Luna joint est une lecture de sept sources, pas une qualification de code ou un audit exhaustif. ROOT a vérifié leurs sept SHA avant ajout du lien de transmission dans les directives, puis a contrôlé les points ci-dessous.

| Demande Nathan | Sources durables | Nature |
|---|---|---|
| Petite entreprise dotée des capacités d’une grande | DEFINITION-PRODUIT §1 et §7, DIRECTIVES-NATHAN | Cible officielle, pas capacité globale livrée |
| Dix départements profonds et interconnectés | DEFINITION-PRODUIT sections M1–M10, PERIMETRE-MODULES | Périmètre cible et critères; les états de juin sont historiques |
| Agents avec outils, logiciels et capacités propres au métier | PERIMETRE-MODULES « Contrat d’autonomie », VISION « Architecture » et « Dashboard » | Exigence de capacités qualifiées, pas simple persona/prompts |
| Plusieurs agents, modèles, droits et budgets configurables | DIRECTIVES et PERIMETRE | Cible; un catalogue ou un profil actif n’atteste pas l’exécution |
| Mémoire premium, ingestion massive, assimilation initiale/continue | VISION « Fusion opérationnelle » et « Mémoire premium » | Pipeline gouverné; pas de score d’assimilation inventé |
| Amélioration de l’estimation par les temps/matériaux réels | VISION « Mémoire premium », rapports M3 | Calibration à évaluer sur chantiers distincts, sans confondre minutes-équipe et heures-personnes |
| Avatar 3D audio/vidéo de type NVIDIA ACE | INSTRUCTION-NATHAN et VISION « Interaction par avatar » | Cible; ACE est une candidate, pas dépendance obligatoire ou qualification production |
| Outils photo, géospatial, API et mesure d’exception | VISION « Précision » et M3 dans DEFINITION | Mesures indépendantes, échelle, droits et incertitude requis |
| Installation VPS sans PC personnel obligatoire | DIRECTIVES « Cœur maintenu », VISION « Architecture », install/deploy | Cible autonome; déploiement réel reste à qualifier |
| Briques GitHub/GitLab/littérature avant réécriture | AGENTS, DIRECTIVES, docs/research | Méthode obligatoire sur capacité majeure; licences/version/tests avant adoption |
| Productivité et économie des tokens | AGENTS, DIRECTIVES, PERIMETRE | Contrôles proportionnés; aucune attente obligatoire de trois modèles; gains à mesurer |

## Ce qui est exactement conservé

Le fichier uploadé « Texte collé.txt » correspond octet pour octet à `docs/produit/PROMPT-NATHAN-RECUPERE-2026-10-01.txt` : **16 341 octets**, SHA-256 `e16d45ce779bf1af2030b886daf653400089cbe0527a2220410c0da349fb0419`. Son contenu s’arrête dans M7.8 ROI/attribution. Ce fichier n’est pas la totalité des longs prompts M1/M5/M10 reçus dans le chat. Leurs exigences sont synthétisées dans les documents cible; le nouveau cahier de transmission conserve leur profondeur, sans se déclarer transcription verbatim.

Les précisions réception/avatars/API/mémoire/apprentissage sont conservées dans `INSTRUCTION-NATHAN-2026-10-02.md`, `DIRECTIVES-NATHAN.md` et `VISION-ENTREPRISE-APPRENANTE.md`. Toutes les anciennes conversations, messages non reçus, journaux Claude privés, PC1/PC2 et données de production ne sont pas déclarés archivés. Le texte actuel de Nathan demandant ce transfert est consigné dans le cahier.

## Local et distant

Préparation locale précédente r29 : 357 chemins explicitement conservés, arbre `54ead4f79e853854b37671f8c5751f9f352f27a2`. Dernier parent distant observé : `3f38364284a917239441b86b14e948dbdbaaac6f` (historique, pas HEAD distant fraîchement vérifié). Branche visée : `codex/restructuration-2026-09-30`, PR privée #623, base `claude/opsys-ai-analysis-x4jt87`.

L’environnement cloud ne dispose d’aucune identité GitHub prête. Le nouveau travail n’est pas annoncé poussé. Le pack transmet un snapshot Git complet autonome et un manifeste; les commits de transport synthétiques ne remplacent pas l’historique réel GitHub, qui devra être relu sur l’infra. Ils ne doivent pas être poussés tels quels sur une branche existante.

## Limites des qualifications

Les preuves sont par tranche, données généralement fictives et sources exactes. Les chiffres ne s’additionnent pas entre reprises. Dernière tranche r392 : 225 tests dans sept fichiers complets + Ruff, dont 24 cas de la console M3; scan r393 ciblé 19 chemins, zéro résultat. Build Core complet, CI distante, PostgreSQL du diagnostic M3, fournisseurs réels, avatar complet, précision terrain et gains de tokens ne sont pas certifiés par ce transfert.

## Contrôle complet de l’état préparé

ROOT a comparé les blobs des **43 323 fichiers** de l’arbre r29 à leurs octets dans le dossier de travail : zéro manquant, deux différences. L’une est l’ajout autorisé du lien de transmission dans DIRECTIVES-NATHAN; l’autre est `core/src/state/openclaw-state-db.generated.d.ts`, déclaration générée non intégrée dans r29. Cette dernière est conservée dans `supplements/non-integre/` du pack avec ses empreintes, sans remplacer silencieusement le blob de l’état préparé. La restauration standard conserve r29; le Codex sur l’infra devra requalifier/régénérer et rapprocher ce supplément.

L’inventaire isolé des fichiers non versionnés ne révèle hors des nouveaux documents que le reçu r29 (inclus au transport) et deux archives brutes AVATAR-TTS-RECHERCHE-r1 non retenues. Elles ne sont pas incluses dans le snapshot préparé; la version SAFE2 qualifiée déjà retenue reste dans le dépôt. Les caches, dépendances installées, bases/credentials personnels et objets LFS non versionnés ne sont pas copiés.
