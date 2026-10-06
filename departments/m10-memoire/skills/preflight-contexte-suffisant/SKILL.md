---
name: preflight-contexte-suffisant
description: Procédure PREFLIGHT pour vérifier qu'un dossier de contexte (événement, résumé, preuves, impact, prochaine action, références de décisions) est suffisant avant une action importante, et pour consommer un Work Completion Trigger de M4.
---

# Vérifier un contexte avant d'agir (PREFLIGHT)

1. Rassemble le dossier : les 5 champs `evenement`, `resume`, `preuves`, `impact`,
   `prochaine_action` (texte non vide chacun) et `references_decisions` (liste non vide de
   `decision_id` déjà journalisées). Vérifie ces décisions dans leurs sources ; si une
   référence canonique est fournie, vérifie-la avec `m10_verifier_reference`. Le prédicat
   de préflight ne vérifie pas lui-même l'existence de ces décisions. Aucune structure
   partielle n'est acceptée ; n'invente ni références, ni preuves, ni motifs pour la remplir.
2. Appelle `m10_contexte_preflight` avec ce `dossier` et l'`horodatage` réellement fourni.
3. Lis la réponse :
   - `suffisant: true` → rien n'a été écrit, la structure requise est présente. Ce résultat
     ne certifie ni les faits, ni leur fraîcheur, ni une autorisation d'action ou un succès
     métier. Vérifie séparément les sources, la cible et les permissions applicables.
   - `suffisant: false` → le refus est déjà TRACÉ au registre (`trace`) ; le `verdict` nomme ce
     qui manque. Cet outil ne bloque pas lui-même l’appelant : complète le dossier ou escalade.
     Quand le moteur de contexte Core est activé pour cet agent, son garde bloque les outils
     OPSYS configurés N3+ si le contexte est indisponible ou périmé, si un signal critique reste
     ouvert, si le contrat de cible manque/est inconnu ou si la cible affaire ne correspond pas
     à l’affaire évaluée. Moteur désactivé : ce garde ne s’applique pas.
     Ne tente pas de modifier sa configuration pour contourner un refus.
4. Restitue les sources vérifiées, ce qui manque et la prochaine action permise. Un état
   incertain ou une absence de trace n'autorise jamais à rejouer un effet métier. L'idempotence
   de consolidation concerne seulement la même affaire et le même jour.

# Consommer un Work Completion Trigger de M4

1. Reçois le WCT tel quel (12 champs exacts, dont `hash_maillon` — la preuve de M4).
2. Appelle `m10_memoriser_wct` avec `wct_recu` inchangé. Ne recalcule et ne modifie JAMAIS
   `hash_maillon` : c'est la référence reçue que M10 doit préserver, pas produire. Sa présence
   ne prouve pas à elle seule l'exécution complète du chantier.
3. `accepte: false` → `consommateurs_cibles` ne contient pas `"M10"`, ou un champ est non
   conforme : rien n'est écrit, le verdict nomme la cause exacte.
