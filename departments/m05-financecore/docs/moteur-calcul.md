# Moteur de calcul M5 — tranche 1

> Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision officielle ou action réelle.
> À valider auprès d'un comptable (CPA) / professionnel qualifié.

Sophie (M5) ne calcule jamais « de tête » (`SOUL.md`). Pour une VAN, un TRI, un versement de prêt, un point mort, une
tornade ou une simulation de trésorerie, elle appelle un **moteur déterministe** qui rend un **reçu de calcul**. Le reçu
se rejoue à l'identique.

Ce que la tranche 1 couvre, en bref :

- calculs en `Decimal` pur : aucun flottant et aucune dépendance (ni numpy, ni scipy) ;
- précision et arrondis déclarés ;
- refus typés pour toute entrée invalide ;
- outils T0 en lecture et en calcul seulement, sans aucun rôle d'appareil ;
- aucune écriture et aucun mouvement d'argent (garde anti-décaissement) ;
- aucun conseil en placement (garde NC 31-103).

## Modules

| Module | Rôle |
|---|---|
| `maths_financieres.py` | Mathématiques financières pures en `Decimal` : VA, VF, VAN, TRI, TRI modifié, délais de récupération, taux périodique, amortissement, crédit-bail ou achat, point mort |
| `monte_carlo_tresorerie.py` | Monte-Carlo à graine sur les flux de la prévision M5.7 existante (`prevision.py`), sans en dupliquer la logique |
| `sensibilite.py` | Modèle de projet, tornade et scénarios |
| `moteur_calcul.py` | Façade : valide et normalise les entrées, refuse avec un code typé, calcule, construit le reçu, rejoue (`rejouer`) |
| `recu_calcul.py` | Format du reçu (`recu-calcul.v1`), empreintes SHA-256, vérification, forme compacte |
| `verdicts_calcul.py` | Catalogue fermé des codes de refus `REJ-CALC-*`. Il est à part de `validation.py`, dont le code est épinglé par la paie |
| `outils.py` (`_outils_calcul`) | Les sept outils agent (T0) |

## Le reçu de calcul

Chaque calcul rend un reçu de format `recu-calcul.v1`. Le reçu ne contient que des types JSON : textes décimaux, entiers,
booléens. Il ne contient jamais de flottant.

| Champ | Contenu |
|---|---|
| `moteur`, `version_moteur` | Le moteur (`rentabilite_investissement`, `amortissement_pret`, `credit_bail_contre_achat`, `point_mort`, `sensibilite_projet`, `monte_carlo_tresorerie`) et sa version (`1.0.0`) |
| `methode` | La formule ou l'algorithme, en une phrase |
| `precision` | 50 chiffres significatifs, arrondi interne ROUND_HALF_EVEN, arrondi monétaire ROUND_HALF_UP au cent là où la méthode le dit |
| `parametres` | Les constantes et les réglages du calcul : bornes et tolérances du TRI ; graine, tirages et distributions du Monte-Carlo |
| `entrees`, `empreinte_entrees` | Les entrées normalisées (« 100 », « 100.0 » et « 100.00 » donnent la même entrée) et leur SHA-256 |
| `resultat` | Le résultat, en textes décimaux |
| `avertissements` | Ce que le calcul ne sait pas ou ne garantit pas : fiscalité, NC 31-103, corrélations, TRI non unique… |
| `mention` | « À valider auprès d'un comptable (CPA) / professionnel qualifié. » |
| `empreinte` | SHA-256 de la forme canonique (`encodage.py`) de tous les champs, sauf `entrees` (couvertes par `empreinte_entrees`) |

Deux opérations s'appliquent au reçu :

- **Vérifier** (`recu_calcul.verifier`, outil `m5_verifier_recu_calcul`) : recalculer les deux empreintes. Un chiffre
  retouché est refusé.
- **Rejouer** (`moteur_calcul.rejouer`) : rappeler le même moteur avec les `entrees` et les paramètres d'appel du reçu,
  puis comparer les empreintes. Le test fait faire au reçu un aller-retour par JSON avant le rejeu.

Quand le reçu dépasse le budget d'une réponse d'outil (6 000 caractères), l'outil le rend **compact**, sans ses
`entrees`, avec la mention `entrees_omises`. Son `empreinte` ne change pas et reste vérifiable.

Pour rejouer un Monte-Carlo, on relance la simulation avec la même graine sur le même instantané : même `prevision_id`,
même empreinte.

