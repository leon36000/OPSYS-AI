# Procédures internes M3 — admission et mémoire documentaire

État antérieur : backend et console privée vérifiés localement par R26. La recherche
hybride décrite ci-dessous est une tranche préparée pour qualification ROOT; ce texte ne déclare pas
encore le parcours HTTP→modèle→PostgreSQL M03 qualifié.
Cette tranche réutilise `MemoireEntreprise` PostgreSQL/pgvector et
sa recherche française. Elle donne à M3 des procédures sourcées; elle ne modifie
aucun calcul de prix ni les règles d'acceptation des devis.

## Parcours et source canonique

Le fichier TXT ou Markdown doit être UTF-8 strict, sans NUL, non vide, de 1 MiB
maximum et produire au plus 100 fragments de 12 000 caractères. L'administrateur
atteste qu'il contient uniquement des procédures internes sans secrets ni données
personnelles. Cette attestation est humaine; aucun détecteur ne la certifie.

1. **Admission** : conserver les octets exacts, leur SHA-256, l'auteur, la version
   de l'extracteur et une clé de rejeu. L'état `RECU` est durable et invisible à M3.
2. **Indexation** : créer les fragments et toutes leurs occurrences dans une
   transaction. L'état `INDEXE` reste invisible tant que la version n'est pas active.
3. **Activation explicite** : comparer l'empreinte courante attendue avant de la
   remplacer. Une concurrence périmée est refusée; l'index préparé peut être repris.
4. **Recherche M3** : sélectionner seulement la version courante et vérifier
   source, texte, positions, lignes et sections avant de rendre une citation. Le mode hybride
   optionnel n'est utilisé qu'avec le provider local et le profil exact attaché aux vecteurs;
   sinon l'outil annonce le repli plein texte.
5. **Oubli** : supprimer toute la série explicitement désignée, ses versions,
   fragments orphelins, vecteurs, occurrences et activation, dans une transaction.

Les UUID initiaux sont générés côté serveur. Une version supplémentaire exige une
série existante. La clé d'admission opaque doit être réutilisée après perte de
réponse : même clé et même contenu donnent la même admission; changer son contenu
est un conflit. Un nouvel identifiant fourni par le client ne crée aucune série.

Le namespace réservé est `opsys-document://<uuid>/<sha256>`. Les attributs libres
d'une mémoire générale ne deviennent jamais des citations vérifiées. La source
canonique est conservée exactement; la normalisation NFC et l'élagage des espaces
servent au texte des fragments. Les positions citées restent des offsets UTF-8
dans le fichier original. Un texte répété peut partager son fragment, tout en
gardant toutes ses occurrences vérifiables.

## Stockage, limites et coût

Le schéma existant reçoit les tables `procedure_series`, `procedure_versions`,
`procedure_occurrences`, `procedure_activations` et
`procedure_admission_oubliees`. Les activations gardent l'auteur et les empreintes
précédente/cible. Les tombstones d'admission ne contiennent que la clé opaque,
sans corps, titre ou identifiant de document.

Les quotas transactionnels comptent aussi les versions reçues et historiques :
64 séries, 8 versions par série et 64 MiB de sources. Les nouvelles opérations
emploient des limites SQL de verrouillage de 2 s et d'instruction de 5 s. Ces
limites ne constituent pas un débit d'ingestion massive.

La portée est imposée par le serveur : `m03-estimation / procedures / interne`.
Les droits d'écriture et l'autorité M03 ne changent pas. Admission, indexation et
activation restent sans appel d'embeddings. Le backfill général continue d'exclure
`opsys-document://`. Une commande d'exploitation distincte peut vectoriser, par
maximum huit fragments, une version explicitement désignée par son UUID et son SHA
actifs. Chaque appel HTTP est hors transaction SQL; avant le commit, l'état `INDEXE`,
les octets/SHA, la source, le fragment et le pointeur actif sont revérifiés. Le CAS
abandonne les résultats périmés après activation ou oubli.

Les colonnes additives `embedding_profile_sha256` et `embedding_status` distinguent
`pending`, `legacy_unknown`, `ready` et `trop_long`. Les embeddings antérieurs sont
`legacy_unknown`, jamais requalifiés par nom de modèle. La recette SHA-256 inclut la
révision et le hash du modèle, le tokenizer, 1 024 dimensions, la tokenisation sans
troncature (512 tokens), pooling CLS, normalisation L2 et préfixes vides. Le provider
authentifié la présente au handshake et à chaque réponse. Une recherche profilée ne
consomme que `ready` au fingerprint exact; la recherche historique sans profil ne
consomme que `legacy_unknown`.

Un refus machine précis `input_token_limit_exceeded` du provider marque `trop_long`
pour cette recette seulement et garde le fragment lexical. Un HTTP 413 générique,
une limite de caractères ou une panne reste une erreur reprenable, jamais une preuve
de longueur-token. Aucun fragment n'est tronqué. Les parcours mixtes de mémoire
conservent leur comportement antérieur.

