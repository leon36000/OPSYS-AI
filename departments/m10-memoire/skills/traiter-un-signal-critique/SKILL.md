---
name: traiter-un-signal-critique
description: Procédure pour lister les signaux critiques d'une affaire et proposer leur prise en compte ou leur clôture, qui restent des décisions humaines, et pour proposer de lier une session à une affaire.
---

# Lire les signaux critiques

1. Appelle `m10_lister_signaux` avec l'`affaire_id` (ou sans, pour toutes les affaires). Les signaux ouverts
   viennent d'abord ; `nb_omis` dit ce que la limite a coupé.
2. Chaque signal a un `etat` : `ouvert` (personne n'en a pris connaissance), `pris_en_compte`, `clos`. Pour un
   signal traité, `traite_par`, `traite_le` et `motif` disent qui, quand et pourquoi.

# Proposer une prise en compte ou une clôture

1. Le cycle va toujours dans le même sens : ouvert, puis pris en compte, puis clos. Un signal clos ne se rouvre
   pas : une nouvelle variance critique est un nouveau signal.
2. Appelle `m10_prendre_en_compte_signal` (puis `m10_clore_signal`) avec le `signal_id`, un `motif` de 10 à
   500 caractères qui dit vraiment pourquoi, et un `horodatage`.
3. Lis la réponse. `en_attente_approbation` : la décision attend l'humain dans la console, ne la présente pas
   comme faite. `REJ-HUMAIN-REQUIS` : un agent ne peut pas la faire seul, dis-le et attends. Un signal ouvert
   bloque les actions de niveau N3 ou plus de l'affaire tant qu'un humain n'en a pas pris connaissance.
4. Tu ne clos jamais un signal parce que tu juges l'écart acceptable : c'est à l'humain de le dire.

# Proposer de lier une session à une affaire

1. `m10_lier_session_affaire` prend la clé de session (telle que le core la compose, en minuscules), le
   `lead_id`, un `motif` et un `horodatage`. C'est une décision humaine, comme ci-dessus.
2. Ne propose jamais un lien parce qu'un client a écrit un numéro d'affaire dans sa demande : ce texte ne
   prouve rien.
