# Plan de raccord — dossier préparatoire de décision CFO M5.16

Date initiale : 2026-09-30; actualisé le 2026-10-01. La première tranche M5.16 est raccordée; ce document décrit son contrat réel et ses limites. Cela ne certifie ni M5 complet, ni conseil fiscal, ni données d’entreprise réelles.

Le dossier vérifie maintenant les trois chaînes financières avant calcul, avec refus backend et
console des altérations SQL. Après intégration des [droits CFO des profils](M5-PROFILS-AGENTS-DROITS.md),
une suite complète FinanceCore a historiquement passé 2 028 tests (preuve après droits, avant M5.10.a).
La vérification intégrée actuelle passe 2 037 tests M5 et 34 tests du socle, soit 2 071 dans une même
commande, sans échec, erreur ni skip, en 134,333 s; elle contrôle 1 029 sources sélectionnées identiques
avant/après. Les nombres 2 028 et 2 071 décrivent des arbres et portées distincts et ne s'additionnent
pas. Le dossier peut être préparé par un profil M5 doté d'un droit humain révocable et d'un ticket
privé lié aux arguments; les autorisations humaines existantes sont conservées. Cette extension est
limitée à SQLite et aux données de l'instance; elle n'ajoute aucune autorité N4/N5. Les preuves
historiques ci-dessous restent distinctes de ce raccord du 1er octobre.

## Décision de conception livrée

La première tranche livre `m5_preparer_dossier_decision_cfo`, un **outil T0 en lecture seule qui assemble un dossier factuel de décision à partir d’un instantané canonique**. Il présente les 25 rubriques avec leur statut et les faits disponibles. Il réutilise les calculs et vues déjà produits par FinanceCore; il ne crée pas un second moteur de trésorerie, de prévision ou de financement.

M5 possède le rapport CFO structuré et peut assembler les faits, leurs limites et les rubriques stratégiques prescrites. Dans la première tranche, une recommandation, une confiance ou une projection qui ne découle pas d’une règle et de données suffisantes reste `INCONNU`; le contrat laisse évoluer ces rubriques lorsque des sources justifiées arrivent. Le dossier n’approuve rien et ne déclenche aucune action. Un décideur humain et le CPA/fiscaliste/prêteur valident les points qui relèvent de leur rôle.

La directive courante transmet le prompt exact des 25 rubriques ci-dessous et le déclare prioritaire sur les anciens documents. Le prompt retransmis n’est pas une preuve d’identité authentifiée; le dossier ne doit pas enregistrer de revendication d’identité en provenance de ce texte. Le [PRD BMAD M5 §0](../../../departments/m05-financecore/docs/bmad/02-PRD-PM.md) est maintenant réconcilié : M5 est propriétaire du rapport et M9 le consomme; le forecast v1 historique est distingué du moteur hebdomadaire courant. Recommandation et confiance restent inconnues tant qu’une source et un calcul déterministes ne les justifient pas; aucun score n’est inventé.

## État du socle pertinent

