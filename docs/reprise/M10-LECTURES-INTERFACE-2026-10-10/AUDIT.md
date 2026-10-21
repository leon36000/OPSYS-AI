Date Toronto : 2026-10-10T01:37:03.080383-04:00

# Reprise M10 : lectures documentaires et interface admin — continuation privée

État OPSYS-AI : **PARTIEL**. La branche privée publiée reste au commit `44d0237fa64f233862baa25a2d3c5c42e3516ba2`, PR #623 ouverte en brouillon. Les changements décrits ici sont gelés dans le checkout isolé F17 et copiés à l’identique dans le clone principal, sans commit ni push à cette date. Ils ne reçoivent aucun crédit de la CI de ce commit.

## Comportement visé

L’admin ouvre explicitement une affaire depuis la recherche ou un signal dans Mémoire. Il consulte des métadonnées documentaires courantes, une version par page, puis le corps exact de la version choisie. Les pages peuvent changer entre lectures ; elles ne forment pas un snapshot. La date, l’auteur historique, les références et l’empreinte proviennent de la source. Un document retiré n’expose aucun corps. Aucun corps de lecture n’est conservé hors ligne.

Déposer, activer et retirer restent trois décisions explicites distinctes utilisant les writers existants. Un brouillon non soumis reste en mémoire du panneau et peut être perdu à sa fermeture ou au changement de session. Une intention déjà soumise conserve son identifiant durable, notamment si le résultat réseau est inconnu. Elle bloque les nouveaux effets de sa série. Un reçu propre confirme l’intention originale ; l’état documentaire courant doit être relu avant une autre décision.

## Rapprochement

Le registre gelé contient 31 sources : 17 Python/contrats/documentation, 5 lecteur et service mobile, 2 contrôleur, 7 interface/raccord/locales. Au HEAD de base exact : 11 modifications et 20 nouveaux fichiers. Chaque fichier a une empreinte, un propriétaire, une préimage Git ou une absence explicite et une limite de qualification. Les dépendances locales `mobile/node_modules` sont un lien de travail exclu de Git.

Les 104 preuves exclues du transfert léger restent indisponibles ; leurs références historiques sont conservées sans prétendre les avoir réexécutées. Le supplément du transfert complet et les conversations absentes restent inconnus. La divergence non attribuée de BRIEF dans l’ancien F15 est préservée et exclue de cette continuation.

## Preuves présentes et défauts conservés

