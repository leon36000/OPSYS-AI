# M2 — Revenue CRM : Client 360, pipeline, moteur de ventes, intelligence de leads, quote-to-cash (condensé fonctionnel du prompt de Nathan, 2026-06-08)

(« GRS » = ancien nom d'OPSYS-AI.) But : M2 est **le système de vérité commerciale**. M2 existe déjà et était marqué vérifié : **ne pas le reconstruire,
ne pas casser routes/modèles existants, ne pas dupliquer le CRM** ; auditer, préserver, enrichir, connecter, tester, rendre intelligent. Aucun lead sans statut,
propriétaire, prochaine action ni historique. Vie commerciale : lead → qualification → dossier → estimation → soumission → relance → acceptation → cédule →
chantier → facture → paiement → avis → référencement/affaires répétées → mémoire client. Interdits : supprimer un client sans validation, écraser un historique,
fusionner des doublons sans journal, changer une soumission finale sans validation, promettre date (M4) ou prix (M3), agir sur facturation/paiement (M5),
relance sensible hors règles, inventer une donnée, marquer perdu sans raison, laisser un lead sans prochaine action. Compatibilité : toute nouvelle route
est additive ; tout changement de route existante = version v2 + régression.

## Sous-modules de rehaussement attendus
- **M2.1 Intégrité et audit du CRM** : leads sans statut, clients sans contact, tâches sans propriétaire, soumissions orphelines, doublons, activités sans
  client, pipeline incohérent, contrats de routes, garde de régression, rapport de qualité, suggestions de réparation.
- **M2.2 Client 360** : nom/téléphone/courriel/adresse, propriétés, services, historique d'interactions (appels, SMS, courriels), photos, documents,
  soumissions, factures, paiements, chantiers, satisfaction, plaintes, avis, source originale, valeur totale et potentielle, prochaine action, préférences,
  risques, notes, mémoire, chronologie complète, résumé financier simple (M5 reste la vérité financière), valeur vie client.
- **M2.3 Profil de propriété / site** (le client est aussi une propriété) : adresse, type de bâtiment, étages, matériaux, historique des travaux, photos,
  accès, stationnement, hauteur, risques, notes d'équipe, mesures connues, services faits/potentiels.
- **M2.4 Scoring de leads 2.0** (sans casser `scoring.py`) : source, ville, service, urgence, photos reçues, adresse complète, signal de budget, délai,
  qualité de communication, doublon, historique, valeur potentielle, probabilité de conversion, rentabilité probable, capacité de cédule, distance, saison,
  marge du service, comportement, réponse aux relances ; scores qualité, urgence, conversion, rentabilité, préparation, risque, préparation à l'estimation.
- **M2.5 Préparation à l'estimation** : prêt si service clair, adresse connue, photos suffisantes ou visite requise, coordonnées valides, urgence connue,
  notes complètes, propriété identifiée, doublon vérifié, source connue ; sortie {prêt, score, manquant, action recommandée, transfert permis} ; contexte
  d'estimation et demande d'information manquante.
- **M2.6 Prochaine meilleure action** (appeler maintenant, SMS, courriel, demander des photos, planifier l'estimation, envoyer à l'estimateur, préparer la
  soumission, relancer la soumission, gagné, perdu, revue admin, escalader une plainte, attendre) avec explication, file de priorité, détection des affaires
  bloquées, SLA ; pas d'action sensible sans validation, pas de sur-relance, respect des préférences et de l'opt-in.
- **M2.7 Relances** : après demande entrante, photos manquantes, soumission envoyée/sans réponse, rendez-vous à confirmer, client dormant, ancien client,
  saison, demande d'avis, référence ; séquences, politique, générateur de messages, SLA, **résurrection de leads dormants** ; jamais agressif, pas de spam,
  opt-in, fréquence limitée, personnalisation, validation humaine au départ, journaux ; performance des relances.
- **M2.8 Cycle de vie des soumissions** : statut, date d'envoi, montant, marge estimée, probabilité d'acceptation, relances, objections, version,
  acceptation/refus, raison de perte, liens M3/M5/M4, envoi à la cédule et à la finance à l'acceptation.
- **M2.9 Coach de vente IA** : résumé du client, ce qu'il veut, ce qui manque, opportunité, risque, objections probables, réponse recommandée, prochaine
  action, préparation d'appel et de relance, explication de la probabilité de gain.
- **M2.10 Attribution de source et retour au marketing (M7)** : source, canal, campagne, UTM, mot-clé, publication, annonce, formulaire, page d'atterrissage,
  coût, qualité, conversion, revenu, marge (M5), raison de perte ; retourne à M7 les leads qui convertissent, les campagnes qui attirent de mauvais leads,
  services les plus demandés, villes rentables, objections, raisons de perte, questions fréquentes.
- **M2.11 Segmentation** : lead chaud, photos requises, prêt à l'estimation, soumission envoyée/périmée, gagné en attente de cédule, chantier actif, facture
  en attente, ancien client, client à forte valeur, candidat référence, risque de plainte, lead dormant, opportunité saisonnière ; actions recommandées.
- **M2.12 Doublons et graphe d'identité** : téléphone, courriel, adresse, nom similaire, même propriété/conversation/facture, historique, score de confiance,
  fusion proposée, **validation humaine**, piste d'audit.
- **M2.13 SLA et prévention de perte de leads** : prochaine action obligatoire, lead chaud contacté vite, photos demandées, soumission relancée, plainte
  escaladée, lead sans propriétaire, tâche en retard ; scan, violations, plan de réparation.
- **M2.14 Référence et affaires répétées** : client satisfait → avis, référence, service complémentaire, relance saisonnière, entretien futur, vente croisée
  (M7 exécute le contenu ; M2 identifie les bons clients).
- **M2.15 Analytique et prévision** : nouveaux leads, qualifiés, conversion, temps de réponse, valeur du pipeline et des soumissions, taux d'acceptation,
  raisons de perte, source et qualité, performance des vendeurs, tâches en retard, ancienneté des leads, prévision de revenus, carnet commercial ; alimente M8/M9.
- **Intégrations** : M1 (admission : interaction, résumé, transcription, source, coordonnées, service, adresse, photos, urgence, sentiment, manquants →
  M2 renvoie client, lead, prochaine action, tâche, statut, alerte de doublon, préparation, propriétaire), M7 (attribution/retour), M3 (contexte → statut,
  manque, brouillon, final, montant, marge, risque, besoin de visite), M4 (soumission acceptée → créneau, équipe, retard, fin de chantier), M5 (soumission
  acceptée → facture, solde, lien de paiement, rentabilité, AR), M10 (nouveaux leads, changements de pipeline, pertes, objections, promesses, décisions,
  fusions, relances, plaintes, préférences ; paquets de contexte).
- **Flux de travail** : A lead reçu de M1 (doublon, client, lead, source, score, préparation, action, propriétaire, activité, mémoire, notification) ; B lead →
  estimation ; C soumission envoyée → relance → perte ; D soumission acceptée → M4/M5 ; E résurrection de dormants (avec validation) ; F requête Client 360.
- **Tableau de bord et mobile** : leads chauds, sans propriétaire/prochaine action, relances dues, soumissions à relancer, valeur du pipeline, conversion,
  qualité des sources, affaires bloquées, doublons, clients à risque/à fort potentiel, prévisions ; écrans kanban, Client 360, détail de lead, cycle de
  soumission, file de relances, coach, attribution, revue des doublons, SLA, segments, prévision ; admin, vendeur (ses leads, prochaine action, client 360,
  coach), client (statut, soumission, documents, messages, rendez-vous, factures via M5), employé (notes terrain).
- **IA** : résumé, scoring, prochaine action, brouillons de relance, objections, coaching, segmentation, analyse des pertes, suggestions de doublons ; jamais
  pour supprimer, fusionner sans validation, changer le prix final, modifier une facture, promettre date/prix, envoyer un message sensible hors politique.
- **Sécurité** : PII masquée, RBAC, audit, suppression/fusion/export contrôlés, consentement SMS/courriel, accès client limité, limitation de débit,
  validation pour actions de masse. **Tests** : scoring, préparation, doublons, prochaine action, politique de relance, attribution, segmentation, SLA,
  client 360, cycle de soumission ; intégrations (M1→lead, lead→M3, soumission envoyée→relance due, acceptée→M4+M5, source→attribution, doublon→fusion
  suggérée, client 360, lead sans action→violation SLA, dormant→plan, mémoire) ; E2E (lead complet, incomplet, soumission gagnée, perdue avec retour M7,
  client 360, lead dormant).
