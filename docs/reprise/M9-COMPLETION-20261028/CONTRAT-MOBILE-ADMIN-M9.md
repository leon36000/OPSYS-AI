# Contrat serveur M9 pour le profil admin mobile (M9.22 reste PHASE_MOBILE_FINALE)

**Ce document prépare la phase mobile ; il ne ferme pas la ligne.** Aucun écran, aucun réseau interrompu côté app, aucune
vue périmée côté app n'ont été construits ni testés ici. Généré depuis le manifeste réel (`charger_outils()`), prouvé par
`tests/test_m9_contrat_mobile_admin.py`.

## Règles
- Seul le rôle `admin` appelle un outil M9 depuis un appareil ; vendeur, employé et client sont refusés (test sur quatre profils).
- Aucun outil M9 n'est ouvert à un autre profil ; trois outils anciens n'ont aucune portée d'appareil (fermés).
- Les outils des modules `outils_*` exigent l'admin authentifié (console ou appareil), jamais un agent ; les outils historiques d'`outils.py` gardent leur voie d'origine côté agent, sans élargir leur portée d'appareil.
- Les lectures sont bornées à 5 900 caractères (pagination `depart`) : une réponse tient sur un téléphone.
- Une vue périmée est refusée (`REJ-VUE-PERIMEE`) quand `vue_attendue` ne correspond plus ; l'app doit alors recharger.
- Les commandes passent par la file d'approbation native ; M9 ne les exécute jamais.
- Les dates (`reference`, `connaissance`, `jour`) sont fournies par l'appelant : M9 n'a pas d'horloge.

