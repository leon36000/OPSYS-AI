# Fusion — avancement des imports M03 privés

Date : 4 octobre 2026. Design de tranche, avant implémentation. M10 reste PARTIEL.

## Problème observé et résultat attendu

La synthèse Fusion compte les versions effectivement admises, mais ne montre pas les
emplacements ATTENTE des nouveaux manifestes d'import. Un lot interrompu peut donc
sembler absent de cette vue. Le hub Fusion ne mène pas encore à « Mes imports ».
L'administrateur doit pouvoir voir ses documents attendus/reçus/indexés/actifs et
retrouver le parcours de reprise, sans confondre ces nombres avec une connaissance
validée de l'entreprise.

## Réutilisation retenue

Étendre `console/fusion_synthese.py` et le hub dans `fusion_pdf_ui.py`; réutiliser
`IngestionProcedures.lister_lots(auteur=identité serveur)` et les manifestes PostgreSQL
déjà qualifiés. Aucun nouveau magasin, moteur, extraction ou brique externe nécessaire
pour cette projection. CSV/PDF/AP gardent leurs propriétaires et états actuels.

Ajouter une carte « Mes imports M03 » séparée des séries/versions partagées : lots,
emplacements déclarés, ATTENTE, RECU, INDEXE et actifs. Ne jamais additionner ces
compteurs avec les versions de la carte existante, ni les afficher comme documents
validés, rappel ou pourcentage d'assimilation. Les cartes sont des observations à
des instants distincts, pas un snapshot multi-base atomique.

## Contrats et contrôles

- Lecture seule, aucun appel modèle/embedding ni activation ou admission implicite.
- Filtre d'auteur dérivé de la session vivante, jamais du formulaire ou de la query.
- Au plus 64 lots; référence unique SHA-256 valide, 1–5 emplacements par lot,
  compteurs entiers non négatifs, ATTENTE + RECU + INDEXE = emplacements,
  actifs <= INDEXE. Une projection incohérente devient indisponible.
- Vérifier l'autorité avant/après lecture et avant réponse. Une révocation refuse
  l'écran; elle ne doit pas produire un écran partiel contenant des métadonnées.
- Source en panne : état indisponible, sans détail d'exception, jamais zéro.
- Aucune référence, titre, corps, SHA de document, identité d'autre auteur ou valeur
  métier dans les compteurs. Lien vers la liste privée existante seulement.
- Réponse `private, no-store`; paramètres inconnus refusés avant toute lecture.

## Qualification requise

Tests HTTP authentifiés des liens, compteurs, autre auteur, panne, projection
incohérente et révocation. PostgreSQL réel : manifeste partiel → admission/indexation/
activation → oubli, avec compteurs dérivés et zéro copie; les chiffres déjà qualifiés
ne remplacent pas cette preuve. Régression des quatre cartes existantes et des
imports, Ruff ciblé, sources gelées et contrôle de secrets avant publication.

## Limites

Procédures internes M03 seulement. Aucune ingestion universelle, OCR, corpus client,
fusion comptable finale, note de connaissance, qualité ou entraînement automatique.
Les cartes partagées et les lots personnels ont des périmètres distincts, explicités
à l'écran. Une carte disponible n'atteste pas que tous les magasins sont disponibles.
