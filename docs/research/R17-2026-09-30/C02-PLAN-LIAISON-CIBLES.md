# C02 — plan initial et critères de vérification

Ce document conserve le plan initial de la tranche M2/M3. Nathan a autorisé sa mise en œuvre
autonome dans la conversation du 30 septembre 2026; les décisions ci-dessous ont été examinées
et l'implémentation est en cours de vérification. Elles ne constituent plus une demande
d'approbation préalable. Les instructions actuelles sont conservées dans
[DIRECTIVES-NATHAN](../../produit/DIRECTIVES-NATHAN.md).

Le périmètre reste celui de [C02-DESIGN-LIAISON-CIBLES](C02-DESIGN-LIAISON-CIBLES.md).
Le ticket opaque, la revalidation transactionnelle Python, le scellement aux demandes
d'approbation et la révocation humaine authentifiée ont été retenus. La première tranche
transactionnelle est limitée à SQLite; PostgreSQL reste refusé pour ces tickets tant que son
verrouillage n'est pas prouvé. Ce plan ne certifie ni les tests en cours ni la liste C02 complète.

## Décisions requises avant le premier patch

1. Confirmer que l’autorité finale est le dispatcher Python dans la transaction métier; une lecture Core→Python au preflight ne compte que comme refus anticipé.
2. Choisir la preuve hors arguments modèle : assertion signée vérifiable par le service ou autorisation opaque à usage unique émise par la voie privée et consommée dans la base d’instance. Préférence proposée : autorisation opaque émise uniquement par le service privé puis liée au hash des arguments et consommée dans la transaction, car le Core n’a pas actuellement de signature métier persistante et le rejeu doit être contrôlé. Réutiliser le transport `_meta` et la base existante; n’ajouter ni service de données ni base métier parallèle. Fixer durée, liaison au `toolName`, arguments finaux, profil/agent et sortie de refus avant le code.
3. Décider si les requêtes `en_attente_approbation` conservent le pointeur privé d’autorisation et le revalident à l’approbation. À défaut, ne pas activer la liaison de cibles pour les actions différées.
4. Valider le sens des opportunités M10 : un lead parent seul ne vaut jamais l’opportunité `<lead>~opp~<wct>`. N’autoriser une action M3 pour une opportunité que si un lien canonique explicite devis/chantier/WCT prouve le même WCT; sinon rester bloqué.
5. Valider l’opération de révocation M10 et son écran/canal humain : association active visée par `ligne_id`, précondition compare-and-set, acteur actif `admin` ou propriétaire, motif, heure serveur, historique conservé. Confirmer si l’outillage M10 N3 exige une demande d’approbation par le socle ou peut s’exécuter comme une commande console humaine vérifiée.

## Séquence proposée

