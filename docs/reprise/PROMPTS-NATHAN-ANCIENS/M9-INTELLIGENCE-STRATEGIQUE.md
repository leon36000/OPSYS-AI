# M9 — Intelligence stratégique : direction IA, décision, scénarios, radar de risques et d'occasions, centre de commandement (condensé fonctionnel du prompt de Nathan, 2026-06-09)

(« GRS » = ancien nom d'OPSYS-AI.) But : le **cerveau de direction**. Pas un endpoint de rapport, pas un chatbot vague, pas un LLM qui invente. Il lit tous les départements,
comprend l'état réel, priorise, simule, détecte, recommande, orchestre et prépare des décisions pour Nathan. Il répond : *que devrait faire l'entreprise maintenant,
pourquoi, avec quelles preuves, quels risques, quel impact, quelles alternatives, quelles dépendances, quelle validation humaine ?* Toute sortie contient : état actuel,
diagnostic, preuves, hypothèses, incertitudes, scénarios, recommandations, priorités, impacts, risques, actions proposées, validation requise, tâches par département,
suivi des résultats, mémoire. **Jamais** : inventer chiffres/revenus/capacité, décider finance/légal/fiscal seul, contredire M5 (finance), M2 (pipeline), M4
(cédule), M6 (inventaire), M7 (marketing), M10 (mémoire canonique), masquer l'incertitude, conseiller sans source, dire « ça va bien » sans métriques, donner une
priorité sans la justifier, déclencher une action risquée sans approbation. M9 ≠ M5 (finance), ≠ M8 (métriques/tableaux), ≠ M10 (mémoire) ; il **interprète,
arbitre, coordonne** ; ne reconstruit pas M1–M8.

## Fonctions attendues
- **M9.1 Tissu de données stratégique** : lit M1 (appels, manqués, messages sans réponse, plaintes, délais, rappels, urgences), M2 (leads, pipeline, conversion,
  relances, bloqués, sources, pertes), M3 (estimations à faire/bloquées, marge prévue, risques, écart estimé/réel), M4 (capacité, cédule, retards, temps réel, météo,
  charge), M5 (cash libre réel, AR/AP, taxes, paies, marge réelle, dette, réserves, alertes), M6 (stock, ruptures, prix, matériaux critiques), M7 (leads par source,
  coût par lead/vente, SEO, PPC, réseaux, avis), M8 (KPI validés, tendances, anomalies), M10 (décisions, plans, promesses, erreurs, règles de Nathan) ; normalise,
  vérifie la **fraîcheur**, détecte les **contradictions**, confiance par source ; ne recommande pas si des données critiques sont périmées/contradictoires sans le dire.
- **M9.2 Graphe d'état de l'entreprise** : entités (entreprise, départements, métriques, leads, clients, propriétés, estimations, soumissions, chantiers, factures,
  paiements, employés, équipes, véhicules, équipements, fournisseurs, campagnes, stock, risques, occasions, décisions, actions, objectifs, contraintes, hypothèses)
  et relations causales (campagne → pipeline, cédule → capacité, stock → préparation du chantier, trésorerie → achat, décision → action → métrique, risque →
  décision bloquée) ; chemins d'impact (« si j'augmente la pub, quels départements ? si M6 est en rupture, quel impact sur M4/M5/M2 ? cédule pleine = pub dangereuse ?
  trésorerie serrée = quelles dépenses retarder ? »).
- **M9.3 Couche sémantique exécutive** : définitions officielles et lignée des métriques (revenu, marges, cash libre réel, valeur du pipeline, lead qualifié,
  conversion, estimation→soumission→vente, rentabilité de chantier, ROI marketing, coût par lead/vente, capacité d'équipe, préparation de l'inventaire,
  satisfaction, score de risque) ; un agent ne peut pas demander « revenu » sans définition officielle.
- **M9.4 Conseil d'agents** orchestré par un superviseur stratégique (conseiller PDG, stratège des opérations, liaison financière — lit M5 sans le remplacer —,
  stratège de croissance marketing, stratégie de ventes, rentabilité des estimations, contraintes d'inventaire, expérience client, responsable des risques,
  auditeur de données, planificateur d'exécution, **critique de décision**) : aucune décision finale par un agent seul — superviseur → agents → auditeur de données →
  critique → politique de gouvernance → recommandation exécutive finale.
