# M10 développement — Raccord au cron natif

Décision du 30 septembre 2026 : réutiliser le runner `command` du Core déjà présent,
sans agent ni modèle. Ce raccord cible une installation où Core et Python sont sur le
même hôte ; les conteneurs séparés de `deploy/` ne sont pas raccordés par ce lot.

1. Écrire un test de génération à partir d'un vrai grant SQLite et observer son échec.
2. Ajouter `openclaw.configuration_cron_memoire_developpement(job_id)` : autorité
   humaine vivante, grant actif, base SQLite fichier, chemins de l'hôte ; aucune commande
   ni identité issue du modèle. Retourner les arguments de déclaration, sans les lancer.
3. La déclaration native est idempotente par `--declaration-key`, quotidienne à 03:00
   dans le fuseau du grant. Elle lance le worker par argv JSON, sans shell intermédiaire,
   sans livraison publique. Le worker reçoit seulement job et référence du credential.
4. Fixer dans le payload les références non secrètes de l'instance SQLite. Ne jamais
   sérialiser des identifiants de connexion PostgreSQL ni une capacité de service.
5. Le CLI humain `configurer-cron --job-id` expose la déclaration après authentification
   interactive ; l'installation de la déclaration reste une opération explicite du Core.
6. Éprouver une échéance avec le véritable Gateway compilé en loopback et des données
   fictives. Vérifier rapport/checkpoint canoniques, reçu du cron et nettoyage des processus.

Propriétés à vérifier : refus sans principal ou après révocation du rôle/grant, absence
de secret dans la déclaration, conservation des chemins spéciaux sans expansion shell,
rejeux identiques, absence d'écriture de rapport pendant la simple génération.
Les résultats de ce lot ne prouvent ni VPS, ni nuit en production, ni PostgreSQL.
