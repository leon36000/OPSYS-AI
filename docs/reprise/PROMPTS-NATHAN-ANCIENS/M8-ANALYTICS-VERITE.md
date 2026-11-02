# M8 — Business Truth & Analytics OS : BI, métriques, tableaux de bord, wallboards, qualité des données, alertes, prévisions, copilote analytique (condensé fonctionnel du prompt de Nathan, 2026-06-09)

(« GRS » = ancien nom d'OPSYS-AI.) But : le **moteur de vérité mesurable**. Pas une page de graphiques décorative, pas une couche qui invente des chiffres. M8 répond : qu'est-ce qui se passe
vraiment, qu'est-ce qui rapporte / coûte / bloque / baisse / monte / est en retard / est risqué / est prioritaire, que corriger, que montrer à Nathan maintenant. **M8 mesure, valide,
expose, alerte, explique, compare** ; il ne décide pas (M9), ne fait pas la compta (M5), ne vend pas (M2), ne planifie pas (M4), ne commande pas (M6), ne tient pas la mémoire (M10).
Garanties : métriques fiables, définitions claires, source de chaque chiffre, fraîcheur de chaque donnée, qualité testée, tableaux utiles, wallboard en direct, alertes actionnables,
tendances compréhensibles, prévu vs réel, intégration M1–M10, **pas d'hallucination analytique, pas de métrique sans définition, pas de graphique sans source, pas de décision sans contexte**.
Ne pas reconstruire les autres départements ; M8 lit et agrège ; ne devient pas un fourre-tout stratégique ; n'invente pas de KPI ; n'expose pas de données sensibles sans permission.

## Fonctions attendues
- **Registre de métriques / couche sémantique** : chaque métrique définie une seule fois (id, nom, définition métier et technique, expression, source, module source, propriétaire, grain,
  dimensions, filtres, fréquence, SLA de fraîcheur, tests de qualité, permissions, format, version) ; contrats de métriques, requêtes, lignée, versionnage ; **aucun tableau officiel
  n'utilise une métrique non enregistrée** (éviter « le CRM dit revenu = X, la compta Y, le marketing Z »).
- **M8.1 Hub de collecte** : connecteurs vers M1…M7, M9, M10 avec état de santé et fraîcheur ; **afficher quand un connecteur est en panne, périmé ou partiel**.
- **M8.2 Entrepôt / marts** : faits (interactions de réception, leads, évènements de pipeline, estimations, soumissions, chantiers, sessions de travail, factures, paiements, matériel utilisé,
  commandes d'achat, évènements marketing, métriques sociales, avis, risques, alertes), dimensions (date, client, propriété, employé, équipe, service, ville, fournisseur, matériau,
  campagne, département), marts (revenu, pipeline de ventes, ROI marketing, opérations terrain, rentabilité des chantiers, santé de l'inventaire, expérience client, trésorerie, santé
  exécutive) ; ne remplace pas les tables transactionnelles ; instantanés, vues matérialisées ; volumétrie élevée → stockage colonne (ClickHouse) plus tard, DuckDB/Parquet pour lots et exports.
- **M8.3 Moteur de qualité des données** (non nul, unicité, intégrité référentielle, valeurs acceptées, fraîcheur, plages, pas de revenu négatif, total de facture = lignes, soumission a un
  client, chantier a une adresse, fin a un horodatage, matériel lié à un chantier, lead a un statut, métrique non périmée) ; rapport, échecs par module, suggestions de correction ; **si une
  métrique critique échoue, le tableau affiche un avertissement**.
- **M8.4 Fraîcheur / lignée / score de confiance** par métrique (module source, point d'accès, table, dernier rafraîchissement, SLA, qualité, lignée, version de transformation, confiance,
  propriétaire) ; pastilles LIVE, FRESH, STALE, PARTIAL, ESTIMATED, MISSING, QUALITY_FAIL, GATED ; **M8 doit oser dire « donnée pas fiable »**.
- **M8.5 Tableau de bord exécutif** : santé globale, cash/finance, pipeline, marketing, terrain, inventaire, clients, risques, occasions, décisions en attente, actions prioritaires ;
  widgets (score de santé, cash libre réel, revenu du mois, marge brute, valeur du pipeline, leads qualifiés, taux d'acceptation, chantiers complétés/en retard, risque de rupture, ROI
  marketing, coût par lead, proxy de satisfaction, plaintes, principaux risques et occasions) ; simple, clair, actionnable.
- **M8.6 Tableaux par département** : M1 (appels reçus/manqués, messages sans réponse, temps de réponse, demandes d'admission, plaintes, rappels, transferts), M2 (leads, qualifiés,
  pipeline, soumissions, conversion, relances, affaires bloquées, raisons de perte, sources), M3 (estimations à faire/bloquées, soumissions, marge prévue, prix moyen, taux, variance, risque
  de marge), M4 (chantiers planifiés/terminés, retards, temps, efficacité de route, conformité GPS, matériel manquant, impact météo), M5 (cash libre réel, AR, AP, factures, paiements, taxes,
  paies, marge réelle, trésorerie 13 semaines), M6 (ruptures, valeur du stock, réapprovisionnement, commandes, prix fournisseurs, écart de matériaux, stock mort), M7 (SEO, Ads, réseaux,
  avis, notoriété, leads par source, coût par lead/vente, ROI), M9 (risques, occasions, décisions, actions, priorités, scénarios, rapports).
- **M8.7 Wallboard en direct** (exécutif, ventes, terrain, finance, marketing, inventaire, expérience client, santé système) : rafraîchissement automatique, temps réel, mode TV, couleurs
  d'alerte, mode sombre, plein écran, rotation de panneaux, bandeau d'alerte, avertissement de données périmées ; flux de métriques et d'alertes.
- **M8.8 Moteur d'alertes** (risque de trésorerie, baisse de leads, appels manqués élevés, conversion en baisse, retards de chantier, rupture, hausse de prix fournisseur, ROI marketing en
  baisse, pic de plaintes, facture en retard, données périmées, échec de qualité, système en panne) ; règles, évaluation, répartition, suppression, escalade, historique, accusé/report/
  résolution ; **une alerte propose une action** (courant, référence, causes probables, actions recommandées, département responsable, revue requise).