- **M9.5 Salle de guerre quotidienne** : qu'est-ce qui est urgent, menace l'argent/les ventes/les chantiers, quels clients rappeler, quels chantiers surveiller,
  factures/paiements/taxes critiques, actions à plus fort impact ; sections (résumé, priorités, alertes cashflow/ventes/opérations/clients/marketing/inventaire,
  décisions requises de Nathan, actions par département, risques, **ce qui a changé depuis hier**).
- **M9.6 Rapport hebdomadaire exécutif en direct** (20 sections : semaine, revenus/cash/marge, pipeline, estimations, production, inventaire, marketing, clients,
  risques, occasions, ce qui a fonctionné/échoué, leçons, décisions à prendre, plan de la semaine, objectifs mesurables, actions par département, prévisions 4 et
  13 semaines, recommandations) ; revues mensuelle et trimestrielle, mémo de conseil ; **chaque recommandation a une source ou une hypothèse explicite** ; dossier de preuves.
- **M9.8 Planification de scénarios** : hausse marketing 25 %, baisse de leads 30 %, coûts matériaux +15 %, deux employés absents, semaine de mauvaise météo, achat
  camion/équipement/bâtiment, embauche, gros client gagné/perdu, retard de paiement, saison morte faible, nouvelle ville/service, concurrent agressif, trésorerie
  serrée, rupture d'inventaire, trop de demandes pour la capacité ; comparaison, tests de résistance, questions « et si ? » ; sortie : impacts, départements touchés,
  impact financier et de capacité, niveau de risque, occasions, contraintes, décision recommandée, validation requise.
- **M9.9 Prévisions consolidées** (7 jours, 30 jours, 13 semaines, 6, 12, 24 mois) à partir des prévisions des départements (M5 reste la vérité pour la trésorerie
  détaillée ; M9 consolide et interprète) : règles métier, séries temporelles, simulation de scénarios, Monte Carlo, incertitude bayésienne, contrôles causaux,
  contraintes de capacité, optimisation sous contraintes.
- **M9.10 Moteur de décision** : questions (budget Google Ads, embaucher, camion, bâtiment, hausse de prix, nouveau service, refuser petits chantiers, prioriser
  une ville, réduire les dépenses, équipement, stratégie marketing, ajouter une équipe) → classer, départements nécessaires, données, fraîcheur, contradictions,
  options, critères, simulation d'impact, risques, contraintes, comparaison, recommandation, demande de validation, plan d'action, mémoire. **Rapport de décision
  stratégique en 21 sections** (question, résumé, décision recommandée, options, données utilisées/manquantes, hypothèses, scénarios prudent/normal/ambitieux,
  impacts financier/ventes/opérations/marketing/clients/risques, dépendances, conditions avant d'agir, validation requise, plan d'action, mesure du succès).
- **M9.11 Priorisation et allocation de ressources** : urgence, impact financier/client, effort, coût, dépendances, risque, capacité, trésorerie, stratégie,
  faisabilité, confiance des données ; ICE, RICE, WSJF, Eisenhower, ROI ajusté au risque, priorisation sous contraintes ; sortie : rang, action, raison, impact,
  effort, département responsable, métrique de succès (ex. « corriger le sauvetage d'appels manqués »).
- **M9.12 Radar de risques** (trésorerie, taxes, paie, légal, plaintes, réputation, dépense marketing, baisse de leads, surcharge de cédule, capacité d'équipe,
  rupture, hausse de prix fournisseur, erreur de marge d'estimation, retard de chantier, données périmées, hallucination d'agent, sécurité, vie privée) : score,
  tendance, plan d'atténuation, escalade ; risque critique = notification de Nathan + tâche + mémoire.
- **M9.13 Radar d'occasions** (ville à forte demande, service très rentable ou sous-exploité, campagne rentable, affaires répétées, référence, vente additionnelle,
  nouvelle équipe rentable, achat d'équipement justifié, prix trop bas, page SEO à créer, contenu social porteur, période saisonnière, concurrent faible,
  fournisseur moins cher, processus à automatiser) avec plan d'action et validation.
- **M9.14 Intelligence concurrentielle et de marché** (profils publics, avis, SEO local, prix publiés, tendances, saisonnalité, matériaux, réglementation,
  fournisseurs) — respect des conditions des sites/API, jamais de scraping illégal ni de prix concurrent inventé, données marquées public/estimé/incertain.
- **M9.15 Livres de jeu (playbooks)** : trésorerie serrée, baisse de leads, trop de leads, surcharge de cédule, mauvaise semaine météo, rupture d'inventaire,
  risque de plaintes, faible conversion de soumissions, ROI marketing faible, début/fin de saison, embauche, achat d'équipement, expansion de ville, hausse de
  prix, nouveau service, poussée d'avis ; chacun avec déclencheur, conditions, données requises, étapes, départements, risques, approbation, métriques de succès,
  plan de retour arrière ; suivi des résultats.
