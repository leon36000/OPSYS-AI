# `m1.plaintes_structurees` : la lecture des plaintes de M1 (contrat v1)

Fiche courte. Contrat champ par champ : [`contracts/m1-plaintes-structurees.v1.yaml`](../contracts/m1-plaintes-structurees.v1.yaml)
(un test le compare à la sortie réelle). Code : `plaintes_structurees.py` (pur) et `m1_lire_plaintes_structurees` (outil).

## Ce que c'est, et ce que ce n'est pas

- **Une lecture, pas un événement du bus.** Les consommateurs de plaintes (M9, conseil stratégique) lisent par outil, à une
  date choisie ; un événement ne sait pas dire « rien reçu » ni se relire un autre jour. `evenements.publie` de M1 est
  inchangé (`m1.lead_qualifie`, `m1.retrait_consentement`) ; aucun type n'est ajouté au catalogue.
- **T0/N0, admin confirmé** (même garde que `m1_produire_digest`), aucune écriture, aucun événement, **aucun rôle
  d'appareil** (`roles_appareil` vide : fermé à tout appareil). L'ouvrir à un lecteur (liste blanche des lectures de M9)
  est une décision du socle, non prise ici.
- Arguments : `date_reference` (AAAA-MM-JJ, le jour de la lecture, inclus ; M1 n'a aucune horloge) et `jours` (1 à 92,
  défaut 7). Réponse : `{"accepte": true, "resultat": {...}}`, refus : `REJ-DIGEST-DATE-INVALIDE`,
  `REJ-PLAINTES-PERIODE-INVALIDE`, `REJ-IDENTITE-APPAREIL-INVALIDE`.

## Une absence n'est pas un zéro : l'état

| `etat` | Sens | `comptes.declarees` |
|---|---|---|
| `CONNUE` | au moins une plainte ou urgence (transfert) au registre pour la période | le nombre |
| `AUCUNE_DECLAREE_PAR_SOURCE` | vocabulaire des plaintes configuré, des signaux au registre, aucune plainte reconnue ni escaladée. **Pas** « aucune plainte » | 0 (déclarées, pas réelles) |
| `NON_BRANCHEE` | M1 ne peut pas se prononcer : vocabulaire à configurer (`VOCABULAIRE_A_CONFIGURER`), profil invalide (`PROFIL_INVALIDE`) ou aucun signal reçu jusqu'à la date (`AUCUN_SIGNAL_AU_REGISTRE`) | `null`, et tous les comptes `null` |

Un compte `null` veut dire **inconnu** (jamais 0), y compris pour une catégorie sans vocabulaire et sans plainte.
`limites` (constantes) rappelle que seules les plaintes reconnues ou escaladées sont comptées.

## Par plainte

`plainte_id` (pseudonyme `pl-<20 hex>` à sens unique dérivé du transfert), `type` (`plainte|urgence`), `categories`
(ensemble fermé, vide pour une escalade de l'agent sans catégorie), `gravite` (**toujours `null`** : aucune source ne la
déclare à M1), `date_survenance` et `recue_le` (réception par M1, pas le fait reproché), `lue_le` (jour de lecture),
`source` (canal), `declenchee_par` (`regles|agent`), `statut` (`ouvert|clos` tel qu'à la fin du jour lu) et `close_le`.

## Révision : détecter les contradictions

`revision.empreinte_contenu` couvre l'état, la période, les plaintes et les comptes. Deux lectures de la même
(`lecture.date_lecture`, `periode`) avec des empreintes différentes sont **contradictoires** : à signaler, jamais à
fusionner ni à moyenner (chaque lecture garde sa propre vérité). La même empreinte avec un autre `registre_tete` n'est
qu'un rafraîchissement. `registre_sequence`, `registre_tete`, `registre_dernier_horodatage` (comparé comme instant)
situent la lecture dans le registre append-only.

## Loi 25

Aucun contact, `conversation_id`, `transfert_id`, `lead_id`, texte du client, résumé (libre quand l'agent le fournit) ni
terme du vocabulaire. Toute chaîne de la sortie est un instant, une date, un pseudonyme ou une valeur d'un ensemble
fermé (une valeur hors ensemble devient `inconnue` ou est écartée) : un texte libre, injection comprise, n'a aucun
chemin jusqu'à la sortie. Le pseudonyme ne permet pas de compter les clients distincts (limite assumée).

## Limites connues

Vocabulaire lu à l'appel, pas à la date de référence ; jour civil tel qu'écrit dans l'horodatage de la plateforme (comme
le digest) ; un client qui écrit d'un autre numéro est un autre correspondant ; aucune plainte hors des canaux de M1
(appel vocal non transcrit, réseaux sociaux, avis) ; « branché » signifie « des signaux sont au registre », pas « les
canaux sont sains ».
