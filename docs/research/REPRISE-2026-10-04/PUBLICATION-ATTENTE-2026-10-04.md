# Publication de reprise — blocage d'authentification

4 octobre 2026, 21:00 UTC. La tranche 28 est qualifiée localement et préparée
pour la branche `codex/restructuration-2026-09-30`, PR privée #623.
Elle n'a **pas été publiée**.

Le premier accès REST, une lecture de référence sans mutation, retourne
`HTTP 401 Bad credentials`. Les appels du connecteur GitHub retournent
`Unknown tool`. L'environnement cloud reste connecté avec politique réseau
enforced, sans identité de sortie configurée signalée au diagnostic.
Aucune connexion interactive, extraction de token ou autre identité n'est utilisée.

Le dernier head distant observé est
`3f38364284a917239441b86b14e948dbdbaaac6f`.
L'arbre Git local préparé pour les six chemins de la tranche 28 est
`21d34ed70b7c12083bd90afa8fabc73aef65f0bb`.
Ce document supplémentaire reste un compte rendu local hors de cet arbre.
Le plan préparé avait l'index partagé à SHA-256
`59b74da15b867a1fded947b5dec49e34ebcba043d8bd8593728b757aa6a6136f`.
Une lecture `git status` du sous-agent d'audit M7 a ensuite rafraîchi ses
métadonnées : SHA-256 actuel
`f099a697a5f37eeebfe3a01c821ffce2a98f489394c93fbeb49ba0fed523da61`.
ROOT vérifie sur une copie RAM que son arbre de contenu reste
`195856b94278102c2536d4d8035384939c69c61f`, identique au précédent.
Aucun contenu indexé n'a changé et l'index n'a pas été restauré ou réinitialisé.
La reprise doit prendre acte de cette empreinte, après sa propre vérification.

Les [preuves M10 CI](preuves/M10-CI-POSTGRESQL-r1.json) conservent la qualification
ROOT r164 : 1 020 tests passés, 35 fichiers complets, zéro échec/erreur/skip,
ainsi que les contrôles de workflow et le scan de secrets r165.
Archive SHA-256
`486725d0a0cd73e7c40cc123840cb43d134f45ba057b7375f05d95885ecac69e`.

À reprise de l'accès GitHub : relire le head distant et vérifier les empreintes
du plan avant publication sans force, puis observer la CI sur le nouveau SHA.
Si la branche a avancé, reconstruire l'arbre depuis son vrai parent ; ne pas
remplacer l'index partagé ni supposer que le dernier head observé est actuel.
Les autres travaux peuvent progresser localement pendant ce blocage.
