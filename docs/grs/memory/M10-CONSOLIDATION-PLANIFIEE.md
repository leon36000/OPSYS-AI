# M10 — Job de consolidation du développement

État au 30 septembre 2026 : worker et autorisations implémentés, choix A approuvé.
Le job analyse les sources et relations du développement et ajoute un rapport durable expurgé.
Il ne remplace pas la consolidation d'affaires et ne déclare aucun module, claim ou plan terminé.
Le [design](M10-CONSOLIDATION-PLANIFIEE-DESIGN.md) conserve la conception initiale ; le
[plan](M10-CONSOLIDATION-PLANIFIEE-PLAN.md) sépare les critères éprouvés des limites restantes.

## Autoriser et révoquer

Le canon doit être une SQLite persistante sur fichier, configurée par `OPSYS_BASE_URL`
(`opsys.stockage.ENV_URL`). `OPSYS_DATABASE_URL` désigne la mémoire RAG distincte.
Autoriser, révoquer et exécuter refusent PostgreSQL et SQLite volatile avant création de credential
ou mutation du job. Les fonctionnalités PostgreSQL des autres domaines mémoire restent distinctes.

La CLI actuelle demande un terminal et authentifie une personne vivante admin/owner.
La racine Git complète et les plafonds viennent de ce grant humain, jamais du worker.
Le fichier credential doit être neuf dans un dossier existant réservé à l'exploitation.

```bash
opsys metier memoire-developpement autoriser-job \
  --job-id audit-developpement --depot /srv/OPSYS-AI \
  --credential-file /srv/opsys/secrets/memoire-jobs/audit-developpement.json \
  --fuseau America/Toronto --premier-jour 2026-09-30
opsys metier memoire-developpement statut-job --job-id audit-developpement
opsys metier memoire-developpement configurer-cron --job-id audit-developpement
opsys metier memoire-developpement revoquer-job --job-id audit-developpement
```

`configurer-cron` appelle le helper serveur authentifié et affiche une déclaration structurée ;
il ne lance pas le Gateway ni la commande d'ajout. Le helper relit le grant actif et produit le
cron natif `0 3 * * *`, son fuseau, une clé de déclaration stable, `--command-argv` et `--no-deliver`.
Le Python, les chemins serveur et l'environnement canonique sont choisis côté serveur.
Ce raccord exige que Core et Python puissent accéder aux mêmes chemins sur le même hôte.
Un déploiement en conteneurs séparés n'est pas démontré par les preuves présentes.

Le principal `service:m10-consolidation` est authentifié par une capacité aléatoire ; seul son hash
est stocké dans le grant canonique. Aucun mot de passe humain n'est conservé par le worker.
Le fichier est ouvert par des descripteurs sans suivre les symlinks, y compris les dossiers parents.
La lecture exige POSIX, un fichier régulier de l'UID courant, mode exact `0600`, un seul lien physique,
et au plus 4 096 octets. Le secret n'apparaît pas dans argv, les rapports ou stdout.
Renouveler un grant utilise un nouveau fichier ; l'ancienne capacité est immédiatement refusée.
La création fichier puis grant ne forme pas une transaction distribuée : un crash peut laisser un
fichier privé orphelin, sans grant actif. La révocation conserve l'historique, sans supprimer le fichier.

## Entrée de service et contrats publics

```bash
python -m opsys.memoire_consolidation executer \
  --job-id audit-developpement \
  --credential-file /srv/opsys/secrets/memoire-jobs/audit-developpement.json
```

Cette entrée refuse les arguments de dépôt, acteur, personne ou rôle. Elle n'appelle pas la CLI
humaine et ne construit pas d'identité admin. L'horloge et l'entropie système sont fournies par
`src/opsys/memoire_consolidation.py` ; l'analyse partagée reste déterministe et sans modèle.

Les fonctions humaines de `m10_memoire.consolidation_developpement` revérifient `_acteur()` vivant :

