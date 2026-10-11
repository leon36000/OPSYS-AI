Le finding tombstone/verdict est corrigé dans deux fichiers, gel2 libéré.

RED-storage-r2 :4F/2P/25nonselectionnés, production fccf intacte. Les4 suites/alertes401/403 perdaient le verdict lors d'une panne alors que le cache était bien fermé ; les2 changements d'identité pendant panne étaient déjà sûrs.

Premier correctif :1F/72P, historique conservé avec ses octets. Le retrait du wrapper avait oublié la garde globale initiale du chargeur, laissant un ancien chargeur lancer une suite après purge. Ajout explicite de cette garde avant/après RPC et2 témoins identité changée pendant succès tardif du tombstone.

Qualification finale fraîche :75P/4suites/0skip,4,473s/RSS663207936. EOF/PIDFD et propriétaires arrêtés ; inventaires fixés pré/post identiques et tous imports mobiles réellement lus couverts. Les8 nouveaux cas couvrent panne401/403 suite/alertes et purge pendant panne ou succès ; les67cas précédents sont réexécutés ici, pas additionnés.

Sources exact2 seulement.609 voisins protégés du corpus611, plus M10gel2 etCore4 fixés. Pas d'invariance de toutes dépendances ni qualification globale mobile/types/styles. Root seul repin et exécution finale commune r3 ; aucun autre préparateur/runtime. R1, tous rouges, JSON/logs et premier XML dérivé incorrect restent intacts.
