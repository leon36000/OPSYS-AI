# Le cash libre rafraîchi par le planificateur (chantier C1 de l'analyse M8)

État au 2 novembre 2026, base `e0424b040`. Branche `claude/m8-cash-libre-planifiable`. Aucune migration.

## 1. Le constat de départ

`m5_constater_cash_libre` fait constater le cash libre réel du jour et le publie au bus (`m5.cash_libre_constate`). Il était
scellé **N3** au registre MCP, alors que ses trois sœurs `m5_constater_*` (`mesures_comptables`, `depense_publicitaire`,
`factures_emises`) sont **N2**. Le planificateur durable refuse tout outil N3 (`REJ-PLAN-NIVEAU-INTERDIT`) et le contrôle de
cohérence des constats planifiés (`constats.problemes`) exige en plus un outil d'agent SANS droit d'appareil. Le cash libre n'était
donc jamais rafraîchi seul. Quatre mesures de M8 en dépendent (`m8_cash_libre_cad`, `m8_solde_tresorerie_cad`,
`m8_comptes_a_payer_cad`, `m8_taxes_a_remettre_cad`), ainsi que la composante « finance » du score de santé (un seul indicateur :
le cash libre).

## 2. Pourquoi l'outil est N3 : ce qui a été trouvé

Lu : le code de l'outil, l'ADR-0009 §4, l'historique (`git log -S`), le registre scellé, les tests qui épinglent le niveau.

| Question | Constat |
|---|---|
| D'où vient le N3 ? | Du **défaut** : l'outil est déclaré `Autonomie.T1` sans `niveau=`, et la correspondance par défaut T1 -> N3 s'applique (`opsys.outils._NIVEAU_PAR_DEFAUT`). Le commentaire d'origine le dit : « T1 -> N3 (par défaut) ». Les trois sœurs ont été écrites le 1er novembre 2026 (commits `f2d44f1bd`, `50b047071`) avec `niveau=Niveau.N2` posé à la main ; l'outil du 29 septembre (`5648adb05`) n'a pas été revu. Le registre MCP (révision 1, `2b3f061ab`) a scellé l'existant. |
| Est-ce un risque réel d'effet externe ? | **Non.** Il calcule une valeur dérivée (le même calcul que `m5_etat_tresorerie`), écrit UNE trace au registre dérivé `constats_cash_libre` et publie UN événement interne dans la même transaction. Aucun mouvement, aucune facture, aucun paiement, aucune remise, aucune écriture au grand livre, aucune sortie externe (garde statique `conformite.verifier_aucun_decaissement`, tests). Les montants du bus sont de la même nature que ceux des sœurs (créances, facturation). |
| Est-ce alors une simple incohérence ? | **Pas seulement.** Le message du commit d'origine pose un choix : « un T1 est une écriture interne : validée au départ par l'humain qui agit (l'admin sur son téléphone), en file d'approbation pour un agent en mode `ombre` ». C'est la définition ADR-0009 du N3 (« modification interne non finale, validation humaine au départ »). Trois tests épinglent ce comportement (`test_constat_cash_libre_outils.py` : l'agent en `ombre` attend, le propriétaire approuve, la demande refusée ne publie rien). |
| Ce que le N3 encadre vraiment | (1) L'outil **rend les montants** (cash libre, solde, composantes, lecture en phrase) à celui qui l'appelle, et exige pour cela le droit de voir les coûts. (2) Il accepte une **identité d'appareil** (l'admin sur son téléphone, `roles_appareil = {admin}`, écran « Chiffres » du mobile admin). (3) Un **agent** qui veut publier un chiffre de trésorerie attend une décision humaine. |

Conclusion : le niveau reflète un choix de gouvernance (documenté et testé), pas un risque d'écriture comptable ou de sortie
externe ; mais le défaut a aussi été reconduit sans revue lors de l'écriture des sœurs.

## 3. Décision : le niveau N3 est conservé, une variante N2 est ajoutée

