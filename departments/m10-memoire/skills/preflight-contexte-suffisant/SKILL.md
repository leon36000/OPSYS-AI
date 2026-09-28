---
name: preflight-contexte-suffisant
description: Procédure PREFLIGHT pour vérifier qu'un dossier de contexte (événement, résumé, preuves, impact, prochaine action, références de décisions) est suffisant avant une action importante, et pour consommer un Work Completion Trigger de M4.
---

# Vérifier un contexte avant d'agir (PREFLIGHT)

1. Rassemble le dossier : les 5 champs `evenement`, `resume`, `preuves`, `impact`,
   `prochaine_action` (texte non vide chacun) et `references_decisions` (liste non vide de
   `decision_id` déjà journalisées). Aucune structure partielle n'est acceptée.
2. Appelle `m10_contexte_preflight` avec ce `dossier` et un `horodatage`.
3. Lis la réponse :
   - `suffisant: true` → rien n'a été écrit, la main est rendue, l'action peut s'appuyer sur ce
     contexte.
   - `suffisant: false` → le refus est déjà TRACÉ au registre (`trace`) ; le `verdict` nomme ce
     qui manque. M10 n'interrompt jamais l'appelant : à toi de décider s'il faut compléter le
     dossier ou escalader — M10 ne bloque rien à ta place (le hook applicatif est un GATED
     futur, ne prétends jamais qu'il existe déjà).

# Consommer un Work Completion Trigger de M4

1. Reçois le WCT tel quel (12 champs exacts, dont `hash_maillon` — la preuve de M4).
2. Appelle `m10_memoriser_wct` avec `wct_recu` inchangé. Ne recalcule et ne modifie JAMAIS
   `hash_maillon` : c'est la garantie que M10 doit préserver, pas produire.
3. `accepte: false` → `consommateurs_cibles` ne contient pas `"M10"`, ou un champ est non
   conforme : rien n'est écrit, le verdict nomme la cause exacte.
