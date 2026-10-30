# Conseil réel M9.4 / M9.23 — vraies sorties de modèles, admission et gouvernance par le code

**Portée.** Question fictive (« Que devrait faire l'entreprise cette semaine avec les leads reçus et le stock de matériaux ? »), faits
RÉELS capturés par le port privé (M2 : 3 leads fictifs ; M6 : disponibilité), SQLite, outils M9 réels, profils d'agents natifs créés par
`agents.creer`, réservations et réconciliations natives (`admission_agents`). Importance « courante » : 3 rôles (croissance_marketing,
contraintes_inventaire, conseiller_pdg).

**Backend réel utilisé, dit tel quel.** Chaque tour a été joué par un VRAI modèle : un sous-agent Claude (modèle « sonnet ») lancé par
l'outil Agent de cette session, qui lit le fichier d'entrée du tour et rend un objet JSON. Ce n'est PAS le runtime natif Core (non exécutable
dans le bac à sable) : la jonction Core reste ouverte (M9.4). Aucun secret lu ni exposé, aucun coût externe hors la session.

**Consommation.** Le harnais des sous-agents rapporte ~80 000–87 000 jetons par tour (système, outils et lecture compris) : réconciliée telle
quelle, elle dépasse le plafond réservé de 6 000 et le code REFUSE le dépôt (`REJ-TOUR-RESERVATION`), puis le budget agent est épuisé. C'est
la règle de budget qui joue. La consommation du modèle SEUL n'est pas mesurable ici ; les dépôts suivants réconcilient une ESTIMATION
déterministe non mesurée `ceil((octets entrée + octets sortie)/3)` (3 119 à 4 337), déclarée telle dans `estimation-usage.json`. Libellé :
dans `ronde1/depots*.json` et `ronde2/depots.json`, le champ `tokens_rapportes_par_le_harnais` contient en réalité cette estimation (erreur
de libellé du script, corrigée ensuite : `tokens_reconcilies_estimation_deterministe` dans `ronde3`) ; les valeurs du harnais sont dans
`estimation-usage.json`.

## Résultats par ronde
| Ronde | Consigne | Rôle | Issue | Cause |
|---|---|---|---|---|
| 1 | « format » seul | croissance_marketing | REFUSÉ | clés racine en trop (`role`, `entree_sha256`) : `REJ-CONSEIL-SORTIE` |
| 1 | « format » seul | contraintes_inventaire | REFUSÉ | nature `fait`/`manque` inconnue : `REJ-CONSEIL-AFFIRMATION` |
| 2 | + schéma exact | contraintes_inventaire | ADMIS | 6 citations exactes, 4 hypothèses, 3 inférences |
| 2 | + schéma exact | croissance_marketing | REFUSÉ | 35 affirmations pour 24 admises (consigne annonçait 40 : erreur de la mission) |
| 3 | schéma + borne 24 | croissance_marketing | ADMIS | 12 citations exactes, 3 hypothèses, 5 inférences |
| 3 | schéma + borne 24 | conseiller_pdg | ADMIS | recommandation + 3 actions |

Clôture : `RECOMMANDATION`, autorité d'effet FAUX, 3 actions toutes `PROPOSABLE` (1 suivi interne, 2 informations), aucune décision majeure ;
rapport de décision v2 `PROPOSITION_NON_RATIFIEE` : sections RENSEIGNÉES (question, décision, données utilisées/manquantes, hypothèses,
incertitudes, diagnostic, validation) et NON_DISPONIBLES nommées (impacts, scénarios, risques, plan d'action, priorités…).

## Ce que cela prouve et ne prouve pas
- Prouvé : de vraies sorties de modèle sont admises ou refusées par le code selon leur forme et leurs citations mot pour mot ; le budget
  réel est appliqué ; la gouvernance classe les actions ; les modèles ont nommé les manques au lieu d'inventer (aucun chiffre hors citation).
- Défauts trouvés et corrigés (commits `1d70014b`, `3c1c8885`) : consigne sans schéma exact ; borne d'affirmations écrite à la main.
- NON prouvé : la vérité des inférences (`validation_semantique: NON_PROUVEE`). Exemple relevé : deux modèles (ronde 3) écrivent « disponibilité
  des équipes » à propos de `m6.disponibilite`, qui concerne les matériaux — citations exactes, interprétation fausse que le code ne peut pas
  détecter. Aucune qualité de conseil n'est donc établie, seulement la tenue des garde-fous.
- Effectif : 6 sorties réelles, 3 rondes, un seul modèle, un seul scénario fictif : indicatif, pas statistique. Wilson 95 % de l'admission
  finale (3/3 sorties de la ronde 3 avec le schéma corrigé, 2 sorties) non calculé : trop peu pour une conclusion.
- Non exécuté : runtime Core natif, critique (importance « courante »), plusieurs modèles ou fournisseurs.
