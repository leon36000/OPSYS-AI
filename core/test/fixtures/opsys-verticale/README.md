# Core et verticale métier réelle

Le job `tests-opsys` lance depuis la racine :

```sh
.venv/bin/python tests/fixtures/qualifier_verticale_core.py --preuve-dir /tmp/preuve-verticale-unique
```

Le dossier de preuve doit être neuf. Le point d'entrée ferme l'environnement du processus Python,
charge les plugins de qualification et exige le cas SQLite 42 unités / marge 114 CAD, zéro skip,
13 phases M8/profil et 9 phases M10 sur les mêmes WCT et devis. Les drivers JavaScript réutilisent
les API de production Core via le loader TypeScript existant ; ils ne copient ni handler ni
transport. Ils se qualifient par exécution HTTP, syntaxe JavaScript et lint, sans prétendre à une
lane TypeScript qui exclut les fixtures.

Les environnements Node sont fermés ; seuls les jetons fictifs du scénario sont écrits dans des
manifestes temporaires privés, supprimés en finally et exclus des preuves. Les sorties sont
écrites dès le lancement, même si le délai est dépassé. Les runtimes et SQLite sont fermés en
finally. Les reçus JSON, JUnit et journaux sont conservés par la CI pendant 30 jours ; une capsule
locale indépendante garde l'historique au-delà de cette rétention.

Limites : une affaire SQLite ; le fournisseur du contrôle d'admission est injecté (trois tokens
ou une exception synthétique), aucun fournisseur payé. Redémarrage HTTP dans le même processus
Python et nouveaux processus Node. Pas de téléphone, crash pendant effet métier, callback retenu
après révocation, PostgreSQL positif, recherche vectorielle/RAG ou isolation dev/métier qualifiée
par ce raccord. FINANCIAL est conservé dans M10 mais exclu du paquet de contexte, même pour M5.
