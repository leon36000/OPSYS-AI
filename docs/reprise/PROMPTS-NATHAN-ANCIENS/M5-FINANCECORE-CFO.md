# M5 — FinanceCore : comptabilité, finance, contrôle, pré-audit, paie, fiscalité et CFO IA (condensé fonctionnel du prompt de Nathan, 2026-06-08 + addendum)

But : faire de M5 le **département financier IA gouverné** : comptable IA, pré-comptable, contrôleur, analyste de trésorerie, auditeur interne,
assistant fiscal prudent, connecteur QuickBooks/CCube, moteur de rentabilité, **CFO IA** (stratégie, projections, achats majeurs, emprunt,
investissement, bâtiment). M5 existe déjà et est avancé : **ne pas le reconstruire**, le durcir, l'unifier, le connecter, le gouverner.
Formule imposée sur toute sortie stratégique/fiscale : « Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute
décision officielle ou action réelle. » Chaque sortie distingue fait vérifié / hypothèse / suggestion / risque / action proposée / action
exigeant validation / donnée manquante.

## Interdit sans validation humaine (demande d'approbation financière créée)
Paiement fournisseur/employé/impôt/taxe, virement, remboursement, modification comptable finale, déclaration/télé-déclaration officielle
(TPS/TVQ, impôt société, T4/RL-1, DAS), changement de taxes, suppression de facture/transaction/client, changement du plan comptable, envoi
de document légal, engagement financier, budget important, fermeture de période, écritures de fin d'année, paie, action RH, action bancaire,
emprunt, achat camion/équipement/bâtiment, signature de contrat, changement de stratégie fiscale. Automatisations permises : lire, classer,
extraire factures/reçus, créer brouillons, proposer écritures et rapprochements, détecter doublons, générer rapports/alertes/tâches,
préparer exports/paquet CPA/brouillons QuickBooks, simuler, noter la confiance, demander validation.

## Fonctions de base attendues (vérifier ce qui existe déjà)
- **Facturation client** : brouillons depuis soumission/chantier/matériel/équipe, statuts (brouillon, en validation, approuvée, envoyée,
  payée, en retard, contestée, annulée), taxes, conditions, PDF, préparation d'envoi, synchronisation QuickBooks si validée ; cycle
  complet soumission acceptée → brouillon → taxes → matériel → client → numérotation → PDF → validation → envoi → paiement → rapprochement.
- **Comptes à recevoir** : vieillissement 0-30/31-60/61-90/90+, clients à risque, relances en brouillon (jamais agressives sans validation),
  séquences, promesses de paiement, litiges, délai moyen de paiement, alerte trésorerie.
- **Comptes à payer** : ingestion de factures fournisseurs, OCR, extraction fournisseur/date/montants/taxes, doublons, catégorisation,
  association chantier/service, échéances, prévision de trésorerie, paiement proposé jamais exécuté.
- **Rapprochement bancaire** : import (CSV, Stripe, QuickBooks, Plaid éventuel), normalisation, appariement paiement↔facture et
  dépense↔facture fournisseur, transactions inconnues, doublons, montants partiels, frais Stripe/banque, fractionnement, **score de
  confiance** (montant exact, date proche, client/fournisseur, numéro de facture, description, historique, source, doublon, frais),
  validation humaine.
- **Taxes TPS/TVQ** : calcul sur factures, extraction sur dépenses, rapports de période préparatoires, anomalies, données pour CPA/Revenu
  Québec ; jamais de télé-déclaration sans validation ; tout est « préparation » sauf preuve officielle.
- **Grand livre / plan comptable** : écritures proposées, piste d'audit, source de chaque écriture, verrouillage de période, retour arrière
  contrôlé, correction documentée, export ; plan comptable versionné et protégé.
- **Rapports** : revenus, dépenses, marges brute/nette estimée, trésorerie, AR/AP, rentabilité par service/ville/équipe/chantier, budget vs
  réel, taxes, rapports CPA, rapport hebdo/mensuel de direction.
- **Rentabilité par chantier** : revenus, matériel prévu/réel, main-d'œuvre, temps estimé/réel, déplacement, frais, marge, écart
  estimation/réel, cause, leçon, recommandation.