## Formules et conventions

Conventions générales :

- un taux est une fraction **par période** (« 0.05 » = 5 %) ;
- les flux tombent en fin de période ; `flux[0]` est au temps 0 et n'est pas actualisé.

### VAN, VA, VF

- VAN = Σ c_t / (1 + r)^t, par la méthode de Horner en v = 1/(1 + r). Elle est rendue au cent.
- VA = M / (1 + r)^n.
- VF = M · (1 + r)^n.

### TRI

Le TRI est la racine de VAN(r) = 0 sur [−0,9999 ; 100] par période. La méthode est un Newton protégé (rtsafe) :

- un pas de Newton n'est accepté que s'il reste dans l'intervalle encadrant et qu'il réduit assez l'erreur ;
- sinon, l'itération fait une bissection.

Paramètres de la recherche :

- arrêt quand l'intervalle est plus étroit que 1e-32, ou après 400 itérations ;
- TRI rendu à 1e-30 près (ROUND_HALF_EVEN) ;
- l'identité |VAN(TRI)| ≤ 1e-20 × max(1, Σ|c_t|) est contrôlée à chaque calcul ;
- le pourcentage est affiché à 4 décimales.

Le statut du TRI suit le nombre de changements de signe des flux. La règle de Descartes en x = 1/(1 + r) donne une
racine unique, r > −1, quand les flux changent **une seule fois** de signe.

| Statut | Signification | TRI rendu |
|---|---|---|
| `UNIQUE` | Un seul changement de signe, racine dans les bornes | oui |
| `HORS_BORNES` | Un seul changement de signe, racine hors de [−0,9999 ; 100] | non |
| `MULTIPLE` | Plusieurs changements de signe, au moins deux racines trouvées sur la grille de balayage | non, racines listées |
| `NON_GARANTI` | Plusieurs changements de signe, une seule racine trouvée : rien ne prouve qu'elle soit la seule | non, racine listée |
| `INDEFINI` | Plusieurs changements de signe, aucune racine trouvée (une racine double peut exister) | non |
| `AUCUN_CHANGEMENT_DE_SIGNE` | Aucun TRI n'existe | non |

Grille de balayage : pas de 0,01 de −0,99 à 1, puis facteur 1,1 jusqu'à 100. Le moteur **n'invente jamais un nombre**.
Hors du statut `UNIQUE`, le reçu dit de lire la VAN ou le TRI modifié.

### TRI modifié

TRIM = (VF des flux positifs au taux de réinvestissement / VA des flux négatifs au taux de financement)^(1/n) − 1.

Le TRIM est `INDEFINI` s'il n'y a pas à la fois un flux positif et un flux négatif. Il est `NON_DEMANDE` si les deux
taux ne sont pas fournis. Fournir un seul des deux taux est refusé.

### Délais de récupération

Le délai est la première période où le cumul, d'abord négatif, devient ≥ 0. Il est interpolé linéairement dans la
période (flux répartis uniformément) et rendu à 1e-4 près.

- Le délai **simple** cumule les flux bruts ; le délai **actualisé** cumule les flux actualisés.
- Statuts : `RECUPERE`, `NON_RECUPERE`, `SANS_INVESTISSEMENT`.
- `redevient_negatif` signale un cumul qui repasse sous zéro après la récupération.

### Amortissement d'un prêt

Fréquences : `mensuelle` (12), `aux_deux_semaines` (26), `hebdomadaire` (52).

Le taux par versement i se tire du taux annuel j selon la convention :

| Convention | Taux par versement i |
|---|---|
| `nominal_compose_a_la_frequence` | j/m |
| `canadienne_semestrielle` | (1 + j/2)^(2/m) − 1. Taux hypothécaire composé semestriellement, usage de la Loi sur l'intérêt |
| `effectif_annuel` | (1 + j)^(1/m) − 1 |

Règles du tableau :

- **Versement** : P · i / (1 − (1 + i)^−n), arrondi au cent ROUND_HALF_UP. Si i = 0, le versement est P/n.
- **Intérêt** de chaque période : solde × i, arrondi au cent ROUND_HALF_UP.
- **Capital** : versement − intérêt.
- **Dernière échéance ajustée** : elle rembourse exactement le solde. Σ capital = principal au cent, et le solde final
  vaut 0. Si l'arrondi solde le prêt avant la n-ième échéance, le tableau s'arrête et un avertissement le dit.
