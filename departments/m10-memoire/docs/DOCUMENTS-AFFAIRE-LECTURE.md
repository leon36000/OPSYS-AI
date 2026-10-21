# Index documentaire d'une affaire — domaine pur

Cette étape fournit `lister_versions_documentaires(maillons, commande, contexte)`
dans `documents_affaire.py`. Elle ne fournit pas encore les deux outils T0 envisagés,
leur admission SQL/DEVICE, leur raccord Cap/MCP, ni un écran mobile. Les données des
tests et captures sont fictives et produites en RAM par les préparateurs existants.
L'ambition M10 et celle des dix départements restent partielles.

La fonction réutilise l'analyse fermée de toute la chaîne documentaire, les références,
le contexte de lecture et la mesure d'enveloppe existants. Aucun import, constante,
définition ou comportement historique n'est modifié. Elle ne fait aucune entrée/sortie,
ne modifie pas les maillons et renvoie des copies indépendantes.

## Entrée fermée et contexte

`commande` est un dictionnaire Python simple avec exactement trois clés obligatoires :

| Clé | Forme |
|---|---|
| `affaire_id` | Identifiant canonique existant, verbatim, égal au contexte. |
| `decalage` | Entier strict de 0 à 64 inclus. |
| `limite` | Entier strict de 1 à 8 inclus. |

Les booléens, flottants, chaînes numériques, sous-classes, propriétés d'objets,
clés manquantes ou supplémentaires sont refusés. Il n'y a aucun défaut implicite :
la limite initiale 1 sera un choix du futur appelant. Le décalage n'est pas corrigé.

Le contexte T0 existant comporte exactement `affaire_id`, `auteur`, `situation`,
`mode`, `quota`. Les trois modes `ombre`, `supervise`, `autonome` sont admissibles
en lecture. La forme exige un auteur admin de source appareil et une affaire connue,
sans intention, UUID, appareil ni heure de mutation inventés dans le contexte T0.
Ce contexte injecté n'est pas une preuve d'autorité réelle : l'adaptateur futur devra
établir l'identité et le rôle SQL actifs avant toute copie du registre.

## Sortie fermée

L'index comporte exactement sept clés : `version_schema` (1), `affaire_id`,
`decalage`, `limite`, `total_versions`, `suivant_decalage`, `versions`.

Seules les versions de l'affaire demandée entrent dans le total et les pages.
L'ordre suit les indices originaux croissants de `version_source` dans le registre,
même si des entrées d'autres affaires ou des activations s'intercalent.
`total_versions` est au plus 64, issu des bornes historiques de huit documents et
huit versions par document. `suivant_decalage` vaut `decalage + limite` seulement
s'il reste des versions, sinon `null`. Toute page au-delà du total mais dans la borne
0–64 est vide ; `decalage` demandé est conservé. Les pages sont des lectures courantes
indépendantes, pas un snapshot figé entre deux appels.

Chaque ligne a exactement seize clés : les treize métadonnées de `lire_version`,
sans `corps`, plus trois informations de version/précondition.

| Clés | Sens |
|---|---|
| `version_schema`, `affaire_id` | Version 1 et affaire demandée. |
| `document_ref`, `version_source` | Références originales `{registre, index, ligne_id}`. |
| `statut` | `DEPOSEE_NON_ACTIVEE`, `COURANTE`, `HISTORIQUE_NON_COURANTE` ou `RETIREE`. |
| `titre`, `methode`, `source_sha256` | Texte/taxonomie existants, méthode `utf8-exact-v1`, hash des octets du corps source. |
| `taille_points`, `taille_octets` | Tailles source existantes, sans normalisation Unicode ou CRLF. |
| `auteur`, `horodatage` | Auteur et heure du dépôt de cette version, conservés verbatim. |
| `activation_ref` | Dernière activation de cette version, ou `null` si jamais activée. |
| `version_no` | Numéro du dépôt de cette version, de 1 à 8. |
| `version_precedente_attendue` | Référence du dernier dépôt du document, quelle que soit la ligne affichée. |
| `activation_attendue` | Référence de la dernière activation du document, ou `null` si jamais activé. |

L'activation historique d'une ligne ne remplace jamais la précondition courante du
document. Une réactivation A→B→A conserve les deux références distinctes. Une version
2 déposée sans activation ne transforme pas la version 1 active en version historique.
Après retrait, toutes les versions portent `RETIREE`. Le corps reste absent de l'index,
les métadonnées et références historiques restent présentes ; aucun effacement n'est promis.

La lecture détaillée réutilisable reste `lire_version` sans modification : treize clés
après retrait, quatorze avec `corps` autrement. Le texte rendu est celui du dépôt exact,
sans citation vérifiée ou finalité documentaire inventées.

## Quota et refus

L'index mesure la future enveloppe positive complète
`{ok: true, resultat: {accepte: true, resultat: DTO}}` par
`len(json.dumps(..., ensure_ascii=False, allow_nan=False))`, avec les séparateurs
Python par défaut : des caractères JSON, distincts des octets UTF-8 capturés.
Une sortie entière trop grande lève le refus fermé `REJ-M10-DOC-QUOTA-DEPASSE`.
Il n'y a ni fragment, troncature, réduction de page silencieuse ni artefact.
Le domaine pur ne borne pas lui-même la future enveloppe de protocole d'un refus.

La totalité de la chaîne est validée avant projection, y compris les entrées hors page
et hors affaire. Corruption, contexte et arguments inadmissibles lèvent les refus
constants existants, sans texte source ou argument dans le verdict. Les preuves restent
limitées au producteur pur ; transactions, 49 tables SQL, RPC, transport opaque DEVICE,
PostgreSQL, téléphone et UI nécessitent des qualifications distinctes.