- **Prévision de trésorerie** : 7/14/30/60/90 jours puis 13 semaines, 6, 12, 24 mois (5 ans pour scénarios majeurs) ; sources : soldes,
  AR/AP, contrats signés, soumissions probables (taux de conversion CRM), cédule, jalons, dépenses récurrentes, paies, taxes, dettes,
  inventaire, achats prévus, marketing, saisonnalité, historique ~10 ans, capacité des équipes ; scénarios (normal, prudent, optimiste,
  saison faible, mauvais payeurs, retard de chantiers, baisse de leads, hausse de dépenses, achat camion/équipement/bâtiment, embauche,
  hausse marketing, nouvelle dette, retard de taxes, croissance rapide, récession locale) ; Monte-Carlo, sensibilité, autonomie (runway).
- **Pré-audit / contrôle interne** : documents manquants, factures sans paiement, paiements sans facture, dépenses sans reçu, taxes
  incohérentes, doublons, fournisseurs suspects, factures modifiées, transactions hors norme, changements de compte inhabituels, risques
  Loi 25, piste d'audit incomplète.
- **Paquet CPA** : export de période, pièces sources, grand livre, balances, rapports TPS/TVQ, AR/AP, rapprochements, anomalies, notes,
  décisions comptables, journaux de validation, justificatifs, export QuickBooks/CSV.
- **Multi-entités** : entité légale, compagnie, division, département, chantier, centre de coût, consolidation, séparation, permissions.
- **Conformité / Loi 25** : classification, masquage de renseignements personnels, journaux sans secrets, permissions, audit d'accès,
  export contrôlé, suppression contrôlée, rétention, consentement.
- **Intégrations par adaptateurs** (jamais de limites cachées ; chaque adaptateur déclare capacités, identifiants manquants, portées,
  lecture/écriture/webhooks, dernière synchro, dernière erreur, limites de débit, niveau de risque) : QuickBooks Online (OAuth, clients,
  factures, paiements, articles, plan comptable, codes de taxe, webhooks, résolution de conflits, **lecture seule puis dry-run puis écriture
  contrôlée**, bac à sable d'abord), CCube (selon API réelle), Sage/Acomba/Xero/CSV/générique, Stripe (webhooks vérifiés et idempotents,
  frais, remboursements = approbation, rapprochement des versements), banque/Plaid en lecture seule, repli CSV. En cas d'écart GRS ↔ logiciel
  externe : créer un conflit, jamais trancher seul.
- **OCR financier** : upload, antivirus si dispo, OCR, extraction, fournisseur, taxes, totaux, lignes, score de confiance, doublon,
  validation mathématique (sous-total + taxes = total), brouillon de facture fournisseur.
- **Agents internes** : commis, rapprochement, contrôleur, préparation fiscale (jamais déclarer), trésorerie, auditeur (vérifie les autres
  agents, bloque les actions risquées), conseiller CFO ; chacun avec permissions, outils, limites, traces, paquet de contexte mémoire.
- **Niveaux de permission financiers** F0 lecture … F7 fiscal/légal (F6 argent réel : validation Nathan, double confirmation) ; seuils
  configurables (montant faible/moyen/élevé, client sensible, nouveau fournisseur, transaction inhabituelle, taxe incohérente, nouveau
  compte, action externe/irréversible) ; au départ envoi réel de factures = validation (plafond auto 0).
- **Piste d'audit** de toute action (acteur, agent, horodatage, avant/après, raison, source, modèle, prompt, paquet de contexte,
  approbation, trace, preuve). **Mémoire M10** de chaque événement et décision financière (paquets : identité finance, QuickBooks, taxes
  QC, rapprochement, rentabilité chantier).
- **Intégration aux autres départements** : M1 (potentiel financier, pas d'écriture), M2 (client → profil de facturation, QuickBooks
  customer), M3 (coût/marge/taxes de la soumission, projet financier à l'acceptation), M4 (temps réel, coût de main-d'œuvre, déplacement,
  écarts), M6 (coût matériel réel, écart prévu/réel), M7 (coût par lead/vente, profit par canal, ROI réel), M8 (M5 est LA source des
  métriques financières ; M8 ne recalcule pas), M9 (diagnostic, prix, projections, risques), M10 (mémoire).
