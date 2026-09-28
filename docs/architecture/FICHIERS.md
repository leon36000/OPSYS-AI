# Dépôt de fichiers adressé par contenu (T1.4-e2)

> Complète [ARCHITECTURE.md](ARCHITECTURE.md) (couche Capacités MCP) et
> [ADR-0009](../decisions/ADR-0009-socle-metier.md) §2 (« tout dans la même base »).
>
> Problème résolu : l'app mobile (T1.4-e) capture les photos « après » et la signature du client
> en fichiers locaux avec leur SHA-256, mais aucune route serveur ne recevait le binaire, et
> `m4_completer_intervention` acceptait n'importe quelle chaîne dans `photos_apres`/`signature`.

## 1. Ce que c'est

Un dépôt de fichiers **adressé par contenu** : un binaire (photo après-chantier, signature
client) est identifié par le SHA-256 de son contenu **complet**, jamais par un nom ou un
identifiant choisi par l'appelant. Deux dépôts du même contenu, par n'importe quel appelant,
convergent vers la même ligne — dédoublonnage naturel.

- **Socle, département-agnostique** : `src/opsys/fichiers.py`. Aucun catalogue de verdicts, aucune
  connaissance de M4 — un futur département (M5 reçus de paiement, M7 contenus marketing) dépose
  et lit des fichiers par les mêmes fonctions, avec sa propre traduction de raison de refus vers
  son propre catalogue (§5).
- **Stocké dans la base de l'instance** (ADR-0009 §2), pas un service de stockage séparé : les
  sauvegardes (un seul fichier SQLite, ou un `pg_dump`) restent cohérentes avec le reste du plan
  de contrôle, sans coordination supplémentaire.
- **Deux outils M4** (`departments/m04-field-ops/src/m4_field_ops/outils.py`) : `m4_deposer_fichier`
  (écrit) et `m4_etat_fichier` (lit), tous deux déclarés `roles_appareil=frozenset({"employee",
  "admin"})` (T1.4-j : la portée n'est plus automatique, chaque outil déclare ses rôles ;
  [ROLES.md](ROLES.md)).

## 2. Schéma (migration `0008`)

Deux tables, non préfixées par département (socle partagé, comme `approbations`,
`mutations_appliquees`) :

| Table | Colonnes | Rôle |
|---|---|---|
| `fichiers` | `empreinte_sha256` (PK), `taille_octets`, `type_mime`, `nombre_blocs`, `complet`, `cree_le`, `complete_le` | La déclaration (immuable une fois posée) et l'état d'assemblage. |
| `fichiers_blocs` | `empreinte_sha256` (PK, FK), `index_bloc` (PK), `contenu_base64`, `taille_octets`, `recu_le` | Chaque bloc reçu. |

Contenu stocké en **base64 texte** (`Text`), comme le reste du plan de contrôle (ex.
`cles_chiffrement.cle` en hex) — pas de type BLOB propre à un dialecte, portable SQLite/PostgreSQL
sans code spécifique, cohérent avec `opsys.stockage.codec`.

## 3. Contrat des outils M4 (FIXE — le client mobile code contre lui)

### `m4_deposer_fichier`

| Paramètre | Type | Règle |
|---|---|---|
| `empreinte_sha256` | string | 64 caractères hexadécimaux **minuscules** |
| `taille_octets` | integer | 1..10 485 760 (10 Mo) |
| `type_mime` | string | `"image/jpeg"` \| `"image/png"` |
| `index_bloc` | integer | ≥ 0 et < `nombre_blocs` |
| `nombre_blocs` | integer | 1..64 |
| `bloc_base64` | string | base64 standard du bloc |

Taille de bloc **fixe** : `TAILLE_BLOC_OCTETS = 262144` (256 KiB) octets décodés par bloc, sauf le
dernier bloc d'un fichier (1..262144). `nombre_blocs` doit être exactement celui qu'implique
`taille_octets` à cette taille fixe (`ceil(taille_octets / 262144)`) — un autre découpage pour la
même taille déclarée est refusé.

