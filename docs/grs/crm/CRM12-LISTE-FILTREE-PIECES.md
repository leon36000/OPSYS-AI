# CRM12 — catégorie courante et filtre des pièces reçues

## Objectif, pourquoi et statut

Retrouver les plans, photos ou documents matériaux d’un chantier sans parcourir toutes ses pièces.
La liste affiche le classement manuel courant et sa révision. **Tranche SQLite privée qualifiée
localement; produit PARTIAL.** Publication en attente du diagnostic de la CI précédente, rouge.
[Audit avant code](CRM12-AUDIT-LISTE-FILTREE-PIECES.md).

## Architecture, fichiers, routes et données

`src/opsys/console/classement_pieces.py.lister_projet` compose les métadonnées natives du dépôt
avec son compagnon validé. `pieces_projet_ui.py` rend le filtre, les comptes et les liens; le port
historique `pieces_projet.lister` garde son contrat. Aucune migration, dépendance ou écriture ajoutée.
Tests : `tests/test_console_liste_pieces_classees.py` et son compagnon `_http.py`.

GET privé `/crm/lead/{lead_id}/pieces-recues`, préfixé par la console. Paramètres fermés :
`categorie`, `decalage` et `source_attendue`. Sept catégories manuelles natives; toutes par défaut.
20 résultats par page, maximum 128 pièces; filtre avant pagination. Le nombre correspondant et le
nombre total du projet restent distincts. Sans classement, « Non classée », révision 0.

Les titres et manifestes du projet exact sont authentifiés par leur AAD natif et comparés à
l’ancre M2 client/projet. Aucun SELECT du chiffré original, aucun déchiffrement des originaux,
aucun titre d’un autre projet déchiffré. La catégorie vient du compagnon contrôlé par identifiant
exact de pièce, pas d’un rapprochement sur SHA ou du client global.

## Workflow et intégrations

1. Admin SQL vivant, clé externe et source M2 autorisées avant lecture.
2. Métadonnées bornées et authentifiées, catégories courantes jointes, filtre puis page.
3. Les liens gardent le filtre et une empreinte liant projet, filtre, source M2, métadonnées et
   historique pertinent. Une modification rend le lien périmé : HTTP 409 « Liste à actualiser ».
4. « Actualiser les résultats » conserve la catégorie mais retire empreinte et décalage.
   Changer de filtre recommence aussi à la première page.
5. Ancre, clé, autorité et sources relues après rendu. Le rendu d’un refus 409 relit aussi l’autorité.

Dépôt, téléchargement et classement restent leurs ports propriétaires. Aucun appel modèle, OCR,
M5, M8 ou M10 métier; préflight M10 de développement frais avant code, instance privée vide distincte
de la mémoire du projet. Les paramètres documentaires restent masqués dans les journaux HTTP.

## Permissions, risques et gates Nathan

Accès console admin SQL seulement, aucun rôle employé/vendeur/client/appareil élargi. Les bornes
natives du dépôt et du compagnon restent appliquées avant chargement. Une incohérence globale du
compagnon refuse la lecture plutôt que d’inventer zéro résultat. Le garde de fraîcheur n’accorde
aucune autorité et ne constitue pas une archive immuable.

La liste prouve ses métadonnées, pas l’intégrité actuelle des octets originaux : leur contrôle reste
au téléchargement. `NON_ANALYSE` reste visible. Aucun antivirus, validation de signature, classement IA,
versionnement du contenu, retrait, purge, export ou usage marketing qualifié. Clés réelles,
rétention/restauration, multi-profils et mobile restent ouverts; aucune production ni déploiement.

## Tests et preuve navigateur

`crm12-filtre-http-v3` : **253 PASS / 93,58 s**; 18 nouveaux tests port et 10 HTTP, puis classement,
dépôt, CRM, galerie et anciennes migrations. Cohorte recoupant 225/237 précédents : ne pas additionner.
Lint ciblé et vérificateur natif OK (10 départements, 306 outils, 177 déclarés aux appareils).
Négatifs : mauvais paramètre/token, token d’autre filtre/projet, dépôt/reclassement, rôle révoqué,
corruption de titre même hors filtre, original corrompu listé NON_ANALYSE mais téléchargement refusé,
changement tardif et absence de DML GET. L’absence initiale et le lint B904 restent historiques.

IAB réel : connexion fictive → CRM → dossier → 41 pièces, dont 21 plans et 20 photos → Plan, page 2
avec le 21e résultat → Photo, première page de 20 → Plan → correction manuelle Plan→Photo → ancien
lien page 2 refusé 409 → actualisation à 20 plans. Neuf GET sans DML; un POST 303 ajoute exactement
une révision et une ligne d’audit. Source figée et empreintes relues après fermeture.

CPU 1, mémoire 1 Gio, swap 0, PID 96, TTL 900 s, Source lecture seule, home/tmp privés avant imports,
écoute loopback éphémère et connexions sortantes interdites par le noyau. Serveur arrêté, PID absent,
unité inactive, reçu rc=0 et aucun onglet de test restant.

## Suite

Corriger les fixtures historiques identifiées dans la CI publiée 9e4, puis publier les lots locaux
avec leurs preuves sans effacer les rouges. Les versions documentaires, la politique de rétention,
les profils autorisés et la bibliothèque intégrale restent des capacités distinctes à auditer.
OPSYS-AI demeure PARTIAL, `runtime_GO=false`, `global_PASS=false`.
