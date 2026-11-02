# M3 — Barème déclaré et mesure déclarée (M3-C1, M3-C2)

Chantier issu de l'analyse d'écart `ANALYSE-M3.md` (« défaut grave »). Statut : **PARTIEL, prouvé en S** (processus Python,
vrais outils, SQLite, horloge injectée) ; jamais exercé contre PostgreSQL, une console réelle, un appareil réel ni les
valeurs réelles de Nathan.

## 1. Le défaut qu'on ferme

Avant ce chantier, `m3_estimer_projet` recevait en **arguments d'appel** le barème (coûts unitaires, durée par unité), la
quantité, le plancher rentable, la graine et les taux de marge. Rien ne les reliait à une source : la règle d'`AGENTS.md`
(« aucun prix, quantité ou score produit par un modèle ») ne tenait que pour l'arithmétique, pas pour ses **entrées**. Un
agent pouvait passer n'importe quel barème, et le garde photos/échelle jugeait des métadonnées de photos, pas la mesure.

Maintenant :

| Entrée | Avant | Maintenant |
|---|---|---|
| Barème (coûts, durée, matériaux, pertes) | argument libre | **version déclarée** d'un registre, référencée par `bareme_ref {bareme_id, version}` |
| Plancher rentable, taux de marge (3 scénarios), seuils de revue | argument libre ou `department.yaml` | **paramètres de la version de barème** |
| Quantité | argument libre | **mesure déclarée** par une personne, référencée par `mesure_ref {mesure_id}` |
| Graine Monte Carlo | argument | **dérivée** des entrées déclarées (choisir sa graine serait choisir son intervalle) |
| Heure (en vigueur, péremption) | — | horloge du **serveur** (`opsys.horloge`), jamais un argument |

Aucune valeur de barème n'est livrée avec le code ni avec le pack : le propriétaire les déclare (ou adopte des valeurs de
départ tirées d'une source écrite, marquées « à valider »).

## 2. Le registre de barème (`bareme_registre.py`)

Un barème est un **ensemble de lignes** + des **paramètres** + des **textes de soumission**, versionné et chaîné.

- **Ligne d'ouvrage** : `service`, `element`, `unite`, `cout_unitaire_min / mode (facultatif) / max`,
  `duree_minutes_par_unite` (facultatif), `semantique_temps` (facultatif ; seule valeur admise `duree_ecoulee_intervention` :
  minutes écoulées sur site, pauses et déplacements exclus, ce qui qualifie la trace de temps de l'apprentissage ; absente, la
  durée reste « non qualifiée », jamais devinée), `source_ecrite` (obligatoire : nom du document, date, auteur). Une seule par service.
- **Ligne de matériau** : `service`, `element`, `unite`, `quantite_par_unite`, `taux_perte` (facultatif ; absent : le besoin
  est publié sans perte et le dit), `sku`, `source_ecrite`.
- **Montants** : textes décimaux (6 décimales au plus), jamais des nombres JSON (un flottant arrondirait en silence).
- **Paramètres** (tous facultatifs, aucun défaut) : `plancher_rentable_cad`, `taux_marge {prudent, normal, agressif}`
  (`normal` donne `prix_recommande`), `seuils_revue` (les cinq seuils de `revue_devis`, dont `minimum_rentable_cad`),
  `mesure {largeur_relative_revue, largeur_relative_max_prix, validite_jours}`.
- **Textes de soumission** : `soumission {exclusions, hypotheses, validite_jours}`.
- **Version** : `date_effet` (ISO 8601 avec fuseau), `valide_jusqu_au` (facultatif), `a_valider`, auteur
  (`nathan_owner` ou `admin`, **une personne**), horodatage du serveur, `empreinte` (SHA-256 du maillon).

