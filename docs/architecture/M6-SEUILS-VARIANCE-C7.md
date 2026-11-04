# M6 — seuils de variance déclarés (C7) et cycle de vie du PO (C4)

Statut (2026-11-03) : **livré et prouvé sur SQLite, avec les vrais outils, registres et bus de M6, des données
fictives et une horloge injectée**. Aucun service externe, aucun paiement, aucun envoi. Les statuts de la matrice M6
restent **PARTIEL** : ce document ne prétend pas terminer le département.

## 1. Le problème

Avant C7, un seul nombre global (`configuration.seuil_variance_chantier_pourcentage`, 0.30) décidait de la revue d'un
écart de matériaux. Une vis de plus et une feuille de revêtement de plus déclenchaient la même revue ; un écart de
0,1 unité sur un article à 2 000 $ valait un écart de 0,1 unité sur une boîte de vis. La valeur ne s'éditait que dans
le manifeste, sans journal de qui l'avait changée.

Avant C4, `invoiced` ne se déduisait pas de M5 : un rapprochement `CONCORDANT` ne produisait qu'une absence d'attente,
et l'admin devait se souvenir de facturer le PO. L'envoi constaté par M1 avait déjà supprimé la seconde approbation
(C2) ; C4 ferme la boucle aval.

## 2. C7 — ce qui est livré

- **Message imposé**, mot pour mot, dans l'attente admin `ecart_materiaux_critique` et dans le résultat de
  `m6_evaluer_variance_chantier` : « Écart matériaux critique — validation admin requise. Causes possibles : erreur
  d'estimation, changement terrain, perte, bris, mauvaise saisie, retour non déclaré ou usage non expliqué. »
  Aucun « vol » n'apparaît dans ce que M6 produit. Une empreinte de test fige le texte.
- **Seuils par matériau et par catégorie** (`seuils_variance.py`) : le seuil du matériau prime, sinon celui de sa
  catégorie **déclarée** (`categories` : matériau → catégorie), sinon le global. Aucune catégorie n'est devinée depuis
  un préfixe de SKU ou le nom du matériau.
- **Deux planchers obligatoires** dans une configuration C7 : quantité minimale et montant minimal en dollars. Un écart
  sous l'un des deux ne déclenche pas la revue, même au-dessus du pourcentage. Le montant est calculé en décimal exact,
  au cent (`ROUND_HALF_UP`), à partir d'une valeur unitaire **fournie** (dernière réception sous le chantier, sinon de
  l'article, sinon livre de prix applicable au jour du WCT). Sans valeur unitaire, le plancher en dollars n'est pas
  évalué : l'écart est marqué critique (`plancher_dollars_non_evalue`) et l'attente de coût de sortie dit quel prix
  déclarer. Jamais un prix inventé.
- **Édition par l'admin avec audit** : l'écran console « Seuils matériaux » (`/seuils-materiaux`) écrit un registre
  append-only et chaîné (`seuils_variance_chantier`) : version, avant/après, auteur, rôle, motif, horodatage,
  approbation, empreinte et empreinte du précédent. Seuls `admin` et `nathan_owner` éditent ; un `manager`, un employé
  ou un agent est refusé. `version_attendue` empêche une mise à jour perdue entre deux admins. Une chaîne retouchée ne
  sert plus AUCUN seuil : la variance sort en `seuil_absent` et une attente dit de reconfigurer.
- **Bandeau de valeur initiale** : tant qu'aucune décision n'est au registre, l'écran affiche « valeur initiale
  proposée par l'architecte, à confirmer ». Une valeur adoptée par un admin est dite « adoptée par un administrateur,
  non confirmée par le propriétaire » ; une valeur adoptée par `nathan_owner` est dite confirmée. Le bandeau ne
  remplace pas une décision : il la situe.
- **Compatibilité** : sans aucune décision C7, le mode `herite` conserve exactement le comportement d'avant (seul le
  seuil global du manifeste / CFG-1 décide, sans plancher). La première décision d'une personne active C7 avec ses
  deux planchers. Aucune valeur réelle n'est proposée dans le manifeste : `0.30` reste la valeur d'agent étiquetée
  « recommandation, non validée ».

