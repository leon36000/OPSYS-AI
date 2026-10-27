# Soumission préremplie — parcours admin M3/M6

27 octobre 2026. CRM-07 **PARTIAL**, tranche serveur HTTP/SQLite qualifiée localement.
Prérequis et choix : [audit](AUDIT-LIGNES-PREFILL-M3-M6.md),
[domaines et ports privés](FONDATIONS-PREFILL-M3-M6.md).

## Objectif et parcours

Le secrétariat conserve les descriptions, matériaux et unités dans un modèle versionné,
puis choisit quantités et fournisseurs pour chaque nouveau devis. M6 fournit le coût;
M3 calcule le prix. Les quantités ne sont jamais déduites du modèle ni proposées par défaut.

1. Ouvrir un modèle textuel et « Configurer les lignes réutilisables ».
2. Renseigner jusqu’à vingt lignes : description, référence matériau M6 et unité exacte.
   Enregistrer crée une version; aucune soumission existante ne change.
3. Dans les soumissions du projet, choisir un modèle puis « Utiliser les lignes et tarifs M6 ».
4. Renseigner la quantité, choisir le fournisseur par son nom M6 pour chaque ligne, puis la majoration.
5. Vérifier les coûts CAD, date effective, fournisseur et source documentaire affichés.
   Sans pièce, le badge reste `FALLBACK_PRICE_BOOK`.
6. Vérifier le coût total privé et le prix de vente par ligne et total, taxes en sus.
7. Créer le brouillon. Le dossier permet ensuite de consulter ses documents HTML/PDF.

Le lien « Choisir les matériaux par nom et unité » ouvre le sélecteur du catalogue M6 actif.
Le catalogue se gère dans `/crm/materiaux`; les fiches sont versionnées et l’unité est immuable.
Les anciennes références explicites restent consultables et remplaçables sans migration automatique. Les fournisseurs compatibles sont proposés par nom,
sans présélection ni classement par coût. Sans lignes enregistrées, le parcours prérempli refuse;
la saisie manuelle existante reste accessible, ainsi que le lien de configuration des lignes.

## Architecture, fichiers et routes

`src/opsys/console/prefill_ui.py` porte les formulaires et appelle les cinq ports privés
qualifiés. `devis_modele_ui.py` raccorde le routeur et les liens; `modeles_soumission_ui.py`
ajoute l’accès depuis le catalogue. Les domaines, tarifs, calculs et journaux restent M3/M6.

- GET/POST `/crm/modeles-soumission/{modele_id}/lignes`
- GET `/crm/lead/{lead_id}/soumission-preremplie`
- POST `/crm/lead/{lead_id}/soumission-preremplie/preparer`
- POST `/crm/lead/{lead_id}/soumission-preremplie`

Les GET portent la version et l’empreinte exactes du modèle. La préparation est une lecture;
elle ne crée pas de devis ni d’intention en base. Le POST final transmet choix, quantité,
révision de lignes, rang SQL et empreinte du tarif. Il ne reçoit aucun coût du navigateur.
Le port relit les sources et fige la provenance privée dans sa transaction de création.

## Permissions, risques et validations

Session active et rôle admin SQL obligatoires, CSRF sur les trois POST, listes de champs fermées,
doublons refusés, corps limité à 128 Kio, vingt lignes maximum, pages `no-store`, textes échappés.
Les descriptions utilisent un textarea pour conserver leurs sauts de ligne, y compris le LF initial.
Le catalogue ne propage pas silencieusement des lignes vers une nouvelle version textuelle.
Un changement de tarif entre préparation et création provoque un refus sans écriture. Un rejeu
identique d’une création réussie conserve son reçu et son prix d’origine, après contrôle d’autorité.

Aucun achat, paiement, envoi fournisseur/client, acceptation ou changement de droits.
Les gates Nathan de ces actions restent applicables. Les coûts et références fournisseur
restent dans la console admin et la provenance privée; les documents client n’en contiennent pas.
M10, import automatique de listes par courriel, mobile et PostgreSQL restent hors qualification
de cette tranche. Le bus durable de ce nouveau parcours est désormais qualifié sur SQLite
avec acceptation fictive explicite; cela ne vaut pas qualification du core ni de PostgreSQL.

