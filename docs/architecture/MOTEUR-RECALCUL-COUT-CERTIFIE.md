# Moteur de recalcul du coût certifié (SQLite) : privé, non branché

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

## Ce qui n'est PAS décidé ici

- **Acteur automatique (D2).** Le moteur exige la session d'un admin console actif (autorité de `_executer_qa`).
  L'acteur est un paramètre explicite mais il doit égaler `session.utilisateur`. Un acteur système sans session
  (réconciliateur, E8) change le modèle d'autorité : décision de Nathan.
- **Octroi des politiques (D1)** : aucune politique n'est créée ni lue par un opérateur ; PostgreSQL reste refusé.
- **Affichage de la lecture admin (D3)**, **surface de déclaration d'équipe (E3)**, **opérateur d'octroi (E4)**.