**Abaisser `m5_constater_cash_libre` à N2 n'aurait pas suffi.** Le planificateur ne peut déclarer qu'un outil sans droit d'appareil
(`constats.problemes` : « agent seulement »). Il aurait fallu soit retirer le droit d'appareil de l'admin (casse l'écran mobile),
soit affaiblir la garde du planificateur qui interdit les droits d'appareil sur un outil déclenché par l'identité système
(élargit ce qu'un outil planifié peut faire). Le brief interdit d'élargir un droit d'appareil. Abaisser aurait de plus retiré sans
raison la file d'approbation d'un agent, que trois tests épinglent.

**Alternative retenue : séparer le calcul et l'écriture partagés de l'action N3 sensible.**

| | `m5_constater_cash_libre` (inchangé) | `m5_constater_cash_libre_planifie` (nouveau) |
|---|---|---|
| Niveau, autonomie | N3, T1 | **N2**, T1 |
| Droit d'appareil | `admin` | **aucun** |
| Qui | l'admin (téléphone) ; un agent via la file d'approbation | **le planificateur durable seulement** (`service_acteur_systeme.planificateur_en_cours`) |
| Arguments | `aujourd_hui`, `role`, `autorise_couts` | `aujourd_hui` seulement (aucun droit écrit par l'appelant) |
| Réponse | les montants, la lecture, les réserves | l'en-tête, le statut, les **codes** de ce qui manque ; aucun montant |
| Écriture | `_constater_cash_libre` | **le même code** : même registre de constats, même rang, même règle « un constat par jour et par version » |

`planificateur_en_cours()` (nouveau, `src/opsys/service_acteur_systeme.py`) est la garde de `verifier_planificateur` rendue en
booléen : acteur système opaque de portée `planificateur`, non fermé, du fil courant, hors requête HTTP/MCP et hors identité d'appel.
Un N2 est automatique pour un agent : sans cette garde, la variante serait une porte dérobée autour du N3. Elle est refusée
(`REJ-CONSTAT-PLANIFICATEUR-SEULEMENT`) pour un agent, un appareil admin, le transport MCP, un département appelant et l'acteur
système du réconciliateur, **avant** la lecture de tout registre. La validation humaine n'est plus « au départ de chaque appel » :
c'est l'activation du constat par un admin (ombre, puis actif, motif, expiration de 90 jours, console serveur, rôle relu en base).

Ce qui n'est pas changé : le niveau, les droits d'appareil, les paramètres et la description de `m5_constater_cash_libre` (donc
son empreinte au registre scellé). **Si Nathan préfère l'uniformité** (N2 pour les quatre), c'est possible plus tard : l'effet serait
seulement qu'un agent en `ombre` pourrait publier sans file ; la variante rend ce geste inutile pour le rafraîchissement.

## 4. Le constat planifié

Bloc `constats_planifies` du manifeste de M5 (modèle : PLANIFICATION.md §9) : `cash-libre`, outil `m5_constater_cash_libre_planifie`,
mesures `[m8_cash_libre_cad, m8_solde_tresorerie_cad, m8_comptes_a_payer_cad, m8_taxes_a_remettre_cad]`, un appel
`aujourd_hui: {calcul: jour}`. Exécuteur `m5.constat.cash-libre`, famille « constats », N2, **inactif par défaut**.

- **Cadence dérivée, jamais recopiée** (`m8_analytics.cadence_constats`) : fenêtre de fraîcheur du catalogue (86 400 s pour ces
  quatre mesures) / 2 passages = **12 h**. Un test relit les définitions de M8 et exige que les mesures déclarées soient exactement
  celles dont la source de données nomme `m5.cash_libre_constate`.
- **Ombre** : l'exécuteur vérifie que l'outil existe et est N0 à N2, calcule les arguments du créneau et journalise « aurait ».
  Il n'appelle rien : aucune trace, aucun événement.
- **Idempotence par créneau** : l'argument est le jour local du CRÉNEAU, jamais l'horloge. Deux déclenchements du même créneau,
  ou du même jour sans changement de données, trouvent le dernier constat (`deja_constate`) : rien n'est publié. Un nouveau jour
  ou une donnée qui change publie un constat au rang suivant.
- **Panne de M5** : un défaut de l'outil est compté (`REJ-PLAN-DEFAUT-EXECUTEUR`), visible à la console Connecteurs, et n'arrête
  ni les autres constats ni le tour.
- Le journal du planificateur ne contient aucun montant ni texte du propriétaire (liste blanche de détails).

### Re-scellement du registre MCP

`opsys-metier registre-mcp verifier` refuse d'abord (`INCONNU m5_constater_cash_libre_planifie`) ; `sceller --par claude-m8-cash-libre`
écrit la **révision 14 : 1 ajouté, 0 modifié, 0 niveau changé, 0 retiré** (637 outils exposés). Diff attendu : un nouvel outil
avec son empreinte, aucun changement d'empreinte pour `m5_constater_cash_libre` (son niveau n'a pas bougé). Si l'architecte décide
plus tard d'abaisser l'outil N3, ce sera un `niveaux_changes` et une nouvelle révision.

## 5. Liste de contrôle d'activation (propriétaire)

1. Déclarer dans `configuration` de M5 ce que seul le propriétaire sait : cycle fiscal (`fiscal`), paies, DAS et dettes
   (`obligations_declarees`). Sans eux, le constat est publié « non calculable, manque X » et M8 le dit, jamais un zéro.
2. Console Connecteurs : passer `m5.constat.cash-libre` en **ombre**, lire le journal « aurait » ; puis **actif**.
3. Pour la composante « finance » du score de santé : déclarer les bornes de `m8_cash_libre_cad` (`configuration.sante.bornes` de M8,
   décision du propriétaire, jamais inventée).
4. Pour supprimer l'intervalle périmé du soir (voir §6) : déclarer `fraicheur_mesures_s: 172800` pour les quatre mesures et
   régler l'intervalle du constat à un jour à l'activation.

## 6. Ce qui est prouvé, et ce qui ne l'est pas

Prouvé (SQLite, horloge injectée, données fictives, vrais outils, vrai bus, M8 réel, console réelle) : voir
`departments/m05-financecore/tests/test_constat_cash_libre_planifie.py` (la variante sur le vrai socle) et
`tests/test_cash_libre_planifie_m8.py` (de bout en bout : rien par défaut ni en ombre, quatre mesures aux valeurs calculées à la main
du cas de référence, 27 861,98 $ de cash libre, composante finance du score, idempotence par créneau, jour local en soirée, panne
de M5, non calculable publié tel quel, étanchéité avec l'outil N3).

**Non prouvé, sans euphémisme :**
- PostgreSQL : rien n'a tourné dessus (aucune table nouvelle ; les outils et le planificateur ne sont pas qualifiés là).
- La boucle réelle du serveur sur plusieurs jours ; les jours de changement d'heure ne sont éprouvés que par le calcul du créneau
  existant.
- **Fraîcheur du soir.** M8 date un constat de M5 du **début du jour de référence en UTC** et la fenêtre du catalogue est de 24 h ;
  le constat change de jour à minuit LOCAL (UTC-5 en novembre). Les quatre mesures sont donc à jour en journée et **périmées de
  19 h à minuit, heure locale**, même quand tous les passages réussissent (caractérisé par un test, pas souhaité). Le remède sans
  toucher au code est la fenêtre de 48 h déclarée par le propriétaire (prouvée, §5.4). Ne pas changer le catalogue de M8 ici est un
  choix de périmètre ; la décision de fond (dater le constat du jour local ?) appartient à l'architecte.
- Aucune activation réelle chez le client ; aucun relevé bancaire réel ; les chiffres fiscaux sont ceux du manifeste de test.
- Analyse préparatoire : À valider auprès d'un comptable (CPA) / professionnel qualifié.
