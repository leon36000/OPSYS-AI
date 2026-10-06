# Qualification empirique de l’apprentissage chantier

Protocole proposé le 5 octobre 2026, adapté au code existant. Il complète l’
[audit M3](M3-APPRENTISSAGE-AUDIT-2026-10-05.md); aucune donnée réelle n’est ingérée,
aucun barème n’est activé et aucune amélioration de précision n’est annoncée par ce document.

## Question mesurable

Pour un service, une unité, une quantité et un barème donnés, une candidate issue de chantiers
antérieurs réduit-elle l’erreur de durée sur des chantiers ultérieurs distincts ? La durée observée
M4 est une durée écoulée d’intervention, pauses et déplacement exclus. Elle ne mesure ni les
heures-personnes ni le coût de paie. Le prix client et l’intervalle de coûts M3 restent des objets distincts.

## Corpus et provenance

Le corpus doit être autorisé, reproductible et séparé des fixtures de développement. Chaque observation
lie WCT, devis accepté, lead et hash du maillon d’estimation, trace/version du barème, début/départ/fin
et statut de vérification M4. Les doublons, sources incohérentes, transitions invalides et unités
incompatibles restent des exclusions nommées. Compter les chantiers distincts, pas seulement les WCT.

Conserver le nombre de demandes d’origine, le nombre de chantiers terminés et vérifiés, les candidats
retrouvés, les jointures qualifiées et chaque motif d’exclusion. Sans inventaire source indépendant,
ne pas conclure que le corpus M4 est complet à partir des seuls éléments reçus par le lecteur.
Un hash vérifie des octets, il ne remplace pas une preuve d’origine autorisée.

Les matériaux doivent disposer d’une unité prévue et réelle explicitement comparable et d’une
sémantique qualifiée. Une mesure étiquetée « pourcentage » ne suffit pas à prouver cette compatibilité.
Ne pas attribuer un écart à une cause sans données vérifiées. Une marge exige prix définitif, coût
complet, verdict M5 calculé et versions cohérentes; elle ne sert pas à entraîner la durée par défaut.

## Partition et mesure

Enregistrer la coupure UTC et les règles avant d’observer le résultat. Réserver les chantiers ultérieurs
pour le holdout; un chantier ne peut contribuer aux deux partitions. Respecter les segments exacts
du code : service, unité, version de barème, quantité et taux. Ne pas interpoler une amélioration à des
quantités, régions ou services absents de l’évaluation.

Reprendre les erreurs signées et absolues, médianes/P80 et effectifs produits par les outils déterministes.
Les métriques sont conservées avant/après correction, avec les exclusions et la couverture. Une candidate
insuffisante ou un intervalle de confiance non concluant reste inactive, sans remplacer les données manquantes.

La politique existante `m3-time-promotion-policy/1` exige notamment 30 chantiers train, 30 holdout,
90 % de couverture, 10 % et une minute d’amélioration minimale, borne de confiance 95 %, 10 000
réplications bootstrap et au plus 5 % de régression P80. Elle est explicitement
`non_qualifiee_empiriquement` : ces seuils gouvernent une évaluation initiale, ils ne constituent
ni une norme scientifique validée ni une preuve commerciale. Le protocole doit rapporter exactement
les seuils et verdicts appliqués, jamais les ajuster après résultat pour faire passer la candidate.

## Décision et suivi

Remettre au propriétaire le corpus/version, les effectifs train/holdout par segment, couverture,
exclusions, erreurs avant/après, limites et verdict de l’outil. L’activation ou le rollback suivent
les outils N4 existants et l’approbation du propriétaire; aucune recommandation LLM ne les remplace.
Après activation, réserver un nouveau lot ultérieur indépendant pour suivre la dérive et les régressions.
Ne pas réutiliser le holdout déjà examiné comme une nouvelle validation indépendante.

Les résultats publics sont agrégés et anonymisés. Le rapport d’apprentissage ne transmet ni GPS,
coordonnées client ni identité employé. Préserver les preuves d’accès, rétention, versions et décisions.
L’apprentissage matériaux, coûts et prix demande ses propres corpus et critères : le succès d’une
calibration de durée ne qualifie pas l’ensemble du département.

Sources : `calibration_raccord.py`, `calibration_cohortes.py`, `calibration_versions.py`,
configuration `calibration_temps` de `department.yaml`, projection M4 et lecteur M5 de rentabilité.
État : protocole documenté, qualification empirique réelle non effectuée.