- **Tableau de bord** et **app mobile** : admin (factures à approuver, paiements, AR en retard, dépenses à valider, trésorerie, anomalies,
  statut CPA, rapport du contrôleur) ; employé (matériel utilisé, photo de reçu, note, confirmation de fin, temps réel ; jamais d'écriture
  finale) ; vendeur (marge estimée de la soumission, statut de paiement, relance autorisée) ; client (facture, statut, lien de paiement, reçu ;
  jamais de marge ni coût internes).
- **Observabilité** (traces par workflow, métriques) et **sécurité** (secrets chiffrés, journaux masqués, moindre privilège, lecture seule
  d'abord, dry-run d'abord, bac à sable d'abord, double confirmation pour l'argent, sauvegarde avant synchro majeure, clés d'idempotence,
  protection contre le rejeu, signature des webhooks, limitation de débit, reprises contrôlées, file de lettres mortes).

## Extension CFO IA (addendum prioritaire)
- **Paie et obligations employeur (en préparation seulement)** : employés, taux, heures, supplémentaires, vacances, jours fériés, primes,
  allocations, avantages imposables ; retenues (RRQ/QPP, RQAP/QPIP, AE/EI, impôts fédéral et Québec, Fonds des services de santé, normes
  du travail), cotisations employeur, CNESST, DAS, remises périodiques, bulletin de paie, projections de paie, **T4 / RL-1 / relevé d'emploi
  préparatoires**. Aucune paie réelle, dépôt direct, remise ou fichier officiel sans validation ; calculs et tables **versionnés par année et
  sourcés** ; tables absentes ou périmées → bloquer. Sortie d'un brouillon : brut, retenues employé, contributions employeur, net, estimation
  des remises, données manquantes, confiance, action officielle bloquée.
- **Conformité fiscale Québec/Canada** : calendrier fiscal vivant (TPS, TVQ, impôt société fédéral et Québec, acomptes provisionnels, DAS,
  CNESST, T4/RL-1, fins de période et d'année), obligations détectées selon le profil, alertes d'échéance, liste de documents, préparation de
  paiement (demande seulement), scan de risques fiscaux. Chaque obligation : type, autorité, période, échéance, montant estimé, source du
  calcul, données manquantes, risque, action recommandée, validation requise. Jamais de taux ou dates codés sans année/source/version.
- **Contrats et cédule → prévision** : carnet signé vs probable, jalons de paiement, dépôt, risques de retard/dépassement, semaine serrée,
  priorisation pour la trésorerie, capacité de production.
- **Conseiller en achats d'actifs (camion, équipement)** : prix, taxes, mise de fonds, paiement, taux, durée, assurance, entretien, énergie,
  productivité, revenus additionnels, économies, trésorerie 13 semaines/12/24 mois, impact fiscal potentiel (CCA), dette, capacité
  d'emprunt, paie/taxes, seuil de rentabilité, conditions avant achat, questions pour CPA/prêteur ; acheter comptant vs financer vs louer ;
  recommandation (acheter maintenant, attendre, financer, louer, comptant, rejeter, données insuffisantes).
- **Conseiller d'achat de bâtiment commercial** : hypothèque commerciale, loyer vs propriété, taxes, assurances, entretien, rénovation,
  zonage, DSCR approximatif, coût d'occupation, stress test revenus −20 % et taux +2 %, liquidités après achat, structure de détention à
  discuter, dossier pour le prêteur, stratégie de négociation, séquence ; validation avocat/notaire/CPA/fiscaliste/prêteur.
- **Conseiller dette / financement / investissement / épargne** : emprunter ou comptant, garder du cash, rembourser la dette, investir
  (marketing, équipement, embauche), réserve d'urgence, rendement minimal ajusté au risque, allocation du capital, fonds de roulement.
  Analyse préparatoire, pas un conseiller réglementé.
- **Réserves et « cash libre réel »** : réserves TPS/TVQ, impôt société, paie, DAS, CNESST/charges, fournisseurs, dettes, urgence, saison
  morte, équipement, marketing, croissance ; **solde bancaire ≠ argent disponible** : cash libre réel = solde − taxes − paies − DAS − AP −
  dettes − obligations − réserves critiques ; ne jamais afficher « disponible » sans les soustraire.
- **Conseiller fiscal/comptable stratégique (gouverné)** : salaire vs dividendes, bonus, timing des dépenses/revenus, achat vs location,
  financement vs comptant, amortissement/CCA, véhicules, avantages imposables, structure corporative et holding à discuter, subventions et
  crédits, fin d'année, questions pour le CPA. Format imposé (question, résumé, données utilisées/manquantes, hypothèses, scénarios, impact
  trésorerie, impact fiscal potentiel, risques, recommandation préparatoire, ce que le CPA/fiscaliste doit valider, prochaines étapes). Jamais un
  avis fiscal officiel.