| Étape | Fichiers candidats (à confirmer avec leurs propriétaires) | Travail et critère d’arrêt |
|---|---|---|
| **1 — Contrat d’exécution Core** | `core/src/context-engine/opsys-contexte-engine.ts`, `opsys-contexte-mcp.ts`, `opsys-contexte-config.ts`, `opsys-contexte-garde.ts`; `core/src/agents/agent-tools.before-tool-call.policy.ts`, `agent-tool-definition-adapter.ts`, `agent-bundle-mcp-runtime.ts` et leurs tests | Décrire un contexte frais de la session dans l’appel contrôlé; préserver l’origine privée de contexte; attacher une preuve aux arguments finaux après les politiques trusted. Conserver le blocage actuel pour tout nom absent du contrat. Échec/absence d’assertion privée doit bloquer la mutation. Aucun argument d’outil, texte de requête, output du modèle ou ID seul ne forge cette preuve. **Arrêt si le runtime n’offre pas de seam fiable entre le hook approuvé et `callTool`.** |
| **2 — Parseur privé et consommation transactionnelle** | `src/opsys/serveur_mcp.py`, `src/opsys/contexte.py`, `src/opsys/capacites.py`, `src/opsys/idempotence.py`, tests `tests/test_contexte.py`, `tests/test_capacites.py`, tests MCP correspondants | Ajouter le seul transport de preuve approuvé (ex. `_meta` dédié), vérifier format, origine, durée, hash outil/arguments, périmètre d’agent et rejeu; installer les données validées dans un `ContextVar` à portée de l’appel. La validation finale est appelée dans la même transaction que l’outil, et consomme le ticket une seule fois. Les réponses métier de refus n’écrivent rien. N’autoriser aucun client public à forger ces métadonnées avec les arguments JSON. |
| **3 — Résolveur M2 `lead_id`** | `departments/m02-revenue-crm/src/m2_revenue_crm/outils.py` et modules métier appelés; tests `test_statuts.py`, `test_reassignation.py`, `test_relances_outils.py`, `test_outils_agent.py`, `test_consentements.py`, `test_acces_appareil.py` | Ajouter un résolveur partagé read-only dans le registre M2 existant, exécuté dans la transaction courante; connecter uniquement les six mutations du design. Vérifier que le lead existe, que son état est recevable selon le contrat existant et que son identité M10 est exactement `lead`. Ne pas déduire une opportunité depuis le préfixe du lead. L’ingestion, doublons, batch, autres rôles/appareils restent inchangés/bloqués par C02. |
| **4 — Résolveur M3 `devis_id` et cohérence croisée** | `departments/m03-estimation/src/m3_estimation/outils.py`, `devis_durable.py`; lecture M2/M10 par API métier interne; tests `test_devis_durable.py`, `test_envoi_devis_capacites.py`, `test_devis_accepte_duree_estimee.py`, tests M2 `test_consommer_devis_accepte.py` | Résoudre l’état courant du devis par la source durable existante. Comparer son `lead_id` avec un lead canonique M2 et l’affaire courante; valider aussi le chantier/WCT quand le record fournit ces références. Pour `m3_marquer_devis_accepte`, aucune transition ni publication bus si le dossier est absent, ambigu, non joint, fermé de manière incompatible ou si un autre devis a déjà converti le lead. Pour l’envoi, le resolver précède la création d’approbation et est rejoué juste avant mutation après approbation. Laisser `m3_creer_devis` et les autres cibles bloquées. |
| **5 — Révocation append-only** | `departments/m10-memoire/src/m10_memoire/liaison.py`, `outils.py`, `tests/test_liaison.py`, surface console humaine existante si retenue; éventuellement `src/opsys/approbations.py` selon décision 5 | Ajouter le tombstone et le calcul du lien actif; la révocation nomme exactement `cle_session` + `ligne_id` actif attendu et échoue si une liaison concurrente l’a remplacé. Vérifier rôle, personne active, source humaine, motif et horodatage serveur; garder les anciens maillons intacts. Au dispatcher, comparer le lien live à l’affaire revendiquée. Sans extension de console/device autorisée, le resolver M10 reste une capacité service et le propriétaire doit fournir la voie humaine avant de dire révocation disponible. |
| **6 — Intégration et contrat généré** | `src/opsys/openclaw.py`, tests `tests/test_openclaw_contexte.py`, `core/src/context-engine/opsys-contexte-config.test.ts`, éventuelles migrations ciblées | Projeter uniquement les identités/résolveurs des outils explicitement raccordés, conserver `inconnue` pour tous les autres. Valider que les agents, levels et context servers générés déterminent la même politique. Faire cette étape après accord sur les extensions du type `Outil` et du fichier `contexte.json`; ne pas déclarer batch ou multi-cible globale. |

## Cas négatifs obligatoires avant activation

### Core, identité et transport

- aucune configuration, configuration inactive, agent hors liste : mêmes règles de transparence documentées; config active invalide, serveur privé absent, contexte périmé ou liaison session inconnue : refus sans appel métier;
- agent/session manquants, agent appartenant à un autre département, appel au serveur M10 avec jeton MCP public, appel au serveur privé avec mauvais agent/origine ou rôle absent : refus;
- métadonnée de preuve absente, falsifiée, expirée, consommée, issue pour un autre outil/profil/session, argument changé après mutation par une policy trusted, ou paramètre ajouté par le modèle : refus sans écriture;
- deux appels concurrents consomment la même preuve : au plus un atteint le dispatcher métier. Rejeu de réponse réseau n’applique aucune mutation seconde; prouver la réponse idempotente ou documenter un refus de rejeu déterministe.

