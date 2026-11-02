# Moteur de recalcul du coût certifié (SQLite) et son activation (E4, E6, E5/E8, D3)

Étape E2 de la conception « routage en production du coût certifié M4 → M5 ». Code : `src/opsys/moteur_recalcul_m4.py`.
Tests : `tests/test_moteur_recalcul_m4_e2.py`.

## Ce que c'est, ce que ce n'est pas

- C'est **un seul moteur de recalcul** dérivé de la couture QA `service_recalcul_m4._executer_qa`, avec les gardes
  qui manquaient à une exécution hors des tests. Il réutilise la portée, la capacité, l'attestation v2 et
  l'historique de `service_recalcul_m4` ; il ne les copie pas.
- Il **n'est branché nulle part** : aucune route, aucun outil MCP, aucun rôle d'appareil, aucun droit, aucune
  politique créée, aucune migration. `service_recalcul_m4.ouvrir` et `service_lecture_m4.ouvrir` restent fermés
  (`*_NON_QUALIFIE`) ; un test le vérifie, ainsi qu'à l'aide d'un import isolé qu'aucun point d'entrée ne charge le
  moteur.
- `_executer_qa` est **inchangée** : les tests e2e et de cascade qui l'appellent gardent leurs attentes. Elle sera
  remplacée par le moteur quand `ouvrir` sera qualifié (E6), pas avant.

## Signature et statuts

```python
recalculer(cnx, session, *, acteur, wct_id, devis_id, intention_id)
```

| Statut rendu | Sens | Écritures |
|---|---|---|
| `publiee` | trace, reçu v2, attestation, audits, intention, résultat et événement `m5.rentabilite_chantier` écrits ensemble | dans le savepoint de l'appelant |
| `deja_executee` | même intention, mêmes paramètres : relecture de l'historique | aucune |
| `rien_a_faire` | autre intention, mais l'état certifié est déjà à jour (même version d'entrées) | **aucune nette** : les audits d'usage de la vérification sont annulés avec le savepoint |

Tout autre cas lève `RefusRecalculM4` (sous-classe de `RefusAutorite`, attribut `code` parmi `CODES`) ; le savepoint est
annulé, la transaction de l'appelant reste utilisable.

## Gardes ajoutées par E2

