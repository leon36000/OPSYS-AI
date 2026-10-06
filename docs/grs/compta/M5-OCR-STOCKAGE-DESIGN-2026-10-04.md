# M5 — compartiment OCR durable, design adapté au worker qualifié

**EN COURS**, 4 octobre 2026. Le worker `ocr_runtime.extraire_candidat` est
qualifié localement (r190,245/245 et appel binaire réel) ; stockage et revue
ne le sont pas encore. Les qualifications image/VPS et corpus métier restent
ouvertes. L’OCR complet et M5/OPSYS-AI restent PARTIEL.

## Données et migration additive

Ajouter trois tables `fusion_pdf_ocr_runs`, `fusion_pdf_ocr_commandes`,
`fusion_pdf_ocr_quota`, migration0025 après0024. Aucun changement des tables
PDF/AP/CSV/M10 existantes. La source PDF déjà chiffrée reste dans son lot ;
le nouveau run la référence sans copie. Le périmètre local reste SQLite.
Le résultat brut seul (tokens/coordonnées/scores compris) est chiffré.

Run UUID, FK pdf_lot_id, acteur d’admission, source_sha256, revision_pdf_source,
configuration_sha256 et profil_id explicites ; clé référencée sans secret,
version_format1, revision_run, statut, réservation, nonce/cipher/octet, code et
horodatages. Identité source et profil immuables au niveau service. Une unique
clé (PDF,source SHA,révision,configuration) permet la déduplication. Commandes
uniques par acteur/mutation, empreinte de requête et FK run. Pas de texte OCR
ou détails financiers dans les colonnes claires, les traces ou M10.

États : RESERVE (quota maximal engagé, pas de payload), A_REVOIR (ciphertext
présent, aucune réservation restante), REFUSE/ERREUR_REPRENABLE/PERIME
(pas de payload/réservation, code générique obligatoire). Quota séparé,
16 runs maximum et4194304octets cipher/réservés. Le nombre de runs compte
les métadonnées même après échec ; il ne faut pas libérer ce compteur tout
en conservant un historique illimité. Reprise d’un même run pourra réutiliser
son entrée, avec révision/CAS ; aucun retry implicite de transport.
Les commandes ont leur propre plafond global de256 entrées, contrôlé dans
la transaction d’admission après recherche d’idempotence. Au plafond, une
commande connue reste relisible ; un nouvel alias ne peut plus être enregistré.
La reprise administrative des runs abandonnés n’est pas implémentée dans ce lot.

JSON≤262144 octets ⇒ AES-GCM ciphertext≤262160 et base64≤349548.
Contraintes DB : taille, versions/révisions, lien état/payload/réservation,
nonce/base64 bornés. Les seules contraintes ne remplacent pas les contrôles
SQL avant lecture ni la validation de contenu du service. Downgrade refuse
si des runs/commandes ou réservations existent ; aucune purge automatique.

## Admission et finalisation

API interne prévue `preparer(fabrique,acteur,pdf_lot_id,revision_source,
mutation_id,*,bundle)` et lectures de métadonnées/résultat privées. Reprendre
la fabrique et l’identité admin/owner actives du PDF natif. Autoriser seulement
le PDF natif refusé pour PDF_IMAGE_OU_MIXTE, source et révision authentifiées.
Le worker structurel distingue ensuite le scan simple du mixte et peut refuser.

Dans une transaction SQLite : lire les métadonnées bornées, contrôler le lot
source et la clé, re-hasher le clair, vérifier profil opt-in, puis atomiquement
réserver262160octets et une entrée, créer run RESERVE et commande. Même clé
et empreinte renvoient le même run ; empreinte divergente = conflit. Le calcul
se déroule après commit sans connexion ni verrou conservés. Une seconde
transaction revalide acteur, source/hash/révision/cipher et configuration,
valide le candidat, chiffre puis fait CAS du run attendu et réconcilie le quota.
Aucune écriture du résultat natif, AP, dette, approbation comptable ou M10.

Un acteur révoqué pendant calcul interdit la livraison du résultat. Le service
ne contourne pas l’identité pour "nettoyer" sa réservation : transaction non
qualifiée = aucune mutation ; une reprise administrative contrôlée sera requise
pour le run abandonné. Ne pas affirmer un remboursement de quota qui n’a pas
pu être autorisé/committé. Une divergence source sous identité encore valide
peut marquer PERIME et restituer la réservation sans exposer de corps.

## Chiffrement et bornes avant lecture

Réutiliser le loader de clés externe `fusion_csv._cle/_reference_cle` et
la primitive `_aesgcm`, avec nonce aléatoire12octets. AAD propre OCR, JSON
canonique versionné liant runUUID, PDFUUID, sourceSHA, révision source, profil,
configuration et révision résultat. Ne pas réutiliser `_chiffrer/_dechiffrer`
CSV : leur AAD a un préfixe CSV différent. Aucun secret nouveau persistant.
L’AAD doit aussi lier l’acteur d’admission et la version du format. Le profil
courant est `ocr-scan-2` ; le premier worker `ocr-scan-1` demeure une preuve
historique, pas un profil de stockage compatible courant.

Avant toute récupération de payload, sélectionner uniquement métadonnées et
longueurs SQL/octet (cast LargeBinary), puis récupérer les colonnes cipher avec
WHERE conservant ces plafonds et types dans la même transaction. Refuser base64
ou nonce trop grands avant transfert vers Python, y compris le source PDF.
Les contraintes SQL de longueur ne prouvent ni le type SQLite effectif, ni
l’alphabet base64, ni l’authenticité du ciphertext. Ces vérifications relèvent
du service : métadonnées SQL de type/octet, sélection bornée, décodage strict,
puis tag AES-GCM et contrat du candidat. Listes et déduplication sélectionnent
les seuls identifiants avant toute lecture de payload.
Déchiffrer puis authentifier source/profil/révision, decoder_candidat et bornes
JSON avant sortie. Refuser corruption/AAD incorrecte sans texte dans exception.

## Vérifications nécessaires

Migration additive depuis0024 avec lignes legacy conservées, quota indépendant,
contraintes et downgrade protégé. Service : quota avant calcul, idempotence,
concurrence, verrou SQLite, revalidation acteur/source, CAS, bornes SQL avant
lecture, erreurs/rollback de chiffrement et compteurs, AAD négatives, profil
manquant, PDF non éligible et aucune mutation native/AP/M10. Un vrai parcours
source refusée native→OCR confiné→ciphertext→lecture humaine préparatoire est
nécessaire ; les doubles déterministes vérifient les courses et pannes seulement.
La console privée viendra ensuite, avec session/CSRF/no-store et échappement,
sans saisie ou mapping comptable automatique.