**Idempotent** : renvoyer un bloc déjà reçu, à l'identique, est un no-op accepté (comparaison sur
le contenu décodé). Un même `empreinte_sha256` annoncé avec une autre `taille_octets`, un autre
`type_mime` ou un autre `nombre_blocs` est refusé — la première déclaration gagne. Un même
`index_bloc` renvoyé avec un contenu **différent** est refusé.

Quand tous les blocs annoncés sont là : concaténation puis triple vérification — taille, SHA-256,
octets magiques du type annoncé (JPEG `FF D8 FF`, PNG `89 50 4E 47 0D 0A 1A 0A`). Toute
discordance **efface les blocs déjà reçus** pour cette empreinte (la déclaration, elle, reste :
un redépôt correct repart de zéro sur les blocs sans redéclarer) et refuse nommé.

Retour accepté :
```json
{"accepte": true, "resultat": {"reference": "fichier:sha256:<hex>" | null, "complet": bool, "blocs_recus": [0, 1, ...]}}
```
`reference` n'est non nul que si `complet` est vrai.

Refus :
```json
{"accepte": false, "verdict": {"code": "REJ-FICHIER-...", "statut": "", "detail": "..."}}
```

| Code | Quand |
|---|---|
| `REJ-FICHIER-PARAMETRES-INVALIDES` | Forme d'un paramètre invalide (type, format, régex, `bloc_base64` non décodable, longueur du bloc reçu incohérente avec sa position pour la taille/nombre_blocs annoncés **dans cet appel**). |
| `REJ-FICHIER-TROP-VOLUMINEUX` | `taille_octets` hors 1..10 485 760, ou un bloc reçu dépasse 262 144 octets décodés. |
| `REJ-FICHIER-INCOHERENT` | La même empreinte est déjà déclarée en base avec une autre taille/type/nombre_blocs, ou le même `index_bloc` revient avec un contenu différent. |
| `REJ-FICHIER-EMPREINTE-DISCORDANTE` | Le contenu assemblé a la bonne taille mais un SHA-256 différent de l'empreinte annoncée. |
| `REJ-FICHIER-TYPE-NON-PERMIS` | Le contenu assemblé n'a pas les octets magiques du `type_mime` annoncé. |

Note de conception (pas une clause du contrat fixe, qui ne porte que sur les six paramètres et la
forme des deux réponses) : la distinction entre `PARAMETRES-INVALIDES` (défaut de CET appel, seul)
et `INCOHERENT` (conflit avec un état déjà en base, ou avec un autre bloc déjà reçu) est un choix
d'implémentation de `opsys.fichiers.deposer_bloc`, documenté dans son docstring et testé
(`tests/test_fichiers.py`) — un autre agent qui lirait un code différemment peut le signaler, la
FORME des réponses ne change pas.

### `m4_etat_fichier`

