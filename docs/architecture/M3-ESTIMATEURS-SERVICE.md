# M3 — Estimateurs par service (M3.8b)

Statut (2026-11-03) : **PARTIEL, prouvé en S** (outils réels, SQLite migrée, horloge injectée, données fictives).
Aucune valeur réelle, aucune intégration à `m3_estimer_projet`, aucun écran, PostgreSQL non éprouvé.

Chantier issu de `docs/reprise/PROMPTS-NATHAN-ANCIENS/ANALYSE-M3.md` §2 (M3.8a/b/c) : le barème déclaré (M3-C1) et la
mesure déclarée (M3-C2) étaient livrés, mais **un seul poste de barème par service** était chiffré à partir d'**une
seule** quantité. M3.8b demandait les variables par service (longueur, descentes, coins, ouvertures, pertes, minimum,
temps minimum) ; la fiche laissait M3.8b `ABSENT`. Ce chantier livre la composition des quantités par service, sans
jamais coder ni inventer un prix, un taux ou un coefficient.

## 1. Ce qui est déclaré, et par qui

Tout coefficient vient du **barème déclaré** par une personne (propriétaire ou administrateur, identité revérifiée en
base : `m3_declarer_bareme`). La mesure de chaque composante est déclarée par une personne (`m3_declarer_mesure`), avec
ses bornes, sa méthode, sa confiance et ses pièces. Aucun agent ne déclare ni ne corrige une valeur.

La version de barème porte un bloc **facultatif** `parametres.estimateurs.<service>` :

```json
{
  "unite_ouvrage": "<unité de la ligne d'ouvrage>",
  "composantes": [
    {
      "grandeur": "<code de la mesure attendue>",
      "unite": "<unité de la mesure>",
      "coefficient": "<texte décimal signé, jamais zéro>",
      "facteur_conversion": "<texte décimal positif, seulement si l'unité diffère>",
      "source_ecrite": "<document, date, auteur>"
    }
  ],
  "quantite_minimum": "<texte décimal positif, facultatif>",
  "temps_minimum_minutes": "<texte décimal positif, facultatif>"
}
```

Règles de la déclaration (`bareme_registre._valider_estimateurs`, refus `REJ-BAREME-INVALIDE`) :

- le service doit avoir **une ligne d'ouvrage** dans la même version, et `unite_ouvrage` doit être **exactement** son
  unité (sinon l'estimateur ne pourrait chiffrer aucun coût) ;
- une composante a un code de `grandeur` stable (jamais un texte libre), une unité, un `coefficient` **signé** (positif
  = ajout, négatif = soustraction, zéro refusé) et une `source_ecrite` obligatoire ;
- `facteur_conversion` est **obligatoire** quand l'unité de la composante diffère de celle de l'ouvrage (aucune
  conversion devinée) et **interdit** quand les unités sont identiques (conversion ambiguë) ;
- une `grandeur` ne peut apparaître deux fois ; seize composantes au plus par service ; une clé inconnue est refusée ;
- `quantite_minimum` et `temps_minimum_minutes` sont strictement positifs.

Le bloc ne change **pas** le barème compilé du moteur (`bareme_registre.compiler`) : un test l'épingle. Les montants
unitaire restent ceux de la ligne d'ouvrage ; l'estimateur ne fait que composer la **quantité** dans son unité.

## 2. La formule (versionnée, `m3-estimateur-service/1`)

```text
contribution_i   = coefficient_i × facteur_conversion_i × valeur_i
quantité_retenue = max(Σ contribution_i, quantite_minimum déclaré)
quantité_basse   = max(Σ min(facteur_i × borne_basse_i, facteur_i × borne_haute_i), quantite_minimum)
quantité_haute   = max(Σ max(facteur_i × borne_basse_i, facteur_i × borne_haute_i), quantite_minimum)
```

Un coefficient négatif **inverse les bornes de sa composante** : la borne basse du total prend la borne haute de la
soustraction (ouvertures, surface déduite). Sans cela, l'intervalle mentirait — un test le prouve sur un revêtement.

Les calculs sont en `Decimal`; les montants sont arrondis au **cent, `ROUND_HALF_UP`**, comme M5 et
`devis_durable.prix_depuis_cout` :

- `coût minimal` = quantité basse × coût unitaire minimal ;
- `coût maximal` = quantité haute × coût unitaire maximal ;
- `coût probable` = quantité retenue × coût unitaire **mode**, **seulement si le mode est déclaré** ; sinon `null` et
  une ligne dans `elements_manquants` ;
- `prix recommandé` = coût probable × (1 + `taux_marge.normal`), **seulement si le mode et le taux normal sont
  déclarés**, via la fonction de prix unique du paquet (aucune formule dupliquée) ; sinon `null` et la ligne à déclarer ;
- `durée` = quantité retenue × `duree_minutes_par_unite` de la ligne d'ouvrage, portée au `temps_minimum_minutes`
  déclaré s'il est plus grand ; taux absent : `null`, jamais une durée inventée.

Aucun seuil de marge, aucun prix de scénario n'est calculé ici : les scénarios et le plancher restent ceux de
`m3_estimer_projet` (section 5).

## 3. Le reçu de calcul

La réponse porte `recu` (et les mêmes valeurs utiles à la racine) :

| Champ | Contenu |
|---|---|
| `formule` | `m3-estimateur-service/1` |
| `bareme_ref` | `{bareme_id, version, empreinte}` de la version résolue |
| `composantes[]` | `grandeur`, `mesure_id`, `revision`, `empreinte`, unité, méthode, confiance, statut de mesure, valeur et bornes, coefficient, conversion, contributions (retenue/basse/haute), source écrite |
| `quantite` | basse, retenue, haute, unité, `minimum_declare`, `minimum_applique` |
| `couts_unitaires` | min, mode, max **déclarés** |
| `couts` | min/probable/max au cent, devise CAD, `ROUND_HALF_UP` |
| `duree` | minutes, taux, minimum déclaré, `minimum_applique` |
| `prix_recommande_cad` | prix déterministe, ou `null` |
| `statut`, `motifs_revue`, `elements_manquants` | revue et déclarations à compléter |
| `empreinte` | SHA-256 du reçu (contenu canonique, empreinte exclue) |

`estimateurs_service.verifier_recu(recu)` **refait l'arithmétique** depuis les entrées enregistrées (contributions,
quantité, coûts, prix, durée) puis vérifie l'empreinte. Il prouve la cohérence interne du reçu, **pas l'authenticité
des registres** : les empreintes du barème et des mesures sont citées, mais une chaîne entièrement réécrite par qui
peut recalculer toutes les empreintes n'est pas détectée ici (même limite assumée que `bareme_registre`).

