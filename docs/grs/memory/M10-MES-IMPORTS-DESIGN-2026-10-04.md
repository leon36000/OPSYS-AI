# M10 — retrouver ses imports après fermeture du navigateur

## Problème vérifié et réutilisation

Le manifeste du commit `05fea996` est durable, mais le parcours initial exige sa clé
opaque conservée par le navigateur. PostgreSQL garde seulement son empreinte. Après
fermeture/perte de l'onglet, un administrateur ne trouve pas facilement son lot partiel.
Le parcours Fusion CSV possède déjà une liste privée de lots et des liens de reprise
(`fusion_ui.py`, `fusion_csv.lister`). Réutiliser ce principe d'interface et les tables
M10 présentes suffit; aucune brique externe ni deuxième vérité n'est nécessaire.

## Choix retenu

« Mes imports M03 » affiche au plus 64 manifestes de **l'auteur courant**. Les états
sont projetés des versions/séries, sans corps ni clé originale stockée ou affichée.
La référence de lecture/reprise est le SHA-256 de clé déjà persisté. Elle n'est jamais
une autorisation : auteur, session administrateur vivante et CSRF restent obligatoires.
Le POST de création garde la clé originale pour préserver son rejeu/idempotence.
Les chemins historiques par clé continuent à fonctionner.

Contrats internes : `lister_lots(*, auteur)` → `ResumeLot(reference,
nombre_emplacements, attente, recu, indexe, actifs)`; `lire_lot_reference(reference,
*, auteur)`; `admettre_emplacement_reference(reference, position, contenu, *, auteur)`.
La référence est strictement 64 caractères hexadécimaux minuscules. Lecture et
admission convergent vers les mêmes helpers transactionnels existants. Aucun DDL.

GET `/memoire/procedures/imports` : liste + formulaire actuel.
GET `/memoire/procedures/imports/ref/{reference}` : état propriétaire.
POST `.../ref/{reference}/reprendre` : mêmes fichiers exacts et validations que la
reprise historique. Les handlers historiques et par référence partagent parsing,
contrôle, gestion de panne, rendu privé et revalidation d'identité avant chaque effet.
Les autres propriétaires et lots effacés sont introuvables. Toute erreur de stockage
reste 503; aucune donnée issue d'un lot ne doit être rendue après révocation de rôle.

## Plan et preuve requise

1. Projection SQL propriétaire et helpers par référence partagés, nouveaux tests PG.
2. Liste/rendu/reprise dans la console; parcours PostgreSQL avec navigateur/service
   nouvellement créés après premier succès puis panne, sans connaître la clé initiale.
3. Autre auteur exclu et accès direct refusé, références invalides, hash modifié avant
   effet, état actualisé après indexation/activation et oubli retirant la liste/reprise.
4. Exécuter les sept fichiers de la qualification précédente + les nouveaux complets,
   Ruff, gardes, gel des sources, contrôles de secrets, preuves et publication de branche.

Le fichier non encore admis doit toujours être renvoyé par l'utilisateur. Cette tranche
reste interne M03 TXT/MD; elle ne fournit ni import client général, classement massif,
OCR/PDF, entraînement ni score d'assimilation représentatif. M10 reste PARTIEL.
