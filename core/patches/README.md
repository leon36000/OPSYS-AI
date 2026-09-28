# Patchs sur le code source amont (OpenClaw)

Aucun patch pour l'instant : tout passe par les interfaces publiques d'OpenClaw (voir `../UPSTREAM.md`).

Format d'un patch : `NNNN-sujet.patch`, produit par `git diff` depuis la racine du code amont
au commit épinglé, appliqué au build d'une image dérivée (`deploy/Dockerfile.core`) à créer avec
le premier patch.
Première ligne de chaque fichier : `# Raison : …` (pourquoi une interface publique ne suffit pas).
