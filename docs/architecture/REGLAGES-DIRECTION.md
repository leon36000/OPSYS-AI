# Réglages de direction (CFG-1) : décider les seuils depuis la console, sans éditer un fichier

Statut (2026-11-02) : **livré et prouvé sur SQLite, avec des données fictives, sur les vrais outils de M2 et de M8, le vrai sas
N3 et la vraie console (client HTTP de test).** Branchés : **M2** (trois délais, les bandes de valeur du score) et **M8** (les
six couples « pire / cible » du score de santé). Les autres départements (M3 barème, M4, M5…) se branchent de la même façon
(§7) ; rien n'y est fait. Aucune valeur réelle, aucun envoi : ce chantier ne fait que ranger des décisions de direction.

## 1. Le problème

Les seuils de direction (dormance d'un lead, devis périmé, fréquence des relances, bornes du score de santé…) vivaient dans le
`department.yaml` du paquet, que le propriétaire ne peut pas éditer. Vides à dessein (aucune valeur n'est inventée), ils
laissaient des fonctions **inertes** (« à configurer ») ou **indéterminées** (score de santé). Les valeurs proposées par les
analyses d'écart (« recommandation, non validée ») dormaient dans des documents.

## 2. Le mécanisme en une page

1. **Le département DÉCLARE** ce que la direction doit décider, dans le bloc `reglages:` de son `department.yaml`
   (`opsys.reglages.declaration`, schéma fermé) : clé `m2.nom`, libellé en français, chemin lu par le département
   (`configuration.segments.jours_inactivite_dormant`), type (`entier`, `decimal`, `texte`, `liste_entiers_croissants`,
   `bornes_pire_cible`), unité, **bornes de saisie** obligatoires (refuser une faute de frappe, pas un seuil d'affaires), niveau
   d'approbation (**N3 seulement** pour l'instant), « ce que cela débloque » et, facultativement, une **proposition** :
   valeur + étiquette exacte « recommandation, non validée » + justification + source écrite. Une déclaration ne porte jamais
   une valeur en vigueur. Une clé inconnue, un type inconnu, un niveau N4, un chemin hors `configuration`, un doublon ou une
   proposition hors bornes sont des **refus à la lecture du manifeste** (`opsys-metier verifier` les voit).
2. **La direction ADOPTE** par un geste N3 : l'écran « Réglages de direction » de la console (ou l'approbation d'une demande
   d'agent dans la page « Approbations ») fait passer l'outil `m9_adopter_reglage` par le sas existant (`approbations.decider`).
   **Seul le propriétaire** (`nathan_owner`, personne active relue en base) décide ; l'outil relit lui-même l'approbateur, le
   niveau de la demande et l'instant de la décision du serveur (`approbateur_en_cours`). Un appel sans cette situation (agent,
   appareil, ligne de commande, test direct) est refusé avant toute écriture : **jamais d'auto-adoption**, une proposition ne
   s'applique pas d'elle-même (le champ est prérempli, la raison et le clic restent à la personne).
3. **Le magasin garde** chaque geste (`opsys.reglages.magasin`) : un registre **append-only et chaîné** (`registres_maillons`,
   département de stockage `opsys-reglages`, aucune migration : portable SQLite / PostgreSQL). Un maillon : qui, rôle, quand
   (horloge du serveur à la décision), ancienne valeur, nouvelle valeur, raison, version du réglage, demande approuvée,
   empreinte du précédent et la sienne. **Retour arrière en une opération** (`m9_revenir_sur_reglage`, N3 aussi) : la valeur
   en vigueur est le sommet d'une pile rejouée depuis la chaîne ; un retour arrière dépile (adoption A, adoption B, retour : A,
   retour : aucune).
4. **Les départements LISENT par une couche unique** (`opsys.reglages.lecture.superposer`) : ils appellent
   `superposer(manifeste_lu, bloc, valeur_du_fichier)` à l'endroit où ils lisaient déjà leur configuration (une ligne par
   département : `_bloc_configuration` de M2, `_configuration` de M8). Pas de cache, pas d'évènement à consommer : l'adoption
   est visible à l'appel suivant.
5. **L'écran dit tout** : ce qui est vide, ce que ça bloque, la proposition et son origine, la valeur en vigueur et d'où elle
   vient, le journal des gestes. L'outil `m9_lire_reglages_manquants` (N0) donne la même chose aux agents, en pages bornées,
   sans raison libre ni journal.

## 3. La précédence (la seule règle)

