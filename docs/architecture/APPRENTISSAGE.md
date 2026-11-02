# Apprentissage : le terrain corrige le système (durées sur site et rapidité des équipes)

> **Besoin du propriétaire.** « OPSYS-AI doit apprendre et s'améliorer autant que possible. » Pour un type de chantier, le
> système apprend quelle équipe réalise le mieux le travail et adapte ses estimations au temps que les chantiers ont
> **véritablement** pris, l'app mobile faisant le lien avec le terrain. Exemple : estimé à 14 h, mais ~16 h sur site en réalité
> (le déplacement est calculé à part) ; le système doit l'apprendre et adapter les soumissions.
>
> **Ce que ce document fait.** Il dit ce qui existait, ce qui est maintenant branché de bout en bout, les décisions d'architecte
> qui l'encadrent, le **patron réutilisable** pour tout autre apprentissage, et, département par département, ce que le système
> pourrait apprendre ensuite, avec l'état honnête (rien d'autre n'est implémenté).
>
> **Ce que ce document ne dit pas.** Que cela tient sur de vrais chantiers : toutes les preuves ci-dessous sont faites avec des
> données FICTIVES (`fictif: true`) et les vrais outils M3/M4 sur SQLite. Voir « Ce qui n'est pas prouvé ».

## 1. Cartographie avant / après (base `e0424b040`)