Le texte de l'attente ne contient ni montant, ni nom de personne, ni cause attribuée. Le signal interne
`seuils_appliques` (seuil retenu, origine, motif, valeur de l'écart) n'entre pas dans l'événement `m6.variance_chantier`,
dont le schéma fermé est inchangé.

## 3. C4 — ce qui est livré

- **Envoi constaté** : `m1.commande_courriel_envoyee` amène le PO de `email_ready` à `sent_to_supplier` seulement si
  l'empreinte du courriel envoyé est celle du courriel persisté de CE PO et si le texte n'a pas été modifié au sas.
  Rejeu sans second effet ; un constat d'un autre PO ou d'un brouillon modifié laisse l'attente N4 à une personne.
  `m6_marquer_po_envoye` (N4) reste la voie d'un envoi hors M1 (téléphone, portail).
- **`invoiced` proposé** : le dernier état d'une facture M5 `CONCORDANT` sur un PO **reçu** produit une attente N3
  `po_a_facturer` (une par PO, rejeu sans doublon). M6 ne facture pas seul : le PO reste `received` jusqu'à ce qu'un
  humain appelle `m6_changer_statut_po` avec un motif. Un PO partiel, déjà facturé, fermé, contesté ou inconnu ne
  produit aucune proposition ; un verdict `ECART`/`INCOMPLET` garde l'attente « À voir » existante vers M5.
- **`closed` / `disputed`** : outils N3 avec motif, selon `contrats.TRANSITIONS_PO`. Un motif vide ou une transition
  illégale est refusé avant toute écriture. M6 ne paie, ne facture et ne ferme rien seul.

## 4. Fichiers et preuves

| Élément | Fichier |
|---|---|
| Seuils, sélection, planchers, registre d'audit | `departments/m06-material-control/src/m6_material_control/seuils_variance.py` |
| Branchement du signal C7 | `variance_chantier.py`, `outils.py` (`_seuils_variance_effectifs`, `_valeurs_unitaires_variance`) |
| Attente `invoiced` | `rapprochements_recus.py` (`propositions_facturation`), `outils.py` (`_attentes_po_a_facturer`) |
| Écran admin | `src/opsys/console/seuils_materiaux_ui.py`, `pages.py`, `application.py` |
| Tests | `departments/m06-material-control/tests/test_seuils_variance_c7.py`, `departments/m06-material-control/tests/test_cycle_vie_po_c4.py`, `tests/test_console_seuils_m6.py` |

Preuves exécutées : `./t.sh departments/m06-material-control/tests` (2 163 tests), `./t.sh
departments/m06-material-control/tests/test_seuils_variance_c7.py departments/m06-material-control/tests/test_cycle_vie_po_c4.py
tests/test_console_seuils_m6.py` (99 tests), `./ruff.sh`, `./verif.sh`, `./sceller.sh`,
`./docs.sh`, et les gardes `tests/test_paquets_declares.py tests/test_garde_fou_texte.py tests/test_commande_metier.py
tests/test_coherence_documentaire.py tests/test_matrices_exigences.py tests/test_portees_appareil.py`. Les mutations
sont détaillées dans `RAPPORT.md`.

## 5. Limites (sans euphémisme)

- **Prouvé sur SQLite seulement**, avec le client HTTP de test ; aucun navigateur réel, aucun téléphone, aucun écran
  mobile des seuils. PostgreSQL n'a pas été rejoué pour ce chantier.
- **Aucune valeur d'affaires réelle** : les 0.30 / 0.15 existants viennent d'un agent et restent « recommandation, non
  validée ». Les seuils par catégorie/matériau, les planchers et la table `categories` sont vides tant que la direction
  ne les déclare pas. Le système ne propose aucune de ces valeurs.
- **La valeur unitaire du plancher en dollars** vient du coût de sortie (réception ou livre de prix), pas du prix payé
  de la facture. Un article sans réception ni prix au livre rend le plancher « non évalué » et laisse l'écart critique.
- **Aucune variance de coût** : C7 porte sur les quantités ; le pourcentage est celui de la quantité, pas un écart de
  marge. M5 reste le propriétaire du coût réel et de la facture.
- **Le registre d'audit n'a pas d'ancre externe** : une réécriture complète et cohérente de la chaîne par quelqu'un qui
  contrôle la base n'est pas détectable. La chaîne protège contre une retouche partielle, pas contre un administrateur
  de la base.
- **CFG-1 et C7 se superposent** : une fois une décision C7 au registre, elle est autoritaire ; le seuil global adopté
  par CFG-1 n'est plus lu. Il n'existe pas d'écran unique fusionnant les deux journaux.
- **`invoiced` reste une proposition** : aucune politique permanente n'est codée ; rien ne s'applique sans le geste
  N3. Un rapprochement `CONCORDANT` arrivé avant la réception complète ne produit pas de proposition rétroactive tant
  que le PO n'est pas `received`.
- **Le texte de M4** (`m4_field_ops/outils.py`, résumé « écart matériaux CRITIQUE signalé par M6 ») n'a pas été modifié :
  il appartient au propriétaire de M4. L'attente admin de M6 porte bien le message imposé.
- Aucun fournisseur réel, aucun courriel réel, aucune facture réelle ; la boucle M5 est jouée par la charge de son
  événement, pas par un service comptable.

## 6. Décisions qui reviennent à la direction

1. **Valeurs initiales** (Q4) : seuil global, seuils par catégorie (revêtement, soffite/fascia, gouttières,
   consommables…), seuils par matériau et les deux planchers. Aucune n'est proposée ici.
2. **Table des catégories** : quels matériaux appartiennent à quelle catégorie. Sans elle, le seuil par catégorie ne
   s'applique pas ; le seuil par matériau et le global restent disponibles.
3. **Politique de facturation** : C4 propose `invoiced` mais ne l'applique jamais. Une politique permanente (par
   montant, par fournisseur) serait une décision N3/N4 de la direction, non codée.
4. **Confirmation des valeurs** : le bandeau distingue une valeur d'agent, une valeur adoptée par un admin et une
   valeur confirmée par le propriétaire. La direction choisit qui confirme et à quelle fréquence.