Paramètre : `empreinte_sha256` (même forme). Retour, **toujours accepté** (l'outil ne refuse que
si `empreinte_sha256` n'a pas la forme attendue, `REJ-FICHIER-PARAMETRES-INVALIDES`) :
```json
{"accepte": true, "resultat": {"existe": bool, "complet": bool, "blocs_recus": [0, 1, ...], "reference": "fichier:sha256:<hex>" | null}}
```
Permet à l'app mobile de reprendre un envoi interrompu (redémarrage, perte réseau) sans
retransmettre les blocs déjà reçus.

### Idempotence d'appareil (T1.4-b)

Chaque bloc est un appel d'outil distinct. Un appel d'appareil qui porte sa propre
`opsys/idempotencyKey` (par bloc) passe par `Capacites._appeler_idempotent`
(`docs/architecture/IDEMPOTENCE.md`) : un renvoi de la même clé, du même outil et des mêmes
arguments rejoue la réponse enregistrée **sans ré-exécuter**. `opsys.fichiers.deposer_bloc` reste
en plus idempotent de son propre chef (comparaison du bloc déjà reçu) pour un renvoi qui
arriverait sans cette clé — ex. reprise après redémarrage de l'app, où l'appareil régénère ses
clés d'idempotence mais retransmet le même bloc numéroté. Les deux mécanismes ne se contredisent
jamais : le second est un filet, pas un remplacement du premier.

## 4. `m4_completer_intervention` : preuves vérifiées, pas seulement bien formées

Avant T1.4-e2, `preuves_completion.photos_apres`/`signature` n'étaient validées que
**structurellement** (`m4_field_ops.preuves.valider_preuves_completion`, INCHANGÉ) : une liste de
chaînes non vide, une chaîne pour la signature si requise — n'importe quelle chaîne inventée
passait.

Désormais, **après** cette validation structurelle et **avant** l'écriture du Work Completion
Trigger (aucune écriture si une référence ne résout à rien) : chaque référence de `photos_apres`
(toujours), et `signature` (seulement si `signature_requise` est vrai — voir note ci-dessous),
doit avoir la forme `fichier:sha256:<hex>` et désigner, dans le dépôt, un fichier **complet** d'un
type permis :
- `photos_apres[i]` : `image/jpeg` ou `image/png` (n'importe quelle image).
- `signature` : `image/png` seulement (capture de signature côté mobile).

Sinon : refus nommé `REJ-PREUVE-FICHIER-INTROUVABLE`, fail-closed, rien n'est écrit ni publié —
même discipline que les six autres contrôles déjà en place sur cet outil (checklist, notes, etc.).

Note de portée : quand `signature_requise` est faux, `signature` reste, comme avant T1.4-e2, soit
`None` soit n'importe quelle chaîne non vide (le contrat structurel de `preuves.py`, inchangé) —
elle n'est PAS vérifiée contre le dépôt dans ce cas. Le PLAN T1.4-e2 demande « la signature (si
requise) » ; élargir la vérification à une signature fournie mais non requise serait un
changement de comportement distinct, non demandé ici.

## 5. Réutilisation par un autre département (M5, M7)

`opsys.fichiers` n'importe rien de `m4_field_ops` et ne connaît aucun code `REJ-*` : un autre
département dépose et lit des fichiers par les mêmes fonctions (`deposer_bloc`, `etat`,
`reference_pour`, `empreinte_depuis_reference`, `empreinte_valide`), et traduit lui-même les
raisons génériques (`DepotResultat.raison` : `"parametres_invalides"`, `"trop_volumineux"`,
`"incoherent"`, `"empreinte_discordante"`, `"type_non_permis"`) vers son **propre** catalogue de
verdicts fermé — exactement comme M4 le fait dans `outils.py::_depuis_depot_fichier`. Aucune
modification du socle n'est nécessaire pour cela ; `TYPES_MIME_PERMIS` (aujourd'hui limité aux
deux types dont M4 a besoin) est un point d'extension évident le jour où un autre usage (ex. PDF
de reçu M5, image de contenu M7) l'exige — décision hors périmètre de cette tranche, à ne pas
anticiper sans besoin réel (AGENTS.md : jamais de donnée ou de capacité inventée par anticipation).

Convention d'isolement des départements (aucun import croisé entre paquets `mN_*` dans ce dépôt,
constaté avant cette tranche) : un futur département n'importe jamais `m4_field_ops`, seulement
`opsys.fichiers`.

## 6. `m4_lister_interventions` : fenêtre planifiée et technicien assigné

Ajout de deux clés par intervention, rendues **seulement quand le registre les porte** — jamais
inventées (fail-closed) :

