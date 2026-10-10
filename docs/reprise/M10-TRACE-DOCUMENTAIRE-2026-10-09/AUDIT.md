# Capture M10 et fermeture des restitutions — 9 octobre 2026, Toronto

OPSYS-AI reste PARTIEL. Base de préparation : 6d35d3acd958dbcfe2603eda3d9c72dd7dbb35a0.
La qualification CI de cette base sera vérifiée avant intégration ; la CI du
nouveau commit restera à obtenir séparément.

La capture technique APP/J utilise les PK natives des INSERT, dans la connexion
canonique et le SAVEPOINT fourni par l’appelant. Les INSERT et retours historiques
restent compatibles. Trois noms documentaires futurs reçoivent un masque statique
des champs plats corps/extrait dans les restitutions APP ; le titre reste visible.
Le SQL brut et les empreintes ne sont pas modifiés. Ce lot ne livre ni writer,
claim, liaison document/APP/J, autorité SQL/DEVICE, quota transactionnel ou RPC.

Le propriétaire a exécuté 119 tests verts et un skip PostgreSQL (Docker local
inaccessible), Ruff et contrôles de provenance/ressources. Root a reproduit par
SQL deux divulgations de corps sur arguments APP JSON tableau/chaîne, puis
vérifié leur fermeture constante au gel2. Six rouges ciblés du propriétaire ont
été conservés puis sont devenus verts. Les 113 résultats du gel1 sont historiques,
sans addition aux 119 du gel2. La contre-revue indépendante du code et des AST ne
relève aucun P1/P2 matériel ; elle n’est pas une nouvelle exécution des tests.
Les vérifications fraîches sur le primaire restent une condition de publication.

Les essais portent sur SQLite fictif et TestClient ASGI pour API/HTML. Ils ne
qualifient pas PostgreSQL, Core, un téléphone, HTTPMCP ou une mutation documentaire
complète. Une sonde HTTP/stdio de quota a été qualifiée séparément avec fakeCap,
sans base ; ses résultats ne sont pas crédités à cette capture.

Les 104 pièces de preuve exclues du transfert léger, son supplément absent et
les conversations indisponibles restent absents. Les paquets et rouges existants
sont conservés, et chaque fichier de ce lot est rapproché de sa préimage exacte.
La continuation reste sur la PR privée en brouillon #623 ; aucun force-push,
merge principal ou déploiement de production n’est autorisé ici.

REGISTRE.json couvre les quatre sources et les trois supports. Les sept empreintes
finales sont portées par le manifeste externe et les objets Git du commit ;
aucune empreinte auto-référente du registre n’est fabriquée.
