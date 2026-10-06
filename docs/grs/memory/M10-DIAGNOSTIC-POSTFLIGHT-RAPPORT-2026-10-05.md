# M10 — diagnostic opérateur du postflight

5 octobre 2026 UTC, ROOT; design puis revue Luna en lecture seule. Périmètre **qualifié localement**, M10/OPSYS-AI global **PARTIEL**.

## Résultat et commande

Le Core expose désormais dans ses sources `opsys database postflight --agent-id <id> [--json]`. Utiliser l’identifiant canonique exact de l’agent configuré, sur l’hôte Core et son environnement de stockage. Après construction/qualification de la release correspondante :

```bash
opsys database postflight --agent-id m03-estimation --json
opsys database postflight --agent-id m03-estimation
```

La commande montre intentions incertaines, lots pending/retry, révision humaine requise, échéances et capacité partagée. Aucun appel MCP/LLM, envoi, rejeu métier, purge, réparation, acquittement, création ou migration. Ce n’est pas une route du dashboard; la console Python n’ouvre pas la base Core. L’accès repose sur les permissions locales du système d’exploitation. Le refus `OPENCLAW_SHELL=exec` exclut le chemin shell marqué d’un agent; il n’établit pas un sandbox contre un processus local capable de changer son environnement. Ne pas ajouter cette commande au catalogue d’outils des modèles.

## Audit et propriétaire existant réutilisé

Les fonctions list de la façade outbox empruntent une admission d’écriture et `ensureSchema`; la liste normale fait vieillir les lots. Elles ne convenaient pas à un diagnostic sans mutation. L’ouverture fraîche canonique `openclaw-agent-db-readonly-open.ts` permet déjà de lire une base existante avec contrôle de version et d’owner sans rejoindre son lifecycle writable. Le groupe CLI `database` a déjà un bootstrap passif sans plugins. Ces deux briques existantes ont été réutilisées, sans dépendance nouvelle.

Le propriétaire des contrats reste `core/src/agents/harness/opsys-postflight-outbox.worker.ts`; son export diagnostique réutilise les décodeurs fermés et quotas. La CLI ne possède ni seconde définition SQL ni parser Python parallèle. L’enregistrement différé garde l’aide indépendante des opérations, vérifié par le test d’import.

Une transaction de lecture `BEGIN` fixe les deux tables au même instantané. Mesures sur sous-requêtes limitées à 257 lignes avant allocation des payloads, puis refus si total dépasse 256 slots ou 1 Mio réservé. Une intention réserve 4096 octets, distincts du poids de son seul JSON. Les lectures de lignes sont elles aussi limitées. Les agrégats Kysely évitent du SQL brut typé; seules les commandes de transaction ont une annotation locale justifiée. Aucune extension d’allowlist.

## Interprétation et confidentialité

- `uncertain` : réservation avant RPC; exécution et résultat inconnus, y compris crash avant dispatch. Ce n’est ni succès, ni refus, ni autorisation de relancer.
- `pending`/`retry` et `attemptCount` concernent la **remise à M10**, pas le devis ni le nombre d’effets source. Après ACK exact, le lot disparaît : cette vue n’est pas un historique ou un taux de réussite.
- `dueForDelivery` et le compteur `due` indiquent seulement une échéance locale sans revue requise. La livraison doit encore qualifier le profil/révision/département, la cible et l’autorité actuelle. Aucune permission déduite de ce champ.
- `reviewRequired` peut être vrai sur un lot durable encore pending/retry devenu trop ancien : le diagnostic ne change pas son état, ne clôture pas une intention et ne libère pas son quota.
- Base absente, owner/schema incomplet, tables additives absentes/partielles, données invalides ou lecture refusée : `unavailable`, raison fermée, **aucun compteur inventé**. Un ID invalide devient null, jamais une copie brute sans borne.
- Projection limitée au dossier, département, profil/révision, outil de l’intention, dates, états, nombre de faits et tentatives. Pas de clé de fait/lot, ownerKey, session, ticket, arguments, payload, texte client ou chemin SQLite. Ces métadonnées restent internes au propriétaire local; ce n’est pas un anonymiseur ou une permission d’exposition publique.

