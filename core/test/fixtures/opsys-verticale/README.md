# Core et verticale métier réelle

Le job `tests-opsys` lance depuis la racine :

```sh
.venv/bin/python tests/fixtures/qualifier_verticale_core.py --preuve-dir /tmp/preuve-verticale-unique
```

Le dossier de preuve doit être neuf. Le point d'entrée ferme l'environnement du processus Python,
charge les plugins de qualification et exige le cas SQLite 42 unités / marge 114 CAD, zéro skip,
13 phases M8/profil, 9 phases M10, 10 phases isolation développement et 8 phases restauration,
sur les mêmes WCT et devis (40 au total). Les drivers JavaScript réutilisent
les API de production Core via le loader TypeScript existant ; ils ne copient ni handler ni
transport. Ils se qualifient par exécution HTTP, syntaxe JavaScript et lint, sans prétendre à une
lane TypeScript qui exclut les fixtures.

Les environnements Node sont fermés ; seuls les jetons fictifs du scénario sont écrits dans des
manifestes temporaires privés, supprimés en finally et exclus des preuves. Les sorties sont
écrites dès le lancement, même si le délai est dépassé. Les runtimes et SQLite sont fermés en
finally. Les bases, archives natives, clés de base et états Core générés restent dans le dossier privé
de qualification ; l’upload utilise une liste explicite de reçus/JUnit/journaux uniquement.
Les reçus JSON, JUnit et journaux sont conservés par la CI pendant 30 jours ; une capsule
locale indépendante garde l'historique au-delà de cette rétention.

La console ASGI authentifie réellement les écritures et préflights techniques (cookie, CSRF,
révocation de rôle/personne). Les seuls changements de registres autorisés lors de ces écritures
restent dans `m10-memoire/developpement` ; tous les autres maillons sont comparés exactement.
Le paquet métier est identique avant/après. La restauration sélectionne une URL SQLite neuve,
sans remplacement ; le snapshot, puis les appendices export/restauration au journal sont vérifiés.
Un nouveau Python héberge le backend et la vraie console : même contexte technique retrouvé après
restauration, mêmes lectures Core M8/M10. Le répartiteur est exercé au repos sans mutation.

Limites : une affaire SQLite et deux entrées techniques fictives ; fournisseur d'admission injecté,
aucun fournisseur payé. Pas de téléphone, crash pendant effet métier, callback retenu après
révocation, PostgreSQL positif, recherche vectorielle/RAG ou ACL client. Console ASGI TestClient,
sans navigateur/TCP console. Le bus au repos ne rediffuse pas un ancien événement. Les YAML M5/M8
de fixture sont transmis séparément et ne viennent pas de l'export ; état Core/Gateway, sessions,
jetons et index rqa exclus. Pas de réappairage physique. FINANCIAL est conservé dans M10 mais exclu
du paquet de contexte, même pour M5. Le champ `task` réémis par le préflight est exclu des claims
sur les sources effectivement récupérées.
