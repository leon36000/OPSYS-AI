# M10 : manifeste durable des imports internes M03

Design de la prochaine tranche autorisée par Nathan : ingestion reprise après interruption,
une seule vérité PostgreSQL, pas de demande de confirmation routinière. Le parcours reste
limité aux procédures internes M03 TXT/MD, de un à cinq fichiers; ce n’est pas l’import
comptable client universel. Le produit global reste PARTIEL.

## Choix

Réutiliser `MemoireEntreprise`, `IngestionProcedures`, la console authentifiée et
`procedure_versions.corps`. Une file n8n/Temporal distincte ou un stockage de corps en plus
n’apporterait pas la transaction nécessaire. Un identifiant de lot dans le navigateur seul
ne permettrait pas une reprise après redémarrage. Le manifeste SQL est retenu.

## Contrats

`creer_lot(cle_lot, sources, *, auteur)` reçoit une clé opaque de 16–128 caractères
et de 1 à 5 descriptions ordonnées : position entière unique de 1 à 5, titre de
1–300 caractères, SHA256 exact du fichier et éventuellement `serie_cible_id`, l’UUID d’une série existante.
La clé opaque est générée dans le formulaire GET avant tout effet et conservée
dans le POST, afin qu’une réponse interrompue reste rejouable. Le manifeste complet est immuable. Sa répétition exacte est idempotente; toute variation
ou tout autre auteur est un conflit. Maximum de 64 lots vivants pour cette tranche.
Toutes les données et extractions des fichiers de la requête sont contrôlées avant le
premier DML. Les noms de fichier bruts et messages d’erreur détaillés ne sont pas conservés.

`admettre_emplacement(cle_lot, position, contenu, *, auteur)` vérifie l’empreinte et
l’identité du manifeste, réutilise l’admission existante avec une clé opaque dérivée
du couple lot/position, puis rattache la version au slot dans la **même transaction**.
L’admission individuelle historique conserve son contrat. Le verrou quota existant
précède les verrous de lot et série partout : admission, reprise, oubli. Une panne
après création d’une version et avant rattachement annule les deux écritures.

`lire_lot(cle_lot, *, auteur)` dérive les états de `procedure_versions` et
`procedure_series` : ATTENTE, RECU, INDEXE et activation courante mesurée. Aucun état
INDEXE recopié dans le manifeste, aucun pourcentage d’assimilation de l’entreprise
inventé. L’auteur d’origine est lié à la commande; seules ses reprises sont acceptées.

Le manifeste ne contient pas les corps. Un slot non admis exige de renvoyer le fichier
exact; son SHA attendu reste stable. Une indisponibilité de stockage arrête les fichiers
suivants. Un succès antérieur reste admis. Le rôle/session doit être revérifié dans
le thread immédiatement avant chaque effet, y compris après l’attente du threadpool.
Aucune indexation, activation, embedding ou action comptable automatique à l’admission.

## Oubli et confidentialité

Avant de supprimer une version documentaire, identifier les lots qui la référencent,
créer un tombstone opaque par clé de lot et supprimer leurs manifests et slots dans
la transaction d’oubli. Cela invalide la reprise de tout lot touché sans laisser titre,
SHA, auteur ou référence de document oublié. Les autres documents du lot ne sont pas
supprimés par cet effet secondaire; leurs versions indépendantes restent accessibles.
Appliquer ce comportement à l’oubli spécifique de procédure et à l’oubli générique.

Les tables et indexes sont créés par `schema.sql`/`migrer()` idempotent sous son verrou
consultatif existant. Aucun nouveau backend ni moteur de migration parallèle.

## Plan et preuves

1. Façade/contrats + tables + helper d’admission transactionnel et oubli des manifests.
2. Tests PostgreSQL réels : migration répétée, redémarrage, rejeu identique, conflit,
   positions non contiguës, deux admissions concurrentes, rollback après création,
   empreinte incorrecte, quota, oubli spécifique/générique, compteurs dérivés et aucune
   activation automatique. Garder les tests individuels antérieurs.
3. Formulaire fermé multi-fichier + GET état/reprise, sessions vivantes, CSRF, limites
   multipart, validation de tout le batch avant admission et succès partiels visibles.
4. Tests console négatifs, PostgreSQL réel intégré, lint, docs, matrice et preuves,
   publication sur branche de travail. Validation native à obtenir après publication.

La responsabilité des écritures est séparée : backend/schéma/façade/tests d’un côté,
console et tests console de l’autre. ROOT contrôle la transaction, l’oubli, la reprise
et l’intégration. Aucun résultat de recherche ou résumé de sous-agent ne remplace
l’exécution des tests sur le code intégré.