La sortie JSON indisponible et la sortie humaine correspondante donnent exit1. Un instantané valide, même non vide, donne exit0; ce code ne certifie pas la santé métier. SQLite read-only peut utiliser des sidecars WAL/SHM selon son environnement; la preuve porte sur absence de mutation des contenus métier, non sur une promesse universelle de zéro interaction filesystem.

## Preuves ROOT

- r366 : rouge avant module, échec d’import; aucun parcours comportemental qualifié.
- r367 : 23 cas réellement passés mais reçu rouge, cardinalité attendue ROOT24 erronée. Rien supprimé.
- r368 : 24/26; deux fixtures corrigées (version0 légitimement refusée; Node24.19 utilise iterate plutôt que all).
- r36926/26, r37027/27 puis r37128/28 : fichiers complets, lint/format. Revue supplémentaire a conduit au nom d’échéance, ID invalide null et mesures limitées; test d’excès de lignes ajouté.
- r372 : 21 régressions passées; contrôle SQL global rouge sur deux agrégats quota préexistants. Remplacement par builders équivalents, sans changement de politique.
- **r373 : 21/21**, deux fichiers complets, contrôle SQL global vert. **r374 : 28/28**, trois fichiers complets, Oxlint/Oxfmt verts. Même ensemble de sources/hash : **49 cas dans cinq fichiers**, aucun ignoré, aucun changement pendant exécution, OOM0. Ce total ne réadditionne pas les reprises antérieures.
- Vrais SQLite jetables : base manquante non créée, schéma absent non initialisé, deux tables absentes/une table absente non migrées, mauvais propriétaire, corruption, quotas saturés/excès257/gros payload, horloge invalide persistée, répétition sans modification des bytes du fichier fermé. Deux connexions réelles en WAL : append après première lecture, instantané stable; aperçu suivant voit le nouvel intent.
- Véritable commande Commander, véritable helper et véritable sortie JSON contre la base sélectionnée dans le processus de test. Six tests de registration ont un helper simulé déclaré, pour options/aide/exit/sortie; le fichier distinct couvre la composition réelle. Aucun lancement de binaire publié/Gateway/outil métier ni provider réel.
- r375 : tentative de compilation globale dans une copie de 36965 fichiers, dépendances locales sans réinstallation, liens confinés et pnpm12.4.0 vérifié par l’intégrité SHA512 du manifeste. **Non qualifiée** : garde pré-lancement, marge effective5262426112 octets <7Gio exigés; exit inconnu, processus enfant non lancé, OOM0, sources/copie inchangées. Le libellé historique du garde `initial_room_below_1GiB` est générique : la limite réellement appliquée ici est7Gio, pas1Gio. Ni build, types globaux, binaire distribué ou CI distante déclarés verts.

Performance : r37394,00s (21 cas plus scan SQL global), pic Vitest1108484096 octets; r37412,69s, pic972414976 octets. Ce sont mesures de qualification, pas un benchmark produit. Le worker garde un avertissement max-lines (limite700); extraction du contrat/reader à étudier séparément avec non-régression, sans masquer la dette.

Capsule et reçu d’intégrité après scan ciblé : `../../research/REPRISE-2026-10-05/preuves/M10-DIAGNOSTIC-POSTFLIGHT-r1.tar.xz` et `.json`. Les sources des runs, rouges, drivers, reviews et corrections sont conservés et vérifiés au roundtrip; la capsule ne transforme pas un scan ciblé en scan de tout le dépôt.

## Suite

Le diagnostic rend les blocages lisibles. Réconciliation humaine authentifiée, pont dashboard→Gateway autorisé, tombstone après ACK, parcours runner/provider/outil métier réel, compilation et CI demeurent ouverts. Aucune purge/reprise implicite, pas de garantie exactement une fois métier ni de daemon permanent. Préparation pour PR privée623; sans identité GitHub disponible, aucun push, merge/main ou déploiement.
