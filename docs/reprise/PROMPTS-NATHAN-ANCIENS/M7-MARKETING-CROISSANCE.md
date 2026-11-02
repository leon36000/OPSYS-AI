# M7 — Marketing & Croissance IA (condensé fonctionnel du prompt de Nathan, juin 2026)

But : un **CMO IA complet** pour une PME de construction/rénovation extérieure, qui soutient la croissance réelle par tous les canaux
légitimes (réseaux sociaux, visibilité locale, notoriété, SEO, PPC, branding, réputation, contenu, campagnes, stratégie, concurrence,
relances, conversion, marketing physique/local) et pas seulement SEO/PPC. Optimise : visibilité, notoriété, abonnés/likes/commentaires/
partages, leads, conversion, coût par lead, coût par vente, réputation/avis, SEO local, performance publicitaire, rentabilité, suivis,
récurrence, bouche-à-oreille, image de marque.

## Règles absolues (à vérifier qu'elles sont déjà des garde-fous réels)
Ne pas reconstruire CRM/compta (s'y connecter). Aucune dépense pub / budget / campagne payante / publication publique sensible / réponse
à avis négatif / envoi massif sans validation humaine. Jamais de bots, faux likes/abonnés/commentaires, spam, scraping interdit,
contournement de limites API ; croissance organique, conforme, mesurable. Préférer les API officielles ; sinon workflow manuel assisté.
Toujours distinguer : automatisable maintenant / exige OAuth-clés / exige validation Nathan / exige approbation de plateforme / reste
manuel. Chaque action trace : qui, quoi, pourquoi, source, modèle, confiance, coût, risque, statut. Toute recommandation liée à une
donnée ou marquée hypothèse. Toute sortie publique passe par une porte qualité (ton, exactitude, conformité, marque, risque,
validation). Français québécois professionnel. Exactitude > vitesse.

## Sous-modules attendus
- **M7.1 Identité de marque (Brand Core)** : profil de marque, ton de voix, services, promesse, avantages, zones, valeurs, objections
  fréquentes, arguments, garanties, preuve sociale, messages et mots interdits, style photo/vidéo par plateforme ; livre de marque
  (JSON), guide de ton, règles de validation, **score de conformité d'un contenu**, audit de contenu, génération de lignes directrices.
- **M7.2 Centre de commande réseaux sociaux** : Facebook, Instagram, TikTok, YouTube/Shorts, LinkedIn, Google Business Profile
  (+ Pinterest, Threads éventuels) ; calendrier éditorial, planification, brouillons, publication assistée, suivi de performance, idées,
  transformation chantier → contenu, hashtags, CTA, variantes par plateforme, recyclage de contenu, banque de contenu, statut
  d'approbation, historique ; adaptateurs par plateforme avec repli **export manuel** (texte, hashtags, média, miniature, heure
  recommandée, instructions, liste de contrôle) quand l'API officielle ne permet pas la publication ; chaque adaptateur déclare
  actions supportées, identifiants manquants, portées requises, limites de débit, dernière erreur, notes de conformité.
- **M7.3 Usine de contenu** : sources (CRM, photos avant/après, notes de chantier, services vendus, ville, témoignages, avis Google,
  FAQ, objections, matériaux, saison, météo, promotions, réalisations, vidéos courtes) → types (post FB, carrousel IG, Reel, TikTok,
  Short, post Google Business, article SEO, page locale, courriel, SMS, brochure, flyer, scripts vidéo/appel/vendeur, description avant/
  après, étude de cas, campagne saisonnière) ; briefs, générateur, recycleur, bibliothèque d'actifs (statut vie privée, droits d'usage) ;
  **flux chantier terminé → angles → variantes multi-plateformes → conformité marque → risque de confidentialité → brouillons →
  validation → publication/export → mesure → apprentissage**.
- **M7.4 Moteur de croissance** : croissance d'audience, engagement, formats gagnants, meilleurs horaires, calendrier de croissance,
  collaborations locales, concours conformes, campagnes de notoriété, stratégie de hashtags, séries de contenu, rétention vidéo,
  recommandations par plateforme, plan 30 jours. Interdit : achat de followers, faux likes, pods, spam, DM massifs, automation contre ToS.
- **M7.5 Réputation** : suivi des avis Google, demande d'avis après chantier (semi-automatique seulement si chantier marqué satisfait),
  brouillons de réponse (publique = validation humaine ; avis négatif = validation obligatoire + alerte admin), détection client
  satisfait/à risque, extraction de témoignages → contenu, note moyenne, recommandations.
- **M7.6 SEO local et contenu** : Search Console, suivi de positions (SerpBear), pages locales, articles, FAQ, titres/meta, maillage
  interne, cannibalisation, suggestions de pages, baisse de trafic, SEO local, Google Business Profile.
