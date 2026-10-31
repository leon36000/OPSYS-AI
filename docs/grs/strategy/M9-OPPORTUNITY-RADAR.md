# M9.13 — radar d'occasions

Statut : **DONE_VERIFIED** (aucun revenu, gain ni probabilité produit ou accepté).
[Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) · [radar de risques](M9-RISK-RADAR.md) ·
[table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Rassembler les occasions d'affaires que Nathan ou le conseil déclarent, et celles qu'un propriétaire mesure déjà, avec
leurs conditions, leurs alternatives et ce qui manque pour les documenter — sans jamais promettre un revenu.

## Pourquoi

Un « revenu probable » calculé par M9 serait un chiffre sans source. Une occasion reste une hypothèse tant que son coût et
la capacité nécessaire ne sont pas des faits cités ; même documentée, elle reste une proposition soumise à un humain.

## État actuel

`occasions.py` (version `2026-10-28.1`) :

- **Occasions déclarées** (au plus `MAX_OCCASIONS` = 30) : champs `id`, `libelle`, `origine` obligatoires ;
  `conditions`, `alternatives`, `cout_ref`, `capacite_ref`, `signaux_refs` facultatifs. Origines admises :
  `DECLAREE_PAR_LA_PERSONNE`, `PROPOSITION_CONSEIL_NON_VALIDEE`, `SIGNAL_MESURE`.
- **Sources** : `cout_ref`, `capacite_ref` et `signaux_refs` sont des adresses de faits citables du dossier stratégique
  (`dossier_strategique.construire`) ; une adresse absente des faits est refusée (`REJ-OCCASION-REF`). Le texte cité est
  rendu à côté de la référence.
- **Statut** : `DOCUMENTEE` si coût **et** capacité sont cités, sinon `HYPOTHESE` avec `manques` nommés. `mesurable`
  vaut vrai seulement si un signal est cité. `confiance` vaut toujours `NON_ESTIMEE`, `decision` toujours
  `HUMAINE_REQUISE`.
- **Interdits** : une clé `revenu(s)`, `gain(s)`, `marge`, `chiffre_affaires`, `probabilite(s)`, `roi` ou
  `date_realisation` est refusée (`REJ-OCCASION-REVENU`) ; un champ hors liste ou mal formé : `REJ-OCCASION-CHAMP`.
- **Signal mesuré** (`signaux_mesures`) : un seul aujourd'hui, `relancer_devis_sans_reponse`, tiré de la dernière capture
  complète et non contradictoire de `m8.vue_executive` (chemin `resultat.entonnoir.devis_en_attente.sans_reponse.devis`) ;
  il rend le nombre de devis et au plus 20 identifiants, statut `HYPOTHESE`, manques `cout` et `capacite`, aucun taux de
  conversion.

## Architecture

`evaluer(occasions, faits, captures, connaissance)` valide chaque occasion, refuse les doublons d'identifiant, ajoute les
signaux mesurés et rend `RADAR_OCCASIONS` avec `radar_id` (empreinte du contenu, rejouable) et deux limites écrites.
L'outil construit les faits citables à `reference` / `connaissance` puis appelle `evaluer` ; rien n'est écrit.

## Fichiers

[occasions.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/occasions.py),
[outils_radars.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_radars.py),
`dossier_strategique.py` (faits citables), `capture_strategique.py`.

## Outils et pages de console

| Outil | Accès |
|---|---|
| `m9_radar_occasions` (`reference`, `connaissance`, `occasions_declarees`) | admin strict, T0/N0, sortie bornée |

Aucune page de console dédiée n'est livrée : le radar d'occasions n'apparaît ni dans la barre `/direction` ni dans un
panneau du tableau de bord. Il se lit par l'outil (agent refusé : admin authentifié seulement).

## Données et registres

Lecture de `captures_strategiques` (chaîne vérifiée, `REJ-CAPTURE-CHAINE-INVALIDE`). Les occasions déclarées ne sont
**pas** conservées : elles sont passées à chaque appel. Aucun registre d'occasions n'existe (table du cahier
`strategic_opportunity` remplacée par un calcul à la demande, voir l'audit §4).

## Workflows

1. Capturer `m8.vue_executive` (et les lectures qui portent coût ou capacité, si un producteur les expose).
2. Appeler `m9_radar_occasions` avec les occasions déclarées et leurs références.
3. Une occasion documentée peut nourrir un cadrage de décision ou un playbook ; la décision reste humaine.

## Intégrations

M8 (`m8.vue_executive`) pour le seul signal mesuré ; tous les faits du dossier stratégique pour les références ;
`evaluation.py` utilise `occasions` dans la catégorie d'abstention du corpus (M9.23).

## Risques

- Aucun producteur n'expose aujourd'hui un coût de relance ni une capacité de vente : le signal M8 reste une hypothèse.
- Les occasions déclarées sont la parole de la personne ; M9 vérifie leurs références, pas leur pertinence.
- Absence de page : l'occasion n'est visible que par l'outil.

## Gates Nathan

Décider quelles occasions déclarer et, pour une occasion documentée, toute dépense ou engagement qui en découle.

## Tests

`departments/m09-strategic-intelligence/tests/test_occasions.py` (hypothèse sans coût ni capacité, occasion documentée
toujours décidée par un humain, clés de revenu refusées, références inconnues refusées, doublons et borne, signal devis
sans taux, identifiant déterministe) ; `tests/test_m9_radars_integre.py` (outil réel : hypothèse, aucune clé de revenu,
`REJ-OCCASION-REVENU`, refus non-admin et agent).

## Statut

DONE_VERIFIED pour ce qui est livré (déclarations sourcées et signal M8) ; pas de page de console.

## Prochaines étapes

1. Ajouter un signal mesuré seulement quand un propriétaire publie la mesure (coût, capacité, demande).
2. Si Nathan le demande, un panneau en lecture seule dans `/direction`, avec les mêmes interdits.
