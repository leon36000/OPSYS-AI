# Catalogue de matériaux nommés — audit avant raccord CRM-07

27 octobre 2026, source `b37db4eeaf46cffb7e16519bf37895272c38de8b`.
Statut : **PARTIAL**, audit ciblé; ne remplace pas l’audit historique M6 ni sa matrice complète.

## Objectif et existant

Le secrétariat doit sélectionner un matériau par nom et unité lors de la configuration des
lignes réutilisables M3. Actuellement `prefill_ui.py` demande une référence matériau explicite;
le fournisseur est déjà sélectionnable par son nom M6. Ne pas déduire un nom depuis un SKU.

- `catalogue.py:resoudre_prix` accepte un dictionnaire fourni par l’appelant et consulte les
  réceptions. Le contrat historique `CatalogueMateriaux` contient des libellés mais n’établit
  pas un registre persistant de fiches administrables ni une unité canonique.
- `besoins_materiaux_recus.py` valide les libellés entrants M3 et un SKU facultatif. Ces
  libellés appartiennent au besoin reçu; ils ne constituent pas un catalogue officiel.
- `livre_prix.py` et `tarif_soumission.py` identifient matériau/fournisseur/unité et gardent
  les coûts. Un prix ne suffit pas à prouver le nom d’un matériau.
- `fournisseurs.py` démontre le journal append-only M6, mais sa projection de mises à jour
  partielles n’est pas reprise : identité et ordre invalides doivent bloquer tout le catalogue.
- Les journaux SQL `stockage.maillons` existent; aucune nouvelle table ni dépendance requise.
  Le modèle versionné M3 fournit le patron CAS, bornes, audit et reçus à réutiliser pour les ports.

L’audit `docs/departements/M6-audit.md` reste historique : ses anciennes absences de PO,
besoins ou variance ne sont pas transposées à l’état actuel. Ce changement ne reconstruit
ni ces capacités ni les prix, les fournisseurs, le stock ou les réservations.

## Patch minimal et contrat

1. Domaine pur `catalogue_materiaux.py`, collection `catalogue_materiaux` : identité stable,
   nom explicite, unité explicite, statut actif/inactif, raison de modification, auteur,
   horodatage serveur transmis par l’adaptateur, révision et empreinte de source.
2. Versions intégrales append-only avec comparaison de révision; unité immuable pour une
   identité existante afin de ne pas requalifier silencieusement prix/stock/besoins. Une autre
   unité exige une autre identité explicite. Aucun prix ni quantité dans une fiche.
3. Historique vérifié avant lecture/écriture : schéma fermé, ordre/révisions, contenu,
   empreintes, identité/unité stables. Les empreintes détectent une incohérence, pas une
   réécriture cohérente malveillante de toute la base. Maximum 10 000 maillons, lecture
   paginée bornée; pas de troncature silencieuse des sources.
4. Ensuite ports privés console admin SQL, reçus de mutation, autorité revalidée au rejeu,
   transaction d’audit, puis gestion du catalogue et sélection M3 par libellé. Les ports/UI
   et la politique d’inactivation des lignes historiques restent **à réaliser** dans cette tranche.

## Permissions, intégrations et risques

Le domaine reçoit un auteur, il ne l’authentifie pas. Les prochains adaptateurs doivent
imposer session admin active, CSRF, réception serveur et idempotence SQL. Aucun outil
appareil ni droit nouveau avant qualification. Nom et unité fournis par un administrateur;
aucune importation automatique des anciens libellés ou prix. Pas de suppression dure.
La révision du catalogue ne réécrit jamais un devis accepté ni une ancienne ligne M3.
Un matériau inactif devra être exclu des nouveaux choix sans supprimer son historique.
M10, mobile, prix courriel, PostgreSQL et contrôle des SKU fournisseurs restent ouverts.
Aucun achat, envoi fournisseur, mouvement de stock ou engagement financier autorisé ici.

## Tests et statut de livraison

Tests prévus : création/révision/lecture historique; conflit concurrent sans effet; unité
immuable; inactivation/réactivation; rejet de source corrompue et champs supplémentaires;
bornes/pagination; copies isolées; transaction SQLite réelle, rollback et réouverture.
Ensuite tests HTTP admin/rejeu/révocation/CSRF et jonction M3/M6 avec noms réels du catalogue.
La fondation pure seule ne vaut pas catalogue utilisable par le secrétariat.

