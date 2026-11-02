"""Réglages de direction (CFG-1) : ce que la direction décide, adopté par un geste N3, lu par les départements à
travers une couche unique. Voir `docs/architecture/REGLAGES-DIRECTION.md`.

- `declaration` : le schéma fermé du bloc `reglages:` d'un manifeste et la validation d'une valeur ;
- `magasin` : les valeurs adoptées (registre append-only chaîné) et le retour arrière ;
- `lecture` : la précédence (adopté > fichier > absence), la superposition utilisée par les départements, l'état pour la
  console et l'outil « quels réglages manquent ».
"""
