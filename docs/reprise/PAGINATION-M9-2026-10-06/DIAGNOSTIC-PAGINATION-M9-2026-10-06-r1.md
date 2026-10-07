# Limite réelle de pagination du briefing M9

Toronto : 2026-10-06T23:34:23.341581-04:00. Modules M9 inchangés et égaux aux blobs du commit `6069c9e61309e4ffd0a1ea33a8e6892c857d5286` ; modifications mobiles locales qualifiées séparément. Diagnostic natif `Capacites` et SQLite migré, cinquante demandes fictives N4.

Le briefing affiche18 demandes. Une mutation explicite de fixture retire la première de la file avant la suite : même `maintenant`, indice18, la suite débute à la vingtième demande originelle et saute la dix-neuvième. Les deux lectures ne modifient aucune table : empreintes globales comparées avant/après chaque appel, distinctes de l’écriture de fixture. Cette campagne ne simule pas une décision authentifiée.

`maintenant` fixe les dates/fenêtres, pas une coupure des sources. La suite relit la file, alertes et faits puis découpe par indice ; elle ne porte ni version des sources ni `briefing_id`. L’ID initial représente contenu affiché et comptes omis : remplacer une demande cachée à compte constant laisse cet ID inchangé, confirmé par le module pur. Les tests historiques prouvent l’exhaustivité à sources stables ; ils ne prouvent pas un snapshot inter-pages.

**Disposition de T4.21** : conception actualisée soumise — pages courantes clairement datées, rafraîchissement depuis le début, anciennes suites abandonnées, sources/manques/refus/cache personnel explicites. Aucune exhaustivité du briefing initial promise ; un snapshot figé demanderait un contrat backend supplémentaire à concevoir. Aucun écran ou changement backend dans ce diagnostic. Revue indépendante source concordante ; produit PARTIEL et file verticale conservée.

Registre `REGISTRE-PAGINATION-M9-2026-10-06-r1.json`, capsule `PREUVES-PAGINATION-M9-2026-10-06-r1.tar.xz` SHA-256 `7ca87766e6f41aa9d0ba476b815500ff596b8d3497858d2bedc333047f9de75f`, 7 membres réguliers sans base. Sources/helper/log/reçu conservés ; DB temporaire détruite, pas réseau/téléphone/effet réel. Les80 sorties précédentes restent immuables,104preuves originales absentes et supplément absent ne sont pas réexécutés.
