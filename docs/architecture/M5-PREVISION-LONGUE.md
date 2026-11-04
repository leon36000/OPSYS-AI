# M5 FinanceCore : prévision financière longue 6 / 12 / 24 mois (M5-PREV-2)

Branche `wt-ds-w14-m5`, base `a0e5c51b2` (registre MCP révision 37 après scellement). Source d'exigences : l'analyse
d'écart des anciens prompts de Nathan (`docs/reprise/PROMPTS-NATHAN-ANCIENS/ANALYSE-M5.md`, P1/P2 et backlog
**M5-PREV-2**), complétée par la fiche M5 du backlog. **Aucune migration** : aucun registre nouveau, aucune table ; les
trois sources existent déjà (`mouvements`, `grand_livre`, `budgets_declares`, `echeanciers_contrats_tresorerie`).

Tout ce document est **préparatoire** : À valider auprès d'un comptable (CPA) / professionnel qualifié. **Aucun CPA n'a
validé la méthode, les hypothèses ni les chiffres.**

## Ce qui est livré

| Outil | Niveau | Geste |
|---|---|---|
| `m5_prevoir_tresorerie_longue` | T0 | Projection mensuelle du solde sur **6, 12 ou 24 mois complets**, à partir du carnet de contrats daté, du budget déclaré et de la moyenne du grand livre ; scénarios **nommés**, hypothèses **déclarées**. Sans `scenario` : résumé **paginé** des scénarios (`depart`, `limite`, total et suite) ; avec : série mensuelle paginée. `recu_complet` rend le reçu complet rejouable. |
| `m5_rejouer_prevision_longue` | T0 | Vérifie les empreintes d'un reçu puis **refait le calcul** depuis ses entrées normalisées ; un reçu compact se vérifie sans se rejouer hors ligne. |

Portée d'appareil **fermée** pour les deux (aucun rôle, refusé dans le code par `_appareil_refuse`). Aucun paiement,
aucune remise, aucune déclaration, aucun envoi, aucune écriture. Les deux modules de calcul sont **purs** (aucun import
`opsys`, aucune horloge, aucun registre) ; l'adaptateur lit et normalise, il ne calcule pas.

Modules : `prevision_longue.py` (calcul), `verdicts_prevision_longue.py` (catalogue fermé de refus, à part de
`validation.py` pour ne pas toucher le catalogue partagé de la paie), `outils_prevision_longue.py` (adaptateur et
déclaration MCP). La garde AST `conformite.verifier_aucun_decaissement` couvre les deux modules purs en **strict** et
l'adaptateur en **lecture seule**.

## La règle d'or : trois sources, une priorité par mois, aucun double compte

Pour chaque mois projeté, le **produit** du mois vient de la source la plus certaine disponible :

1. **une échéance contractuelle** dont la date tombe dans le mois (`echeanciers_contrats`, échéancier saisi et revu par
   une personne, TTC de la pièce, aucune taxe recalculée) ;
2. sinon, le **budget de produits** déclaré pour ce mois (`budgets_declares`, `m5_etablir_budget`, N3) ;
3. sinon, la **moyenne mensuelle des produits** des écritures **définitives** du grand livre sur les
   `mois_historique` mois complets qui précèdent le mois courant, multipliée par la croissance et la saisonnalité du
   scénario.

Les **charges** suivent la même priorité (budget du mois, sinon moyenne du grand livre), **sans saisonnalité** : la
saisonnalité déclarée porte sur les revenus, jamais sur les charges.

Quand une échéance contractuelle tombe dans un mois, le budget de **produits** de ce même mois est **ignoré** (il est
déjà couvert par le contrat) et **compté** dans `couverture.budget_produits_ignores_*`. C'est la garantie anti-double
compte : le budget n'est jamais ajouté par-dessus une échéance, et l'échéance n'est jamais ajoutée par-dessus le budget.

**Un zéro déclaré est un zéro connu.** Un budget à `0.00` pour un mois ne déclenche aucun repli sur l'historique : la
direction a déclaré zéro, le calcul l'utilise. Un mois sans budget du tout, lui, prend la moyenne du grand livre et le
dit (`couverture.mois_recurrents`).

