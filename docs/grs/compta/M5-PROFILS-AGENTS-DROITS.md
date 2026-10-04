# M5 — autorisation CFO des profils d’agents

Actualisé le 1er octobre 2026 UTC. Le raccord donne accès à deux rapports préparatoires; le département CFO complet et son déploiement restent à démontrer. M5.10.a étend facultativement l'outil de décision capital déjà dans cette liste, sans ajouter de droit, rôle, outil financier ni action.

## Accès livré

Un profil actif `m05-financecore` peut appeler `m5_preparer_dossier_decision_cfo` ou `m5_preparer_decision_capital` si une personne active `admin` ou `nathan_owner` lui accorde ce droit dans la console. Chaque outil doit déjà figurer dans la liste du profil. Une liste vide est refusée. Activation, budget de tokens et permission financière sont trois contrôles distincts; aucun rôle humain ni droit N4/N5 n’est attribué à l’agent.

L’audit initial constatait le refus du dossier CFO pour les agents et une voie capital sans identité acceptant un argument de permission. Le serveur MCP refuse désormais ces deux outils sans identité humaine valide ou ticket CFO privé. Les parcours humains console/appareil gardent leurs propres contrôles.

## Configuration

1. Utiliser une instance SQLite migrée jusqu’à `0014`; les essais n’ont migré aucune base métier réelle.
2. Créer/ouvrir un profil M5, choisir ses outils et plafonds de tokens, puis l’activer.
3. Avec une session admin/propriétaire, ouvrir **Lecture CFO préparatoire**, choisir les outils, les dates de rapport, la limite quotidienne et l’expiration, puis accorder le droit.
4. Exporter/régénérer la configuration Core par le parcours existant. Le générateur inscrit `opsysRuntimeAdmission.profileId` et `profileRevision`; une ancienne configuration sans révision ne peut pas obtenir un ticket CFO.
5. Révoquer dans la même section pour retirer l’accès. Toute nouvelle révision du profil l’invalide aussi : renouveler explicitement le droit et régénérer la configuration.

Les routes sont `POST /agents/{id}/droit-cfo` et `POST /agents/{id}/droit-cfo/retrait`, sous le montage habituel `/opsys`. Session, rôle actif et CSRF sont revérifiés; révision du profil et version du droit refusent les formulaires périmés. Le renouvellement préremplit les valeurs courantes.

| Limite | Comportement |
|---|---|
| Quota quotidien | 1 à 20, défaut 3; compte les **tickets émis**, même inutilisés/expirés, par agent et jour UTC. Le renouvellement ne remet pas ce compte à zéro. |
| Concurrence | Un ticket non expiré disponible pour le droit courant. |
| Expiration du droit | Défaut 30 jours; maximum 90 jours. |
| Dates du rapport | Intervalle ordonné d’au plus 90 jours; vérifie l’argument `aujourd_hui`. |
| Ticket | Durée 90 secondes; un ticket consommé est refusé même avec les mêmes arguments. |

**Les dates de rapport ne filtrent pas les lignes historiques des livres.** Les sources financières restent celles de l’instance entière, avec des mouvements qui peuvent être plus anciens. Il n’y a pas de cloisonnement SaaS par entreprise/client certifié.

## Parcours et stockage

Le Core reconnaît ces deux outils du serveur `opsys_m5` et la session du profil généré. Il fige les arguments JSON finaux puis appelle `opsys_runtime_cfo_ticket` sur `/mcp/runtime/<profile-id>`, avec le bearer privé de cette route. Le ticket est transmis à `/mcp/m05-financecore` dans `_meta["opsys/cfoGrantTicket"]`, hors des arguments accessibles au modèle. Le Core refuse une réponse d’émetteur invalide/expirée et borne cet appel privé à dix secondes.

La base conserve les empreintes du ticket opaque et des arguments, l’outil, l’instance, la révision du profil, la version du droit et les dates. À l’émission puis à la consommation, le backend revérifie profil actif M5, outils, révision, instance, droit/échéance, autorité toujours active de l’émetteur humain et date de rapport. Avant la lecture financière, il consomme le ticket par modification conditionnelle `available → consumed`, dans la transaction SQLite qui capture les sources. Un changement de droit/profil après émission bloque la lecture; aucun résultat de rejeu idempotent n’est livré.

Les quatre tables de migration `0013 → 0014` sont `opsys_instance`, `agents_grants_cfo`, `agents_grants_cfo_historique` et `agents_tickets_cfo`. Les octrois, renouvellements et retraits gardent auteur, rôle, version et instantané. Le downgrade est refusé pour conserver ces traces. L’UUID d’instance est durable dans la base.

| Fonction | Sources |
|---|---|
| Autorité, quota, ticket | `src/opsys/agent_cfo_grants.py`, `contexte.py`, `serveur_mcp.py` |
| Console/génération | `src/opsys/console/agents_ui.py`, `application.py`, `src/opsys/openclaw.py` |
| Tables/migration | `src/opsys/stockage/schema.py`, `migrations/versions/0014_grants_lecture_cfo_agents.py` |
| Consommation et lecture | `departments/m05-financecore/src/m5_financecore/outils.py` |
| Core | `core/src/agents/opsys-cfo-grant-ticket.ts`, `agent-bundle-mcp-runtime.ts`, `core/src/config/types.agents.ts`, `zod-schema.agent-runtime.ts` |

