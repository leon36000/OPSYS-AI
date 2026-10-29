# M9.19 — gouvernance et validation humaine

Statut : **DONE_VERIFIED** (approbations natives ; aucune extension de droits).
[Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) · [conseil](M9-DEPARTMENT-COUNCIL-AGENTS.md) ·
[exécution et actions](M9-EXECUTION-OKR.md) · [table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Garantir qu'aucune recommandation de la Direction IA ne se transforme en dépense, embauche, prix, dette, contrat ou acte
légal sans la validation de la personne habilitée, et que M9 n'obtienne aucun droit que l'admin n'a pas déjà.

## Pourquoi

Le cahier prévoyait une table `strategic_approval_request`, un courtier MCP et une notification à Nathan. OPSYS-AI a déjà
une file d'approbation native, des rôles relus en base et des niveaux N ; un second circuit de validation créerait un
contournement. M9 classe, propose et constate ; la file native décide.

## État actuel

- **Classes sensibles** (`conseil.ACTIONS_SENSIBLES`, neuf familles) : `depense_reelle`, `budget_marketing`,
  `embauche`, `achat_majeur`, `dette`, `prix_global`, `contrat`, `suppression_donnees` → mandataire « Nathan » ;
  `decision_fiscale_ou_legale` → « Nathan et professionnel ».
- **`conseil.gouverner`** classe chaque action d'une recommandation : famille sensible → `VALIDATION_HUMAINE_REQUISE`
  avec son mandataire ; `suivi_interne` ou `information` → `PROPOSABLE` ; tout autre type → `REFUSEE_TYPE_INCONNU`
  (fail-closed). `effet_autorise` et `autorite_d_effet` valent toujours faux ; `decision_majeure` est vrai dès qu'une
  action est sensible. Entrée invalide : `REJ-GOUVERNANCE-ENTREE`.
- Les étapes sensibles des playbooks utilisent les mêmes familles (vérifié au chargement) ; le cadrage de décision
  (M9.10) reprend les classes sensibles applicables à chaque type de décision.
- **Approbations natives** : une action passe par `opsys.actions_m9` (liste blanche d'outils T1 de niveau N3 au moins)
  et devient une demande `en_attente` ; `approbations.decider` vérifie au point d'effet la personne active, le rôle
  autorisé par la politique du département cible pour ce niveau, puis exécute avec les arguments exacts enregistrés,
  une seule fois.
- **Décision depuis l'appareil du propriétaire** : `m9_decider_demande_approbation` (T1/N2, `roles_appareil` admin)
  délègue à `opsys.approbations_appareil` : la personne authentifiée doit porter `nathan_owner` (un simple `admin` voit
  la file sans arguments), seuls N3 et N4 se décident sur l'appareil, N5 et T3 restent à la console. Aucun paramètre ne
  désigne le décideur. `m9_lister_demandes_approbation` est la lecture correspondante.

## Architecture

**Rôle relu en base, à chaque appel** :

- les outils des modules `outils_*.py` (51 au rapport de livraison ; 52 dans l'arbre de travail du 29 octobre avec
  `m9_reauditer_conseil`, module `outils_reaudit_conseil` en cours d'ajout) appellent `exiger_admin_strict` : identité
  appelante `admin`, source console ou appareil, personne active portant encore le rôle `admin` ; agent ou absence
  d'identité refusés (`REJ-IDENTITE-APPAREIL-INVALIDE`) ;
- les 23 outils historiques d'`outils.py` gardent leur voie d'origine : portée d'appareil `admin` ou fermés aux
  appareils (`m9_etat_consolide`, `m9_valider_rapport_strategique`, `m9_valider_snapshot`), voie agent inchangée
  (`_exiger_admin_pour_appareil`) ; il est donc faux de dire que tout M9 est « admin strict » ;
- le port d'actions refait sa propre vérification (admin via M9, personne active) et le producteur cible revérifie ses
  portées.

**Aucune extension de droits** : aucun outil M9 n'est ouvert à un autre profil que `admin` sur appareil ; aucun outil M9
ne dépasse N3 ni l'autonomie T1 ; aucun ne porte un verbe d'argent, d'envoi ou de suppression.

## Fichiers

[conseil.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/conseil.py) (`gouverner`,
`ACTIONS_SENSIBLES`),
[outils_tissu.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_tissu.py)
(`exiger_admin_strict`), [outils.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils.py)
(outils d'approbation), [actions_m9.py](../../../src/opsys/actions_m9.py),
[approbations_appareil.py](../../../src/opsys/approbations_appareil.py), `src/opsys/approbations.py`.

## Outils et pages de console

| Outil | Accès |
|---|---|
| `m9_lister_demandes_approbation` | T0, admin d'appareil ; arguments visibles du seul propriétaire |
| `m9_decider_demande_approbation` | T1/N2, admin d'appareil ; personne `nathan_owner` ; N3/N4 seulement |
| `m9_proposer_action`, `m9_reconcilier_action` | admin strict (voir M9.17) |

Console : aucune page `/direction` ne décide une approbation ; `/direction/actions` renvoie vers la file native
`/approbations` de la console.

## Données et registres

File `approbations` du socle (demande, niveau, statut, décideur, rôle, résultat) ; journal d'audit natif (dont
`approbation.refus_appareil`) ; registre `actions` de M9 (empreintes et constats seulement).

## Workflows

1. Le conseil recommande ; `gouverner` classe les actions ; la clôture porte le verdict.
2. L'admin propose une action de la liste blanche ; la demande attend.
3. Le propriétaire approuve ou refuse (console, ou appareil pour N3/N4) ; M9 réconcilie et constate.

## Intégrations

Politique de rôles de chaque département cible (`Departement.roles_autorises`), identité (`opsys.identite`), Core pour
la portée d'appareil (`roles_appareil`), M10 pour la trace de décision (M9.20).

## Risques

- Une famille sensible absente de la liste est refusée comme type inconnu : il faut l'ajouter explicitement.
- Dans `tests/test_m9_gouvernance.py`, la dernière assertion de `test_les_outils_de_m9_n_ont_aucun_pouvoir_d_effet_externe`
  (portée d'appareil) se termine par `or True` et ne vérifie rien ; la portée est vérifiée ailleurs
  (`tests/test_m9_contrat_mobile_admin.py`, `tests/test_m9_acces_strict.py`).
- Deux régimes d'identité coexistent : tout nouvel outil doit choisir explicitement le sien.

## Gates Nathan

Toute action de famille sensible ; toute modification de la liste blanche ou des familles ; les décisions N5 à la
console avec attestation professionnelle quand elle s'applique.

## Tests

`tests/test_m9_gouvernance.py` (neuf familles et mandataires, type inconnu refusé, outils sensibles réels hors liste
refusés sans demande créée, outils proposables T1/N3, rôle retiré après la demande → décision refusée, personne
désactivée, double décision refusée) ; `tests/test_m9_acces_strict.py` (garde statique) ;
`departments/m09-strategic-intelligence/tests/test_outils_approbation_appareil.py` ; `test_conseil.py`.

## Statut

DONE_VERIFIED en processus (SQLite, vraies approbations, vrais producteurs M2/M4/M10).

## Prochaines étapes

1. Remplacer l'assertion tautologique par une vérification réelle de la portée d'appareil.
2. Faire relire par Nathan la liste des familles sensibles et leurs mandataires.
