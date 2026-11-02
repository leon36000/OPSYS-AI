# M4 — Field Operations OS : équipes, cédule, dispatch, GPS, terrain, optimisation, exécution et fin de chantier (condensé fonctionnel du prompt de Nathan, 2026-06-09)

(« GRS » = ancien nom d'OPSYS-AI.) But : le **système nerveux terrain**. Pas un calendrier, pas une liste de jobs, pas un GPS bricolé. M4 sait qui travaille, qui est disponible et
compétent, où sont les équipes, quoi faire aujourd'hui/demain, quel chantier est prêt ou risqué, quel matériel est requis, quelle route est optimale, quelle météo peut bloquer,
quel client notifier, quand l'équipe part/arrive/commence/termine, quel matériel a été utilisé, quelles photos/preuves existent, et quand déclencher inventaire, facture,
paiement, avis client, marketing, analytique et mémoire. Éviter : équipe au mauvais endroit, client oublié, rendez-vous non confirmé, matériel manquant, route inefficace,
équipe surchargée, mauvaise priorisation, météo ignorée, retard non communiqué, travaux sans preuve, matériel non enregistré, facture non déclenchée, client sans
notification, marge détruite par la planification, GPS exposé trop longtemps au client, promesse impossible. Ne pas reconstruire M2/M3/M5/M6 ; **ne pas inventer une cédule
disponible que M4 n'a pas validée** ; pas de GPS client hors fenêtre de confidentialité ; pas de facture finale sans règles/validation.
Chaîne : vente acceptée → chantier planifié → équipe envoyée → client informé → travaux exécutés → matériel enregistré → photos/preuves → facture déclenchée → inventaire à jour → analytique → mémoire.

## Fonctions attendues
- **M4.1 Modèle de données terrain** : équipes, employés, véhicules, équipements, chantiers, visites, tâches, créneaux, plans de route, arrêts, tournées, pings GPS, évènements de
  géorepérage, sessions de travail, listes de contrôle, matériel utilisé, photos, notifications client, retards, incidents, demandes de changement, évènements d'achèvement, scores
  d'équipe, instantanés de risque météo ; tout évènement terrain traçable.
- **M4.2 Profils d'équipe et d'employé** (rôle, compétences et niveau, permis, disponibilité, horaire, zone préférée, charge, préférences, historique de retards/qualité/incidents,
  complétion de listes de contrôle, rétroaction client). **Pas de surveillance abusive** : pas d'étiquette psychologique, pas de sanction RH automatisée, pas de données de santé,
  décision RH jamais finale ni automatique ; seulement des signaux opérationnels légitimes reformulés (adéquation d'équipe, risque de fatigue, équilibre de charge, signal de
  stress opérationnel, compatibilité d'équipe, risque de sécurité, tendance de performance) ; validation humaine pour toute décision sensible.
- **M4.3 Compétences / rôles / certifications** (gouttières, descentes, soffite, fascia, revêtement, réparation, hauteur, échafaudage, échelle, remorque, camion, service client,
  urgence, diagnostic, finition, photo) ; exigences du chantier (compétence X, niveau Y, véhicule/équipement, deux personnes, expérience, validation des chantiers risqués) ;
  admissibilité des équipes.
- **M4.4 Disponibilité et feuilles de temps** : horaire, congés, indisponibilités, pointage entrée/sortie, déplacement, chantier, pauses, risque de temps supplémentaire,
  demande de correction avec approbation admin, **export vers M5** (M4 prépare les temps ; M5 fait la paie finale).
- **M4.5 Admission d'un chantier depuis CRM/estimation** (client, adresse, service, soumission acceptée, estimation, durée, matériaux, risques, photos, notes, fenêtre, priorité,
  dépôt, statut financier) ; un chantier ne va pas en cédule finale si : adresse absente, client non confirmé, soumission non acceptée, info critique manquante, matériel
  impossible, risque non validé, dépôt requis flou.
- **M4.6 Préparation du chantier** : client confirmé, adresse validée, soumission acceptée, service clair, matériaux connus, durée estimée, équipe admissible, météo acceptable,
  inventaire prêt, facturation/dépôt OK, photos suffisantes, risques traités, fenêtre client connue → {prêt, score, raisons bloquantes, action recommandée, planifiable
  provisoirement, expédiable}.
- **M4.7 Planification intelligente** (fenêtres client, durée, déplacement, compétences, véhicules, équipement, matériel, priorité, urgence, météo, distance, zones, heures,
  pauses, temps supplémentaire, préférences, fatigue, regroupement de petits chantiers, proximité, chantiers météo-sensibles, forte marge, client à risque) ; M4 propose
  automatiquement ; confirmation client et changements majeurs selon la politique de validation ; conflits, capacité, explication.
- **M4.8 Optimiseur de tournées (VRP/VRPTW)** : véhicules = équipes, chantiers = visites, dépôt, fenêtres horaires, durée de service, matrice de déplacement, capacité de journée,
  compétences, priorités, pauses, durée maximale ; objectifs (minimiser déplacement, maximiser chantiers complétés, respecter fenêtres/compétences/journée, réduire temps
  supplémentaire/retards/kilomètres, prioriser urgence/marge, équilibrer la charge) ; si pas de solution parfaite → meilleure solution + chantiers non planifiés + raison ;
  simulation, ré-optimisation, explication ; comparaison éventuelle de solveurs.
- **M4.9 Couche fournisseur de routage** : matrice statique locale, OSRM/Valhalla auto-hébergés, OpenRouteService, GraphHopper, Google/Mapbox (avec trafic, derrière une
  décision de budget), repli par distance approximative ; priorité : cache → auto-hébergé → trafic payant → approximation ; l'optimiseur ne dépend pas d'un seul fournisseur.
- **M4.10 Météo et risque terrain** : température, pluie, neige, verglas, vent, rafales, humidité, orages, alertes, chaleur/froid extrêmes, visibilité, prévision horaire et 8 jours ;
  chantiers sensibles (hauteur, revêtement, scellant/adhésif, échelle, longs travaux extérieurs, client sensible au retard) ; {risque, facteurs, action recommandée, sécuritaire
  d'expédier} ; **une météo critique n'annule pas automatiquement sans politique** : elle bloque ou demande validation selon le niveau.
- **M4.11 Score d'adéquation d'équipe** (compétences, distance, horaire, équilibre de charge, client, complexité, équipement, sécurité, fatigue, fiabilité) avec signaux
  permis (compétences, expérience, retards, qualité des listes, capacité, surcharge, distance, matériel, type de chantier, préférences opérationnelles non sensibles) et
  **interdits** (santé privée, jugement psychologique, profilage discriminatoire, sanctions automatiques, données hors contexte) ; explication lisible, revue admin.
- **M4.12 Tableau de dispatch** : aujourd'hui, semaine, carte, vue équipes, file de chantiers, prêts à planifier, bloqués, plans de route, GPS en direct, en retard, risques
  météo, notifications client, file d'achèvement ; glisser-déposer, assigner, proposer/confirmer la route, notifier, suivre les retards, replanifier, voir matériel/risque/photos,
  clôturer avec validation.
- **M4.13 GPS en direct et géorepérage** (ETA, sécurité, preuve d'arrivée/départ, optimisation, notification client, fin de chantier, analytique) **sans surveillance abusive** :
  suivi actif seulement pendant les heures/trajets de travail, employé informé, client voit position/ETA seulement avec notification active et pour son chantier, expiration
  automatique, pas d'historique client, accès admin journalisé, rétention selon politique ; géorepérages (dépôt, chantier, fenêtre de suivi client) ; évènements (quitté le
  dépôt, arrivé près du chantier, démarré, quitté le chantier, retour au dépôt, arrêt inattendu, arrivée en retard).
- **M4.14 ETA client / fenêtre de suivi** : « l'équipe est en route », ETA, carte limitée, arrivée, retard, contact, consignes, fin des travaux, facture/paiement via M5, avis ;
  lien sécurisé à jeton, expiré à la fin ou après un délai.
- **M4.15 App mobile employé** (hors ligne d'abord) : cédule, route, client/adresse, notes, photos d'estimation, matériel requis, pointage, départ du dépôt, arrivée, démarrage,
  pause, fin, matériel utilisé, photos avant/après, incident, support, demande de changement, signature client si requise ; file locale, reprise de synchro, conflits,
  téléversement de photos en arrière-plan, GPS en tampon, horodatages local + serveur.
- **M4.16 Exécution de chantier** : états (brouillon, prêt à planifier, planifié, confirmé, matériel prêt, assigné, en route, arrivé, démarré, en pause, bloqué, terminé en
  attente de revue, terminé vérifié, facturé, fermé, annulé, replanifié) ; machine à états avec politique de transition ; listes de contrôle ; sessions de travail ;
  chronologie ; chaque changement d'état audité.
- **M4.17 Déclencheur de fin de chantier (le cœur)** : avant d'accepter « travaux terminés » : temps réel, matériel utilisé, photos après, liste de contrôle terminée, notes
  d'imprévus, signature si requise, confirmation de l'adresse, statut d'incident ; déclenche M6 (retrait du matériel, stock bas, besoin de commande), M5 (brouillon de facture,
  coût réel, lien de paiement, AR, validation si montant/ordre de changement), M2 (chantier complété, activité, prochaine action), M7 (demande d'avis, contenu avant/après si
  consentement), M8 (temps réel vs prévu, marge prévue vs réelle, performance d'équipe), M10 (évènement, écarts, leçons) ; **si matériel utilisé ≠ prévu ou photos/liste manquantes
  → « terminé en attente de revue », pas « vérifié »**.
- **M4.18 Matériel utilisé et synchro d'inventaire** (utilisé, supplémentaire, non utilisé, perte, bris, achat sur place avec photo du reçu, note) ; envoi à M6 (chantier, équipe,
  matériaux, quantités, pertes, retours, achat, horodatage, confiance, revue requise) ; détection d'écarts.
- **M4.19 Preuves terrain** (photos avant/pendant/après, dommage, accès, matériel, signature, note, liste de contrôle, GPS d'arrivée, temps) ; exigences de photos, contrôle de
  qualité, lot de preuves ; **photos de maisons clients = données sensibles ; aucun usage marketing sans consentement ou validation**.
- **M4.20 Incidents, retards, ordres de changement** (client absent, mauvaise adresse, accès bloqué, matériel manquant, météo, danger, dommage découvert, travaux plus gros,
  retard, plainte, équipement brisé, employé malade) ; un ordre de changement qui augmente le prix = validation humaine + M3/M5/M2.
- **M4.21 Replanification et expédition de secours** (équipe en retard, chantier plus long, annulation, météo, matériel manquant, véhicule brisé, urgence, absence) : recalcul,
  déplacement, appel au client via M1, notification admin, équipe alternative, blocage, plan de secours.
- **M4.22 Analytique opérationnelle** (chantiers planifiés/complétés/replanifiés, arrivée à l'heure, déplacement, durée estimée vs réelle, matériel estimé vs utilisé, qualité,
  conformité des photos, attente client, utilisation d'équipe, risque de temps supplémentaire, retards météo, efficacité de route, conformité du suivi GPS) ; alimente M8/M9.
- **M4.24 Mémoire (M10)** : assignations, routes, retards, incidents, durées réelles, matériel réel, erreurs d'estimation, problèmes client, performance d'équipe, météo,
  changements de cédule, décisions admin, leçons ; avant un changement critique de cédule : lire la mémoire et vérifier les décisions précédentes.
- **Flux** : A soumission acceptée → chantier planifiable ; B planification quotidienne (chantiers prêts, équipes, véhicules, météo, matrice, solveur, explication, plan de
  dispatch, revue admin, notifications) ; C équipe en route ; D chantier démarré ; E travaux terminés ; F retard/météo/incident.
- **Sécurité/Loi 25** : GPS minimisé, suivi client à jeton expirant, accès admin aux journaux GPS audité, PII masquée, photos/signatures protégées, RBAC, aucun suivi hors
  travail, politique de rétention, consentement employé documenté, transparence, vérification des webhooks, limitation de débit.
- **Tests visés** : préparation, conflits de cédule, construction du problème VRP et contraintes, cache de matrice, risque météo, score d'équipe, confidentialité GPS,
  géorepérage, validation de fin de chantier, validation du matériel, export de temps, machine à états ; intégrations (quote acceptée → chantier, estimation → durée/matériaux,
  M6 → préparation du matériel, M5 → dépôt, cédule → notification client, ping GPS → ETA, fin → inventaire/facture/analytique/mémoire) ; E2E (soumission acceptée → planifié,
  optimisation d'une journée de 3 équipes et 8 chantiers, en route avec ETA et jeton client expirant, travaux terminés avec toute la chaîne, vent fort qui bloque, incident de
  matériel manquant avec replanification).
- **Critères de sortie** : VRP de production, couche de routage, météo, scoring sans données sensibles, dispatch, flux mobile employé, GPS/ETA respectant la confidentialité,
  déclencheur de fin de chantier, synchro M6, brouillon M5, mise à jour M2, évènements M8/M10, incidents/replanification, export de temps vers M5, tests, docs, matrice ;
  aucune promesse client impossible, aucun GPS abusif, aucune action financière/RH sensible sans validation.
