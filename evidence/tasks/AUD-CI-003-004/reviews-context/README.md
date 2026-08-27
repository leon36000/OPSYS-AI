# Voix préservées, NON comptées dans le consensus

`verify_proof_sealed.py` ne lit que `reviews/*.json`. Ce dossier est donc invisible
du calcul de consensus — c'est délibéré, et c'est aussi une faiblesse connue du
mécanisme : un verdict gênant pourrait y être caché. Rien n'est caché ici, et voici
exactement pourquoi chaque fichier s'y trouve.

## `Kimi-2.7.ANCIEN-SCEAU.json`

Verdict **APPROVE**, obtenu réellement de `Kimi-2.7` (Moonshot) — mais sur le
**diff précédent**, celui du premier scellement.

- son `prompt_sha256` est `e183573b…5f6dd21e`
- le sceau courant est `f1c223e4…47cb0a2`

Le premier prompt ne montrait que les 2 fichiers du périmètre scellé. Le second
montre les 5 fichiers modifiés, dont la suppression du constat d'audit
`AUD-A5-001` (sévérité critique) — que Kimi n'a jamais vue.

Le laisser dans `reviews/` l'aurait fait compter comme une voix sur un code qu'il
n'a pas jugé. Le supprimer aurait effacé une mesure réelle. Il est donc conservé
ici, hors du consensus, et son statut est écrit.

Kimi a bien été resollicité sur le nouveau sceau : deux tentatives, deux
`TRUNCATED_COMPLETION` avec `finish_reason: length`. Le prompt est passé de 25 238
à 36 096 caractères, et `FORGE_MODEL_BRIDGE_MAX_TOKENS` vaut 4096 — budget consommé
en tokens de raisonnement avant émission. Aucun verdict n'a été fabriqué à sa place.
