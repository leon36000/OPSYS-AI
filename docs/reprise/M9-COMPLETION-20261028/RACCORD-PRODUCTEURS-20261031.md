# Raccordement du conseil M9 aux quatre producteurs livrés (M1, M4, M7, M8) — 2026-10-31

Branche privée `claude/m9-raccord-producteurs` (aucun push, aucune fusion, aucune publication). Base : `claude/integration-lignes-trial`
(`83efcd82b` = #861 + #859 + les quatre producteurs) **plus** la tranche 1 M9 (`55d45f458`, corpus métier, chiffres libres, âge des
lectures), fusionnée sans conflit (`4caf6283c`, `git merge --no-ff`, aucun fichier en conflit, aucune résolution à justifier).

**M9 reste PARTIEL.** Ce travail ne ferme aucune ligne de la matrice. La qualification par modèle réel reste **OUVERTE**, l'exécution
Core native reste **OUVERTE**, la qualité métier du conseil reste **NON ÉTABLIE** (corpus fictif d'un seul auteur, sorties de modèle
figées).

## Commits (ordre d'exécution)

| SHA | Objet |
|---|---|
| `4caf6283c` | fusion de la tranche 1 M9 |
| `9411c7f5d` | M7 : `m7.depenses_marketing` (catalogue, liste blanche, validation, citations sûres, contradictions sans horloge) |
| `0b4dd6b98` | M4 : `m4.capacite_equipe` (heures déclarées, jamais converties ; priorisation refuse l'unité) |
| `550909159` | M8 : fenêtre `fraicheur_attendue_s` déclarée par le propriétaire, comparée par M9 |
| `c67e381d5` | M1 : `m1.plaintes_structurees` (NON_BRANCHEE sans compte, AUCUNE_DECLAREE jamais « 0 plainte », contradiction par empreinte) |
| `b1ebd85f5` | correctif : la page de faits de l'aperçu du dossier prend ce que le résumé laisse du budget de sortie |
| `b1b9f61bf` | corpus métier v2 (pages capturées des vrais producteurs), v1 gelé |
| (ce rapport) | rapport et preuves |

## Droits de lecture ajoutés à `opsys.lecteurs_m9.LECTURES_AUTORISEES` — DÉCISION DE NATHAN

Exactement **trois** ajouts, tous des lectures T0/N0 déjà existantes chez leur propriétaire. Aucun outil nouveau (366 outils avant et
après, `opsys-metier verifier` ; le compteur de `docs/architecture/ROLES.md` ne change pas). Aucun `roles_appareil` ajouté, aucun droit
machine ni compte élargi : le port reste réservé à la fabrique d'outils de M9 et à l'admin authentifié (console ou appareil) relu en
base à chaque lecture, attribué au département M9.

| Département | Outil ajouté | Appelant (rôle) | Niveau | Garde propre à l'outil (inchangée) |
|---|---|---|---|---|
| `m01-front-office` | `m1_lire_plaintes_structurees` | admin authentifié via M9 | T0 / N0 | admin confirmé ; `roles_appareil` vide |
| `m04-field-ops` | `m4_lire_capacite_equipe` | admin authentifié via M9 | T0 / N0 | admin ; `roles_appareil` vide |
| `m07-marketing` | `m7_lire_depenses_marketing` | admin authentifié via M9 | T0 / N0 | admin ou propriétaire de console confirmé ; `roles_appareil` vide |

Rien pour M8 : `m8_lire_vue_executive` et `m8_lire_mesures_chantier` y figuraient déjà. Constaté par essai sur le VRAI port : l'admin
`console` ET l'admin `appareil` lisent les trois outils par le port (le port n'applique pas le `roles_appareil` du producteur, qui ne
gouverne que l'accès direct d'un appareil) ; un agent, un vendeur, un employé, une personne désactivée et une source d'identité inconnue
sont refusés avant toute lecture et sans écriture. La liste blanche du socle et le catalogue de M9 sont égaux (test existant).

