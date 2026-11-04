# M1 — Transfert enrichi, statut client borné et métriques de réception (vague 14)

Statut : **PARTIEL, prouvé sur SQLite avec des données fictives**. Trois chantiers de la fiche M1-E/G/H de
`docs/reprise/PROMPTS-NATHAN-ANCIENS/ANALYSE-M1.md` §4. Aucune valeur d'affaires réelle, aucun service externe, aucun
envoi : M1 prépare et lit, une personne décide.

## 1. M1-E — Le transfert dit ce qui manque et ce qu'il reste à faire

`transferts.preparer_ouverture` calcule deux champs, à partir de la MÊME lecture de qualification que le lead :

- `informations_manquantes` : `{"statut": "evaluee" | "partielle", "champs": [...], "non_evalues": [...], "motif": ...}`.
  `service`, `ville` et `contact` sont les trois seuls champs que M1 sait établir ; un profil d'entreprise incomplet
  (zone ou services absents) ne fait pas croire à un manque : il met `service`/`ville` dans `non_evalues` avec le motif
  `diagnostic_indisponible`. Le contact absent, lui, reste un vrai manque.
- `prochaine_action` : `{"code", "detail", "champs"}` avec un code d'ensemble fermé (`demander_informations`,
  `traiter_la_plainte`, `traiter_l_urgence`, `prendre_en_charge`, `verifier_le_dossier`,
  `decision_humaine_apres_retrait`). Un client retiré (STOP) ne reçoit aucune relance ; une urgence passe avant une
  plainte ; un champ non évalué commande de vérifier le dossier.

Ces champs sont sur la ligne `transfert/ouvert` (append-only) et dans `m1_lire_transfert`.

**Deux événements minimaux**, publiés dans la transaction du registre :

| Type | Quand | Charge |
|---|---|---|
| `m1.transfert_ouvert` | tout transfert ouvert | `evenement_id`, `transfert_id`, `conversation_id` (pseudonyme), `lead_id` ou null, `type_transfert`, `categories`, `niveau`, `canal`, `declenche_par`, `horodatage` |
| `m1.plainte_ouverte` | plainte ou urgence | même charge, `type_transfert` limité à `plainte`/`urgence` |

