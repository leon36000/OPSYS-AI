# M10 — preuves courantes du backend mémoire, de l’API et de la console

Date : 2026-09-30. Dépôt : `/workspace/OPSYS-AI-recent`. HEAD `2e56c0d5605dfe575bde9244f38924d5390f2674`; les preuves décrivent l’arbre de travail partagé et ses modifications locales, pas un commit livré.

## Contrats présents

- Le backend de mémoire de développement est `departments/m10-memoire/src/m10_memoire/developpement.py`. Il conserve prompts, plans, décisions, postflights et index de sources dans les maillons canoniques M10. Le scanner est en lecture seule, limité aux fichiers suivis par Git, borné à 500 fichiers, 256 000 octets par fichier et 8 000 000 octets au total. Il exclut secrets/sauvegardes, traite les liens symboliques de façon sûre, détecte la croissance après indexation et garde le chemin Git complet quand le scan part d’un sous-répertoire.
- L’audit `auditer_developpement` est en lecture seule et exige un rôle administrateur ou propriétaire actif. Il borne l’analyse à 5 000 événements, 10 000 relations, 500 sources et 500 constats; la limite de sortie est 1–500. Le rapport indique les troncatures et ne transforme pas un résultat en `done`.
- L’API est définie par `src/opsys/console/memoire_api.py`; son routeur est monté dans `src/opsys/console/application.py`. La console sert la page mémoire et les pages de recherche, scan et audit dans `application.py`/`memoire_ui.py`. Les actions revalident la session/rôle; les écritures exigent CSRF. L’audit HTML ne rend pas le texte des prompts.
- Le CLI est raccordé par `src/opsys/memoire_developpement_cli.py`; il authentifie interactivement l’identité locale et n’accepte pas l’acteur dans les options.
- La route privée `/mcp/contexte/<agentId>` dans `src/opsys/serveur_mcp.py` utilise un jeton distinct du bearer public. La génération OpenClaw refuse le namespace contextuel au modèle. Dans le Core, la configuration active invalide échoue fermée et les appels M3 connus lient le lead ciblé au contexte de l’affaire. Cela ne prouve pas une liaison complète pour tous les outils/classes de C02.

## Preuves exécutées et provenance

Les comptes ci-dessous viennent des JUnit root fournis pour cette intégration; les résultats du rapport auteur sont indiqués séparément. Ils ne constituent pas une exécution CI distante.

| Source | Résultat mesuré | Portée |
|---|---|---|
| `preuves/integration-m10-final.xml` | **908 passés, 0 échec, 0 erreur, 0 skip**, 28,171 s; début `2026-09-30T18:50:36.774529+00:00` | Suite complète M10. Le JUnit compte 22 tests dans `test_developpement.py` et 24 dans `test_memoire_developpement_api.py`. |
| `preuves/ci-console-final.xml` | **61 passés, 0 échec, 0 erreur, 0 skip**, 8,443 s; début `2026-09-30T19:01:15.852474+00:00` | Suite console locale mesurée par root : `tests.test_console` 46, `tests.test_console_finance` 6, `tests.test_ci_departements` 9. Les 46 tests `test_console` incluent trois tests mémoire listés ci-dessous. |
| `m10-fraicheur-audit-resultat.md` | Rapport de l’agent auteur, non recompté comme exécution root | Décrit les corrections du scanner et les parcours ciblés d’audit/fraîcheur. Le compte final root ci-dessus prévaut sur les anciens nombres ou échecs d’intégration cités dans des rapports antérieurs. |

Cas M10 pertinents présents dans le JUnit final :

- `departments.m10-memoire.tests.test_developpement::test_scan_repo_git_est_borne_read_only_et_exclut_secrets_backups_et_donnees`
- `...::test_scan_sous_repertoire_conserve_chemin_git_complet_module_et_fraicheur`
- `...::test_scanner_borne_un_fichier_qui_grossit_apres_indexation`
- `...::test_scanner_refuse_symlink_leaf_vers_fichier_exclu` et `...::test_scanner_refuse_composant_symlink_vers_repertoire_prive`
- `...::test_audit_developpement_borne_authentifie_et_sourcable`
- `...::test_audit_ne_classe_pas_absente_une_cible_valide_hors_fenetre`
- `...::test_audit_signale_postflight_dont_le_plan_est_absent_du_registre`
- `...::test_cli_audit_requiert_auth_interactive_et_retourne_echec_si_partiel`
- `...::test_rendu_audit_console_ne_divulgue_pas_le_texte_des_prompts`
- `departments.m10-memoire.tests.test_memoire_developpement_api::test_audit_http_est_authentifie_strict_borne_et_non_destructif`
- `departments.m10-memoire.tests.test_memoire_developpement_api::test_http_postgresql_persiste_sur_le_stockage_canonique`
- `tests.test_console::test_memoire_console_raccord_api_et_page_sourcée`
- `tests.test_console::test_memoire_console_echappe_recherche_et_refuse_role_retire`
- `tests.test_console::test_audit_memoire_console_rend_le_rapport_sans_contenu_et_revalide_le_role`

Le cas `test_http_postgresql_persiste_sur_le_stockage_canonique` est présent et passé dans le JUnit M10 final. Son code utilise `postgres_ephemere()`; la fixture démarre localement `pgvector/pgvector:pg17` par Docker. C’est une preuve d’écriture/relecture API sur un conteneur PostgreSQL 17 éphémère pendant ce test précis. Ce n’est ni une base distante, ni une instance de production, ni une nouvelle preuve de déploiement. Zéro skip dans le JUnit confirme que la branche de skip « Docker absent » n’a pas été prise pour ce run.