| Maillon de la boucle | Avant | Après |
|---|---|---|
| Temps réel certifié (pointages de l'app mobile → WCT de M4, durée écoulée sur site moins pauses, **sans déplacement**) | branché (M4, bus `m4.travaux_termines`) | inchangé |
| Réception M3 (`wct_recu`), jointure devis accepté / estimation d'origine / trace de temps (`calibration_raccord`) | branché | inchangé, réutilisé tel quel |
| Observations normalisées, cohortes, rapport train/holdout (`calibration_cohortes`) | « évaluation pure, inactive » | inchangé (chemin exact et N4, voir ci-dessous) |
| Candidate de calibration versionnée, évaluation hors ligne, activation N4 par le propriétaire (`calibration_versions`) | branché mais **pratiquement inatteignable** : portée = quantité exacte et taux exact, 30 chantiers de train **et** 30 de holdout par portée, activation toujours N4 | inchangé ; reste le chemin « preuve statistique stricte » |
| Estimateur robuste par **type de travaux** (tous volumes), intervalle, poids d'âge, aberrantes, dérive | absent | `apprentissage_durees.py` (pur) |
| Gouvernance par règle déclarée (auto dans les bornes / personne au-delà / refus hors bornes), retour arrière, journal | seulement N4 pour tout | `apprentissage_journal.py` + `outils_apprentissage_durees.py` |
| Estimation M3 réellement adaptée, avec trace « version, n chantiers, intervalle » | seulement si une portée exacte N4 est active (aucune ne l'était) | `estimation.py` : `apprentissage_duree` + trace durable de schéma 3 |
| Apprentissage « quelle équipe pour quel type de travaux » | absent (`qualite` = part de chantiers sans écart) | indice de rapidité par couple (équipe, type), normalisé par la difficulté, critère facultatif de l'indice d'adéquation M4 |
| Complexité d'un chantier | absente | déclarée dans une échelle de l'entreprise (`m3_declarer_complexite_chantier`) |

Les deux chemins coexistent et ne s'empilent jamais : si une calibration exacte N4 est en vigueur pour la demande, c'est elle qui
s'applique et le bloc `apprentissage_duree` dit `non_appliquee / calibration_exacte_active`.

## 2. Décisions d'architecte

1. **Boucle fermée.** Temps certifié par le terrain → observations normalisées (type de service, quantité, unité, équipe
   pseudonymisée, complexité déclarée, saison de calendrier, durée **sur site**) → apprentissage par cohorte (type, unité) →
   candidate versionnée → application gouvernée → estimation adaptée avec sa trace. Le déplacement reste calculé à part
   (distances de M4) et n'est jamais mélangé au temps appris : une observation qui n'est pas exactement
   `duree_ecoulee_intervention`, qui n'est pas en minutes ou qui déclare du déplacement est exclue et comptée.
2. **Une calibration ne s'applique jamais sans règle.** Seuils et bornes sont des données déclarées
   (`department.yaml/configuration/apprentissage_durees`, **vides à livrer**) ; sans politique complète, rien n'est calculé ni
   appliqué et le refus dit quoi déclarer. Petits ajustements dans les bornes : appliqués **au brouillon d'estimation seulement**
   (l'envoi au client reste une décision N4 du propriétaire, inchangée) ; au-delà, ou en cas de dérive : une personne approuve
   (N3, file d'approbation) ; hors bornes absolues : refusé (même un humain ne l'approuve pas par ce chemin) ; retour arrière en
   une opération ; journal append-only.
3. **Équipes.** L'apprentissage porte sur le **couple (équipe, type de travaux)**, en agrégat, jamais par individu. Il alimente
   l'indice d'adéquation M4 comme critère de plus (`rapidite`, poids déclaré, absent par défaut), avec nombre de chantiers,
   intervalle et phrase lisible. Une équipe sans historique suffisant est « non évaluable » (nommée à part, jamais zéro). L'humain
   affecte toujours.
4. **Transversal.** Ce document est le registre du patron (§4) et de ce qui peut être appris ensuite (§9).
5. **Mobile.** Voir §10 : l'écran et le contrat existants suffisent ; aucune modification de code mobile.

## 3. Comment la durée apprise est calculée

* **Observation** : `taux observé = durée réelle sur site / quantité` (minutes par unité). Il ne dépend ni de l'estimation d'origine
  ni d'une calibration déjà appliquée : l'apprentissage ne peut pas se mordre la queue.
* **Cohorte** : (type de service, unité de quantité). Tous volumes confondus (le taux est par unité), contrairement à la
  calibration exacte.
* **Exclusions comptées** : non certifié (statut, liaison exacte au devis accepté, chaîne M3), sémantique non « sur site », unité
  non minute, mesure ou chronologie invalide, observation dans le futur de l'horloge injectée, complexité hors échelle, rejeu
  identique (compté une fois), conflit de rejeu (toutes les versions exclues), aberrante (écart à la médiane supérieur à
  `aberrantes_k` x échelle robuste `max(1,4826 x MAD, plancher relatif x médiane)`).
* **Estimateur** : médiane pondérée par l'âge (poids `2^(-âge / demi-vie)`), intervalle par bootstrap de la médiane ensemencé par
  le contenu (même entrée, même sortie), nombre minimal de **chantiers distincts**.
* **Dérive** : médiane des `derive_fenetre` derniers chantiers contre celle des précédents **et** contre le taux en vigueur ;
  jugée avant l'exclusion des aberrantes (un vrai changement de régime n'est pas une aberration). Si dérive, le taux est ré-estimé
  sur la seule fenêtre récente et `regime_depuis_utc` est retenu : l'ancien régime ne dilue plus le nouveau, et la dérive absorbée
  par une version en vigueur ne se répète pas.
* **Décision** : `insuffisante`, `stable` (le taux en vigueur est dans l'intervalle, ou écart sous `variation_minimale_pct`),
  `refusee_hors_bornes` (facteur hors [`facteur_min`, `facteur_max`]), `approbation_requise` (dérive ou variation > palier
  `variation_auto_max_pct`, relatif au taux en vigueur), `auto_applicable`.
* **Application** : seulement si le taux du barème de la demande est **exactement** celui contre lequel la version a été décidée
  (`bareme_modifie_depuis_la_version` sinon : la version est suspendue jusqu'au prochain calcul). L'estimation devient
  `quantité x taux appris`, la trace de temps passe au schéma 3 (`calibration_version_id`, `taux_minutes_par_unite_source`) et la
  charge du registre porte `apprentissage_duree` (version, n chantiers, intervalle, facteur, mode d'activation). Sans version, la
  charge et son hash sont ceux d'avant. Le prix, l'intervalle de coût et les scénarios ne changent pas : seule la durée change.
  **Où la trace est visible** : dans la réponse de `m3_estimer_projet` (le brouillon interne que l'estimateur et le propriétaire
  relisent) et, durable, dans la charge du registre des estimations ; le document de soumission destiné au client (HTML/PDF) ne
  porte aucune donnée interne d'apprentissage, par construction (liste blanche de `soumission.py`). La durée de
  main-d'œuvre n'alimente pas le prix dans le modèle actuel de M3 ; la relier au coût de main-d'œuvre exigerait un taux
  horaire déclaré, hors de ce lot.

## 4. Le patron réutilisable (observation → candidate → évaluation → promotion → canari → retour arrière)

1. **Observation** certifiée, normalisée, pseudonymisée, avec provenance et horodatage injecté. Les exclusions sont comptées par
   raison. Aucune horloge ni aléa non ensemencé dans le calcul.
2. **Candidate** versionnée et hachée (identité = contenu), inscrite à un journal append-only chaîné. Une candidate de même contenu
   ne s'écrit qu'une fois.
3. **Évaluation hors ligne** : estimateur robuste, intervalle, taille minimale, détection de dérive. Pour une promotion qui exige
   plus qu'une règle, le chemin strict train/holdout de `calibration_versions` reste disponible (N4).
4. **Promotion gouvernée** : une règle déclarée dit ce qui s'applique seul, ce qui attend une personne, ce qui est refusé ;
   fail-closed si la règle manque. Les seuils sont des données, jamais des constantes de formule.
5. **Canari / ombre** : le mode du département décide. En `ombre`, la candidate est calculée, journalisée et montrée mais rien
   n'est appliqué automatiquement (une version approuvée par une personne reste appliquée). Hors ombre, application automatique
   dans les bornes, sur le brouillon seulement.
6. **Retour arrière** : une opération (version attendue nommée, comme un compare-and-swap), la version précédente redevient la
   référence ; après un retrait humain la cohorte est **gelée** pour l'automatique jusqu'à la prochaine approbation humaine.

Réutiliser : `apprentissage_durees.py` (estimateur, bootstrap, dérive, décision) et `apprentissage_journal.py` (journal chaîné,
piles de versions, retrait, gel) sont écrits pour une grandeur « taux par unité » ; un autre apprentissage change l'observation et
la grandeur, pas la gouvernance.

## 5. Gouvernance et modes

| Mode du département | Calcul / journal | Mise en vigueur automatique | Version approuvée par une personne |
|---|---|---|---|
| `ombre` | oui (N2) | **non** (`auto_non_autorise_dans_ce_mode`) ; une version auto déjà en vigueur est gelée et seulement montrée | appliquée |
| `supervise` | oui | oui, `auto_applicable` seulement, brouillon seulement | appliquée |
| `autonome` | oui | idem (le mode `autonome` reste réservé au propriétaire) | appliquée |

Outils (aucun droit d'appareil) : `m3_lire_apprentissage_durees` (T0, lecture seule), `m3_calculer_apprentissage_durees` (N2),
`m3_approuver_calibration_duree` (N3, **décision humaine exigée** par `approbateur_en_cours` : un appel sans demande approuvée
est refusé), `m3_annuler_calibration_duree` (N3, humain), `m3_declarer_complexite_chantier` (N3), `m3_lire_performance_equipes`
(T0, réservé à M4 et M3) ; côté M4 : `m4_lire_equipes_faits_m3` (T0, réservé à M3). Une planification hebdomadaire
(`apprentissage-durees`) appelle le calcul. Aucun événement n'est publié : le journal est la trace.

Politique à déclarer (`configuration.apprentissage_durees`, version `m3-apprentissage-durees/1`) : `echantillon_minimum`,
`echantillon_minimum_equipe`, `demi_vie_jours`, `aberrantes_k`, `echelle_minimale_relative`, `niveau_confiance`, `replications`,
`variation_minimale_pct`, `variation_auto_max_pct`, `facteur_min`, `facteur_max`, `derive_fenetre`, `derive_seuil_pct`,
`complexites`. Les limites de forme refusent une faute de frappe (palier de 0 %), elles ne choisissent aucune valeur. Ces valeurs
sont une décision de Nathan ; les tests en utilisent de fictives.

## 6. Équipes : l'indice de rapidité

* **Qui est une équipe.** M4 (qui détient le profil) ne livre l'équipe d'un WCT que si l'assignation est une équipe **déclarée au
  profil avec au moins deux membres déclarés** ; un identifiant de personne, une équipe d'une seule personne ou une assignation
  inconnue donnent `equipe_ref: null` et un motif. L'équipe sort sous un pseudonyme stable (`eq-` + 16 hexadécimaux), jamais le nom
  ni un membre. Le journal ne contient donc aucun identifiant d'équipe ni de membre en clair (test).
* **Normalisation par la difficulté.** Strates = (type, complexité déclarée ou `inconnue`). La référence d'une strate est la
  médiane de l'entreprise ; une strate n'est **comparable** que si au moins deux équipes y ont travaillé et que
  `echantillon_minimum_equipe` chantiers y existent. Les observations d'une strate non comparable ne comptent pas
  (`observations_sans_comparaison`). Ainsi une équipe toujours affectée aux chantiers faciles, seule dans sa strate, n'est ni
  « meilleure » ni évaluée (test : une équipe plus rapide qui a fait des chantiers difficiles reste devant une équipe de vitesse
  moyenne qui n'en a fait aucun, alors que sa moyenne brute est plus lente).
* **Divergence assumée avec la formulation du besoin** (« 0,93 de l'estimé en médiane »). L'indice est relatif à la durée
  habituelle de l'entreprise pour ce type, à difficulté comparable, et non à l'estimation d'origine : celle-ci change quand une
  calibration est appliquée et ne porte pas la difficulté ; la médiane des pairs élimine les deux effets. La phrase affichée le dit
  (« 9 chantiers de ce type à 0,93 de la durée habituelle de l'entreprise (intervalle 0,88 à 0,99) »).
* **Dans l'indice d'adéquation M4.** Critère `rapidite` facultatif (poids déclaré > 0, sinon il n'existe pas et rien ne change),
  sous-indice `1 / (1 + indice)`. Les équipes sans historique suffisant (ou de moins de deux membres) sont nommées à part
  (`rapidite_non_evaluable`, « jamais notée zéro ») tant qu'il reste au moins deux équipes évaluables ; sinon le critère est écarté
  pour toutes. `rapidite_concluante` dit si les intervalles de la meilleure et des autres se séparent. Limite connue : une équipe
  neuve n'est pas classée sur ce critère ; l'humain peut l'affecter, c'est ainsi qu'elle se fait un historique.
* **Garde-fous** (SOUL.md M4, Loi 25, R-020) : agrégat d'équipe, pas de note de personne, pas de sanction, `decision: humain`.
  Le refus des attributs personnels protégés de l'indice s'applique aussi à la nouvelle entrée.

## 7. Loi 25

Données traitées : durées de chantier et affectations d'équipe, déjà détenues par M4/M3. Pseudonymisation de l'équipe avant
l'apprentissage ; chantiers inscrits au journal par empreinte ; approbateur = identifiant de compte (déjà le cas des journaux de
calibration). Aucune coordonnée GPS, aucun nom, aucun courriel dans le journal ni dans les sorties. Une équipe d'une personne ne
produit aucun agrégat. Ce document ne remplace pas l'EFVP : l'usage des durées d'équipe pour l'affectation reste à valider avec
un juriste avant des données réelles (À valider auprès d'un professionnel qualifié).

## 8. Stockage et PostgreSQL

Aucune table, aucune migration : le journal est `stockage.maillons("m03-estimation", "apprentissage_durees")` (registre portable,
précondition de rang pour les écritures concurrentes), sans SQL propre ni garde « SQLite seulement ». Non éprouvé sur PostgreSQL
(aucun test PostgreSQL de ce lot).

## 9. Ce que le système peut apprendre ensuite (aucun n'est implémenté par ce lot)

| Département | Grandeur apprenable | Source d'observation existante | État honnête |
|---|---|---|---|
| M1 | meilleur moment/canal de rappel, durée utile d'un appel, motifs de perte | `m1.*` (leads, rappels) | rien |
| M2 | calibrer le score de leads (rang → probabilité) sur les conversions réelles | `calibration_scoring.py` (jeu fictif seulement) | mécanique présente, jamais sur du réel consenti |
| M3 (autres) | marge réellement obtenue, taux d'acceptation par prix, perte de matériaux par poste, durée selon la saison/météo | devis acceptés, `estime_vs_reel`, variance M6 | durée sur site : fait (ce document) ; le reste rien ; la saison est décrite par cohorte mais n'est pas appliquée |
| M4 | durée de déplacement réelle contre ETA, durée d'un service dans le profil (`duree_min`) | pointages `en_route`, ETA | rien |
| M5 | délais de paiement par client/type (prévision de trésorerie), coût réel par poste | factures, paiements, `cout_reel.py` | rien |
| M6 | prix fournisseur, délais de livraison, pertes/bris par matériau | livre de prix, réceptions, variance | variance M6 existe (constat), aucun apprentissage |
| M7 | rendement des canaux (coût par lead qualifié, par vente) | UTM → lead → vente | rien |
| M8 | seuils de constats (valeurs normales), détection d'anomalies | mesures de l'entrepôt | rien |
| M9 | pertinence des signaux, fiabilité des sources | corpus et évaluation | rien |
| M10 | leçons retenues, ce qui est réutilisé ou contredit | connaissances sourcées | rien |

Pour chacun, le patron du §4 s'applique tel quel : observation certifiée et pseudonymisée, candidate versionnée, règle déclarée,
ombre d'abord, retour arrière. Aucun apprentissage ne devrait modifier un prix, un montant fiscal ou une obligation légale sans
passer par le moteur déterministe concerné et l'approbation de son niveau.

## 10. App mobile (M3 → terrain)

Rien de nouveau n'est requis du code mobile : les pointages (`arrivee`, `pause_debut`, `pause_fin`, `depart`) et la complétion
produisent déjà le WCT dont la durée est la durée sur site hors pauses ; le déplacement (`en_route`) est déjà distinct. L'écran
employé ne montre ni indice d'équipe ni apprentissage (les outils sont fermés aux appareils). Contrat souhaitable pour plus tard,
sans code ici : un champ « difficulté du chantier » (échelle déclarée de l'entreprise) rempli par le chef d'équipe à la
complétion, qui appellerait `m3_declarer_complexite_chantier` (aujourd'hui sans droit d'appareil, donc déclaré par la console ou
un agent après approbation). Jest ne tourne pas ici : rien du côté mobile n'a été rejoué.

## 10 bis. La durée apprise arrive à la cédule de M4 (P4-01)

M4 planifie avec la durée sur site de l'estimation M3 du devis accepté, correction apprise comprise (`m3.devis_accepte` :
`duree_estimee_minutes` et `duree_origine`), et ne recalcule rien. Voir [M3-M4](M3-M4-MATHIS-GABRIEL.md) et le README de M4.
Preuve : `tests/test_m4_duree_multijours_bout_en_bout.py` (M3 supervisé → devis → deux journées d'une équipe). Le déplacement reste
calculé par M4. En `ombre`, aucune version n'est appliquée automatiquement : la durée du barème est celle que M4 reçoit.

## 11. Preuves et limites

Preuves exécutées (données fictives, SQLite, vrais outils M3/M4) : `departments/m03-estimation/tests/test_apprentissage_bout_en_bout.py`
(chantiers de bout en bout : 14 h → ~16 h avec trace, type B stable, hors norme et non-vérifié exclus, déplacement variable sans
effet, ombre sans effet, dérive qui exige une personne, retour arrière, 14 h rétablies, journal sans donnée personnelle, indices
d'équipe), `test_apprentissage_durees.py`, `test_apprentissage_journal.py`, `test_apprentissage_estimation.py` (M3), et
`test_adequation_rapidite.py` et `test_outils_adequation_eta.py` (M4).

**Ce qui n'est pas prouvé.** Aucune donnée réelle n'existe : la tenue sur de vrais chantiers, la qualité des seuils (à décider par
Nathan) et l'absence de biais résiduel (les strates « inconnue » mélangent des difficultés) ne sont pas démontrées. La complexité
dépend d'une déclaration humaine. L'app mobile n'a pas été rejouée ; PostgreSQL n'a pas été éprouvé pour ce journal ; l'appel
`m4_proposer_adequation_equipes` avec la vraie lecture de M3 n'est prouvé qu'en deux moitiés (M4 avec un double de M3 dans la suite
M4, M3 réel dans le test de bout en bout qui appelle la lecture de M4 vers M3 puis l'ordre pur) car la capacité de la cédule n'est
pas reproduite dans la suite de M3. Les durées de plusieurs jours sont modélisées par un seul couple arrivée/départ (la
segmentation par visites de M4 n'est pas exercée). Le modèle est linéaire en quantité (taux par unité) : un chantier à fort coût
fixe de mise en place serait mal représenté.
