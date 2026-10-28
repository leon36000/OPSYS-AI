# CRM12 — déposer et télécharger les pièces reçues d’un projet

## Objectif, pourquoi et état

Le secrétariat peut conserver une photo ou un PDF reçu dans le bon dossier M2, avant soumission
acceptée et avant fin de travaux. Le téléchargement rend l’original conservé, pas une reconstruction.
**PARTIAL : tranche serveur SQLite qualifiée localement, publication/CI à réconcilier; aucune production.**
Le classement, les versions, la rétention, les autres rôles et le mobile restent ouverts.
[Audit avant le raccord HTTP](CRM12-AUDIT-TRANSPORT-PIECES-RECUES.md),
[stockage et contrat du port](CRM12-PIECES-RECUES.md).

## Architecture, fichiers et routes

- `console/pieces_projet_ui.py` : formulaire multipart, clé externe dédiée, rendu et téléchargement.
- `console/pieces_projet.py` : ancre M2 exacte, autorité SQL, chiffrement, reçu idempotent, transaction.
- `console/crm_ui.py` : lien depuis le dossier et carte documentaire au statut partiel.
- `console/journaux_http.py` : masque les paramètres, même refusés ou dupliqués.
- `console/application.py` : cumule les CSP locales avec la CSP obligatoire dans un seul champ HTTP.
- `tests/test_console_pieces_projet_http.py` : 31 cas HTTP et politique de sécurité partagée.

Ces chemins sont relatifs à `src/opsys/`, sauf le fichier de tests. Routes privées sous le préfixe
configuré de la console : GET/POST `/crm/lead/{lead_id}/pieces-recues`, GET
`/crm/lead/{lead_id}/pieces-recues/{piece_id}`. La galerie M3/M4 déjà livrée reste distincte.
Aucun nouvel outil agent, MCP ou appareil; aucun élargissement du contrat MIME M4.

## Données et workflow

1. Ouvrir le dossier du projet, puis « Pièces reçues de ce projet : photos et PDF ».
2. Saisir un titre et sélectionner un JPEG, PNG ou PDF de 1 Mio maximum.
3. Le serveur contrôle le rôle admin actif en SQL avant lecture du corps, puis le formulaire fermé,
   le CSRF et l’original. Enveloppe HTTP bornée avant parseur, y compris sans Content-Length.
4. Le port conserve titre et original chiffrés, leur source, auteur et date; pièce et audit atomiques.
   Une saisie rejouée à l’identique rend le même reçu. Une saisie réutilisée autrement est un conflit.
5. La page liste les pièces par projet, par 20, avec taille/type/date/auteur/SHA et `NON_ANALYSE`.
6. « Télécharger l’original » retourne les octets authentifiés, avec un nom serveur fixe. Le nom reçu
   n’est ni un chemin ni un en-tête de sortie et n’est pas conservé par cette tranche.

Revalidation de la clé, de l’ancre M2, de l’autorité SQL et de la sélection après rendu/construction de
réponse. Changement ou corruption : refus, sans octets partiels. Le POST est encore dans sa transaction
jusqu’à ces contrôles : une clé changée après dépôt annule aussi pièce et audit.
L’association porte le lead complet, y compris une opportunité M2 récurrente, pas le client global.
Aucune soumission ni preuve terrain artificielle créée pour rendre le formulaire disponible.

## Configuration et permissions

Cette tranche nécessite la dépendance `cryptography` déjà qualifiée dans l’extra `ingestion`,
et une clé externe dédiée `OPSYS_PIECES_PROJET_CLE` : base64 canonique de **32 octets**.
Elle doit être injectée par la configuration privée du service, avec les protections appropriées,
pas publiée dans une commande, Git, journal, capture ou URL. Aucun secret réel n’a été créé ici.
La clé n’est ni celle des sessions de console ni celle de l’ingestion financière.
Sans configuration valide, la page indique que l’administrateur doit configurer le stockage sécurisé.
Le stockage et le téléchargement restent fermés; aucune clé de secours inventée.
La configuration graphique, la rotation et la restauration avec clés doivent encore être qualifiées.

Admin SQL actif uniquement; session expirée/rôle révoqué refusé. L’employé ne reçoit aucun accès.
Les pièces reçues ne deviennent pas automatiquement des faits financiers, une mémoire M10,
des pièces marketing, des photos de complétion M4 ou une attestation de signature.

## Sécurité des originaux et risques

Pas d’aperçu inline. Réponse `application/octet-stream`, `attachment` avec nom fixe, `nosniff`,
`no-store`, CSP `sandbox` restrictive conservée **avec** la politique générale obligatoire.
Une politique locale plus permissive ne peut pas retirer la politique globale.
La revue a révélé que le middleware écrasait auparavant les politiques spécifiques : deux rouges
l’ont démontré à l’en-tête final avant correction. Le test couvre aussi plusieurs politiques locales.

La signature minimale et le SHA ne certifient pas l’innocuité d’un document. Aucune extraction,
conversion, exécution, OCR ou vérification antivirus; le statut le dit. Les quotas, métadonnées en
clair, conservation immuable et limites de clé sont décrits dans le contrat du port. Pas de promesse
Loi 25 globale, d’effacement de sauvegarde ou de qualification PostgreSQL/multi-instance.

## Tests et preuve navigateur

`crm12-pieces-http-v4` : **237 PASS / 72,88 s**, dont HTTP (31), port (36), CRM (55), galerie (40),
préparation chantier (16), migrations historiques (13), console partagée (46). Lint et vérificateur
natif OK : 10 départements, 306 outils, 177 déclarés aux appareils. Après deux retouches de texte
(carte du dossier et message de configuration), `crm12-pieces-http-v6` : **86 PASS / 23,65 s**
(HTTP + CRM), mêmes contrôles. Populations recoupées : ne pas les additionner.

Navigateur IAB réel sur une instance Linux fictive : connexion → répertoire CRM → dossier du projet
M2 sans devis ni WCT → choix du PDF fictif via sélecteur natif → dépôt POST 303 → liste contenant
une pièce → téléchargement du PDF. Les **605 octets** téléchargés sont exactement ceux de la source,
SHA-256 `438e826a699f7b63a5569394ebbee872783fcca63e92fe136320526793d154d5`.
Trois GET 200 sans DML; un POST ajoute une pièce et une ligne d’audit. Le fixture utilise l’ingestion
native M2; ce n’est pas une preuve M1→terrain complète ni un dossier réel.
Source en lecture seule, home/tmp privés avant imports, CPU 1, mémoire 1 Gio, swap 0, 96 PID, TTL
900 s, écoute IPv4 loopback éphémère et appels connect sortants interdits par le noyau. Serveur
arrêté, PID absent, unité inactive, reçu rc=0, onglet fermé. Les seules modifications après cette
preuve navigateur concernent ces deux textes; le comportement de dépôt/téléchargement est inchangé.

## Gates Nathan et suite

Aucun besoin d’approbation supplémentaire pour ces essais fictifs réversibles. Déploiement, migration
ou donnée de production et engagement externe restent hors mandat. Réconcilier la CI de la tête déjà
publiée avant publication normale du nouveau lot. Puis traiter le classement et les versions/retrait
logique avec audit, la politique de conservation et l’exploitation des clés, sans effacement dur.
Le mobile reste en dernière phase. OPSYS-AI et CRM12 restent PARTIAL.
