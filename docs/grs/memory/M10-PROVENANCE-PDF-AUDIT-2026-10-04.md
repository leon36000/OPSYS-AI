# M10 — prochain raccord métier après M1 (audit RO)

**Priorité proposée : raccorder le pilote PDF Finance à la provenance documentaire M10, comme source candidate explicitement non validée.** Une arrivée PDF existante devient consultable comme source d’entreprise sourcée avec son statut d’extraction, son extracteur/version, son hash et sa référence locale; le texte et l’original restent dans le stockage chiffré PDF. Cela étend réellement le parcours d’assimilation à un format documentaire déjà pris en charge, sans inventer d’apprentissage ni de deuxième copie.

## Écart démontré

Le programme dit que l’ingestion universelle et le corpus client restent à qualifier (`docs/programme/RESTRUCTURATION-2026-09-30.md:82-90`). La cible Fusion demande inventaire, extraction par format, classification avec contrôle humain, provenance page/ligne et états par document (`docs/produit/VISION-ENTREPRISE-APPRENANTE.md:62-83`). En pratique, les imports durables M10 portent uniquement sur les procédures internes M03 TXT/MD et excluent secrets/PII (`docs/grs/memory/M10-IMPORT-LOTS-REPRISE-2026-10-04.md:5-31`). Le PDF natif existe déjà dans Finance, mais son type/classe sont fixés `pdf_natif`/`FINANCIAL` (`src/opsys/fusion_pdf.py:100-113, 243-254`), avec source et résultat chiffrés et extraction bornée (`:34-47, 412-475`). Fusion n’en expose que des compteurs et rappelle que les extraits ne sont pas vérifiés (`src/opsys/console/fusion_synthese.py:324-330`).

Le CSV bancaire a déjà le bon point d’intégration M10 : il append une provenance structurée dans le registre `m10-memoire/documents` lors des transitions (`src/opsys/fusion_csv.py:301-340`). Mais son contrat est strictement CSV et porte une seule classe `FINANCIAL` (`departments/m10-memoire/src/m10_memoire/provenance_documentaire.py:12-20, 22-65`); il ne peut pas représenter proprement le PDF sans extension ciblée.

## Tranche bornée

- **Propriétaires** : `departments/m10-memoire/src/m10_memoire/provenance_documentaire.py` pour un variant PDF fermé, `src/opsys/fusion_pdf.py` pour appeler cet append dans la transaction existante, et `src/opsys/console/fusion_pdf_ui.py` pour projeter dans le détail PDF un état M10 sourcé (ou « indisponible »). Tests ciblés `departments/m10-memoire/tests/test_registre.py`, `tests/test_fusion_pdf.py` et `tests/test_console_fusion_pdf.py`. Pas de changement `store.py`/schéma : `stockage.maillons` est déjà utilisé par l’intégration CSV dans sa transaction.
- Contrat PDF limité à `lot_id`, URI locale stable, `source_sha256`, classe constante `FINANCIAL`, auteur, version/configuration d’extracteur, révision, `statut` courant, nombre de pages et code fermé d’erreur. Pas d’octets, extraits, noms de fichier, PII, ni résultat AP. Statuts restent ceux du PDF (`RECU`, `EXTRAIT_PREPARATOIRE`, `REFUSE`, `ERREUR_REPRENABLE`), sans assimiler « extrait » à « validé ».
- Écrire provenance à l’admission puis à chaque transition terminale/reprise dans la **même transaction** que `FUSION_PDF_LOTS` et le journal existant; rejouer une révision identique doit être idempotent. Aucun nouveau DDL/store/job; le registre hash-chaîné documentaire existant reste l’autorité de provenance, le stockage PDF reste l’autorité du contenu et de ses pages/citations.
- Conserver exactement l’accès PDF actuel et son identité active, réponses `no-store`, quotas, chiffrement, refus d’extraction ambiguë et validations existantes. Cette tranche ne donne pas accès Finance-only si le PDF exige aujourd’hui un autre rôle.

## Premier oracle et limites

Premier test sur une base de fixture : admission PDF fictif → M10 contient seulement la provenance attendue; succès d’extraction ajoute statut/pages/config; refus et erreur reprenable restent distincts; rejeu ne double pas; panne forcée pendant append annule également transition/journal. Vérifier que les octets PDF/extraits n’apparaissent jamais dans les maillons M10 et que lire les pages passe toujours par le lecteur PDF protégé. Réutiliser en priorité `tests/test_fusion_pdf.py`, `tests/test_console_fusion_pdf.py` et tests du registre documentaire; ajouter un parcours PostgreSQL réel uniquement si la suite propriétaire du PDF est qualifiée ainsi.

**Ce raccord ne fait pas encore de classification générale**, ingestion client universelle, indexation M10, recherche cross-département, dédoublonnage, mesure de couverture, sélection d’échantillon ou apprentissage. Il apporte une provenance interrogeable pour une filière existante; les documents PDF restent Finance et les extraits restent des candidats. Le blocage suivant sera un flux guidé de classification humaine pour d’autres types de documents, à cadrer séparément avec des classes réellement supportées et des tests d’accès/effacement.

## Empreintes sources consultées

Voir `SOURCES.sha256` pour les hashes exacts du programme, directives, vision, reprise M10 et modules propriétaires consultés. Lecture limitée aux extraits référencés; aucun code/test/serveur n’a été lancé et aucun fichier du dépôt n’a été modifié.

## Statut avant code

Audit préparatoire de la tranche26, base publiée `853d31d2c8bab5492f6e27fb034f6a1dbaa65e83`. Aucun raccord PDF/M10 encore qualifié à cette rédaction. Le contrat architecte et les tests peuvent préciser cette étude; le rapport final portera leurs preuves et limites.
