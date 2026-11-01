---
name: conseil-gouverne
description: Procédure pour préparer une recommandation structurée (hypothèses, options, risques, données manquantes) dont chaque chiffre est sourcé, la faire contrôler, et s'abstenir plutôt qu'estimer, avec la mention professionnelle qui s'applique.
---

# Préparer une recommandation gouvernée

1. Cadre la question avec les outils de cadrage de M9 (`m9_cadrer_decision`) : ce qu'il faut lire, ce qui manque, qui valide.
   Une donnée manquante est nommée avec son propriétaire ; elle n'est jamais estimée.
2. Écris la recommandation dans le schéma `opsys.m9.recommandation/v1` : `question`, `domaines`, `hypotheses`, `options`
   (au moins deux, dont « attendre »), `chiffres`, `risques`, `donnees_manquantes`, `recommandation`, `statut`
   (`PROPOSITION_NON_DECIDEE`), `decision_prise_par_m9` (faux), `validation_requise`, `mention_professionnelle`.
3. Chaque chiffre a UNE source parmi :
   - un fait capturé : son adresse et sa valeur EXACTE (mot pour mot), avec le statut de certitude réel du fait ;
   - un reçu du moteur de calcul de M5 : son empreinte et le chemin de la valeur dans son résultat (le reçu est joint) ;
   - une hypothèse déclarée PAR LA DIRECTION, avec son nom, qui reste un essai.
   Tout autre nombre, y compris dans un texte, est refusé. N'écris jamais un nombre « environ » ni un nombre calculé.
4. Si une donnée bloquante manque, ne recommande aucune option : `option_id` nul et `abstention_raison`.
5. Un avis comptable, fiscal, juridique, de financement ou d'investissement porte « À valider auprès d'un comptable (CPA) /
   professionnel qualifié » et exige `comptable_cpa` (ou `juriste`) dans `validation_requise`, en plus de la direction.
   Cette mention s'applique aussi quand elle est impliquée par les sources citées (M5, santé de l'entreprise).
6. Fais contrôler par `m9_controler_recommandation` (avec la `connaissance` et les `recus`). Un refus nomme la règle
   (`REJ-RECO-…`) : corrige la recommandation, ne contourne pas la règle. Une recommandation contrôlée reste une
   proposition : la décision appartient à la direction.