## 4. Fail-closed : ce que le refus dit

| Cas | Verdict |
|---|---|
| aucun estimateur pour ce service | `REJ-ESTIMATEUR-NON-DECLARE` : la clé `parametres.estimateurs.<service>`, la forme à déclarer, aucune valeur d'exemple chiffrée |
| une ou plusieurs mesures requises absentes | `REJ-ESTIMATEUR-MESURES-MANQUANTES` : **toutes** les grandeurs manquantes, puis `m3_declarer_mesure` |
| mesure d'une grandeur non déclarée | `REJ-ESTIMATEUR-MESURE-NON-PREVUE` : grandeurs admises, sans recopier un texte hostile (une grandeur non codée est dite « ? ») |
| deux mesures pour la même grandeur | `REJ-ESTIMATEUR-MESURE-AMBIGUE` : jamais un choix silencieux |
| mesure d'un autre lead/service | `REJ-MESURE-AUTRE-LEAD` (même règle que `m3_estimer_projet`) |
| unité différente | `REJ-MESURE-UNITE` : aucune conversion devinée |
| mesure périmée | `REJ-MESURE-PERIMEE` : date et validité déclarée |
| bornes trop larges pour un prix | `REJ-MESURE-INSUFFISANTE` : seuil déclaré |
| quantité nulle ou négative | `REJ-ESTIMATEUR-QUANTITE-NON-POSITIVE` : vérifier mesures et coefficients, jamais ramener à zéro |
| borne basse de coût ≤ 0 | `REJ-ESTIMATEUR-BORNES-NON-POSITIVES` : aucune borne inventée |
| entrée mal formée | `REJ-ESTIMATEUR-INVALIDE` |

Manques **non bloquants** (le calcul reste possible, la liste dit quoi déclarer) : `cout_unitaire_mode`,
`taux_marge.normal`, `duree_minutes_par_unite`. Une revue est demandée (`statut: a_revoir`) quand une mesure est
au-delà du seuil de revue déclaré ou de confiance faible — les motifs viennent de `mesure_declaree.evaluer`, jamais
d'un seuil recalculé ici.

## 5. Outil et intégration

Outil `m3_calculer_estimation_service` (T0, lecture seule, **fermé aux appareils**) :

```text
lead_id, service, bareme_ref {bareme_id, version, empreinte?}, mesures_ref [{mesure_id, revision?, empreinte?}]
```

Il résout le barème **en vigueur** (validé, empreinte vérifiée), vérifie la **déclaration d'estimateur avant** de
résoudre les mesures (le refus le plus en amont est dit en premier), résout chaque mesure pour ce lead et ce service,
puis appelle le module pur. Aucune écriture, aucun évènement, aucune publication.

