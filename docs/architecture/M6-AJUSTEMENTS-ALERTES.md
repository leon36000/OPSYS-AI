# M6 — ajustements d'inventaire audités (C10) et alertes d'approvisionnement (C9)

Statut (2026-11-03, vague 14) : **PARTIEL, prouvé par exécution sur SQLite avec les vrais outils, les vrais registres
durables et le bus réel, sur des données fictives.** Aucun service externe, aucun paiement, aucune suppression, aucun
nom d'employé dans une sortie.

## 1. Le problème

Deux trous de M6 restaient ouverts après les vagues 12 et 13.

1. **Un écart d'inventaire ne se corrigeait pas.** `m6_soumettre_comptage` calcule un écart
   (`VARIANCE_INVENTAIRE`) et l'écrit comme CONSTAT, sans jamais toucher au stock (DA-M6-09) : après une perte
   physique, le théorique reste supérieur au réel et chaque comptage re-signale le même écart. La fiche C10 demandait
   une écriture d'ajustement décidée par un humain, avec motif typé, avant/après, preuve facultative et seuil
   d'approbation déclaré.
2. **Plusieurs alertes de la fiche M6.13 n'existaient pas** : agrégats répétés par article et par équipe, « commande
   reçue mais stock disparu », rappel de déclaration d'usage manquante, rappel de réception d'un PO au-delà du délai
   habituel du fournisseur. Aucun exécuteur ne les calculait.

## 2. C10 — `m6_ajuster_stock` (N3, agent seulement)

Module pur : `departments/m06-material-control/src/m6_material_control/ajustements.py`.
Outil : `m6_ajuster_stock`, `Autonomie.T1`, `Niveau.N3`, aucun droit d'appareil.

### 2.1 Ce que l'appelant fournit

| Champ | Règle |
|---|---|
| `ajustement_id` | texte non vide ; clé d'idempotence |
| `materiau_id` | texte non vide |
| `motif` | liste **fermée** : `correction`, `stock_retrouve`, `retour_fournisseur`, `erreur_saisie`, `inventaire_physique`, `annulation` ; tout autre code est `REJ-AJUSTEMENT-MOTIF-INVALIDE` |
| `quantite_apres` | quantité **visée** (stock total, ou celui de `emplacement`), nombre fini ≥ 0 ; jamais un écart fourni par l'appelant |
| `preuve` | facultative ; si présente, référence CAS `fichier:sha256:<64 hexadécimaux>` (`REJ-AJUSTEMENT-PREUVE-INVALIDE` sinon) |
| `emplacement` | facultatif ; liste fermée d'`emplacements.py`, référence exigée selon le lieu |
| `horodatage` | texte non vide, fourni par l'appelant (aucune horloge dans le module) |

L'acteur vient de l'identité d'appareil confirmée en base, ou vaut `agent` pour la voie des agents ; ce n'est jamais un
argument.

### 2.2 Ce qui est calculé et écrit

L'écart est `après - avant`, en `Decimal` exact sur le texte canonique. Il est écrit comme mouvement `AJUSTEMENT` :

- `chantier_id` = `*` : un ajustement d'inventaire n'appartient à aucun chantier ; le stock total change, les lectures
  par chantier ne sont pas attribuées ;
- `quantite` = l'écart signé en `Decimal` **exact** (jamais un flottant) ; `cout_unitaire` = `null` ;
- `ajustement` = objet d'audit additionnel (identifiant, matériau, motif, preuve, emplacement, avant, après, écart,
  niveau et motif d'approbation, seuil, acteur, approbateur, horodatage).

`registre.py` n'ajoute cette extension au hash que si la clé `ajustement` est présente ; un maillon antérieur (huit
clés, ou avec `wct_id`/`unite`/`origine_cout`) garde son empreinte à l'octet près. `stock.py` inclut `AJUSTEMENT` dans
le stock théorique ; `conformite.DESIGNATION_TYPE_MOUVEMENT` autorise sa construction dans
`ajustements.construire_mouvement`.

