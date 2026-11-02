# Preuves brutes de la mesure des embeddings (2026-11-02)

Résultats JSON du banc `install/qualification/embeddings_fr/` (`opsys.qualification.mesure-embeddings-fr/v1`) : métriques,
intervalles, trace des cinq premiers passages par question et système, latences et jetons. **Aucun vecteur, aucune clé,
aucune donnée réelle** (corpus fictif). Jamais écrasés ; le nom porte l'horodatage et l'empreinte SHA-256 du corpus.

| Fichier | Corpus | Contenu |
|---|---|---|
| `mesure-20261102T093226Z-7f27ab07.json` | jugements **v1** (avant revue) | première exécution réelle, embeddings seuls (8 configurations), sans trace par question |
| `mesure-20261102T093958Z-91dbf324.json` | jugements **v2** | exécution avec le juge de reclassement (300 appels réels), traces par question |
| `mesure-20261102T094924Z-91dbf324.json` | jugements **v2** | rejeu depuis le cache disque (aucun nouvel appel) avec la matrice d'écarts entre modèles : **source des tableaux du rapport** |

Rapport : [`../MESURE-EMBEDDINGS-FR-2026-11.md`](../MESURE-EMBEDDINGS-FR-2026-11.md).