Jamais de contact, de texte, de résumé, de terme du vocabulaire ni de montant. `evenement_id` déterministe
(`m1-transfert-ouvert-<transfert_id>`, `m1-plainte-ouverte-<transfert_id>`) : un rejeu est un no-op. Le schéma est
**gelé après cette livraison** : M2 (tâche de suivi) et M10 (fait d'affaire) le consomment tel quel.

**M10-02 avant cette vague** : M10 ne consommait de M1 que `m1.lead_qualifie` (`departments/m10-memoire/department.yaml`
et `etapes.py`). Il ne touchait ni transfert ni plainte. Les deux nouveaux types sont donc neufs pour lui.

## 2. M1-G — Statut client borné, après identité, par quatre lectures T0 privées

`m1_statut_client(verification_id, sujet, horodatage, reference=None, facture_id=None)` :

1. la vérification est rejouée depuis `verifications_identite` ; sans état `verifie`, ou sans le niveau de la finalité
   (`statut_dossier` : `general` ; `facturation` : `sensible`), **aucune lecture n'est faite** et la réponse est le repli
   exact « Je vais vérifier avec l'équipe. » ;
2. le lead vient des lignes `lead_emis` de la conversation vérifiée. Aucun `lead_id`, `client_id` ou `devis_id` n'est
   accepté de l'appelant ;
3. le port privé `lecteur_statut_client` (`Capacites._lecteur_statut_client`) n'ouvre que quatre lectures T0/N0 déjà
   existantes, dans le contexte de M1 : `m2_trouver_client_de_lead`, `m2_obtenir_client_360`, `m3_lire_devis`,
   `m4_lister_interventions`, `m5_lire_plan_facturation`. Un outil hors liste, un autre contexte ou un niveau non T0/N0
   est refusé ;
4. le statut brut est traduit par la table fermée de `statut_client.py` et rendu par le gabarit fixe `statut_client`
   (aucun texte libre, aucun montant, aucune date d'exécution). Un statut inconnu rend le repli, jamais le code brut.

**Sujets et références** : `dossier` (aucune référence), `soumission` (`devis_id`), `visite` (`intervention_id`),
`facture` (`devis_id`, `facture_id` facultatif : identifiant ou numéro de facture). Une référence mal formée est un
refus (`REJ-M1-STATUT-REFERENCE-INVALIDE`), pas un repli.

**Matrice d'abus** (tests `test_statut_client_outils.py` et `test_m1_statut_client_e2e.py`) : identité non vérifiée ou
expirée ; niveau `probable`/`general` pour une facture ; lead absent ou ambigu ; référence d'un autre lead ; référence
inconnue ; statut brut inconnu ; référence avec saut de ligne, espace, chemin ou balise ; port absent ; outil hors
liste ; contexte hors M1. Tous rendent le même repli (ou le refus de forme), sans révéler l'existence d'un dossier.

**Limites** : M5 n'expose pas de lecture d'une facture par son seul `facture_id` ; une facture se lit donc par le
`devis_id` qui la porte (`facture_id` filtre ensuite le jalon). M4 est lu par la liste paginée des interventions
(50 par page, 10 pages au plus) : une visite au-delà n'est pas retrouvée et rend le repli. Aucun test avec un vrai
client, un vrai devis ou une vraie facture ; aucun écran client ; la liaison `facture_id` au dossier client n'est pas
prouvée au-delà du lead.

## 3. M1-H — Métriques de réception, avec des « non évaluées » explicites

`m1_constater_reception(date_reference, jours=7)` publie `m1.reception_constatee` (M8) et rend le même objet. Chaque
métrique porte un état `CALCULEE` ou `NON_EVALUEE` :

| Métrique | Source | Absence |
|---|---|---|
| `delai_premiere_prise_en_charge_s` | ouverture d'un transfert -> première ligne `prise_en_charge` ou `clos` ; médiane, maximum, échantillon, `en_attente` | `AUCUN_TRANSFERT`, `AUCUNE_PRISE_EN_CHARGE` |
| `appels_manques_rappeles_pct` | lignes `appel_importe` (manque/voicemail) et tentative `tentative_sans_contact` ou clôture `contact_reussi` ; ratio au centième (ROUND_HALF_UP) | `AUCUN_APPEL_MANQUE` |
| `leads_par_service`, `leads_par_ville` | lignes `lead_emis` de la période, groupées | `AUCUN_SIGNAL` (une période avec signaux et sans lead donne un vrai zéro) |
| `hors_zone` | non tracée : la ville refusée n'est pas conservée | toujours `NON_EVALUEE` |
| `photos_recues_pct` | non tracée : M1 ne reçoit pas de pièces (M1-L non livré) | toujours `NON_EVALUEE` |

`evenement_id` déterministe (`m1-reception-<date>-<jours>-<empreinte[:16]>`) : rejouer le même registre ne publie rien de
plus. Aucun contact, aucun texte, aucun `lead_id`, aucune conversation dans la charge ; les villes et les services sont
des agrégats. La « raison de perte » reste à M2 : M1 ne la fabrique pas.

**Non planifié** : le constat n'est pas déclaré dans `constats_planifies` de M1 parce que le socle dérive l'intervalle
d'une mesure du catalogue fermé de M8 (`cadence_constats`) et qu'aucune mesure de réception n'y existe. L'agent M8 doit
d'abord déclarer la mesure ; jusque-là, le constat s'appelle à la demande (agent) et publie au bus.

## 4. Décisions qui reviennent à la direction

- **Objectif de délai de première prise en charge** et **cible d'appels manqués rappelés** : aucune valeur, aucun seuil
  ici (CFG-1). Le constat mesure, il ne juge pas.
- **Niveau d'identité exigé par sujet** : `statut_dossier` = `general`, `facturation` = `sensible`, comme la machine
  d'états existante. Élargir ou restreindre est une décision de politique, pas un réglage de code.
- **Ce que M1 peut dire d'une facture** : seulement son statut. Montant, échéance, PDF et relance restent hors du
  gabarit ; une personne les donne si la direction le décide.
- **Mesure M8 de réception** : nom, fenêtre et cadence à déclarer par l'agent M8 avant tout branchement planifié.
