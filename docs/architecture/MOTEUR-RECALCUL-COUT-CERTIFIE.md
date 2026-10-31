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
| PostgreSQL | `BACKEND_NON_SQLITE` | première vérification, sans aucun accès à la base |
| Verrou d'écriture `BEGIN IMMEDIATE` (écouteur `begin` de l'engine), comme `service_lecture_m4` | `VERROU_ECRITURE_ABSENT` | à l'entrée et à chaque `_verifier` de la portée |
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
| E6 | `service_recalcul_m4.ouvrir`, `service_lecture_m4.ouvrir` / `ouvrir_appareil` | Les portes publiques délèguent au moteur qualifié (session console admin) ; refus typé sans politique, sur PostgreSQL, sans verrou. Les coutures QA `_executer_qa`, `_ouvrir_qa`, `_ouvrir_appareil_qa` sont retirées. Route console à la demande : `POST /crm/lead/{lead}/soumissions/{devis}/couts-travaux/recalcul-certifie` (CSRF, aucun champ métier). |
| E5 / E8 | `src/opsys/evenements/reconciliateur_cout_certifie.py`, appelé à la fin de `repartiteur.repartir` | Réconciliateur piloté par l'état, lot borné, intention déterministe, une transaction BEGIN IMMEDIATE par candidat. `OPSYS_COUT_CERTIFIE_RECONCILIATEUR` = `ombre` (défaut, zéro écriture) / `actif` / `inactif` (valeur inconnue = inactif). Journal `cout_certifie_reconciliations` en mode actif. |
| D3 | `m5_financecore.outils._vue_cout_certifie`, console « Coûts des travaux » | `m5_lire_rentabilite_chantier` et la console exposent `cout_certifie.statut` = `a_jour` / `perime_recalcul_en_attente` / `inconnu` et la dernière trace certifiée (montants masqués sans droit de voir les coûts). |

Pour activer en production (SQLite) : un admin octroie `m4.verifier_v3` et `m4.recalculer_v3` depuis la console ;
le réconciliateur tourne d'abord en `ombre` (journal « aurait publié ») ; passer `OPSYS_COUT_CERTIFIE_RECONCILIATEUR=actif`
pour qu'il publie. PostgreSQL reste refusé (D5).

### Limites connues

- Octroyer `m4.verifier_v3` active aussi la voie V1 **à la livraison** du WCT (`service_capability.courante`,
  `_recevoir_travaux_termines`) : une exception de `port_service_m4.publier` dans cette livraison annule toujours le
  savepoint de livraison (reçu WCT et facture brouillon compris), puis réessai/quarantaine (constat 8). Le
  réconciliateur, lui, ne tourne jamais dans une livraison. Découpler la V1 de la livraison reste à faire.
- Intention déterministe calculée sur l'état M5 (version des entrées, tarifs, nombre de traces) : un changement
  purement M4 après certification (correction d'une déclaration d'équipe déjà vérifiée) n'est pas détecté par le
  statut D3 ; la signature des registres M4 relance le balayage, mais l'état M5 inchangé reste `a_jour`.
- Mémoire de convergence par processus : deux processus (serveur MCP + CLI) restent sérialisés par SQLite ; une
  exécution concurrente rend `a_jour` ou `deja_executee`, jamais une seconde écriture.