### M2 / M3 et jointure canonique

- M2 : lead exact valide autorisé; ID inconnu, lead d’une autre affaire, contexte lead différent, parent fourni pour une opportunité, opportunité inconnue ou lead déjà incompatible avec transition métier : refus sans nouveau maillon/event;
- M3 : devis inconnu, devis appartenant à un autre lead, lead absent de M2, record devis corrompu/incomplet, chantier/WCT rattaché à une autre affaire, références redondantes discordantes : refus avant changement de statut, événement bus ou demande d’approbation;
- devis accepté : lead existant mais non qualifié, lead clos incompatible, lead déjà converti par un devis différent, WCT/affaire-opportunité seulement supposé depuis le préfixe : refus ou résultat d’ignorance métier existant, jamais acceptation fausse;
- devis N4/N5 en attente : approbation humaine possible, mais changement/révocation du lead, du devis, du chantier/WCT ou de la liaison session avant le clic d’approbation invalide l’autorisation exécutée; aucun appel d’exécution avec l’ancienne preuve.

### M10 révocation et courses

- personne inconnue/inactive, rôle non autorisé, motif vide, session `agent:<id>:main`, clé de session mal formée ou session étrangère : aucune écriture;
- révocation d’une liaison inexistante, déjà révoquée ou dont `ligne_id` n’est plus courant : refus et historique intact;
- nouvelle association concurrente : le tombstone basé sur l’ancien `ligne_id` ne retire pas la nouvelle; une révocation confirmée devient `lie: false` à la lecture suivante;
- mutation déjà au preflight lorsqu’une révocation est écrite : dispatcher relit le journal dans sa transaction, bloque l’exécution sur ancienne affaire, et ne publie aucun événement métier;
- aucune fuite de session, identifiant de contact ou lien privé dans les journaux non protégés, prompts, `details` visibles au modèle ou catalogues d’outils.

## Preuve attendue pour une revue de fermeture

1. Tests unitaires de chaque résolveur canonique et des règles lead/opportunité/devis; tests déterministes qui comparent le journal avant/après tous les refus.
2. Tests Core du vrai `runBeforeToolCallHook` et du call adapter/runtime, avec la métadonnée de preuve absente, altérée, finale après policies et rejouée; pas seulement des tests de fonction pure `evaluateGuard`.
3. Tests Python sur le serveur MCP privé/public et une base SQLite/PostgreSQL de test existante : ticket émis côté privé, ticket consommé au dispatcher dans la même transaction que M2/M3, rollback de l’ensemble, relecture M10 après révocation, compétition/rejeu.
4. Parcours approbation : demande créée, cible changée ou liaison révoquée, puis tentative d’approbation; prouver que l’action est refusée et qu’aucun état métier n’a changé. Parcours positif : M2 lead confirmé; M3 devis d’un lead confirmé; signature approbateur conforme; un seul maillon/event attendu.
5. Génération de configuration : seules les mutations unitaires retenues changent de `inconnue` à résolues; les double-cibles, batchs, multi-cas et autres départements sont encore bloqués. Relecture du diff, des tests modifiés et des preuves, sans réclamer de validation d’intégration réelle au-delà des environnements effectivement utilisés.

## Hors périmètre

Aucun déblocage des outils des huit autres catégories C02, aucune autorisation large par nom de champ, aucune identité de cible portée dans les arguments publics, aucune ouverture de route MCP privée aux agents, aucun changement des rôles ou niveaux d’approbation, aucune correction du chemin M1→lead, aucune preuve de production/PostgreSQL distant, CI distante, Docker ou publication. La fermeture C02 globale reste hors de portée tant que les batchs et relations restantes sont bloqués ou n’ont pas de contrat séparé.
