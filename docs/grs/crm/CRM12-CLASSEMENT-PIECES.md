# CRM12 — classement manuel et historique des pièces reçues

## Objectif, pourquoi et statut

Le secrétariat range une pièce dans le dossier du chantier exact et peut corriger ce rangement tout
en retrouvant les choix antérieurs. Le fichier original reçu reste identique.
**PARTIAL : tranche locale SQLite qualifiée; publication en attente de la CI précédente.** Le besoin
documentaire intégral, les filtres de liste, les versions, le retrait/rétention, les autres rôles,
l’exploitation des clés et le mobile restent ouverts. [Audit préalable](CRM12-AUDIT-CLASSEMENT-PIECES.md).

## Architecture, fichiers et routes

Sous `src/opsys/` :

- `console/classement_pieces.py` : compagnon versionné et contrôles de source, CAS et rejeu.
- `console/classement_pieces_ui.py` : formulaire privé et consultation de l’historique.
- `console/pieces_projet_ui.py` : lien par pièce et refus HTTP explicites.
- `console/crm_ui.py` : raccord du routeur; mêmes autorisations de console.
- `stockage/schema.py`, `stockage/migrations/versions/0029_pieces_classements.py` : table additive
  `pieces_classements`, liée à `pieces_projet`. Aucun UPDATE de l’original, du titre chiffré ou de son AAD.
- `tests/test_console_classement_pieces.py` et `tests/test_console_classement_pieces_http.py` : 50 cas nouveaux.

GET/POST privé `/crm/lead/{lead_id}/pieces-recues/{piece_id}/classement`, sous le préfixe configuré.
Accès depuis « Classement et historique » dans la liste des pièces du projet. Cette liste ne filtre
pas encore les catégories et n’affiche pas une catégorie courante pour chaque ligne.
Les primitives de [dépôt/téléchargement](CRM12-PIECES-RECUES-HTTP.md) restent les propriétaires des originaux.

## Données et workflow

Catégories fermées : **Non classée, Plan, Photo, Correspondance, Devis / contrat, Matériaux, Autre**.
Motifs fermés et explicitement choisis : **Organiser le dossier**, **Corriger une erreur**.
Il s’agit de rangement administratif manuel, indépendant du MIME. Un PDF scanné peut être rangé
comme photo; le type du fichier ne change pas. Cela ne valide ni un contrat ni une comptabilisation.

1. Admin actif confirmé en SQL, session vivante, clé externe valide, ancre M2 exacte.
2. Lecture authentifiée de l’original reçu, puis contrôle borné du compagnon et de ses parents.
3. Sans historique : « Non classée », révision 0, aucune ligne inventée.
4. L’admin choisit catégorie/motif et soumet la révision courante avec CSRF et intention unique.
5. Une nouvelle révision append-only conserve avant/après, auteur, date serveur UTC, motif, projet,
   référence de pièce, SHA source de l’original, mutation, précédent et empreinte de chaîne.
   Classement et audit sont dans le même savepoint puis la transaction HTTP.
6. Même saisie/mêmes arguments : reçu initial exact, même après une correction ultérieure.
   Le reçu historique est nommé comme tel; le classement courant reste affiché séparément.
   Réutiliser la saisie autrement, soumettre une révision périmée ou un choix inchangé est un conflit.
7. Ancre, autorité, original et compagnon relus avant retour/commit. Une modification tardive
   annule classement et audit, y compris après construction de la réponse de redirection.

Le principe réutilise les repères manuels M4 : registre compagnon, reçu avant CAS, historique
paginé à plafond stable. Les ancres d’intervention, les permissions DEVICE et les classes M10 ne
sont pas transférées à cette fonction. Aucun événement M5/M10, extraction, OCR ou modèle appelé.

## Pagination, bornes et permissions

20 révisions par page; le lien conserve `revision_max`. La page montre aussi le véritable état
courant, même s’il a évolué depuis la première page d’historique. Le formulaire soumet la révision
courante visible et reste protégé par CAS. 32 révisions par pièce, 4096 lignes globales et 4 Mio de
métadonnées; mesures SQL avant chargement des lignes. Limites du dépôt inchangées : 128 pièces,
1 Mio par original, 32 Mio de chiffrés. Refus explicite hors capacité, aucun historique tronqué silencieusement.

