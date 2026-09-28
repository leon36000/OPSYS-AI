---
name: journaliser-une-decision
description: Procédure pour journaliser une décision motivée au registre Business et obtenir sa référence vérifiable, ou pour signaler puis arbitrer une révision entre deux souvenirs, sans jamais fusionner ni muter un maillon existant.
---

# Journaliser une décision

1. Rassemble : `decision_id`, `raison` (obligatoire, non vide — sans elle, refus immédiat),
   `statut` (un des `STATUT_DECISION` : `proposee`, `validee`, `remplacee`, `annulee`, ou
   l'échappatoire `indetermine` si vraiment tranché ainsi — jamais deviné), `options_ecartees`.
2. Appelle `m10_journaliser_decision` avec `decision` et `horodatage` (ISO-8601 AVEC fuseau —
   sans fuseau, refus). N'invente aucun de ces champs.
3. Lis la réponse : `accepte: false` → le `verdict` nomme ce qui manque (raison absente,
   statut hors énuméré) ; corrige, ne réessaie pas à l'identique. `accepte: true` → conserve la
   `reference` (`ligne_id`, `registre`, `hash_tete`) : c'est ce que M9 (`memoire_m10`) ou un
   futur lecteur vérifiera par `m10_verifier_reference`.
4. Pour connaître le statut COURANT d'une décision déjà journalisée, appelle
   `m10_statut_decision` — ne le déduis jamais d'un maillon isolé, le statut est toujours celui
   du dernier maillon écrit pour ce `decision_id`.

# Signaler puis arbitrer une révision

1. Quand deux maillons se ressemblent ou qu'un fait devient obsolète, appelle
   `m10_signaler_revision` avec les deux `ligne_id` concernés (jamais un maillon contre
   lui-même) et un `horodatage`. Conserve le `ligne_id` du signalement retourné.
2. Une fois l'arbitrage humain rendu, appelle `m10_arbitrer_revision` avec ce même `ligne_id`
   (nommé `revision_ligne_id`) et le statut choisi (`STATUT_REVISION` : jamais de valeur de
   fusion, elle n'existe pas). Un `revision_ligne_id` qui ne correspond à aucun signalement
   réellement écrit est un refus.
3. Les deux maillons d'origine ne sont JAMAIS modifiés ni fusionnés : la révision ajoute des
   maillons, elle n'en efface ni n'en réécrit aucun.