Le dossier CFO contrôle les chaînes `principal`, `factures` et `comptes_a_payer` avant calcul. Leur empreinte non signée ne protège pas d’une réécriture cohérente par un opérateur SQL privilégié.

## Preuves locales

Les [archives R20](../../research/R20-2026-10-01/README.md), en cours de collecte, distinguent prototypes et intégration active. Ces suites se recoupent et ne s’additionnent pas.

- Backend scratch final : 28 tests, dont restauration d’une base migrée conservant profil, droit actif, historique et ticket utilisable; le ticket restauré est ensuite consommé.
- Console active et générateur : **4 réussites**, aucun échec/skip, 2,424 s. Admin/propriétaire, octroi limité, retrait, formulaire périmé, CSRF, employé et retrait de rôle après lecture de requête. Le RED préalable et la reprise intermédiaire avec fixture de révision périmée sont conservés.
- Core actif via le routage normal `pnpm --dir core test` : **12 réussites** dans deux fichiers, dont serveur Python HTTP local, handler M5 canonique, rapport accepté de 25 rubriques et refus d’une révision périmée. Aucun appel réel à un fournisseur LLM.
- Historique du premier raccord des droits, avant M5.10.a : FinanceCore actif **2 028 réussites**, aucun échec/erreur/skip, 117,113 s. Les commandes Core/M5/console de cette campagne contrôlaient 1 034 sources sélectionnées, inchangées avant/après. Ce résultat ne s'ajoute pas à la campagne intégrée suivante.
- Vérification intégrée actuelle après M5.10.a : **2 037 tests M5 + 34 tests du socle = 2 071 tests** dans une seule commande, 0 échec, 0 erreur, 0 skip, 134,333 s JUnit. Les 1 029 sources sélectionnées sont identiques avant/après. JUnit : [m5-scenarios-integres-root-r1-2026-10-01.xml](../../research/R20-2026-10-01/preuves/m5-scenarios-integres-root-r1-2026-10-01.xml.gz); [résultat et métadonnées](../../research/R20-2026-10-01/preuves/m5-scenarios-integres-root-r1-2026-10-01-resultat.json.gz). Les 34 tests socle sont inclus dans 2 071; les anciennes preuves 2 028 et les suites 4/4, 12/12 ou 15/15 ne s'y additionnent pas.

Référence backend : `tests/test_agent_cfo_grants.py`, `test_console_agent_cfo_grants.py`, `test_openclaw_profils.py` et les tests M5. La passe complète du socle après raccord (`socle-cfo-integre-root-r3-2026-10-01`) se termine avec **2 282 réussites, trois échecs, 35 erreurs et 83 skips**, sur 2 403 cas, en 1 743,215 s; les 1 034 sources contrôlées restent identiques. Deux fixtures étaient périmées : chemin du helper CFO et liste des outils runtime. Après leur correction, les cinq fichiers concernés passent **45/45**, sans erreur ni skip, en 13,691 s JUnit (`cfo-raccord-fixtures-root-r4-2026-10-01`); ce ciblé ne remplace pas une reprise complète.

Les 36 autres cas avaient rencontré quatre démarrages PostgreSQL terminés avec le code 1. Leurs logs ont été perdus par `docker run --rm`; la pression disque/VFS est une hypothèse, pas une cause établie. La fixture conserve désormais l'état et les deux flux du journal avant nettoyage, y compris lors d'une création partielle. Après intégration, `postgres-fixture-cas-affectes-root-r1-2026-10-01` passe **47/47**, sans erreur ni skip, en 20,426 s JUnit. La comparaison des identifiants JUnit confirme que les **36 anciens cas affectés** sont tous présents et réussis. Cette reprise ciblée ne remplace pas la suite complète. Une vérification supplémentaire du hook Core partagé avait donné 8/9 : l'ancien test `_meta` omettait personne/rôle. Sa fixture est corrigée sans assouplir la garde de production; la passe élargie des 158 fichiers CI reste en cours. Ruff global passe après une correction d'ordre d'import.

## Limites restantes

- **SQLite uniquement** : opérations de droit et tickets refusées hors SQLite; concurrence PostgreSQL non qualifiée.
- Instance entière, sans isolation SaaS démontrée. Un clone de la base conserve son UUID. Restaurer une sauvegarde ancienne peut ressusciter un ticket encore valide : le test de restauration ne prouve pas l’absence de rejeu entre copies/sauvegardes.
- Le bearer métier partagé est réservé au Core/opérateur. Un détenteur peut fabriquer des métadonnées humaines, qui ne sont pas des attestations cryptographiques. Le chemin agent inspecté ne lui distribue pas cette clé; la frontière OS/Docker réelle reste à démontrer (C01 partiel).
- La révision lie le droit au profil stocké; elle n’atteste pas le modèle/fournisseur réel d’un client ayant altéré sa configuration.
- Le quota de tickets n’est pas un plafond financier exact ni une admission générale de tous les appels LLM.
- Aucun paiement, écriture finale, paie, déclaration, campagne payante ou achat n’est autorisé. Les rapports gardent leurs inconnues et validations professionnelles; les capacités M5.1–20 restent à compléter selon leurs preuves propres.
