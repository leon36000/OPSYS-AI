# M3 — Estimation Intelligence : vision IA, mesure, géospatial, coûts, risque, prix, marge, soumission, apprentissage terrain (condensé fonctionnel du prompt de Nathan, 2026-06-08)

(« GRS » = ancien nom d'OPSYS-AI.) But : transformer un lead qualifié en estimation **exploitable, vérifiable, rentable et prête à devenir soumission**. Protéger contre
sous-estimation (marge détruite), surestimation (vente perdue) et **fausse précision**. Toute estimation produit : estimation, plage de confiance, hypothèses,
données utilisées, données manquantes, risques, incertitudes, informations à collecter, marge attendue, prix recommandé, preuves visuelles/géospatiales, statut
de validation humaine. Jamais « c'est exact » si la mesure vient d'une photo insuffisante. Ne pas reconstruire M2/M5 ; ne pas inventer coûts/prix sans source ;
pas de soumission officielle sans validation selon seuil ; pas de « vérifié » sans les portes/gates documentés.

## Sous-modules attendus
- **M3.1 Admission** : recevoir le lead propre de M2 (client, propriété, adresse, service, photos/vidéos/360, notes de réception, urgence, délai, source, historique,
  signal de budget, contraintes d'accès, ville), vérifier la préparation → {prêt, score, données manquantes, raison bloquante, action suivante}, demande
  d'information manquante.
- **M3.2 Contexte de propriété et de site** : adresse normalisée, géocodage, Street View comme **contexte seulement** (jamais substitut aux photos récentes du
  client), photos historiques, données publiques/cadastre si accessibles, notes d'employés, anciennes interventions, profil de propriété M2, mémoire, zone
  desservie, distance, accès, hauteur probable, risques, historique des travaux, confiance géospatiale.
- **M3.3 Pipeline de vision (sans halluciner)** : validation du fichier, masquage PII, qualité d'image, orientation, classification de scène, détection
  d'éléments, segmentation, mesures possibles, incertitude, annotations, rapport visuel. Éléments : gouttière, descente, coin, fascia, soffite, revêtement,
  fenêtre, porte, mur, toit, corniche, dommage, infiltration, hauteur, obstacle, arbre, galerie, entrée, pente, accès difficile. Confiance basse → pas de
  mesure finale : demander des photos ou une visite.
- **M3.4 Qualité des photos et confiance de mesure** : résolution, flou, angle, distance, éclairage, obstruction, perspective, objet complet, échelle connue,
  multi-angles, EXIF, référence de taille, zone coupée, doublons, cohérence ; scores (qualité, faisabilité de mesure, confiance visuelle, confiance d'échelle,
  couverture) ; **demande de photos précise** (« il nous manque une photo de face complète… »).
- **M3.5 Segmentation / détection** : détection par texte (Grounding DINO) + segmentation (SAM2) + géométrie (contours, longueurs relatives, surfaces, angles)
  → mesure métrique si échelle suffisante ; registre de modèles et santé ; **SAM2 en production sur GPU = décision de Nathan** : sinon repli (mesure manuelle,
  OpenCV de base, annotation humaine, qualité de photo seulement, estimation par règles).
- **M3.6 Moteur de mesure** : longueur de gouttière, nombre de descentes, hauteur, surface de revêtement, longueur de fascia, surface de soffite, zones
  endommagées, distance d'accès, pente/complexité ; sources : mesures manuelles, photos avec échelle, multi-angles, 360/LiDAR, Street View (contexte),
  historique, formules par type de bâtiment, visite. **Une seule photo sans échelle = plage ou hypothèse, jamais une mesure exacte.** Sortie : valeur, bornes,
  confiance, méthode, revue humaine requise.
- **M3.7 Estimation géospatiale** : adresse normalisée, distance et temps de déplacement, zone, conditions locales, accès, ajustement régional des prix,
  difficulté par zone, jeu de données de construction QC.
- **M3.8 Estimateurs par service** : gouttières/descentes (longueur, coins, descentes, hauteur, type, accès, matériau, retrait, obstacles, déplacement,
  urgence), revêtement extérieur (surface, matériau, démolition, membrane, moulures, ouvertures, hauteur, échafaudage, complexité, perte), soffite/fascia
  (longueur, largeur, ventilation, hauteur, accès, dommage), réparation (zone, urgence, difficulté, déplacement, diagnostic, temps minimum, matériel) ; registre
  d'estimateurs, classificateur de service.
- **M3.9 Calcul matériaux et main-d'œuvre** : prix de M6 (sinon livre de prix interne versionné marqué « repli »), catalogues, historiques M5, fournisseurs,
  taxes, marge, durée, équipe nécessaire, déplacement, location, sous-traitance, pertes, imprévus ; priorité des sources de coût.
- **M3.10 Risque et complexité** : hauteur, accès difficile, pente, arbres, fils électriques, retrait d'ancien matériel, urgence, client loin, mauvaises
  photos, incertitude de mesure, météo, équipe spécialisée, couleur spéciale, matériel non stocké, petit chantier non rentable, chantier trop loin, risque
  relationnel ; score, niveau, facteurs, marge tampon recommandée, revue humaine.
- **M3.11 Prix et marge** : coûts, déplacement, frais généraux, marge cible, risque, saison, capacité, concurrence si connue, urgence, taille, minimum
  rentable, stratégie M9, conversion M2, rentabilité réelle M5, inventaire M6, source M7 ; prix minimum / recommandé / agressif / prudent, marge attendue,
  risque de marge, conditions, validation. **Jamais un prix sous le minimum rentable sans alerte rouge et validation de Nathan.**
- **M3.12 Monte Carlo / incertitude** : distributions (longueur, surface, coût matériel, temps, complexité, déplacement, météo, marge, conversion),
  sensibilité, intervalles, scénarios ; sortie coûts et prix p50/p80, probabilité de risque de marge, facteurs d'incertitude dominants.
- **M3.13 Générateur de soumission brouillon** : client, adresse, service, description, matériaux, exclusions, hypothèses, références photo, prix, taxes,
  délai, conditions, validité, options, ventes additionnelles, notes internes, niveau de confiance, résumé lisible par le client, PDF, envoi au CRM,
  demande d'approbation.
- **M3.14 Revue et approbation humaines** : file de revue, politique, journal des ajustements humains ; validation obligatoire si confiance sous seuil,
  montant au-dessus du seuil, marge sous seuil, photos insuffisantes, mesure incertaine, service complexe, client à risque, chantier loin, prix sous le
  minimum, donnée fournisseur absente.
- **M3.15 Apprentissage estimé vs réel** : comparer matériel, temps, prix vs facture, marge prévue vs réelle, risques prévus vs réels, par service, ville,
  équipe, fournisseur, saison ; analyse des écarts, calibration des estimateurs et du modèle de prix, mémoire de leçons ; chaque erreur devient mémoire et
  amélioration de règle. (Un chantier d'apprentissage des durées par type de travaux et par équipe est déjà en cours côté OPSYS-AI : ne pas le dupliquer.)
- **M3.16 Jeux de données / RAG construction Québec** : contrats, soumissions, factures, matériaux, prix, chantiers, photos, temps, erreurs, marges, villes,
  fournisseurs, commentaires ; sources externes (listes de prix, guides d'installation, fiches techniques, bonnes pratiques, météo, jeux de données de
  vision, données géospatiales publiques, documents validés) ; jamais de mélange de données clients privées non anonymisées avec des jeux externes ;
  règles validées ; graphe d'estimation.
- **M3.17 Tableau de bord et mobile** : estimations à faire/bloquées, photos manquantes, à valider, risque de marge, prix sous minimum, envoyées, acceptées,
  écart estimé/réel, services et villes rentables, état SAM2, file de vision ; mobile vendeur/admin (lead prêt, demander des photos, annoter, mesure
  manuelle, lancer l'estimation, comparer les scénarios, approuver, envoyer au CRM, voir risques et marge, demander une visite) et employé après chantier
  (matériel réel, temps réel, imprévus, photos finales, notes, comparaison à l'estimation).
- **Intégrations** : M2 (reçoit lead/client/propriété/photos/notes/source/pipeline ; renvoie statut, manque, brouillon, montant, confiance, approbation,
  raison bloquée), M1 (demander photos/adresse/clarification), M4 (capacité, équipe, coût de déplacement, contraintes de planning), M5 (marges historiques,
  coûts réels, rentabilité ; envoie prix, marge prévue, devis accepté, besoin de dépôt), M6 (prix, stock, fournisseur, délai, alternative), M7 (services
  demandés, objections de prix, villes, raisons de refus, demandes non rentables, contenu avant/après), M8 (taux estimation→soumission→vente, marge prévue/
  réelle, erreur d'estimation), M10 (hypothèses, mesures, risques, prix, décisions, erreurs, corrections, ajustements humains, règles validées).
- **Flux** : A lead → estimation complète ; B photo insuffisante (angles manquants → message précis → tâche → blocage du prix final → reprise) ; C SAM2
  indisponible → repli documenté ; D estimation → soumission (options, exclusions, marge, risque, brouillon, CRM, relance) ; E après chantier → apprentissage.
- **Sécurité** : jamais de photos clients publiques, PII masquée, stockage sécurisé, permissions, audit, pas d'entraînement sur photos privées sans
  anonymisation/consentement, pas de scraping Street View interdit, clés sécurisées, coûts d'API contrôlés, validation pour prix final risqué.
- **Tests** : préparation, qualité de photo, détection/segmentation simulées, bornes de mesure, estimateurs (gouttières, revêtement, soffite/fascia,
  réparation), calculs de matériaux/main-d'œuvre, risque, prix, Monte Carlo, politique d'approbation, brouillon ; intégrations (lead M2 → admission,
  photo → qualité, repli sans SAM2, mesure manuelle → estimateur, estimation → prix, → brouillon → M2, livre de prix de repli, signal de marge M5, mémoire) ;
  E2E (gouttières avec photos suffisantes, photos insuffisantes sans prix final, revêtement avec incertitude, estimation risquée avec approbation obligatoire,
  estimé vs réel avec calibration, contexte géospatial Québec avec coût de déplacement).
- **Critères de sortie** : aucune estimation ne prétend être précise sans preuve ; photos insuffisantes bloquent le prix final ; SAM2 branché ou gate documenté
  avec repli ; E2E géospatial QC ; approbation humaine ; mémoire ; docs ; matrice à jour.