## Lectures admin (N0)
- `m9_apercu_dossier_strategique` — Construit, sans rien écrire, le dossier stratégique d'une question depuis les captures connues : couverture, manques, contradictions et faits citables
- `m9_apercu_graphe_impacts` — Résume le graphe d'impacts connu à un instant : objets par type, arêtes, règles actives et règles INCONNUES (lecture absente, refusée, partielle ou co
- `m9_apercu_revue` — Compose sans rien écrire la revue hebdomadaire, mensuelle ou trimestrielle d'une période (heure locale du fuseau), telle que M9 la connaît à l'instant
- `m9_auditer_affirmations_conseil` — Compare un lot de citations textuelles structurées à un dossier serveur sélectionné dont l'empreinte est attendue, ou conserve des hypothèses explicit
- `m9_bilan_suivis_decision` — Bilan INTERNE d'une période [debut, fin) explicite des suivis internes : ouverts dans la période, clos par revue humaine dans la période, ou encore ou
- `m9_cadrer_decision` — Cadre une question de direction (budget publicitaire, embauche, achat, prix, service, ville, dépenses, équipement, marketing, équipe) : type reconnu o
- `m9_couverture_strategique` — Évalue la couverture des lectures attendues à une référence, avec ce que M9 connaissait à l'instant de connaissance : ABSENTE, REFUSEE, PARTIELLE, CON
- `m9_diagnostiquer_dossier_direction` — Prépare un dossier historique sourcé et compare ses observations à une référence horaire explicite avec fuseau. Signale les observations futures sans 
- `m9_evaluer_playbook` — Instancie un playbook sur l'état réel (déclencheur du radar ou déclaré par la personne), rend ses étapes gouvernées (sensibles = validation humaine, a
- `m9_evaluer_scenarios` — Évalue des chocs du catalogue (hypothèses nommées, bases = faits citables du dossier) et les compare à la référence : sensibilités arithmétiques seule
- `m9_indicateurs_executifs` — Relie les indicateurs de direction (revenu, marges, cash libre, pipeline, conversion, rentabilité, ROI, coût par lead, capacité, stocks, satisfaction,
- `m9_interpreter_question_scenario` — Interprète une question « et si… » en propositions de chocs du catalogue de scénarios (paramètres dits seulement ; un paramètre non dit est à fournir,
- `m9_lire_actions` — État des actions proposées : tentatives, demande native, constats, sources ; sans les arguments.
- `m9_lire_alertes_m8` — Alertes proposées par M8 déjà reçues via le bus (m8.alerte_proposee), sans filtre de date — relecture pure du registre durable des alertes M9, n'ingèr
- `m9_lire_capture` — Relit une capture et, par tranches de 4 000 caractères au plus, le JSON canonique exact d'une page de la réponse du producteur (aucune troncature : su
- `m9_lire_conseil` — Projection d'une session : tours, dépôts, refus, clôture.
- `m9_lire_document_veille` — Contenu d'un document citable (jamais d'un document en quarantaine, remplacé ou périmé), par tranches bornées, étiqueté donnée non fiable.
- `m9_lire_entree_tour_conseil` — Entrée d'un tour en attente (consigne fixe et données séparées), par tranches bornées ; refuse un tour tranché ou prématuré (critique).
- `m9_lire_etat_consolide` — Reconstruit l'état consolidé courant par relecture pure du registre, sans ingérer de nouveau snapshot.
- `m9_lire_experiences` — Expériences à un instant : version courante, évaluation sur les captures connues, historique des résultats.
- `m9_lire_plans` — Plans à un instant : version courante et historique, retard calculé du jour donné, résultats clés mesurés chez leurs propriétaires, sources changées d
- `m9_lire_rapport_conseil` — Relit, par tranches bornées, le rapport de décision v2 d'une session close.
- `m9_lire_revue` — Relit, par tranches bornées, le JSON canonique exact d'une revue publiée (aucune troncature : suivre prochain_depart).
- `m9_lire_suite_briefing` — Lit la suite d'une section du briefing du matin quand celui-ci annonce « N autres éléments non affichés » : reprend à `depart` (indice dans la section
- `m9_lire_suivi_decision` — Relit un suivi interne et sa preuve historique par identifiant, avec sa clôture par revue humaine éventuelle, sans mutation ni exécution. Une clôture 
- `m9_lire_veille` — État de la veille à un instant : sources, documents (accepté, quarantaine, remplacé, périmé), liens ; sans contenu. Filtrable par décision.
- `m9_lister_captures` — Liste par pages bornées les captures stratégiques (la plus récente d'abord), avec la vue du registre : une reprise avec une vue périmée est refusée. A
- `m9_lister_demandes_approbation` — Liste les demandes d'approbation EN ATTENTE du socle, la plus ancienne d'abord, pour l'app du propriétaire : département, outil, niveau N, arguments e
- `m9_lister_playbooks` — Liste les gabarits de playbooks (cash, leads, surcharge, météo, rupture, prix, plaintes, conversion, marketing, saisons, embauche, équipement, expansi
- `m9_lister_revues` — Liste par pages bornées les revues publiées (la plus récente d'abord), avec la vue du registre.
- `m9_lister_suivis_decision` — Liste les suivis internes encore ouverts (sans clôture par revue humaine), échéance la plus proche d'abord puis par identifiant, chacun avec son plan 
- `m9_observations_chantier_periode` — Observations de chantier d'une période [debut, fin) explicite : snapshots WCT transportés par m8.snapshot_chantier dont l'instant métier d'origine tom
- `m9_preparer_cloture_suivi_decision` — Relit un suivi interne planifié non clos et une preuve M8 reçue de même métrique, même chantier et même définition, puis calcule leurs empreintes pour
- `m9_preparer_dossier_direction` — Prépare un dossier historique sourcé pour une question de direction, sans valider de décision. Conserve les variantes contradictoires et signale les m
- `m9_preparer_memoire_decision` — Prépare, sans rien écrire, les arguments exacts de m10_journaliser_decision pour une session de conseil close : identifiant stable par session, versio
- `m9_preparer_suivi_decision` — Relit une preuve M8 reçue et calcule son empreinte pour une demande de suivi. Lecture pure ; preuve historique, couverture et actualité métier non éva
- `m9_previsions_consolidees` — Présente les prévisions publiées par leurs propriétaires (trésorerie M5) avec versions, âge, réserves et faits citables ; leads, capacité et matériaux
- `m9_prioriser_options` — Classe des pistes déclarées (impact, urgence, confiance de 1 à 5) selon une politique versionnée dont chaque rang se refait à la main, nomme les confl
- `m9_produire_briefing_matin` — Assemble le briefing du matin (décisions en attente de la file du propriétaire, alertes M8 du jour, faits du bus consolidés la veille, manques) pour u
- `m9_produire_lecture_strategique` — Lecture stratégique des alertes de mesure de chantier terminé proposées par M8 (temps réel contre prévu, marge, matériaux) reçues dans la fenêtre du b
- `m9_projeter_tendance` — Extrapole, par le code (moyenne mobile, droite des moindres carrés, saisonnier naïf), un fait numérique capturé chez un producteur, avec chaque point 
- `m9_propager_impacts` — Propage un changement depuis un objet (devis, chantier, intervention, lead…) selon les relations prouvées par des lignes capturées : rend les objets l
- `m9_proposer_profils_conseil` — Rend les déclarations de profils d'agents des rôles du conseil (manuel, tours et réessais bornés). Aucune création, aucun grant : un administrateur le
- `m9_radar_occasions` — Évalue des occasions déclarées (conditions, alternatives, coût et capacité cités) et les signaux mesurés (devis sans réponse M8) : sans coût ni capaci
- `m9_radar_risques` — Signale les risques déjà mesurés par les propriétaires (cash M5, matériaux M6, incidents M4, marge M8) : gravité d'une grille proposée non validée, pr
- `m9_rapport_activite_periode` — Rapport INTERNE partiel d'activité [debut, fin) : observations WCT liées au bus, puis alertes M8 connues à la lecture, puis suivis de décisions humain
- `m9_rapport_periode` — Synthèse INTERNE d'une période [debut, fin) explicite : compteurs, total et vue du bilan des suivis internes (sans ses lignes) et alertes M8 reçues do
- `m9_rapprocher_metriques` — Classe les mesures capturées de M8 face aux définitions du registre M8 (compatible, sans définition, unité divergente, version périmée, non déclarée o
- `m9_reauditer_conseil` — Relit les citations admises d'une session de conseil et dit si leur source a changé depuis (capture plus récente de la même lecture, valeur différente
- `m9_salle_de_guerre` — Vue quotidienne en lecture seule : décisions en attente, alertes M8, couverture et manques, contradictions, conseils en cours et recommandations à val
- `m9_verifier_captures` — Vérifie la chaîne des captures (rangs, empreintes, réception monotone) sans rien écrire.
- `m9_verifier_memoire_decision` — Compare ce que M9 croit avoir consigné dans M10 à ce que M10 dit (lecture capturée m10.statut_decision) : cohérent, mémoire fantôme, divergent, non en

## Écritures internes admin (N1/N2, journalisées, idempotentes par rang)
- `m9_abandonner_tour_conseil` (N2)
- `m9_annuler_plan` (N2)
- `m9_capturer_producteur` (N2)
- `m9_clore_suivi_decision` (N3)
- `m9_cloturer_conseil` (N2)
- `m9_decider_demande_approbation` (N2)
- `m9_declarer_source_veille` (N2)
- `m9_definir_experience` (N2)
- `m9_deposer_tour_conseil` (N2)
- `m9_enregistrer_plan` (N2)
- `m9_evaluer_experience` (N2)
- `m9_importer_document_veille` (N2)
- `m9_lier_veille_decision` (N2)
- `m9_noter_suivi_plan` (N2)
- `m9_ouvrir_conseil` (N2)
- `m9_ouvrir_suivi_decision` (N3)
- `m9_proposer_action` (N2)
- `m9_publier_revue` (N2)
- `m9_reconcilier_action` (N2)
- `m9_retirer_source_veille` (N2)

## Fermés aux appareils
`m9_etat_consolide`, `m9_valider_rapport_strategique`, `m9_valider_snapshot`

## Reste à faire en phase mobile
Écran admin, état hors ligne, rechargement sur vue périmée, tests appareil réels, droits des quatre profils côté app.
