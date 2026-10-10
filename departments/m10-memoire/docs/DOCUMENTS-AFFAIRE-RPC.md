# Façade documentaire appareil M10 — raccord interne candidat

Cette tranche ajoute trois déclarations et leurs handlers à la fin de la factory
historique M10. Les anciens outils gardent ordre, schémas et comportement. Aucun
nouvel outil de lecture, écran, manifest, rôle généré ou permission Core n'est livré.
Le raccord nommé Cap/MCP est une étape distincte détenue par son owner : les
présentes définitions seules ne qualifient pas un parcours réseau DEVICE.

| Nom | Champs RPC requis, sans défaut | Métadonnées |
|---|---|---|
| `m10_deposer_version_document_appareil` | affaire_id, document_ref, version_precedente, titre, corps, confidentialite | T1/N3, admin, affaire |
| `m10_activer_version_document_appareil` | affaire_id, document_ref, version_source, activation_attendue | T1/N3, admin, affaire |
| `m10_retirer_document_appareil` | affaire_id, document_ref, activation_attendue, code_motif | T1/N3, admin, affaire |

Chaque schéma est un objet fermé. La cible est exactement `("affaire_id",)` et
l'identité de contexte `affaire` ; un identifiant caller n'accorde aucune permission.
Les références fermées portent registre `documents_affaire`, index entier 0–511 et
ligne_id hex64 minuscule. Le dépôt initial exige les deux références nulles ; le
domaine décide les préconditions fraîches. Le texte reste UTF8 exact, titre jusqu'à
120 points, corps 1–2000 points et au plus 8000 octets, confidentialité INTERNAL.
Le code de retrait est RETRAIT_ACCES. Auteur, appareil, clé, heure, quota, situation
et mode ne sont jamais des paramètres RPC. Le validateur JSON Schema minimal du
socle ne remplace pas `documents_affaire.valider_commande`.

## Liaison privée et handlers

`invocation_documentaire_appareil(cnx, *, meta, quota, mode_manifeste)` capture une
dataclass privée frozen dans un ContextVar ; reset en finally, même sur exception.
La connexion doit être canonique courante, ouverte, en transaction et dans un
SAVEPOINT déjà créé par le caller. Il n'existe aucune factory de secours. Le Meta
exact conserve appareil/clé UTF8 verbatim au plus 128 points et l'heure déclarée
valide au plus 40, dont `.000`. Le quota est un entier exact au moins 40 sans plafond
5400/6000 ajouté ; le mode est un membre fermé des modes déclarés. La SQL du backend
refuse ensuite tout mode effectif hors ombre.

Une invocation imbriquée, absente ou contradictoire ferme avec
`RuntimeError("CONFIRMATION-INCONNUE") from None`, avant tout SQL et avant import
lazy du backend. Les handlers réexaminent cette liaison, admettent et copient la
commande avec l'API pure, puis importent `muter_document_m10` localement. Une forme
profonde invalide ferme aussi avant SQL. Une liaison privée ne crée aucune identité
ambiante, n'atteste pas l'appareil et ne remplace pas la personne active/admin SQL.
Elle ne doit être posée que par le futur chemin caller nommé et pour un seul appel.

Les handlers rendent directement la frame publique entière du backend :
`{ok:true,resultat:{accepte:true,resultat:ACK10},rejoue:bool}`. Aucun `depuis_couple`,
réenveloppement générique, nouvelle réclamation, finalisation ou trace n'est ajouté
par cette façade. Le backend seul assure préflight avant claim, effet document,
APP/J, liaison, postflight et preuve OWN. Le caller doit laisser ses RuntimeError
sortir de son SAVEPOINT ; aucune conversion en couple négatif normal après append.

## Confirmation et limites

La confirmation positive conserve la propre intention appareil/clé/outil/hash,
auteur et heure originale. Elle peut confirmer v1 après v2 ou retrait, sans CAS
frais ni effet supplémentaire. Toute ambiguïté, cache corrompu ou refus seul reste
inconnue pour une intention client persistée ; aucun nouveau UUID/body ne doit être
fabriqué pour la débloquer. La traduction wire fermée et son budget sont à raccorder
par Cap/MCP, après rollback. Ces handlers ne font pas cette traduction.

Les tests exercent les vrais handlers déclarés, avec instance SQLite fictive sur
fichier, lead mémorisé par le vrai producteur amont, personne SQL admin et identité
appareil injectée. Les comparaisons observent les 49 tables de cette fixture : effet
nominal seulement document/liaison, claim, APP et journal, sans double trace. Les
reprises, retrait de rôle, modes, JSON cache ambigu, contexte absent/contradictoire,
forme profonde et panne après trace sont exécutés localement. Une réouverture de
moteur SQL n'est pas une preuve de redémarrage de processus.

Ni ce test ni le mot RPC dans les schémas ne prouvent HTTPMCP, Core, jeton opaque,
appairage, scopes serveur, révocation de jeton, PostgreSQL, téléphone ou exposition
mobile. Ils ne prouvent pas la vérité métier du texte ni un effacement des copies
APP. Les trois modules backend gel2 et les captures/lecteurs/purs restent readonly.
La qualification de transport et de permissions courantes complète reste future.
