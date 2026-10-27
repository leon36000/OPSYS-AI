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
4. Renseigner quantité et référence fournisseur M6 pour chaque ligne, ainsi que la majoration.
5. Vérifier les coûts CAD, date effective, fournisseur et source documentaire affichés.
   Sans pièce, le badge reste `FALLBACK_PRICE_BOOK`.
6. Créer le brouillon. Le dossier permet ensuite de consulter ses documents HTML/PDF.

Les fournisseurs/matériaux sont encore saisis par référence explicite : recherche et sélection
par libellé restent à améliorer. Sans lignes enregistrées, le parcours prérempli refuse;
la saisie manuelle existante reste accessible, ainsi que le lien de configuration des lignes.

## Architecture, fichiers et routes

`src/opsys/console/prefill_ui.py` porte les formulaires et appelle les quatre ports privés
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
de cette tranche. Le consommateur M6 de l’acceptation a été testé au jalon ports; le bus complet
de ce nouveau parcours reste à qualifier séparément.

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

Prochaines étapes : sélection ergonomique par libellé, confirmation complète du prix de vente
avant création, preuve du bus acceptation → départements, puis qualification navigateur selon
le harnais autorisé. Mobile reste en dernière phase. Les autres exigences CRM-07 restent ouvertes.