**Append-only et chaîné** (`registre`/`stockage.maillons("m03-estimation", "bareme")`, aucune migration) : une révision ajoute
la version n+1 ; la version n reste lisible à l'identique. Chaque maillon porte l'empreinte du précédent ; chaque lecture
rejoue tous les invariants (séquence des versions, dates d'effet croissantes, auteur humain, valeurs valides). Altération d'un
maillon, permutation, retrait, ou réécriture cohérente d'un seul maillon : `REJ-BAREME-ALTERE`, et plus rien n'est utilisable.
Limite assumée (celle de `registre.py`) : une chaîne **entièrement** réécrite par quelqu'un qui recalcule toutes les empreintes
n'est pas détectée sans ancre externe.

**En vigueur à l'instant t** : validée (`a_valider` → `m3_valider_bareme`), `date_effet <= t`, aucune version plus récente
déjà en effet, `valide_jusqu_au` non atteint. Les comparaisons de bornes sont exactes (l'instant de la date d'effet est en
vigueur ; l'instant de fin ne l'est plus).

**Résolution** (`resoudre`) : `bareme_ref` doit exister, correspondre à `empreinte` si elle est donnée, être validé, et être
en vigueur. Refus lisibles qui disent quoi faire : `REJ-BAREME-INTROUVABLE`, `-VERSION-INCONNUE`, `-EMPREINTE-DIFFERENTE`,
`-A-VALIDER`, `-HORS-VIGUEUR` (pas encore / plus de version en vigueur), `-PERIME` (« la version 2 est en vigueur depuis le … :
référencer la version 2 »).

**Écriture : une seule fonction** par geste, `bareme_registre.declarer_version(journal, …, auteur, horodatage)` et
`valider_version`. C'est le **point d'accroche des réglages de direction (CFG-1)** : l'écran de saisie appellera cette fonction
(ou `m3_declarer_bareme`) avec l'identité de la personne ; rien d'autre n'écrit un maillon de barème. `version_attendue`
(optimiste) refuse une révision faite sur une version périmée (`REJ-BAREME-REVISION-PERIMEE`) et rend la version déjà écrite
si le même appel est rejoué.

## 3. La mesure déclarée (`mesure_declaree.py`)

Enregistrement chaîné (`registre "mesures_declarees"`) : `valeur`, `unite`, `borne_basse`, `borne_haute`, `methode` (relevé
sur place, plan, photo à l'échelle mesurée à la main, estimation grossière), `confiance` (faible, moyenne, élevée), `mesure_le`,
`pieces` (références de photos ou de plans, jamais une URL), `lead_id`, `service`, auteur (propriétaire, admin, ou **vendeur
propriétaire du lead**), révisions sans écrasement. Aucune vision requise : une photo n'entre que comme pièce d'une mesure faite
à la main ; un candidat de vision n'est jamais une mesure (`vision_gouvernance.py`, inchangé).

`evaluer` juge la suffisance avec les seuils **déclarés dans le barème** (largeur relative = (haute − basse) / valeur, comparée
sans arrondi) :

| Cas | Résultat |
|---|---|
| unité ≠ unité de l'ouvrage du barème | `REJ-MESURE-UNITE` (aucune conversion devinée) |
| plus ancienne que `validite_jours` | `REJ-MESURE-PERIMEE` |
| largeur > seuil « aucun prix » | `REJ-MESURE-INSUFFISANTE` — dit quoi mesurer de plus |
| bornes larges et seuil « aucun prix » non déclaré | `REJ-BAREME-INCOMPLET` — le seuil n'est pas deviné |
| largeur > seuil de revue (ou seuil absent), ou confiance faible | **plage + revue humaine requise** (`statut_prix: a_revoir`) |
| sinon | `retenu` |

Les comparaisons de seuil sont strictes (un devis exactement au seuil ne déclenche rien, comme `plancher.py`).

## 4. L'estimation (`entrees_declarees.py`, `estimation.py`, `outils.py`)

`m3_estimer_projet(contrat, marqueur, photos, seuils, bareme_ref, mesure_ref, …)` :

1. Valide contrat et marqueur (inchangé), puis résout les références **avant tout autre calcul** (barème, plancher déclaré,
   service couvert, mesure de CE lead et de ce service, bonne unité, assez précise). Un refus écrit **rien** au registre.
2. Garde photos/échelle (inchangée) : photos insuffisantes → `prix_bloque`, `statut_prix: bloque`, relance M2, même avec un
   barème et une mesure déclarés.
3. Monte Carlo sur le barème compilé (`bareme_registre.compiler` : `version = "<bareme_id>@v<n>"`). L'`intervalle_confiance`
   (clé gelée d'`EstimationV1`, mêmes douze clés) est l'**enveloppe de la mesure** : borne basse à la quantité basse, borne haute
   à la quantité haute, mêmes graine et niveau. Mesure ponctuelle : l'enveloppe est exactement l'intervalle d'avant (prouvé
   contre l'ancien appel libre). Prix recommandé, P50/P80 et scénarios restent calculés à la **valeur retenue** (limite 7).
4. Clé sœur `declaration` (`m3.declaration/v1`) : référence exacte du barème (`id`, `version`, `empreinte`) et de la mesure
   (`id`, `revision`, `empreinte`), quantités, plancher, niveau statistique, `statut_prix` (`bloque`, `a_revoir`, `retenu`),
   `revue_humaine_requise`, `motifs_revue`, intervalle. Le même bloc est rangé dans la charge du registre des estimations
   (donc dans son `hash_maillon`) ; `faits_revue` passe en `m3.faits-revue/v2` avec `mesure_a_bornes_larges`.
5. **Reçu rejouable** : `m3_rejouer_estimation(estimation_id)` refait le calcul avec la **version de barème et la révision de
   mesure citées** — même si une version 2 ou une révision de mesure les a remplacées — et confronte l'intervalle gardé. Un
   écart est dit, jamais corrigé en silence. Rien à rejouer pour un prix bloqué ou une estimation d'essai.

**Revue d'envoi** : `revue_devis.MESURE_INCERTAINE` se déclenche aussi quand l'estimation source a `mesure_a_bornes_larges`
(fait canonique de la charge, source `estimation_canonique`). Aucun onzième ou douzième motif : le critère existant est étendu.
Un devis chiffré avec un barème déclaré est jugé avec les **seuils de revue de ce barème** (`parametres.seuils_revue`, la version
exacte citée), clé par clé : une clé non déclarée garde celle de `department.yaml`, sinon le critère reste « seuil à configurer ».

## 5. La voie de compatibilité (et pourquoi un agent ne peut pas la prendre)

Les tests et les appels historiques passent encore `bareme`, `quantite` et `plancher_rentable`. Cette **voie d'essai**
(`outils_bareme.voie_libre_autorisee`) n'est ouverte que si **les deux** conditions tiennent :

1. la variable d'environnement du **serveur** `OPSYS_M3_VOIE_LIBRE` vaut exactement `essai` (le `conftest.py` racine la pose
   pour les tests ; ni l'installateur ni le conteneur ne la posent) ;
2. l'appel **ne vient pas du transport MCP** (`contexte.appel_provient_du_mcp()`, posé par le serveur MCP, pas par les arguments).

Un agent ne peut ni poser une variable du serveur ni cesser de venir du MCP. Hors de cette voie :
`REJ-BAREME-LIBRE-REFUSE` (valeur libre fournie) ou `REJ-BAREME-REFERENCE-REQUISE` (aucune référence), avec le message de ce
qu'il faut déclarer. Mêlée à une référence, une valeur libre est refusée aussi (elle ne vient jamais « corriger » le barème
déclaré). La graine libre est refusée avec une référence. Même fermeture pour `m3_simuler_intervalle` et
`m3_confronter_plancher` (le plancher libre). L'orchestrateur pur ignore de toute façon les arguments libres quand une
déclaration est fournie (défense en profondeur).

## 6. Outils (7 nouveaux, registre MCP rescellé)

| Outil | Niveau | Qui |
|---|---|---|
| `m3_declarer_bareme`, `m3_valider_bareme` | T1 | **personne** `nathan_owner`/`admin`, identité revérifiée en base ; appareil `admin` ; un agent est refusé (`REJ-BAREME-IDENTITE`) |
| `m3_lire_bareme`, `m3_lister_baremes` | T0 | agents ; appareil `admin` |
| `m3_declarer_mesure` | T1 | **personne** `nathan_owner`/`admin`/`seller` (propriétaire du lead) ; appareils `seller`, `admin` ; un agent est refusé (`REJ-MESURE-IDENTITE`) |
| `m3_lire_mesure` | T0 | agents ; appareils `seller`, `admin` |
| `m3_rejouer_estimation` | T0 | agents ; fermé aux appareils |

Journal d'audit (`m3.bareme_declare`, `m3.bareme_valide`, `m3.mesure_declaree`) : identifiants et numéros de version seulement,
ni montant, ni nom, ni contact (testé).

## 7. Soumission (`conditions_soumission.py`)

Pour un devis dont l'estimation source est déclarée, `m3_generer_soumission_brouillon` (HTML et PDF) ajoute quatre sections
tirées de données déclarées :

- **Exclusions** et **hypothèses** : les textes que le propriétaire a écrits dans la version de barème citée, repris tels quels,
  plus des phrases à gabarit fixe qui ne disent que ce que la mesure déclare (quantité retenue, méthode, date, plage) ;
- **Délai** : la durée de main-d'œuvre estimée en heures (arrondie au dixième, moitié vers le haut), avec « aucune date de début
  ni de fin n'est promise » — **jamais une date** (la planification est celle de M4) ;
- **Validité** : `validite_jours` déclaré, ajouté à la date **du devis** (jamais à l'horloge) ;
- **Aucune garantie** : le code n'en écrit aucune ; une garantie n'existe que si l'entreprise l'a écrite dans ses textes déclarés.

Liste blanche inchangée : ni coût, ni marge, ni taux, ni nom d'auteur dans le document. Les gabarits de phrases sont du texte à
faire valider par l'entreprise ; toute portée juridique : **À valider auprès d'un professionnel qualifié**.

## 8. Points d'accroche (non construits ici)

- **Réglages de direction (CFG-1, `claude/cfg-reglages-direction`)** : appeler `bareme_registre.declarer_version` /
  `valider_version` et `mesure_declaree.declarer` (ou les outils) avec l'identité de la personne ; l'écran n'a qu'à produire
  `lignes`, `parametres`, `soumission`. `department.yaml/configuration` (seuils de revue, taux de scénarios) reste lu par la voie d'essai et,
  pour les clés que le barème ne déclare pas, par la revue d'envoi d'un devis : CFG-1 devra les unifier avec les paramètres du barème.
- **Apprentissage des durées (`claude/apprentissage-durees`)** : une calibration appliquée devra se référer à une **version de
  barème**. Le barème compilé porte `version = "<id>@v<n>"` ; l'empreinte du barème compilé (`trace_calibration_temps.empreinte_bareme`)
  et `bareme_version` des contrats la suivent ; le bloc `declaration` de la charge cite la référence exacte. Aujourd'hui,
  `_calibration_active_pour_demande` ne lit pas la déclaration et **aucune calibration n'est appliquée** à une estimation
  déclarée (`outils.estimer_projet`, commentaire à l'endroit du branchement) ; la trace de temps garde `provenance:
  "bareme_fourni"` pour ces estimations (à renommer par ce chantier, non touchée ici pour ne pas entrer en conflit).

## 9. Preuves

Tests du département M3 (base SQLite migrée, horloge injectée, données fictives) :

- `test_bareme_registre.py`, `test_mesure_declaree.py` : registres purs (déclaration, révision, en vigueur à l'instant exact,
  chaînage, altération, refus lisibles, seuils stricts) ;
- `test_estimation_declaree.py` : l'orchestrateur par références (identique à l'ancien appel libre pour une mesure ponctuelle,
  enveloppe, revue, plancher, rejeu après révision, aucune donnée personnelle dans la charge) ;
- `test_outils_bareme.py` : les vrais outils (`executer_atomique`) : identités, heure du serveur, voie libre fermée aux appels
  MCP, références refusées, audit sans donnée personnelle ; `test_bareme_capacites.py` : le répartiteur réel (`Capacites`, M3 en
  mode `ombre`) : portée d'appareil, enveloppe d'idempotence, file d'approbation d'un agent ;
- `test_conditions_soumission.py` (HTML et PDF) et `test_bareme_bout_en_bout.py` (parcours complet : v1, estimation, reçu, v2,
  rejeu, refus, mesure large, revue, mesure précise, soumission).

Hors département : `tests/e2e/test_verticale_affaire_durable.py` déclare désormais barème et mesure depuis des appareils réels
(HTTP, SQLite **et PostgreSQL via docker**) avant l'estimation de l'agent. Mutations : `tests/outils_preuve/batterie_bareme_registre.py`
(46 mutations de métier sur huit fichiers, copie jetable, suite ciblée ; une redondance structurelle déclarée avec sa raison).

## 10. Limites

1. **Aucune valeur réelle** : le barème, le plancher, les taux et les seuils de Nathan ne sont pas dans le dépôt ; tout est testé
   avec des valeurs fictives. Sans barème déclaré, M3 ne chiffre rien (voulu).
2. **Pas de saisie en console** : il n'existe pas encore d'écran pour déclarer un barème ou une mesure ; les outils sont
   appelables par un appareil `admin` (barème) ou `seller`/`admin` (mesure) ou, plus tard, par CFG-1. Sans écran ni appareil
   apparié, personne ne peut aujourd'hui déclarer en production.
   Un agent ne peut pas non plus **proposer** un barème à faire adopter (pas de brouillon d'agent en file d'approbation) : l'ingestion
   d'onboarding pourrait en produire à partir des soumissions passées, c'est un chantier suivant ; en attendant une valeur de départ
   tirée d'une source écrite est saisie par une personne avec `a_valider=true`, puis validée.
3. **PostgreSQL non éprouvé** : écritures sérialisées par `verrou_ecriture_console` et rejeu sur écriture concurrente, comme
   les autres ports humains ; aucun test sur PostgreSQL pour ces registres.
4. **L'authenticité de l'auteur repose sur OPSYS-CORE** (jeton d'appareil) ou la session de console ; M3 la revérifie en base
   mais ne peut pas l'établir seul. La chaîne n'est pas ancrée à l'extérieur.
5. **`m3_creer_devis` reste libre** : lignes, coûts unitaires et `taux_marge` d'un devis viennent encore de l'appelant. La garde
   est la revue N4 de l'envoi (qui nomme maintenant la mesure à bornes larges) ; lier les lignes du devis à l'estimation et au
   barème est un chantier suivant.
6. **Le contrôle d'un barème libre en exploitation** suppose que `OPSYS_M3_VOIE_LIBRE` n'est jamais posée sur un serveur de
   production ; rien ne le vérifie au démarrage.
7. **Incertitude de la mesure** : elle élargit l'intervalle et le prix recommandé, mais P50/P80, scénarios et besoins en matériaux
   (publiés à M6) sont calculés à la valeur retenue ; la quantité n'est pas tirée dans le Monte Carlo (M3-C8).
8. **Vision, géospatial, estimateurs par service, distance** : inchangés (hors périmètre ; aucun GPU).
9. **Taxes** : toujours « en sus » ; M3 n'en calcule aucune (M5). **À valider auprès d'un comptable (CPA)** pour toute valeur fiscale.