Un ajustement sur un emplacement **nommé** écrit aussi un transfert audité entre ce lieu et `inconnu` (le résidu non
localisé) :
- stock trouvé en plus : `inconnu -> emplacement` ;
- stock manquant : `emplacement -> inconnu`.
Le total change de l'écart, et le lieu nommé porte la quantité corrigée. Le transfert est **VALIDÉ avant la première
écriture** : si `emplacements.construire_transfert` refuse (`REJ-TRANSFERT-STOCK-INSUFFISANT`,
`REJ-TRANSFERT-STOCK-LOCALISE-INCOHERENT`), aucun maillon `AJUSTEMENT` n'est écrit (tout-ou-rien). Un ajustement
**global** (sans emplacement) ne déplace rien : il est refusé par
`REJ-AJUSTEMENT-STOCK-LOCALISE-INCOHERENT` si le stock localisé dépasserait le total visé et rendrait le résidu
`inconnu` négatif. Le verdict dit quoi faire : régulariser d'abord l'emplacement (transfert vers « inconnu »), puis
refaire l'ajustement global. Aucune quantité par emplacement ne devient donc négative.

### 2.3 Seuil d'approbation DÉCLARÉ

`configuration.seuil_ajustement_stock_quantite` (réglage de direction `m6.seuil_ajustement_stock_quantite`, CFG-1) :

- `abs(écart) <= seuil` : N3, l'approbation N3 du département suffit ;
- `abs(écart) > seuil` : N4, il faut l'approbation d'un `admin` ou du `nathan_owner`, vérifiée par
  `approbations.approbateur_en_cours` ; une approbation de `manager` ne suffit pas ;
- seuil **absent ou illisible** : tout ajustement escalade en N4 (`motif_approbation = seuil_absent`) ; aucune valeur
  par défaut.

Le seuil est une **quantité** dans l'unité de l'article, jamais un montant. Aucune valeur n'est proposée par le code.

### 2.4 Idempotence et refus

- Même `ajustement_id` et même demande : le maillon existant est rendu (`deja_enregistre`), rien n'est écrit.
- Même `ajustement_id` avec une autre demande : `REJ-AJUSTEMENT-ID-DEJA-UTILISE`.
- Ajustement localisé dont le transfert est refusé : refus du transfert, **aucun** maillon `AJUSTEMENT`.
- Ajustement global qui rendrait `inconnu` négatif : `REJ-AJUSTEMENT-STOCK-LOCALISE-INCOHERENT`, aucune écriture.
- Écart nul : `aucun_ecart`, aucune écriture.
- Hors transaction durable : `REJ-M6-TRANSACTION-REQUISE`.
- Identité d'appareil non `admin` : `REJ-IDENTITE-APPAREIL-INVALIDE` (même garde que les autres outils de stock).

## 3. C9 — alertes d'approvisionnement

Module pur : `departments/m06-material-control/src/m6_material_control/alertes_approvisionnement.py`.
Exécuteur : le constat planifié existant **`m6.constat.disponibilite`**, qui appelle `m6_constater_disponibilite`
(le même que pour la disponibilité M8). Il reste **inactif par défaut** : aucun admin ne l'a activé, rien ne tourne.
Lecture : `m6_lire_alertes_approvisionnement` (T0/N0, agent seulement) ; les alertes remontent aussi dans
`attentes()` (« À voir »).

### 3.1 Alertes calculées

