---
name: mesure-et-tests-marketing
description: À utiliser pour normaliser des UTM, importer des conversions hors ligne, concevoir un test marche-arrêt ou géographique avec reçu de calcul, lire une attribution simple, ou mesurer la visibilité dans les réponses d'IA sans causalité inventée.
---

# Mesure marketing honnête

1. UTM : `m7_normaliser_utm` sur des URL fournies en texte (jamais ouvertes). Une valeur non normalisable est rendue avec
   sa raison, jamais devinée. Les identifiants publicitaires (gclid, fbclid…) sont écartés, pas gardés.
2. Conversions hors ligne : `m7_importer_conversions_hors_ligne` n'accepte que l'identifiant du lead que M2 connaît, le
   type, la date, la valeur en CAD et une source normalisée. Jamais de nom, de courriel ou de téléphone. Rien n'est
   envoyé à Google ou Meta. Consentement et Loi 25 : À valider auprès d'un professionnel qualifié.
3. Concevoir un test : `m7_concevoir_test_marketing` (taille d'échantillon, puissance, durée marche-arrêt, plan
   géographique). Le nombre vient du reçu de calcul rejouable (`m7_rejouer_recu_mesure`), jamais de ta tête. Si c'est
   irréalisable (trop de semaines, moins de six paires), dis-le tel quel. Préenregistre avant de regarder les résultats :
   `m7_enregistrer_plan_test_marketing`.
4. Lire un résultat : `m7_analyser_test_marketing`. Sans plan préenregistré antérieur et période identique, c'est
   « exploratoire » : une différence observée, pas un effet. Ne dis jamais « causé par » ni « grâce à ».
5. Attribution : `m7_lire_attribution_simple` compte par dernière source connue, garde la part « sans source » visible,
   ne donne un coût par conversion que si la dépense est CONNUE, et laisse « indistinguables » les sources aux
   intervalles qui se chevauchent. Argent : réservé à l'admin confirmé ou au propriétaire.
6. Visibilité dans les réponses d'IA : panel par API OFFICIELLES seulement (`m7_planifier_panel_visibilite_ia`, coût
   affiché d'avance, jamais de scraping d'interface), puis `m7_calculer_visibilite_ia` (taux, Wilson, effectif ;
   « une réponse d'API n'est pas celle de l'interface grand public »). Recommandations de contenu :
   `m7_recommander_contenu_geo`, sourcées ; Google dit qu'aucune optimisation spéciale n'est requise. Un changement de
   site n'est qu'un brouillon (`m7_proposer_changement_site`) ; le publier reste N3.