Les trois cas console root donnent un parcours de page/API, l’échappement/retrait de rôle et le rendu de l’audit. La présence de la route et des tests établit le montage dans l’application locale; elle ne prouve pas un parcours complet par un utilisateur en production.

## Limites restantes

- L’audit applique ses plafonds aux lignes qu’il examine, mais `_connexion()` appelle `_connecter()`, qui appelle `_charger_registre()` et relit/reconstruit d’abord le journal canonique complet dans une base SQLite en mémoire. Les limites de 5 000/10 000/500 ne bornent donc pas le coût de cette reconstruction préalable. L’audit n’est pas un scan à coût constant quand le registre canonique grandit.
- L’audit s’exécute à la demande : aucun scheduler, job nocturne ou rappel automatique n’est installé.
- La mémoire de développement et le paquet de préflight ne sont pas une recherche vectorielle/sémantique; aucun système de rappel/retrieval vectoriel, Qdrant, Temporal ou graphe externe n’est prouvé. Aucune mesure de précision/rappel à grande échelle n’est produite.
- Le scanner ne couvre que le périmètre de fichiers suivis par Git qu’il accepte, pas l’ensemble arbitraire du système de fichiers. Les tests locaux n’établissent pas un scan exhaustif du dépôt à l’échelle de production.
- La preuve PostgreSQL est limitée au conteneur local éphémère décrit ci-dessus. Pas de production, de réplication, de concurrence multi-instance ni de restauration PostgreSQL distante. La reconstruction canonique est exercée; les archives de production ne le sont pas.
- Les preuves Core du garde restent limitées aux scénarios de configuration/liaison testés. Elles ne ferment pas la limite C02 générale. Aucun module complet ni intégration réelle n’est revendiqué.

## Empreintes SHA-256 courantes

Empreintes calculées sur les fichiers présents dans l’arbre de travail le 2026-09-30; elles remplacent les anciennes empreintes backend de ce document.

```text
ab727fb4ea39d4133634806801fafd13f96c9ba65c01eb9eddf1493ee12c84a5  src/opsys/serveur_mcp.py
2226942c55198431488656483e136a4117c37e6585ca7e66161303e62754981d  src/opsys/openclaw.py
8a448eab82335402d6b0a5443b23f42600276367ba7165fe086658b77d3dc352  core/src/context-engine/opsys-contexte-config.ts
86b9814d002e799e62acd1928953fef0d5b79cc2823ab044c27614af586296a8  core/src/context-engine/opsys-contexte-mcp.ts
06eddb9bb0754dcafd62b240acb41ee5482c867b2414583f011c7d457a9d68bb  core/src/context-engine/opsys-contexte-garde.ts
778153d3bad575b6d5d90602e3bb35147233bc155c8e464a361d618a444c4c4b  core/src/context-engine/opsys-contexte-config.test.ts
30a664bbad6facb30410768d89b067c4235c959da09cf2657d142cb81b8e30fa  core/src/context-engine/opsys-contexte-garde.test.ts
28ce90f47e17663383039b5850d5af2527b01837340fd4990854d7a530083036  core/src/agents/agent-tools.before-tool-call.opsys-contexte.test.ts
03bba39095118069802871919fd1212bfe276d9e2e26f075649394cbf60442c0  departments/m10-memoire/src/m10_memoire/developpement.py
4c5685250b088a02771e1d734a81f07fb7f4ef4dca5cee20e3947746fa68ce45  departments/m10-memoire/tests/test_developpement.py
bf214d18f58ab5efd34305f350886f9b15c7b5041ce6d10ba12b46eb49322e82  departments/m10-memoire/tests/test_memoire_developpement_api.py
c50b01f94d5da819a3bf286d783daee7660ed3ff177283c51b6b84fbf94b8bcd  tests/test_console.py
4db042543af9b23536b5070113f0f6ab32b4015fde0a318341e32b2eace71404  src/opsys/console/memoire_api.py
729dc637dc37423aeec6d34894880a3980174e20869d03c33f93d142b4f8108e  src/opsys/console/memoire_ui.py
6f1cb2689ef7d76eae8425ada4a53cf0408bddd3d4243c062df817b924e4c7e4  src/opsys/console/application.py
198c1fb06924fe1cbc0c2d096018cc425092cde61135f538dcabdfcd02017ead  src/opsys/console/pages.py
e6ce4d6c52bfee2be1b05a24b756b3984a2ddf814876271d241203c6feb139d5  src/opsys/memoire_developpement_cli.py
1dbf106caa98c9aeb593594ab38e5622cb12623a529f2a2a3e289d79c53fed7a  docs/grs/memory/M10-MEMORY-DEVELOPPEMENT.md
```

Empreintes des preuves de test root :

```text
56a935fba0e8d35d671c6ee31fed3363b9344f5f3d5f52a111f579d7aa5e79fc  /workspace/restructuration-opsys-2026-09-30/preuves/integration-m10-final.xml
2dba0571516b70544b04f624a30b775e8f1574e02af6df556590a83d85d06224  /workspace/restructuration-opsys-2026-09-30/preuves/ci-console-final.xml
76eb58e1b19ad9b6df19bb4a7eb4ae04063e3bb3807a3c2534382ec245387e32  /workspace/restructuration-opsys-2026-09-30/m10-fraicheur-audit-resultat.md
```