| Type | Compte | Neutre ? |
|---|---|---|
| `ecarts_repetes_article` | constats `VARIANCE_INVENTAIRE` non nuls par article | article + compte |
| `items_manquants_repetes_article` | `PERTE`/`BRIS` par article | article + compte |
| `items_manquants_repetes_equipe` | `PERTE`/`BRIS` par **équipe déclarée** (identifiant du profil `equipes`) | identifiant d'équipe, jamais un nom |
| `ajustements_frequents_article` | mouvements `AJUSTEMENT` par article | article + compte |
| `commande_recue_stock_disparu` | réception positive **dans la fenêtre** (horodatage du mouvement) et stock théorique ≤ 0 | article, quantités |
| `declaration_usage_manquante` | WCT reçu dans la fenêtre sans aucun mouvement qui le cite | `wct_id`, `intervention_id`, jours |
| `reception_po_en_retard` | PO `sent_to_supplier`, âge **strictement supérieur** au `delai_habituel_jours` du fournisseur | `po_id`, fournisseur, jours |

Aucun prix, aucun coût, aucun texte libre de client, aucune note. Un WCT dont le `technicien_id` n'est pas une équipe
DÉCLARÉE n'est jamais regroupé : il alimente une entrée `non_evaluees` qui demande de déclarer le profil des équipes.
Une quantité illisible (booléen, texte, non fini) n'est **jamais** comptée ni convertie en zéro : le mouvement est
ignoré et la règle dépendante porte une entrée `non_evaluees` (`mouvements.quantite`). Les réceptions sans horodatage
ne peuvent pas être bornées par la fenêtre : elles restent comptées et une entrée `non_evaluees` le dit (horodater les
mouvements de réception) ; les réceptions datées hors fenêtre ne déclenchent rien.

### 3.2 Valeurs déclarées, jamais inventées

- `configuration.alertes_approvisionnement.fenetre_jours` (réglage `m6.alertes_fenetre_jours`, entier 1–365,
  **borne appliquée aussi dans le module pur** : 0, 366, un texte ou un booléen donnent une entrée `non_evaluees`) :
  sans elle, aucune alerte datée n'est évaluée ;
- `configuration.alertes_approvisionnement.seuil_repetition` (réglage `m6.alertes_seuil_repetition`, entier ≥ 2) : sans
  lui, les comptes restent visibles mais aucun verdict de répétition n'est rendu ;
- `delai_habituel_jours` de la fiche fournisseur : sans lui, le PO du fournisseur part en `non_evaluees`.

Toutes les règles non évaluées disent **quelle clé déclarer**. Aucune valeur n'est codée en dur.

### 3.3 Instantané et idempotence

Le constat écrit un maillon dans le registre durable `alertes_approvisionnement` :
`constat_id` déterministe (`m6-alertes-<jour>-<version des données>-<marque de l'instant>`), `alertes`,
`non_evaluees`, `comptes`, `hash_precedent`, `hash_maillon`. Rejouer le même instant ne publie rien de plus ; un autre
instant est un instantané de plus. Le registre est purement interne : **aucun événement de bus n'est ajouté**, donc les
compteurs de l'entrepôt M8 et les tests de constats existants ne changent pas.

Les attentes de l'admin portent une alerte par ligne (20 au plus), plus une attente `alertes_a_configurer` qui liste les
clés manquantes. Rien n'est poussé vers un téléphone ou un courriel.

## 4. Mutations (mutkit, un mutant à la fois)

Chaque balayage a été lancé seul (aucun autre balayage ni test concurrent sur le même fichier), puis les survivants
non équivalents ont reçu un test et ont été rejoués par `mutkit.py run` jusqu'à `KILLED`.