| Besoin | Source réutilisable | État constaté et limite |
|---|---|---|
| Solde, argent disponible, cash libre, réserves | `outils._lectures_finance`, `_resultat_cash_libre`, `cash_libre.calculer_cash_libre`, `cash_libre.vue_cash_libre`; outil `m5_etat_tresorerie` | Le cash libre porte `cash_libre_id`, composantes, provenance, fraîcheur, réserves, hypothèses et manques. Le solde vient du registre plat de mouvements; aucune connexion bancaire ni réconciliation bancaire n’est présente. Paies, DAS et dettes peuvent être des déclarations du propriétaire; elles ne sont pas un calcul de paie. |
| Comptes à recevoir | `facturation.comptes_a_recevoir`; outil `m5_lire_comptes_a_recevoir` | Vue des factures actuellement `ENVOYEE`, montants et âges lorsque `aujourd_hui` est fourni. Une facture envoyée n’est pas une preuve de paiement futur; aucune échéance contractuelle client n’est stockée. |
| Comptes à payer et engagements fournisseurs | `comptes_a_payer.resume_a_payer`, `comptes_a_payer.lister`; outil `m5_lister_comptes_a_payer` | Les reçus M6, attentes PO, factures saisies et corrections append-only permettent des totaux/rapprochements proposés. Le rapprochement fournisseur n’est pas un rapprochement bancaire. Le registre M5 ne constate pas les paiements fournisseurs; les totaux sont donc à afficher avec leur portée et leurs manques. |
| Devis acceptés et contrats | `devis_recus`, événements canoniques M3; agrégat conservé dans la forme historique sans échéancier de `m5_preparer_decision_capital` | Avec l'extension de scénario capital, la réponse compacte omet le contexte détaillé AR/AP/devis sous la limite de sortie. Un devis accepté n’est pas un contrat signé; aucune preuve de dépôts/jalons contractuels n’est présente. Le dossier CFO en 25 rubriques reste un autre outil et n'infère pas de carnet contractuel ou de revenu futur. |
| Cédule et flux datés | `prevision.assembler`, `_page_prevision`, `m5_prevoir_tresorerie`; `m5_lire_calendrier_obligations` | Prévision déterministe des seuls flux connus et datés, de 1 à 26 semaines, selon les délais et dates explicitement configurés. Ce n’est pas une projection de ventes, de capacité ni une cédule signée. Les données inconnues bloquent les semaines concernées; le solde est observé à la fin de la semaine. |
| Calendrier fiscal/obligations | `calendrier_fiscal.prochaines_echeances`, `calendrier_obligations.lire_obligations_documentees` | TPS/TVQ versionnées pour 2025–2026, validation CPA `A_VALIDER`; l’année absente est refusée. Paies/DAS/dettes ont des obligations déclarées, sans moteur de paie. Les métadonnées RQ ont été repérées, mais les téléchargements directs ont répondu HTTP 403 dans les preuves R16 : ne pas certifier une règle RQ depuis cette recherche. |
| Scénarios de capital | `decision_capital.preparer`; outil distinct `m5_preparer_decision_capital` | Extension M5.10.a facultative : jusqu'à huit sorties datées et sourcées par option, plus une couverture jusqu'à l'horizon (1–26 semaines) déclarée manuellement. Le prix comptant, la mise de fonds et chaque montant de paiement cité sont rapprochés; aucun calendrier, taux, taxe, intérêt ou frais n'est créé. La projection compacte réutilise le solde du registre et les flux connus du même snapshot, donc les obligations n'y sont comptées qu'une fois et le cash libre n'est pas re-soustrait. Elle rapporte le solde final et le minimum des soldes de fin de semaine, pas le creux intra-semaine. Source/couverture manquante ou écart non rapproché : aucun solde chiffré pour l'option. Ce n'est ni une VAN/TRI/DSCR ni une garantie d'abordabilité. |

Références détaillées : [audit M5 fiscalité/paie/calendrier](M5-CFO-IA-FISCALITE-PAIE-STRATEGIE-AUDIT.md), [recherche R16 M5](../../research/R16-2026-09-30/recherche-m5.md), [preuves R16 M5](../../research/R16-2026-09-30/m5-preuves.json). Les interfaces principales sont dans [`outils.py`](../../../departments/m05-financecore/src/m5_financecore/outils.py), [`cash_libre.py`](../../../departments/m05-financecore/src/m5_financecore/cash_libre.py), [`prevision.py`](../../../departments/m05-financecore/src/m5_financecore/prevision.py), [`comptes_a_payer.py`](../../../departments/m05-financecore/src/m5_financecore/comptes_a_payer.py), [`facturation.py`](../../../departments/m05-financecore/src/m5_financecore/facturation.py) et [`decision_capital.py`](../../../departments/m05-financecore/src/m5_financecore/decision_capital.py).

## Contrat et interface raccordés

L’outil de lecture M5 `m5_preparer_dossier_decision_cfo` ne crée aucun registre ni table. Il accepte seulement les paramètres de cadrage; il ne reçoit aucun montant, identité, rôle, solde, facture, contrat ni réserve en entrée. Il assemble tous les champs à partir d’un snapshot canonique unique.

```text
m5_preparer_dossier_decision_cfo(
    aujourd_hui: date ISO obligatoire,
    question_posee: texte obligatoire, 1..1000 caractères
)
```

`question_posee` est fournie par l’appelant et affichée comme mandat; elle ne devient pas une donnée financière ni une identité vérifiée. Un texte retransmis ne prouve pas qui l’a posé. En console, `metier.executer` fournit la date du serveur. Aucun montant, rôle ou droit de coût n’est accepté dans l’appel. La personne et l’autorisation de lire les coûts viennent de l’identité confirmée par les gardes M5.

Réponse M5.16 :

