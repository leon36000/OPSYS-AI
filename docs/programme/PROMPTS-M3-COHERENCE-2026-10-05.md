# Cohérence du prompt M3 — 5 octobre 2026 UTC

La consigne initiale de `SOUL.md` demandait de présenter systématiquement un intervalle
et les P50/P80. Son ajout final et le skill précisaient déjà que ces valeurs sont des coûts
internes. Laisser les deux formulations pouvait conduire un agent à présenter un coût au
client comme un prix. Les deux premières consignes sont maintenant alignées sur les champs
réellement calculés : `prix_recommande` ou `scenarios_prix[].prix` pour la vente; intervalle
de coût, P50/P80 et bases de coût uniquement dans une vue financière autorisée.

Sources contrôlées :

- [Instructions M3](../../departments/m03-estimation/SOUL.md).
- [Procédure d’estimation](../../departments/m03-estimation/skills/estimer-un-projet/SKILL.md).
- [Calcul et séparation coût/prix](../../departments/m03-estimation/src/m3_estimation/estimation.py).
- [Projection selon les droits](../../departments/m03-estimation/src/m3_estimation/outils.py).

Le prix recommandé reste absent sans taux de marge déclaré. L’agent ne calcule ni prix,
ni marge et ne montre aucun résultat chiffré pendant un blocage ou une attente d’approbation.
Les droits du serveur et la projection des outils gardent leur rôle; un prompt ne les remplace pas.

Vérification : comparaison des formulations avec le code et le skill, préimage et SHA
conservés. Aucun calcul, rôle, contrat ni code runtime modifié. Aucun test de modèle lancé :
la correction ne démontre ni baisse des tokens ni absence d’erreur d’un modèle. L’évaluation
future doit opposer au même prompt une estimation sans taux, un intervalle de coûts, un prix
recommandé disponible et un résultat en attente d’approbation, puis compter les affirmations
et appels injustifiés.
