# CRM12 — audit complémentaire du formulaire et du téléchargement

Date : 28 octobre 2026 UTC. Base : `f7957b74b69463cbb117b76cb7f4105e5af867fe`.
Le port privé de pièces reçues est qualifié localement ([contrat](CRM12-PIECES-RECUES.md)); aucune
route HTTP ne l’expose encore. Le besoin reste celui du dossier chantier du secrétariat.

## Réutilisation et décision avant code

`console/fusion_pdf_ui.py` utilise déjà Starlette pour un multipart borné en amont :
`_corps_borne` mesure Content-Length et les morceaux avant le parseur; `_multipart_pdf` ferme le
formulaire et ses fichiers. Réutiliser le lecteur de corps pur et ce schéma de transport, avec
champs propres aux pièces. Aucun appel à Fusion, aucune classe FINANCIAL et aucun parseur PDF.
Starlette et python-multipart sont déjà des dépendances du parcours existant : aucun paquet ajouté.
L’admin authentifié et le rendu privé sont fournis par `crm_ui.creer_router`; le port contrôle
l’autorité SQL. Le dossier actuel n’a pas de lien de dépôt avant travaux. La galerie M3/M4 reste distincte.

## Patch décidé, données et routes

- GET/POST `/crm/lead/{lead_id}/pieces-recues` : page de 20 et dépôt multipart.
- GET `/crm/lead/{lead_id}/pieces-recues/{piece_id}` : téléchargement original autorisé.
- Formulaire fermé : CSRF, saisie hexadécimale, titre explicite, un fichier. Maximum HTTP : 1 Mio
  plus 64 Kio d’enveloppe. Refuser doublons/champs inconnus, encodage inattendu, requêtes hors bornes.
- Clé externe dédiée `OPSYS_PIECES_PROJET_CLE` : base64 canonique de 32 octets, sans valeur par défaut,
  sans reprise de la clé Finance/console/CAS. Pas de génération de secret réel dans cette QA.
  Absence/invalidité : indisponibilité explicite. Rotation et exploitation restent non qualifiées.
- Le nom reçu n’est pas utilisé comme chemin ni en-tête de sortie. L’original n’est jamais rendu inline :
  `application/octet-stream`, attachment avec nom serveur fixe, nosniff, CSP sandbox, no-store.
- Admin SQL vérifié avant lecture du corps; CSRF avant écriture; ancre M2/clé/autorité et contenu
  revérifiés après rendu et avant retour. Le POST et sa trace restent dans la transaction du port.
- Lien depuis le dossier; paramètres de toutes ces routes masqués dans les journaux, y compris refus.

## Risques, gates, tests et statut

L’admission ne certifie pas l’innocuité, les dimensions d’une image ou une signature PDF. Aucun OCR,
aperçu actif, export, courriel, droit agent/DEVICE ou collecte réelle ajouté. Les limites/rétention
et les métadonnées en clair restent celles du port. Tests HTTP : entrée/sortie réelle, CSRF, rôle,
rejeu, mauvais projet, corps trop grand, paramètres dupliqués, corruption, revalidation après rendu,
clé manquante/erronée, HTML échappé et journaux. Puis navigateur privé avec un original fictif si
l’environnement le permet. Aucun déploiement ou configuration de production autorisé par cette tranche.
Statut avant patch : **NON_IMPLÉMENTÉ**. Mobile en dernière phase; CRM12 intégral reste PARTIAL.

## Constat de revue : politique du téléchargement écrasée

Revue statique indépendante : `_EntetesSecurite` dans `console/application.py` remplace la CSP locale
par la politique générale. Le premier test ne vérifiait que `default-src none`, pas `sandbox`.
Reproduire ce défaut à l’en-tête final, puis cumuler la politique locale et la politique obligatoire
sur un seul champ HTTP, conformément au [modèle de politiques multiples CSP du W3C](https://www.w3.org/TR/CSP3/).
La politique générale doit toujours s’appliquer : conserver seulement la politique locale pourrait
relâcher d’autres réponses. Ce petit correctif partagé requiert les régressions de console.

## Qualification après audit et correctif

Raccord HTTP et CSP cumulées implémentés : [résultats et limites](CRM12-PIECES-RECUES-HTTP.md).
237 tests intégrés puis 86 après retouches de texte, sans addition; dépôt et téléchargement réel
d’un PDF fictif vérifiés dans IAB avant toute soumission/WCT. Bibliothèque et production non complètes.
