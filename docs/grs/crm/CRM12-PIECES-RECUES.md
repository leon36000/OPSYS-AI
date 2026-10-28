# CRM12 — originaux reçus par projet : port privé

## Objectif, pourquoi et statut

Conserver le plan PDF ou la photo reçue pour le **projet M2 exact**, même avant acceptation d’une
soumission et avant fin des travaux. Deux chantiers du même client ont des dossiers distincts.
**PARTIAL : port serveur SQLite qualifié localement.** Le formulaire privé et le téléchargement
sont maintenant raccordés : [qualification HTTP et navigateur](CRM12-PIECES-RECUES-HTTP.md). Aucune bibliothèque complète ni mise en production annoncée.
[Audit avant code](CRM12-AUDIT-PIECES-RECUES-PAR-PROJET.md).

## Architecture et fichiers

- `src/opsys/console/pieces_projet.py` : `deposer`, `lister`, `lire`; port interne console.
- `src/opsys/stockage/schema.py` : `PIECES_PROJET`, table distincte de Fusion/M10 texte/CAS.
- `src/opsys/stockage/migrations/versions/0028_pieces_projet.py` : migration additive depuis 0027.
- `tests/test_console_pieces_projet.py` : 36 cas fictifs, dont concurrence et migration.

La tranche initiale du port (`f7957b74`) n’exposait aucune route HTTP ni nouvel outil agent/appareil. La galerie M3/M4
existante conserve ses routes et permissions. La primitive native M2 résout le client du lead dans
son registre canonique; un hash ou un identifiant ressemblant à un projet n’accorde aucun accès.
Les opportunités récurrentes `<lead>~opp~<wct>` sont résolues intégralement, jamais rabattues à la racine.

## Données et workflow

1. Connexion courante SQLite, session vivante, rôle admin actif **en SQL**.
2. Registre M2 borné puis chaîne vérifiée, projet existant résolu par le lecteur T0 natif.
3. Original JPEG/PNG/PDF de 1 à 1 048 576 octets; titre de 1 à 160 caractères sans contrôles;
   clé externe de 32 octets et saisie de 32 caractères hexadécimaux explicites.
4. SHA-256 source, type déclaré et signature minimale vérifiés. Statut explicite `NON_ANALYSE` :
   ni l’innocuité, ni la validité PDF/image complète, ni une signature juridique ne sont certifiées.
5. AES-256-GCM via `cryptography` déjà retenu, nonces aléatoires, AAD propre incluant identifiant,
   projet/client, auteur, saisie, empreinte, type, taille, date et version. Titre et original chiffrés
   séparément : la pagination ne charge pas les originaux. La clé n’est jamais conservée dans cette table.
6. Pièce immuable et audit humain dans un savepoint natif. Rejeu identique : même reçu, pas de doublon
   ni nouvel audit. Changer projet/titre/type/octets pour la même saisie du même auteur : conflit.
7. Ancre et autorité relues; quota post-écriture; reçu produit par la même lecture authentifiée que
   les consultations. Toute erreur annule pièce et audit, même si l’appelant attrape le refus.

Le reçu contient pièce/projet, titre, auteur, date serveur UTC, type, taille, SHA et statut. L’original
n’est retourné que par `lire`, après authentification du chiffré et contrôle de taille/SHA. Les octets
identiques de deux projets produisent des pièces et des chiffrés distincts. Pas de lien CAS partagé.
Aucun registre M2 modifié par le dépôt, aucun WCT ni devis artificiel, aucune transmission M5/M10.

## Bornes et permissions

128 pièces et 32 Mio de chiffrés base64 (titres compris) pour cette instance pilote; pages de 20.
Les longueurs sont mesurées en SQL **avant** lecture/décodage du chiffré. Registre M2 : bornes natives
10 000 maillons / 8 Mio. Session non admin, expirée ou révoquée : refus avant la source.
Clé absente/invalide, mauvaise clé, corruption ou source modifiée : refus fermé, sans original partiel.
Les métadonnées privées projet/auteur/date/SHA restent lisibles en base par les administrateurs SQL.

## Tests et preuves locales

QA isolée `crm12-pieces-v4` : **160 PASS / 49,12 s**, dont 36 cas de ce port, avec CRM (55), galerie
M3/M4 (40), préparation chantier (16), migrations historiques (13). Ne pas additionner ces populations
aux anciennes exécutions. Lint des fichiers testés et du port/schéma/migration : OK.
Vérificateur natif : 10 départements, 306 outils, 177 déclarés aux appareils, contrats inchangés.

Deux transactions concurrentes pour une saisie rendent un seul reçu et une seule trace. Les cas
négatifs couvrent autre projet du même client, opportunité récurrente native M2, rôle SQL révoqué
avant et pendant dépôt, modification M2 en cours, rejeu différent, mauvaises clés, chiffrés et AAD
corrompus, quotas avant déchiffrement et après écriture, panne du journal et rollback. Migration
0027→0028 conserve le journal; mise à niveau répétée, rétrogradation vide et refus si pièce présente.
Les marqueurs JPEG/PNG/PDF des fixtures sont des sources **non analysées**, pas des fichiers qualifiés
pour décodage/affichage. Aucun navigateur ni parcours complet terrain n’est prétendu.

Préflight M10 privé frais et borné, sources versionnées épinglées : la mémoire vide de cette instance
fictive n’est pas la mémoire du projet. Revue statique indépendante : rejet des identifiants `~opp~`
reproduit, corrigé et testé. Premiers rouges et défauts de harnais/lint conservés séparément.

## Risques, gates Nathan et prochaines étapes

Le port reçoit explicitement une clé; le raccord de configuration externe sécurisé est encore à faire.
Pas de clé de production générée ni de migration de production exécutée. La perte de la clé rend les
originaux illisibles; rotation/version des clés, restauration et exploitation restent à qualifier.
Pas d’OCR, antivirus/CDR, aperçu actif, classement, versions, retrait, purge, politique de conservation,
effacement de sauvegardes, accès employé/vendeur/client/agent, export ou utilisation marketing.
Le chiffrement ne certifie pas la conformité Loi 25. PostgreSQL et multi-instance non qualifiés.

Prochaine tranche : formulaire privé borné avec CSRF et clé externe dédiée, lien depuis le dossier,
téléchargement forcé sans nom utilisateur dans les en-têtes, journaux masqués, revalidation après rendu,
tests HTTP puis navigateur fictif. App mobile en dernière phase. Le besoin CRM12 intégral reste ouvert.
