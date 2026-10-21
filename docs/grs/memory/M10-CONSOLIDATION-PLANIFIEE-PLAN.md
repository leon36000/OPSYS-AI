# M10 développement — Plan d'implémentation

> Exécution native par l'owner `audit_core`, selon le skill `executing-plans` ; étapes testées avant livraison.
> État au 30 septembre 2026 : interfaces stables et implémentation livrée ; coches limitées aux preuves ci-dessous.
> Guide actuel : [consolidation développement](M10-CONSOLIDATION-PLANIFIEE.md).

**But :** produire un rapport développement durable, expurgé et sourcé sous capacité de service révocable.
**Architecture :** canon OPSYS append-only, analyse pure partagée par wrappers humains/service distincts,
runner déterministe sans modèle. Le root raccordera ensuite cron Core/HTTP/console ; aucun de ces raccords ici.
**Stack :** Python existant, stdlib, SQLAlchemy/SQLite et registre M10 actuels ; zéro dépendance nouvelle.
**Design :** [conception approuvée, choix A](M10-CONSOLIDATION-PLANIFIEE-DESIGN.md), limité au développement par le root.

## Contraintes et revue

- Aucun contournement de `_acteur`, TTY ou authentification humaine ; aucun rôle en argument/env du worker.
- Grant, lease avec fencing, rapport et checkpoint dans le canon ; validation finale atomique/revocation vivante.
- Autoriser/révoquer/exécuter exigent SQLite persistante fichier avec `BEGIN IMMEDIATE` ; PG/SQLite volatile refusés avant effet.
- Chaîne complète reconstruite ; coût mémoire croissant conservé et documenté, plafonds d'analyse explicites.
- Sources tardives, DST Toronto, même clé avec charge changée, crash avant/après commit et vieux lease : tests négatifs.
- Credential POSIX régulier, propriétaire courant, mode 0600, un seul lien physique, lecture ≤4096 octets,
  composants sans symlink ; secret absent des sorties. C01 demeure une limite OS.

## 1 — Autorité et canon du job

**Fichiers :** nouveau `departments/m10-memoire/src/m10_memoire/consolidation_developpement.py`,
nouveau test voisin `test_consolidation_developpement.py` ; registre dédié `m10-memoire/consolidation_developpement`.
**Interfaces :** `autoriser(job_id, repository, credential_file, *, fuseau, premier_jour, limites) -> dict`,
`revoquer(job_id) -> dict`, `lire_statut(job_id) -> dict`, `lister_jobs() -> list[dict]`,
`lire_rapport(job_id, report_id=None) -> dict | None` ; toutes exigent `_acteur()` humain vivant.
`executer(job_id, credential_file) -> dict` authentifie uniquement la capacité de service du grant.
- [x] RED : grants sans contexte humain refusés, credential inconnu/mauvaise portée/symlink/mode large refusés.
- [x] Implémenter records append-only `grant`, `revocation`, `lease`, `report`, `checkpoint` avec chaîne vérifiée.
- [x] Vérifier SQLite réel, mutation humaine absente et révocation effective ; le secret ne sort jamais du fichier.
- [x] RED/GREEN : hardlinks, caps invalides et backend non pris en charge refusés sans mutation/credential nouveau.

## 2 — Lecture et analyse partagées, rapport et self-model

**Fichiers :** `developpement.py` et le nouveau module/test ci-dessus.
**Interfaces :** `_snapshot_audit_developpement(...) -> dict` reconstruit le canon puis lit fenêtres/refs/global head ;
`_analyser_audit_developpement(snapshot, *, limite, repository) -> dict` analyse sans acteur/écriture/IO ;
les fraîcheurs déjà mesurées sont contenues dans le snapshot.
`auditer_developpement(...)` reste wrapper humain `_acteur()` ; seul le runner service validé lit son snapshot.
- [x] RED : audit humain toujours protégé ; rapport service expurgé, sources/HEAD/fraicheur/omissions résolvables.
- [x] Extraire l'analyse existante sans changer son contrat ; self-model avec sources indexées,
  empreintes réellement observées et inconnus explicites ; aucune conclusion de complétion.
