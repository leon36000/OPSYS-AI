# M7 — programme CMO humain durable 30/60/90 jours

**Intégré et qualifié localement par ROOT le 3 octobre 2026. M7 reste PARTIEL.** La campagne passe 181 cas sur huit fichiers complets, sans échec/erreur/skip, en 52,664 s JUnit. Ruff passe sur cinq fichiers modifiés; 671 sources restent stables, sans nouvel OOM ni processus survivant. [Reçu, JUnit, gels et journaux](../../research/REPRISE-2026-10-03/preuves/m7-cmo-session-r2/VERIFICATION-ROOT.json). Les résultats recouvrent les régressions Growth, sans addition aux campagnes précédentes. La qualification de 176 cas [avant correction d’expiration](../../research/REPRISE-2026-10-03/preuves/m7-cmo-durable/VERIFICATION-ROOT.json) reste historique.

La page CMO conserve un programme humain : hypothèse, objectifs, baseline/cible déclarées, responsables internes, capacité déclarée, fenêtres de travail, version, décision et revues. Les fenêtres proviennent du producteur déterministe existant `plan_cmo.projeter`; aucune nouvelle génération de plan, inbox ou orchestration n’est ajoutée.

Un admin ou propriétaire actif propose/révise; seul `nathan_owner` décide. L’auteur, son rôle et l’heure UTC sont établis par le serveur. L’approbation cible **la révision et son empreinte exactes**. Une modification crée une proposition nouvelle, sans reprendre l’approbation antérieure. Le programme approuvé et ses revues restent lisibles après changement d’une source : la lecture ne recalcule ni ne remplace leurs snapshots.

Une décision nouvelle exige projection et références Growth courantes compatibles, sous contrôle des têtes; une source changée demande révision, sans remplacement silencieux de la baseline. Une revue humaine vise une version approuvée, même ancienne, et cite observations/période explicites. L’affectation d’un responsable interne actif ne donne aucun droit ni garantie de disponibilité M4. L’approbation du programme n’autorise aucune publication ou dépense.

## Routes privées

Toutes les routes suivent le préfixe configuré de la console. Les GET privés sont `no-store`; les écritures exigent session active et CSRF.

| Méthode | Route sans préfixe | Usage |
|---|---|---|
| GET | `/marketing/cmo` | Page existante; historique, puis projection/saisie après choix des dates. |
| GET | `/api/marketing/cmo/strategies` | Historique conservé, sans paramètre et sans relecture Growth. |
| GET | `/api/marketing/cmo/strategies/contexte` | Contexte courant avec `date_depart`, `debut`, `fin` explicites. |
| GET | `/marketing/cmo/strategies/{programme_id}/reviser` | Préparer une révision avec ces mêmes paramètres de dates. |
| POST | `/marketing/cmo/strategies` | Conserver une proposition/révision. |
| POST | `/marketing/cmo/strategies/{programme_id}/decisions` | Approuver ou refuser une version exacte. |
| POST | `/marketing/cmo/strategies/{programme_id}/revues` | Conserver une revue humaine sourcée. |

Chaque POST possède son alias JSON sous `/api`, par exemple `/api/marketing/cmo/strategies/{programme_id}/revues`. Les GET plan et rapport d’acquisition existants restent distincts. Aucun outil agent supplémentaire n’est exposé.

## Parcours Synergy fictif vérifié

Une observation fictive déclare **12 demandes d’avis en septembre**, unité `demande`. Nathan fictif propose une cible déclarée de 20, et un livrable de quatre paquets chantier à revoir; un employé fictif porte deux heures de capacité déclarée. Le programme commence le 1er octobre : trois fenêtres jusqu’au 29 décembre. Le propriétaire approuve sa version exacte puis consigne une revue citant une observation déclarée et une conclusion « causalité inconnue ».

Le test HTTP retrouve proposition, baseline, décision et revue après réouverture SQLite. Il ne prouve ni 20 demandes obtenues, ni amélioration, conversion, causalité ou rentabilité. Les données et personnes sont fictives.

## Bornes et portée

Baseline inconnue reste inconnue, jamais zéro. Valeurs, métriques, unités, preuves et confiance demeurent `DECLAREE_NON_VERIFIEE`; la provenance du programme humain ne certifie pas les observations. Une observation legacy V1 conserve son auteur inconnu. Une cible numérique et sa baseline doivent partager métrique/unité littérales; aucun dictionnaire global ni calcul de progrès n’est créé.

Persistance dans le registre interne `m07-marketing/strategies_cmo` de la table canonique `REGISTRES`, sans migration. POST bornés à **32 KiB UTF-8**; registre limité à **1 000 événements, 32 Ki caractères par événement, 1 Mi caractères total**, contrôlés SQL avant décodage. JSON/champs fermés, doublons et profondeur excessive refusés; accès DB/métier POST dans le threadpool. La session doit rester non expirée et les droits DB actifs à la fin de la lecture privée, avant tout rejeu et avant la finalisation de l’écriture. Le rejeu exact rend le reçu après contrôle des droits actuels; exception, CAS ou quota invalide annulent l’écriture transactionnelle.

Saisie HTML simple : un objectif/une action, une observation par revue. API privée : jusqu’à 10 objectifs/30 actions/20 références de revue. Le sélecteur montre explicitement au plus 100 observations; il ne fournit pas d’instantané multipages Growth. Périodes observées : 366 jours inclusifs; horizon de 90 jours sans débordement de date.

Budget LLM : **zéro token** pour cette tranche. Elle ne calcule ni ROI ni valeur financière et ne publie/dépense rien; aucune collecte analytique, apprentissage ou scheduler n’est ajouté. SQLite local seulement dans cette qualification; PostgreSQL, VPS, mobile dédié et sources externes ne sont pas qualifiés. Les hashes locaux ne protègent pas contre un administrateur DB qui modifie et rehash. Le département CMO complet demeure une ambition.

## Propriétaires et preuves

- [Programme durable](../../../departments/m07-marketing/src/m7_marketing/cmo_strategie.py), [commandes privées](../../../src/opsys/console/metier.py), [console](../../../src/opsys/console/marketing_cmo_ui.py).
- [Parcours HTTP et concurrence](../../../tests/test_console_cmo_strategies.py), [bornes SQL et autorité](../../../departments/m07-marketing/tests/test_cmo_strategie.py).
- [Growth humain](M7-GROWTH-SAISIE-HUMAINE-2026-10-03.md) et [matrice M7](M7-MATRICE-CAPACITES-2026-09-30.md).

Les tests refusent notamment source changée sans rebase, mauvais hash/unité, responsabilité cliente, auteur forgé, CSRF invalide, JSON profond, dépassement de date/quota et retrait de rôle avant finalisation. Deux propositions concurrentes sur la même tête ne produisent qu’un append. L’affectation n’accorde aucun accès. Le rouge Ruff initial est conservé; sa correction ROOT combine des contextes sans retirer l’oracle de permission. Trois nouveaux tests ont ensuite prouvé l’acceptation incorrecte d’une session expirée pendant le POST ou avant le rejeu (176 réussis, trois échoués). Après correction, les 179 cas passent. Deux cas supplémentaires vérifient expiration/retrait de rôle pendant la lecture de l’historique : la dernière campagne complète passe 181 cas. Les trois JUnit et leurs gels sont conservés; aucun résultat rouge n’est remplacé.

Restent à construire ou qualifier : automatisation CMO sous permissions, intégration M10, données analytiques externes et financières, capacité terrain M4, interfaces mobiles dédiées et exploitation VPS. Le programme humain durable ne complète pas ces capacités.
