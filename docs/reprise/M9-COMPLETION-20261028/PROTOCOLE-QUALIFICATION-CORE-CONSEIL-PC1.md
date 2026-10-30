# Protocole reproductible — qualification de la jonction conseil M9 ↔ Core natif (PC1)

**État : protocole livré, NON exécuté.** Le bac à sable de la mission n'exécute pas `core/` (il se construit et se
teste en CI). Les rondes de modèles déjà jouées (`preuves-conseil-reel/`) prouvent l'admission déterministe des sorties,
pas cette jonction. M9.4 reste PARTIEL tant qu'une trace issue de PC1 n'a pas reçu le verdict `COMPLETE`.

## Point de raccord (code)
- `raccord_core_conseil.py` : séquence attendue (`SEQUENCE`), dérivation du profil d'un rôle (`agent_id`), vérificateur
  de trace (`verifier_trace`). Tests : `departments/m09-strategic-intelligence/tests/test_raccord_core_conseil.py`
  (traces simulées) et `tests/test_m9_raccord_core_conseil_integre.py` (refus d'identité constaté sur le vrai `Capacites`).
- Côté M9 : `m9_proposer_profils_conseil` → `m9_ouvrir_conseil` → `m9_lire_entree_tour_conseil` →
  (tour natif sous réservation de budget) → `m9_deposer_tour_conseil` → `m9_cloturer_conseil` → `m9_lire_rapport_conseil`.
  Le dépôt exige une réservation du profil du rôle (`m9-<role>`), `conciliee`, dans son plafond, à usage unique ; au plus
  deux dépôts par tour.

## Identité de lecture de l'entrée (écart corrigé sans élargir de droits)
`m9_lire_entree_tour_conseil` exige un admin authentifié. Les profils proposés listaient cet outil alors que leur agent
aurait été refusé à l'appel ; ils n'ont désormais **aucun outil** (`entree_du_tour` le dit) : l'orchestrateur admin lit
l'entrée et la remet au tour. Un agent qui tenterait quand même l'appel est refusé (`REJ-IDENTITE-APPAREIL-INVALIDE`,
constaté sur le vrai `Capacites`). Si PC1 observe un succès d'agent, le vérificateur le classe `ECART` (règle R1).
Faire lire l'entrée par l'agent lui-même serait un élargissement de droits : décision du propriétaire, non prise ici.

## Pré-requis (à PC1)
1. Dépôt au commit de code indiqué plus bas (« Octets requis ») ; `pip install -e ".[dev]"` ; `(cd core && pnpm install --frozen-lockfile && pnpm build)` (Node 24).
2. Base fictive isolée (`OPSYS_BASE_URL` vers un SQLite jetable) ; aucune donnée réelle, aucun secret de production.
3. Configuration du Core générée par `opsys-metier openclaw configurer --config-dir <dossier jetable>` ; Gateway et
   appairage comme `tests/e2e_core/README.md` (`python tests/e2e_core/scenario.py` pour le modèle de lancement).
4. Fournisseur de modèles : un fournisseur de TEST ou un modèle réel sous plafond de jetons explicite ; la réservation
   de budget du socle (`admission_agents`) doit être active.

## Déroulé (chaque ligne produit un événement de trace)
| # | Acteur | Action | Observation attendue |
|---|---|---|---|
| 1 | admin | Créer et activer les profils de `m9_proposer_profils_conseil` (déclenchement manuel) | profils `m9-<role>` actifs, sans outil, aucun cron |
| 2 | admin | `m9_ouvrir_conseil` sur un dossier de captures fictives | un tour en attente par rôle |
| 3 | agent | (contrôle négatif) appel direct de `m9_lire_entree_tour_conseil` par l'identité du runtime | refus `REJ-IDENTITE-APPAREIL-INVALIDE` |
| 4 | admin | `m9_lire_entree_tour_conseil` puis remise de l'entrée au tour | entrée reproductible (sha256) |
| 5 | runtime | Tour exécuté sous réservation ; usage réel réconcilié | réservation `conciliee`, `tokens_reels` ≤ plafond |
| 6 | admin | `m9_deposer_tour_conseil` avec l'identifiant de réservation | dépôt admis ou refusé par le code |
| 7 | admin | Rejouer le dépôt avec la même réservation ; essayer une réservation d'un autre profil | rejeu sans nouvel effet ; refus `REJ-TOUR-RESERVATION` |
| 8 | admin | `m9_cloturer_conseil`, `m9_lire_rapport_conseil` | rapport v2, sections manquantes nommées |

## Trace et verdict
Consigner un fichier `trace.json` (nom distinct par exécution, jamais écrasé) : liste d'événements
`{acteur: admin|agent|runtime, outil, resultat: ok|refus, code?, session_id?, role?, issue?: ADMIS|REFUSE, reservation?: {id, profil, statut, tokens_reels, tokens_plafond}}`,
dans l'ordre d'exécution. Un dépôt porte l'`issue` renvoyée par l'outil (il répond `accepte` même quand la sortie est
refusée) ; seul un dépôt `ADMIS` précédé d'une entrée admin de même session et même rôle ferme un cycle.
```bash
python - <<'PY'
import json
from m9_strategic_intelligence import raccord_core_conseil as rc
print(json.dumps(rc.verifier_trace(json.load(open("trace.json"))), ensure_ascii=False, indent=1))
PY
```
Verdicts : `COMPLETE` (cycle entier sans écart) · `INCOMPLETE` (cycle non observé) · `ECART` (règle R1–R4 violée :
succès d'agent sur un outil M9, dépôt incomplet ou hors réservation conforme, réservation partagée, plus de deux dépôts).
Le vérificateur juge la cohérence d'une trace, pas son origine : joindre les journaux du Gateway et du moteur
(`<travail>/journaux/`) et leurs empreintes.

## Octets requis (référence exacte pour la qualification intégrée dédiée)
Commit de code : `a1fa74930d83ef02b00cc6388ee85fc542e7defc` (branche `mission/claude-m9-direction-complete-20261028`). Les preuves Core existantes portent
d'autres états et ne qualifient pas ce commit. Vérifier avant toute exécution :
`git rev-parse HEAD` = `a1fa74930d83ef02b00cc6388ee85fc542e7defc` puis `sha256sum` de chaque fichier ci-dessous.

| Fichier | SHA-256 |
|---|---|
| `departments/m09-strategic-intelligence/src/m9_strategic_intelligence/raccord_core_conseil.py` | `1cb127c16cf1797431ef30a97e823b5b9a0de31cae564c90a5fe52092f8d9e72` |
| `departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_conseil.py` | `0912b2f492f8db62db041c5204354397fc923b6bc84c92be095ea89e34441f15` |
| `departments/m09-strategic-intelligence/src/m9_strategic_intelligence/sessions_conseil.py` | `455e82ad16a2b9c76993d72e231fac3c4913169eb813802294c70c9ed503fd6f` |
| `departments/m09-strategic-intelligence/src/m9_strategic_intelligence/conseil.py` | `0a49e580bae7199e41bd46b6c374fe61ef337ab2f9f3456761b09d0cc9f8f3db` |
| `departments/m09-strategic-intelligence/src/m9_strategic_intelligence/dossier_strategique.py` | `4085fc7f82d61f571f6be5f12952deb293c8f69fdea49665c1ababdc25a26159` |
| `departments/m09-strategic-intelligence/src/m9_strategic_intelligence/capture_strategique.py` | `23729ca4df96e8d155e57f69565a3fc2a73cd578881e9fb7dd776b8e4b674957` |
| `departments/m09-strategic-intelligence/department.yaml` | `68bd15293bb239636e28b0b6096071972c9fe989eb0a3135d2f8df3f810bb7a8` |
| `src/opsys/admission_agents.py` | `d2af531cf2ebabd7db3479932539e94043cb98fde22b95d81eab8b9ff25c74ee` |
| `departments/m09-strategic-intelligence/tests/test_raccord_core_conseil.py` | `ad159d9c61e9a7dc6d652eb50dd7611e3551e1a8684869855338d58601c4e7ad` |
| `tests/test_m9_raccord_core_conseil_integre.py` | `851682f8ec4388a2fc743595fad162002db697fc7557bb6f439e7b5cd33d2993` |
| `tests/test_m9_conseil_integre.py` | `cc6a33ee2769a5b1291043be70a6c332494f3727f8ecef0e622a3e363eff2123` |

## Parcours attendu (dans l'ordre)
1. Pré-contrôle sans Core, sur ces octets :
   `pytest departments/m09-strategic-intelligence/tests/test_raccord_core_conseil.py tests/test_m9_raccord_core_conseil_integre.py tests/test_m9_conseil_integre.py -q`
   (attendu : tout vert ; sinon arrêter).
2. Déroulé du tableau ci-dessus sur le Core natif, trace consignée événement par événement, dans l'ordre d'exécution.
3. Verdict du vérificateur sur la trace : `COMPLETE` exigé ; `INCOMPLETE` ou `ECART` = qualification non obtenue.
4. Joindre : trace, verdict JSON, journaux Gateway et moteur, empreintes de ces fichiers, SHA du Core utilisé.

## Ce que ce protocole ne prouve pas
La vérité des inférences ; le coût réel en production ; PostgreSQL ; une planification cron (M9.5, distincte).
Aucun grant réel, merge ni déploiement n'est impliqué.
