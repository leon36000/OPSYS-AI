# M1 — suivi humain des rappels, livraison locale du 4 octobre 2026

**Tranche 25 qualifiée localement par ROOT r150. M1 global PARTIEL.**
Le parcours livré concerne la console humaine et SQLite ; il ne certifie
aucun opérateur téléphonique, client joint ou résultat terrain. La rédaction
extérieure n’a lancé aucun test, service, réseau ou CI et n’a modifié aucune
source produit.

## Comportement et périmètre

Sur les seuls transferts `ventes` reliés à
`appel_importe.reponse.tache_rappel.transfert_id`, l’owner ou l’admin actif
s’attribue un dossier libre puis consigne une tentative sans contact et une
prochaine échéance explicite. Le dossier reste ouvert et visible. Cette saisie
humaine interne est **T1/N2**, sans approbation N3 ; la clôture humaine N3
existante reste séparée, inchangée.

[Audit ciblé](M1-SUIVI-RAPPELS-AUDIT-2026-10-04.md) et
[design adapté](M1-SUIVI-RAPPELS-DESIGN-2026-10-04.md) décrivent les deux POST
privés `…/reception/transferts/{id}/suivi-rappel`, formulaire/API, session,
CSRF, corps fermé, CAS et idempotence canonique. Acteur, rôle et heure viennent
du serveur ; l’échéance choisie avec offset est future et normalisée UTC.
Le suivi est une déclaration humaine, jamais preuve d’un appel effectué ou
d’un contact obtenu. Aucune téléphonie, notification, CRM, disponibilité M4,
LLM, fournisseur, dépense ou autre action externe n’est créée.

Le backend est **console uniquement** : `source=appareil` refuse même pour un
owner/admin actif ; `roles_appareil=frozenset()` ferme aussi le catalogue.
Le rejeu SDK générique N2 peut restituer un reçu avant le corps M1 ; son
contrôle actuel en base n’est alors pas garanti. Authentification/rejeu Core
restent à qualifier avant ouverture de ce nouveau port. Aucun port appareil
n’est livré par cette tranche.

## Lecture, autorité et atomicité

Le helper commun [lecture M1](../../../src/opsys/stockage/lecture_m1.py)
borne M1/principal en transaction SQLite avant décodage : **10 000 maillons,
65 536 octets UTF-8 par maillon, 8 388 608 octets cumulés**, inclusifs.
Le digest réutilise ce helper avec ses constantes conservées ; son texte
reste borné à 32 768 octets UTF-8. Le writer répète le contrôle SQL après
append, avant sa seconde lecture. Le cas réel 10 000→10 001 refuse 503,
sans décodage post-append, avec toutes les tables META inchangées.

Le chaînage interne est vérifié par `Registre(lignes).valider_chaine()` en
mémoire ; l’append reste porté par le registre durable. Ce contrôle ne
fournit ni ancre externe ni protection contre une réécriture complète
cohérente de la base. Le port métier relit rôle et expiration avant
claim/replay, après réclamation du rejeu avant retour, puis après l’outil.
Le rejeu exact n’ajoute pas de maillon ; clé conflictuelle, snapshot périmé,
refus incomplet et exceptions ferment la transaction sans succès finalisé.

## Preuves ROOT et historique conservé

Base publiée de préparation : `7adca5ae3bb18be7799e39f62883ed70c633a115`.
Préimages, contrats r1–r4, sources et reçus SHA-256 sont conservés dans le
paquet extérieur ; les captures antérieures restent historiques.

| Campagne | Observation | Portée |
|---|---|---|
| r144 | 0P/1F/0E/0S ; 404 attendu 409 ; 1 243 sources inchangées ; 1,6689 s murales | Route absente au baseline |
| r145 | Vérificateur vert, Ruff rouge : trois erreurs ; aucun pytest | Arrêt statique |
| r146 | 27P/21F/0E/0S sur 48 cas | Masquage du module horodatage, corrigé par alias |
| r147 | 1 723P/9F/0E/0S sur 1 732 cas, 39 fichiers ; Ruff/vérificateur verts | Catalogue, contrats de surface et refus incomplet corrigés |
| r148 | 1 734/1 734, sans échec/erreur/skip | Vert intermédiaire avant quota post-append et fermeture appareil |
| r149 | 1 734P/1F/0E/0S | Fixture de quota corrigée : nombre initial capturé avant mutation de sa liste |
| r150 | **1 737/1 737, 0F/0E/0S, 39 fichiers complets** | Sources finales qualifiées localement |

r144 échoue sur HTTP avant sa comparaison de toutes les tables : ce rouge
ne prouve pas l’absence d’effet. r150 couvre effectivement les refus SQL et
le rollback de dépassement, ainsi que deux refus appareil owner/admin sur
vraie base, sans delta de toutes les tables.

ROOT r150 : **118,464 s JUnit**, 121,516 s murales du reçu complet ; Ruff vert
sur 11 chemins, dont un test historique restauré à sa préimage, et vérificateur
vert (214 outils, 122 portées appareil). **1 245 sources sans dérive, aucun
OOM**. Les 61 cas console/SQL/métier sont inclus dans les 1 737, comme les neuf
unitaires de domaine ; ces derniers utilisent des connexions simulées et ne
constituent pas des preuves SQLite. Les campagnes se recouvrent et ne
s’additionnent pas en couverture produit globale.

## Limites et conditionnement

Les nouveaux GET fiche/API et le nouveau writer sont bornés. L’ancien
`m1_lire_transfert` direct décode encore avant bornage hors wrapper console :
sa lecture MCP/appareil reste **hors qualification**, sans modification
silencieuse de ce port. PostgreSQL, réattribution, contact réussi et rappel
autonome restent hors de la tranche. M1 global demeure PARTIEL.

Le périmètre de cette livraison est **10 chemins code/test, six documents,
deux artefacts de capsule**, soit 18 chemins. Le test historique de transfert
restauré à sa base n’est pas un changement publié. Les [preuves conservées](../../research/REPRISE-2026-10-04/preuves/M1-SUIVI-RAPPELS-r1.tar.xz)
et leur [manifeste](../../research/REPRISE-2026-10-04/preuves/M1-SUIVI-RAPPELS-r1.json)
contiennent les campagnes distinctes, sources gelées et résultats de qualification.
Le manifeste référence également le contrôle des secrets ROOT r151 et la revue finale.

La CI conservée du **4 octobre à 14:06:16 UTC** porte sur la base `7adca5ae` :
dépendances, mobile et E2E réussis ; CI, Core et installateur en cours. Ces
états ne qualifient ni le prochain commit ni les correctifs de suivi. Aucune
fusion, mise en production ou promotion globale n’est déduite de ROOT r150.
