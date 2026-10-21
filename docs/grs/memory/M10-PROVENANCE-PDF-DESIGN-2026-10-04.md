# M10 — provenance PDF Finance : design du 4 octobre 2026

**Tranche 26 qualifiée localement par ROOT r156. M10 et Fusion restent PARTIEL.**
Ce contrat documentaire adapte l’[audit initial](M10-PROVENANCE-PDF-AUDIT-2026-10-04.md)
et la décision ROOT ; le [rapport](M10-PROVENANCE-PDF-RAPPORT-2026-10-04.md)
conserve le baseline, les rouges et la qualification locale.

## Raccord et autorité

Raccorder le [workflow PDF Finance existant](../../../src/opsys/fusion_pdf.py)
au [registre documentaire M10](../../../departments/m10-memoire/src/m10_memoire/provenance_documentaire.py),
puis montrer sa provenance dans la [fiche PDF privée](../../../src/opsys/console/fusion_pdf_ui.py).
Le propriétaire PDF reste seul autorité des octets, du texte, des fragments,
pages/citations et résultats chiffrés. M10 conserve uniquement une source
**candidate FINANCIAL**, explicitement non validée ; ce n’est ni une
indexation/vectorisation ni un classement documentaire universel.

Réutiliser le registre `m10-memoire/documents`, l’admission, les transitions,
reçus, quotas et transactions privés actuels. Aucun DDL, store générique,
parser, OCR, worker, moteur LLM, Qdrant, apprentissage ou ledger M5 nouveau.
Le contrat CSV `CHAMPS` et ses validations restent inchangés ; CSV et PDF
coexistent dans le même registre avec leurs variants fermés distincts.

## Variant PDF fermé

`type_entree=provenance_documentaire`, `genre=m5.document_pdf_natif`,
`classe=FINANCIAL`, `lot_id` UUID canonique, `source_sha256` hex64 et URI
`opsys-ingestion://m05-financecore/pdf/lots/{id}`. Compléter seulement par :
`auteur` du lot initial, `acteur_transition`, `extracteur`,
`configuration_sha256`, `source_revision`, `revision`, `statut`,
`total_pages`, `code`, `horodatage` zoné. Identifiants et versions bornés,
entiers stricts ; extracteur de forme `pypdf-x.y.z/pdf-natif-n`, acteurs fermés
et UUID exact hexadécimal minuscule 8-4-4-4-12, sans constructeur `uuid` ; aucun champ supplémentaire, nom de fichier, corps, montant,
extrait, clé ou donnée client.

La source — genre, lot, URI, hash, classe, auteur, extracteur/configuration —
est immutable. L’acteur de transition et l’état évoluent. Statuts et codes
reprennent le PDF : `RECU` et `EXTRAIT_PREPARATOIRE` sans code ; extraction
préparatoire de 1 à 20 pages ; autres états zéro page, code cohérent avec
`REFUSE` ou `ERREUR_REPRENABLE`. Une extraction ne vaut pas validation humaine.

## Révisions, atomicité et lecture

Admission nouvelle : `source_revision=1`, révision M10 1. Chaque transition
terminale ou reprise append dans la **même transaction SQLite** que le lot
PDF, quotas, reçu et journal. Révisions M10 consécutives ; après la première
capture, révision source PDF consécutive également. La première capture d’un
ancien lot peut commencer à une révision PDF supérieure à 1, sans inventer
son passé. Ancien lot sans trace : absence explicite. GET et rejeu n’ajoutent
ni rattrapage ni maillon. Révision identique/contenu identique : idempotence ;
conflit de contenu, genre ou source : refus entier.

Le port courant doit être durable SQLite, dans la transaction PDF canonique.
Avant décodage et après append : préflight SQL du seul registre documentaire,
plafonds inclusifs **10 000 lignes, 65 536 octets UTF-8 par ligne,
8 388 608 octets cumulés**. Un dépassement ou une provenance corrompue refuse
503 `PDF_PROVENANCE_INDISPONIBLE`, message générique, avec rollback de toutes
les écritures liées. Ne pas imposer ce bornage silencieusement au store
universel ou à l’ancien chemin CSV.

Le nouveau port `lire_avec_provenance(fabrique, acteur, lot_id)` retourne
`{lot: _vue(lot), provenance: dict | None}` dans une transaction unique,
avec droits, compatibilité et préconditions de clé PDF actuels. Avant rendu,
comparer lot/URI/hash, extracteur/configuration, état, révision source, pages
et code ; incohérence : 503, jamais une absence fabriquée. La fiche existante
`/fusion/pdf/lots/{lot_id}`, sous le préfixe réel, projette les champs typés,
échappés, `no-store` et readonly. Accès/session PDF inchangés ; pages et
citations continuent à passer par le lecteur PDF protégé.

Lecteurs/writers vérifient le chaînage **interne** du registre documentaire.
Aucune ancre externe ou protection contre une réécriture complète cohérente
de base n’est annoncée. PostgreSQL reste hors qualification.

## Qualification ROOT r156

La campagne couvre le variant strict et la non-régression CSV ; SQL réel pour
admission, extraction simulée explicitement, refus, erreur/reprise, dédup et
rejeu ; collisions vérifiées dans le contrat pur. Rollback forcé après append :
lot, résultat chiffré, quota, commandes, journal et provenance inchangés ;
limite réelle de ligne avant décodeur avec compteur nul et rollback post-append
sur un plafond cumulé abaissé au volume de la fixture. Aucun test de remplissage
à 8 Mio ou 10 000 lignes n’est revendiqué dans cette campagne. UI après reconnexion : droits actuels, refus employé,
CSRF, GET sans append, absence historique, `no-store`, mismatch/corruption
fermés sans corps. Préserver les suites PDF intégrales et leur worker confiné
selon environnement, sans présenter un mock comme une extraction réelle.
ROOT r156 passe 1 401/1 401 sur 52 fichiers complets, sans échec/erreur/skip ;
Ruff et vérificateur verts, 1 247 sources sans dérive/OOM. Le PDF reste
préparatoire et cette preuve ne promeut pas M10/Fusion globalement.

## État de la qualification élargie

ROOT a élargi le scope avant lancement à **52 fichiers complets**, dont treize
supplémentaires AP backend/UI et installation PDF. ROOT r153 reste rouge :
**1 398P/3F/0E/0S sur 1 401 cas**, Ruff/vérificateur verts. Corrections :
compteur attendu de deux traces admission+préparation, UUID canonique validé
par grammaire sans modifier la politique de conformité, et réemploi de
l’option RAM de la fixture PostgreSQL réelle. Le double CAS unitaire a aussi
été adapté au contrat du store, sans assouplir celui-ci.

Le test de développement API M10 emploie un vrai PostgreSQL, image locale
`pull=never`, tmpfs 256 Mio et limite mémoire 512 Mio. Ce test est distinct du
raccord financier PDF, qui reste **SQLite uniquement, sans DDL**. ROOT r156
passe les mêmes 52 fichiers et 1 401 cas, sans échec/erreur/skip. La suite
comprend huit nouveaux cas SQL provenance PDF, 63 cas PDF historiques
incluant le worker confiné réel, 49 cas console PDF et 21 cas purs M10 ;
ils sont inclus dans les 1 401, pas additionnés à la campagne. ROOT a vérifié par AST la conservation du premier oracle,
de `CHAMPS` et du corps des gardes CSV déplacées dans le dispatch ; cette
préservation et la qualification PDF locale n’étendent pas le raccord
financier à PostgreSQL, l’indexation ou l’apprentissage.