## Preuves et statut

`tests/test_console_prefill_http.py` utilise le serveur ASGI réel, SQLite réel et des données
fictives. Parcours choix → préparation sans écriture → création → réouverture du moteur →
documents HTML/PDF analysés → rejeu après changement de prix; éditeur versionné, CSRF,
révocation admin, coût injecté, source/prix modifiés, fournisseur inconnu, doublon, lignes
supplémentaires, quantités invalides, limite de corps et conservation des retours à la ligne.

QA privée `crm-prefill-qa-20261027-r1/http-v2` : 348 réussites, aucun échec ni saut, 19,96 s;
Ruff et vérificateur 287 outils/173 portées appareil réussis. Population recoupant les précédentes,
non additive. Source en lecture seule, mémoire 1 Gio, CPU 100 %, 96 tâches, réseau bloqué,
homes/tmp privés, empreintes et reçus durables. Ce sont des preuves HTTP/SQLite et de rendu
documentaire, pas une qualification navigateur natif ni un GO produit global.

Le rouge `http-v1` est conservé : le parseur de test sélectionnait le formulaire de déconnexion
de l’en-tête au lieu du formulaire métier; corrigé par sélection explicite de l’ancre du modèle.
La revue a aussi identifié le risque de perte des sauts de ligne dans un input texte; corrigé
par textarea et test de conservation. Aucun contrôle produit n’a été affaibli.

Prochaines étapes : qualification navigateur selon
le harnais autorisé. Mobile reste en dernière phase. Les autres exigences CRM-07 restent ouvertes.

## Choix fournisseur par nom — jalon suivant

`m3_lister_fournisseurs_modele` est un port console privé supplémentaire : admin SQL et réception
serveur exigés, canaux génériques/appareils fermés. Il réutilise le livre M6 et les fiches
fournisseurs réelles; seuls identifiant et nom sont transmis au menu. Aucun courriel, téléphone
ou coût n’est nécessaire à ce choix. Le tarif est toujours relu lors de la préparation puis
de la création. Les quantités et fournisseurs restent des choix explicites de l’utilisateur.

Le lecteur pur `fournisseurs_compatibles` examine au plus 10 000 maillons par registre et
100 fournisseurs distincts pour le matériau. Le dépassement refuse, sans tronquer la liste.
Un dernier tarif futur, d’une autre unité/devise ou invalide rend ce fournisseur indisponible,
sans retour à un ancien prix. Les références non sélectionnables sont signalées. Sans tarif
utilisable, le bouton est désactivé et l’interface indique de compléter M6; les POST restent
contrôlés côté serveur. Les paires matériau/unité répétées partagent une lecture dans la page.

La revue indépendante a révélé qu’une mise à jour fournisseur sans identifiant pouvait laisser
réapparaître l’ancien libellé. La validation du journal fournisseur bloque maintenant ce cas,
les types inconnus, mises à jour orphelines et créations dupliquées, y compris lors du POST final.
Elle ne modifie pas le registre ni ses contrats d’écriture historiques.

Preuve `supplier-v2` : 361 réussites, aucun échec ni saut, 20,70 s, Ruff et vérificateur réussis
(288 outils, 173 portées appareil inchangées). Cas supplémentaires : nom corrigé sans coordonnées,
limites 100/101, corruption de fiche, dernier prix futur, nom HTML échappé, choix initial vide,
absence de fournisseur utilisable et corruption entre préparation/création sans écriture.
Le rouge `supplier-v1` conserve trois constats de lint; ses 355 tests passaient déjà.
Les populations se recoupent. Aucun test navigateur natif ni GO global n’est déduit de ce jalon.

La recherche ciblée dans `catalogue.py`, `livre_prix.py`, `registre.py` et `contrats.py` M6
n’a pas établi de registre durable de noms de matériaux exploitable ici : la résolution de prix
n’est pas un catalogue de libellés. Aucun nom matériau n’est inventé depuis son identifiant.

## Jonction HTTP → acceptation → départements

