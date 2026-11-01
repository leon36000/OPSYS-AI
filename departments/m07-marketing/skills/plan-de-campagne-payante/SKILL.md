---
name: plan-de-campagne-payante
description: À utiliser pour préparer une campagne payante (Google Ads, Meta) en brouillon, vérifier ses plafonds et règles d'arrêt, lire son rapport de performance ou ses anomalies de dépense, sans jamais lancer ni dépenser.
---

# Plan de campagne payante, règles d'arrêt et rapport honnête

1. Les créatifs sont des visuels du studio déjà composés, contrôlés et APPROUVÉS par une personne (`m7_lire_studio`) ;
   sans visuel approuvé, dis-le et arrête-toi. Les textes sont en français d'abord (`fr-CA` obligatoire).
2. Prépare le brouillon avec `m7_preparer_plan_media` : budget en cents CAD, ciblage géographique et par mots-clés
   seulement (jamais d'âge, de sexe ni d'autre critère protégé), aucun nom de concurrent. Les plafonds quotidien et
   total sont déduits du budget par le code ; les règles supplémentaires (coût par conversion maximal, dépense sans
   conversion, saut de dépense) sont des PROPOSITIONS de pause. Idempotent par clé ; une révision change l'empreinte.
3. `m7_soumettre_plan_media` refait tous les contrôles (visuels toujours approuvés, début dans le futur). Le lancement
   est un engagement de dépense : `m7_demander_lancement_campagne` (N4, propriétaire seulement, par l'empreinte exacte).
   Tu ne peux que déposer la demande. Même approuvée, OPSYS ne crée, ne modifie ni ne finance aucune campagne : la
   direction la lance dans la plateforme avec le dossier de lancement (`m7_lire_plans_media`, `avec_dossier`). Ne dis
   jamais « la campagne est lancée ».
4. Après le lancement humain, évalue avec `m7_evaluer_regles_media` (plan, référence de campagne, période) ; les
   anomalies DEP-01 à DEP-07 sont des constats. Un jour sans donnée est un TROU, jamais un zéro ; une règle sans de quoi
   être jugée est « non évaluable ». `m7_signaler_anomalies_depense` les annonce au bus (M9, M8). Rien n'est mis en
   pause par toi.
5. `m7_rapport_performance_media` : couverture, intervalles de Wilson, effectif, suffisance (sous 100 clics ou
   5 conversions, ne conclus rien), campagnes indistinguables sans classement. Ce rapport décrit, il n'explique pas :
   aucune causalité sans test préenregistré (skill `mesure-et-tests-marketing`). Évaluation et rapport lisent de
   l'argent : réservés à l'admin confirmé ou au propriétaire.
6. Limites : aucun connecteur n'a lu un vrai compte publicitaire ; les montants sont en CAD, jamais convertis. Les taxes,
   la comptabilité et l'impôt : À valider auprès d'un comptable (CPA) / professionnel qualifié.
