# M10 — provenance PDF Finance : qualification locale du 4 octobre 2026

**Tranche 26 qualifiée localement par ROOT r156. M10 et Fusion restent PARTIEL.**
La rédaction extérieure n’a lancé aucun test, import produit, worker, parser,
réseau ou CI, et n’a modifié aucune source du dépôt.

## Raccord livré et autorité conservée

Le [workflow PDF Finance](../../../src/opsys/fusion_pdf.py) inscrit une
provenance candidate dans le [registre documentaire M10](../../../departments/m10-memoire/src/m10_memoire/provenance_documentaire.py)
à l’admission et aux transitions, puis la [fiche privée PDF](../../../src/opsys/console/fusion_pdf_ui.py)
la projette après reconnexion. Le [design](M10-PROVENANCE-PDF-DESIGN-2026-10-04.md)
adapte l’[audit initial](M10-PROVENANCE-PDF-AUDIT-2026-10-04.md).

Le PDF demeure seul autorité des octets, texte, fragments, pages/citations et
résultats chiffrés. M10 ne copie ni corps, montant, nom de fichier, clé, donnée
client ou résultat AP : seulement lot, URI locale, hash, auteur initial,
acteur de transition, extracteur/configuration, révisions/statut/pages/code.
La classe `FINANCIAL` est celle de cette filière, les extraits restent
préparatoires. Aucun classement universel, indexation, vectorisation,
apprentissage, fournisseur, LLM, migration, store générique, paiement ou
ledger final n’est ajouté. Le contrat CSV et ses gardes sont conservés.

## Transaction et consultation

Le raccord financier est **SQLite uniquement, sans DDL**. Lot PDF,
provenance, quotas, reçu et journal évoluent dans la même transaction.
Préflight SQL avant décodage et après append : plafonds inclusifs de
**10 000 lignes, 65 536 octets UTF-8 par ligne, 8 388 608 octets cumulés**.
Dépassement, collision ou corruption ferme en erreur générique 503
`PDF_PROVENANCE_INDISPONIBLE`, avec rollback lié.

`lire_avec_provenance` lit lot et trace dans une transaction, compare leurs
métadonnées et conserve droits/session, compatibilité et préconditions PDF.
La fiche privée reste `no-store`, typée et échappée. Ancien lot sans trace :
absence explicite ; GET et rejeu n’ajoutent rien. Une première capture
ultérieure peut commencer à la révision PDF courante, sans inventer son passé.
Le chaînage interne est vérifié ; aucune ancre externe ni protection contre
une réécriture complète cohérente de base n’est annoncée.

## Preuves ROOT conservées

Base publiée de préparation : `853d31d2c8bab5492f6e27fb034f6a1dbaa65e83`,
arbre `456b9850f5eecf98dbef818f4e010c58750dc89b`. Les sources finales sont
comparées aux empreintes de campagne ; préimages, oracle initial et rouges
restent conservés avec SHA-256.

| Campagne | Résultat | Portée |
|---|---|---|
| r152 | **0P/1F/0E/0S**, un cas, 1 246 sources inchangées | En-tête canari `%PDF-1.7` admis en SQL, zéro trace contre une attendue ; aucun parser/worker |
| r153 | **1 398P/3F/0E/0S**, 1 401 cas, 52 fichiers ; Ruff/vérificateur verts | Rouge élargi conservé, avant correctifs |
| r154 | **1 401/1 401, 0F/0E/0S, 52 fichiers complets** | Vert intermédiaire avant adaptation du jeton de test |
| r155 | Scan 16 fichiers, une alerte sur un jeton fictif d’un ancien test | Rouge conservé, aucun secret réel ni exclusion ajoutée |
| r156 | **1 401/1 401, 0F/0E/0S, 52 fichiers complets** | Qualification locale finale après génération du jeton fictif |

L’assertion de cardinalité r152 échoue avant les contrôles de la future trace,
et ne prouve aucune extraction. Le scope r153/r154 a été élargi **avant**
lancement de treize fichiers AP backend/UI et installation PDF. Les trois
correctifs r153 conservent le contrat : deux traces admission+préparation,
UUID canonique minuscule 8-4-4-4-12 par grammaire sans import `uuid`, et fixture
PostgreSQL réutilisant l’option RAM existante. Politique de conformité M10
inchangée ; premier oracle, `CHAMPS` et gardes CSV préservés par contrôle AST
ROOT. Le double CAS unitaire a été corrigé sans assouplir le store.
Le scan r155 signalait un littéral entièrement fictif dans un test HTTP ancien.
Le jeton est maintenant généré explicitement au test ; son absence de la réponse
et le marqueur `redacted=true` restent vérifiés. Le scanner et les contrôles de
masquage de production n’ont reçu aucune exclusion ou assouplissement.

ROOT r156 : **181.250 s JUnit**, 184.732 s murales ; Ruff vert sur dix chemins,
vérificateur vert (dix départements, 214 outils, 122 portées appareil),
**1 247 sources sans dérive, OOM inchangé et aucun processus survivant**.
Le pic RSS du groupe pytest est 322 412 544 octets.

| Fichier critique inclus dans les 1 401 cas | Cas | Preuve et limite |
|---|---:|---|
| Nouvelle provenance PDF | 8 | SQL réel, canaris et états contrôlés ; aucun nouveau parser |
| Suite PDF historique complète | 63 | Inclut le worker natif réellement confiné et ses refus |
| Console PDF complète | 49 | SQLite/HTTP privé, droits, erreurs et rendu |
| Nouveau contrat PDF M10 | 21 | Validation pure, sans prétention d’intégration SQL |
| API M10 de développement | 25 | Inclut un test sur vrai PostgreSQL en RAM |

Ce PostgreSQL utilise la même image locale sans pull, tmpfs 256 Mio et mémoire
512 Mio. Il qualifie un chemin **M10 de développement existant**, pas le
raccord PDF Finance sur PostgreSQL. Les lignes du tableau et les campagnes
recouvrantes ne sont pas additionnées en couverture produit globale.

## Limites et preuves publiées

M10 et Fusion restent PARTIEL : pas de corpus client universel, classement
général, apprentissage ou première validation sur données client réelles.
PostgreSQL financier demeure hors qualification. ROOT a confirmé dix chemins
code/test modifiés depuis la base25, sans autre changement de source.
La [capsule de preuves](../../research/REPRISE-2026-10-04/preuves/M10-PROVENANCE-PDF-r2.tar.xz)
et son [manifeste SHA-256](../../research/REPRISE-2026-10-04/preuves/M10-PROVENANCE-PDF-r2.json)
conservent les rouges, le gel qualifié, les reçus de scan de secrets ROOT r155 (alerte fictive) et r157/r158,
les préimages et les révisions de revue. Le manifeste vérifie chaque membre.
Le test de limite post-append emploie un plafond cumulé abaissé à la fixture ;
il ne revendique pas un remplissage de 8 Mio ou de 10 000 lignes.

Le snapshot CI base25 du **4 octobre à 14:58:34 UTC** garde mobile,
dépendances et E2E réussis ; CI/Core/installateur en cours. Doubles hébergés
réussis et E2E self-hosted ignorés ne prouvent pas le Desktop réel ; les étapes
Linux restantes attendent leur résultat. Ces états ne qualifient pas le futur
commit26, et n’annoncent aucune fusion ou mise en production.