- **M7.7 Médias payants / intelligence publicitaire** : Google Ads (Search, Performance Max), Meta Ads, TikTok/YouTube Ads, retargeting,
  campagnes locales ; lecture de campagnes, coût par lead/vente, budgets suggérés, mots-clés négatifs, analyse d'annonces et de pages
  d'atterrissage, créatifs, qualité des leads, attribution CRM, alerte gaspillage ; simulateur de budget. **Toute modification réelle
  (campagne, budget, enchère, dépense, pause) = demande d'approbation (admin/Nathan).**
- **M7.8 ROI et attribution** : source du lead (normalisée, UTM), coût par lead, coût par vente, marge estimée par service, ROI par canal,
  valeur moyenne client, villes et services rentables, campagnes à couper/augmenter, recommandations, export de rapport. Sources : CRM,
  compta, factures, pipeline, campagnes, Search Console, Ads, Matomo, réseaux, formulaires, appels, GBP.
- **M7.9 Intelligence concurrentielle** : concurrents, positions, offres visibles, sites publics, GBP/réseaux publics si conforme,
  avis comparés, messages, opportunités, différenciation ; pas de scraping interdit ; si incertain → tâche de recherche manuelle assistée ;
  toujours source + niveau de confiance.
- **M7.10 Marketing hors ligne / local** : lettrage camions/remorques, pancartes de chantier, flyers, cartes d'affaires, partenariats
  locaux, commandites, événements, **programme de référence**, rabais de voisinage, bouche-à-oreille, uniformes, affichage local.
- **M7.11 Conseiller CMO stratégique** : diagnostic, plan 30/60/90 jours, priorités de croissance, stratégie saisonnière, expansion
  ville/service, analyse de marque, prix/offres, contenu, réputation, réseaux, risques, plan d'exécution ; briefs de campagne ; **rapport
  hebdomadaire** ; question libre au CMO.
- **M7.12 Tableaux de bord** (admin) : leads de la semaine, coût par lead, meilleurs canaux, croissance abonnés, engagement, posts
  planifiés, contenus à valider, campagnes actives, avis, recommandations, risques, prochaines actions ; centre social (calendrier,
  brouillons, aperçu multi-plateforme, score qualité, approuver/refuser) ; usine de contenu ; réputation ; ROI ; conseiller CMO.
- **M7.13 App mobile** : admin (tableau marketing, contenus à approuver, avis, rapport hebdo, recommandations, calendrier) ; vendeur
  (suggestions de contenu terrain, demander photo avant/après, mini-témoignage, signaler client satisfait) ; employé (fin de chantier :
  photos avant/après, notes, autorisation client, qualité, client satisfait oui/non, potentiel de contenu — **l'employé ne publie pas, il
  alimente l'usine de contenu**).
- **Mémoire marketing** : brand book, contenus publiés et performances, campagnes, posts gagnants/faibles, objections, avis, concurrents,
  stratégies validées, rapports, décisions de Nathan, règles, angles qui marchent, villes et services rentables ; chaque mémoire avec
  source, date, type, canal, performance, confiance, statut.
- **Porte qualité du contenu** : scores (conformité marque, clarté, adéquation plateforme, conversion, authenticité, risque vie privée,
  risque de conformité, risque d'exagération, orthographe, pertinence locale). **Bloquer** : promesse non vérifiable, garantie ou prix
  inventé, photo client sans autorisation, adresse client visible, visage/plaque visible sans autorisation, exagération illégitime, ton
  non conforme, contenu offensant, réponse à avis négatif sans validation.
- **Niveaux de risque** : 0 lecture ; 1 brouillon ; 2 tâche interne ; 3 publication faible risque (validation au départ) ;
  4 campagne/budget (validation Nathan) ; 5 réputation sensible (validation Nathan) ; 6 légal/financier (interdit sans humain).
- **Boucles de travail** : A chantier terminé → contenu social ; B rapport marketing hebdomadaire (leads par canal, coût, conversion, ROI,
  croissance, engagement, top/flops, opportunités → recommandations priorisées → tâches) ; C campagne saisonnière (saison/besoin →
  historique CRM → rentabilité compta → service prioritaire → offre → brief page d'atterrissage → contenu → campagne brouillon → plan
  hors ligne → budget → validation → suivi) ; D avis client → réputation → contenu.
- **Automatisations déterministes** (n8n à l'époque) : synchro quotidienne des métriques, chantier terminé → contenu, alerte d'avis,
  rapport CMO du lundi, rappel de trous de calendrier. Les actions publiques passent par l'approbation.
- **Critères de sortie** : département non limité à SEO/PPC ; calendrier et approbation fonctionnent ; chantiers génèrent du contenu ;
  ROI lit CRM/compta ; réputation ; CMO fondé sur données ; actions risquées bloquées ; publications publiques validées ; tests (unitaires,
  intégration, E2E chantier gouttières à Repentigny : 5 contenus, porte qualité, approbation FB + GBP, publié/exporté, métriques, rapport) ;
  documentation ; matrice fidèle ; traces ; aucun secret en dur ; API externes derrière adaptateurs ; **mode export manuel sans identifiants**.
  Si un connecteur manque à cause d'OAuth : « PARTIEL — GATE NATHAN ».
