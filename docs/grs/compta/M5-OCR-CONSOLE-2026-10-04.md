# M5 — Revue privée du texte OCR

État : **QUALIFIÉ LOCAL — composant r206**. M5 et OPSYS-AI restent **PARTIEL**.
Cette tranche relie le candidat OCR déjà stocké et chiffré à la console privée.
Les changements restent locaux, non publiés ; la qualification porte sur le périmètre ci-dessous.

## Parcours et configuration

L’opérateur du serveur peut définir `OPSYS_INGESTION_OCR_BUNDLE` avec le chemin
absolu du bundle préalablement provisionné et validé. Variable absente ou vide :
action OCR désactivée. La fabrique Python reçoit explicitement `bundle_ocr` ;
elle ne consulte pas implicitement l’environnement. Le lanceur transmet ce
choix. Le décodage de configuration ne lit, ne crée et n’installe aucun fichier.
La disponibilité et les empreintes des ressources sont vérifiées par le service
OCR lors du calcul, avant l’inférence. Un chemin syntaxiquement valide ne prouve
pas la disponibilité du bundle ou des namespaces Linux.

Un propriétaire ou administrateur actif ouvre un lot PDF refusé pour
`PDF_IMAGE_OU_MIXTE`, puis demande explicitement le calcul. Le POST conserve les
contrôles de session courante, CSRF, révision source et idempotence. Aucun chemin
bundle n’est accepté depuis HTTP. La réponse dirige vers le candidat du run lié
à ce lot ; ses tokens sont rendus comme texte échappé, sur des blocs bornés,
avec des réponses privées `no-store` et un avertissement de vérification humaine.
L’identité et les rôles sont relus après les opérations longues.

La revue déchiffre uniquement un candidat `A_REVOIR` encore lié à sa source courante.
Les états sans résultat ont des explications fixes : document refusé, calcul
interrompu, résultat périmé ou calcul réservé. Une réservation n’est jamais
présentée comme la preuve qu’un worker est encore actif. Le refus ou l’erreur
ne relance pas le calcul. Les pages ne révèlent ni code interne ni ciphertext.
Le POST vérifie aussi que le run renvoyé est lié au lot et à la révision demandés.
Elle ne préremplit pas de montant, ne transforme pas le texte en facture,
ne crée ni saisie AP ni écriture financière. Les erreurs affichées sont génériques :
les chemins, clés et détails internes restent hors de la page.

## Fichiers

- `src/opsys/console/ocr_configuration.py` : opt-in serveur strict.
- `src/opsys/console/application.py` : raccord du lanceur et des routers.
- `src/opsys/console/fusion_pdf_ui.py` : action explicite sur lot admissible.
- `src/opsys/console/fusion_pdf_ocr_ui.py` : POST calcul et GET revue privée.
- `tests/test_console_ocr_configuration.py` et `tests/test_console_fusion_pdf_ocr.py` :
  contrôles de configuration, d’accès et de rendu.

## Limites et suite

Le stockage OCR demeure limité à SQLite. La qualification antérieure du worker
est une exécution Linux locale sur source synthétique ; elle ne qualifie pas
l’image serveur, un VPS, un corpus client ni la précision comptable. Le bundle
n’est ni embarqué ni téléchargé automatiquement. Les réservations abandonnées
ne disposent pas encore d’une reprise administrative. Cette revue ne relance
pas automatiquement les calculs en erreur et n’interprète aucun résultat comme
une donnée vérifiée.

Voir [stockage et limites](M5-OCR-STOCKAGE-2026-10-04.md),
[worker qualifié localement](M5-OCR-WORKER-2026-10-04.md) et
[audit image/VPS](M5-OCR-IMAGE-AUDIT-2026-10-04.md).

## Qualification ROOT et preuves

r206 : **179/179**, huit fichiers complets, aucun échec/erreur/skip ; Ruff et
vérificateur métier passent. 1 302 chemins source/ressources surveillés restent
stables, 51,161 secondes pour la campagne avec le parcours réel ; pas de hausse
OOM ni de processus survivant signalé. Les huit fichiers incluent 15 tests
configuration, 14 revue OCR, 49 console PDF native, 46 console générale, 19 centre
de configuration, 7 référence AP M5, 4 saisie AP M5 et 25 service OCR. Les
anciennes campagnes se recouvrent : leurs totaux ne s’ajoutent pas à 179.

La preuve externe ROOT démarre la vraie application avec `TestClient` et
l’opt-in serveur, admet le PDF bitmap fictif r190 (12 194 octets, SHA
`a8487a4255aac8d40d5f88d635045a14a4f80a1b535757a53f610fdca3348d22`),
prépare réellement le PDF natif, obtient le refus image, appelle le worker
OCR sous bubblewrap et lit les trois tokens depuis le résultat SQLite/AES-GCM
(935 octets chiffrés). Les snapshots de toutes les tables hors compartiment
OCR restent identiques pendant le calcul ; toutes les tables restent identiques
pendant le GET et le rejeu du même POST. Le worker n’est pas rappelé au rejeu.
Le serveur HTTP est simulé par TestClient ; ce n’est pas un déploiement réseau.

Les tests de route conservent de vrais SQLite/AES, mais simulent le profil et
l’inférence : source inter-lot réellement différente, CSRF, doublons/champs
inconnus/query/chemin HTTP, révision, retrait de rôle après calcul ou lecture,
source périmée, XSS échappé, découpage de 129 tokens en 128 + 1, et absence
de mutation des tables à la lecture. Ces tests ne mesurent pas la reconnaissance.

La revue RO du routeur a identifié une lacune fonctionnelle : les états durables
sans candidat produisaient un faux 404. ROOT ajoute cinq cas : r205 **9P/5F**,
avec échecs d’assertion HTTP constatés avant correction. Les états viennent de
véritables transitions SQLite : refus et timeout simulés au bord de l’inférence,
source modifiée pendant l’inférence, et réservation conservée après retrait de
rôle. La correction r206 rend ces états sans appeler `lire_resultat`, conserve
le refus des liens lot-run divergents et renforce l’association au POST.
Le cinquième cas fournit un retour de service incohérent au POST et exige son
refus avant redirection. Les quatorze tests UI font partie des 179.

r201 conserve **15 assertions rouges** avant le câblage de configuration.
Le RED du writer UI est une erreur de collecte car le module n’existait pas,
pas neuf assertions rouges. r202 passe Ruff/vérificateur et stocke réellement
le candidat ; l’échec de GET vient du harness TestClient qui doublait le préfixe
`/opsys`. Son script et son log sont conservés. r203 corrige uniquement cette
simulation d’URL dans un script distinct, avec les mêmes assertions du parcours.
La revue ROOT remplace aussi les libellés techniques affichés par du français,
sans modifier les états métier. Les sorties intermédiaires de développement
du writer UI ne sont pas toutes enregistrées en fichiers : elles restent dans
le transcript d’outils, hors capsule. Son RED collecte et ses GREEN9/Ruff
finaux sont conservés, sans reconstitution des sorties absentes. Les campagnes
ROOT disposent chacune de leurs journaux distincts.

La capsule `docs/research/REPRISE-2026-10-04/preuves/M5-OCR-CONSOLE-r1.tar.xz`
et son manifeste JSON conservent les journaux, JUnit, préimages, drivers,
rapports et fermeture source sélectionnée. Les binaires/modèles externes et
bases SQLite privées de test ne sont pas redistribués. Aucun secret de client
n’est utilisé. La dernière lecture GitHub (4 octobre 23:21:32 UTC) retourne
401 sans mutation distante ; elle ne justifie aucune affirmation de publication.