| Fonction | Résultat public |
|---|---|
| `autoriser(job_id, repository, credential_file, *, fuseau, premier_jour, limites)` | Grant expurgé, sans hash ni capacité brute. |
| `revoquer(job_id)` | `job_id`, `active=false`. |
| `lire_statut(job_id)` | Principal/domaine, activité/version, racine, chemin credential, fuseau, premier jour, plafonds, backlog, prochain créneau, dernier rapport résumé et lease. |
| `lister_jobs()` | Liste triée de ces statuts, grants révoqués compris. |
| `lire_rapport(job_id, report_id=None)` | Entrée canonique expurgée ; défaut dernier rapport, `None` si aucun rapport ou id absent. |

Le résumé `last_report` contient `report_id`, `slot`, `status`, `input_head`, `observed_at`, `grant_version`.
L'entrée complète contient `kind`, `job_id`, `grant_version`, `slot`, `report_id`, `principal`, `report`.
Un job inconnu est une erreur explicite, pas un rapport vide. Les lectures humaines n'attribuent pas
le principal de service à une personne et n'exposent aucune empreinte de capacité.

Le worker retourne `job_id`, `status`, `report_id`, `slot`, `backlog`, `replayed`.
États : `available`, `partial`, `not_due`, `replayed` ; refus : `blocked` avec code d'erreur borné.
Codes processus : 0 pour résultat disponible/rejeu/non dû, 2 pour rapport partiel, 1 pour refus/échec,
2 également pour argument invalide selon argparse. Les exceptions internes ne sont pas imprimées.

## Canon, concurrence et reprise

Grants, révocations, leases, rapports et checkpoints partagent le registre append-only
`m10-memoire/consolidation_developpement`, distinct du canon des prompts/plans/claims.
Les chaînes du job et du développement sont revalidées, y compris avant un rejeu.
Admission et validation utilisent SQLite `BEGIN IMMEDIATE`. L'analyse longue est hors transaction.
La transaction finale relit grant actif/hash/version, lease epoch/clé/expiration et tête des entrées,
puis ajoute rapport, checkpoint et lease terminée ensemble. Un ancien worker ne peut valider après reprise.

Un crash avant cette validation laisse au plus un lease : attendre son expiration pour reprendre.
Un commit sans reçu se retrouve au rejeu sans double rapport. Une mutation canonique pendant l'analyse
refuse le lot ; un nouveau head ouvre une révision même si son horodatage métier est ancien.
Le créneau est 03:00 dans le fuseau du grant. Chaque invocation traite au plus le plus ancien créneau dû ;
le backlog reste visible, avec refus explicite au-delà de dix ans. Les jours de Toronto autour du DST
utilisent la date locale et une occurrence à 03:00. Aucun job ne dépend d'une horloge de modèle.

Un rejeu avec même créneau et même `input_head` retourne le rapport durable existant : une modification
physique de fichier sans ingestion canonique n'est pas revérifiée par ce rejeu. Une nouvelle nuit vérifie
les fichiers ; une nouvelle révision canonique déclenche une nouvelle analyse le même jour.
Chaque rapport décrit l'état observé à `observed_at`, pas la fraîcheur permanente d'un checkout vivant.

L'export/restauration canonique transporte les grants et rapports. Le secret credential est exclu de
l'archive actuelle : le test de reprise conserve le fichier privé sur le même hôte. Un déplacement exige
un renouvellement humain avec un nouveau credential. Arrêter les workers avant restauration : le
rollback du canon et la concurrence de workers actifs pendant restauration ne sont pas prouvés ici.

## Rapport, plafonds et limites

Le rapport conserve version d'analyse, tête canonique, commit Git local, instant, couverture et plafonds.
Le self-model cite les refs d'index, event ids, chemins, empreintes indexées et effectivement observées,
fraîcheur et portée. Une empreinte observée vaut `null` si le fichier n'a pas été lu.
La mission et les permissions non évaluées restent `unknown`, la complétion `not_evaluated`.
Une source hors racine autorisée vaut `outside_grant`/`unknown`, sans lecture ni fausse absence.
Ces sources sont comptées séparément des omissions dues aux plafonds. Aucun contenu complet de fichier,
prompt brut ou secret ne constitue une auto-description validée.