- **M8.9 Tendances / prévisions / variances** (tendance, saisonnalité, moyenne mobile, semaine/mois/an sur période, prévu vs réel, prévision simple avec bornes de confiance, anomalies) ;
  variances obligatoires : matériaux estimés vs utilisés, main-d'œuvre estimée vs réelle, marge de soumission vs marge réelle, durée prévue vs réelle, dépense marketing vs revenu,
  prévision de pipeline vs revenu, prévision de trésorerie vs réel.
- **M8.10 Score de santé** transparent (finance, ventes, marketing, opérations, inventaire, clients, données, système) ; **aucun score opaque : toujours montrer les facteurs**, historique, explication.
- **M8.11 Copilote analytique** : questions en langage naturel (pourquoi les ventes baissent, service le plus rentable, ville la plus performante, leads bloqués, marge qui descend,
  fournisseur qui augmente, équipe la plus efficace, marketing qui donne les meilleurs clients, chantier plus cher que prévu, que regarder aujourd'hui) → intention → registre → contexte
  sémantique → permissions → requête sûre → validation → contrôle qualité/fraîcheur → réponse **avec sources** → graphique suggéré → action ou renvoi à M9 ; **pas de SQL destructif,
  pas de requête sans permission, pas de métrique non définie, pas de réponse sans source, pas de conseil stratégique final (renvoyer à M9), pas de chiffre sans avertissement si la qualité échoue**.
- **M8.12 Générateur de rapports** (résumé opérationnel quotidien, rapport d'affaires hebdomadaire, performance mensuelle, ROI marketing, finance, terrain, variance d'inventaire,
  expérience client, qualité des données) en PDF/Markdown, planifiés ; **dossiers de preuves** (question, métriques, modules sources, fraîcheur, qualité, graphiques, tableaux,
  hypothèses, avertissements, export, trace) utilisables par M9, Nathan, le CPA ou un audit.
- **M8.13 Passerelle BI externe** (Superset/Metabase/Grafana) : lire la couche analytique de M8, pas les tables brutes ; jetons d'intégration ; permissions ; activation d'un outil externe = validation.
- **M8.14 Analytique mobile par profil** : admin/Nathan (exécutif, risques, alertes, cash, pipeline, chantiers, marketing, inventaire, décisions), vendeur (ses leads, conversion, relances,
  soumissions, prochaines actions), employé (ses chantiers, temps, conformité des listes, photos manquantes ; performance personnelle limitée **non punitive**), client (statut, facture via M5 ;
  aucune métrique interne).
- **M8.15 Confidentialité / RBAC** (propriétaire, admin, finance, gestionnaire, vendeur, employé, client, agent système ; permissions par métrique et par tableau, masquage de PII,
  sécurité par ligne, politique d'export, journal d'exports) ; un employé ne voit pas marges, coûts sensibles ni finances globales ; validation requise pour changer une définition de KPI,
  supprimer un tableau officiel, exporter des données financières sensibles ou une liste de clients, publier un wallboard public, activer un outil BI, connecter une nouvelle source.
- **M8.17 Fournisseur de preuves pour M9** (santé, métriques, tendances, risques, signaux d'occasions, variances, fraîcheur, qualité, dossiers de preuves) : M9 interprète, M8 prouve.
- **M8.18 Mémoire (M10)** : nouvelle métrique, définition changée, tableau ajouté, alerte critique, anomalie, variance importante, échec de qualité, rapport généré, chiffre stratégique,
  correction de données, leçon.
- **KPI obligatoires** (liste complète par département fournie dans le prompt : M1 appels reçus/manqués/récupérés, temps de réponse, admissions, plaintes, transferts ; M2 nouveaux leads,
  qualifiés, lead→soumission, soumission→vente, pipeline, relances, pertes, qualité des sources ; M3 estimations, bloquées, confiance moyenne, brouillons, estimation→soumission, marge
  estimée, variance estimé/réel ; M4 chantiers planifiés/terminés, à l'heure, durée moyenne, déplacement, retards, fin en attente de revue, conformité d'entrée du matériel ; M5 cash libre réel,
  AR, AP, factures en retard, marges brute/nette, réserves taxes/paie, trésorerie 13 semaines ; M6 ruptures, valeur du stock, réapprovisionnement, demandes d'achat, variation de prix,
  écart de matériaux, exactitude de l'inventaire ; M7 visites, rangs SEO, dépense Ads, coût par lead/vente, portée et engagement sociaux, avis, ROI ; M9 risques/occasions ouverts, décisions en
  attente, actions en retard, rapports, approbations ; système : santé de l'API, Qdrant, LiteLLM, n8n, Langfuse, mobile, nombre de données périmées).
- **Widget** : titre, valeur, delta, période, tendance, statut, source, fraîcheur, pastille de qualité, exploration, responsable, action recommandée.
- **Orchestration** : actifs de données (brut par département → marts → registre → rapport de qualité), planifications (rafraîchissement quotidien, wallboard horaire, scan de qualité,
  distribution d'alertes, pack hebdo, contrôle de fraîcheur, scan d'anomalies) qui ne peuvent jamais modifier une définition de KPI sans validation, masquer un échec de qualité ni envoyer des
  données sensibles au mauvais rôle.
- **Observabilité** : latences (rafraîchissement, connecteurs, requêtes, tableaux, alertes, qualité, copilote, entrepôt), traces du copilote (SQL sûr, explications, garde-fous), santé du service.
- **Tests visés** : registre, requêtes, permissions, fraîcheur, qualité, connecteurs, tableaux, alertes, tendances, variances, score, garde-fous du copilote, dossier de preuves ; intégrations
  M1…M7 → M8, M8 → M9, M8 → M10, M8 → mobile ; E2E (tableau de ventes ; rentabilité d'un chantier estimé/terminé/matériel/coût réel ; ROI marketing avec dossier de preuves pour M9 ;
  alerte de rupture avec chantiers à venir ; wallboard de risque de trésorerie ; échec de qualité qui bloque la métrique et fait refuser le copilote).
- **Critères de sortie** : connecteurs de production ou gates documentés, registre, couche sémantique, qualité, fraîcheur/lignée/confiance, tableau exécutif complet, tableaux par département,
  wallboard, alertes, tendances/variance, score transparent, copilote sécurisé, rapports/dossiers de preuves reçus par M9, mémoire, crochets mobile, RBAC par métrique/tableau, traces, E2E
  d'analytique métier, docs, matrice ; aucune métrique critique sans source, fraîcheur et qualité.