- **Refus** si le versement arrondi ne couvre pas l'intérêt de la première période (amortissement négatif).

Le reçu porte les totaux et `empreinte_tableau`, la SHA-256 du tableau entier. L'outil rend les lignes par pages ; la
concaténation des pages redonne cette empreinte (test).

Références vérifiées par les tests :

- 100 000 $ à 5 % composé semestriellement, sur 25 ans, en versements mensuels : 581,60 $.
- 250 000 $ à 6 % nominal mensuel sur 30 ans : 1 498,88 $.

### Crédit-bail ou achat

Le moteur compare la **valeur actuelle des coûts** des deux options sur le même terme de `mois` mois. Le taux mensuel
se tire du taux annuel effectif : i = (1 + r)^(1/12) − 1.

- **Achat comptant** = prix + frais − VR / (1 + i)^mois.
- **Crédit-bail** = dépôt + Σ paiements actualisés + (option − VR) / (1 + i)^mois, si l'option d'achat est exercée.
  - Paiements en début de période : t = 0…mois−1. En fin de période : t = 1…mois.
  - Sans option exercée, l'actif est rendu au bailleur à la fin du terme.

Toutes les hypothèses sont des entrées explicites. `paiements_en_debut_de_periode` est obligatoire : il n'est jamais
supposé. Le champ `option_au_cout_actualise_le_plus_bas` est un fait calculé, pas une recommandation.

### Point mort

- q* = F / (p − cv), et ⌈q*⌉ pour la quantité entière.
- Chiffre d'affaires du point mort : q* × p.
- Marge de sécurité : (q prévue − q*) / q prévue.
- Le modèle est linéaire.

### Sensibilité et scénarios

Le modèle de projet est fixe :

- flux_0 = −investissement ;
- flux_t = F × (1 + g)^(t−1), arrondi au cent, pour t = 1…n ;
- la valeur résiduelle s'ajoute en n.

Mesures : VAN au taux d'actualisation, TRI avec son statut, délai simple.

La **tornade** fait varier une hypothèse à la fois, de sa valeur basse à sa valeur haute (bas ≤ base ≤ haut). Elle
mesure l'amplitude |VAN(haut) − VAN(bas)| et trie les barres par amplitude décroissante, puis par nom.

Les **scénarios** sont des jeux de valeurs nommés.

Aucune variation n'est fixée par défaut (pas de « ±10 % » implicite) : les valeurs viennent de l'appelant.

## Monte-Carlo de la trésorerie

**Entrées.** La simulation part de la prévision M5.7 existante (`m5_prevoir_tresorerie` : même instantané, même
accès) :

- le solde de départ ;
- les flux connus et datés des semaines calculées ;
- le seuil du propriétaire.

Si la prévision devient non calculable à partir de la semaine X, la simulation s'arrête à X − 1. Si X = 1, l'appel est
refusé.

**Lois de perturbation.** Les lois sont déclarées nature par nature : `facture_client`, `echeancier_contrat`,
`facture_fournisseur`, `attendu_fournisseur`, `taxes`, `paies`, `das`, `dettes`.

| Loi | Paramètres | Méthode |
|---|---|---|
| Triangulaire | `min`, `mode`, `max` | Facteur multiplicatif du montant, par inversion de la fonction de répartition, en formule fermée |
| Normale tronquée | `moyenne`, `ecart_type`, `min`, `max` | Facteur multiplicatif du montant. Inverse de la répartition par l'algorithme AS241 de Wichura (1988) en `Decimal`, le même que `statistics.NormalDist.inv_cdf`. Troncature par Φ(z) = (1 + erf(z/√2))/2, erf par sa série entière sur 90 chiffres, z ramené dans [−10, 10] |
| Bernoulli de retard | `probabilite`, `semaines` | Encaissements seulement : retarder un décaissement serait optimiste. Un encaissement reporté au-delà de l'horizon n'est pas compté |

Règles d'application :

- le facteur est arrondi à 1e-12 (ROUND_HALF_EVEN), puis le montant perturbé au cent (ROUND_HALF_UP) ;
- une nature sans loi reste déterministe ;
- aucun flux nouveau n'est créé.

