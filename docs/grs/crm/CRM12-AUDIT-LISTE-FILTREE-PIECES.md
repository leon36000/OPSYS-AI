# CRM12 — audit avant catégories courantes et filtre dans la liste du projet

Date : 28 octobre 2026 UTC. Source : `9a13def776c7b16bc326d24641b450c540bf3562`.
État : dépôt, téléchargement, classement manuel et historique qualifiés localement; la liste ne
montre pas les catégories et ne les filtre pas. Besoin du secrétariat : retrouver rapidement les
plans ou pièces matériaux d’un chantier précis, en conservant un classement courant fiable.

## Sources et réutilisation

`console/pieces_projet.py.lister` projette déjà les métadonnées par projet, sans sélectionner le
chiffré original. `_recu` authentifie le titre et les métadonnées AAD; `_borner` mesure la base avant
lecture. `console/classement_pieces.py._charger` contrôle le compagnon, ses parents, révisions et
empreintes. Sa lecture détaillée `lire` authentifie également l’original : l’appeler pour chaque
ligne ferait inutilement lire et déchiffrer tous les fichiers. M4 `couleurs_calendrier.resumer`
montre le précédent utile : état courant d’un ensemble d’ancres autorisées. Réutiliser le mécanisme,
sans les droits/ancres M4. Aucun nouveau service, package ou candidat tiers nécessaire; les recherches
GitHub/GitLab documentaires sont consignées dans les audits précédents de cette même capacité.

## Patch décidé avant code

- Ajouter `classement_pieces.lister_projet` en composition privée : autorité SQL et ancre M2 exacte,
  bornes natives, projection des seules métadonnées du projet, compagnon validé et catégorie courante.
  Le port de base `pieces_projet.lister` conserve son contrat. Aucune migration ou écriture nouvelle.
- Authentifier les titres/métadonnées de ce projet (128 pièces maximum), sans sélectionner ni
  déchiffrer le chiffré des originaux. Ne pas déchiffrer les titres d’autres projets du même client.
- Catégorie fermée facultative; filtre appliqué **avant pagination**, page de 20, total filtré et
  total du projet distincts. Aucun rapprochement sur SHA ou client global.
- Empreinte de lecture liant projet, filtre, source M2, métadonnées brutes et historique compagnon
  de ce projet. Les pages suivantes exigent cette empreinte; toute évolution pertinente demande
  d’actualiser la liste. Ce garde de fraîcheur n’est pas un droit d’accès ni un snapshot archivé.
- Formulaire GET de filtre, catégorie et révision visibles sur chaque pièce; liens précédent/suivant
  conservent filtre et empreinte. Actualiser enlève l’empreinte périmée. POST de dépôt inchangé.
- Paramètres fermés/dupliqués refusés; ancre, clé, autorité et vue complète relues après rendu.
  Journalisation des requêtes documentaires déjà masquée pour cette route, y compris refus.

## Tests et risques

Démontrer l’absence, puis liste/catégorie/absence explicite, filtre avant page, totaux, pagination
sur 21 correspondances dispersées, token lié au filtre/projet et refus après dépôt/reclassement.
Prouver qu’aucune colonne originale `chiffre` ne sort de SQL et qu’aucun déchiffrement original n’a
lieu; titres étrangers hors scope, rôle révoqué avant lecture et pendant rendu, compagnon corrompu,
paramètres invalides et lecture sans DML. Régressions dépôt/classement/CRM, puis navigateur fictif.
Les bornes du compagnon sont globales : une incohérence globale reste un refus fermé, pas un zéro.
L’intégrité du contenu original reste vérifiée au téléchargement; la liste indique `NON_ANALYSE`.

## Gates, statut et suite

Root seul Source/Git writer; préflight M10 privé frais avant code, mémoire vide de QA distincte de
la mémoire du projet. Données et clés fictives uniquement. Aucun nouveau droit, classement automatique,
classe financière/M10, migration de production, retrait, purge, export ou déploiement.
Clés/rétention/versions/multi-profils/mobile restent ouverts. OPSYS et CRM12 restent PARTIAL.

## Résultat de la tranche

Liste, catégorie courante et filtre qualifiés localement : **253 PASS / 93,58 s**, lint et
vérificateur natif OK. 28 nouveaux cas (18 port, 10 HTTP); les autres sont des régressions recoupées.
Navigateur réel sur 41 pièces fictives : 21 plans répartis sur deux pages, changement vers Photo
réinitialisant la pagination, correction Plan→Photo, ancien lien refusé 409 puis actualisation à
20 plans. Neuf GET sans DML; un POST ajoute uniquement révision et audit. Sources épinglées,
unité privée arrêtée et onglet fermé. Voir le [contrat détaillé](CRM12-LISTE-FILTREE-PIECES.md).
La CI publiée 9e4 reste rouge terminale (socle et gate) : nouvelle publication suspendue au diagnostic.