`tests/test_console_prefill_bus.py` réutilise les formulaires HTTP et le répartiteur réel
de `test_cascade_devis_accepte.py`. Un lead fictif publié par M1 est qualifié dans M2,
puis un devis est créé par HTTP avec modèle M3 et tarif M6. Le brouillon ne crée ni
intervention ni besoin matériaux. Après changement du tarif, l’acceptation explicite
conserve le coût figé 25 CAD et le prix de vente 30 CAD du scénario fictif.

Les cinq consommateurs ont des reçus SQL traités : M2 convertit le lead, M4 inscrit
une intervention à planifier, M5 reçoit le devis, M6 reçoit deux pieds de matériau et
M8 reçoit le fait chantier. Sans stock, M6 marque à commander et réserve zéro; M4
reste bloqué. Aucun achat ni facture finale ni promesse de cédule n’est déclenché.
La provenance privée des tarifs reste absente du message, dont les champs financiers
existants restent inchangés. Rejouer le même événement ou le même devis sous un nouvel
identifiant ne duplique aucun registre métier.

Qualification privée `crm-prefill-qa-20261027-r1/bus-v2` : huit tests réussis, zéro échec
ou saut, 2,71 s; Ruff et vérificateur 288/173 réussis. Sept tests de cascade préexistants
sont réutilisés, résultats non additionnables aux autres campagnes. Le test ne qualifie
ni navigateur natif, ni envoi client, ni acceptation juridique, ni M10, ni PostgreSQL.

## Aperçu du prix de vente avant création

Le formulaire de confirmation affiche les prix unitaires, montants de ligne, coût total
privé et prix de vente total en CAD, taxes en sus. Le calcul pur
`m3_estimation.devis_durable.calculer_lignes_devis` est partagé avec la création durable :
prix unitaire arrondi au cent, puis multiplication par quantité et nouvel arrondi au cent.
Aucune formule parallèle dans l’interface, aucun prix fourni par le navigateur.

La préparation ne crée pas de journal ni de mutation. Les tarifs sont relus lors de la
création avec leurs rangs et empreintes; un tarif changé reste refusé. Les majorations
vides, négatives, non finies, exponentielles, excessives ou trop précises sont refusées
avant affichage du total. Les coûts restent réservés à la console admin.

Les tests HTTP comparent les montants affichés aux montants réellement enregistrés,
notamment le cas de double arrondi : 15,50 CAD × 4 avec majoration 25 % donne 77,52 CAD.
Ce sont des données fictives; le formulaire ne constitue ni un envoi ni une acceptation.

Qualification `crm-prefill-qa-20261027-r1/sale-preview-v2` : 161 tests réussis, aucun
échec ni saut, 9,86 s; Ruff et vérificateur 288 outils/173 portées réussis. Populations
recoupées, non additives. Régression HTTP, jonction du bus, devis durables, stockage et
conformité M3. Revue statique indépendante du calcul, du rendu et des effets sans constat.
Le reçu `sale-preview-v1` reste historique : mêmes 161 tests réussis, une ligne de rendu
trop longue signalée par Ruff puis corrigée; aucune garde affaiblie.

Le raccord de gestion et de choix nommé est qualifié par
`tests/test_console_catalogue_m6_http.py` : création de fiche → sélection de sa version active
→ lignes M3 → devis sourcé M6. L’identité, la révision et l’empreinte de la fiche sont relues
sous la transaction d’enregistrement. Une fiche périmée/inactive refuse le nouveau choix.
Voir [audit et preuves du catalogue](../inventory/M6-AUDIT-CATALOGUE-LIBELLES.md).

Les nouvelles versions de modèles textuels, de lignes et de fiches matériaux publient
maintenant une référence vers M10 dans leur transaction. M10 valide la source puis mémorise
uniquement rang, révision, empreinte et horodatage dans une chaîne privée. Aucun texte ou
prix du modèle n’y est copié. Voir [audit et preuves M10](AUDIT-CATALOGUES-M10.md).

Les fiches et modèles affichent l’état de preuve M10 après revalidation de l’admin SQL :
en attente, reçu et mémoire concordants, échec, quarantaine ou preuve à vérifier. Une
publication seule ne donne jamais le badge mémorisé. Cette consultation est en lecture seule.