Le formulaire URL-encodé est borné à 4096 octets avant parseur; champs, doublons, entiers et paramètres
fermés. Rôle SQL vérifié avant le corps et après effet/rendu, clé relue, aucun droit agent/appareil/
employé/vendeur/client ajouté. Métadonnées de classement et audit restent privées mais en clair en SQL.
Les empreintes détectent les incohérences; elles n’attestent pas une inviolabilité contre un administrateur
SQL malveillant. La preuve d’original ne suffit pas seule à authentifier son classement compagnon.

## Tests et preuve navigateur

`crm12-classement-http-v3` : **225 PASS / 70,89 s** : classement (28 port + 22 HTTP), dépôt (36 port +
31 HTTP), CRM (55), galerie M3/M4 (40), migrations historiques (13). Lint et vérificateur natif OK :
10 départements, 306 outils, 177 déclarés aux appareils. Ces cohortes recoupent les essais précédents :
ne pas les additionner.

Contrôles négatifs : catégories inconnues et faux niveaux M10, projet étranger du même client,
révocations avant source/pendant effet, original intact, corruption du compagnon, CAS concurrent
(deux connexions SQLite, un seul gagnant), reçu ancien après correction, pagination plafonnée,
quotas prélecture/postécriture, panne d’audit et rollback. Migration 0028→0029 répétée, original
conservé lors du retour vide en 0028, rétrogradation refusée si historique présent.

Deux lacunes tardives ont été reproduites puis corrigées : le rejeu relit aussi le compagnon après
fermeture des sources; le POST frais compare le classement validé après construction de sa réponse.
Le premier rouge HTTP suivait la redirection : le GET refusait la corruption, alors que la ligne et
l’audit avaient déjà été commités. Le test final vérifie directement le POST et l’absence de DML persistant.
Les échecs/lints initiaux restent conservés, sans conversion en succès.

IAB réel, données fictives : déconnexion/reconnexion explicite → CRM → dossier M2 sans devis/WCT →
dépôt PDF → classement Plan → correction Photo → deux révisions visibles → téléchargement original.
Les **605 octets** et le SHA `438e826a699f7b63a5569394ebbee872783fcca63e92fe136320526793d154d5`
restent identiques après les classements. Sept GET 200 sans DML; trois POST 303 ajoutent respectivement
pièce/audit puis une révision/audit à chaque classement. Un sélecteur `getByLabel` exact n’avait aucun
match, sans effet; le contrôle accessible `combobox` a fonctionné après inspection du DOM. Ce défaut
initial d’automation n’est pas un bug produit.

Enveloppe Linux privée : Source en lecture seule, home/tmp avant imports, CPU 1, mémoire 1 Gio,
swap 0, PID 96, TTL 900 s, écoute loopback éphémère et connect sortants interdits par le noyau.
Serveur arrêté, PID absent, unité inactive, reçu rc=0, onglet fermé. Préflight M10 privé frais et
sources versionnées épinglées; cette mémoire vide de développement n’est pas la mémoire du projet.

## Gates Nathan, risques et prochaines étapes

Aucune donnée réelle, clé réelle, migration/déploiement de production, engagement, suppression ou
permission supplémentaire. Pas de retrait, purge, version du contenu, classement IA, classement en
masse, export ou usage marketing. Bibliothèque complète, politique de rétention, rotation/restauration
et accès multi-profils restent à qualifier. Le mobile suit les grandes exigences serveur.

Prochaine capacité : faire apparaître la catégorie courante dans la liste du projet et permettre un
filtrage borné, sans déchiffrer tous les originaux ni mélanger les projets. Auditer ce raccord avant code.
Réconcilier la CI de la tête publiée avant publication normale de ce lot local. OPSYS-AI reste PARTIAL,
`runtime_GO=false`, `global_PASS=false`.