**Rejouable bit pour bit.** Le générateur est `random.Random(graine)` (Mersenne Twister). Le moteur ne lit que
`getrandbits(53)`, et chaque uniforme vaut u = (2k + 1) / 2^54, dans ]0, 1[. Les lois s'obtiennent par inversion, en
`Decimal`. `ln`, `exp` et `sqrt` de `decimal` ne dépendent pas de la `libm` de la machine.

Chaque flux consomme toujours le même nombre d'uniformes, dans un ordre total : semaine, sens, nature, identifiant. Un
test épingle les chiffres et l'empreinte d'un cas de référence.

**Sorties.** Pour chaque semaine, le moteur rend :

- `solde_base`, le solde de la prévision déterministe ;
- P5, P50 et P95 au **rang le plus proche** : la valeur de rang ⌈p·N⌉ des N tirages triés, sans interpolation ;
- la moyenne ;
- le nombre de tirages négatifs et leur probabilité, à 4 décimales ;
- les mêmes chiffres sous le seuil, si un seuil est fourni.

Sur le chemin entier, il rend aussi la probabilité qu'au moins une semaine soit négative et les percentiles du point le
plus bas. Les semaines sont rendues en colonnes, pour que 26 semaines et le reçu complet tiennent dans une réponse.

**Bornes.**

| Borne | Valeur |
|---|---|
| Tirages | 1 à 10 000 |
| Horizon | 1 à 26 semaines |
| Flux | 400 au plus |
| Tirages × flux perturbés | ≤ 400 000 (environ 2,7 s au pire, mesuré) |
| Graine | Entier de 0 à 2^63 − 1, déclaré. Jamais l'horloge |
| Facteurs | Entre 0 et 10 |
| Écart-type | Supérieur à 0, au plus 5 |
| Masse gardée par la troncature | ≥ 1e-6 |

**Limites.** Les tirages sont indépendants d'un flux à l'autre : aucun choc commun ni aucune corrélation n'est modélisé.
Les lois sont déclarées par l'appelant ; ce ne sont pas des estimations statistiques. Un encaissement que la prévision
ne compte pas (échu ou sans date) ne l'est pas non plus ici.

## Bornes des entrées

| Entrée | Borne |
|---|---|
| Montant | Texte décimal, au plus 2 décimales, \|x\| ≤ 999 999 999 999,99. Le signe est contraint selon le champ |
| Taux | Texte décimal, au plus 12 décimales, de 0 à 1. La croissance d'un projet va de −0,5 à 1 |
| Flux | 2 à 600 périodes |
| Amortissement | 1 à 40 ans |
| Crédit-bail | 1 à 120 mois |
| Projet | 1 à 50 ans |
| Sensibilité | 6 variations et 8 scénarios au plus |

Un nombre JSON, `NaN`, `Infinity` ou la notation scientifique sont refusés : texte décimal exigé.

## Outils (T0, aucun rôle d'appareil)

| Outil | Rend |
|---|---|
| `m5_calculer_rentabilite_investissement` | VAN, TRI (statut), TRI modifié, délais de récupération |
| `m5_calculer_amortissement_pret` | Reçu du tableau entier, plus une page de lignes (`depart`, `limite` ≤ 60, `prochain_depart`) |
| `m5_comparer_credit_bail_achat` | VA des coûts des deux options et leur écart |
| `m5_calculer_point_mort` | Point mort en unités et en chiffre d'affaires, marge de sécurité |
| `m5_analyser_sensibilite_projet` | Tornade et scénarios |
| `m5_simuler_tresorerie_monte_carlo` | Percentiles, probabilité d'un solde négatif, reçu |
| `m5_verifier_recu_calcul` | Empreintes valides, rejeu identique ou non |

Règles communes aux sept outils :

- **Portée fermée.** Aucun outil ne déclare `roles_appareil`. Une identité d'appareil est refusée dans le code
  (`REJ-IDENTITE-APPAREIL-INVALIDE`).
- **Accès du Monte-Carlo.** Il suit la vue des coûts de `m5_prevoir_tresorerie` :
  - pour un agent, `autorise_couts` est obligatoire ;
  - `faux` donne le refus `REJ-CALC-COUTS-REQUIS` : la simulation ne rend que des montants ;
  - le propriétaire confirmé via console est accepté.
- **Mentions.** Chaque sortie acceptée porte les deux mentions (`analyse.SORTIES_CALCUL`).
- **Aucune écriture.** Aucun registre ni événement n'est touché : le test compare la base SQLite entière avant et après
  chaque appel. La garde `conformite.verifier_aucun_decaissement` couvre les modules en mode strict, et le Monte-Carlo
  en lecture seule, car il ouvre le registre des mouvements pour le solde, comme `m5_prevoir_tresorerie`.

## Vague 3 : trois outils de conseil en financement (T0, N0)

Deux moteurs s'ajoutent au registre `MOTEURS` (donc rejouables par `m5_verifier_recu_calcul`) et un composite s'y inscrit au
chargement de `conseiller_financement.py` :

| Moteur (`moteur`, version) | Outil | Rend |
|---|---|---|
| `remboursement_anticipe_pret` | `m5_simuler_remboursement_anticipe` | Jusqu'à 4 stratégies de remboursement accéléré comparées à l'échéancier normal : versements et intérêts économisés, solde final. Pénalité de remboursement anticipé : seulement celle que l'appelant déclare |
| `echelonnement_placements_terme_fixe` | `m5_echelonner_placements_terme_fixe` | Jusqu'à 12 échelons de trésorerie à terme fixe (intérêt simple ou composé annuellement, aux taux SAISIS par l'appelant) : valeur à l'échéance, taux et terme moyens pondérés, couverture de jusqu'à 12 besoins de liquidités. Rachat anticipé et impôt non modélisés |
| `comparaison_financement` | `m5_comparer_financement_achat` | Achat comptant, prêt (amortissement canadien, frais de dossier compris, taux effectif = TRI mensuel annualisé) et location, par la valeur actuelle de leurs coûts ; jusqu'à 6 variations nommées pour la sensibilité ; le reçu cite l'empreinte des calculs qu'il compose |