Réglage par réglage : **1. valeur adoptée** (chaîne valide, conforme à la déclaration actuelle) **> 2. valeur déjà écrite dans
`department.yaml`** (compatibilité : rien n'est cassé pour qui l'a remplie) **> 3. absence** (le département reste fail-closed
exactement comme avant : « seuil à configurer », score indéterminé). Une proposition n'est jamais lue par un département.
Sans rien d'adopté, `superposer` rend la valeur du fichier **telle quelle (le même objet)** : aucun changement de comportement
(la suite de M2 : 2 278 tests, celle de M8 : 1 615 tests, passent à l'identique).

Ce qui n'est **pas** servi, par conception (on retombe sur 2 puis 3) : hors transaction ; chaîne qui ne se rejoue pas (valeur
modifiée à la main, maillon retiré ou échangé, même avec l'empreinte refaite) — alors **aucune** valeur adoptée n'est servie,
l'écran le signale en alerte et aucun geste n'est accepté ; valeur adoptée devenue incompatible avec la déclaration (bornes
resserrées depuis) ; réglage que le manifeste du département qui lit ne déclare pas ; base sans le registre. Un bloc illisible
du fichier (`segments: 5`) est remplacé par la valeur adoptée, et rendu tel quel sans adoption (le département dit « invalide »).

## 4. Les garanties et leurs preuves

| Garantie | Où c'est prouvé |
|---|---|
| Schéma de déclaration fermé ; propositions étiquetées, sourcées, dans leurs bornes ; M8 sans proposition | `tests/test_reglages_declaration.py` |
| Chaîne, idempotence, version attendue, retour arrière, raison sans renseignement personnel, falsification (chaque contrôle isolé), maillon illisible, deux fils concurrents | `tests/test_reglages_magasin.py` |
| Les mêmes gestes, la chaîne falsifiée, la course de deux fils, une base sans le registre et le geste complet de la console sur SQLite **et** PostgreSQL 17 éphémère | `tests/test_reglages_postgresql.py` |
| Précédence, compatibilité avec `department.yaml`, fail-closed, état « ce qui manque » | `tests/test_reglages_lecture.py` |
| Jamais d'auto-adoption : décision forgée (rôle, personne, niveau, outil, demande non en cours), agent, journal d'audit | `departments/m09-strategic-intelligence/tests/test_outils_reglages.py` |
| Écran : accès (propriétaire / administrateur / employé), CSRF, champs fermés, bornes, double envoi, retour arrière, échappement | `tests/test_console_reglages.py` |
| Bout en bout M2 et M8, panne, redémarrage, chaîne falsifiée, compatibilité | `tests/test_reglages_bout_en_bout.py` |

## 5. Les propositions (aucune valeur inventée)

Les trois délais de M2 (`30`, `14`, `7` jours) sont les **exemples chiffrés écrits dans le manifeste de M2** depuis T4.6 et T4.9,
repris tels quels, étiquetés « recommandation, non validée » et dits **illustratifs, jamais calibrés sur l'entreprise**. Les
bandes de valeur du score (des montants en dollars) et **toutes** les bornes du score de santé n'ont **aucune proposition** :
l'analyse d'écart de M8 recommande de laisser tourner les mesures quatre à huit semaines avant de fixer « pire » et « cible »
(ANALYSE-M8 §5, Q1). Aucune valeur fiscale ou tarifaire n'est écrite nulle part dans ce chantier.

## 6. Ce qui est volontairement absent

- **Pas de péremption** des valeurs adoptées (l'analyse d'écart de M2 évoquait « 90 jours renouvelables », comme les
  politiques de service) : un seuil de direction qui expire en silence rendrait une fonction inerte sans que personne l'ait
  décidé. À rouvrir si la direction le veut ; le retour arrière couvre le besoin de défaire.
- **Pas de niveau N4** : un réglage N4 ne pourrait pas être adopté tant qu'aucun outil N4 n'existe ; le manifeste le refuse.
- **Pas d'évènement du bus** : les départements relisent la couche à chaque appel, il n'y a donc rien à invalider ni personne à
  prévenir ; un évènement sans consommateur aurait seulement ajouté une garantie à tenir.
- **`ponderations_validees_par` (M8)** n'est pas encore un réglage : adopter des bornes ne valide donc pas les pondérations du
  score, qui restent « proposition non validée » dans la lecture (testé).
- **Aucun droit d'appareil** : ni la lecture ni l'adoption ne sont ouvertes à un téléphone (aucun écran mobile des réglages
  n'existe ; les ouvrir est une décision de portée à prendre avec `ROLES.md`).

## 7. Brancher un département de plus

1. Déclarer le réglage dans le `department.yaml` (bloc `reglages:`, clé `mN.nom`, chemin sous `configuration`, bornes de saisie,
   `debloque`, proposition seulement si une source écrite la fournit).
2. Au point où le département lit son bloc de configuration, appeler
   `reglages_lecture.superposer(donnees_du_manifeste, ("configuration", cle), valeur_du_fichier)`.
3. Tests : sans rien d'adopté le comportement ne change pas ; adopté, la fonction se débloque ; retour arrière, elle redevient
   inerte (modèle : `tests/test_reglages_bout_en_bout.py`). Aucun changement d'outil, de droit ni de niveau.

## 8. Limites (dites sans euphémisme)

- Prouvé sur **SQLite** ; le magasin et la lecture n'emploient que des primitives déjà qualifiées pour PostgreSQL
  (`registres_maillons`, point de sauvegarde, verrou de console), et un test de parité rejoue le magasin contre un PostgreSQL
  éphémère quand Docker est présent (voir `tests/test_reglages_postgresql.py`) ; rien en exploitation.
- Les valeurs **réelles** de Nathan n'existent pas ici : ce chantier livre l'endroit où les décider, pas les décisions.
- L'écran n'a été joué que par le client HTTP de test (HTML, formulaires, CSRF) ; aucun navigateur réel, aucun téléphone ;
  l'écran mobile des réglages n'existe pas.
- Une adoption est un geste **du propriétaire** ; un administrateur sans ce rôle voit l'écran mais n'agit pas.
- La validité d'un seuil pour l'entreprise (ni trop bas, ni trop haut) n'est pas jugée : seules les bornes de saisie le sont.
  Les valeurs fiscales, comptables ou légales restent à valider auprès d'un comptable (CPA) / professionnel qualifié.