## Ce que fait le raccordement, producteur par producteur

Tous : entrée au catalogue (outil, arguments libres, référence, instants, révisions, incomplétude), charge validée par
`charges_producteurs` (module pur) AVANT d'être conservée, citations limitées à une liste de chemins sûrs (`Lecture.citables`), refus
conservé comme manque (`verdict REFUSEE`, `code charge_invalide`, sans recopier la valeur reçue). Une clé inconnue est refusée
(contrat versionné : une extension du producteur passe par une nouvelle version, sinon M9 s'arrête — fail-closed).

* **M7 dépenses** : devise `CAD` seule ; `statut` ∈ CONNUE|PARTIELLE|NON_BRANCHEE ; `total_cad` non nul si et seulement si CONNUE (et
  égal à la somme des canaux, chaque canal CONNUE porté par ≥ 1 relevé : jamais de zéro implicite) ; `au_moins_cad` réservé à PARTIELLE
  (borne basse, jamais un total) ; période rendue = période demandée. NON_BRANCHEE/PARTIELLE = incomplet. Jamais citable : libellé de
  campagne saisi, texte libre, `observation_source`. L'horloge de lecture de M7 (`lue_le`) est retirée de l'empreinte comparée : sinon
  toute relecture eût créé une fausse contradiction.
* **M4 capacité** : unité `heures_declarees` seule (toute autre : refus, aucune conversion), portée, fuseau, heures = minutes/60 exactes,
  totaux = somme des équipes, bornes d'une semaine ; non calculable = aucune valeur + cause nommée (incomplet). **`priorisation.allouer`
  refuse (`REJ-PRIORITE-UNITE`) une capacité citée de `m4.capacite_equipe`** : des heures d'équipe ne sont pas des jours-personnes.
* **M8 fraîcheur** : `fraicheur_declaree` ne retient qu'une fenêtre `type(x) is int`, 1 ≤ x ≤ 315 360 000 s, lue une fois, dont la version
  (`encodage.empreinte({lecture, fraicheur_attendue_s})`) se recalcule. Tout le reste est ignoré : `NON_EVALUEE`, jamais `HORS_FENETRE`
  (drapeau `fraicheur_declaration_ignoree`). Précédence : attente explicite de l'appelant, sinon fenêtre du producteur (`fraicheur_source`).
  Le conseil voit `fraicheur_attendue_s`/`fraicheur_source`. La valeur reste dans les pages hachées de la capture (aucun champ de capture
  ajouté : les registres durables existants restent valides).
* **M1 plaintes** : états/motifs fermés et cohérents ; NON_BRANCHEE = tous les comptes `null` ; AUCUNE_DECLAREE = aucun compte non nul ;
  comptes recomptés depuis les plaintes listées ; gravité toujours `null` ; période = période demandée. **Un compte nul n'est jamais un
  fait citable** (`zero_non_citable`) : « aucune déclarée par la source » ne se cite que par `etat`. Deux lectures aux mêmes arguments dont
  l'`empreinte_contenu` déclarée diffère = contradiction signalée, non fusionnée ; même empreinte, autre tête de registre = rafraîchissement.

`contrats_attendus` : les trois domaines sont `PUBLIE` et rejouent la validation réelle ; le code des formes simulées est retiré.
`test_contrats_attendus.py` est réécrit : les anciens tests décrivaient la forme SIMULÉE obsolète (ce ne sont pas des attentes du corpus).

## Corpus avant / après (effectifs, Wilson 95 %, cas rouges)

Preuves : `preuves-evaluation-metier/EVAL-METIER-v1-{avant,apres}-raccord-20261031T141500Z.json`, `EVAL-METIER-v2-apres-raccord-…`,
`EVAL-METIER-v2-sur-ancien-code-4caf6283c-…`. Jamais écrasées ; aucun appel de modèle ; latence du harnais ≈ 0,02–0,03 s.

| Corpus | Code | Conformes | Wilson 95 % | Rouges |
|---|---|---|---|---|
| v1 gelé (60 cas, sceau `6faf3c0aefd1`) | `4caf6283c` (avant) | 58/60 | [0,886 ; 0,991] | `mkt-A07` `rep-V02` |
| v1 gelé | HEAD (après) | **58/60** | [0,886 ; 0,991] | `mkt-A07` `rep-V02` (identiques) |
| v2 (77 cas) | HEAD (après) | **75/77** | [0,910 ; 0,993] | `mkt-A07` `rep-V02` ; **aucun nouveau rouge** |
| v2 | `4caf6283c` (avant) | 55/77 | [0,605 ; 0,803] | non exécutable tel quel : lecture absente du catalogue (22 cas non conformes comptés cas par cas) |

Par partition (v2, après) : ajustement 51/52 [0,899 ; 0,997] ; vérification 24/25 [0,805 ; 0,993]. Par famille (conformes/effectif,
ajustement ; vérification) : direction 7/7 ; 3/3 — marketing 9/10 ; 5/5 — trésorerie 7/7 ; 3/3 — leads 10/10 ; 5/5 — ville 9/9 ; 5/5 —
réputation 9/9 ; 3/4. Effectifs par famille très petits : aucune comparaison entre familles.

**Doubles de protocole contre vrais contrats.** Dans v2, les 60 cas de v1 sont conservés ; trois fixtures simulées sont remplacées par
des pages capturées sur le vrai producteur, **attentes inchangées (vérifié par test)** : `mkt-A01`, `mkt-A03` (dépenses lues sur
`m7.depenses_marketing`), `lea-A02` (capacité lue sur `m4.capacite_equipe`). 17 cas nouveaux (10 ajustement, 7 vérification) sont
bâtis sur des pages **capturées sur les vrais producteurs** M1, M4, M7, M8 (données fictives, produits par leurs fonctions publiques et
leur registre durable, non écrits à la main) ; leurs attentes ont été écrites **avant la première exécution** depuis les contrats et
comptées à la main (16 faits pour M7 NON_BRANCHEE, 6 pour M1 AUCUNE_DECLAREE) et n'ont pas été modifiées. Restent **simulés** :
`m7.performance_campagnes`, `m1.digest`, `m4.cedule_semaine.capacite_jours_personnes` (**aucun producteur**), `m8…cout_ouverture_ville`,
M5 et M2. Les sorties de « modèle » restent des textes rédigés à la main : le 75/77 ne dit rien d'un modèle réel.

Un défaut de fixture a été trouvé par un test de conformité des pages (`lea-V04` : arguments de capture d'une autre semaine que la page) ;
corrigé dans la fixture avant le gel, attentes inchangées.

## Cas rouges et limites (non corrigés)

* `mkt-A07` : le type d'action est déclaré par le modèle (limite connue de la tranche 1, M9.17).
* `rep-V02` : « il y a 0 plainte » écrit en hypothèse (entier nu) reste admis. Le raccordement empêche de CITER un zéro (aucun fait
  n'existe) mais pas de l'ÉCRIRE en texte libre : il faudrait un schéma d'affirmation numérique. Même limite pour toute quantité nue.
* La capacité de M4 (heures déclarées, borne basse sur les journées datées) **ne peut pas alimenter l'allocation en jours-personnes** :
  `m9_prioriser_options` refuse désormais ce croisement. Le champ `capacite_jours_personnes` des cas `lea-*` reste simulé, sans producteur.
* M7 : branché mais **sans ingestion ni saisie réelle** de relevés : en production la lecture dit `NON_BRANCHEE`.
* M4 : non calculable sans profil des équipes, sans cédule appliquée ou pour une semaine sans journée datée.
* M8 : la configuration `fraicheur_lectures_s` est vide par défaut : tant que le propriétaire ne déclare rien, `NON_EVALUEE`.
* M1 : « branché » veut dire « des signaux sont au registre », pas « les canaux sont sains » ; aucune plainte hors des canaux de M1.
* Non exercés : modèle réel, Core natif, navigateur, suite complète du socle, isolation PDF native. Corpus fictif d'un seul auteur.

## À décider par Nathan

1. **Accepter ou refuser les trois droits de lecture** ci-dessus (rien n'est fusionné ni publié tant que ce n'est pas décidé).
2. Déclarer (ou non) des fenêtres `fraicheur_lectures_s` pour `m8_lire_vue_executive` et `m8_lire_mesures_chantier` (aucune valeur n'est
   livrée ni dérivée).
3. Précédence de la fraîcheur : j'ai retenu « l'attente explicite de l'appelant l'emporte sur la fenêtre du producteur, la source est
   dite » ; la règle inverse (le producteur l'emporte, ou la plus stricte) est une décision de politique.
4. Unité de la capacité pour l'allocation : jours-personnes (aucun producteur) ou heures d'équipe (M4) ? Aujourd'hui l'allocation sur une
   capacité M4 est refusée, jamais convertie.
5. Politique « clé inconnue refusée » : une extension compatible d'un contrat producteur arrête la lecture de M9 jusqu'à sa mise à jour.
6. Qui saisit les relevés de dépenses de M7 (connecteur Google/Meta ou saisie du propriétaire) — décision produit hors de ce travail.

## Défauts et incidents relevés en chemin

* Ajouter trois lectures au catalogue faisait dépasser la borne de sortie de l'aperçu du dossier (5902 à 5969 caractères pour 5900) et
  cassait 8 tests d'intégration existants : corrigé (`b1ebd85f5`), la page de faits prend ce que le résumé laisse.
* `CATALOGUE_VERSION` passe à `2026-10-31.1` : les nouvelles captures portent cette version (donc d'autres empreintes de maillon) ; les
  captures déjà conservées restent valides (la version n'est pas revérifiée).
* **12 tests échouent sur la ligne d'intégration elle-même (`83efcd82b`), avant tout changement de cette branche** (M5 rend la rentabilité
  `PARTIELLE`, donc la marge réelle `None`) : `test_m9_e2e_cahier` (2), `test_m9_experiences_integre` (1),
  `test_m9_indicateurs_cadrage_integre` (1), `test_m9_producteurs_b` (5), `test_m9_semantique_integre` (3). Même liste exacte avant et
  après (comparée). Non causé ici, non corrigé ici ; à traiter par le propriétaire de la ligne.

## Commandes exécutées (HOME et TMPDIR privés ; `--import-mode=importlib -p no:cacheprovider` ; python du worktree `wt-main`, `pythonpath` du pyproject du worktree vérifié)

* `pytest departments/m09-strategic-intelligence/tests tests/test_portees_appareil.py tests/test_lecteurs_m9.py tests/test_m9_*.py
  tests/test_console_direction_m9.py tests/m9_producteurs_b.py` : **1961 réussis, 12 échecs (les 12 de la base, liste identique), 2 ignorés**
  (`preuves-execution/log-raccord-m9-20261031T142700Z.txt`).
* `ruff check src tests departments` : `All checks passed!`.
* `python -m opsys.cli verifier` (HOME vierge) : `OK : 10 départements, 366 outils … 231 outils déclarés …`, identique à la base
  (`preuves-execution/verifier-raccord-20261031T142700Z.txt`).
* `pytest departments/m01-front-office departments/m04-field-ops departments/m07-marketing departments/m08-analytics` : **7142 réussis, 0 échec, 20 ignorés**
  (`preuves-execution/log-raccord-departements-m1-m4-m7-m8-20261031T142700Z.txt`) ; aucun fichier de ces départements n'est modifié par cette branche.
