# M6 / CRM-14 — confirmation atomique d’un lot tarifaire

Audit/contrat avant code, sourcee0dfc9ec. Statut initial : non implémenté. Aperçu privé existant,
aucun bouton appliquant le lot. Cette tranche ajoute seulement le coordinateur privé testé
sur données fictives; aucune mise à jour d’entreprise, connexion courriel ou permission nouvelle.

## Objectif, pourquoi et réutilisation

Appliquer toutes les lignes revalidées ou aucune. Réutiliser `prix_console.confirmer` pour
chaque ligne : CAS matière/fournisseur/dernierprix, réception durable, audit et événement source
M10 restent dans leur transaction. Ne pas append directement au livre, ne pas repayer/commander,
ne pas réévaluer les devis ni republier les événements au niveau du lot.

`executer_atomique` n’annule que l’enveloppe ok=False : un refus enfant accepte=False reste
ok=True. Le coordinateur doit lever un refus DANS la transaction englobante, puis convertir
l’exception après rollback. Réutiliser `stockage.transaction()` imbriquée, pas un simple savepoint
SQL : les rappels aprèsvalidation doivent aussi être isolés et jetés sur échec. Le dispatcher
encadre exécution ET contrôle final de session dans cette primitive, même si l’appelant attrape
ensuite PermissionError et valide sa transaction extérieure.

## API, données et permissions

Nouveau T1 privé `m6_confirmer_import_tarifs_console`, sans rôle appareil, origine console admin
SQL courante, réception liée console:<auteur>, sans MCP. Deux fermetures génériques et profilées
avant factory, dispatcher d’écriture privé et Meta parent hors arguments. Pas de route HTTP dans
cette tranche. Arguments CSV/mapping/séparateur/fournisseur/référence comme aperçu, source_attendue
et preparation_attendue obligatoires64hex. Type exact/longueur CSV avant encode,1Mio octets,
mapping copié, sources/document bornés. Aucun jour, source SQL ou nonce enfant fourni par l’appelant.

## Workflow et atomicité

Autorité→arguments bornés→réclamation parent→si reçu clos, vérifier structure/statut/identités/
preuve/quota et retourner exactement le reçu d’origine. Ne pas exiger une nouvelle source après
ses propres écritures; l’heure du nouvel appel ne fait pas partie des arguments idempotents.
Rejeu garde contrôle d’identité actuel et ne revendique pas fraîcheur du prix actuel.

Pour un parent frais : reparsing propriétaire→3snapshots bornés→projection canonique→source et
préparation attendues exactes→toutes lignes admissibles→capacité livre+n_lignes<=10000 avant premier
append. Conserver les ancres du même aperçu pour chaque writer, ne pas recréer une intention
après chaque append. Nonces enfants courts, préfixe versionné+SHA256 acteur/clé parent/position;
même acteur/horodatage Meta, contexte parent restauré après chaque enfant. Enfant déjà présent
pour un parent frais =conflit, pas rejeu d’une opération étrangère.

Premier refus/panne enfant, quota final insuffisant, données inattendues ou perte d’autorité :
rollback prix+réclamations+réceptions+audit+outbox/M10 ensemble. Préfixe initial du livre et sources
catalogue/fournisseurs conservés; exactement n_lignes ajouts attendus, références des reçus enfants
cohérentes. Le reçu parent compact inclut sources approuvées, hash binaire, acteur/identité de lot,
nombre et références des lignes, preuve d’intégrité; il n’authentifie pas l’expéditeur/document.

## Risques, tests et gates

Avant code : vrai rouge nom/dispatcher absent. Puis deux matériaux réels de fixtures,
confirmation par writers natifs, réception/M10/audit, même reçu après libérationSQL et changement
ultérieur de sources sans nouvelle écriture. Refus: source/préparation périmées, mauvais fichier,
lot partiellement invalide, capacité, conflit parent/enfant, reçu parent non clos/corrompu,
autorité/MCP/réception, petite sortie; panne deuxième ligne et publication M10. Expiration finale
attrapée dans transaction appelante doit laisser toutes tables identiques. Deux appels concurrents
même clé doivent produire un seul lot. Rôles/contrôleur commun inchangés, aucune portée ajoutée.

Préflight natif M10 de cette nouvelle tâche acquis dans instance privée vide, contexte versionné
relu; cela ne vaut pas rappel de la mémoire projet. Recherche/infrastructure déjà qualifiées
réutilisées, pas de dépendance/model/CLI/VM nouveau. Revue statique indépendante des frontières
transaction/reçu collectée avant code. QA SourceRO/CPU1/1Gio/96tâches/600s/réseau refusé.