| Fichier | Mutants | Tués | Survivants | Sort des survivants |
|---|---:|---:|---:|---|
| `ajustements.py` | 50 | 49 | 1 | équivalent : `ecart > 0` vs `>=` dans `construire_transfert` ; `ecart == 0` est déjà retourné plus haut (ligne 229), donc la branche ne voit jamais zéro |
| `alertes_approvisionnement.py` | 90 | 88 | 2 | équivalents : `quantite > 0` vs `>= 0` (une réception nulle ne crée qu'une clé à 0, ensuite filtrée par `recus > 0`) et `recus > 0` vs `>= 0` (les clés de `recus` ne viennent que de réceptions strictement positives) |
| `registre.py` | 46 | 46 | 0 | — |
| `outils.py` 554-600 (seuil et réglages C9/C10) | 10 | 10 | 0 | — |
| `outils.py` 1495-1600 (`m6_ajuster_stock`) | 30 | 30 | 0 | — |
| `outils.py` 1597-1690 (outils C9) | 42 | 42 | 0 | — |
| `outils.py` 2513-2545 (`constater_disponibilite`) | 7 | 7 | 0 | — |
| `outils.py` 4703-4745 (`_attentes_alertes`) | 13 | 13 | 0 | — |
| `outils.py` 3546-3600 (déclarations des outils) | 6 | 5 | 1 | hors périmètre : le survivant porte sur `m6_produire_digest` (déclaration préexistante, non transformée) |

`stock.py`, `conformite.py`, `pertes_appareil.py`, `preuves_pertes_bris_appareil.py` et
`reapprovisionnement_appareil.py` ne changent que des ensembles de noms (une entrée `AJUSTEMENT` ou une clé autorisée) :
`mutkit` ne mute pas les chaînes, donc aucun mutant n'y est produit. Le changement de comportement est couvert par les
tests de `stock`, de `registre` et de `conformite`.

## 5. Preuves exécutées

- `departments/m06-material-control/tests/test_ajustements_inventaire.py` : 35 tests (motifs, formes, preuve CAS,
  seuil à la borne, N4 sans/sous approbation admin, idempotence, motif inconnu sans écriture, chaîne antérieure
  inchangée, emplacement, absence de texte libre, hors transaction).
- `departments/m06-material-control/tests/test_alertes_approvisionnement.py` : 41 tests (agrégats, aucune fuite de nom,
  équipe non déclarée, seuil/fenêtre absents, borne, stock disparu, usage manquant, PO à la borne du délai, déterminisme,
  constat inactif, lecture paginée, rejeu).
- Scénario de bout en bout (`test_bout_en_bout_c9_c10.py`, 1 test) : réception → ajustement → constat → alertes →
  attentes, avec les vrais outils, registres et bus.

## 6. Limites (sans euphémisme)

- **La clôture d'un inventaire physique en lot n'existe pas** : l'ajustement se fait article par article. Un comptage
  multi-emplacements n'est pas un seul geste.
- Le rapprochement par emplacement s'appuie sur la chaîne des transferts ; une sortie non localisée antérieure peut
  encore bloquer un ajustement localisé (`REJ-TRANSFERT-STOCK-LOCALISE-INCOHERENT`) ou global
  (`REJ-AJUSTEMENT-STOCK-LOCALISE-INCOHERENT`) tant qu'un humain n'a pas régularisé l'emplacement.
- Le seuil d'ajustement est une **quantité**, pas un montant : aucun plafond en dollars n'est appliqué à un ajustement.
- Le constat C9 ne s'active pas seul ; aucun test ne l'a fait tourner plusieurs jours sur la boucle réelle du serveur.
- Aucune alerte n'est poussée : « À voir » se lit dans l'app ; aucun SMS, courriel ni notification.
- Les agrégats de répétition (`ecarts_repetes_article`, `items_manquants_repetes_*`, `ajustements_frequents_article`)
  ne sont pas fenêtrés mouvement par mouvement. Pour `commande_recue_stock_disparu`, la fenêtre borne les réceptions
  DATÉES ; un maillon de stock sans `horodatage` (forme historique, codec inchangé) ne peut pas être daté, reste compté
  et produit une entrée `non_evaluees` : la règle n'est donc pas entièrement bornée pour les registres antérieurs.
- Aucun test PostgreSQL ni mobile n'a été lancé pour ce chantier ; aucun navigateur réel.
- Les valeurs de fenêtre, de seuil et de délai fournisseur restent à déclarer par la direction ; le code n'en propose
  aucune.
- Avis comptable : tout traitement d'un ajustement comme charge, perte ou avoir relève de M5 et reste **à valider auprès
  d'un comptable (CPA) / professionnel qualifié**.
