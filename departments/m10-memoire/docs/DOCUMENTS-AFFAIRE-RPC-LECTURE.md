# Façade des lectures documentaires T0

Deux déclarations sont ajoutées à la fin de `outils()`, après les vingt-quatre
déclarations historiques. Leurs handlers rendent directement l'enveloppe entière
du backend interne ; ils n'utilisent pas `depuis_couple` et n'ajoutent pas `rejoue`.
Cette étape n'établit pas encore une qualification Cap/MCP, Gateway ou téléphone.

| Outil | Arguments obligatoires fermés |
|---|---|
| `m10_lister_documents_affaire_appareil` | `affaire_id`, `decalage`, `limite` |
| `m10_lire_version_document_affaire_appareil` | `affaire_id`, `document_ref`, `version_source` |

Les deux outils sont T0/N0, admin appareil, de portée `affaire`, cible
`("affaire_id",)` et identité de contexte `affaire`. Le schéma interdit les clés
supplémentaires. Les signatures n'ont ni défaut ni kwargs libres. L'index accepte
un décalage entier strict 0–64 et une limite entière stricte 1–8 : le choix initial
1 doit être explicite. Les références non nulles réutilisent exactement le schéma
documentaire historique `{registre, index, ligne_id}`, indice 0–511.

Le raccord privé est `invocation_lecture_documentaire_appareil(cnx, *, quota,
mode_manifeste)`. Il stocke un contexte frozen dans une ContextVar remise à zéro
dans `finally`, refuse une invocation imbriquée, et exige la connexion SQLite
canonique ouverte en transaction, le quota entier positif et un des trois modes.
Aucun Meta de mutation, UUID, appareil ou heure n'est inventé pour cette lecture.
Ce contexte n'autorise pas l'action : le backend confirme l'identité ambiante
typée et l'admin actif SQL avant le corpus documentaire.

Sans contexte privé admissible, ou avec arguments malformés, le handler lève
`RuntimeError("LECTURE-DOCUMENTAIRE-INDISPONIBLE") from None` avant l'import lazy du
backend. Les exceptions fermées du backend sortent ensuite sans traduction dans
la façade. Le futur raccord Cap nommé devra en établir la portée avant sa factory,
et conserver ces refus sans echo de données ou repli ARTEFACT.

Le retour positif a exactement la forme
`{ok: true, resultat: {accepte: true, resultat: DTO}}`. L'index a sept clés et des
lignes de seize métadonnées sans corps ; le détail existant a treize clés après
retrait ou quatorze avec corps. Voir [le contrat pur](DOCUMENTS-AFFAIRE-LECTURE.md)
et [le backend de lecture](../../../docs/architecture/M10-LECTURE-DOCUMENTAIRE.md).

Les captures de cette étape passent par les vrais handlers, sur SQLite temporaire
et corpus/documents fictifs créés par les APIs existantes. Identité ambiante et
contexte privé sont injectés : ce ne sont pas des captures HTTP, MCP, Core ou DEVICE
opaque. Les déclarations historiques et leurs AST sont conservés ; l'oracle de liste
complète 24→26 relève de la qualification de métadonnées séparée du propriétaire.