**Ce qui n'est pas branché (limite assumée)** : `m3_estimer_projet` continue de chiffrer **une** mesure déclarée avec
le Monte Carlo, le plancher et les scénarios. L'estimation composite n'alimente pas encore son registre, son reçu
`declaration` ni son contrat gelé `EstimationV1`. Le parcours actuel est : l'agent calcule la quantité composée et son
coût, une personne déclare la mesure correspondante (avec les bornes du reçu), puis `m3_estimer_projet` chiffre selon
la voie déclarée existante. Brancher directement le reçu dans l'orchestrateur (et dans `m3_rejouer_estimation`) est un
chantier suivant ; il toucherait le contrat gelé et la charge du registre.

## 6. Preuves

- `departments/m03-estimation/tests/test_estimateurs_service.py` : formule (somme, conversion, soustraction avec
  inversion des bornes, minimum de quantité, temps minimum, `ROUND_HALF_UP`), reçu et sa vérification, tous les refus,
  déclaration du barème (unité, conversion, coefficient, source, doublon, clé inconnue, minimum).
- `departments/m03-estimation/tests/test_outils_estimateurs.py` : vrais outils, SQLite migrée, horloge injectée, lecture
  seule (même reçu au rejeu, aucune écriture), refus (barème inconnu, mesure inconnue, autre lead, grandeur hostile),
  absence de mode/taux, T0 fermé aux appareils.
- Scénario de bout en bout : `departments/m03-estimation/tests/test_estimateurs_bout_en_bout.py` (barème déclaré →
  quatre services et leurs mesures composantes → calcul par service → reçu vérifié → révision d'une mesure → rejeu avec l'ancienne révision → refus
  d'une mesure d'un autre lead).
- Mutations : voir `RAPPORT.md` (mutkit, par fichier, survivants équivalents expliqués).

## 7. Limites

Relecture adverse par un autre modèle (corrigé : verdict d'une capacité de calcul dépassée qui dit quoi réduire, drapeau `minimum_applique` fidèle aux trois bornes, `verifier_recu` qui rend un verdict sur un reçu aux blocs non dictionnaires). Limites assumées, NON corrigées :
- **Prix calculé depuis le coût probable déjà arrondi au cent** (`prix = coût probable arrondi × (1 + taux)`) : sur des cas étroits, l'écart avec « tout calculer exact puis arrondir une fois » est de 1 cent (exemple prouvé : 10,005 × 1,333333 donne 13,35 ici, 13,34 en un seul arrondi). La convention est celle du reçu lisible (le client voit coût et prix cohérents) ; la règle d'arrondi à retenir est à confirmer par la direction et un comptable (CPA).
- **`verifier_recu` ne prouve que la cohérence interne d'un reçu isolé** : un faussaire qui recalcule l'empreinte peut effacer le prix, changer le statut/motifs de revue ou permuter `lead_id`/`service`/`bareme_ref`, car ces champs ne sont confrontés à rien (ni barème, ni registre). L'authenticité vient des registres chaînés, pas de ce vérificateur.


1. **Aucune valeur réelle** : les coefficients, minimums et temps minimums de l'entreprise ne sont pas dans le dépôt.
   Sans déclaration, l'outil refuse et dit quoi déclarer (voulu).
2. **Pas d'écran de saisie** : les estimateurs se déclarent par `m3_declarer_bareme` (appareil admin) ou, plus tard, par
   CFG-1. Aucun écran ne compose les quatre estimateurs.
3. **Pas d'intégration à `m3_estimer_projet`** (section 5) : le prix/plancher/scénarios et le registre des estimations
   restent ceux de la voie mono-mesure.
4. **Une seule ligne d'ouvrage par service** : la composition agrège des quantités dans l'unité de cette ligne. Un
   service qui exige des coûts unitaires distincts par élément (gouttière, descente, coin) demande plusieurs lignes
   d'ouvrage, ce que le registre interdit encore ; c'est un chantier de barème, pas d'estimateur.
5. **Le modèle de perte est celui des lignes de matériau** (`taux_perte`), pas un facteur appliqué à la quantité
   d'ouvrage : un coefficient de perte sur la main-d'œuvre serait une valeur inventée.
6. **Pas de distance, de déplacement, de saison, d'urgence** dans la composition : ces facteurs restent hors périmètre
   (M3-C6, M3.11b).
7. **PostgreSQL non éprouvé** pour ces lectures ; aucune donnée réelle, aucune console, aucun appareil.
8. **Le reçu n'est pas signé** : son empreinte détecte une modification interne, pas une réécriture cohérente des
   registres sources.