L'opérateur lance explicitement :

```sh
python -m opsys.memoire vectoriser-procedures --document-id UUID --sha256 SHA256 --limite 8
```

La commande requiert `OPSYS_EMBEDDINGS_LOCAL=1` et le client local avec clé référencée
par l'environnement; elle n'affiche ni texte, ni clé, ni URL de base. Elle ne crée
pas de vecteurs automatiquement à l'admission, à l'indexation ou à l'activation.

Les sorties d'outil sont bornées à 6 000 caractères JSON sérialisés; texte à
4 000 caractères au total, 800 par résultat et trois positions rendues par
citation. Le nombre total d'occurrences et les troncatures restent explicites.
Le contenu est marqué non fiable : intégrité documentaire et origine ne valent
pas validation de sa vérité métier ni permission de suivre ses instructions.

## Effacement et frontières actuelles

L'oubli UUID supprime toutes les versions. Un filtre source/document associé aux
filtres canoniques département/portée/sensibilité retire aussi une admission
`RECU` sans fragment. Les filtres sujet/attribut portent sur les fragments et ne
désignent pas une admission sans fragment. L'oubli d'une version courante remet
le pointeur à NULL; aucune version historique n'est promue implicitement.

Une clé explicitement oubliée ne recrée pas sa source par rejeu. Une nouvelle
clé permet une nouvelle admission humaine. Ce comportement ne s'étend pas
automatiquement à toutes les purges historiques. Aucune durée de rétention des
admissions `RECU` n'est inventée. Une lecture déjà engagée peut avoir chargé un
corps avant son effacement; les lectures ultérieures ne le retrouvent plus.

Il s'agit d'une base par entreprise, pas d'une isolation SaaS multi-tenant
qualifiée. TXT/Markdown seulement : aucun PDF/OCR, classement automatique,
évaluation sémantique représentative ou score global de fusion. La qualification
sur PostgreSQL éphémère ne prouve pas durabilité disque, restauration ou VPS.

## Console administrateur

Depuis Mémoire, « Gérer les procédures M03 » ouvre `GET /memoire/procedures`.
La page liste les métadonnées, huit versions au maximum par série, et la version
active. Elle ne prévisualise pas le fichier. L'admission peut créer une nouvelle
série ou ajouter une version à une série UUID existante.

Les actions HTML sont `POST /memoire/procedures/admettre`,
`POST /memoire/procedures/{uuid}/{sha}/indexer`, `POST .../activer` et
`POST /memoire/procedures/{uuid}/oublier`. L'activation transporte l'empreinte
courante attendue; l'oubli demande la confirmation `OUBLIER` et un motif.
Les champs de département, portée ou acteur sont refusés : le serveur les impose.

Le parseur multipart Starlette existant reçoit un corps borné à 1 MiB + 64 KiB,
un fichier et cinq champs; l'upload est fermé même en cas de refus. Les suffixes
`.txt` et `.md` acceptent `text/plain`, `text/markdown` ou
`application/octet-stream`, avec charset UTF-8 ou absent. L'en-tête est une
déclaration; le contrôle des octets UTF-8 reste au backend. La clé de reprise est
conservée dans une réponse d'erreur lorsque le formulaire a pu être parsé.

Les droits administrateur vivants sont relus avant le corps, après parsing et
après les lectures ou effets; CSRF est obligatoire. HTML et erreurs échappent les
valeurs et ne rendent ni corps, DSN ou message brut du driver. Les réponses sont
privées avec `Cache-Control: no-store`.

L'identité console SQLite et la mémoire PostgreSQL sont deux bases : une
révocation survenue après le commit peut laisser une écriture validée avant le
refus HTTP 403. Cette frontière est explicitement testée; aucune révocation
atomique entre les bases n'est promise.

## Qualification

Le service se trouve dans `src/opsys/memoire/ingestion_procedures.py`, la
persistance dans `store.py` et `schema.sql`, les citations d'outil dans `outils.py`.
Le manifeste M03 ouvre la lecture des procédures. Les tests sont
`test_memoire_ingestion.py`, `test_memoire_store.py` et `test_memoire_outils.py`.

La couverture ciblée de recette/fingerprint et du mode fallback est ajoutée dans
`tests/test_memoire_embeddings_procedures.py`. Le parcours PostgreSQL réel HTTP→provider→
citation est défini dans `tests/test_memoire_embeddings_procedures_local_postgres.py`, opt-in ROOT;
il doit être qualifié avant toute annonce de disponibilité opérationnelle.
Résultats antérieurs, commandes et suite : [lot R26](../programme/LOT-INGESTION-PROCEDURES-M3.md).
Le prérequis du store reste décrit dans [R25](../research/R25-2026-10-02/README.md).
