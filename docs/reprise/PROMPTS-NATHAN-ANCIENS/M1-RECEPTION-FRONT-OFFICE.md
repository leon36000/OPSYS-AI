# M1 — Réception, adjointe administrative, Front Office IA omnicanal (condensé fonctionnel du prompt de Nathan, 2026-06-08)

(« GRS » = ancien nom d'OPSYS-AI.) But : M1 est la **porte d'entrée** : il reçoit, comprend, qualifie, organise, priorise et distribue toute demande
entrante ou administrative. Pas un simple chatbot/voicebot/formulaire. **Garanties** : aucune demande oubliée, aucune conversation sans trace,
aucun lead sans statut, aucun client sans prochain suivi, aucune promesse non autorisée, aucun prix inventé, aucun engagement légal/financier
sans validation, aucun transfert sans contexte, aucune tâche administrative critique sans suivi ; chaque interaction enrichit le CRM et la
mémoire. Rapide, poli, professionnel, bilingue si nécessaire, prudent, traçable, mesurable, escaladable.
Flux : M7 génère la demande → M1 répond/qualifie/collecte/crée le dossier → M2 pipeline → M3 chiffre → M4 planifie → M5 facture → M10 mémoire.
Ne pas reconstruire M2 (s'y brancher), M7 (recevoir ses leads), M5 (M1 ne pose aucune action financière finale).

## Canaux
Appels entrants (et sortants autorisés), messages vocaux, SMS, courriels, formulaires web, webchat, Facebook/Instagram, Google Business
Profile messages, WhatsApp (si légal), portail client, saisie manuelle admin. Toute demande devient une **interaction** normalisée
(identifie le client, détecte les doublons, classifie l'intention, lie au CRM, crée conversation/tâche, priorise, notifie).

## Sous-modules attendus
- **M1.1 Hub d'admission omnicanal** (ci-dessus). Intentions : soumission, suivi, facture/paiement, plainte, urgence, rendez-vous, fournisseur,
  spam, emploi, partenariat, document, autre.
- **M1.2 Agent vocal de réception** : répondre/assister les appels, poser les questions obligatoires, nom/téléphone/adresse/service, urgence,
  plainte, créer le lead, proposer un rappel, transférer à un humain, message vocal, résumer, écrire CRM et mémoire. **Modes progressifs, sans
  sauter d'étape** : 0 audit ; 1 messagerie vocale intelligente (transcription, résumé, tâche/lead) ; 2 bac à sable (appels de test, latences) ;
  3 assistant après-heures (collecte, aucune promesse, rappel) ; 4 live assisté (suggestions, humain peut intervenir) ; 5 production contrôlée
  (demandes simples, escalade stricte, rapport quotidien). Pipeline voix : audio → détection d'activité vocale → transcription en continu →
  intention → état de dialogue → modèle/outils → garde de réponse → synthèse vocale → résumé → CRM → mémoire ; interruptions (barge-in),
  délai de silence, repli humain, repli messagerie, transfert si faible confiance, incompréhensions répétées, appelant en colère, urgence,
  sujet légal/financier ; surveillance de latence. Téléphonie : Twilio/SIP (identifiants = gate Nathan ; simulateur d'abord), LiveKit/Pipecat
  en option, STT local prioritaire (confidentialité), TTS local/québécois si possible, repli texte/SMS.
- **M1.3 Qualification de lead** par service : **gouttières** (adresse, type de bâtiment, étages, photos avant/arrière/côtés, problème,
  réparation ou neuf, urgence, délai, accès, arbres, couleur), **revêtement** (adresse, type actuel, surface, photos, réparation ou
  remplacement, infiltration, matériaux, délai, budget si accepté), **soffite/fascia** (photos, longueur, ventilation, dommage, hauteur, accès),
  **service/réparation** (problème, urgence, photo, risque sécurité, date). Détecte l'information manquante, demande des photos (lien de
  téléversement), crée le lead, note la qualité et l'urgence, transfère à l'estimation. Détection de doublons et de spam.
- **M1.4 Sauvetage d'appel manqué** : interaction, SMS de réponse automatique **seulement si politique/opt-in configurés** (brouillon type
  « Nous avons manqué votre appel… »), tâche de rappel, transcription du message vocal, client existant identifié, CRM, notification admin,
  suivi jusqu'au contact réussi.
- **M1.5 Messagerie vocale intelligente** : transcription, résumé, extraction nom/téléphone/service/adresse, classification, urgence, sentiment,
  tâche de rappel, lead, notification, audio lié.
- **M1.6 Tri de la boîte courriel** : catégories (nouvelle demande, client existant, facture/paiement, fournisseur, plainte, spam, emploi,
  partenariat, document, autre) ; créer lead/tâche, proposer réponse, demander l'information manquante, transférer compta/estimation/admin,
  marquer spam, archiver seulement si sûr après validation.
- **M1.7 Assistant SMS/messages** : brouillons, demande de photos, rappel de rendez-vous, suivi de soumission, confirmation de disponibilité,
  lien de paiement (si M5 le fournit), messages de chantier, relance douce ; respect opt-in, pas de spam ni de messages de masse.
- **M1.8 Bureau des plaintes et escalade** : détecter client fâché, qualité, retard, dommage, facture contestée, risque d'avis négatif, menace
  légale, demande de remboursement ; jamais admettre une responsabilité légale, promettre un remboursement ni argumenter ; priorité haute,
  alerte admin, réponse empathique en brouillon, dossier, demande de preuves/photos, liens CRM/M5/M4. Réponse type empathique fournie.
- **M1.9 Bureau des rendez-vous et rappels** : proposer des créneaux, vérifier la cédule **via M4**, rappels, confirmer, replanifier, annuler,
  conflits, rappel automatique ; ne jamais confirmer un chantier sans M4 ni promettre une date si la capacité est incertaine ; toujours créer
  tâche/événement et notifier client + admin.
- **M1.10 Répondeur de statut client** : où en est ma soumission ? quand venez-vous ? facture envoyée ? comment payer ? photos reçues ?
  changer mon rendez-vous ? — en interrogeant M2, M3, M4, M5, M10 ; si incertain ne rien inventer (« Je vais vérifier avec l'équipe… ») ;
  jamais de détail financier sans vérification d'identité.
- **M1.11 Moteur d'adjointe administrative** : résumé quotidien (nouveaux leads, appels manqués, messages urgents, clients à rappeler, rendez-vous
  à confirmer, documents/photos manquants, plaintes/risques, tâches administratives, recommandations), leads sans suivi, messages sans
  réponse, tâches en retard, suggestions d'organisation, factures demandées.
- **M1.12 Transfert vers un humain** (vente, estimation, admin, finance, plainte, urgence, technique, propriétaire) : chaque transfert contient
  résumé, client, coordonnées, demande, urgence, sentiment, informations collectées/manquantes, historique, prochaine action recommandée,
  liens CRM/conversation, transcription — **aucun transfert sans contexte**.
- **M1.13 Boucle d'intelligence de réception** : temps de réponse, appels manqués, conversion, raisons de perte, questions fréquentes,
  objections, villes et services demandés, demandes hors zone, plaintes récurrentes, qualité des sources marketing, efficacité des scripts,
  taux de rendez-vous, taux de photos reçues → alimente M7, M2, M3, M8, M9, M10.
- **Scripts et politiques versionnés et configurables** (demande de soumission, plainte, facture/paiement, fournisseur) avec phrases permises/
  interdites et questions obligatoires. **Prix** : jamais de prix fixe sauf catalogue validé (« nous préparerons une estimation… »). **Délais** :
  jamais de date sans M4. **Garantie** : seulement les garanties validées de la base de connaissances. **Urgence/sécurité** : escalade immédiate,
  pas d'instruction dangereuse, humain requis. **Plainte** : empathique, non défensif, sans engagement légal.
- **Intégrations** : M2 (trouver/créer client, doublons, lead, activité, tâche, transcription/résumé/photos, score, prochaine action) ; M7
  (reçoit source, UTM, canal, annonce, contenu, page, mots-clés ; retourne qualité du lead, service, ville, objection, délai de réponse,
  conversion, raison de perte, questions fréquentes, sentiment, photos, rendez-vous) ; M3 (service, adresse, photos, notes, urgence, type de
  bâtiment, accès, contraintes, délai, historique, résumé) ; M4 (disponibilités, créneaux, retards, capacité) ; M5 (statut facture, lien de
  paiement, reçu, copie, solde ; jamais modifier/supprimer/négocier) ; M10 (mémoire des demandes, préférences, objections, plaintes, promesses
  humaines, erreurs de réception, scripts améliorés, pertes ; paquets de contexte).
- **Tableau de bord et app mobile** : appels du jour/manqués, messages vocaux à traiter, messages sans réponse, nouveaux leads/qualifiés, photos
  manquantes, rappels, rendez-vous demandés, plaintes, urgences, transferts en attente, temps de réponse, conversion, sources, qualité ;
  admin (boîte de réception, appels manqués, rappels, messages urgents, leads à valider, plaintes, transferts, rapport quotidien, « prendre en
  charge », « rappeler », « envoyer la réponse approuvée »), vendeur (leads reçus avec résumé), employé (signaler info/plainte terrain), client
  (soumettre demande, envoyer photos, voir statut, message simple).
- **Sécurité/conformité** : secrets chiffrés, PII masquée dans les journaux, transcriptions avec permission, enregistrement d'appel selon
  politique de consentement validée, accès par rôle, piste d'audit, archivage contrôlé, opt-in SMS, anti-spam, limitation de débit, signature
  des webhooks, protection contre le rejeu, idempotence, validation humaine pour plaintes/risques.
- **Observabilité** : traces (contexte, modèle, outil, résultat, qualité, escalade, latence), métriques (appels répondus/manqués, récupérés,
  temps de réponse, création de leads, qualité, photos, transferts, plaintes, latence voix p50/p95, erreurs STT/TTS, échecs d'écriture CRM).
- **Tests** : intention, qualification, info manquante, doublons, pont CRM, garde de sécurité, scripts, plainte, sentiment, politique de
  transfert, politique SMS, enregistrement ; intégration (appel simulé → transcription → lead ; message vocal → tâche ; appel manqué → SMS
  brouillon + rappel ; courriel de soumission → lead ; plainte → escalade ; SMS avec photo → lead mis à jour ; source M7 → M2 ; disponibilité
  M4 ; facture sans identité vérifiée bloquée ; événement mémoire) ; E2E (appel gouttières, appel manqué, courriel revêtement, plainte, demande
  de facture avec identité, appel en bac à sable avec transfert).
- **Critères de sortie** : toutes interactions capturées, pont CRM, qualification, tri courriel, SMS ou repli documenté, appel manqué,
  messagerie vocale, bac à sable vocal, Twilio/SIP branché ou « GATED_NATHAN », scripts versionnés, garde de sécurité (prix/promesses/actions
  risquées), plainte, rendez-vous au moins en demande, transfert à l'estimation, mémoire, retour à M7, tableau de bord, crochets mobile,
  traces, E2E verts, docs, matrice à jour.