## Les hypothèses sont DÉCLARÉES, jamais reçues en argument ni supposées

Elles vivent dans `configuration.prevision_longue` du `department.yaml`, relu à chaque appel. L'outil ne les reçoit pas
dans ses arguments : un agent ne peut pas changer la croissance, la saisonnalité ou un délai pour « améliorer » un
résultat. Forme (les valeurs ci-dessous sont des **EXEMPLES de forme fictifs**, jamais des valeurs à recopier) :

```yaml
configuration:
  prevision_longue:
    mois_historique: 12                 # 3 à 24 : mois COMPLETS avant le mois courant, avec écritures définitives
    scenarios:                          # 1 à 4 scénarios NOMMÉS (noms uniques, minuscules)
      - nom: "base"                     # nom exact rendu par l'outil
        croissance_revenus_mensuelle: "0.00"    # texte décimal, strictement > -1 et <= 1
        croissance_charges_mensuelle: "0.00"    # même borne, appliquée dès le premier mois projeté
        saisonnalite: ["1.00", "1.00", "1.00", "1.00", "1.00", "1.00",
                       "1.00", "1.00", "1.00", "1.00", "1.00", "1.00"]   # DOUZE coefficients 0 à 3
        delai_encaissement_jours: 30    # 0 à 365 : fin du mois + N jours pour un produit non contractuel
        delai_paiement_jours: 30        # 0 à 365 : fin du mois + N jours pour une charge
      - nom: "prudent"
        croissance_revenus_mensuelle: "-0.02"
        croissance_charges_mensuelle: "0.01"
        saisonnalite: ["0.8", "0.8", "0.9", "1.0", "1.1", "1.2",
                       "1.2", "1.1", "1.0", "0.9", "0.8", "0.8"]
        delai_encaissement_jours: 60
        delai_paiement_jours: 30
```

Le manifeste livré **ne porte aucun `prevision_longue`** : vide, l'outil refuse avec
`REJ-PREVISION-LONGUE-A-DECLARER` et dit exactement quoi écrire. Aucun scénario, aucune croissance, aucun coefficient,
aucun délai n'est proposé par le code. Une valeur que l'architecte ou Nathan écrirait resterait une **recommandation non
validée** jusqu'à sa décision ; le code ne l'écrit pas.

