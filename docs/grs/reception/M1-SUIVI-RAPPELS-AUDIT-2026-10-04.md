# M1 — audit ciblé du suivi de rappels, 4 octobre 2026

**Tranche 25 qualifiée localement par ROOT r150. M1 global PARTIEL.**
Cet audit documentaire porte sur la lacune du baseline et le contrat retenu,
sans exécution de test, service ou fournisseur. Le
[design adapté](M1-SUIVI-RAPPELS-DESIGN-2026-10-04.md) précise la prochaine
extension ; le [rapport](M1-SUIVI-RAPPELS-RAPPORT-2026-10-04.md) conserve le
premier rouge et la qualification finale locale.

## Besoin et existant

Les [directives produit](../../produit/DIRECTIVES-NATHAN.md) et le
[périmètre M1](../../produit/PERIMETRE-MODULES.md) demandent appels manqués,
suivi et handoff. L’import canonique écrit déjà un transfert durable de rappel
et son rattachement dans
[`appel_importe.reponse.tache_rappel.transfert_id`](../../../departments/m01-front-office/src/m1_front_office/outils.py)
(base de préparation, lignes 330–363). Les dossiers privés, voicemail et la
clôture humaine existent. La qualification réussie rejoint déjà M2 ; ce lot
ne crée pas un CRM parallèle.

Le [résumé de réception](M1-DIGEST-CONSOLE-RAPPORT-2026-10-04.md) est une
lecture agrégée qualifiée séparément. Il n’enregistre aucune prise en charge
ni tentative de rappel humaine.

## Lacune du baseline

Sur les préimages de la base publiée `7adca5ae`,
[`EtatTransfert` et `lire`](../../../departments/m01-front-office/src/m1_front_office/transferts.py)
(lignes 124–164) projettent l’ouverture, la clôture et les messages rattachés,
sans attribution ou tentative non terminale structurée. La
[fiche réception](../../../src/opsys/console/frontoffice_marketing.py)
(lignes 275–285) propose la note et la clôture. L’opérateur qui ne joint pas
le client peut garder le dossier ouvert, sans consigner ce résultat de façon
structurée. Ce constat ne démontre pas l’absence de toute note libre ailleurs,
ni un défaut de la clôture actuelle.

Impact opérationnel : responsable, tentative déclarée et prochaine échéance
ne sont pas projetés dans le dossier. Confiance élevée pour ce baseline,
étayée par les préimages SHA-256 et l’oracle HTTP. La qualification locale
postérieure est documentée séparément, sans effacer ce constat historique.

## Contrat retenu et limite de la preuve

ROOT restreint l’extension aux transferts `ventes` reliés à une ou plusieurs
entrées d’appel importé par le chemin exact ci-dessus. Deux actions humaines
internes, `prise_en_charge` et `tentative_sans_contact`, niveau **T1/N2**,
conservent le dossier ouvert. Elles ne sont pas une approbation N3 ; la clôture
existante reste distincte. Attribution à soi seul, tentative par attributaire
seul, heure serveur, rôle vivant, CAS et rejeu exact sont les contrôles attendus.

ROOT r144 exerce un véritable transfert issu de l’import canonique et envoie
un snapshot obsolète. Il attend 409 mais obtient 404 : **0 réussite, 1 échec,
0 erreur, 0 ignoré**, 1 243 sources inchangées, 1,6689 s murales. Le contrôle
d’absence d’effet en base vient après cette assertion et n’est pas atteint.
Ce rouge prouve la route manquante au baseline, pas encore le refus CAS,
l’atomicité, le rejeu ou le contrôle d’identité du candidat.

Le périmètre à qualifier est SQLite seulement. Une tentative consignée reste
une déclaration humaine ; aucun appel techniquement effectué, contact obtenu,
rappel autonome, notification ou résultat terrain n’en découle.

## Amendements ROOT r2–r4 et qualification locale

Le suivi utilise désormais un préflight commun
[`stockage.lecture_m1`](../../../src/opsys/stockage/lecture_m1.py), appelé avant
le premier décodage, sur M1/principal en transaction SQLite : 10 000 maillons,
65 536 octets UTF-8 par maillon, 8 388 608 octets cumulés, inclusifs. Le digest
réutilise ce helper, en conservant ses constantes et ses limites de rendu.
Le nouveau suivi vérifie ensuite le chaînage interne sur une copie en mémoire
avec `Registre(lignes).valider_chaine()` ; le writer reste le registre durable.
Ce contrôle n’apporte ni ancre externe ni protection contre une réécriture
complète cohérente de la base.

Le port métier contrôle expiration et autorité avant claim/replay et après
l’outil ; un refus incomplet doit fermer le chemin sans finaliser de succès.
La garde du rejeu revalide aussi l’autorité après réclamation avant de
retourner le reçu historique. Les tests directs du port et les tests SQL réels
du préflight complètent le
contrat. Les tests unitaires à connexion simulée ne prouvent pas SQLite.
La qualification HTTP/console finale ROOT r150 passe 1 737/1 737 sur
39 fichiers complets, sans échec/erreur/skip ; Ruff et vérificateur verts,
1 245 sources sans dérive/OOM. Le contrôle SQL post-append avant seconde
lecture et les refus backend de source appareil sont couverts sur vraie base.
Le backend est console uniquement, même un owner/admin actif de provenance
appareil refuse ; la portée catalogue appareil est vide. Authentification et
rejeu SDK restent à qualifier avant ouverture de ce port. L’ancien lecteur
direct `m1_lire_transfert` demeure hors qualification de bornage hors wrapper
console ; les nouveaux GET fiche/API et le nouveau writer sont bornés.
PostgreSQL reste exclu. Les neuf unitaires de domaine ne constituent pas des
preuves SQLite. Les rouges et le vert intermédiaire sont conservés dans le
[rapport](M1-SUIVI-RAPPELS-RAPPORT-2026-10-04.md).