- Source17 gelée : jonction Root 779 tests réussis, sans test ignoré, sur 16 fichiers ; Ruff global réussi ; vérificateur métier : dix départements, 242 outils, 150 outils autorisés au total. Les 18 fenêtres backend de lecture ont chacune conservé 49 tables ; les huit frames Cap/SQLite ont une identité fictive injectée. Ces résultats ne prouvent pas un transport avec token DEVICE opaque.
- Version finale du contrôleur GEL3 : TypeScript mobile global réussi ; suite mobile entière répartie sur quatre processus neufs : 5 562 tests réussis, 237 fichiers, zéro échec et zéro test ignoré. Le test nommé du corps blanc est réussi. L’exécution initiale arrêtée au plafond RSS et la qualification précédente à 5 552 tests demeurent conservées dans leurs scopes exacts.
- Le Root a trouvé un défaut de contrat : un corps composé d’espaces, admis par le domaine Python et le writer mobile, est refusé par le lecteur qui réutilise un prédicat de titre non blanc. Le témoin rouge échoue précisément après acceptation par le vrai writer ; la correction remplace un seul prédicat. Les bornes de tailles et l’empreinte exacte restent contrôlées. La nouvelle qualification globale ci-dessus porte ces octets corrigés ; les anciens verts restent liés à leurs sources.
- Le clone principal a ensuite passé une qualification fraîche de 779 tests Python, sans test ignoré, Ruff et le vérificateur métier. Les 90 imports Python de test et les 83 imports métier pointent sur ce clone. Les 615 fichiers mobiles correspondent exactement au checkout qualifié ; aucune nouvelle exécution mobile dans le clone n’est revendiquée. Ces répétitions et sous-suites ne sont pas additionnées.
- Le P2 de renouvellement de session a été reproduit puis corrigé : même destination et nouveau jeton reprennent l’identifiant original ; une destination étrangère est refusée avant effet. La revue indépendante de la correction n’a trouvé aucune anomalie matérielle. Ses observations statiques restent distinctes des tests Root.
- L’interface a 20 tests de rendu/route/raccord et 55 tests de traduction, inclus dans la suite complète ; elle n’est pas qualifiée sur un téléphone ou un pont SQLite natif.
- Les avis Claude déjà clos ont effectivement mobilisé Opus 5.5, deux Sonnet 5.5 et Haiku 5.5. HIGH/HIGH/MAX sont des configurations ; l’effort effectif n’est pas émis par le fournisseur. Ce sont des avis statiques confrontés aux fichiers. La contre-revue Source14 a reçu un GO Root sur 38 fichiers gelés et 44 origines vérifiées : Opus HIGH, deux Sonnet HIGH et une mission Haiku MAX limitée à deux fiches. La passe est close : les quatre modèles/rapports et les clôtures ont été vérifiés, mais le contrôle formel reste rejeté pour Haiku351/350 mots. Les avis complets ont été lus et confrontés séparément, sans tronquer un rapport, modifier le garde ou relancer le modèle. Deux constats ont conduit aux corrections Root décrites ci-dessous ; les tests réels portent les nouveaux octets, les avis restent liés au snapshot précédent. Les deux avis LiteLLM Muse/Luna sont clos, avec modèles réels vérifiés ; aucun nouveau défaut confirmé. Leurs propositions de tests restent des avis et ne sont pas présentées comme des exécutions.

Les corrections finales permettent à un autre admin de lire une autre affaire tout en retenant l’intention originale hors de sa vue et en bloquant les nouveaux effets. Le contrôleur compare les métadonnées immuables de la même version entre index et détail, sans figer le statut ni l’activation. La reprise vérifie la série de l’intention originale même quand l’affaire affichée a été effacée. Les 31 tests du contrôleur sont inclus dans la passe complète. Un premier contre-exemple auteur partageait par erreur le même objet entre les fixtures ; ce rouge a été attribué au montage, corrigé et conservé, sans le déclarer défaut produit.

## Blocages précis

La campagne Native T0 préparée exige au moins 6 GiB de mémoire disponible avant lancement ; la marge locale mesurée est inférieure. Aucun nouveau service n’a été lancé. Le préflight PC1 constate de la mémoire disponible, mais n’a pas trouvé Node 24, Python verrouillé ni ce checkout dans son inventaire borné ; aucun runtime distant n’est donc prêt. Aucun processus utilisateur n’est arrêté pour dégager de la mémoire.

Docker local demeure inaccessible ; PostgreSQL doit être distingué des qualifications SQLite et des runners. La CI du commit publié 44d est réussie, dont le build Core complet, avec 38 jobs réussis et deux jobs Docker conditionnels ignorés. Elle ne qualifie pas les nouvelles sources F17. Le Core reste au même arbre `4ad1a927b4286039c23f7b93cbf43c2d02b61c7e`.

## Suite et sortie de cette tranche

Le lecteur corrigé et les jonctions sont gelés et qualifiés localement. La disposition des avis et les qualifications sont closes. Relire le HEAD distant immédiatement avant publication et publier une continuation normale sur la branche privée existante. Obtenir ensuite la CI applicable du nouveau commit exact et actualiser la PR #623. Pas de force-push, de fusion sur main ni de déploiement de production.

La suite métier demeure M7 → M1 → M2 → M3 → M4/M6 → M5 → M8/M9/M10 avec identifiants communs, preuves de reprise et capacités profondes restant inscrites avec leurs dépendances. Le dashboard, les quatre profils mobiles hors ligne, les avatars, permissions et mémoires métier/développement séparées restent dans l’ambition ; cette tranche ne les déclare pas entièrement livrés.