- **Moteur de décision CFO** : rapport de décision standard en 25 sections (question, résumé, recommandation, confiance, données utilisées/
  manquantes, hypothèses, scénarios prudent/normal/optimiste, trésorerie 13 semaines, projections 6/12/24 mois, impacts taxes/paie/dette/marge/
  croissance, risques, conditions avant d'agir, questions CPA et banque, plan d'action, validation requise) ; classification de la question ;
  comparaison de scénarios ; détection du besoin d'approbation ; table de demandes d'approbation stratégiques (achat véhicule/équipement/
  bâtiment, emprunt, stratégie fiscale, paiement taxes/paie, dépôt officiel, investissement, grosse dépense marketing, embauche, fermeture de
  période, écriture finale).
- **Base de connaissances fiscale/comptable (RAG sourcé)** : sources internes (10 ans de données, factures, contrats, paies, paquets CPA,
  décisions de Nathan, erreurs passées, stratégies validées) et externes (Revenu Québec, ARC, CNESST, normes du travail, documentation
  QuickBooks/Stripe/Plaid, jeux de données publics OCR/classification — licence vérifiée, données privées séparées, PII retirée,
  **jamais de réponse fiscale non sourcée**, ajustement fin seulement pour extraction/classification/OCR, jamais pour inventer des conseils
  fiscaux, jeu de référence validé par Nathan/CPA).
- **Tableau de bord CFO** : cash bancaire / libre réel, réserves, AR/AP, factures en retard, paies/DAS/TPS-TVQ à venir, impôt estimé,
  trésorerie 13 semaines, projections 6/12 mois, carnet signé/probable, marges par chantier/service/ville, dettes, capacité d'emprunt, décisions
  en attente, achats proposés, risques fiscaux et de trésorerie, recommandations CFO ; pensé pour répondre vite : sommes-nous en santé, que
  s'en vient-il, que puis-je me permettre, que dois-je éviter, quelle est la meilleure décision maintenant.
- **Questions types à savoir traiter** : camion à 95 000 $ ? équipement à 40 000 $ ? bâtiment commercial ? financer ou payer comptant ?
  combien garder pour les taxes ? combien investir sans mettre la paie en danger ? engager un employé ? investir 50 000 $ ? augmenter mes
  prix ? quel service/ville/chantier est le plus (moins) rentable ? quel contrat est dangereux ? quelle semaine sera serrée ? quelle stratégie
  présenter au CPA ?
- **Tests visés** : brouillon de paie (retenues, contributions, estimation de remises, dépôt réel bloqué), calendrier fiscal (alerte,
  paiement officiel bloqué), TPS/TVQ de période, acomptes d'impôt société, achat camion (comptant vs financement, 13 semaines, 12 mois,
  recommandation, questions CPA), achat équipement (ROI, seuil de rentabilité), achat bâtiment (hypothèque, DSCR, stress), question CFO
  (« puis-je investir 50 000 $ ? » sans hallucination, avec sources), calcul des réserves et du cash libre réel, tentative de paiement
  automatique bloquée avec piste d'audit complète.
- **Critères de sortie** : aucun paiement ni déclaration automatique possible ; piste d'audit ; AR/AP/OCR/rapprochement/Stripe/QuickBooks
  (lecture puis dry-run)/CCube/CPA/rentabilité/trésorerie/contrôleur/mémoire/tableau de bord/tests/docs/matrice fine ; paie brouillon ;
  calendrier fiscal ; projections ; réserves ; simulations d'achat ; conseil sourcé ; validation CPA/humaine explicite.
