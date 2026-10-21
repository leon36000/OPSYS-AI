# M3 — r2 du staging `m3_lister_devis`

Cette révision préserve intégralement le staging r1 et n’apporte aucune modification au dépôt. Elle répond aux retours ROOT en ajoutant des cas de test contractuels et en reformatant les lignes nouvelles longues. La vérification de style Ruff et les empreintes du r1 avaient été faites par ROOT; aucun test/build/QA n’a été lancé par cet agent.

Les deux seuls fichiers modifiés dans `files/` sont `departments/m03-estimation/src/m3_estimation/outils.py` et `departments/m03-estimation/tests/test_acces_par_proprietaire.py`. Le code produit dans r1 est inchangé hormis formatage dans la nouvelle fonction. Les tests r2 couvrent désormais:

- absence d’appareil, employé, admin, personne inactive, et rôle seller retiré après émission;
- devis `brouillon`, `envoye`, `accepte` lus dans l’ordre stable; pagination sans doublons, rejeu identique et aucune écriture;
- curseur transféré entre vendeurs, repère devenu hors portée après réassignation M2, jeton fabriqué visant un autre propriétaire ou un identifiant inconnu; même refus générique;
- limite invalide et curseur malformé.

Les statuts `envoye` et `accepte` de fixture sont produits avec les transitions existantes de `devis_durable`; le listing reste en lecture seule. Les appels des tests utilisent le helper courant de cette suite, qui ouvre une transaction par `executer_atomique` avec des personnes réelles dans la base temporaire; `_vue_projection_effective` revalide leur statut/rôle actif au moment de l’appel. Le chemin exact du runtime `Capacites.appeler` doit encore être couvert par la QA ROOT si nécessaire.

La page est bornée à 1–50 devis; le registre durable est toutefois relu et filtré en entier à chaque requête, puisque le réducteur partagé `devis_durable.lister_devis` rend la liste complète. Le coût du scan n’a pas été benchmarké. Le curseur est non signé et n’est pas une autorisation: une modification ne donne accès qu’aux devis du vendeur actuellement authentifié; le serveur revalide personne, rôle et appartenance du repère.

`PATCH-R2.diff` est le delta depuis r1. Les copies d’origine et leur empreinte restent sous `preimages/` et `PREIMAGES.sha256`; `SHA256SUMS-R2` couvre les deux copies finales, le patch delta et le rapport. Aucune promotion n’a été effectuée.