Ils obéissent aux mêmes règles que les sept outils de la tranche 1 : `Decimal` pur, entrées en texte décimal, refus typés
(`REJ-CALC-*`), `objet` de la liste fermée, garde NC 31-103 sur le texte libre `demande`
(`REJ-CONSEIL-RECOMMANDATION-TITRES`), aucune écriture, aucun rôle d'appareil, mentions obligatoires. Le scénario « au coût
actualisé le plus bas » est un fait de calcul sous les hypothèses, pas une recommandation ; aucun effet fiscal (DPA, TPS/TVQ,
déductibilité) n'est modélisé. Détail et preuves : [M5-SOPHIE](../../../docs/architecture/M5-SOPHIE.md).

## Garde NC 31-103

M5 n'est pas un conseiller inscrit.

- **Objets admis.** Les calculs d'investissement, de prêt, de crédit-bail et de sensibilité exigent un `objet` de la
  liste fermée des décisions d'exploitation : `equipement`, `vehicule`, `outillage`, `immeuble_exploitation`,
  `embauche`, `projet_interne`, `pret_entreprise`, `credit_bail_entreprise`.
- **Refus.** Tout autre objet est refusé (`REJ-CALC-OBJET-HORS-PERIMETRE`) : actions, obligations, fonds, FNB,
  cryptoactifs ou portefeuille. Le refus renvoie à un représentant inscrit.
- **Avertissement.** Chaque reçu dit qu'il s'agit d'information générale calculée sur les hypothèses de l'appelant :
  ni conseil personnalisé, ni recommandation d'achat de titres.

## Codes de refus (`verdicts_calcul.CODES_CALCUL`)