- **M9.16 Planificateur d'exécution et OKR** : objectifs, résultats clés, initiatives, tâches, responsables, échéances, dépendances, progression, blocages,
  résultats ; plan d'action (action, département, responsable humain/agent, pourquoi, impact attendu, échéance, dépendances, risque, métrique, validation).
- **M9.17 Orchestrateur d'actions stratégiques** : crée des actions **contrôlées** (tâche, relance CRM, revue d'estimation/cédule/achat d'inventaire, brouillon de
  campagne, rapport de décision financière, mise à jour de mémoire, rapport de tableau de bord). **Interdit sans validation** : dépenser, publier une campagne,
  changer un budget, message sensible, déclaration fiscale, payer un employé, acheter un actif, signer un contrat, supprimer des données, changer la politique de prix.
- **M9.18 Expérimentation et ROI** : hypothèse, référence, métrique de succès, plafond de budget, durée, limite de risque, responsable, retour arrière ; expériences
  (petit budget Ads, page d'atterrissage, format social, séquence de relance, plancher de prix, forfait, nouvelle ville, script d'estimation, moment de demande d'avis).
- **M9.19 Gouvernance / validation humaine** : demande d'approbation stratégique (dépense réelle, budget marketing, embauche/licenciement, camion/équipement/
  bâtiment, dette, prix globaux, message client sensible, publication sensible, décision fiscale/légale, suppression de données, contrat, engagement financier),
  champs : type, résumé, montant, risque, départements touchés, action recommandée, alternatives, dossier de preuves, besoin de Nathan/CPA/avocat/admin, statut.
- **M9.20 Mémoire stratégique (M10)** : décisions, hypothèses, recommandations, plans, risques, occasions, résultats d'expériences, rapports, raisons de refus,
  validations, leçons, erreurs de prédiction ; avant une recommandation majeure : charger décisions passées, plans actifs, erreurs, objectifs de Nathan, contraintes,
  état des départements.
- **M9.21–22 Tableau de bord exécutif et briefing mobile** : score de santé de l'entreprise, risque de trésorerie, tendance des revenus, santé du pipeline, ROI
  marketing, capacité, risque de cédule, préparation de l'inventaire, risque client/plaintes, charge d'équipe, conversion, risque de marge d'estimation, principaux
  risques/occasions/priorités, décisions en attente, actions en retard, plan de la semaine, perspective 30 jours, prévision 13 semaines ; mobile admin : briefing du
  matin, alertes critiques, décisions en attente, recommandations, rapport hebdo, questions stratégiques, impact d'une décision, scénarios.
- **M9.23 Évaluation et confiance** : factualité, ancrage dans les sources, qualité de décision, détection de risques, cohérence, fraîcheur, taux d'hallucination,
  sécurité des actions, suivi des résultats d'affaires, taux d'acceptation humaine ; jeux de questions de référence, juge de qualité de décision, vérificateur
  d'ancrage ; **pas de niveau « vérifié » si les recommandations ne sont pas évaluées**.
- **Autres exigences** : rapports quotidien/hebdo/mensuel/trimestriel, plans 7 j/30 j/90 j/12 mois ; traces complètes (question, contexte, instantanés, débat du
  conseil, options, analyse de risques, recommandation, critique, approbation, modèle, coût, latence, score) ; sécurité (PII masquée, aucune donnée client envoyée
  à un modèle externe sans politique, RBAC, outils externes seulement via un courtier sécurisé, bac à sable d'actions) ; tâches automatiques déterministes
  (salle de guerre quotidienne, rapport hebdo, radar de risques/occasions, notification de décisions en attente, suivi d'actions, revue mensuelle) qui ne peuvent
  jamais valider une décision majeure, dépenser, changer un budget/prix, envoyer un message sensible ou signer.
- **Tests visés** : fraîcheur, contradictions, définitions de métriques, classification de décisions, options, score de risque, priorisation, scénarios, rapport,
  politique d'approbation, permissions d'action ; instantanés M1…M10 → M9 ; action M9 → tâche de département ; E2E (rapport hebdomadaire complet ; « augmenter
  Google Ads de 25 % ? » avec risque de capacité/trésorerie et approbation ; trésorerie serrée → plan sans achat risqué ; trop de leads pour la capacité ;
  occasion dans une nouvelle ville avec expérience ; risque de réputation après pic de plaintes).
