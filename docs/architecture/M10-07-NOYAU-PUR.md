# M10-07 — noyau pur de fusion (état partiel)

`m10_memoire.routeur.fusionner` est une brique interne de calcul déterministe. Elle accepte des candidats structurés
et préfiltrés par l'appelant, puis calcule `somme(poids_source / (k + rang))`. `k`, chaque poids, la limite de résultats
et le budget d'extraits `max_caracteres_extraits` sont obligatoires; aucun poids par défaut ou priorité métier n'est appliqué.

Chaque candidat doit déclarer son domaine, sa source, sa référence, son rang, son extrait, une citation structurée avec
une ancre déclarée et ses descripteurs de statut, fraîcheur, autorité et module. Le dédoublonnage utilise la référence
exacte fournie par l'adaptateur. Une référence présente sur plusieurs sources doit avoir un contenu, une citation et
des métadonnées concordants, sinon la fusion est
refusée. Une référence répétée dans la même liste source est refusée, afin qu'elle ne contribue jamais deux fois au
score tout en n'étant rapportée qu'une fois pour cette source. L'ordre d'entrée n'influence pas le résultat. La
troncature est signalée.

Le noyau ne canonicalise pas les références; il vérifie seulement qu'elles sont non vides, sans espace périphérique, et
égales aux références déclarées dans les citations. Il n'authentifie pas les citations, ne résout pas leur source et ne
valide pas le format ou le contenu d'un hash déclaré. Ces contrôles et la résolution vers la source originale doivent
être effectués par l'adaptateur avant la fusion et avant toute exposition. Plusieurs types d'ancre sont permis; aucun
format de hash commun n'est imposé ici.

Les poids et contributions non finis sont refusés. Un poids positif dont la division RRF sous-flue à zéro est aussi
refusé, car cette perte de précision peut inverser le classement stable; un poids explicitement nul reste valide si une
autre source a un poids positif.

`max_caracteres_extraits` et `caracteres_extraits` portent uniquement sur le texte des extraits. Les références, citations
et autres champs sont conservés intacts; le sérialiseur peut donc produire un objet bien plus grand que cette limite.
Une référence longue peut à elle seule dépasser largement le budget. Une borne sur la réponse JSON complète reste à
implémenter et à tester avant toute exposition : ce noyau ne fournit pas de plafond global.

## Limites bloquantes avant tout usage exposé

Cette fonction ne lit aucune source et n'évalue aucun droit. Elle ne prouve pas que les candidats sont réellement
préfiltrés. Elle n'authentifie pas d'appelant, ne contrôle pas le profil, ne sépare pas les domaines en amont, ne fait
pas respecter les règles de confidentialité et ne vérifie pas que le profil affaires ne peut atteindre des sources de
développement (ou l'inverse). Les champs d'autorité, de statut et de fraîcheur sont conservés mais ne changent pas le
score. Les quatre voies, leurs adaptateurs et l'outil MCP `m10_rechercher_memoire` restent à construire.

Il faut implémenter et tester l'identité et les permissions côté serveur avant tout appel de source; un booléen ou une
affirmation « autorisé » fourni au noyau n'est pas une preuve. Les coefficients et règles de pondération statut,
fraîcheur, autorité et module restent à décider/configurer explicitement. Le contrat d'ordre d'autorité existant n'est
pas modifié et ses contradictions ne sont pas résolues par ce noyau. Ce livrable ne signifie donc pas que M10-07 est
complet.
