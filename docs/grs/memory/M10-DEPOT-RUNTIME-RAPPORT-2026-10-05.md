# M10 — dépôt privé lié au profil runtime

Statut : opération privée implémentée et vérifiée localement. La file Core n’est pas encore envoyée automatiquement par ce lot.

## Comportement réel

`opsys_runtime_deposer_faits` est accessible uniquement sur la route runtime existante liée au profil et protégée par son jeton privé. Elle n’apparaît pas dans le catalogue métier et la politique générée interdit les outils runtime aux agents. Elle accepte une affaire, un à vingt faits fermés, un horodatage explicite et la révision de profil. Le profil et son département viennent de la route et de la base, jamais d’arguments du modèle.

Le propriétaire réutilise le contrat de `m10_deposer_faits_candidats`, contrôle le profil actif/non supprimé, sa révision et chaque outil source autorisé. Les mêmes droits sont revalidés avant commit sous la transaction existante. Le dépôt M10 utilise son véritable registre durable ; aucune seconde base ou nouvelle migration. Panne, compteur incohérent, révocation durant la transaction ou changement de base annulent tous les maillons. Les erreurs privées sont fermées et ne recopient pas les détails d’exception.

L’ACK accepté est émis après sortie de la transaction : profil/révision/département/engine, affaire, mêmes clés dans leur ordre et compteurs exacts. Un dépôt déjà connu confirme zéro écriture et tous les faits déjà déposés. Une clé divergente refuse sans remplacer le premier fait.

## Qualification

R330 conserve la preuve rouge de l’opération absente : 19 échecs et un refus de catalogue déjà correct. R331 : 18/20 ; les deux échecs proviennent de la réutilisation interdite d’un manager MCP à cycle de vie unique. La reprise recrée le vrai serveur au redémarrage simulé, sans changer l’assertion d’idempotence. R332 : 26/26 pour le nouveau parcours complet. R333 conserve deux erreurs Ruff sur des contextes async imbriqués ; leur combinaison garde ordre et nettoyage.

**R334 : 147/147 dans huit fichiers complets, Ruff et manifestes réussis**, sources gelées inchangées et aucun OOM. Le nouveau fichier couvre vingt faits, tc40/tc64 conservés, replay après libération/réouverture de la base, refus de conflit et de droits, arguments fermés, mauvais jeton, panne au second maillon, faux/absents/booléens compteurs, révocation dans la transaction, changement de base et deux appels MCP concurrents suivis d’un rejeu sans doublon. La chaîne durable M10 est vérifiée.

Les appels traversent le vrai serveur MCP HTTP via transport ASGI, le vrai service M10 et SQLite. Ce n’est pas encore une preuve du réseau TCP depuis le Core, du drain de l’outbox ou d’un provider métier. La concurrence SQLite du cas de test ne qualifie pas PostgreSQL ni toutes les interleavings possibles.

## Limites explicites

- Le jeton hôte est une frontière de confiance : cette opération atteste les observations de l’hôte, sans prouver cryptographiquement le résultat d’un outil distant.
- L’affaire a la forme canonique ; elle vient du ticket capturé par le Core dans la chaîne prévue. Cette route ne revalide pas une affectation actuelle de l’affaire et ne reçoit pas de ticket historique durable. Elle écrit seulement des traces candidates fermées, sans lecture de données client ni mutation métier.
- La provenance de profil est présente dans l’ACK ; le registre candidat canonique historique conserve le département et les faits, sans nouveau champ durable de profil. Le registre de provenance complète reste à étendre explicitement.
- Un profil retiré/périmé refuse la livraison ; le futur sender doit garder le lot pour reprise ou revue. Il ne doit pas inventer un nouveau profil ou convertir sa révision.
- Aucun drain Core, timer, cron, ACK de la nouvelle outbox, exactly-once global, build Core complet ou déploiement n’est livré par cette opération seule.

Plan et prochain raccord : [livraison de l’outbox](../../programme/M10-ENVOI-OUTBOX-2026-10-05.md). L’audit Luna est une lecture statique ; son erratum confirme que le collector courant garde tc40. La variante tc64 n’est pas substituée aux clés déjà capturées.

## Preuves incrémentales

[Capsule](../../research/REPRISE-2026-10-05/preuves/M10-DEPOT-RUNTIME-r1.tar.xz) — SHA-256 33c678d76701103dc6caad6dd97381f135d2799940bd8071da9cb30e508800fb.
[Inventaire et bases référencées](../../research/REPRISE-2026-10-05/preuves/M10-DEPOT-RUNTIME-r1.json).
Toutes les références aux deux capsules antérieures et toutes les nouvelles entrées ont été relues et vérifiées. Le rapport avant ces liens est conservé ; le scan cible les sources/docs, pas toute l’archive.