| Garde | Code de refus | Où |
|---|---|---|
| Moteur autre que SQLite et PostgreSQL | `BACKEND_NON_QUALIFIE` (ex-`BACKEND_NON_SQLITE` : PostgreSQL est désormais qualifié, vague 6) | première vérification, sans aucun accès à la base |
| Exclusion d'écriture VÉRIFIÉE, comme `service_lecture_m4` : SQLite, `BEGIN IMMEDIATE` (écouteur `begin` de l'engine) ; PostgreSQL, verrou consultatif d'instance détenu par la session (`pg_locks`), cf. `opsys.stockage.exclusion` | `VERROU_ECRITURE_ABSENT` | à l'entrée et à chaque `_verifier` de la portée |
| Acteur et intention en paramètres, validés strictement ; l'acteur doit être l'utilisateur de la session admin | `ACTEUR_INVALIDE`, `INTENTION_INVALIDE`, `IDENTIFIANT_INVALIDE` | avant tout accès |
| Politique `m4.recalculer_v3` **et** `m4.verifier_v3` : absente, révoquée, expirée | `POLITIQUE_ABSENTE`, `POLITIQUE_REVOQUEE`, `POLITIQUE_EXPIREE` (nomme l'opération) | avant tout savepoint |
| Revue finale du chantier en attente | `REVUE_EN_ATTENTE` | à la première projection M4 |
| Équipe pointée non établie (pas de preuve typée V3) | `EQUIPE_INCONNUE` | idem |
| Historique des tarifs d'équipe illisible | `TARIFS_ILLISIBLES` | lecture seule avant savepoint |
| Aucun tarif ne couvre la date de la visite | `TARIF_ABSENT` | après l'écriture de la trace, dans le savepoint, puis annulation |
| Reçu WCT M5 sans `empreinte_charge` | `WCT_SANS_EMPREINTE` | lecture seule avant savepoint |
| WCT d'avant le modèle de visites | `WCT_ANTERIEUR_MODELE_VISITES` | refus du producteur M4 |
| Autre refus du producteur M4 | `SOURCE_M4_REFUSEE` | idem |
| Même intention, autres paramètres | `INTENTION_EN_CONFLIT` | |

Règle produit : une déclaration d'équipe n'est pas une présence individuelle ; un historique sans équipe établie reste
inconnu ; aucune attribution supposée, aucun coût estimé. Le moteur refuse plutôt que de publier un partiel sous
provenance certifiée.

## Activation (décisions D1, D2, D3, D5 de DECISIONS-ARCHITECTE-r1)

Les sections ci-dessus décrivent le moteur tel que livré en E2 ; il est désormais branché.

| Étape | Code | Ce qui est activé |
|---|---|---|
| E4 / D1 | `src/opsys/service_politiques.py`, console `/administration/politiques-service` (`console/politiques_service_ui.py`), migration `0036` | Octroi, renouvellement, révocation des trois politiques (`m4.verifier_v3`, `m4.recalculer_v3`, `m4.relire_faits_pour_m5_v1`) par un admin actif relu en base, CSRF ; jamais par un agent (MCP, département, appareil refusés). Expiration exacte à 90 jours, renouvellement sans cumul, révocation immédiate (révision inactive + audit), journal append-only `service_politiques_journal`. |
| D2 | `src/opsys/service_acteur_systeme.py` | Acteur système `opsys-systeme` : jeton non fabricable hors du réconciliateur, lié à son fil, refusé sous MCP / identité d'appel / livraison du bus ; aucune personne en base ; une personne nommée `opsys-systeme` est refusée par le moteur. |
| E6 | `service_recalcul_m4.ouvrir`, `service_lecture_m4.ouvrir` / `ouvrir_appareil` | Les portes publiques délèguent au moteur qualifié (session console admin) ; refus typé sans politique, sur un moteur non qualifié, sans exclusion d'écriture. Les coutures QA `_executer_qa`, `_ouvrir_qa`, `_ouvrir_appareil_qa` sont retirées. Route console à la demande : `POST /crm/lead/{lead}/soumissions/{devis}/couts-travaux/recalcul-certifie` (CSRF, aucun champ métier). |
| E5 / E8 | `src/opsys/evenements/reconciliateur_cout_certifie.py`, appelé à la fin de `repartiteur.repartir` | Réconciliateur piloté par l'état, lot borné, intention déterministe, une transaction BEGIN IMMEDIATE par candidat. `OPSYS_COUT_CERTIFIE_RECONCILIATEUR` = `ombre` (défaut, zéro écriture) / `actif` / `inactif` (valeur inconnue = inactif). Journal `cout_certifie_reconciliations` en mode actif. |
| D3 | `m5_financecore.outils._vue_cout_certifie`, console « Coûts des travaux » | `m5_lire_rentabilite_chantier` et la console exposent `cout_certifie.statut` = `a_jour` / `perime_recalcul_en_attente` / `inconnu` et la dernière trace certifiée (montants masqués sans droit de voir les coûts). |

Pour activer en production (SQLite) : un admin octroie `m4.verifier_v3` et `m4.recalculer_v3` depuis la console ;
le réconciliateur tourne d'abord en `ombre` (journal « aurait publié ») ; passer `OPSYS_COUT_CERTIFIE_RECONCILIATEUR=actif`
pour qu'il publie. **PostgreSQL (vague 6, `docs/qualification/QUALIFICATION-POSTGRESQL.md` §16)** : le moteur, la relecture courante, l'historique, les politiques et l'acteur système tournent sur PostgreSQL 17 réel ; l'exclusion d'écriture est un verrou consultatif d'instance (sérialise les portées de la famille, pas les écrivains M3/M4/M5 ordinaires : le protocole optimiste des services — relecture identique avant et après — porte le reste) ; la verticale d'affaire complète (HTTP MCP, bus, recalcul certifié) passe sur les deux moteurs.

### Décisions r5

- **Publication certifiée découplée de la livraison** (`service_capability.publication_isolee`) : la voie V1 de la
  livraison du WCT publie dans son propre point de sauvegarde. Un échec n'annule que la publication ; le reçu WCT,
  la facture brouillon et la trace ordinaire restent, la livraison est `traite` sans réessai ni quarantaine. Le
  reçu du bus porte `service_m4 = echec_publication` et un code typé (`TARIFS_ILLISIBLES`, `AUTORITE_PERDUE`,
  `SOURCE_INVALIDE`, `ECHEC_PUBLICATION`) ; M5 marque le devis « à recalculer » (trace PARTIELLE
  `REJ-COUT-CERTIFIE-A-RECALCULER`, mécanisme E1, persistante jusqu'au prochain certifié) ; D3 dit
  `perime_recalcul_en_attente` ; le réconciliateur reprend hors livraison.
- **Correction purement M4 après certification = périmé** : après toute écriture M4 (signature des registres M4),
  le réconciliateur rejoue le moteur qualifié pour chaque certifié `a_jour` dans un point de sauvegarde toujours
  annulé et compare ce que la projection M4 actuelle CHIFFRE (`port_service_m4.signature_main_d_oeuvre` : statut,
  minutes, taux, coût, lignes par visite et équipe, manques — sans les empreintes de provenance, qui changent à
  chaque écriture M4) à la dernière trace certifiée. Différent, ou plus certifiable (équipe inconnue, revue en
  attente, visite non relisible...) : marque E1 puis recalcul ; identique : rien n'est écrit. Choisi plutôt qu'un
  événement M4 consommé par la cascade : M4 ne publie pas ces corrections (et relève d'un autre chantier), et M5 ne
  peut pas relire une projection hors portée de service ; le réconciliateur a déjà l'autorité (politiques + acteur
  système) et réutilise exactement l'état E1 que D3 affiche.

### Limites connues

- Mode `ombre` : la correction M4 et l'échec de publication sont constatés et journalisés, rien n'est marqué ; D3
  ne montre le périmé qu'en mode `actif` (ou par la marque écrite en livraison, qui ne dépend pas du mode).
- Coût de la relecture M4 : un moteur rejoué (annulé) par certifié à jour après chaque écriture M4, borné à 5 par
  tour et mémorisé par signature ; à mesurer sur une instance à fort volume.
- Aucune surface ne permet aujourd'hui de corriger des pointages V3 après fermeture de visite (`VISITE-INACTIVE`) :
  le test positif de correction M4 injecte la correction au producteur M4 ; la surface E3 relève d'un autre chantier.
- Mémoire de convergence par processus : deux processus restent sérialisés par SQLite ; une exécution concurrente
  rend `a_jour` ou `deja_executee`, jamais une seconde écriture.
