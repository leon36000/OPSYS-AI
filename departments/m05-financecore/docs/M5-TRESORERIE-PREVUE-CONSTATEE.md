# La trésorerie prévue constatée (chantier C5 de l'analyse M8)

État au 4 novembre 2026. Aucune migration. Périmètre : l'analyse M8 §4 C5 — M5 publie sa prévision, M8 la consomme.

## 1. Ce que M5 publie

`m5_constater_tresorerie_prevue` (T1/N3, `admin`) fait constater la prévision des flux connus et datés et la publie au bus
(`m5.tresorerie_prevue_constatee`, catalogue du socle, schéma fermé). La variante planifiée
`m5_constater_tresorerie_prevue_planifie` (T1/N2, aucun droit d'appareil, `REJ-CONSTAT-PLANIFICATEUR-SEULEMENT` pour tout
autre appelant, constat `tresorerie-prevue` inactif par défaut) suit le même patron que celle du cash libre (voir
`M5-CASH-LIBRE-PLANIFIE.md`) : même registre `constats_tresorerie_prevue`, même rang, même règle « un constat par jour et
par version » (`deja_constate`).

Le constat reprend `prevision.assembler` TEL QUEL : solde de départ + 6 semaines du cas de référence
(`19885.02, 15685.02, …`, seuil `16000.00`, alerte en semaine 2), solde minimal prévu et sa semaine, semaines sous le seuil
(vides quand le seuil n'est pas configuré : `SEUIL_A_CONFIGURER`, jamais inventé), série hebdomadaire pour le
prévu-contre-réel de M8, codes de manque quand rien n'est chiffrable. Horizon 1–26 semaines, seuil, délais d'encaissement et
de paiement : `configuration.prevision`, GATE NATHAN, jamais inventés. Aucun montant n'est recalculé. Seule exception au gel
de `validation.py` (épinglé par le contrat d'admission paie) : le verdict `REJ-CONSTAT-EMISSION-INVALIDE` vit dans le module
C5, même forme que `validation.construire_verdict` (même patron que `cout_reel.CODE_CERTIFIE_A_RECALCULER`).

## 2. Ce que M8 en fait

Trois mesures fermées (62 au catalogue, +3) : `m8_solde_minimal_prevu_cad` (reprise telle quelle + semaine), `m8_semaines_sous_seuil`
(compte des semaines listées, seuil déclaré en M5 jamais inventé), `m8_ecart_tresorerie_prevue_reelle_cad` (prévu S1 de la
DERNIÈRE ANCIENNE version échue MOINS le solde réel du cash libre, en `Decimal` : la seule opération de M8 sur ces montants).
Trois tuiles sur le wallboard finance-opérations (plafond 12 → 16), règle `ALERTE-TRESORERIE-SOUS-SEUIL` enrichie
(`mesures_liees` += 3 C5), péremption += 3 C5, contrôle qualité `Q-TRESORERIE-PREVUE-COHERENTE`.

## 3. Preuve

- Tests rouges d'abord, verts ensuite : 11 (pur M5) + 7 (outils M5) + 30 (mesures M8 dont E2E wallboard + alerte).
- E2E : vrai constat M5 sur SQLite migrée → vrai bus → `operations_recues.fait` → mesures → wallboard → alerte.
- Négatif/abus : seuil absent, horizon non chiffrable, prévision périmée, constat forgé/rejoué, idempotence, bornes,
  rôle non autorisé, texte libre refusé.
- `mutkit.py` : module pur M5 9/9 tués ; lignes C5 de `mesures_constats` 61 tués + 2 équivalents prouvés
  (`ordre_publication(f, _)[0]` ne voit que l'instant publié).
- Gardes : `opsys-metier verifier` OK (10 départements, 693 outils), `ruff` OK, cohérence documentaire OK.
- Limite : rien sur PostgreSQL ni sur données réelles ; aucun CPA n'a rien validé.