```json
{
  "type": "DOSSIER_DECISION_CFO",
  "version_contrat": "v1",
  "question_posee": "texte fourni",
  "reference": {
    "aujourd_hui": "AAAA-MM-JJ",
    "devise": "CAD",
    "snapshot_id": "empreinte déterministe des sources financières lues"
  },
  "statut_global": "PREPARATOIRE",
  "rubriques": [
    {
      "numero": 5,
      "titre": "Données utilisées",
      "statut": "CONNU | PARTIEL | INCONNU",
      "contenu": null,
      "source_refs": {
        "colonnes": ["departement", "registre", "taille", "tete"],
        "lignes": [["m05-financecore", "factures", 3, "identifiant complet"]]
      }
    }
  ],
  "mention": "Analyse préparatoire…"
}
```

Le contrat fermé est décrit dans [dossier_decision_cfo.v1.yaml](../../../departments/m05-financecore/contracts/dossier_decision_cfo.v1.yaml). Les faits monétaires restent des textes décimaux CAD, jamais des nombres flottants. Chaque rubrique apparaît exactement une fois dans l’ordre prescrit; son statut est `CONNU`, `PARTIEL` ou `INCONNU`. Un manque structurel est centralisé à la rubrique 6; un statut inconnu n’est jamais zéro. Recommandation et confiance restent inconnues sans calcul déterministe justifiable. Les références exactes sont centralisées à la rubrique 5; `snapshot_id` scelle les têtes complètes, `cash_libre_id`, `prevision_id`, la configuration et la date. La question apparaît dans le dossier, mais ne fait pas partie de l’identité du snapshot. Aucune donnée de contact ou ligne confidentielle n’est incluse.

Le dossier est dérivé et non stocké : `snapshot_id` identifie les sources financières de cette lecture, pas la question ou une décision signée. Les 25 rubriques sont présentes dans une réponse compacte sous le budget M5; aucune troncature silencieuse. Un test passe par `Capacites` avec question de 1 000 caractères, configuration, 13 semaines, plusieurs factures clients, une facture fournisseur, une réserve et des têtes complètes, sans troncature sous 6 000 caractères. Les contrôles exécutés prouvent le refus d’accès avant lecture après révocation et le refus des trois chaînes altérées avant calcul. Les empreintes non signées ne protègent pas contre une réécriture cohérente de toute la chaîne par un opérateur SQL privilégié.

Le dossier `m5_preparer_dossier_decision_cfo` en 25 rubriques et le comparateur `m5_preparer_decision_capital` sont deux outils et deux contrats distincts. Le nouveau champ d'échéancier du comparateur est optionnel : son omission préserve la forme de réponse antérieure; sa présence produit une projection capital compacte et omet alors le contexte détaillé AR/AP/devis de cette réponse. La borne de sortie est mesurée après assemblage : si les projections dépassent le budget, leurs soldes passent à `NON_CALCULABLE`; le rapport est ensuite mesuré de nouveau et refusé s'il reste trop volumineux. Ni ce scénario ni le dossier CFO ne complètent à eux seuls les rubriques stratégiques manquantes.

### Rubriques officielles M5.16 et couverture initiale

La liste exacte transmise par la directive actuelle remplace le canevas R16. Le premier raccord rendra toutes les rubriques; les inconnues restent visibles et motivées au lieu d’être omises.

| Nº | Rubrique exacte | Couverture du premier raccord |
|---:|---|---|
| 1 | Question posée | Connue comme texte de l’appel; aucune attribution d’identité tirée de ce texte. |
| 2 | Résumé exécutif | Partiel; résumé mécanique des faits et manques uniquement. |
| 3 | Recommandation | Inconnue tant qu’aucune règle/calcul justifiable ne produit un choix. |
| 4 | Niveau de confiance | Inconnu; aucun score heuristique. |
| 5 | Données utilisées | Connu avec sources canoniques, date, devise et empreintes disponibles. |
| 6 | Données manquantes | Connue à partir des verdicts et manques des services source. |
| 7 | Hypothèses | Résumés des hypothèses cash libre; provenance détaillée demeure avec les composantes de trésorerie. |
| 8 | Scénario prudent | Inconnu jusqu’à un moteur versionné et ses hypothèses explicites. |
| 9 | Scénario normal | Inconnu; aucune moyenne ou situation « normale » supposée. |
| 10 | Scénario optimiste | Inconnu; aucune croissance ou vente supposée. |
| 11 | Cashflow 13 semaines | Partiel : prévision canonique hebdomadaire connue/datée (1–26 semaines), pas une série journalière; configuration absente est un manque. |
| 12 | Projection 6 mois | Partielle seulement si la prévision hebdomadaire couvre la période et reste calculable; sinon inconnue. |
| 13 | Projection 12 mois | Inconnue dans ce raccord; horizon hebdomadaire actuel au plus 26 semaines. |
| 14 | Projection 24 mois | Inconnue; aucun moteur de cet horizon. |
| 15 | Impact taxes | Partiel : composante TPS/TVQ observée, calendrier à valider; aucun avis fiscal ou projection fiscale. |
| 16 | Impact paie | Partiel pour les montants paies/DAS déclarés, pas pour un calcul de paie, retenues ou cotisations. |
| 17 | Impact dette | Partiel pour le montant déclaré; échéanciers et covenants contractuels inconnus. |
| 18 | Impact marge | Inconnu dans ce raccord; aucun effet futur d’une décision n’est calculé. |
| 19 | Impact croissance | Inconnu; pas de causalité ni de pipeline probabilisé établis par les faits financiers M5. |
| 20 | Risques principaux | Partiel seulement si un déficit de cash libre est constaté; pas de score de risque. |
| 21 | Conditions avant d’agir | Inconnu dans ce raccord; aucune action financière engagée. |
| 22 | Questions CPA/fiscaliste | Inconnu dans ce raccord; les mentions de validation CPA restent à la rubrique 25 et aux faits fiscaux. |
| 23 | Questions banque/prêteur | Inconnues tant qu’offre, covenant ou termes du prêteur ne sont pas présents. |
| 24 | Plan d’action recommandé | Inconnu; aucune action stratégique n’est recommandée. |
| 25 | Validation requise | Partielle : gardes N3–N5 et validations CPA sont visibles; les validations propres à la décision dépendent du mandat et des sources. |

