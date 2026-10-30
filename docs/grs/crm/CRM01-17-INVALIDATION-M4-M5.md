# Fraîcheur de la projection M4 V3 dans les traces M5

Examen lecture seule du code M4 `16379c6150516034e018c631ce9022570987e7d0` et de l'arbre M5 `7f4e311af16d3702f69cfbe64e51ff8ca4746e3e`. Aucun fichier M4 ou M5 d'exécution, aucun contrat partagé, droit, migration ou bus n'a été modifié par cette analyse. La cascade expérimentale mentionnée par l'autre mission n'a pas été examinée ni publiée ici.

## Constat

**Il n'existe pas de mécanisme M4 publié qui invalide transactionnellement toutes les traces M5 dépendantes de la V3.** La V3 ne fournit un verdict de fraîcheur qu'en appelant son port propriétaire avec `source_attendue`, sous l'autorité console admin existante (`temps_certifies_v3.py:123-146`, `temps_certifies_v2.py:197-225`). Le manifeste M4 ne publie que `m4.travaux_termines`, produit lors de la complétion WCT ; il ne publie pas de signal sur chaque changement ultérieur des sources V3 (`department.yaml:45-46`, `outils.py:1053-1056`). Une revue de complétion ou une déclaration de composition peut modifier le CAS sans nouvel événement WCT.

La source V3 incorpore le CAS V2 qui couvre **l'intégralité** des registres M4 principal, visites et compositions, ainsi que les audits des preuves utilisées (`temps_certifies_v2.py:46-61`, `temps_certifies_v3.py:129-136`). Elle n'est donc pas strictement une version par chantier. Une déclaration d'une autre équipe, un autre jour, change le CAS d'un chantier inchangé : test fictif `CRM01-17-PREUVES/invalidation/invalidation-transversale-03.xml`, 1 test vert, exit 0. Les totaux restent égaux tandis que la relecture avec l'ancienne source retourne `SOURCE-PERIMEE`. Les tentatives 01 et 02 ont échoué par import de dépendances du harnais ; les logs sont conservés. Trois tests existants (`invalidation-m4-01.xml`, exit 0) couvrent également la composition, la revue et le scénario V3, sans prouver de notification M5 automatique.

Un audit manquant ou altéré invalide aussi la preuve lors d'une relecture ; le journal SQL et les droits ne sont pas intégralement gouvernés par des mutations métier M4. Une empreinte d'entrée conservée dans une trace prouve ce qui a été lu, pas que cette source est encore courante. L'événement WCT et la trace de rentabilité peuvent rester accessibles même après le changement. Aucun TTL ou événement asynchrone seul ne ferme la fenêtre entre un changement validé et sa réception par M5/M8/M10.

## Mesure sûre dans le périmètre actuel

- Ne pas publier ou exposer comme **courante et complète** une rentabilité durable V3 tant que ses consommateurs ne peuvent pas vérifier la source. Garder le résultat historique identifié par sa source comme historique, ou le statut partiel/inconnu ; aucun zéro de remplacement.
- La vue console existante peut relire `projeter(..., source_attendue=source_enregistree)` sous une vraie session admin active, en revalidant instance, WCT, reçus, taux et autorité. En cas de refus ou de révocation : résultat inconnu/périmé ; une nouvelle projection est calculée puis relue avant un usage autorisé. Cette procédure ne donne aucune identité admin au répartiteur et ne permet pas à M8/M10 de vérifier eux-mêmes aujourd'hui.
- Ne pas reprendre les fonctions privées `_projection`/`_qualifier`, ni fournir une source prévalidée par l'appelant comme preuve, ni simuler `origine=console`. L'autre mission possède les choix de lecture ou de publication M5 ; cette note ne modifie pas ses fichiers.

## Option future nécessitant coordination

Une automatisation correcte nécessite au minimum une frontière propriétaire de vérification de fraîcheur et une règle de lecture applicable à **chaque consommateur**. L'identité ou capacité de service doit être fiable, liée à l'instance, au WCT, au consommateur et à la transaction, non forgeable par un paramètre ou un contexte libre ; elle doit couvrir rejets, révocation, CAS et audit. Le résultat doit distinguer `courant`, `périmé` et `inconnu` ; si la vérification échoue, aucun lecteur ne doit utiliser silencieusement le montant comme actuel. La modification du contrat de sécurité ou des surfaces partagées exige une attribution explicite : elle n'est pas déjà disponible et aucune identité machine n'est inventée ici.

Un éventuel signal d'invalidation M4 pourrait accélérer le marquage, mais il serait un **indice de réveil**, pas une preuve unique de fraîcheur. Avec les CAS actuels, sa portée doit couvrir les trois registres globaux et les audits pertinents ; les changements sans événement et les courses entre transactions doivent être pris en compte. Une notification par seul chantier est insuffisante. Il faudrait documenter son émission dans la même transaction que chaque mutation autorisée, les pertes, doublons, reprises et l'intervalle précédant livraison, puis conserver la vérification synchrone avant chaque lecture/usage complet. Le catalogue d'événements et le stockage commun étant hors périmètre, aucun nouvel événement n'a été créé.

Si cette option est mandatée, préparer des commits distincts : (1) contrat versionné et matrice des sources/invalidation ; (2) port propriétaire M4 de vérification et tests négatifs sous une autorité de service réellement attribuée ; (3) raccords de notification partagés attribués au coordinateur ; (4) consommateurs M5/M8/M10 par leurs propriétaires. Aucun SHA d'implémentation de ces propositions n'existe ici. Tester une modification hors chantier, la modification après une lecture mais avant consommation, la perte et le rejeu d'un signal, la révocation, l'audit altéré, les sources remplacées et la réouverture. La séquence ne justifie aucune fusion, paie ou effet de production.

## Reproduction privée de la modification transversale

Depuis le clone M4 ; `invalidation-transversale-01.py` importe les fixtures existantes et utilise exclusivement une base et des identités fictives. Le premier fichier `invalidation-transversale-source-initiale.py` conserve le script avant l'ajout de la fixture `base_durable`. Les lots 01 et 02 ont respectivement échoué à importer M4 puis M6 ; 03 corrige le `PYTHONPATH` et passe. Aucune dépendance n'a été installée pour cette analyse.

```sh
QA="$PWD/../preuves-m4-v2"
PY_PATH="$PWD/src:$PWD/departments/m04-field-ops/tests"
for d in departments/m*/src; do PY_PATH="$PY_PATH:$PWD/$d"; done
env PYTHONPATH="$PY_PATH" HOME="$QA/home" OPSYS_HOME="$QA/opsys" XDG_CONFIG_HOME="$QA/xdg" XDG_CACHE_HOME="$QA/xdg" XDG_DATA_HOME="$QA/xdg" TMPDIR="$QA/tmp" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 timeout 90s systemd-run --user --scope --quiet -p MemoryMax=1G -p TasksMax=32 -p CPUQuota=100% taskset -c 0 bwrap --unshare-net --unshare-pid --ro-bind / / --dev /dev --proc /proc --bind "$QA" "$QA" --chdir "$PWD" -- python3 "$QA/runner-tests.py" "$QA/venv/bin/python" -m pytest -p no:cacheprovider -q "$QA/invalidation-transversale-01.py" --junitxml="$QA/invalidation-transversale-03.xml"
```

Les homes et répertoires temporaires sont privés ; le réseau et le PID sont isolés, les sources montées en lecture seule, le lot borné à 1 CPU, 1 Gio, 32 tâches et 90 secondes. Le processus de test est terminé ; aucun serveur n'a été lancé.
