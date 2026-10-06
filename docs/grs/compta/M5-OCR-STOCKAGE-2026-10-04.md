# M5 — candidats OCR durables et chiffrés

**QUALIFIÉ LOCAL — composant r198**, 4 octobre 2026 UTC. Le service interne
`fusion_pdf_ocr` et la migration0025 fonctionnent sur SQLite. M5, l’OCR complet
et OPSYS-AI restent **PARTIEL**. Cette tranche n’ajoute aucun endpoint ou écran,
aucune saisie AP et aucune action comptable. Elle reste locale, non publiée.

## Fonctionnement démontré

Le service reçoit un lot PDF déjà refusé pour `PDF_IMAGE_OU_MIXTE`, sa révision,
l’acteur admin/owner actif, une mutation idempotente et un bundle explicitement
administré. Il authentifie et déchiffre la source existante, réserve le quota
dans une transaction, puis appelle le [worker confiné](M5-OCR-WORKER-2026-10-04.md)
hors connexion et transaction. Une nouvelle transaction revalide l’identité,
les références du run, le PDF, son ciphertext/nonce et le profil avant toute
finalisation. Aucun parsing PDF ou moteur OCR de repli sur l’hôte applicatif.

Les trois tables ajoutées sont `fusion_pdf_ocr_runs`, `fusion_pdf_ocr_commandes`
et `fusion_pdf_ocr_quota`. Source PDF, AP, CSV et mémoire restent dans leurs
compartiments actuels. Le candidat brut est chiffré AES-GCM avec une AAD propre
liant UUID run/PDF, acteur, SHA/révision source, profil/configuration, empreintes
des ressources, référence de clé, version et révision du résultat. La clé
provient du loader externe existant ; aucun secret nouveau stocké en base.

Lectures et déduplication n’importent pas un ciphertext avant contrôle :
projection SQL des types/tailles en octets, sélection bornée, base64 strict,
tag AES-GCM et contrat du candidat. La cohérence état/réservation/payload est
vérifiée aussi dans le service, y compris pour des lignes dont les contraintes
SQL ont été contournées dans une fixture de corruption.

## Limites, états et reprise

Profil `ocr-scan-2`, JSON≤262144octets, ciphertext≤262160 et base64≤349548.
16 runs au maximum,4Mio de ciphertext ou réservation et256 commandes par
instance. Les deux plafonds de runs/octet s’appliquent ensemble ; ils ne
garantissent pas16 réservations maximales simultanées. Les échecs libèrent les
octets, tout en conservant le run comptabilisé pour borner l’historique.
Une mutation connue reste relisible au plafond des commandes. Un alias
nouveau ne relance pas l’OCR et respecte son propre plafond.

`RESERVE` → `A_REVOIR`, `REFUSE`, `ERREUR_REPRENABLE` ou `PERIME` via CAS.
Une divergence de source/profil sous identité valide invalide le candidat.
Un acteur révoqué pendant le calcul interdit la transaction finale : le run
reste réservé. Une panne de quota ou un conflit CAS annule les écritures de
finalisation. Ces réservations abandonnées nécessitent une future reprise
administrative : aucun retry, remboursement forcé ou nettoyage automatique
n’est livré. Aucun statut n’atteste l’exactitude comptable des tokens OCR.

`preparer`, `lire`, `lire_resultat` et `lister` sont des interfaces Python
privées. PostgreSQL est refusé pour ce service ; l’essai PostgreSQL ci-dessous
porte uniquement sur la migration et le stockage commun, pas sur l’OCR.
Downgrade refusé si runs, commandes ou quota non vide seraient supprimés.

## Preuves ROOT et historique

r198 : **410/410**,13 fichiers complets, zéro échec/erreur/skip, Ruff et
vérificateur métier réussis. La fermeture source/ressources est inchangée,
les compteurs OOM restent identiques et les gardes ne signalent aucun survivant.
1299 chemins source/ressources surveillés,45,691s ; fermeture sélectionnée,
pas une inspection de tous les fichiers du dépôt.
Les tests comprennent34 cas du schéma OCR,25 du service, les245 cas du worker,
contrat et PDF natif, et les migrations/stockage/AP/autorité des agents concernés.
Ces sous-comptes sont inclus dans410 ; les campagnes antérieures ne s’additionnent pas.

Le parcours réel ROOT utilise le PDF bitmap **fictif** r190,12194octets,
SHA `a8487a4255aac8d40d5f88d635045a14a4f80a1b535757a53f610fdca3348d22`.
Extracteur natif réel → refus image → worker OCR réel sous bubblewrap →
trois tokens → candidat AES-GCM935octets → relecture après déchiffrement.
Quota réconcilié à935octets, une seule entrée ; mutation et alias relus sans
nouvel appel moteur. Snapshot PDF/quota natif et registres inchangé en r198.
La reprise r199 étend le snapshot à toutes les tables `fusion_*` hors nouveau
compartiment OCR, incluant AP et CSV, avec un nouveau parcours binaire réel.
Il ne s’agit ni d’un corpus client ni d’une mesure générale de précision.

r192 :4P/3F AP, helper de tests supposant la tête0024 et des tables postérieures
présentes au retour0023. Correction du périmètre historique et du rollback à
la révision réellement initiale ; r1937/7 puis r19441/41 avec trois pannes DDL
OCR vérifiant rollback intégral et conservation du PDF. r19760P/1F révèle une
autre assertion de tête0024 dans la migration d’autorité des agents ; elle
est remplacée par la tête du registre Alembic, avec assertions métier conservées.

r195 : vraie verticale réussie et340P/1F ; PostgreSQL sur disque échoue avant
readiness avec `initdb ENOSPC`. r196341/341 puis r198410/410 configurent la
fixture de **vrai PostgreSQL17** en tmpfs256Mio et conteneur512Mio à travers
un harness QA externe explicite. Aucun fichier ou assertion PostgreSQL du
dépôt n’est modifié, aucun test ignoré. Cela ne qualifie pas sa persistance
sur disque ni un VPS. La configuration et les journaux rouges sont conservés.

Les premiers logs RED des agents sont des erreurs de collecte sans module,
pas des dizaines d’assertions rouges. La revue a ajouté huit cas de concurrence,
quota et corruption, puis ROOT a renforcé les contrôles d’état ; aucune
revendication de développement intégralement TDD n’est faite.

## Suite

Revue privée avec session vivante, CSRF, échappement du texte non fiable et
réponses sans cache ; configuration bundle exclusivement administrateur,
désactivée par défaut. Qualification image/installateur/VPS et corpus métier
toujours requise. Le profil Docker existant a une limite de namespaces connue ;
ne pas déclarer l’OCR disponible parce que les seuls paquets sont installés.
Le [design de stockage](M5-OCR-STOCKAGE-DESIGN-2026-10-04.md) conserve les
choix et limites ; les preuves r192–r198 sont archivées avec leurs versions.