Validation humaine/politique de prix actuelle reste requise au point d’entrée du produit; ici
seulement API privée et fixtures. La future UI devra garder le fichier dans le navigateur ou
le redemander, sans recopier colonnes libres ou persister secrètement le CSV côté serveur.
Aucun import officiel, prix réel, donnée réelle, paiement, nouveau droit, déploiement ou fusion.
Produit et CRM-14 restentPARTIAL. Suites : qualification du coordinateur, puis confirmation HTTP
CSRF/revue explicite et reçu historique, sous les mêmes portes. M8/M9/M10 complets non revendiqués.

## État qualifié localement et fichiers

Le coordinateur privé est maintenant implémenté dans
`departments/m06-material-control/src/m6_material_control/import_tarifs_confirmation.py`.
`prix_console.py` déclare l’outil, `src/opsys/console/metier.py` le distribue dans sa transaction
privée et `src/opsys/capacites.py` ferme les deux autres transports avant lecture/factory.
Les fonctions du writer de saisie, les contrats purs et le contrôleur commun sont conservés.
`tests/test_console_import_tarifs_confirmation_m6.py` exerce31cas nouveaux. Aucune route
HTTP de confirmation n’est ajoutée; l’aperçu HTTP reste sans effet sur les prix.

QA finale `price-import-confirm-v6` :94PASS/28,30s, dont31nouveaux de lot +23aperçu privé
+21saisie +19conformité, puis catalogue natif306outils/177déclarés. Les cohortes90 et77
compatibles sont réutilisées sans addition. Quotas CPU1/1Gio/swap0/96tâches/600s, Source
en lecture seule et sockets refusées vérifiés avant imports; toutes données fictives.
Preuves durables du chantier : `PRICE-IMPORT-CONFIRMATION-LOCAL-QUALIFIED.json`,
phase RESULT/RECEIPT/XML et revue statique indépendante.

Un lot2lignes écrit exactement2tarifs,2réceptions,2audits,3réclamations (parent+enfants),
2événements source, puis le vrai drainage produit2références M10 minimisées sans prix/identifiants
matériau/fournisseur. Rejeu après drainage et changement ultérieur de prix n’écrit rien. Cela
qualifie ce parcours local, pas une mémoire projet ou un flux courriel de production.
Frontière native9999+2 refusée avant append;9999+1 accepté puis rejoué à10000. Refus d’un
enfant, panne publication, métadonnées modifiées sur chacun des3registres, quota final et
expiration finale (même attrapée par caller qui valide) annulent toutes tables concernées.
Deux intentions concurrentes identiques produisent un seul lot.

Revue : parent rechaîné vers faux rangs/hashes et détail enfant booléen égal à1 en Python
ont été reproduits rouges puis corrigés. Les résultats enfants clos et leurs empreintes
d’arguments sont liés au parent; comparaison JSON canonique préservant les types. Les octets
des reçus SQL sont bornés avant décodage et les3registres rebornés après les writers avant
le premier décodage de contrôle. Revue de clôture sans constat résiduel sur ces corrections.
Les rouges lint et erreurs d’assertion/fixture de test sont historiques et distincts des défauts
produit reproduits. La CI globale du parent publié reste en cours au dernier relevé; aucun
PASS global, import officiel ou déploiement n’est revendiqué.

## Statut, gates Nathan et suites

Coordinateur privé : qualifié localement; CRM-14, M6 et produit : PARTIAL. Aucune action Nathan
requise pour ces préparations réversibles. La validation explicite/politique autorisée des
prix réels reste nécessaire au futur point d’entrée; aucun prix d’entreprise n’a été appliqué.
Prochaine capacité : confirmation HTTP avec revue explicite, CSRF, nonce lié à l’intention
et reçu historique, sans stocker secrètement les colonnes libres du CSV. Courriel automatique,
formats fournisseurs réels, navigateur réel, PostgreSQL/mobile et production restent ouverts.


Raccord suivant : la [confirmation HTTP](M6-IMPORT-TARIFS-CONFIRMATION-HTTP.md) est maintenant
qualifiée localement. Le coordinateur et ses writers sont inchangés; le point d’entrée privé
exige revue explicite/CSRF/mêmeCSV, protège la transaction jusqu’après rendu et affiche le reçu
historique. Cette preuve ne vaut pas validation de prix d’entreprise réels ni import courriel.