Plafonds maximums du grant : 5 000 événements, 10 000 relations, 500 sources, 500 constats
(défaut 100), 256 000 octets par fichier, 8 000 000 octets réservés par lecture de sources,
128 000 octets de rapport (minimum 2 048), lease 600 secondes. Les bornes peuvent être réduites.
Le budget octets est réservé de façon pessimiste ; il peut rendre une couverture partielle avant de lire autant
d'octets que le maximum. Les sources non lues restent inconnues. Les constats retirés pour respecter la
taille du rapport sont comptés par `findings_omitted_by_report_cap` et `status=partial`/`truncated=true`.
Si les métadonnées seules dépassent la taille, le lot échoue explicitement sans rapport partiel trompeur.

La reconstruction **complète** et la validation du canon sont conservées ; leurs coûts CPU/RAM croissent
avec le journal et ne sont pas bornés par les caps d'analyse. Le lease borne la validation temporelle,
pas un arrêt forcé du worker autonome. Le runner cron Core possède son contrôle de durée/arrêt distinct.
Git/SQLite sont locaux et le worker ne requiert aucun fournisseur réseau. Les fichiers non indexés,
non suivis ou exclus ne sont pas réputés audités. **C01 demeure une limite OS** : un processus partageant
l'UID et les droits sur credential/base n'est pas isolé par ce mécanisme ; aucune isolation production
de comptes, hôtes ou conteneurs n'est revendiquée.

## Preuves exécutées

Les preuves sont dans `/workspace/restructuration-opsys-2026-09-30/preuves/` :
`m10-job-cibles-final.xml/.log`, `m10-job-departement-final.xml/.log`, séries RED `m10-job-red-*.xml/.log`,
et inventaire `m10-job-verification.json`. Elles utilisent des bases, dépôts Git et identités fictifs temporaires,
avec authentification produit réelle, sans Docker, fournisseur, installation ou commit dans le dépôt propriétaire.
La suite département vérifie aussi la consolidation d'affaires existante après extraction de l'analyse partagée.
Verdict du snapshot testé le 30 septembre à 20:57 UTC : **84/84 ciblés**
(35 jobs, 22 développement, 27 conformité), puis **954/954** pour
le département M10 entier et `tests/test_commande_metier.py`, zéro échec/erreur/saut. Les 84 sont inclus
dans les 954, pas un total supplémentaire. Lint des cinq fichiers possédés : zéro erreur.
Exécution : Python 3.12.14, pytest 9.1.1 ; bases et dépôts temporaires, aucune nuit en production.
L'extension C02 ultérieure de provenance humaine `source="cli"` se situe hors des cinq fichiers gelés :
ce résultat 954 décrit le snapshot antérieur, pas une validation de cette extension. Son owner/root
porte les vérifications C02 et globales ultérieures ; le worker et sa preuve cron demeurent inchangés.

La probe indépendante `m10-native-cron-probe-result.json` et son harness/log, à la racine de ces preuves,
ont utilisé Gateway Core `dist` réel sur loopback, payload command, échéance `at`, sans modèle ni livraison :
un `finished=ok`, worker `available`, chaîne valide, un rapport/checkpoint, puis même id au rejeu sans doublon.
La probe a été reprise après gel final des cinq fichiers Python ; snapshot dans `m10-job-source-freeze.json`.
SHA256 du résultat final : `d2ab1ce54164aad397f2e137fa305a0fcd6f772106784f5e7c1ff8c46e851589`.
Cette probe prouve l'exécution cron sur **un même hôte synthétique**, pas une nuit récurrente VPS,
un service OS permanent, des conteneurs séparés ou PostgreSQL. Les 36 tests du design initial ne sont
pas utilisés comme preuve de ce nouveau job.

PREUVE: worker/CLI et canon SQLite éprouvés ; compte exact et empreintes des fichiers dans `m10-job-verification.json`.
