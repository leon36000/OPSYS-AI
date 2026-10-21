# OCR financier — qualification du contrat candidat

4 octobre 2026 UTC. **Tranche 27 : frontière JSON/TSV qualifiée localement.
M5, Fusion et OPSYS restent PARTIEL; aucun OCR activé dans le produit.**

## Comportement livré

[Le contrat](M5-OCR-CONTRAT-2026-10-04.md) est implémenté dans
[`ocr_candidat.py`](../../../src/opsys/ocr_candidat.py). L'orchestrateur doit
fournir un contexte immuable source/lot/révision/configuration/profil. Le
validateur refuse les JSON inconnus, doublonnés, hors bornes ou incohérents;
l'adaptateur reprend le TSV hiérarchique Tesseract, ses mots, coordonnées et
scores bruts. Il ne corrige aucun identifiant ni montant et renvoie toujours
`CANDIDAT_A_REVOIR`. Un changement de famille de composant est refusé même si
le nom ressemble à une version valide.

Le module ne lance aucun processus, ne lit aucun fichier et ne touche ni DB,
M10, fournisseur, facture, approbation ou clé. Aucune dépendance ajoutée, aucun
upgrade, modèle téléchargé ou binaire redistribué. La configuration du futur
worker devra mesurer et vérifier les identités du profil; la concordance des
métadonnées du candidat ne remplace pas ce prévol.

## Preuves ROOT

| Exécution | Résultat et portée |
|---|---|
| r159, avant module | **0P/78F/0E/0S** : capacité absente, import différé et assertions explicites, pas une erreur de collecte |
| r160, après première version | **78P/4F/0E/0S** : quatre cas de revue reproduisent l'acceptation d'une mauvaise famille ou d'un nom versionné trop long |
| r161, version corrigée | **202P/0F/0E/0S**, quatre fichiers complets : 82 contrat OCR, 63 PDF, 49 console PDF et 8 provenance PDF→M10; Ruff des deux fichiers et vérificateur verts |
| r162, relecture historique | Deux ensembles de **55 mots chacun** issus du pilote fictif r133 acceptés, textes/boîtes/scores inchangés; aucun nouveau run PDFium ou Tesseract |

r161 : 30,109 s JUnit, 33,065 s au mur; pic RSS observé du groupe pytest
161 234 944 octets, 1 249 sources stables, aucun OOM/garde ni processus survivant.
Les suites PDF adjacentes exercent le worker natif existant et ses refus;
elles ne démontrent pas un worker OCR. Les 202 cas sont une campagne ciblée,
pas un verdict de réussite pour tout le dépôt. Les contrôles nouveaux portent
sur les limites exactes des pixels/tokens/octets, les booléens numériques,
les scores négatifs/non finis, les hiérarchies TSV, les boîtes et les identités.

La relecture r162 utilise la [capsule du pilote CPU](../../research/REPRISE-2026-10-04/preuves/M5-OCR-PILOTE-CPU-r1.tar.xz),
SHA-256 `3dc087c92acfdf57691fc50e6fc9fb94baf3ec962fcd8a06850ec7d24f82b098`.
Le profil historique est pypdfium2 **5.3.0**, distinct du candidat 5.13.0.
Les métadonnées v1 de relecture sont construites explicitement, avec lot et
configuration fictifs; le pilote n'avait pas émis ce nouveau contrat. Les mots,
boîtes et scores viennent des observations conservées. Le TSV brut n'est pas
présent dans cette capsule : cette relecture ne qualifie donc pas son décodage,
qui est couvert par les fixtures TSV des tests. Les erreurs reconnues sur la
facture inclinée restent intactes et ne deviennent pas une vérité comptable.

Le scan final ROOT r163 porte sur six fichiers : code, tests et quatre docs,
sans modification de règles/exclusions. Son reçu, les gels, logs et JUnit sont
dans la [capsule du contrat OCR](../../research/REPRISE-2026-10-04/preuves/M5-OCR-CONTRAT-r1.tar.xz)
et le [manifeste](../../research/REPRISE-2026-10-04/preuves/M5-OCR-CONTRAT-r1.json).
Les rouges et préimages sont conservés. Le statut de la CI du nouveau commit
doit être observé séparément du head précédent.

## Limites et prochaine livraison

Pas encore de diagnostic PDF image seule, worker OCR produit, profil installé
vérifié, confinement Docker qualifié, candidat chiffré durable, route privée,
console de revue, correction humaine ou intégration mobile. Ces incréments
restent requis pour que l'entreprise puisse utiliser cette capacité. Aucun
import AP automatique, indexation financière M10, score d'assimilation ni
mesure de précision métier n'est ajouté. Les deux observations du pilote ne
constituent pas un corpus représentatif ni un taux de reconnaissance français.

La prochaine étape est le worker distinct et son diagnostic conservateur,
avec isolation effective, artefacts mesurés et sorties validées par ce contrat;
la source PDF native et son refus `PDF_IMAGE_OU_MIXTE` restent la voie canonique.
