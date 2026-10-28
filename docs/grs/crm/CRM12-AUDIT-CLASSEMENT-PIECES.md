# CRM12 — audit avant classement manuel des pièces reçues

Date : 28 octobre 2026 UTC. Source : `9e4b6edfb832e4303550dc9d0d45a10bd91040fb`.
Statut avant code : **ABSENT**. Dépôt et téléchargement privés existent; pas de catégorie métier
modifiable ni d’historique de classement. Besoin : retrouver le plan, la correspondance ou les pièces
matériaux d’un chantier, sans confondre un rangement administratif avec une validation métier.

## Réutilisation examinée

Le [port de pièces reçues](CRM12-PIECES-RECUES-HTTP.md) possède déjà l’original chiffré, son titre,
son auteur, son SHA et son ancre M2. Son AAD authentifie ces champs : les modifier casserait le fichier.
Il faut un historique compagnon, sans UPDATE de l’original ni réécriture de sa clé/AAD.

`m4_field_ops/couleurs_calendrier.py` fournit le précédent métier : catalogue fermé, révision attendue
strictement entière, reçu idempotent retrouvé avant CAS, historique distinct et pagination à plafond
stable. Réutiliser ce mécanisme sans les ancres/créneaux ou droits DEVICE de M4.
`m2_revenue_crm/clients.py` conserve aussi les corrections avec révision et historique; sa portée
**client** ne convient pas à une pièce d’un projet exact. `m10_memoire/classification.py` classe les
événements, et `confidentialite.py` gouverne les accès : leurs classes INTERNAL/FINANCIAL ne sont
pas des catégories de rangement. Aucune de ces permissions ne sera déduite du choix de l’admin.
Recherche native indépendante statique, sans imports/exécution/écriture, concordante avec cet audit.
Les candidats GitHub/GitLab documentaires ont déjà été examinés dans l’audit des pièces reçues
(cryptography/Mayan EDMS); aucun nouveau service, paquet ou code tiers nécessaire pour ce raccord.

## Patch minimal retenu

- Historique SQL append-only compagnon `pieces_classements`, migration additive 0029 depuis 0028.
  Réutiliser SQLAlchemy/Alembic, savepoint, autorité SQL et ancre M2; pas de stockage parallèle externe.
- Catégories fermées : non classée, plan, photo, correspondance, devis/contrat, matériaux, autre.
  Ce choix est un libellé administratif manuel, jamais une attestation juridique, comptable ou terrain.
- Chaque correction conserve pièce/projet exact, catégorie avant/après, auteur SQL, date serveur,
  révision/précédent, source de l’original, mutation idempotente et empreinte de chaîne.
  Motif fermé choisi par l’admin : organiser le dossier ou corriger une erreur; pas de texte privé
  ajouté dans ces métadonnées. Aucun classement automatique par extension, LLM ou OCR.
- Absence d’historique : « Non classée », révision 0, sans écriture inventée. Révision attendue/CAS
  et saisie différente : conflit. Rejeu ancien rendu comme reçu historique, pas comme état courant.
- 32 révisions par pièce, 4096 lignes globales, bornes SQL avant lecture des lignes, pagination de 20
  avec plafond de révision conservé. Intégrité et source propres au compagnon : l’AAD de l’original
  ne protège pas à lui seul les catégories.
- Page GET/POST `/crm/lead/{lead_id}/pieces-recues/{piece_id}/classement`, lien depuis la pièce.
  Formulaire fermé et borné, CSRF; admin avant corps et après rendu/écriture, clé/ancre relues.
  Pas de retrait, suppression, déplacement vers un autre projet ou nouveau droit agent/appareil.

## Tests, risques et gates

Démontrer d’abord l’absence de capacité. Tester classement/réconnexion, original inchangé, projet
étranger du même client, rôle révoqué, mauvaise clé/source, rejeu après correction, CAS concurrent,
corruption chaîne/source, quotas prélecture et rollback journal; migration vide/antérieure et refus de
rétrogradation occupée. Tester formulaire, doublons/champs inconnus, CSRF, revalidation après rendu,
pagination et histoire figée, puis navigateur fictif si possible. Ne pas additionner les cohortes.

Les empreintes permettent de détecter une incohérence; elles ne certifient pas une inviolabilité face
à un administrateur SQL malveillant. Clé, rétention, exploitation/production et mobile restent aux
limites du port. Aucun secret réel ni migration de production. Root seul Source/Git writer;
préflight M10 privé frais avant code. Le produit et CRM12 restent PARTIAL.

## Résultat après l’audit

[Port, HTTP et navigateur](CRM12-CLASSEMENT-PIECES.md) qualifiés localement : 225 tests intégrés,
50 nouveaux; original téléchargé identique après deux classements. Le contrôle tardif du compagnon
sur rejeu et celui du POST après construction de la réponse ont été reproduits rouges puis durcis.
Le besoin documentaire complet et la publication de cette tranche restent ouverts.
