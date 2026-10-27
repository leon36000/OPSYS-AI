# CRM07 — catalogue de modèles et clauses versionnés

## Objectif et état actuel

Le secrétariat peut créer un modèle textuel, modifier sa description de travaux et ses clauses,
et retrouver chaque version précédente. Il ne doit pas recopier un document pour conserver l'ancien texte.
Audit préalable : [AUDIT-MODELES-SOUMISSION.md](AUDIT-MODELES-SOUMISSION.md).
CRM07 reste **PARTIAL** : le catalogue est une tranche distincte; le rattachement d'une version à un devis,
les champs de quantités/prix préremplis et la reprise des clauses dans HTML/PDF restent à implémenter.
La console expose cette limite avant toute saisie. Aucun modèle juridique ni clause légale n'est préinstallé.

## Architecture, fichiers et données

- `m3_estimation/modeles_soumission.py` : domaine déterministe, version, CAS, intention, empreinte, validation du journal.
- `m3_estimation/outils.py` : collection durable M3 `modeles_soumission`, autorité SQL, heure serveur, audit atomique.
- `opsys/console/modeles_soumission_ui.py` : formulaire, catalogue et anciennes versions.
- `opsys/console/metier.py` : port privé admin; `capacites.py` refuse les voies générique et profil.

Un modèle contient `modele_id`, titre, description des travaux, clauses. Chaque version cite sa révision,
auteur admin, horodatage serveur, source et prédécesseur. Le journal contient l'intention et l'empreinte des cinq
arguments métier; l'audit technique ne copie ni titre, ni description, ni clauses.
La version précédente demeure intacte; le texte est une donnée échappée, jamais du code ni une expression de template.
Le stockage existant et ses transactions sont réutilisés. Aucun autre département ou registre de devis n'est reconstruit.

## Routes et workflow

- `GET /crm/modeles-soumission` : catalogue, formulaire de création.
- `GET /crm/modeles-soumission/{id}?version=N` : version précise; `0` ou absence signifie dernière.
- `POST /crm/modeles-soumission/enregistrer` : nouvelle version, révision attendue, intention, CSRF.
- Outils privés : `m3_enregistrer_modele_soumission`, `m3_lire_modele_soumission`, `m3_lister_modeles_soumission`.

Depuis la liste des soumissions d'un projet, ouvrir « Modèles de soumission ».
Créer un texte ou ouvrir la dernière version; son formulaire est prérempli. Enregistrer ajoute une version.
Une ancienne version est consultable sans formulaire d'écrasement. Les liens précédent/suivant parcourent l'historique.
Le même POST renvoie son reçu initial. Une intention réutilisée avec une autre charge ou une révision périmée reçoit409.
Deux rédacteurs sur une même révision ne peuvent pas gagner simultanément.

## Bornes et intégrité

Catalogue trié par identifiant, 25 modèles par page, curseur lié à la tête du journal.
Un changement entre deux pages impose une reprise409; aucun résultat ancien n'est mélangé silencieusement.
Maximum1 000 versions au total dans cette première tranche; au-delà, refus explicite.
Titre120, description4 000, clauses12 000 caractères, identifiant100. Le quota de sortie UTF-8 est contrôlé avant écriture.
Corps de formulaire borné200 000 octets; champs inconnus/dupliqués refusés. Pas de troncature silencieuse des textes.
Les empreintes et contrôles de séquence détectent les altérations incohérentes; ils ne constituent pas une signature
contre une réécriture complète et cohérente de la base par un administrateur d'infrastructure.

## Permissions, intégrations et gates

Admin humain actif confirmé dans SQL, à chaque lecture/écriture/rejeu. Aucun grant vendeur, appareil, agent ou MCP ajouté.
SQLite : écriture et audit dans la transaction existante, CAS durable. Writer PostgreSQL fermé en attente de qualification.
Pas d'envoi, signature, engagement, prix recalculé, notification ni événement M10 produit par ce catalogue.
Aucun devis existant, accepté ou non, n'est modifié lorsqu'un modèle change.
Les règles d'envoi et d'approbation des devis restent celles de M3. M10, mobile et navigateur sont encore à raccorder/qualifier.

## Tests et prochaines étapes

Tests domaine : versions, copies indépendantes, CAS, mutation contradictoire, rejeu ancien, quotas, limite de source,
corruption et rechaînage sémantiquement invalide, pagination, texte et horodatage.
Tests HTTP/SQLite : vrai formulaire, création/révision/historique, réouverture, révocation, CSRF, limites,
audit rollback, rédacteurs concurrents, catalogue paginé et absence de mutation d'un devis accepté et de son document.
Les résultats exécutés sont conservés dans les reçus privés `crm-modeles-qa-20261027-r1` du workspace.

Étape suivante obligatoire : sélectionner une version exacte lors de la création de la soumission,
figer sa source et ses textes dans le devis, étendre la projection client partagée HTML/PDF sans coût interne,
puis démontrer que les devis acceptés restent identiques après révision du catalogue.
La modification des modèles ne doit jamais réécrire rétroactivement les soumissions.

## Qualification exécutée le 27 octobre 2026

La sélection de tests domaine et HTTP/SQLite compte **386 réussites, 0 échec, 0 saut** (26,84 s).
Ruff passe; le vérificateur valide 10 départements, 281 outils dont 173 déclarés aux appareils.
Cette population recoupe les tests CRM et agenda antérieurs : elle ne s’additionne pas à leurs résultats.
La revue indépendante a trouvé deux défauts corrigés : conservation du premier saut de ligne HTML
et refus des identifiants `.`/`..`. Leurs régressions font partie de cette sélection.
Le premier passage reste conservé : 367 tests réussis mais trois erreurs de format Ruff, ensuite corrigées.

Les tests utilisent uniquement des données fictives, un HOME privé, la source en lecture seule et
un réseau interdit, avec limites effectives de 1 GiB, un CPU et 96 tâches. Le processus QA est fermé.
Reçu durable : `crm-modeles-20261027-r1/QUALIFIED-CLOSED.json` dans le chantier du workspace.
Cette preuve qualifie le catalogue et ses routes HTTP/SQLite; elle ne qualifie ni navigateur natif,
ni writer PostgreSQL, ni application automatique du modèle à un devis. CRM07 reste PARTIAL.
