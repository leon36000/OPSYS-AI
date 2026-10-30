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
1. Dépôt au SHA qualifié ; `pip install -e ".[dev]"` ; `(cd core && pnpm install --frozen-lockfile && pnpm build)` (Node 24).
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

## Ce que ce protocole ne prouve pas
La vérité des inférences ; le coût réel en production ; PostgreSQL ; une planification cron (M9.5, distincte).
Aucun grant réel, merge ni déploiement n'est impliqué.
