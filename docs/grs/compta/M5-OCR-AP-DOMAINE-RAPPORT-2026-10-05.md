# OCR → brouillon fournisseur : domaine et provenance

Statut : domaine qualifié localement sur SQLite; interface OCR/AP et raccord M5 à qualifier séparément.
[Programme](../../programme/PROGRAMME-24H-2026-10-04.md).

## Réemploi et comportement

`fusion_ap` réutilise le candidat OCR chiffré existant, son décodeur strict, la transaction admin,
le CAS et le quota de brouillons. `creer_brouillon_ocr` crée explicitement huit champs vides,
statut `A_REVOIR`. `enregistrer_ocr` corrige ensuite ce brouillon : chaque champ non vide
porte une à trois références page/index/SHA du token courant. Le hash canonique du token inclut
texte, boîte et confiance brute; cette dernière reste non calibrée. Aucun montant n’est transféré.

Une table compagnon `fusion_ap_ocr_sources` lie immuablement le brouillon au run, à sa révision,
à la configuration et au profil. L’absence de cette ligne signifie PDF natif. Le candidat et le
brouillon ont leurs propres AAD chiffrées; leurs lectures revérifient source PDF, révision, run,
configuration et citations dans la transaction courante. La lecture de métadonnées vérifie aussi
la provenance. Une source périmée ne peut pas être réaffectée silencieusement : nouveau lot explicite.

La migration additive 0026 conserve les brouillons et commandes natifs. Leur empreinte de mutation
reste exactement celle du contrat antérieur; la provenance OCR n’est ajoutée que pour OCR.
SQLite applique des triggers contre update/delete de la provenance; PostgreSQL n’a pas ce verrou
SQL dans cette tranche et n’est pas qualifié ici. Le downgrade est refusé si des liens OCR existent.
Le chemin financier et les routes existantes restent natifs : ce livrable seul n’autorise pas M5.

## Vérification ROOT

- Revue r1 : régression de rejeu natif et création OCR non vide directe détectées avant promotion.
  Staging r2 distinct corrigé; préimages et rapports conservés.
- r256 : 298 réussites, quatre échecs conservés. La fixture censée créer un autre lot utilisait
  les mêmes octets et était donc dédupliquée; des assertions de downgrade attendaient encore 0025.
  Les fixtures sont distinctes et le rollback exige maintenant la conservation de 0026 et des données.
- r257 interrompu par ROOT après une erreur de préparation; aucune qualification annoncée.
- **r258 : 302 tests réussis dans quatorze fichiers complets**, zéro échec/erreur/skip.
  Ruff a ensuite signalé trois lignes trop longues dans la migration.
- **r259 : Ruff et contrats verts** après simple formatage; comparaison AST stricte prouve
  que la migration exécutée en r258 conserve exactement sa sémantique.

Les tests couvrent brouillon vide, saisie humaine/citations, rejeu, mauvais lot, source/run/cipher
altérés, AAD, quota/rollback, migration/conservation/downgrade et parcours PDF natifs financiers.
Le runtime OCR de ce raccord est simulé explicitement sur données fictives; cela ne prouve pas
l’extraction OCR réelle ou la précision sur factures clients. Une alerte de dépréciation pypdf
reste dans un test existant de document actif; aucune erreur ni skip ne la remplace.

Preuves : [capsule](../../research/REPRISE-2026-10-05/preuves/OCR-AP-DOMAINE-r1.tar.xz)
et [inventaire](../../research/REPRISE-2026-10-05/preuves/OCR-AP-DOMAINE-r1.json).
