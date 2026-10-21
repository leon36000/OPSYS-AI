# M10 — persistance interne des faits à déposer

Statut : stockage Core vérifié localement; collecteur authentifié, livraison M10 et cycle cron
encore à raccorder. Ce rapport porte sur la conservation après panne, pas sur une mémoire complète.

Le Core réutilise sa base SQLite par agent, Kysely et le worker du propriétaire existant. La table
additive `opsys_postflight_outbox` conserve un lot fermé : affaire, département, profil, révision,
moteur et 1–20 faits `{cle, outil, resultat, code}`. Aucun prompt, argument brut d'outil, texte de
tour, ticket cible ni secret n'est accepté dans cette enveloppe. Ce stockage ne prouve pas, à lui
seul, que les identifiants ou résultats proviennent d'une exécution autorisée.

Les écritures sont transactionnelles et revérifient le propriétaire courant. Un lot identique en
attente est réutilisé; une même clé avec contenu divergent ou un chevauchement de lots est refusé.
Les plafonds de 256 lots et 1 Mio sont contrôlés dans la transaction, sans purge automatique.
Le moteur accepte une horloge injectée; les reprises attendent 1, 5, 15, 60 minutes puis un jour.
Après huit tentatives ou sept jours, le lot reste conservé en `needs_review`. Aucun minuteur ou
appel externe n'est créé par cette tranche.

L'ACK exige une correspondance exacte et au moins une tentative avant suppression. Il n'y a pas
de tombstone durable : le même lot peut être réinséré après ACK. La déduplication de bout en bout
doit donc reposer sur les clés stables et le registre M10, dont le raccord reste à vérifier.
Un effet métier distant suivi d'une panne avant journal local demeure une fenêtre de perte;
rejouer le dépôt M10 et rejouer l'outil initial sont deux opérations distinctes.

## Vérifications conservées

- r284 : 9/9 tests du stockage dans son fichier complet, worker SQLite réel, Oxlint/Oxfmt verts.
- r286 : 17/17 pour le stockage et l'outbox de tours existante; 10/10 pour le worker propriétaire,
  confirmés dans le JUnit. Le reçu global reste rouge : la seconde sélection n'incluait pas le
  fichier de réparation des index demandé; ce défaut de sélection n'est pas masqué.
- r289 : 5/5 pour ce fichier complet via la configuration de base existante, puis lint/format verts.

Le complément r293 vérifie **38/38 dans trois fichiers complets**, avec lint/format verts :
11 cas de stockage, 8 de l'outbox de tours et 19 du collecteur historique. Les clés v1 de
40 caractères hexadécimaux et v2 de 64 sont conservées exactement, sans conversion; les formes
intermédiaires, majuscules et préfixes altérés sont refusés sans écriture. Avec les 10 et 5 cas
de propriétaire et index inchangés, ces vérifications couvrent conservation/réouverture, rejeu,
divergences, quotas, migration depuis
une ancienne base, révocation et reprise. Les exécutions r282–r283 conservent la correction du
montage de test : attendre le nettoyage asynchrone canonique avant réouverture. r285 conserve
l'échec sous limite V8 de 256 Mio; les reprises sont bornées et n'ont provoqué aucun OOM cgroup.

La construction complète demeure **non qualifiée**. r288 a révélé un mauvais chemin de lanceur;
r290 le refus normal des dépendances externes au checkout isolé; r291 l'absence des liens locaux
aux packages dans cette copie. r292 corrige le montage avec une copie physique indépendante des
dépendances et pnpm 12.4.0 dont digest et signature npm sont vérifiés. Sa compilation globale
a été arrêtée par le garde de mémoire brute avant OOM; les sorties partielles ne sont pas une livraison.
Les sources live restent inchangées dans ces exécutions; leurs reçus rouges sont conservés.
Le seuil RSS de 6 Gio suit le groupe du lanceur, sans mesurer séparément les groupes tsdown
détachés; seul le garde de mémoire brute cgroup couvre cette consommation dans le reçu.
La [revue de ressources](../../research/REPRISE-2026-10-05/conceptions/LOT5-BUILD-RESSOURCES-REVUE-r2.md)
précise cette limite : aucun plafond RSS agrégé de toute la compilation n’est garanti par ces logs.

**Construction ciblée et parcours du worker compilé vérifiés :** r294 sélectionne uniquement
l'entrée du worker dans la véritable configuration de compilation, avec ses plugins de schéma
SQL et de dépendances. La compilation réussit; la première sonde omettait le callback requis
du propriétaire et reste rouge. La sonde corrigée r295 emploie sa capture d'exécution canonique
et le véritable propriétaire de worker SQLite : enregistrement des deux formats de clé, fermeture,
réouverture, rejeu stable, refus divergent et suppression après ACK exact. Elle passe sans appel
externe ni OOM. Ce parcours ne remplace ni les déclarations TypeScript ni le build/CI complets.

## Données et suite

Les identifiants d'affaires et profils restent des métadonnées internes lisibles dans SQLite.
Les permissions de la base par défaut sont celles du propriétaire existant (fichier 0600,
répertoires 0700); aucun chiffrement applicatif nouveau n'est livré. Un chemin personnalisé
garde ses responsabilités d'exploitation et ses droits existants.

Avant raccord : préserver les clés historiques `tc-40`, associer reçu d'admission et ticket cible
validés au véritable appel d'outil, puis vérifier dépôt réel, ACK perdu, redémarrage et révocation.
L'usage fournisseur inconnu conserve sa réserve et ne devient ni un coût zéro ni un refus d'outil.
Les [conceptions r1](../../research/REPRISE-2026-10-05/conceptions/LOT5-COLLECTEUR-CONCEPTION-r1.md)
et [r2 corrigée](../../research/REPRISE-2026-10-05/conceptions/LOT5-COLLECTEUR-CONCEPTION-r2.md)
conservent les sources et les frontières de panne. Aucun fournisseur payant, client réel,
fonctionnement continu de 24 heures ou autonomie globale n'est qualifié par cette tranche.

## Vérification des traces avant publication

Le scan brut r296 reste rouge. Ses 54 481 détections ont été classifiées : 54 479 portent
uniquement sur des paires chemin de source / SHA-256 dans les manifestes de preuve; deux sont
les clés publiques npm utilisées pour vérifier la signature du lanceur. Aucun secret privé
n'est identifié dans ces valeurs. r297 vérifie 196 fichiers avec des exceptions limitées aux
lignes de checksum des 31 manifestes concernés et aux deux clés publiques exactes : aucune
détection restante, aucune exception sur les fichiers de code ou de documentation. Le scan
initial, sa classification et la configuration d'exceptions sont conservés pour revue.

## Preuves conservées

[Capsule de sources, variantes, reçus et worker compilé](../../research/REPRISE-2026-10-05/preuves/POSTFLIGHT-STOCKAGE-r1.tar.xz)
— SHA-256 8ebf70ae4a967d34c29f4a9e3bf64d694c9fa89723b2564f382d827bf498a9d0.
[Inventaire](../../research/REPRISE-2026-10-05/preuves/POSTFLIGHT-STOCKAGE-r1.json) et
[avis MIT Kysely](../../research/REPRISE-2026-10-05/preuves/POSTFLIGHT-STOCKAGE-NOTICE-r1.txt).
La capsule conserve le rapport avant ajout de ces liens; ses exécutions rouges restent présentes.
