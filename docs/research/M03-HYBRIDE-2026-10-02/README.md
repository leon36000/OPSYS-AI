# Mémoire M03 hybride — preuves du 2 octobre 2026

50 tests unitaires et cinq tests PostgreSQL avec embedder simulé passent. Un scénario réel modèle ONNX→HTTP→PostgreSQL→recherche hybride avec citation→oubli passe également. Les sélections se distinguent; elles ne qualifient pas une qualité premium sur données client.

Le conducteur du scénario réel R1 sort avec le code 1 après le test réussi, sur une double suppression temporaire. Ses postconditions ont été vérifiées indépendamment; le correctif scratch R2 a uniquement une vérification syntaxique et un dry-run, sans rejeu. Les erreurs intermédiaires sont incluses.

[Capsule](M03-HYBRIDE-R1.tar.gz) : 90 membres dont 88 captures, sans poids, environnement ou secret. [Inventaire](CAPSULE-MANIFEST.json). Recette et version vectorielle strictes; sans profil compatible la recherche reste lexicale. Pas de déploiement VPS, corpus client représentatif ou qualification SaaS.