## Réutilisation technique à privilégier

1. Authentifier/autoriser avant la première lecture, comme `m5_etat_tresorerie`; l’admin confirmé est accepté depuis l’appareil ou la console, le propriétaire confirmé depuis la console. Aucun rôle ou droit n’est accepté en argument.
2. Charger une fois le manifeste et les registres `principal`, `factures` et `comptes_a_payer`. Réutiliser `_lectures_finance()`, `_resultat_cash_libre()`, `facturation.comptes_a_recevoir()`, le résumé AP et le moteur de prévision existant. Ce dossier ne lit pas le registre des devis/contrats.
3. Pour éviter qu’un rapport montre deux instantanés différents, `_page_prevision()` accepte les `lectures` déjà capturées. Le rapport CFO les transmet au moteur canonique au lieu de relire les registres.
4. Garder les formules dans les modules purs actuels (`cash_libre.py`, `prevision.py`, `comptes_a_payer.py`, `decision_capital.py`). Ne pas reconstruire AR/AP/cash ou appliquer des calculs de marge dans le nouveau wrapper. Les fonctions existantes qui bloquent sur une donnée indispensable restent la source de leur verdict.
5. Le rapport est borné sous le budget sortie existant de `jetons`; `snapshot_id` est déterministe et les références exactes du snapshot restent dans la réponse. Le code refuse si le document complet dépasse le budget. Il ne publie rien et n’écrit aux registres de mouvements, constats, factures, AP, approbations ou mémoire.

## Vérification et limites de couverture

Les sept tests CFO ajoutés dans `departments/m05-financecore/tests/test_dossier_decision_cfo.py` ont été exécutés ciblés. Ils couvrent le contrat et les 25 rubriques, les sources vides sans mutation, le retrait live du rôle avant lecture, l’appel agent sans identité, la question de 1 000 caractères avec empreinte source/configuration (la question reste hors empreinte), l’horizon 13 semaines indépendant de flux postérieurs et un appel réel via `Capacites` avec cash/réserve, AR/AP, 13 semaines, têtes exactes et absence de troncature sous 6 000 caractères. Le test connu compare le cash et la projection aux outils canoniques. Ces tests sont faits avec stockage SQLite isolé et données explicitement fictives.

Les suites source préexistantes sont `departments/m05-financecore/tests/test_cash_libre_outils.py`, `test_prevision_outils.py`, `test_comptes_a_recevoir.py`, `test_comptes_a_payer_outils.py` et `test_calendrier_obligations.py`. Elles restent la preuve des services sous-jacents; elles ne sont pas revendiquées ici comme couvertures CFO ou comme exécutées dans le run ciblé.

### Validation intégrée de cette tranche

Le raccord console est monté dans l’application réelle et sa suite combinée CFO/finance/voicemail/M1/socle a réussi **69 tests, 0 échec, 0 erreur, 0 skip, en 27,141 s**. Le JUnit source est conservé hors dépôt dans `/workspace/restructuration-opsys-2026-09-30/preuves/m5-cfo-console-combine-final.xml` (SHA-256 `c9ac41c96efa459345c4fdc9eb2296e2a900fe86fb7d48867c3d5b781d1d634b`). La capture de sources a été prise après exécution seulement; elle ne prétend pas être une empreinte avant. Le compte-rendu de capture est `/workspace/restructuration-opsys-2026-09-30/preuves/m5-cfo-console-combine-final.json`. Le test de console CFO valide notamment un snapshot connu avec ses dates et montants rendus depuis la réponse outil. Cette suite combine plusieurs portées et n’est pas additionnée à la suite FinanceCore.