- **`technicien_assigne`** : le `technicien_id` de la **dernière** transition `en_route` de
  l'intervention dans le registre (`etats.py::_technicien_assigne_durable`), ou `null` tant
  qu'aucune n'a eu lieu. C'est un fait **historique** : un report ou une annulation ultérieurs
  laissent ce champ tel quel (à lire aux côtés de `statut` pour l'image complète, pas comme une
  affirmation d'assignation courante).
- **`fenetre_planifiee`** : **toujours `null` aujourd'hui**. `m4_planifier_intervention` calcule
  une fenêtre (`cedule.generer_cedule`, fonction **pure**, sans registre) et la renvoie à
  l'appelant de CET appel, mais ne l'écrit **à aucun maillon** — le registre ne porte donc
  structurellement aucune fenêtre à ce jour, pour aucune intervention. Persister le choix de la
  cédule (nouveau champ de maillon, ou un type de maillon dédié) est un changement de la machine
  à états de M4, hors périmètre de cette tranche (« ce qui reste », rapport de livraison) — non
  entrepris ici sans décision explicite, pour ne pas improviser une modification structurelle
  (CLAUDE.md : lire `ARCHITECTURE.md` avant toute modification structurelle).

## 7. Loi 25 : limites et rétention

Les photos après-chantier peuvent montrer des personnes, des plaques d'immatriculation ou des
adresses ; la signature est une donnée personnelle du client. `docs/compliance/politiques/`
contient une politique adjacente et pertinente :
[`POLITIQUE-photos-non-contractuelles.md`](../compliance/politiques/POLITIQUE-photos-non-contractuelles.md)
(M3 Estimation, PLAN T2.3). Constats de lecture, avant d'agir :

- Son propre index (`docs/compliance/politiques/README.md`) l'attribue explicitement à **M3**
  (« Gardée par le code fail-closed (`m3_estimation.politique_photos`, PLAN T2.3) tant qu'elle
  n'est pas validée ») — aucune entrée pour une politique de photos M4 dans cet index, ni dans son
  propre « backlog » de politiques à venir.
- Son état est `STATUT_VALIDATION: proposition` (non validée par Nathan/un juriste) et sa garde de
  code (`m3_estimation.politique_photos.verifier_collecte_photo_autorisee`) est scopée, par audit
  et par tests, à la **future capacité de vision de M3** (Phase 2 : SAM2/OpenCV) — M3 ne lit ni ne
  stocke aujourd'hui aucun octet d'image, et « aucun appel de ce module n'existe encore ailleurs
  dans `src/m3_estimation` ».
- §1 de cette politique dit vouloir couvrir, **plus tard**, « la documentation avant/après d'un
  chantier (M4...) » : c'est une intention de portée future, pas une garde déjà câblée ni
  indexée pour M4 aujourd'hui.

Conclusion, sans rien inventer : **aucune politique actuellement validée ni actuellement indexée
ne conditionne, à ce jour, la collecte des photos de chantier de M4** — donc pas de garde fermée
ajoutée ici (une garde qui bloquerait tout dépôt d'image aurait rendu impossible le contrat
fonctionnel demandé par cette même tranche, T1.4-e2 point 3 : déposer un fichier réel puis
compléter une intervention). Ce que ce point laisse, honnêtement, en suspens :

- **Durée de rétention des fichiers (`fichiers`/`fichiers_blocs`) : non fixée.** Aucune purge
  n'existe. La politique M3 propose, pour son propre usage, 24 mois après la fin du chantier ou le
  refus du devis (elle-même marquée « à vérifier » par un juriste) — un point de départ possible
  pour une future politique M4, jamais codé en dur ici sans décision humaine.
- **Accès et journalisation** : `m4_deposer_fichier`/`m4_etat_fichier` portent l'autonomie standard
  des outils M4 (T1/T0, RBAC `employee`/`admin`) ; aucun contrôle d'accès PAR intervention n'existe
  au niveau du dépôt lui-même (il est intervention-agnostique, adressé par contenu seul) — la
  restriction « le client ne voit que ses propres photos » (P8, DEFINITION-PRODUIT.md) doit être
  appliquée par la couche qui EXPOSE une référence à un client (hors périmètre de cette tranche,
  purement serveur : aucune route client n'existe encore).
- **Avant toute collecte réelle de photos de client en production**, une politique M4 dédiée
  (même patron que `POLITIQUE-geolocalisation.md`, déjà validée pour le GPS terrain) reste à
  écrire et faire valider par Nathan ou un juriste (T3, AGENTS.md : « engagements externes : humain
  seul ») — recommandé, non entrepris ici : cette tranche est un contrat serveur, pas une décision
  de politique.

## 8. Ce que ce point ne fait pas

- Aucune route HTTP publique : le dépôt n'est atteignable que par les outils MCP (`opsys-mcp`,
  ADR-0009), comme tout le reste du plan métier.
- Aucune conversion, redimensionnement ni floutage d'image (P8/`POLITIQUE-photos-non-
  contractuelles.md` §5 : le floutage, quand il existe, est une étape de M7 au moment d'une
  publication proposée — jamais de ce dépôt).
- Aucun quota par intervention, par technicien ou par instance (seule la limite par fichier,
  10 Mo, existe).
- Aucune suppression ni purge (§7).