| Code | Quand |
|---|---|
| `REJ-CALC-MONTANT-INVALIDE` | Montant non textuel, illisible, signe interdit, hors bornes ou plus de 2 décimales |
| `REJ-CALC-TAUX-HORS-BORNES` | Taux illisible ou hors de l'intervalle du paramètre ; un seul des deux taux du TRI modifié fourni |
| `REJ-CALC-FLUX-VIDES` | Moins de deux flux |
| `REJ-CALC-FLUX-INVALIDES` | Flux tous nuls, mal formés, en double, sens incohérent avec la nature, booléen manquant |
| `REJ-CALC-FREQUENCE-INCONNUE` | Fréquence de paiement hors de la liste |
| `REJ-CALC-CONVENTION-INCONNUE` | Convention de taux hors de la liste |
| `REJ-CALC-DUREE-INVALIDE` | Années, mois ou semaines hors bornes |
| `REJ-CALC-BORNE-DEPASSEE` | Trop de flux, de tirages ou de scénarios ; budget tirages × flux dépassé ; réponse trop grosse |
| `REJ-CALC-DISTRIBUTION-INVALIDE` | Loi ou nature inconnue, paramètres incohérents, troncature dégénérée, retard sur un décaissement |
| `REJ-CALC-GRAINE-INVALIDE` | Graine absente, non entière, booléenne ou hors de [0 ; 2^63 − 1] |
| `REJ-CALC-MARGE-NON-POSITIVE` | Point mort : prix ≤ coût variable |
| `REJ-CALC-HYPOTHESE-INVALIDE` | Sensibilité : hypothèse inconnue, bas > base ou base > haut, ni variation ni scénario |
| `REJ-CALC-SCENARIO-INVALIDE` | Scénario mal nommé, en double ou avec une hypothèse inconnue |
| `REJ-CALC-PREVISION-NON-CALCULABLE` | Monte-Carlo : aucune semaine calculable dans la prévision |
| `REJ-CALC-OBJET-HORS-PERIMETRE` | Garde NC 31-103 |
| `REJ-CALC-RECU-INVALIDE` | Reçu mal formé ou retouché ; reçu compact soumis au rejeu |
| `REJ-CALC-MOTEUR-INCONNU` | Moteur ou version que ce code ne sait pas rejouer |
| `REJ-CALC-COUTS-REQUIS` | Monte-Carlo sans droit aux coûts |
| `REJ-CALC-PAGE-INVALIDE` | `depart` ou `limite` hors bornes (tableau d'amortissement) |
| `REJ-CALC-AMORTISSEMENT-IMPOSSIBLE` | Le versement arrondi ne couvre pas l'intérêt de la première période |

## Preuves

Les tests sont dans `tests/test_moteur_calcul.py` et `tests/test_moteur_calcul_outils.py`.

**Valeurs de référence**, recalculées indépendamment en `fractions.Fraction` :

- TRI de flux à solution exacte (10 %, 33,1 %, 0 %) ;
- TRI de flux irréguliers comparé à une bissection rationnelle à 1e-28 ;
- rente de 20 ans : TRI de 7,7547 % ;
- versements canadiens composés semestriellement, en mensuel, aux deux semaines et en hebdomadaire. Le taux i est
  encadré par une bissection rationnelle ; la formule fermée donne le même cent aux deux bornes ;
- références publiées : 581,60 $ et 1 498,88 $ ;
- VAN, TRI modifié, délais, crédit-bail à taux nul, point mort ;
- chaque barre de la tornade.

**Propriétés sur des cas générés à graine** :

- 300 suites de flux conventionnelles : TRI `UNIQUE` et |VAN(TRI)| sous la tolérance déclarée ;
- 150 prêts : Σ capital = principal au cent, cohérence de chaque ligne ;
- 400 points de l'inverse normale comparés à `statistics.NormalDist` ;
- moyennes des lois triangulaire et normale tronquée.

**Reçus** : chaque reçu se rejoue à l'identique après un aller-retour JSON. Un reçu retouché est refusé. Deux écritures
d'une même entrée donnent la même empreinte. Les chiffres et l'empreinte du Monte-Carlo sont épinglés.

**Mutations tuées (8 sur 8)** :

1. convention canadienne en 1/m au lieu de 2/m ;
2. arrondi HALF_EVEN au lieu de HALF_UP ;
3. dernière échéance non ajustée ;
4. TRI multiple traité comme unique ;
5. rang des percentiles au plancher au lieu du plafond ;
6. Bernoulli de retard inversé ;
7. garde NC 31-103 retirée ;
8. vérification d'empreinte retirée.

## Ce qui n'est pas couvert

- **Statistiques avancées et prévision de séries chronologiques** : ARIMA/ETS, Croston, Prophet, bayésien (PyMC), et
  distributions empiriques des délais de chaque client. À brancher quand numpy, statsforecast ou SciPy seront
  installables (`R2-FINANCE-FISCALITE-CALCUL.md` §5). La prévision reste celle des flux connus et datés (M5.7).
- **Optimisation** : allocation de trésorerie, ordonnancement des paiements fournisseurs, portefeuille (cvxpy,
  OR-Tools).
- **XIRR** (flux à dates irrégulières), conventions de jours et échéanciers datés de prêts (QuantLib) : les périodes
  sont numérotées, sans dates.
- **Corrélations** entre flux dans le Monte-Carlo, et rétro-tests de couverture P5–P95.
- **Effets fiscaux** : DPA par catégorie, demi-année, CRIC, TPS/TVQ et déductibilité. Aucun n'est modélisé : à valider
  avec le CPA.
- **Persistance des reçus** comme artefacts immuables : un reçu vit dans la réponse de l'outil, il n'est pas archivé.
