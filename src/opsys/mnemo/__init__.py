"""Mnémo : modèle de soi de l'entreprise, graphe de connaissances d'entités et apprentissage continu gouverné (M10).

Trois pièces, une seule règle : rien ne devient vrai, ni actif, sans source, sans état et sans l'accord d'une personne
quand l'effet est structurant.

- `soi` : le « profil d'entreprise apprenant » — des énoncés versionnés et sourcés (état proposé, confirmé, obsolète),
  construits des faits que les départements publient déjà ; une dérive est une PROPOSITION de révision, jamais un
  écrasement ;
- `graphe` : un graphe d'entités (client, propriété, intervention, matériau, fournisseur, équipe, document, décision) à
  schéma fermé, derrière le port `MoteurGraphe` (adaptateur SQL natif, double en mémoire) ;
- `lecons` et `promotion` : des leçons candidates, mesurées hors ligne, promues par une personne avec canari et retour
  arrière ; aucune ne s'applique seule.

Aucun appel réseau, aucun modèle, aucune horloge cachée : l'instant est toujours passé par l'appelant. Voir
`docs/architecture/M10-SOI-GRAPHE.md`.
"""
