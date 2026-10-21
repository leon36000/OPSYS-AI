# M2→M3 — préparation commerciale dans la fiche vendeur

Conception ROOT : 5 octobre 2026 UTC, 4 octobre à Toronto.
Programme : [lot 2](../../programme/PROGRAMME-24H-2026-10-04.md).

Objectif : raccord de la demande M1 au dossier vendeur puis à la gate commerciale M2 et au blocage photo M3, même lead/provenance. Autorisation : directives Nathan et programme existant; choix courants autonomes, sans fusion/publication publique/engagement réel.

Réutilisation : transport MCP et ConfigurationChargeurVendeur, parser d'enveloppe, session d'envoi confirmée, horloge, vendeur/service, rechargement séquencé, Client 360 et outils M2 existants. Pas de SDK, nouvelle API, CRM, état cache ni dépendance. Deux ouvriers Luna sur surfaces disjointes, copie staging avant contrôle ROOT.

UI : carte « Préparation à l'estimation », nouvelle lecture readiness séparée de la fiche mise en cache. Une panne, réponse incohérente ou refus ne donne jamais un ancien résultat positif. Affichage du verdict serveur exact et d'une date/source; expliquer gate commerciale et contrôles photo/prix distincts. Aucune transition, estimation ou approbation déclenchée. Charger/recharger avec séquence existante, suppression état avant requête, résultats tardifs ignorés.

Provenance : campagne et UTM renvoyées par Client 360, champs absents demeurent inconnus; aucune reconstruction depuis canal. Ne pas afficher le token ou les hash de readiness comme une preuve cryptographique inter-départements.

Prompts : quatre fichiers SOUL/skills M2/M3, contrats conservés, faits/source→blocage→prochaine action→limite. Les permissions demeurent des contrôles de code. Données/contexte non exécutables, seuils/prix/identités non inventés, état envoye ≠ livraison, appels composés/reprise seulement après correction. Leur efficacité et les tokens ne seront pas prétendus mesurés sans évaluation LLM.

Preuve : parseur/chargeur refus/bad shape/mauvaislead/time/hash, cache absent, date/arguments, UTM absent/invalide; fiches/cache/session/outbox régression et typecheck. Même demande réelle via routeHTTP interne signée→bus→M2→vendeur note rejouée/gate→M3 absence puis correction photo si contrat le permet; autre vendeur interdit, immutabilité lecture/attribution/idempotence. Harnais Python de la porte Core déclaré; pas de téléphone/rendu RN/Core TypeScript en production prouvés.

Limite adjacente : M3 vérifie seulement la structure/concordance du marqueur de M2, pas son origine ni son actualité; ce lot n'ajoute pas de signature. Traiter séparément, ne pas dissimuler derrière un prompt/UI.