## Fondation qualifiée localement

`catalogue_materiaux.py` et `test_catalogue_materiaux.py` livrent le domaine décrit :
versions complètes, unité immuable, inactivation réversible, historique vérifié et pages
limitées à cinquante fiches. Le domaine ne remplace pas l’autorisation de l’adaptateur.
Qualification privée `crm-prefill-qa-20261027-r1/materials-v2` : 47 tests réussis,
aucun échec ni saut, 1,13 s; Ruff et vérificateur 288/173 réussis. Regroupement du nouveau
catalogue, de la résolution de prix historique et de la conformité M6; non additionnable
aux campagnes précédentes. Source en lecture seule, réseau bloqué, mémoire 1 Gio, CPU
100 %, 96 tâches, homes/tmp privés et reçus durables.

Le scénario SQLite réel couvre persistance, réouverture, rollback et conflit de révision
séquentiel. Il ne prouve pas deux écrivains simultanés : cette preuve reste à ajouter
avec l’adaptateur transactionnel. Revue statique indépendante sans constat bloquant,
limitée au domaine et aux tests, sans nouvelle exécution. Le rouge `materials-v1` reste
conservé : 47 tests réussis et une règle Ruff SIM117 dans le test de rollback, corrigée.

**Prochaine étape précise :** ports M6 privés de lecture/liste/enregistrement, uniquement
console admin SQL; reprendre le patron de `console.metier._executer_modeles` et les reçus
`idempotence`, sans importer le département M3 dans M6. Schémas fermés, admin revalidé,
réception serveur, transaction audit+réponse bornée+mutation. Fermer ces ports aux appareils,
MCP et agents génériques. Prouver concurrence SQL et rejeu/révocation avant les formulaires.
Aucun écran ni nouveau port exposé par cette fondation; M6 et CRM-07 restent PARTIAL.

## Ports privés qualifiés, interface encore ouverte

`catalogue_console.py` expose trois ports internes : `m6_enregistrer_materiau_console`,
`m6_lire_materiau_console`, `m6_lister_materiaux_console`. `console.metier` vérifie la
session active et le rôle admin en base, fournit identité et réception serveur, puis
appelle l’outil réel. L’adaptateur M6 revérifie l’identité SQL avant chaque opération,
y compris un rejeu. PostgreSQL, origine agent et MCP sont refusés; `capacites.py` ferme
les chemins génériques et runtime avant toute intention. Aucune portée appareil ajoutée.

Écriture SQLite : reçu idempotent, CAS et journal métier, audit puis réponse dans une
transaction imbriquée. Une panne d’audit ou dépassement de quota annule aussi le reçu.
La limite de sortie porte sur l’enveloppe publique entière en UTF-8, plafonnée à 64 Kio.
Les lectures sont paginées; la réponse porte `accepte`, puis `resultat` ou `raison` de
refus. Aucun nouveau endpoint HTTP ni interface utilisateur à ce jalon.

`tests/test_console_catalogue_m6.py` prouve le dispatch console SQL, réouverture, versions,
inactivation, rejeu exact, conflit d’intention, révocation, session expirée, owner sans
admin, champs fermés, refus des canaux génériques, unité immuable, corruption du journal,
rollback audit/quota et frontière UTF-8 exacte. Deux threads tentent réellement la même
révision sous les transactions SQLite `BEGIN IMMEDIATE` : un seul réussit, l’autre reçoit
`REVISION-PERIMEE`. Ceci ne qualifie pas PostgreSQL ni une flotte multi-hôtes.

QA `crm-prefill-qa-20261027-r1/material-ports-v2` : 98 tests réussis, zéro échec/saut,
10,37 s; Ruff et vérificateur 291 outils/173 portées réussis, populations recoupées.
Le rouge v1 conserve 68 tests réussis et deux E501. La revue indépendante a aussi trouvé
l’ordre historique des outils à préserver et le quota d’enveloppe incomplet : corrigés
avec régression `test_outils_agent.py` et test UTF-8 à la frontière. Aucun test affaibli.

Prochaine étape : formulaires HTTP admin de gestion du catalogue puis sélection M3 par
nom/unité, avec source et révision explicites. Préserver les anciens modèles et devis;
refuser les nouveaux choix inactifs. M10, mobile et PostgreSQL restent ouverts. **PARTIAL**.