**Pourquoi pas CFG-1 (`reglages:`)** : les réglages de direction sont des scalaires (entier, décimal, texte, liste
d'entiers) ; un scénario est un objet à douze coefficients et deux délais. Le budget déclaré a déjà suivi ce choix
(registre propre, pas CFG-1) ; la prévision longue lit sa configuration dans le manifeste, comme `configuration.prevision`
de la prévision à 13 semaines.

## Le calcul, mois par mois

- **Horizons** : seuls 6, 12 et 24 mois **complets après le mois courant**. Le mois courant, partiel, n'est jamais
  projeté ; le premier mois est le suivant `aujourd_hui`.
- **Solde de départ** : le solde du **registre des mouvements** (`soldes.calculer_solde`), pas la somme des comptes de
  banque du grand livre. Un écart entre les deux n'est pas réconcilié ici (dit dans les limites).
- **Historique** : la fenêtre est exactement les `mois_historique` mois complets qui précèdent le mois courant. Chaque
  mois doit porter **au moins une écriture définitive** ; un mois vide fait refuser
  (`REJ-PREVISION-LONGUE-HISTORIQUE-INCOMPLET`) plutôt que d'entrer zéro dans une moyenne. Les brouillons sont comptés
  à part, jamais additionnés.
- **Moyenne** : `somme des produits / nombre de mois`, arrondie au cent `ROUND_HALF_UP` ; idem pour les charges.
- **Croissance** : `moyenne × (1 + croissance) ^ rang`, où le rang du premier mois projeté vaut 1 ; arrondi au cent.
- **Saisonnalité** : coefficient du **mois civil** de la ligne (janvier = indice 0, décembre = indice 11), appliqué au
  produit récurrent du mois.
- **Délais** : un produit du budget ou de l'historique est encaissé à la **fin de son mois + N jours** ; une charge est
  payée à la même règle avec son délai. Une échéance contractuelle **garde sa date** : elle est déjà datée par la pièce,
  le délai client ne s'y applique pas.
- **Hors horizon** : un flux dont la date de trésorerie sort de l'horizon est exclu et compté
  (`produits_hors_horizon`, `charges_hors_horizon`), jamais replié sur le dernier mois.
- **Prudence** : une échéance contractuelle **échue** n'est pas comptée (un client en retard ne paie pas « au mois 1 ») ;
  son nombre et son montant sont dits. Une échéance hors horizon est exclue et dite.
- **Carnet incomplet, distingué de la source** : l'adaptateur valide d'abord `devis_recus` sur le même modèle
  fail-closed que `m5_prevoir_tresorerie_contrats` : chaque maillon doit être un objet portant
  `devis_id`, `lead_id`, `chantier_id`, `lignes`, `prix_total`, `horodatage_acceptation`, avec un `devis_id` textuel
  non vide et **un seul** événement par devis. Une structure absente, un identifiant invalide ou un doublon
  contradictoire refuse tout le carnet (`REJ-PREVISION-LONGUE-CARNET-INVALIDE`) : aucun événement n'est écrasé.
  Ensuite, `echeanciers_contrats.flux_prevision` bloque un contrat dont la couverture n'atteint pas la fin de
  l'horizon, un contrat dont le devis manque ou dont une facture active du même devis existe (double compte). La
  réponse distingue explicitement :
  - `couverture.devis_sans_echeancier` (nombre) et `couverture.incompletude` (phrase sans identifiant) quand un devis
    accepté n'a pas encore de contrat : aucun montant n'est projeté pour lui, et ce n'est **pas** un contrat bloqué ;
  - `couverture.contrats_bloques` (codes `REJ-CONTRAT-*`) quand un contrat existant est bloqué : aucun montant partiel
    n'est projeté.
  Ces champs sont omis quand ils sont vides, pour ne pas gonfler la réponse. Aucun identifiant de devis, nom,
  texte libre ni donnée personnelle n'est rendu dans la couverture.
- **Provenance** : la réponse liste les six registres effectivement décisifs — `mouvements`, `grand_livre`,
  `budgets_declares`, `echeanciers_contrats_tresorerie`, `devis_recus`, `factures` — avec leur taille et, pour les
  registres chaînés, les huit premiers caractères de leur tête. `devis_recus` n'est pas chaîné : sa tête est absente,
  jamais un identifiant. La provenance est **hors du reçu** : un reçu prouve le calcul de ses entrées normalisées, pas
  l'état courant des registres.
- **Arithmétique** : `Decimal` exact, contexte 64 ; chaque montant calculé est arrondi au cent avec `ROUND_HALF_UP` et
  aucun autre arrondi n'existe. Jamais de flottant.

## Fail-closed : ce que l'outil refuse, et ce qu'il dit

| Code | Quand |
|---|---|
| `REJ-PREVISION-LONGUE-A-DECLARER` | `configuration.prevision_longue` absente ou vide |
| `REJ-PREVISION-LONGUE-CONFIGURATION-INVALIDE` | clé inconnue, plus de quatre scénarios, structure fermée violée |
| `REJ-PREVISION-LONGUE-MOIS-HISTORIQUE-INVALIDE` | `mois_historique` hors 3–24, booléen, texte |
| `REJ-PREVISION-LONGUE-SCENARIOS-A-DECLARER` | liste absente ou vide |
| `REJ-PREVISION-LONGUE-SCENARIO-INVALIDE` / `-DOUBLE` / `-INCONNU` | nom hostile, clé inconnue, doublon, nom non déclaré |
| `REJ-PREVISION-LONGUE-CROISSANCE-INVALIDE` | croissance hors `]-1, 1]`, flottant ou illisible |
| `REJ-PREVISION-LONGUE-SAISONNALITE-A-DECLARER` / `-INVALIDE` | moins ou plus de douze coefficients, valeur hors 0–3 |
| `REJ-PREVISION-LONGUE-DELAI-INVALIDE` | délai hors 0–365 ou non entier |
| `REJ-PREVISION-LONGUE-HISTORIQUE-INCOMPLET` | mois manquant, non consécutif, sans écriture définitive |
| `REJ-PREVISION-LONGUE-HISTORIQUE-INVALIDE` | montant non décimal, clé inconnue |
| `REJ-PREVISION-LONGUE-BUDGET-INVALIDE` / `-DOUBLE` / `-HORS-PLAN` | budget négatif, hors horizon, mois double, compte absent du plan |
| `REJ-PREVISION-LONGUE-CARNET-INVALIDE` / `-DOUBLE` / `-DATE-INVALIDE` | échéance mal formée, montant ≤ 0, doublon, date illisible ; ou `devis_recus` de structure invalide, identifiant invalide ou devis dupliqué |
| `REJ-PREVISION-LONGUE-CHAINE-INVALIDE` | registre altéré (grand livre, mouvements, budgets, échéanciers, factures) |
| `REJ-PREVISION-LONGUE-ECHEANCIER-INVALIDE` | échéancier illisible ou version orpheline |
| `REJ-PREVISION-LONGUE-REPONSE-TROP-GROSSE` | la réponse ne tient pas sous le budget même avec une ligne (ou un seul résumé de scénario), ou le reçu complet demandé ne tient pas (jamais tronqué) |
| `REJ-PREVISION-LONGUE-TRANSPORT-INVALIDE` | curseur incohérent, résultat recalculé différent ou offset hors du résultat |
| `REJ-PREVISION-LONGUE-RECU-INVALIDE` / `-REJEU-DIFFERENT` | reçu retouché, moteur ou version étrangers, ou rejeu qui ne redonne pas le même calcul |

Chaque refus est un `{code, detail}` ; le détail dit quoi corriger ou quoi déclarer. Aucun refus ne rend zéro, une
moyenne ni une valeur par défaut.

## Reçu, rejeu et budget de réponse

Chaque calcul rend un `recu-calcul.v1` : méthode, précision, paramètres, entrées normalisées (historique, budget,
carnet, configuration), empreintes SHA-256 et résultat avec `empreinte_etat` (l'état complet des scénarios). Le reçu
complet est **rejouable** par `m5_rejouer_prevision_longue` : il refait le calcul depuis les entrées et compare
l'empreinte.

**En-tête du reçu.** `m5_rejouer_prevision_longue` exige explicitement `moteur == "prevision_longue"` et
`version_moteur == "1.0.0"` **avant** de présenter le reçu comme valide pour cet outil. Le vérificateur générique
`recu_calcul.verifier` reste inchangé : il ne juge que l'intégrité du format. Un reçu réempreinté (empreintes
recalculées) d'un autre moteur ou d'une autre version est donc intègre au sens générique, mais refusé par l'outil avec
`REJ-PREVISION-LONGUE-RECU-INVALIDE` ; le calcul n'est pas exécuté. Un reçu **compact du même moteur** reste vérifiable
(`recu_valide: true`, `rejoue: false`) ; il ne prétend pas au rejeu hors ligne.

**Portée du reçu.** Le reçu atteste le calcul de ses entrées normalisées et l'intégrité de son contenu. Il ne
revalide **pas** l'état courant des registres, ni la provenance (`sources`) affichée par une projection. La réponse de
rejeu porte cette portée dans `portee` ; un reçu émis avant qu'une facture bloque un contrat reste rejouable, alors
qu'une **nouvelle** projection voit le blocage.

Sous le budget d'une réponse (5 300 caractères), le reçu part **compact** (sans `entrees`, empreinte conservée) ; la
projection reste vérifiable, mais le rejeu hors ligne demande le reçu complet. `m5_prevoir_tresorerie_longue` accepte
`recu_complet: true` : il rend alors **seulement** le reçu complet, sans aucune ligne de projection. C'est le chemin
prouvé de bout en bout.

**Pagination du résumé (sans `scenario`).** `depart` et `limite` paginent désormais les **résumés de scénarios**,
comme ils paginent déjà les lignes d'un scénario choisi. Une page porte `scenarios_total`, `scenarios_depart`,
`scenarios_affiches` et `prochain_depart` (nul sur la dernière page). Si la page demandée ne tient pas sous 5 300, elle
est **réduite d'un scénario à la fois** et la réponse le dit par `scenarios_affiches` et `prochain_depart`. Aucun
avertissement n'est supprimé. Tant que les registres et la configuration restent inchangés, le reçu compact est
identique d'une page à l'autre (il contient toujours tous les scénarios et son empreinte). Les pages relisent les
registres : comparer les reçus permet de détecter un changement, mais aucun curseur ne fige un instantané. Un `depart`
au-delà du total rend une page **vide tracée** (`scenarios: []`, `scenarios_affiches: 0`, `prochain_depart: null`),
jamais une erreur ni un
repli. Si même **un** résumé de scénario, son reçu compact et les avertissements ne tiennent pas, l'outil refuse avec
`REJ-PREVISION-LONGUE-REPONSE-TROP-GROSSE` : aucune page partielle n'est rendue. Ce refus peut aussi survenir après
plusieurs pages acceptées, par exemple pour un dernier scénario dont les 24 mois sont en découvert avec une couverture
chargée ; `prochain_depart` ne garantit donc pas que la page suivante tiendra dans le budget. Le reçu, ses empreintes,
sa portée et tout calcul d'argent sont inchangés ; le rejeu reste régi par les entrées du reçu, pas par la page consultée.

**Transport complet sans stockage (`transport_pagine: true`).** Mode additif pour une page logique qui dépasse le budget.
Le premier appel garde les mêmes paramètres M5 et omet `empreinte_resultat` et `offset_transport`. Chaque réponse
retourne un `fragment` de JSON canonique, `longueur_caracteres`, une empreinte SHA-256 et `prochain_offset`. Pour
continuer, l'appelant répète les mêmes paramètres de prévision et fournit l'empreinte et l'offset de la page précédente.
Il concatène les fragments dans l'ordre et ne parse le JSON reconstruit qu'après `prochain_offset: null`. Chaque
enveloppe, mentions incluses, reste sous le même budget de sortie; aucune section ni aucun caractère n'est supprimé ou
tronqué. Le mode choisit le même reçu complet ou compact que la réponse publique normale aurait accepté.
`recu_complet: true` reste l'option explicite pour transporter le reçu rejouable complet.

L'empreinte porte sur le JSON public entier recalculé, reçu et provenance inclus. Une différence à la reprise provoque
un refus générique sans donnée de résultat; recommencer à la première page. Ce SHA-256 non signé contrôle seulement la
cohérence des fragments, pas leur authenticité. Les registres sont relus à chaque page, aucun instantané n'est stocké
et les droits M5 restent ceux de l'outil existant. Une sortie changée est détectée; le mécanisme ne garantit pas une
vue temporelle atomique entre appels. Sur PostgreSQL en `READ COMMITTED`, des écritures concurrentes pourraient aussi
être vues différemment par plusieurs lectures d'un même calcul ; ce cas concurrent n'a pas encore été éprouvé.

**`scenario` en mode reçu complet.** Le contrat existant est explicité : un scénario **valide** ne change pas le reçu
(il n'y a aucune ligne à filtrer) ; il est seulement validé. Un scénario **inconnu** est refusé
(`REJ-PREVISION-LONGUE-SCENARIO-INCONNU`), jamais ignoré silencieusement. Refuser tout `scenario` en mode reçu complet
casserait les appelants qui passent le scénario de la projection ; ce n'est pas fait.

**Reçu complet trop gros.** Le reçu complet n'est jamais tronqué ni remplacé par un reçu compact quand
`recu_complet: true`. S'il dépasse le budget de réponse, l'outil public refuse avec
`REJ-PREVISION-LONGUE-REPONSE-TROP-GROSSE` (catalogue de la prévision longue), jamais avec un code d'un autre outil.

## Preuves exécutées

- `departments/m05-financecore/tests/test_prevision_longue.py` : cas de calcul pur, bornes, refus, reçu, rejeu, avec
  des valeurs calculées à la main dans les docstrings.
- `departments/m05-financecore/tests/test_prevision_longue_outils.py` : cas sur SQLite réelle, vrais registres, vrai
  sas N3/N4, vrai plan comptable, vrai bus (aucun événement publié) ; cas de référence 20 000 → 21 449,75 $ ; refus
  d'appareil ; grand livre, budget et échéancier altérés ; devis reçus altéré ou dupliqué ; contrat à couverture
  incomplète ; devis sans échéancier distingué ; provenance des six registres ; reçu étranger ou réempreinté refusé ;
  reçu complet rejoué et reçu complet trop gros refusé sans troncature ; pagination du résumé de 1 à 4 scénarios (noms
  légaux de 40 caractères, horizon et historique maximaux, `limite=3`, `depart` hors borne, reçu identique, refus sans
  troncature) ; garde anti-décaissement.
- `./ruff.sh`, `./verif.sh`, `./sceller.sh` (révision 37), `./docs.sh`, gardes documentaires : voir le rapport.

## Mutations

Voir `RAPPORT.md` : balayage `mutkit.py sweep` sur `prevision_longue.py`, `verdicts_prevision_longue.py` et
`outils_prevision_longue.py`, mutants tués, survivants équivalents expliqués.

## Limites (sans euphémisme)

- **Aucune valeur réelle** : ni les scénarios, ni les croissances, ni la saisonnalité, ni les délais, ni le budget de
  Nathan ne sont dans le dépôt. Sans déclaration, l'outil refuse.
- **Aucun CPA n'a validé** la méthode, le découpage en trois couches, la priorité carnet > budget > historique, ni les
  arrondis.
- **Ce n'est pas une prévision de trésorerie complète** : taxes TPS/TVQ, paies et retenues, DAS, dettes, impôts,
  subventions et acomptes provisionnels ne sont pas inclus. La prévision des flux connus et datés
  (`m5_prevoir_tresorerie`, 13 semaines) et le cash libre restent les références pour ces obligations ; la prévision
  longue ne les remplace pas et ne s'y ajoute pas.
- **Aucun pipeline commercial** : M5 ne lit ni M2 ni M8 pour cette projection ; aucune vente probable, aucun taux de
  conversion, aucune pondération n'est ajoutée. La couche « probable » de l'analyse M5 n'est donc pas livrée ici.
- **Historique = moyenne** : une activité irrégulière, un chantier exceptionnel ou une saison apprise ne sont pas
  représentés autrement que par la moyenne et les coefficients déclarés. Le grand livre doit être complet (brouillons
  validés) ; sinon les mois vides font refuser.
- **Carnet = échéanciers explicitement saisis** : un devis accepté n'est ni un contrat signé ni un encaissement ; une
  facture active du même devis bloque l'échéancier. Le TTC vient de la pièce, aucune taxe n'est recalculée.
- **Le solde de départ n'est pas réconcilié** avec la somme des comptes de banque du grand livre.
- **Budget déclaré** : M5 ne propose ni ne calcule de budget ; sans budget, l'historique sert de base et le dit.
- **Jamais PostgreSQL, jamais un écran, jamais un téléphone** : prouvé sur SQLite en processus. Aucun navigateur, aucun
  appareil réel, aucune charge, aucune concurrence multi-machines.
- **Aucun constat planifié, aucun événement, aucune table** : la prévision est une lecture à la demande, pas une
  publication au bus ; M8 ne la consomme pas.
- **La réponse est bornée** : le reçu complet n'est jamais dans la même réponse que la projection détaillée ; il faut
  l'appeler avec `recu_complet`.

## Décisions qui reviennent à la direction

1. Les **scénarios** : leurs noms, leur nombre (1 à 4), la croissance mensuelle des revenus et des charges.
2. Les **douze coefficients de saisonnalité** de chaque scénario (aucune saisonnalité apprise n'est calculée).
3. Les **délais** d'encaissement client et de paiement fournisseur (0 à 365 jours).
4. Le **nombre de mois historiques** (3 à 24) : plus long lisse davantage, mais exige un grand livre complet sur la
   période.
5. Le **budget** de chaque mois (produits et charges), par `m5_etablir_budget` (N3) — M5 n'en propose aucun.
6. La **validation CPA** de la méthode, des arrondis et de l'interprétation « carnet > budget > historique ».
