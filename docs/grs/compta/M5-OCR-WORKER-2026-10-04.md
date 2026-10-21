# M5 — worker OCR local et bundle opt-in

**QUALIFIÉ LOCAL — composant r190**, 4 octobre 2026. Composant Python appelable,
sans endpoint, stockage, installation automatique ou écran de revue. M5/OCR
complet/OPSYS-AI restent **PARTIEL**. Rien n’a été publié sur GitHub dans cette
tranche ; la CI native et le VPS ne sont pas qualifiés par ces essais.

## Fonctionnement effectivement exercé

`ocr_profil.py` vérifie le bundle déjà installé ; `ocr_runtime.py` reçoit les
octets d’un PDF et un lot/révision explicites, monte seulement les fichiers
validés, puis appelle le worker borné sous bubblewrap. `ocr_worker.py` active
les limites, crée le lecteur PDF en confinement, applique la grammaire
[structurelle qualifiée](M5-OCR-STRUCTURE-PDF-2026-10-04.md), puis rend et appelle
Tesseract uniquement si la page est candidate. La sortie est directement le
JSON candidat validé par `ocr_candidat.py`, sans enveloppe PNG/TSV en base64.

Le profil reçoit sa configuration du code, jamais du PDF. Le SHA source, UUID
lot, révision, configuration et profil sont vérifiés à nouveau par le lanceur. Le profil
`ocr-scan-2` ajoute explicitement `--dpi 150` à Tesseract et vérifie la
distribution pypdf avant import, puis version et chemins effectifs du module
et du lecteur avant parsing. Ce contrôle de chemin ne vérifie pas le hash
de tous les fichiers Python de la distribution.
Le texte machine reste littéral et non fiable, y compris du HTML ; aucune
correction ni interprétation de fournisseur, montant, taxe ou compte.
Le pump enfant traite stdin/stdout/stderr simultanément, applique un délai,
refuse toute erreur diagnostique et récupère le processus. Aucun repli sur
un parser ou moteur exécuté hors confinement.

## Profil volontairement étroit

Linux x86_64, pypdf 6.19.0 / Pillow 12.3.0, pypdfium2 5.13.0 et PDFium 153.0-7999,
Tesseract 5.5.0 / Leptonica 1.84.1. Le wheel officiel, tous ses membres RECORD,
les trois packages extraits, la bibliothèque PDFium et le modèle français
ont leurs empreintes vérifiées. Le binaire Tesseract est également épinglé.
Le lanceur n’installe ni extrait ni télécharge rien. Le bundle fermé contient
`wheel.whl`, `rasterizer/` et `tessdata/fra.traineddata` ; propriété/permissions,
symlinks, objets spéciaux, profondeur et nombre d’entrées sont contrôlés.
Les fichiers montés sont revérifiés avant import dans le worker.

Une page, source ≤1 Mio, 150 DPI, raster ≤4 Mpx et 4096 pixels par axe,
PNG ≤512 Kio, TSV ≤256 Kio, JSON ≤256 Kio. Limites natives AS 512 Mio / CPU 10 s,
mur 15 s global et 8 s enfant. L’AS est une limite par processus, pas une preuve
d’un plafond mémoire agrégé de déploiement. L’empreinte du binaire et les
versions ne qualifient pas toutes les bibliothèques système transitives.
L’image, l’installateur, les namespaces/cgroups de la cible, la provenance
complète des dépendances système et le prévol VPS restent à vérifier.

## Preuves ROOT

r190 : **245/245**, six fichiers complets, zéro échec/erreur/skip :
82 contrat OCR +63 PDF natif +34 structure +29 profil +23 lanceur +14 worker.
Ruff et vérificateur métier réussis ; 1 293 chemins source/ressources identiques
avant/après, compteurs OOM inchangés, aucun survivant signalé par les gardes.
Campagne : 16,528 s. Ces cas recouvrent r182 ; ils ne s’additionnent pas à son total.

Le vrai parcours utilise une nouvelle pièce **fictive**, créée sans modifier
les deux anciens scans : un bitmap valide contient « FACTURE FICTIVE TEST ».
Le worker produit trois tokens, dimensions 1 275 × 1 651, statut
`CANDIDAT_A_REVOIR`, source 12 194 octets SHA
`a8487a4255aac8d40d5f88d635045a14a4f80a1b535757a53f610fdca3348d22`.
Les 31 fichiers des packages extraits sont vérifiés. Bundle et binaires restent
hors du dépôt et de la capsule ; les références/hashes permettent leur contrôle.
Ce test de trois mots n’est pas une mesure de précision comptable ou fr-CA.

r188 contrôle séparément les deux scans historiques via le nouveau worker
réel : deux refus `OCR_STRUCTURE_REFUSEE`, conformes à la grammaire actuelle.
Les tests de pipes emploient des processus Python fictifs ; les tests de profil
emploient un mini-wheel/modèle fictifs avec empreintes patchées. Ils ne
remplacent pas le parcours binaire réel ci-dessus. Aucun corps OCR n’est écrit
dans une base, un journal métier, AP ou M10 par ce composant.

## Historique des tentatives

r184 : 21 assertions négatives (module absent), avec limite du log déclenchée.
r185 conserve ensuite les 21 assertions négatives et le log compact complet.
r186 : vérificateur réussi, trois erreurs de lint ROOT, avant tout appel OCR.
r187 reprend après corrections de forme uniquement, sans changer les règles :
240/240 et premier parcours réel réussis. Revue ROOT/Luna ensuite : résolution
Tesseract non explicitée et contrôle pypdf après import. r189 prouve les quatre
écarts ciblés (9P/4F). r190 qualifie le profil corrigé avec cinq cas de plus
(245/245) et un nouveau parcours réel ; les reçus r187 restent historiques.
Les logs agent disponibles sont conservés : le premier rouge profil est une
erreur de syntaxe de fixture, le second une collecte sans module ; aucun de
ces deux fichiers n’est présenté comme 29 assertions comportementales rouges.
Les tests worker ont été ajoutés après son code ; pas de revendication TDD
universelle. La prochaine extension devra conserver cette distinction.

## Suite autorisée

Compartiment OCR séparé et chiffré, quota réservé avant calcul, AAD liée au
lot/source/révision/profil, idempotence et revalidation après calcul, puis
revue privée humaine sans cache. Le résultat PDF natif et son refus restent
intacts ; aucun AP prérempli, aucune dette ni paiement. Voir le
[design du worker](M5-OCR-WORKER-DESIGN-2026-10-04.md).

Preuves : [capsule](../../research/REPRISE-2026-10-04/preuves/M5-OCR-WORKER-r1.tar.xz)
et [inventaire](../../research/REPRISE-2026-10-04/preuves/M5-OCR-WORKER-r1.json).