Après correction d’une allowlist de test devenue obsolète (ajout du nom du nouvel outil T0 admin dans le set attendu, sans changement de garde ou de rôle), la suite complète `departments/m05-financecore/tests` a réussi **2 022 tests, 0 échec, 0 erreur, 0 skip, en 114,358 s**. Le JUnit est conservé hors dépôt dans `/workspace/restructuration-opsys-2026-09-30/preuves/m5-financecore-cfo-green-20260930T230753Z.xml`; le log et le manifeste sont `m5-financecore-cfo-green-20260930T230753Z.log` et `m5-financecore-cfo-green-20260930T230753Z-run.json` dans le même dossier. Les empreintes avant/après couvrent 351 fichiers M05 et `src/opsys`, sans chemin modifié pendant l’exécution. Le run rouge antérieur est conservé pour la traçabilité : 2 022 tests, avec un seul échec dans `test_l_outil_ne_declare_que_l_admin_comme_role_d_appareil`, dû à cette allowlist exacte qui omettait le nouvel outil; le run vert suit uniquement sa mise à jour.

Couverture future avant de déclarer M5.16 complet : vérification explicite de la branche RQ `A_VALIDER`; devis accepté sans preuve de contrat, puisque ce rapport ne lit pas le registre de devis; désactivation complète du compte humain en plus du retrait de rôle; et qualification approfondie des rubriques stratégiques qui restent inconnues ou partielles. L’intégrité des trois chaînes corrompues est désormais contrôlée dans le dossier CFO. La première tranche ne prétend pas calculer un effet fiscal/de paie/dette attribuable à la question : les rubriques 15–17 montrent uniquement les composantes observées/déclarées avec leurs manques. Le prototype de scénario capital ne constitue pas une paie calculée, une projection 12/24 mois, une lecture de contrat signé, une analyse de DSCR ou une preuve d'abordabilité complète.

## Hors tranche et critères de fin

Cette tranche ne crée pas de comptabilité en partie double, de banque connectée/rapprochée, de paie, de moteur fiscal RQ, de contrat signé, de probabilités de vente, de simulation de cinq ans, de VAN/TRI/DSCR, de conseil CPA, d’écriture ou de mémoire M10. Ces besoins restent distincts et requièrent leurs propres sources, validations et frontières humaines.

Le raccord backend et le montage UI de cette tranche sont vérifiés par les suites ci-dessus. M5.16 reste un dossier préparatoire à couverture partielle : les sources absentes limitent les conclusions financières, et les validations humaines ainsi que les lacunes nommées restent requises avant toute décision.

## Consolidation du 3 octobre 2026 : faits déclarés et publication de la console

Le calendrier d'obligations est capturé dans le même contexte de lecture financier.
La rubrique 16 conserve paies/DAS déclarées, montants utilisables, statuts, échéances,
périodes, sources et versions dans un format compact fermé. La console restitue
ces faits en français. Une source périmée ou une déclaration incomplète n'est pas
un montant exploitable; `null` ne devient jamais zéro. Le mode sans calendrier
conserve l'objet déclaratif historique. Ce raccord n'est ni un moteur de paie,
ni une déclaration, ni une exécution officielle.

Le rapport garde ses 25 rubriques et son budget de 5 700 caractères dans le
périmètre testé, y compris 13 semaines et une question de 1 000 caractères.
La console refuse une rubrique malformée, des nombres non finis ou une structure
incomplète. Elle revalide la session et le rôle après la lecture et avant toute
publication; le retrait réel d'un rôle pendant la requête HTTP produit 403.

Preuves actuelles : 38 cas natifs CFO/calendrier/grants passent sur SQLite; la
campagne de console/Fusion AP/PDF en contient ces 38 et passe 162 cas uniques.
Un cas PostgreSQL de synthèse reste explicitement hors de cette campagne.
Ruff passe sur les 12 fichiers concernés. Les comptes historiques ci-dessus
restent ceux de leurs propres exécutions, pas une qualification globale actuelle.
Voir le [bilan de reprise](../../programme/REPRISE-BILAN-R32-R42-2026-10-02.md)
pour les reçus exacts, préimages, corrections, limites et reprises rouges.