- [x] Refaire tous les tests développement existants ; absence de mutation de prompt/plan/claim.
- [x] RED/GREEN : hors grant séparé des absences et omissions par cap ; omissions par taille rapport comptées.

## 3 — Créneaux, reprise et transaction finale

**Interfaces :** grant stocke racine, fuseau, premier jour et caps ; horloge `_maintenant()` serveur,
créneau quotidien 03:00 ; `executer` traite au plus un créneau dû par invocation et expose le backlog.
- [x] RED : rejeu sans doublon, arrivée tardive révisant un créneau, rattrapage de nuits et changement DST.
- [x] RED : révocation pendant analyse, expiration/reprise de lease, exception avant commit,
  nouveau worker retrouvant le commit au rejeu sans double rapport.
- [x] Réserver lease avec epoch ; analyser hors transaction longue ; revérifier grant/lease/entrée avant rapport+checkpoint.
- [x] Export/restauration SQLite réelle du canon puis reprise avec credential privé conservé séparément ;
  chaînes valides et refus de corruption ; nouvelle tête révise le rapport même avec timestamp ancien.
- [ ] Crash OS brutal ou restauration pendant un worker vivant : non éprouvés ; arrêter les workers avant restauration.

## 4 — CLI humaine et worker stable

**Fichiers :** `src/opsys/memoire_developpement_cli.py`, nouveau `src/opsys/memoire_consolidation.py`, tests ciblés.
**CLI humain :** `memoire-developpement autoriser-job --job-id ID --depot PATH --credential-file PATH`
avec fuseau/premier jour/caps ; `revoquer-job --job-id ID`, `statut-job --job-id ID`,
`configurer-cron --job-id ID` appelle le helper root sous autorité humaine sans lancer de commande.
TTY actuel inchangé. Horloge/entropie OS résident dans le boundary `opsys.memoire_consolidation`, sans exemption du gate domaine.
**Worker :** `python -m opsys.memoire_consolidation executer --job-id ID --credential-file PATH` seulement.
**Résultat public :** `job_id`, `status` (`available`/`partial`/`not_due`/`replayed`/`blocked`),
`report_id`, `slot`, `backlog`, `replayed` ; aucune capacité, prompt brut ou identité choisie en arguments.
- [x] RED : worker arguments dépôt/rôle/personne refusés, CLI jobs non interactif refusé, aucune fuite stdout/stderr.
- [x] Authentification CLI réelle sur terminal synthétique, grant/statut/révocation ; aucun mot de passe/capacité en sortie.
- [x] Sous-processus worker Python réel puis second sous-processus rejouant le même rapport canonique.
- [x] Implémenter adaptateurs ; contrat public transmis au root avant raccord UI/cron.
- [x] Guide et lint des fichiers possédés, JUnit ciblé réel SQLite ; comptes/empreintes dans inventaire de preuves.
- [x] Probe indépendante Gateway/cron Core réel sur loopback même hôte synthétique, échéance `at`,
  un `finished=ok`, rapport/checkpoint valide et rejeu sans double ; aucune nuit VPS revendiquée.
- [ ] Nuits récurrentes sur VPS, isolation OS C01 et chemins entre conteneurs : non démontrés.

PREUVE: `m10-job-cibles-final.xml`, `m10-job-departement-final.xml`, `m10-job-verification.json` et
`m10-native-cron-probe-result.json` ; les cinq fichiers Python sont gelés dans `m10-job-source-freeze.json`
et la probe native a été reprise sur ce gel. Verdict département au snapshot 20:57 UTC : **954/954**, zéro échec/erreur/saut ;
84 ciblés inclus dans ce total. Contrats partagés neuf types et deux outils contexte corrigés par leurs owners.
L'extension C02 `source="cli"` ultérieure est hors de ce snapshot et du gel cinq fichiers ; root/owner la revérifient.
