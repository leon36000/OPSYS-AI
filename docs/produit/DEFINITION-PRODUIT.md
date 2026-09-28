# OPSYS-AI — Définition produit de référence

**Version :** 28 septembre 2026 (révision 2 : prompt M6 intégré, prompts M4, M5 et M9 complets, app mobile renforcée)
**Révision 3 (28 septembre 2026, ingénieur en chef) :** choix du core tranché et points ouverts d'ingénierie décidés, voir [ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md). Le reste du texte est inchangé.
**Langue :** français (Québec)
**Lecteur principal :** Claude Code et tout agent qui travaille sur OPSYS-AI
**Sources :** prompts maîtres des départements (8–9 juin 2026, et 23 juin 2026 pour M6), plan maître v1.2 (juillet–août 2026), directives de Nathan (septembre 2026). Détail en annexe A.

---

## 0. Comment utiliser ce document

1. Ce fichier définit le **QUOI** : ce qu'est OPSYS-AI, ce que fait chacun des 10 départements, quelles règles ne se négocient pas.
2. Le **COMMENT** (langages, frameworks, briques, structure du code) est laissé à la restructuration, sauf ce que la section 3 fixe déjà.
3. En cas de contradiction entre ce fichier et un ancien prompt de département, **ce fichier gagne**. Les anciens prompts restent la référence pour le détail fonctionnel (routes, tables, KPI, scénarios de test).
4. Rien ici ne dit qu'un département est « terminé ». Les états de la section 11 datent de juin 2026 et doivent être revérifiés par audit.
5. **Test de dérive :** si un livrable pourrait décrire n'importe quelle entreprise sans parler de leads, soumissions, chantiers, équipes, factures ou matériaux, c'est de l'infrastructure, pas OPSYS-AI. Retour à la section 1.
6. **L'app mobile est un pilier du produit**, pas un complément (inventaire, punch des employés, vendeurs, approbations du propriétaire, suivi client). Voir la section 9 avant de concevoir quoi que ce soit côté interface.

---

## 1. Ce qu'est OPSYS-AI

**OPSYS-AI (anciennement GRS) est un système d'exploitation d'entreprise piloté par IA.** Il donne à une petite entreprise de services les ressources d'une grande, sous la forme de **10 départements virtuels** qui travaillent ensemble sur une seule vérité partagée : réception, ventes, estimation, terrain, finance, inventaire, marketing, analytique, stratégie et mémoire.

**Premier cas d'usage :** Gouttières et Revêtements Synergy (GRS), entreprise de rénovation extérieure au Québec (gouttières, revêtement extérieur, soffite/fascia, réparations).
**Ensuite :** PME de services québécoises, en SaaS, avec la conformité Loi 25 comme différenciateur.

### Ce qu'OPSYS-AI n'est PAS

- Ce n'est **pas une infrastructure IA**, un cockpit d'agents, un orchestrateur générique ni un framework. Forge et les autres projets d'infrastructure de Nathan sont des choses distinctes.
- Ce n'est **pas un chatbot**, ni dix outils côte à côte. Les départements se parlent par événements et par contrats d'interface stables.
- Ce n'est **pas un simple RAG**. La mémoire est un département (M10), pas seulement une base vectorielle.
- Ce n'est **pas un CRM seul**. Le CRM (M2) est un des dix organes.

### Le principe qui traverse tout

Ce ne sont pas des chatbots qui répondent : ce sont des **départements qui opèrent**. Ils lisent les vraies données de l'entreprise, agissent dans les limites qu'on leur donne, et demandent une signature humaine dès que ça touche l'argent, le légal, la paie, un client sensible ou une décision irréversible.

### Ce que ça change pour l'entreprise

Plus d'appel manqué, de lead oublié, de chantier mal planifié, de matériel manquant, de facture non envoyée ni de leçon perdue. Un seul événement (« travaux terminés ») déclenche des réactions coordonnées dans tous les départements (section 6).

---

## 2. Les 10 départements en un coup d'œil

| Code | Département | Rôle | Question à laquelle il répond |
|---|---|---|---|
| **M1** | Front Office IA | Reçoit, comprend, qualifie et distribue toute demande entrante ou administrative | Qui nous contacte et que veut-il ? |
| **M2** | Revenue CRM | Vérité commerciale : clients, leads, pipeline, soumissions | Où en est chaque client, quelle est la prochaine action ? |
| **M3** | Estimation Intelligence | Transforme un lead prêt en estimation chiffrée, rentable, honnête sur son incertitude | Combien ça coûte, combien on charge, avec quelle confiance ? |
| **M4** | Field Operations | Équipes, cédule, routes, GPS, exécution et clôture des chantiers | Qui va où, quand, avec quoi, est-ce terminé ? |
| **M5** | FinanceCore | Comptabilité, fiscalité, paie, contrôle, CFO IA | Combien d'argent avons-nous vraiment, que peut-on se permettre ? |
| **M6** | Material Control | Inventaire, achats, fournisseurs (Gentek, Royal, O.A.M., Kaycan), bons de commande, sorties terrain, variance des matériaux | Qu'a-t-on en stock, à quel coût, que faut-il commander, que s'est-il vraiment utilisé ? |
| **M7** | Marketing & Croissance IA | CMO IA : visibilité, réputation, acquisition | Comment obtenir plus de leads, et de meilleurs ? |
| **M8** | Business Truth & Analytics | Métriques gouvernées, dashboards, alertes, qualité des données | Que disent vraiment les chiffres, peut-on s'y fier ? |
| **M9** | Strategic Intelligence | Direction IA : décisions, scénarios, risques, priorités | Que devrait-on faire maintenant, et pourquoi ? |
| **M10** | Mémoire | Mémoire long terme gouvernée, non-oubli | Qu'a-t-on déjà fait, décidé, appris ? |

---

## 3. Direction actuelle (septembre 2026)

OPSYS-AI a changé de forme, pas de but. L'idée de base reste : **10 départements virtuels, les ressources d'une grande entreprise dans une petite**.

| Sujet | Avant (plan v1.2, juin–août 2026) | Maintenant |
|---|---|---|
| Déploiement | Framework qui se greffe sur une infra IA existante (prérequis : passerelle LLM, base vectorielle, PostgreSQL, stockage) | **Produit autonome, installable sur un VPS** |
| Configuration des modèles | Passerelle LLM fournie par l'hôte | **Dashboard OPSYS-AI** pour configurer tous les modèles nécessaires, **cloud ou locaux** |
| Core | Core autonome avec 8 services partagés | **OPSYS-CORE**, construit directement sur le code source d'**OpenClaw2** ou de **Hermes Agent**, lourdement modifié pour tout unifier (aucune dépendance à leurs mises à jour) |
| Mémoire | M10 + RAG fournis par l'hôte | Mémoire de type OpenClaw2 (jugée excellente) + **RAG premium obligatoire** ; documentation à rédiger en prérequis |
| Coût des modèles | Routage de modèles par département | **Économie de tokens maximale**, mécanismes natifs |
| Dépôts Forge | Gouvernaient le développement | **Mis de côté** ; le projet est restructuré et assaini |
| Construction | Stack imposée par les prompts | **Briques open source mûres = ingrédients**, adaptées ou fusionnées puis homogénéisées (GitHub, GitLab, bibliothèques open source) |

**Ce qui ne change pas :** les 10 départements, leur synergie, la validation humaine, la Loi 25, l'indépendance envers l'infrastructure personnelle de Nathan, l'ambition SaaS, **et l'app mobile à quatre profils, qui reste primordiale**.

**Le choix OpenClaw2 vs Hermes Agent n'est pas tranché.** Il se fait par comparaison documentée : licence (modification et redistribution commerciale), état du code, facilité de modification, qualité de la mémoire, support multi-modèles.

**Tranché le 28 septembre 2026 : OpenClaw2, forké en dur et renommé OPSYS-CORE** (comparatif et décisions : [ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md)).

---

## 4. Architecture produit

```
 App mobile (admin · vendeur · employé · client)     Dashboard web admin
                     │                                       │
 ┌───────────────────┴───────────────────────────────────────┴───────────┐
 │  10 DÉPARTEMENTS VIRTUELS  M1 · M2 · M3 · M4 · M5 · M6 · M7 · M8 · M9 · M10  │
 │  (contrats d'interface stables, événements partagés)                  │
 └───────────────────────────────────┬───────────────────────────────────┘
                                     │
 ┌───────────────────────────────────┴───────────────────────────────────┐
 │  OPSYS-CORE : runtime d'agents, mémoire, outils, services partagés    │
 └───────────────────────────────────┬───────────────────────────────────┘
                                     │
 ┌───────────────────────────────────┴───────────────────────────────────┐
 │  PLATEFORME : VPS · base de données · RAG · modèles cloud/locaux ·    │
 │  secrets · stockage fichiers                                          │
 └───────────────────────────────────────────────────────────────────────┘
```

### Services partagés du Core (plan v1.2)

Approbations · autorisation · audit · gates · notifications · mémoire · métriques · observabilité.
Chaque département les consomme au lieu de réinventer les siens. C'est ce qui rend la synergie fiable.

### Dashboard web admin

**Exigé par Nathan :** tout gérer et configurer depuis un seul endroit, y compris la connexion de tous les modèles IA nécessaires (cloud ou locaux).
**Impliqué par les prompts des départements :**
- statut des connecteurs et des portes fermées (gates) ;
- file d'approbations humaines ;
- politiques et scripts (ex. scripts de réception, politiques de conversation) ;
- gestion des utilisateurs, rôles et permissions ;
- tableaux de bord et wallboards par département (M8) ;
- tableau de bord de dispatch (M4), CFO (M5), stratégie (M9), mémoire (M10).

### App mobile

**Pilier du produit** (directive de Nathan, 28 septembre 2026). Une seule app, **quatre profils** : admin, employé, client, vendeur. C'est l'interface principale de l'employé (punch, chantier, matériaux), du vendeur (leads, soumissions) et du propriétaire en déplacement (approbations), et le canal du client. Chaque département définit ses écrans par profil. **Détail complet en section 9.**

---

## 5. Principes transversaux (invariants)

### P1 — L'humain reste dans la boucle

Synthèse commune. Les échelles exactes de M7 (niveaux 0–6) et de M5 (F0–F7) restent la référence dans leur département.

| Niveau | Nature | Règle |
|---|---|---|
| N0 | Lecture | Automatique |
| N1 | Brouillon (post, facture, réponse, rapport, recommandation) | Automatique |
| N2 | Tâche interne, rappel, alerte, demande de validation | Automatique |
| N3 | Action externe à faible risque ou modification interne non finale (publication approuvée, rapprochement proposé, écriture proposée) | Validation humaine au départ |
| N4 | Engagement : dépense, budget, campagne, prix, envoi sensible, écriture comptable finale | Validation de Nathan |
| N5 | Argent réel, fiscal, légal, paie, RH, achats majeurs, emprunts | Validation de Nathan **et** du professionnel concerné (CPA, fiscaliste, avocat, prêteur). Jamais automatique |

Une IA propose, justifie, cite ses sources, donne sa confiance, puis demande validation. Elle ne décide pas seule de la vérité comptable, légale ou stratégique.

### P2 — Honnêteté des chiffres et de l'incertitude

- Jamais de chiffre, de prix, de revenu ou de capacité inventé.
- Toute recommandation est liée à une donnée ou marquée explicitement comme hypothèse.
- Chaque chiffre a une source, une fraîcheur et un statut de qualité. Le système ose dire « donnée pas fiable ».
- Les sorties distinguent : fait vérifié, hypothèse, suggestion, risque, action proposée, action nécessitant validation, donnée manquante.
- Une seule photo sans échelle donne une plage, pas une mesure exacte (M3).

### P3 — Traçabilité totale

Chaque action produit une trace : **qui, quoi, pourquoi, source, modèle utilisé, confiance, coût, risque, statut**. Les modifications sensibles gardent l'avant et l'après. Observabilité : traces des appels de modèles (prompt, contexte, sortie, coût, latence) et traces système (API, base de données, workflows, erreurs).

### P4 — Mémoire avant, mémoire après

Avant toute réponse complexe ou modification critique, le département lit son contexte dans M10. Après toute action importante, il y écrit ce qui a été fait, pourquoi et avec quel résultat.

### P5 — Ne pas reconstruire, ne pas casser

M2 et M5 sont les piliers les plus avancés : on les durcit, on les connecte, on ne les refait pas. Toute nouvelle route est additive ; un changement incompatible passe par une v2, avec tests de régression. **Voir le point ouvert n° 7 (section 13) : cette règle doit être réconciliée avec la restructuration.**

### P6 — Complétion prouvée

Statuts utilisés : `STUB`, `PARTIEL`, `NEEDS_HARDENING`, `GATED_NATHAN`, `GATED_EXTERNAL_API`, `EXISTING_VERIFIED`, `FAIT_VÉRIFIÉ` / `DONE_VERIFIED`.
- Aucun département n'est déclaré terminé sans routes, tests (unitaires, intégration, E2E), documentation, tableau de bord, traces, mémoire M10 et statut à jour.
- Une porte fermée s'affiche « PARTIEL — GATE NATHAN », jamais « terminé ».
- Si un connecteur manque, on livre un **mode de repli manuel ou par export**, documenté.
- Aucune déclaration « 100 % » sans preuve.
- Chaque département commence par un **audit sans modification** de l'existant.

### P7 — Séparer le déterministe de l'IA

- Les automatisations planifiées (type n8n) exécutent des tâches déterministes à faible risque et des appels internes. Elles ne paient pas, ne publient pas de façon sensible, ne modifient pas les prix, ne suppriment rien, ne fusionnent rien sans validation.
- Les workflows à états avec validation humaine, reprises et cycles passent par un moteur de workflows d'agents (LangGraph dans les prompts).
- Le LLM ne calcule jamais les métriques ; il les explique.

### P8 — Sécurité, confidentialité, Loi 25

- Contrôle d'accès par rôle (`nathan_owner`, `admin`, `finance`, `manager`, `seller`, `employee`, `client`, `system_agent`) et par métrique.
- Renseignements personnels masqués dans les journaux ; secrets jamais en clair ni codés en dur ; jetons OAuth chiffrés.
- Signatures de webhooks vérifiées, idempotence, protection contre le rejeu, limites de débit.
- Consentements documentés : SMS et courriel (opt-in), enregistrement d'appels, suivi GPS des employés.
- Photos et données de clients : pas d'usage marketing ni d'entraînement sans consentement ou anonymisation.
- Aucune donnée client vers un modèle externe sans politique explicite.
- Suppression, export et fusion contrôlés ; rétention configurable ; audit des accès.

### P9 — Conformité aux plateformes

Aucun faux abonné, faux like, bot, pod d'engagement, spam, scraping interdit ni contournement des limites d'API. Intégrations officielles d'abord ; sinon workflow manuel assisté avec validation.

### P10 — Indépendance et dégradation gracieuse

- OPSYS-AI ne dépend d'aucune infrastructure personnelle de Nathan.
- Un prérequis manquant met le système en **mode bridé** plutôt que de le faire planter.
- Replis prévus dans les prompts : M3 sans SAM2 (règles, OpenCV, mesure manuelle) ; M7 en export manuel ; M4 avec plusieurs fournisseurs de routage ; M5 avec import CSV ; M3 avec grille de prix interne versionnée quand M6 n'est pas prêt.

### P11 — Économie de tokens

Nouveau et prioritaire. Points d'appui déjà présents dans les prompts :
- routage par difficulté : modèle local rapide pour tri, intentions et classification simple ; modèle local plus fort pour résumés et coaching ; modèle premium seulement pour les cas complexes (M1, M2) ;
- contextes de mémoire en couches (« doit savoir », important, preuves, approfondissement) pour ne pas tout injecter (M10) ;
- automatisations déterministes pour tout ce qui n'exige pas d'IA (P7).

### P12 — Langue et ton

Français québécois professionnel, clair et crédible ; bilingue si le client l'exige (M1). Exactitude avant vitesse, stabilité avant magie, produit réel avant démonstration impressionnante.

### P13 — Chaque département a une source de vérité, et les autres ne la recalculent pas

Voir la section 8.

### P14 — Le mobile d'abord

L'app mobile est un pilier du produit : inventaire, punch, vendeurs, terrain, approbations du propriétaire, suivi client. Chaque département définit ses écrans mobiles par profil, et les critères de complétion de la plupart d'entre eux (M1, M2, M3, M4, M5, M6, M8, M9, M10) incluent leurs écrans ou hooks mobiles. Le terrain fonctionne **hors ligne d'abord**. Détail en section 9.

---

## 6. Le système en mouvement

### Flux principal

```
M7 attire → M1 capte et qualifie → M2 structure (lead, client, propriété, pipeline)
→ M3 estime et rédige la soumission → M2 suit la soumission (relances)
→ soumission acceptée → M4 planifie, route, exécute (avec M6 pour le matériel)
→ M5 facture, encaisse, mesure la rentabilité → M8 mesure → M9 décide → M10 mémorise
```

M10 reçoit des événements de tous les départements à chaque étape.

### Cascade « travaux terminés »

Quand un employé clique « Travaux terminés » dans l'app, une chaîne contrôlée se déclenche.
**Conditions préalables (M4) :** checklist terminée, photos après, matériel utilisé, temps réel, notes d'imprévus, signature du client si requise. S'il manque quelque chose ou si le matériel diffère du prévu, le statut devient `completed_pending_review`, pas `completed_verified`.

| Département | Réaction |
|---|---|
| **M4** | Valide la complétion, clôt le chantier, alimente l'analytique terrain |
| **M6** | Ouvre le formulaire de matériaux utilisés dans l'app, valide les sorties, compare estimé et réel, ajuste le stock, alerte l'admin si l'écart est important, signale le stock bas, crée le besoin de commande |
| **M5** | Prépare la facture brouillon (validation humaine), calcule le coût réel, met à jour les comptes à recevoir et la rentabilité du chantier |
| **M2** | Marque le chantier terminé, écrit l'activité, définit la prochaine action |
| **M7** | Propose une demande d'avis et, avec consentement, du contenu avant/après |
| **M3** | Compare estimé et réel pour calibrer ses règles |
| **M8** | Temps réel vs prévu, marge prévue vs réelle, performance d'équipe |
| **M9** | Lecture stratégique via les preuves de M8 |
| **M10** | Grave l'événement, les écarts et les leçons |

### Flux des matériaux (M3 → M6 → M4 → M6)

```
M3 finalise l'estimation et envoie les besoins matériaux à M6
→ M6 valide le catalogue, vérifie le stock, réserve, ou crée un besoin de commande
→ M6 rédige le bon de commande (PO) ; l'admin le valide
→ M1 (adjointe administrative) envoie le courriel au fournisseur si la politique l'autorise
→ le fournisseur confirme → réception (complète ou partielle) → stock mis à jour
→ M4 exécute le chantier → « Travaux terminés » → l'employé remplit le formulaire de matériaux utilisés
→ M6 compare estimé et réel → écart faible : stock ajusté ; écart fort : alerte admin et `completed_pending_review`
→ M5 reçoit le coût réel → M8 mesure la variance → M9 lit le risque → M10 grave la leçon
→ M3 recalibre ses estimations
```

### Boucles de rétroaction

- **M1, M2 → M7 :** qualité des leads, conversions, raisons de perte, objections, villes et services demandés.
- **M4, M5, M6 → M3 :** estimé vs réel, pour calibrer prix et durées.
- **M5 → M7 :** coût par lead et par vente, revenus et profit par canal, ROI réel.
- **M8 → M9 :** paquets de preuves (métriques, tendances, fraîcheur, qualité).
- **M9 → tous :** actions stratégiques transformées en tâches contrôlées.
- **Tous → M10 :** événements, décisions, erreurs, leçons.

---

## 7. Les 10 départements

### M1 — Front Office IA (réception, adjointe administrative, omnicanal, voix)

**Mission.** La porte d'entrée d'OPSYS-AI. Reçoit, comprend, qualifie, organise, priorise et distribue toute demande entrante ou administrative. Empêche l'entreprise de perdre des opportunités : appel manqué, message oublié, courriel non traité, formulaire incomplet, client non rappelé, lead sans statut.

**Ce que c'est / n'est pas.** Ce n'est ni un chatbot, ni un robot vocal, ni un formulaire. M1 capte la demande ; M7 attire l'attention ; M2 gère le pipeline.

**Canaux.** Téléphone, SMS, courriel, formulaire web, webchat, messages Facebook/Instagram, Google Business Profile, WhatsApp (optionnel, si légal), messagerie vocale, saisie manuelle, portail client.

**Fonctions.**
- M1.1 Hub d'intake omnicanal : toute demande devient une interaction tracée.
- M1.2 Agent vocal de réception (déploiement progressif, voir ci-dessous).
- M1.3 Qualification : questions obligatoires par service (gouttières, revêtement, soffite/fascia, réparation), détection d'infos manquantes, demande de photos, score de lead.
- M1.4 Sauvetage d'appel manqué : interaction, SMS (si politique active), tâche de rappel, suivi jusqu'au contact.
- M1.5 Messagerie vocale intelligente : transcription, résumé, extraction, lead, tâche.
- M1.6 Tri des courriels : catégories (nouvelle demande, client existant, facture, fournisseur, plainte, spam, emploi, partenariat…).
- M1.7 Assistant SMS/messages, dans le respect de l'opt-in.
- M1.8 Bureau des plaintes et escalades : ton empathique, jamais défensif, jamais engageant légalement.
- M1.9 Rappels et rendez-vous, via la cédule de M4.
- M1.10 Réponses de statut aux clients existants (soumission, visite, facture) ; si incertain : « Je vais vérifier avec l'équipe ».
- M1.11 Adjointe administrative : résumé quotidien, rappels, leads sans suivi, documents et photos manquants.
- M1.12 Transfert humain avec contexte complet (types : ventes, estimation, admin, finance, plainte, urgence, technique, propriétaire).
- M1.13 Boucle d'apprentissage : temps de réponse, conversions, questions fréquentes, raisons de perte.

**Règles dures — M1 ne doit jamais :** inventer un prix ferme ; promettre une date sans M4 ; confirmer un rendez-vous sans créer l'événement ou la tâche ; promettre un rabais ou une garantie non validés ; donner un avis légal, fiscal ou contractuel ; enregistrer un appel sans politique de consentement ; envoyer des messages de masse non sollicités ; transférer sans résumé ; laisser une conversation sans prochaine action ; supprimer un client ou un lead.
**M1 doit toujours :** demander l'information manquante, créer ou mettre à jour le CRM, créer une tâche de suivi, classer l'intention, scorer urgence et qualité, résumer, escalader si risque, écrire dans M10, tracer.

**Voix : montée en charge sans sauter d'étape.** Audit → messagerie vocale intelligente → bac à sable (faux clients) → assistant hors heures → live assisté (humain supervise) → production contrôlée. Faible confiance de transcription : redemander. Deux échecs de compréhension, plainte, sujet légal ou financier, urgence de sécurité : transfert humain immédiat.

**Échanges.** Reçoit de M7 (source, UTM, campagne). Envoie à M2 (lead, activité, tâche, transcription), à M3 via M2 (service, adresse, photos, urgence), à M4 (disponibilités, rappels), à M5 (demande de statut de facture ; **aucune modification financière**), à M10, à M8. Retourne à M7 la qualité des leads. **Sert de canal administratif à M6** : révise et envoie les courriels de bons de commande aux fournisseurs (si la politique l'autorise) et suit leurs réponses.

**Mobile.** Admin : inbox omnicanal, appels manqués, rappels, plaintes, transferts, « prendre en charge », « rappeler », « envoyer la réponse approuvée ». Vendeur : leads reçus avec résumé de conversation. Employé : signaler une info client ou une plainte du terrain. Client : soumettre une demande, envoyer des photos, voir le statut.

**Portes fermées.** Identifiants Twilio, SIP réel, politique d'enregistrement d'appels, opt-in SMS.
**État connu (juin 2026).** `STUB` : `voice_agent.py`, `voice_pipecat_stub.py`, `sip_connector.py`, `tts_engine.py`, `crm_integration.py`. Manque le runtime vocal de production, la transcription en production, les scénarios E2E, le routage complet, la mémoire, le tableau de bord, le flux d'appel manqué, l'escalade humaine, le consentement d'enregistrement et un vrai score de lead.
**Preuve de complétion.** Toutes les interactions capturées ; pont CRM réel ; qualification, tri de courriels, appel manqué et messagerie vocale fonctionnels ; garde-fous bloquant prix et promesses ; escalade de plaintes ; scripts versionnés ; E2E verts (appel de soumission, appel manqué, courriel de revêtement, plainte, demande de facture, bac à sable vocal).

---

### M2 — Revenue CRM (client 360, pipeline, moteur de ventes)

**Mission.** Le cœur commercial : qui est le client, d'où vient le lead, ce qu'il veut, où il en est, qui doit agir, quelle est la prochaine action, quelle est la valeur, quelle relance est due. **Aucun lead sans statut, propriétaire, prochaine action ou historique.**

**Cycle de vie couvert.** Lead → qualification → dossier client → estimation → soumission → relance → acceptation → cédule → chantier → facture → paiement → avis → référence et affaires répétées → mémoire client.

**Ce que M2 n'est pas.** Pas la source de vérité financière (c'est M5). Pas un simple carnet de contacts.

**Fonctions.**
- Cœur existant : leads, clients, contacts, pipeline, kanban, tâches, activités, tags, produits/services, soumissions, doublons, dossier client, import en lot, rapports.
- M2.1 Intégrité et audit du CRM (orphelins, champs requis, garde anti-régression).
- M2.2 Client 360 : fiche totale (interactions, photos, soumissions, factures, chantiers, plaintes, valeur, préférences, mémoire).
- M2.3 Profil de propriété : type de bâtiment, étages, matériaux, historique, accès, photos, services potentiels.
- M2.4 Lead Scoring 2.0 : qualité, urgence, conversion, rentabilité, préparation, risque.
- M2.5 Préparation à l'estimation : le lead est-il prêt pour M3 ? Que manque-t-il ?
- M2.6 Prochaine meilleure action, avec explication.
- M2.7 Relances : séquences, dormants, ancien client, saisonnier, avis, référence.
- M2.8 Intelligence des soumissions : statut, probabilité d'acceptation, objections, raison de perte, passage à M4 et M5.
- M2.9 Coach de vente IA.
- M2.10 Attribution des sources et retour vers M7.
- M2.11 Segmentation : `hot_lead`, `needs_photos`, `estimate_ready`, `quote_sent`, `quote_stale`, `won_pending_schedule`, `active_job`, `invoice_pending`, `past_customer`, `high_value_customer`, `referral_candidate`, `complaint_risk`, `dormant_lead`, `seasonal_opportunity`.
- M2.12 Graphe d'identité et doublons (fusion proposée, jamais automatique).
- M2.13 SLA et prévention de perte de leads.
- M2.14 Références et affaires répétées.
- M2.15 Analytique et prévisions commerciales.

**Règles dures.** Jamais : supprimer un client sans validation ; écraser un historique ; fusionner sans journal ; changer une soumission finale sans validation ; promettre une date (M4) ou un prix (M3) ; agir sur la facturation (M5) ; marquer un lead perdu sans raison ; laisser un lead sans prochaine action. Relances : pas de spam, pas d'agressivité, opt-in respecté, fréquence limitée, validation humaine au départ.

**Échanges.** Reçoit de M1 (interaction, résumé, infos collectées) et de M7 (source, campagne). Envoie à M3 (contexte d'estimation), à M4 (soumission acceptée), à M5 (client, montant, dépôt). Retourne à M7 la qualité des leads, la conversion, les raisons de perte. Alimente M8/M9.

**Compatibilité.** L'API existante `/api/crm` (leads, clients, kanban, pipeline, soumissions, products, tasks, reports) **ne doit pas être cassée**.

**Mobile.** Admin : pipeline, leads chauds, relances, doublons. Vendeur : ses leads, prochaine action, Client 360, soumissions, coach de vente, pipeline personnel. Client : statut de la demande, soumission, rendez-vous. Employé : remonter des notes du terrain.

**État connu.** `FAIT_VÉRIFIÉ` au moment du prompt (« complet et validé »). Le travail restant est du durcissement, de l'intelligence et des intégrations, pas une reconstruction.
**Preuve de complétion.** Cœur stable et aucune route cassée ; Client 360, scoring 2.0, préparation, relances, prochaine action, cycle de soumission, attribution, sales coach fonctionnels ; intégrations M1/M3/M4/M5/M7/M10 ; E2E verts (lead complet, lead incomplet, soumission gagnée, perdue, Client 360, lead dormant).

---

### M3 — Estimation Intelligence (vision, mesure, coûts, risque, prix, marge)

**Mission.** Transformer un lead qualifié en estimation exploitable, vérifiable, rentable et prête à devenir une soumission.

**Les trois dangers à éviter.** Sous-estimer (marge détruite), surestimer (vente perdue), **inventer une précision qui n'existe pas**.

**Chaque estimation contient toujours :** l'estimation, une plage de confiance, les hypothèses, les données utilisées, les données manquantes, les risques, les incertitudes, les prochaines infos à collecter, la marge attendue, le prix recommandé, les preuves visuelles et géospatiales, le statut de validation humaine.

**Fonctions.**
- M3.1 Intake depuis M2 et vérification de préparation.
- M3.2 Contexte de la propriété et du site (adresse, distance, accès, historique).
- M3.3 Pipeline de vision : qualité de l'image, classification, détection, segmentation, annotation, sans halluciner.
- M3.4 Qualité des photos et confiance des mesures (résolution, flou, angles, échelle, complétude) ; demande précise de photos manquantes.
- M3.5 Détection et segmentation (Grounding DINO + SAM2 + géométrie). Replis : mesure manuelle, OpenCV de base, annotation humaine, qualité de photo seule, estimation par règles.
- M3.6 Moteur de mesure avec bornes d'incertitude. Une seule photo sans échelle = plage ou hypothèse.
- M3.7 Estimation géospatiale (Québec) : normalisation d'adresse, distance, région. Street View sert de contexte seulement, jamais de remplacement des photos du client.
- M3.8 Estimateurs par service : gouttières et descentes, revêtement, soffite/fascia, réparation.
- M3.9 Matériaux et main-d'œuvre (prix de M6 ; à défaut, grille interne versionnée marquée `fallback_price_book`).
- M3.10 Risque et complexité (hauteur, accès, pente, arbres, photos faibles, distance, urgence, petit chantier non rentable).
- M3.11 Prix et marge : minimum rentable, plages, scénarios prudent/normal/agressif. **Jamais sous le minimum rentable sans alerte rouge et validation de Nathan.**
- M3.12 Incertitude par Monte Carlo (P50, P80, facteurs dominants).
- M3.13 Génération de la soumission brouillon : description, matériaux, exclusions, hypothèses, prix, délai, options.
- M3.14 Revue et approbation humaine.
- M3.15 Apprentissage estimé vs réel après chantier.
- M3.16 Base de connaissances de construction au Québec (RAG, prix fournisseurs, historique).
- M3.17 Tableau de bord et mobile.
- M3.18 Intégration mémoire.

**Validation humaine obligatoire si :** confiance sous le seuil, montant au-dessus du seuil, marge sous le seuil, photos insuffisantes, mesure incertaine, service complexe, client à risque, chantier éloigné, prix sous le minimum rentable, donnée fournisseur absente.

**Règle données.** Ne jamais mêler des données privées de clients non anonymisées à des jeux de données d'entraînement externes.

**Échanges.** Reçoit de M2 (lead, propriété, photos), de M6 (prix, stock, fournisseur), de M5 (marges historiques, coûts réels), de M4 (capacité, coût de déplacement). Renvoie à M2 (statut, soumission, confiance), à M6 (besoins matériaux : items, quantités estimées, facteur de perte, confiance), à M1/M2 (demandes de photos), à M5 (prix, marge prévue), à M7 (services demandés, objections de prix, raisons de refus), à M8 et M10.

**Mobile.** Vendeur/admin : lead prêt, demande de photos, annotation, mesure manuelle, scénarios, approbation, risques, marge. Employé : après chantier, matériel réel, temps réel, imprévus, photos finales.

**Portes fermées.** SAM2 en production sur GPU ; Cognee en production ; budgets d'API externes (géocodage, Street View).
**État connu.** `PARTIEL` (~1 294 lignes). OR-Tools, SymPy et Monte Carlo partiellement présents. Manquent SAM2 en production, Cognee, l'E2E d'estimation géospatiale québécoise.
**Preuve de complétion.** Photos insuffisantes bloquent tout prix final ; estimateurs, coûts, prix/marge, Monte Carlo, soumission brouillon et approbation fonctionnels ; SAM2 branché ou porte documentée avec repli ; E2E verts (gouttières avec photos suffisantes, photos insuffisantes, revêtement, estimation risquée, estimé vs réel, contexte géospatial).

---

### M4 — Field Operations (équipes, cédule, dispatch, GPS, exécution)

**Mission.** Le système nerveux terrain. Planifie, optimise, supervise et clôt l'exécution des chantiers. Est le pont entre la vente acceptée et la vraie vie : équipe envoyée, client informé, travaux faits, matériel enregistré, preuves sauvegardées, facture déclenchée.

**Ce que c'est / n'est pas.** Ni un simple calendrier, ni une liste de jobs, ni un GPS bricolé.

**Fonctions.**
- M4.1 Modèle de données terrain (équipes, employés, véhicules, équipements, jobs, visites, routes, GPS, sessions de travail, incidents, complétions).
- M4.2 Profils d'équipes et d'employés : compétences, disponibilité, charge, fiabilité.
- M4.3 Compétences, rôles et certifications ; admissibilité des équipes par job.
- M4.4 Disponibilités et feuilles de temps : **punch in/out**, pauses, temps de déplacement, dépassement d'heures. M4 prépare, M5 valide la paie.
- M4.5 Réception d'un job depuis M2/M3 (soumission acceptée).
- M4.6 Préparation du job : client confirmé, adresse validée, soumission acceptée, matériel connu, équipe admissible, météo, dépôt/finance.
- M4.7 Cédule intelligente : fenêtres client, durées, compétences, véhicules, urgence, météo, regroupement de jobs proches.
- M4.8 Optimisation de tournées (VRP avec fenêtres horaires ; OR-Tools dans les prompts). Si pas de solution parfaite : meilleure solution, jobs non planifiés et raisons.
- M4.9 Couche de fournisseurs de routage (cache, moteurs auto-hébergés, services cloud, repli approximatif). L'optimiseur ne dépend d'aucun fournisseur unique.
- M4.10 Météo et risques terrain (vent, pluie, neige, verglas, chaleur) ; météo critique = blocage ou validation.
- M4.11 Score d'équipe et d'adéquation (voir garde-fous humains).
- M4.12 Tableau de dispatch : vue du jour, semaine, carte, équipes, jobs bloqués, jobs en retard, file de complétion.
- M4.13 GPS en direct et géorepérage.
- M4.14 ETA client et fenêtre de suivi.
- M4.15 App terrain de l'employé, **hors ligne d'abord** (file locale, synchronisation, photos en arrière-plan).
- M4.16 Exécution du job (machine à états, voir ci-dessous).
- M4.17 **Déclencheur de fin de travaux** (cascade de la section 6).
- M4.18 Matériel utilisé et synchronisation avec M6.
- M4.19 Preuves terrain : photos avant/pendant/après, signature, note, GPS d'arrivée, temps. Pas d'usage marketing sans consentement.
- M4.20 Incidents, retards, avenants (un avenant qui augmente le prix exige validation humaine + M3/M5/M2).
- M4.21 Replanification et dépannage.
- M4.22 Analytique terrain vers M8/M9.
- M4.23 Pont temps → paie vers M5.
- M4.24 Intégration mémoire.

**Statuts d'un job.** `draft` → `ready_to_schedule` → `scheduled` → `confirmed` → `materials_ready` → `assigned` → `en_route` → `arrived` → `started` (`paused`, `blocked`) → `completed_pending_review` → `completed_verified` → `invoiced` → `closed` (`cancelled`, `rescheduled`). Chaque transition est auditée.

**Garde-fous humains et vie privée.**
- Signaux de « facteur humain » reformulés en signaux **opérationnels** : adéquation d'équipe, risque de fatigue, équilibre de charge, tendance de performance. Jamais d'étiquette psychologique, jamais de donnée de santé, jamais de sanction RH automatique.
- GPS employé actif seulement pendant les heures et trajets de travail définis ; l'employé sait quand le suivi est actif ; accès admin journalisé ; rétention définie.
- GPS client : uniquement pour son chantier, lien sécurisé, expiration automatique, aucun historique complet.
- Ne jamais promettre une date ni confirmer un chantier sans la confirmation de M4.

**Échanges.** Reçoit de M2/M3 (job, durée, matériel, risques), de M6 (préparation matériel), de M5 (dépôt/finance). Envoie à M6 (matériel utilisé), à M5 (facture brouillon, temps, coûts), à M2 (statut), à M8, à M10 ; notifie le client (avec M1).

**Mobile (central).** Employé : cédule, route, détails du job, **punch in/out**, checklist, photos, **formulaire de matériaux utilisés (M6)**, incident, terminer les travaux, hors ligne. Admin : tableau de dispatch, approbation des complétions. Client : ETA limité.

**Portes fermées.** Fournisseurs de routage payants (Google, Mapbox), notifications SMS (Twilio via M1).
**État connu.** `STUB` (~453 lignes, ancien chemin `module6_equipes`). Manquent l'optimisation de tournées en production, la météo, le score d'équipe, le déclencheur de fin de travaux, le GPS terrain complet, l'E2E mobile terrain, le tableau de dispatch et les intégrations M5/M6/M8/M10.
**Preuve de complétion.** Réception de jobs, préparation, cédule, optimisation en production, météo, dispatch, mobile employé, GPS, ETA respectueux de la vie privée, machine à états, déclencheur de fin de travaux avec synchronisation M6 et facture brouillon M5, incidents et replanification, export des temps vers M5 ; tests unitaires, d'intégration et E2E verts (soumission acceptée → chantier, optimisation d'une journée, équipe en route et suivi client, travaux terminés, météo bloquante, incident terrain) ; documentation complète ; matrice à jour ; **aucune promesse impossible au client, aucun GPS abusif, aucune action financière ou RH sensible sans validation.**

---

### M5 — FinanceCore (comptabilité, fiscalité, paie, CFO IA)

**Mission.** Transformer les événements opérationnels en vérité financière structurée : leads convertis, soumissions acceptées, chantiers terminés, matériaux utilisés, factures, paiements, dépenses, taxes, rapprochements, rapports, trésorerie, rentabilité. Gardien de la santé financière, puis **CFO IA** : comprendre, prévoir, simuler, conseiller.

**Source de vérité financière d'OPSYS-AI.** M2, M8 et M9 la consomment ; ils ne la recalculent pas.

**Fonctions (numérotation de l'extension « CFO IA », qui fait foi).**
- M5.1 Opérations comptables : grand livre, plan comptable, écritures proposées, verrouillage de période, piste d'audit.
- M5.2 Facturation, comptes à recevoir (âge des créances, relances) et comptes à payer (OCR de factures fournisseurs, détection de doublons).
- M5.3 Rapprochement bancaire (Plaid, CSV, Stripe, QuickBooks) avec score de confiance.
- M5.4 Paie et obligations d'employeur : brouillons de paie, retenues, cotisations, DAS, CNESST, T4/RL-1/relevé d'emploi préparatoires.
- M5.5 Conformité fiscale Québec/Canada : calendrier fiscal vivant, TPS/TVQ, acomptes provisionnels, échéances.
- M5.6 Dossier CPA et fin d'année.
- M5.7 Prévision de trésorerie (aujourd'hui → 5 ans, scénarios, tests de stress).
- M5.8 Projection financière des contrats et de la cédule (carnet signé, probable).
- M5.9 Rentabilité par chantier, service, ville, équipe.
- M5.10–M5.12 Conseillers d'achats majeurs : camion, équipement, bâtiment commercial (acheter, financer, louer ; capacité de remboursement).
- M5.13 Conseiller en dette, financement et investissement.
- M5.14 Stratégie d'épargne et de réserves.
- M5.15 Conseiller fiscal et comptable stratégique (préparatoire).
- M5.16 Moteur de décision CFO (rapport en 25 sections).
- M5.17 Garde de risque financier et pré-audit (contrôleur, auditeur interne).
- M5.18 Base de connaissances fiscale et comptable (RAG sourcé, séparé des données privées).
- M5.19 Tableau de bord CFO.
- M5.20 Intégration mémoire.
Transversal : conformité Loi 25, multi-entités, adaptateurs QuickBooks, CCube, Stripe, Plaid, import CSV.

**Concept central.** *Solde bancaire ≠ argent disponible.*
**Cash libre réel = solde bancaire − taxes − paies − DAS − comptes à payer − dettes − obligations − réserves critiques.** Le système n'affiche jamais un « cash disponible » sans soustraire les obligations connues.

**M5 peut automatiquement :** lire, classer, extraire, créer des brouillons, proposer des écritures et des rapprochements, détecter des doublons, produire rapports, alertes, tâches, exports, dossiers CPA, brouillons QuickBooks, simulations et scores de confiance.
**M5 ne peut jamais, sans validation humaine :** payer (fournisseur, impôt, taxe, employé), virer, rembourser, faire une écriture finale, déposer une déclaration officielle, changer les taxes, supprimer une facture, une transaction ou un client, modifier le plan comptable, fermer une période, faire la paie, agir auprès de Revenu Québec/ARC, acheter un actif, emprunter, investir, signer un contrat. Chaque cas crée une demande d'approbation.
**Mention obligatoire** sur toute réponse stratégique : *« Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision officielle ou action réelle. »*
**Échelle de permissions F0–F7.** F0 lecture, F1 brouillon, F2 tâche interne (automatiques) ; F3 modification interne non finale ; F4 envoi client ; F5 modification comptable finale ; F6 argent réel (double confirmation) ; F7 fiscal/légal (Nathan + professionnel). Au départ, `auto_send_invoice_max_amount = 0` : tout envoi réel est validé.

**Règles fiscales et paie.** Aucun taux fiscal codé en dur sans année, source et version. Tables absentes ou données d'employé incomplètes : on bloque. Aucun calcul de paie sans version et traçabilité. Aucune réponse fiscale sans source officielle. Le mode de fonctionnement des logiciels externes : lecture seule → essai à blanc → bac à sable → écriture avec validation.

**Limites d'expertise.** M5 n'est **pas un conseiller financier réglementé** : ses sorties sont des analyses préparatoires, jamais un avis fiscal officiel. Il produit scénarios et questions à poser au CPA, au fiscaliste, à l'avocat ou au prêteur. Les jeux de données publics (OCR de factures, classification de dépenses) servent seulement à des tâches contrôlées (extraction, classification, mapping de comptes). La fiscalité locale reste du RAG sourcé sur les documents officiels (Revenu Québec, ARC, CNESST) plus des règles et une validation du CPA ; on n'affine jamais un modèle pour « inventer » des conseils fiscaux. L'historique de l'entreprise (jusqu'à 10 ans) sert aux projections.

**Échanges.** Reçoit de M2 (soumission acceptée, client), de M3 (prix, marge prévue), de M4 (temps, statut), de M6 (bons de commande, réceptions, factures fournisseurs, écarts de prix, coût réel du matériel). **M6 ne paie jamais : M5 gère les comptes à payer.** Fournit à M7 (coût par lead, ROI), à M8 (métriques financières propres), à M9 (diagnostics, projections), à M2 (statut de paiement, solde, lien de paiement). M1 peut demander un statut de facture, jamais une modification.

**Mobile.** Admin : factures à approuver, paiements reçus, retards, dépenses à valider, trésorerie, anomalies. Employé : matériel utilisé, photo de reçu, confirmation de fin de travaux (jamais d'écriture finale). Vendeur : marge estimée de la soumission, statut de paiement, relance autorisée. Client : facture, lien de paiement, reçu, historique simple. **Jamais de marges ni de coûts internes visibles pour le client.**

**Portes fermées.** OAuth QuickBooks, CCube, actions financières et légales, dépenses infonuagiques, validation par le CPA pour tout ce qui est officiel.
**État connu.** `FAIT_VÉRIFIÉ` pour la base (~14 249 lignes, ~91 fichiers Python, ~238 routes sous `/compta`). QuickBooks et CCube en `STUB` (gate). L'extension CFO IA (paie, fiscalité, projections, conseillers, tableau de bord CFO) est **à construire** et devient prioritaire.
**Preuve de complétion (CFO IA).** Paie brouillon, calendrier fiscal vivant, réserves et cash libre réel, prévisions 13 semaines à 24 mois alimentées par contrats et cédule, simulations camion/équipement/bâtiment, comparaisons emprunt vs comptant, rapport de décision CFO, tableau de bord CFO, mémoire M10, sources fiscales citées, E2E verts, toute action critique bloquée sans validation.

---

### M6 — Material Control (inventaire, achats, fournisseurs, bons de commande, variance)

**Mission.** La vérité des matériaux : catalogue, fournisseurs, prix, bons de commande, stock, réservations par chantier, sorties terrain, écarts. Le système nerveux matériel d'OPSYS-AI. **Il empêche l'entreprise de perdre de l'argent par mauvaise gestion des matériaux** : matériau oublié ou commandé en double, mauvais fournisseur, prix ou item, chantier planifié ou équipe envoyée sans matériel, usage non déclaré, perte disproportionnée non détectée, erreur d'estimation non apprise, bon de commande non suivi, stock faux, facture fournisseur impossible à rapprocher, marge détruite par un coût réel supérieur au prévu.

**Ce que c'est / n'est pas.** Ce n'est ni un simple tableau de stock, ni une liste de matériaux. M6 ne refait ni M3 (estimation), ni M4 (terrain), ni M5 (finance). **M6 ne paie pas** : M5 gère les comptes à payer.

**Fournisseurs initiaux :** Gentek, Royal Solution de Bâtiment, O.A.M., Kaycan.

**Fonctions.**
- M6.1 Catalogue de matériaux : SKU interne, catégorie, service lié, fournisseur principal et alternatif, unité, couleur, dimensions, prix estimé et validé, compatibilités, substitutions. Catégories : gouttières, descentes, coins, coudes, fascia, soffite, revêtement, moulures, membrane, vis, scellant, accessoires, consommables, outils, équipements, matériaux spéciaux.
- M6.2 Registre des fournisseurs : contact, courriel de commande, délais habituels, catégories vendues, format de commande préféré, historique de prix, fiabilité, erreurs passées.
- M6.3 Livre de prix : prix par item, fournisseur et date ; historique, hausses, factures et PO liés. **Un prix sans source est marqué `ESTIMATED` ou `FALLBACK_PRICE_BOOK`.**
- M6.4 Besoins matériaux depuis M3 : items, quantités estimées, unité, facteur de perte, confiance. M6 valide, vérifie le stock, réserve, crée un besoin de commande, recommande un fournisseur, estime le coût, puis retourne la préparation du matériel à M3/M4.
- M6.5 Moteur de bons de commande (PO). Statuts : `draft`, `pending_admin_review`, `approved`, `email_ready`, `sent_to_supplier`, `supplier_confirmed`, `partially_received`, `received`, `cancelled`, `disputed`, `invoiced`, `closed`.
- M6.6 **Commande par courriel via M1** : M6 génère le courriel (objet, destinataire, liste des matériaux, chantier, date requise, livraison ou retrait, numéro de PO) ; M1 le révise, l'envoie si la politique l'autorise et suit la réponse. **M1 est le canal ; M6 reste la source de vérité du PO.**
- M6.7 Réception et entrée en stock : complète, partielle, item manquant, substitué, prix différent, dommage, photo, livraison au dépôt ou au chantier, ramassage chez le fournisseur. Un prix réel qui s'écarte du prévu au-delà du seuil crée une alerte admin et un signal à M5 et M8.
- M6.8 Réservation par chantier : pas de double réservation, libération en cas d'annulation, ajustement si l'estimation change.
- M6.9 Emplacements de stock : dépôt principal, camion, remorque, chantier, employé, fournisseur, retour, rebut, inconnu. Tout transfert est audité.
- M6.10 **Formulaire mobile des matériaux utilisés** (voir section 9) : s'ouvre quand l'employé termine le chantier.
- M6.11 Validation des sorties : item prévu ou non, quantité vs estimée, unité cohérente, stock disponible, retours, pertes, bris, achat terrain justifié, photo ou reçu requis.
- M6.12 Moteur de variance estimé vs réel : écarts de quantité, d'items non prévus ou non utilisés, de perte, de prix, d'unité, d'estimation. Causes possibles : `estimation_error`, `field_change`, `waste`, `breakage`, `data_entry_error`, `unexplained_usage`. Un écart critique passe le chantier en `completed_pending_review`.
- M6.13 Alertes de perte, gaspillage, bris et usage inexpliqué. Déclencheurs : usage au-dessus du seuil, matériau cher sans estimation, pertes élevées, écarts répétés pour une même équipe, stock négatif, ajustements manuels fréquents, commande reçue mais stock disparu, chantier fermé sans usage déclaré.
- M6.14 Ajustements et piste d'audit : correction, perte, bris, retour fournisseur ou chantier, stock retrouvé, erreur de saisie, inventaire physique, transfert, annulation. Chacun garde acteur, raison, avant, après, source, preuve, approbation si nécessaire.
- M6.15 Réapprovisionnement : seuils, stock réservé et disponible, chantiers à venir (M4), besoins (M3), délai fournisseur, saison, prix, risque de rupture, suggestion de commande.
- M6.16 Pont finance vers M5 : PO, réception, facture fournisseur, taxes, écart de prix, chantier lié. M5 renvoie l'AP, le statut de paiement, le coût validé, le rapprochement.
- M6.17 Achats imprévus sur le terrain : limités, tracés, photo du reçu, approbation, envoyés à M5.
- M6.18 Tableau de bord et mobile admin ; M6.19 pont analytique vers M8 ; M6.20 signaux stratégiques vers M9 ; M6.21 mémoire M10.

**Règles dures.**
- **Jamais** : envoyer une commande réelle sans validation ou politique explicitement autorisée ; **accuser un employé de vol** ; ajuster l'inventaire sans trace ; modifier un coût fournisseur officiel sans source ; supprimer l'historique ; masquer un écart. Pas de suppression dure sans gate.
- **Le système ne dit jamais « vol ».** Il dit : *« Écart matériaux critique — validation admin requise. Causes possibles : erreur d'estimation, changement terrain, perte, bris, mauvaise saisie, retour non déclaré ou usage non expliqué. »* L'admin classe ensuite la cause.
- L'employé peut déclarer l'usage réel mais **ne voit pas les coûts sensibles**.
- Les automatisations planifiées peuvent créer tâches, notifications internes, brouillons de courriel, scans et rapports ; elles ne peuvent pas envoyer une commande sans politique, ajuster un stock critique sans audit, accuser quelqu'un, payer, supprimer ni masquer un écart.
- Rôles : `admin`, `inventory_manager`, `field_employee`, `seller`, `finance`, `system_agent`, propriétaire.

**Échanges.**
- **Reçoit** de M3 (besoins matériaux), de M4 (matériaux utilisés, pertes, retours, bris, achats terrain, photos et reçus, notes), de M5 (facture fournisseur, statut de paiement, coût validé), de M1 (confirmation du fournisseur, réponses).
- **Fournit** à M3 (disponibilité, coût source, fournisseur recommandé, délai, substitution, risque de rupture, coût réel ou livre de prix), à M4 (matériel prêt ou à commander), à M5 (coût réel, PO, réception, écart de prix), à M8 (`stockout_count`, `stock_value`, `reorder_recommendations`, `purchase_requests`, `supplier_price_change_rate`, `material_variance`, `inventory_accuracy`, `high_variance_jobs`, `material_waste_rate`, délai des PO, fiabilité des fournisseurs), à M9 (risque de rupture, hausse de prix, opportunités d'économie), à M10 (écarts, prix, fournisseurs, pertes, décisions admin, leçons). Renvoie à M3 les erreurs d'estimation pour son apprentissage.

**Mobile (central).** Employé : matériaux prévus pour le chantier, formulaire des matériaux utilisés, ajout d'item, quantité réelle, retour, perte ou bris, achat terrain, photo du reçu, notes. Admin : alertes matériaux, PO à approuver, écarts de chantier, stock critique, réception rapide, validation d'usage, rapport de pertes et bris.
**Tableau de bord admin :** stock critique, commandes en attente, PO à approuver et envoyés, réceptions partielles, écarts importants, pertes et bris, chantiers sans matériel prêt, fournisseurs en retard, hausses de prix, stock réservé et disponible, variance par équipe, chantier et service.

**Portes fermées.** Aucune API externe obligatoire. Portes de politique : envoi réel de commandes à un fournisseur, ajustements de stock critiques, achats terrain.
**État connu.** `STUB` (« thin, à concevoir »). Prompt daté du 23 juin 2026.
**Preuve de complétion.** Catalogue, fournisseurs, livre de prix (ou repli documenté), besoins reçus de M3, PO, courriel fournisseur via M1 (ou repli manuel documenté), réception, réservations, formulaire mobile de l'employé, sortie de stock, variance estimé vs réel, alertes admin sur le tableau de bord et le mobile, coûts réels reçus par M5, métriques reçues par M8, signaux reçus par M9, leçons dans M10, **aucun employé accusé automatiquement**, piste d'audit sur chaque ajustement, tests et documentation. E2E : estimation → PO Gentek → approbation ; réception partielle ; travaux terminés normaux ; écart important (ex. 40 % de plus que prévu) ; risque de rupture.

---

### M7 — Marketing & Croissance IA (CMO IA)

**Mission.** Un département marketing complet, branché sur les données réelles de l'entreprise. Agit comme CMO IA, équipe de réseaux sociaux, stratège de croissance, analyste publicitaire, expert SEO local, gestionnaire de réputation, créateur de contenu et conseiller marketing. **Pas seulement SEO et publicité payante** : ce n'est qu'une sous-partie. Objectif : croissance réelle, légitime et mesurable (visibilité, notoriété, leads, conversion, coût par lead et par vente, réputation, rentabilité).

**Fonctions.**
- M7.1 Identité de marque : voix, promesse, zones desservies, messages interdits, garde-fous de marque.
- M7.2 Centre de commande des réseaux sociaux : Facebook, Instagram, TikTok, YouTube/Shorts, LinkedIn, Google Business Profile ; calendrier, brouillons, publication assistée. Si l'API officielle ne permet pas la publication, **paquet manuel** (texte, mots-clics, média, heure, instructions).
- M7.3 Usine à contenu : chantier → contenu (détecter un chantier terminé, récupérer photos et notes, angle marketing, variantes par plateforme, contrôle de marque et de confidentialité, brouillon, validation, publication ou export, mesure, apprentissage).
- M7.4 Moteur de croissance organique (aucun faux abonné, faux like, pod, spam, message massif).
- M7.5 Réputation : suivi des avis Google, demandes d'avis, brouillons de réponses, alerte d'avis négatif.
- M7.6 SEO local et contenu SEO (Search Console, suivi de positions, pages locales).
- M7.7 Médias payants et intelligence publicitaire : **lecture et recommandations** ; toute modification réelle de campagne ou de budget crée une demande d'approbation.
- M7.8 ROI et attribution : marketing → leads → ventes → profit.
- M7.9 Veille concurrentielle (sources publiques légales, avec niveau de confiance).
- M7.10 Marketing local hors ligne : lettrage de camions, pancartes de chantier, dépliants, programme de référence, partenariats.
- M7.11 Conseiller CMO stratégique : plans 30/60/90 jours, rapport hebdomadaire, campagnes saisonnières.

**Garde-fous.**
- Niveaux 0–2 automatiques (lecture, brouillon, tâche interne). Niveau 3 (publication faible risque) : validation au départ. Niveau 4 (campagne, budget) et niveau 5 (avis négatif, plainte, crise) : validation de Nathan. Niveau 6 (légal, financier, rabais majeur) : jamais sans humain.
- Contrôle de qualité avant toute sortie publique. Blocages : promesse non vérifiable, garantie ou prix inventés, photo de client sans autorisation, adresse ou visage ou plaque visibles, exagération, ton non conforme, réponse à un avis négatif sans validation.
- Toujours distinguer : automatisable maintenant, nécessite OAuth/API, nécessite Nathan, nécessite l'approbation de la plateforme, doit rester manuel.

**Échanges.** Reçoit de M2 (qualité des leads, raisons de perte), de M5 (coût par vente, revenus par canal), de M4 (chantiers terminés, photos), de M1 (questions fréquentes). Envoie des leads à M1 (source, UTM, campagne), des métriques à M8, des contenus à valider.

**Mobile.** Admin : tableau de bord marketing, contenus à approuver, avis à répondre, rapport hebdomadaire. Vendeur : suggestions de contenu, demande de photos avant/après, mini-témoignage, signaler un client satisfait. Employé : après chantier, photos, notes, autorisation du client, qualité, « client satisfait oui/non », « potentiel de contenu ». **L'employé ne publie pas : il alimente l'usine à contenu.**

**Portes fermées.** OAuth Google Ads, Search Console, Google Business Profile, approbations Meta, TikTok, LinkedIn, YouTube.
**État connu.** `STUB` (ancien « M7 Marketing/SEO », chemin `module8_seo`). Matomo, SerpBear, n8n, Langfuse, Qdrant étaient déjà déployés.
**Preuve de complétion.** Brand Core, usine à contenu, calendrier social et approbations fonctionnels ; chantier → contenu ; au moins un workflow automatisé ; lecture réelle ou simulée explicitement de Matomo/SerpBear ; ROI lié à M2 et M5 ; moteur de réputation ; plan stratégique fondé sur les données ; publications publiques toujours validées ; mode d'export manuel si accès absents ; E2E vert (chantier de gouttières terminé à Repentigny → 5 contenus → approbation → publication ou export → mesure).

---

### M8 — Business Truth & Analytics (vérité chiffrée)

**Mission.** Le moteur de vérité mesurable. **M8 mesure, valide, expose, alerte, explique et compare. Il ne décide pas** (M9), **ne fait pas la comptabilité** (M5), ne vend pas (M2), ne planifie pas (M4), ne commande pas (M6), ne fait pas la mémoire (M10).

**Fonctions.**
- M8.1 Hub de collecte : connecteurs vers M1–M7, M9, M10 avec état (fonctionnel, en panne, périmé, partiel).
- M8.2 Entrepôt de données : faits, dimensions, marts métier ; ne remplace pas les tables transactionnelles.
- M8.3 **Couche sémantique et registre de métriques** : chaque métrique définie une seule fois (définition métier et technique, source, grain, fraîcheur, permissions, version). **Aucun tableau de bord officiel n'utilise une métrique non enregistrée.**
- M8.4 Qualité des données : tests (non nul, unicité, intégrité, fraîcheur, plage, cohérence des factures…).
- M8.5 Fraîcheur, lignée et score de confiance. Badges : `LIVE`, `FRESH`, `STALE`, `PARTIAL`, `ESTIMATED`, `MISSING`, `QUALITY_FAIL`, `GATED`. **M8 ose dire « donnée pas fiable ».**
- M8.6 Tableau de bord exécutif (simple, clair, actionnable).
- M8.7 Tableaux de bord par département (M1, M2, M3, M4, M5, M6, M7, M9).
- M8.8 Wallboards en direct (mode TV, rotation, bannière d'alerte).
- M8.9 Alertes métier : **chaque alerte propose une action**, pas seulement un problème.
- M8.10 Tendances, prévisions et écarts (prévu vs réel : matériel, main-d'œuvre, marge, durée, marketing, pipeline, trésorerie).
- M8.11 Score de santé de l'entreprise, **transparent** : les facteurs sont toujours montrés.
- M8.12 Copilote analytique en langage naturel : SQL sûr, aucune requête destructive, aucune métrique non définie, aucune réponse sans source, permissions respectées, décisions renvoyées à M9.
- M8.13 Générateur de rapports.
- M8.14 Pont vers des outils BI externes (Superset, Metabase, Grafana), qui lisent la couche M8, pas les tables brutes.
- M8.15 Analytique mobile par profil.
- M8.16 Sécurité et accès : un employé ne voit ni marges, ni coûts sensibles, ni finances globales.
- M8.17 Fournisseur de preuves pour M9.
- M8.18 Intégration mémoire.

**Échanges.** Lit tous les départements. Fournit à M9 des paquets de preuves ; à Nathan des tableaux de bord et alertes ; à M10 les changements de définition, anomalies et échecs de qualité. **Pour la finance, M8 consomme M5 et ne recalcule pas.**

**Mobile.** Admin : tableau de bord exécutif, alertes, wallboard. Vendeur : ses ventes. Employé : résumé de performance limité et **non punitif**. Client : aucune métrique interne.

**État connu.** `PARTIEL` (~379 lignes) : tableau de bord, score de santé et tendances existent. Manquent connecteurs de production, couche sémantique, qualité de données, lignée, alertes, wallboard, copilote.
**Preuve de complétion.** Connecteurs de production ou portes documentées, registre de métriques, qualité, fraîcheur, tableau de bord exécutif live, wallboard, alertes, copilote sécurisé, paquets de preuves reçus par M9, contrôle d'accès par métrique, E2E analytiques (ventes, rentabilité de chantier, ROI marketing, rupture de stock, risque de trésorerie, échec de qualité).

---

### M9 — Strategic Intelligence (direction IA)

**Mission.** Le cerveau de direction. Lit tous les départements, comprend l'état réel, priorise, simule, détecte les risques et les occasions, prépare les décisions pour Nathan. Répond à : *que devrait faire l'entreprise maintenant, pourquoi, avec quelles preuves, quels risques, quel impact, quelles alternatives, quelles dépendances et quelle validation humaine ?*

**Frontières.** M9 ≠ M5 (finance détaillée), ≠ M8 (mesure), ≠ M10 (mémoire, que M9 utilise). M9 est au-dessus des départements sans les remplacer.

**Fonctions.**
- M9.1 Tissu de données stratégique : snapshots M1–M8, fraîcheur, contradictions.
- M9.2 Graphe d'état de l'entreprise (impacts : « si M6 est en rupture, quel effet sur M4, M5, M2 ? »).
- M9.3 Couche sémantique exécutive (définitions alignées sur M8).
- M9.4 **Conseil d'agents** : conseiller PDG, opérations, liaison finance, croissance marketing, stratégie de vente, rentabilité d'estimation, contraintes d'inventaire, expérience client, responsable des risques, auditeur de données, planificateur d'exécution, critique de décisions. **Aucun agent ne décide seul** : superviseur → agents de département → auditeur de données → critique → gouvernance → recommandation finale.
- M9.5 Salle de guerre quotidienne (briefing du matin).
- M9.6 Rapport exécutif hebdomadaire ; M9.7 revues mensuelle et trimestrielle.
- M9.8 Moteur de scénarios et tests de stress (hausse de budget marketing, baisse de leads, hausse du coût des matériaux, absences, météo, achat de camion, nouvel employé, gros client perdu, nouvelle ville…).
- M9.9 Prévisions consolidées (M9 consolide et interprète ; le détail de trésorerie reste à M5).
- M9.10 Intelligence de décision : rapport en 21 sections (question, décision recommandée, options, données utilisées et manquantes, hypothèses, scénarios, impacts, dépendances, conditions, validation, plan d'action, mesure du succès).
- M9.11 Priorisation et allocation de ressources.
- M9.12 Radar de risques ; M9.13 radar d'occasions ; M9.14 veille de marché.
- M9.15 Playbooks stratégiques (crise de trésorerie, chute de leads, surcharge de cédule, semaine de mauvais temps, rupture de stock, hausse de prix…).
- M9.16 Planification d'exécution et OKR.
- M9.17 Orchestrateur d'actions : crée des tâches contrôlées dans les départements.
- M9.18 Expériences et ROI.
- M9.19 Gouvernance et validation humaine.
- M9.20–M9.23 Mémoire, tableau de bord exécutif, briefing mobile, évaluation et confiance.

**Règles dures.** Jamais inventer de chiffre, de revenu ni de capacité. Jamais contredire M5 (finance), M2 (pipeline), M4 (cédule), M6 (inventaire), M7 (marketing) ni la mémoire canonique de M10. Jamais masquer l'incertitude. Jamais de recommandation sans source ou hypothèse explicite. Validation obligatoire pour dépense réelle, changement de budget marketing, embauche, achat majeur, dette, modification globale des prix, décision fiscale ou légale, contrat, suppression de données.

**Mobile.** Admin/Nathan seulement : briefing du matin, alertes critiques, décisions en attente, scénarios, rapports, poser une question stratégique.

**État connu.** `STUB` (~169 lignes, proxy `dept_financier.py`, ancien chemin `module7_strategie`). Manquent projections, rapport hebdomadaire live, lecture transversale, scénarios, priorisation, tableau de bord, gouvernance, intégration M10, E2E.
**Preuve de complétion.** Module réel lisant M1–M8, M10 utilisé, couche sémantique, salle de guerre et rapport hebdomadaire live, scénarios, prévisions, décisions, radars, conseil d'agents avec critique, gouvernance bloquant les actions risquées, orchestrateur d'actions, évaluations (fidélité aux sources, qualité de décision, taux d'hallucination), E2E verts, **aucune décision majeure sans validation de Nathan**.

---

### M10 — Mémoire (long terme, intelligence, conscience opérationnelle)

**Mission.** Le cerveau permanent. Capture, organise, relie, vérifie, révise, récupère et injecte le contexte pour que le système **n'oublie rien d'important et ne travaille jamais dans le vide**. Rien n'est trop petit pour être mémorisé s'il peut influencer une décision future.

**Ce que ce n'est pas.** Pas un simple RAG : une mémoire complète, gouvernée, vérifiable, versionnée, interrogeable, auditable.

**Deux mondes, liés mais séparés par permissions et confidentialité.**
1. **Mémoire de l'usine** (Forge) : code, plans, prompts, protocoles de développement. *Voir point ouvert n° 5.*
2. **Mémoire d'affaires** : clients, procédures, services, prix, marketing, comptabilité, équipes, inventaire, factures, chantiers, erreurs, apprentissages.

**Ce qu'elle mémorise (côté produit).** Modules et leur état, décisions (avec raison, options, conséquences, statut), erreurs et leçons, règles et instructions de Nathan, préférences de clients, promesses humaines, plaintes, hypothèses d'estimation, décisions financières et stratégiques, tests et preuves, historique des changements, **modèle de soi** d'OPSYS-AI (identité, mission, limites, modules, règles, portes).

**Dix règles.** (1) Toute tâche laisse une trace. (2) Aucun agent n'agit sans contexte. (3) Rien n'est écrasé sans mémoire. (4) Toute décision a une raison. (5) La mémoire est révisable (remplacer, archiver, expurger, pierre tombale ; **pas de suppression dure par défaut**). (6) Tout est sourcé. (7) Le système se connaît lui-même. (8) Mémoire avant génération. (9) Mémoire après action. (10) **Pas de mémoire magique** : explicite, testée, auditable.

**Ordre de vérité en cas de contradiction.** Constitution du système → décisions explicites de Nathan → matrice de complétion à jour → rapports récents validés → tests et sondes → code actuel → documentation → journaux récents → mémoires anciennes → hypothèses. Une contradiction n'est jamais tranchée au hasard : elle est enregistrée et résolue.

**Statuts de mémoire.** `active`, `draft`, `verified`, `stale`, `superseded`, `contradicted`, `archived`, `rejected`, `sensitive`, `requires_review`.
**Niveaux de confidentialité.** `PUBLIC_INTERNAL`, `INTERNAL`, `SENSITIVE`, `FINANCIAL`, `CLIENT_PRIVATE`, `SECRET_REF`, `LEGAL_LOCKED`.

**Couches (dans les prompts).** Journal d'événements immuable, mémoire structurée (base relationnelle), mémoire vectorielle, graphe de connaissances (avec repli sur relations en base), points de reprise de workflows, registre de décisions, mémoire d'affaires, modèle de soi, routeur de récupération, **injecteur de contexte**, auditeur de mémoire, gouvernance, banc d'évaluation.
**Paquets de contexte.** Chaque département a les siens (ex. identité, politiques, contexte client) et les charge avant toute action critique. Ils sont en couches pour économiser les tokens.
**Récupération.** Combine sémantique, mots-clés, module, fraîcheur, importance, statut, autorité de la source, voisinage dans le graphe, permissions ; pas une simple similarité.

**Lien avec la directive de septembre.** La mémoire d'OpenClaw2 est jugée excellente ; un **RAG premium est obligatoire**, avec documentation en prérequis. M10 doit s'appuyer sur ces éléments sans perdre les garde-fous ci-dessus.

**Mobile.** Admin : recherche dans la mémoire, décisions à valider, contradictions. Employé : ajouter une note de chantier ou une « chose à ne pas oublier » ; ne voit jamais la mémoire interne. Vendeur : consulter la mémoire client autorisée, ajouter un apprentissage de vente.

**État connu.** `STUB` : `conscience_bridge.py` insuffisant. Manquent la mémoire opérationnelle réelle, le graphe en production, l'auto-amélioration, les jeux de données.
**Preuve de complétion.** Capture des événements, décisions, erreurs, tests ; synchronisation base relationnelle et vectorielle ; couche relationnelle ; paquets de contexte ; consolidation nocturne ; audit « non-oubli » ; modèle de soi ; permissions ; secrets jamais en clair ; détection des contradictions et des mémoires périmées ; réponses sourcées ; E2E verts.

---

## 8. Qui est source de vérité de quoi

| Sujet | Source de vérité | Les autres… |
|---|---|---|
| Première interaction, conversation, transcription | **M1** | M2 reçoit le résumé |
| Client, lead, pipeline, statut d'une soumission | **M2** | M5 fait foi pour l'argent |
| Prix, estimation, marge **prévue** | **M3** | M2 conserve le statut de la soumission |
| Cédule, capacité, temps terrain, statut de chantier | **M4** | M1 ne promet jamais une date sans M4 |
| Factures, paiements, comptabilité, taxes, paie, marge **réelle**, cash libre réel | **M5** | M2, M8, M9 consomment sans recalculer |
| Catalogue, stock, prix fournisseurs confirmés, bons de commande, matériel utilisé, variance des matériaux | **M6** | M5 paie et rapproche les factures ; M1 envoie les courriels de commande ; M3 utilise une grille interne en repli |
| Campagnes, SEO, réseaux sociaux, avis, contenu | **M7** | M2 retourne la qualité des leads |
| Définition officielle des métriques, tableaux de bord, qualité de données | **M8** | M9 s'appuie dessus |
| Stratégie, décisions de direction, priorités | **M9** | Approbations finales par Nathan |
| Mémoire canonique, décisions historiques, règles | **M10** | Chaque département y lit et y écrit |

---

## 9. L'app mobile : pilier du produit

**Directive de Nathan (28 septembre 2026) : l'app mobile est primordiale**, pour l'inventaire, le punch des employés, les vendeurs, et tous les autres profils. Ce n'est pas un complément du dashboard web : c'est l'interface principale de l'employé sur le terrain, du vendeur, du client, et du propriétaire qui approuve depuis son téléphone.

### 9.1 Ce que les prompts établissent

- Une app existait (« forge-app », probablement React Native/Expo), avec **quatre profils** : admin, employé, client, vendeur, branchée aux API des départements. Les prompts disent de la réutiliser plutôt que de la refaire ; voir le point ouvert n° 9 pour la suite dans le pivot.
- Chaque département définit ses écrans par profil. Les critères de complétion de la plupart d'entre eux incluent leurs écrans ou hooks mobiles.

### 9.2 Exigences non négociables

- **Hors ligne d'abord** pour le terrain : file locale, reprise de synchronisation, détection de conflits, photos envoyées en arrière-plan, GPS mis en tampon, horodatage local et serveur.
- **Localisation en arrière-plan uniquement pendant les heures et trajets de travail**, employé informé, accès admin journalisé.
- **Notifications push** (plus SMS et courriel via M1 selon la politique).
- **Caméra et capteurs** : photos avant/pendant/après, photos de reçus, signature du client, scan de code (QR ou code-barres) pour la réception de stock si retenu.
- **Vues par rôle** : l'employé ne voit jamais coûts, marges ni finances ; le client ne voit aucune donnée interne ; les liens de suivi client sont sécurisés, tokenisés et expirants.
- **Le propriétaire approuve tout depuis le téléphone** : factures, contenus, complétions de chantier, bons de commande, décisions stratégiques, réponses sensibles.

### 9.3 Profil employé (terrain)

- **Punch (M4.4)** : entrée et sortie, départ du dépôt, pauses, temps de déplacement, demande de correction de temps. Les temps alimentent un **brouillon de feuille de temps envoyé à M5** ; M5 valide la paie, jamais l'app.
- **Cédule et route (M4)** : chantiers du jour, route, client et adresse, notes, photos d'estimation, matériel requis, ETA.
- **Exécution (M4)** : en route, arrivé, démarrer, pause, terminer ; checklist ; photos avant/après ; incident ; demande de support ou de changement ; signature du client si requise.
- **Inventaire (M6.10, M6.17)** : à « Travaux terminés », l'app ouvre le **formulaire de matériaux utilisés** : liste prévue (M3/M6), quantités réelles ajustables, ajout d'un item non prévu avec la raison de l'écart, matériel non utilisé, retourné, brisé, perdu, achat terrain (**photo ou reçu obligatoire**), notes, photos, confirmation de l'employé. Brouillon possible, puis soumission. **Aucun coût affiché.**
- **Achat imprévu sur le terrain** : fournisseur, montant, item, raison, photo du reçu, chantier ; approbation, puis envoi à M5.
- **Réception de stock** (si assigné) : saisie ou scan de la réception d'un bon de commande (M6.7).
- **Après le chantier, pour le marketing (M7)** : photos, notes, autorisation du client, qualité du résultat, client satisfait oui/non, potentiel de contenu. **L'employé ne publie pas.**
- **Autres** : photo de reçu ou de dépense (M5), signaler un client qui demande un rappel, une plainte ou une info terrain (M1/M2), noter une « chose à ne pas oublier » (M10), voir sa performance personnelle, limitée et non punitive (M8).

### 9.4 Profil vendeur

- **M2** : ses leads avec le résumé de conversation de M1, priorité, prochaine meilleure action, Client 360, photos, notes, soumissions, relances autorisées, coach de vente, pipeline personnel.
- **M3** : lead prêt pour l'estimation, demander des photos au client, annoter une photo, ajouter une mesure manuelle, lancer l'estimation, comparer les scénarios, approuver la soumission, voir risques et marge, demander une visite terrain.
- **M5** : marge estimée de la soumission, statut de paiement du client, relance autorisée, documents manquants.
- **M7** : suggestions de contenu terrain, demander des photos avant/après, mini-témoignage, signaler un client satisfait.
- **M10 et M8** : mémoire client autorisée, ajouter un apprentissage de vente (objection), analytique de ses ventes.
- **Ne voit pas** : finances globales, coûts internes au-delà de sa soumission.

### 9.5 Profil admin / propriétaire (Nathan)

- **Approbations** : factures (M5), contenus et réponses aux avis (M7), complétions de chantier (M4), **bons de commande (M6)**, soumissions risquées (M3), décisions stratégiques (M9), décisions à valider (M10).
- **M1** : inbox omnicanal, appels manqués, rappels, messages urgents, plaintes, transferts, « prendre en charge », « rappeler », « envoyer la réponse approuvée ».
- **M4** : dispatch du jour, retards, incidents, file de complétion.
- **M6** : **alertes matériaux, PO à approuver, écarts de chantier, stock critique, réception rapide, validation d'usage, rapport de pertes et bris**, détails du chantier.
- **M5** : paiements reçus, impayés, dépenses à valider, trésorerie et cash libre réel, anomalies, dossier CPA, rapport du contrôleur.
- **M7, M8, M9, M10** : tableau de bord marketing et avis à répondre ; tableau de bord exécutif, alertes et wallboard ; briefing du matin, alertes critiques, décisions en attente, scénarios, question stratégique ; recherche dans la mémoire et contradictions.

### 9.6 Profil client

- Soumettre une demande, envoyer des photos, voir le statut de la demande et de la soumission, rendez-vous, message simple (M1/M2).
- Suivi d'arrivée limité : ETA, lien sécurisé et expirant (M4).
- Facture, statut de paiement, lien de paiement, reçu, historique simple (M5).
- **Aucune métrique, marge ou coût interne.**

### 9.7 La chorégraphie centrale : « Travaux terminés » dans l'app

1. L'employé touche **Terminer**.
2. L'app vérifie checklist, photos après, temps réel, notes d'imprévus et signature si requise.
3. Elle ouvre le **formulaire des matériaux utilisés** (M6.10).
4. À la soumission, M6 valide et compare estimé et réel.
5. Écart faible : stock ajusté. Écart important : `completed_pending_review` et **alerte sur le mobile de l'admin**.
6. La cascade de la section 6 se déclenche (facture brouillon M5, mise à jour M2, avis et contenu M7, analytique M8, mémoire M10, apprentissage M3).

### 9.8 Écrans proposés dans les prompts (à adapter)

Noms de routes de type Expo Router, donnés à titre de repère :
- **Employé** : `app/(employee)/today`, `route`, `job/[id]`, `job/[id]/checklist`, `job/[id]/materials`, `job/[id]/photos`, `job/[id]/incident`, `job/[id]/complete`, `field-performance-summary`.
- **Admin** : `app/(admin)/strategy-dashboard`, `strategy-daily-brief`, `strategy-decisions`, `strategy-risks`, `strategy-opportunities`, `strategy-scenarios`, `strategy-reports`, `analytics-dashboard`, `analytics-wallboard`, `analytics-alerts`, `analytics-departments`, `analytics-reports`.
- **Vendeur** : `app/(seller)/sales-analytics`.

### 9.9 Dashboard web

Complément de l'app pour l'admin : tableau de dispatch, wallboards, tableaux de bord par département (M4, M5, M6, M8, M9, M10), gestion des connecteurs, des politiques et des utilisateurs, file d'approbations.

---

## 10. Portes fermées (gates) et dépendances externes

| Élément | Département | Repli prévu |
|---|---|---|
| Identifiants Twilio (voix, SMS) | M1, M4 | Bac à sable, messagerie vocale, saisie manuelle |
| SIP réel | M1 | Twilio ou messagerie vocale |
| Politique d'enregistrement d'appels, opt-in SMS/courriel | M1, M2 | Pas d'enregistrement ni de message automatique |
| OAuth QuickBooks | M5 | Lecture seule, essai à blanc, export CSV |
| CCube | M5 | Adaptateur en essai à blanc, import CSV |
| Stripe, Plaid | M5 | Bac à sable, import CSV bancaire |
| OAuth Google Ads | M7 | Lecture seule, recommandations manuelles |
| Search Console, Google Business Profile, Meta, TikTok, LinkedIn, YouTube | M7 | **Paquet manuel d'export** |
| SAM2 en production sur GPU | M3 | Règles, OpenCV, mesure manuelle, annotation humaine |
| Cognee en production | M3, M10 | Relations en base, graphe local |
| Fournisseurs de routage payants (Google, Mapbox) | M4 | Moteurs auto-hébergés, distance approximative |
| Envoi réel d'une commande à un fournisseur | M6, M1 | Brouillon de courriel + validation de l'admin, ou politique explicitement autorisée ; repli manuel |
| Ajustements de stock critiques, achats terrain | M6 | Piste d'audit + approbation |
| Paie, impôts, remises, déclarations | M5 | **Jamais automatique** ; brouillons et préparation seulement |
| Achats majeurs, emprunts, embauche | M5, M9 | Rapport de décision et demande d'approbation |
| Dépenses infonuagiques | Tous | Validation de Nathan |

**Règle :** une porte fermée s'affiche « PARTIEL — GATE NATHAN » et le repli est implémenté et documenté.
**Note :** « Nathan » désigne le rôle propriétaire (`nathan_owner`). Dans une version SaaS, c'est le propriétaire de chaque instance.

---

## 11. État d'avancement connu (juin 2026, à revérifier)

| Dépt | Statut au moment des prompts | Repères |
|---|---|---|
| M1 | `STUB` | Fichiers vocaux en simulation |
| M2 | `FAIT_VÉRIFIÉ` | Pilier avancé ; API `/api/crm` existante |
| M3 | `PARTIEL` | ~1 294 lignes ; SAM2 et Cognee manquants |
| M4 | `STUB` | ~453 lignes ; ancien chemin `module6_equipes` |
| M5 | `FAIT_VÉRIFIÉ` (base) | ~14 249 lignes, ~91 fichiers, ~238 routes `/compta` ; QuickBooks/CCube `STUB` ; extension CFO IA à construire |
| M6 | `STUB` (« thin, à concevoir ») | Prompt dédié du 23 juin 2026 ; fournisseurs initiaux : Gentek, Royal Solution de Bâtiment, O.A.M., Kaycan |
| M7 | `STUB` | Ancien « Marketing/SEO » ; chemin `module8_seo` |
| M8 | `PARTIEL` | ~379 lignes ; tableau de bord, score de santé, tendances |
| M9 | `STUB` | ~169 lignes ; proxy `dept_financier.py` ; ancien chemin `module7_strategie` |
| M10 | `STUB` | `conscience_bridge.py` insuffisant |

Le produit global n'était pas à 100 %. Le plan maître v1.2 (50 décisions D-001 à D-050, 39 risques, 13 réglementations) et le squelette de dépôt existent ; ils sont à **réviser** selon le pivot, pas à jeter.
Ordre de développement ratifié dans le plan v1.2 : **M7 → M1 → M2 → M4**. À revoir avec la restructuration.

---

## 12. Ce que les anciens prompts supposent de Forge et qui doit être redécidé

Les prompts de départements ont été écrits pour le dépôt Forge/GRS/Andromeda. Ils mentionnent des éléments à classer en deux groupes.

**A. Outillage de développement (probablement hors produit)**
Constitution Forge/GRS, matrice de complétion Forge, protocole Cursor (preflight/postflight), mémoire de code et hooks Git, Forge Conscience, orchestrateur RSI, `AGENTS.md`, méthode PROOF IDE. La discipline « pas de faux terminé, preuve à chaque étape » reste valable comme pratique d'ingénierie.

**B. Briques candidates (pas des obligations)**
- Orchestration : LangGraph, Temporal, n8n, Dagster/Prefect.
- Données et mémoire : PostgreSQL, Qdrant, LlamaIndex, Cognee, DuckDB, ClickHouse, dbt/MetricFlow, Great Expectations.
- Modèles : LiteLLM, vLLM, embeddings locaux, DSPy, Ragas, DeepEval.
- Observabilité : Langfuse, OpenTelemetry, Grafana, Superset, Metabase.
- Voix : Pipecat, LiveKit, Twilio, STT/TTS locaux ou cloud.
- Terrain : OR-Tools, PyVRP, Timefold, OSRM, Valhalla.
- Inventaire : QR/code-barres, OCR de documents fournisseurs, courriel sortant via M1.
- Vision : SAM2, Grounding DINO, OpenCV.
- Marketing : Matomo, SerpBear.
- Finance : QuickBooks, CCube, Stripe, Plaid.

Ces briques sont des **ingrédients** : chacune se justifie par la maturité de son code et son utilité pour un département précis, pas par son inclusion dans un ancien prompt.

---

## 13. Points ouverts et incohérences détectées

**Révision 3 :** les points 1, 5, 6, 7, 9, 10 et 11 sont décidés dans l'[ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md). Restent à Nathan : le point 4 (nom commercial) et la portée SaaS de M5 (point 8).

1. **Chemins hérités qui ne suivent pas la numérotation** : M4 = `module6_equipes`, M9 = `module7_strategie`, M7 = `module8_seo`, alors que M6 = `module6_inventory` dans son propre prompt. La numérotation M1–M10 de ce fichier fait foi ; les chemins sont à rationaliser (risque de confusion M4/M6 surtout).
2. **Trois numérotations des sous-modules M5** : prompt de base (M5.1–M5.10), addendum du 8 juin (M5.1–M5.15), extension « CFO IA ultime » (M5.1–M5.20). Ce fichier suit l'extension, la plus complète.
3. **Deux formulations de la mention obligatoire de M5** (« Préparation IA — validation Nathan/CPA requise avant action officielle » dans l'addendum ; « Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision officielle ou action réelle » dans l'extension). Retenir la seconde.
4. **Nom commercial.** Le profil de l'entreprise dit « Gouttières et Revêtements Synergy » ; les modèles de SMS (M1) et de courriel fournisseur (M6) disent « Gouttières et Revêtements Lanaudière ». À confirmer avant de figer scripts et messages.
5. **M10 : la moitié « usine » (Forge) est de l'outillage de développement**, pas du produit. À trancher : la garde-t-on comme mémoire de développement pour les agents, séparée du produit livré ?
6. **Ordre de développement** M7 → M1 → M2 → M4 : à confirmer après restructuration. M6 n'y figure pas encore, alors que M3, M4 et M5 en dépendent (matériaux, coût réel).
7. **« Ne pas reconstruire M2 et M5 » vs « restructurer sans les dépôts Forge ».** Le code existant de M2 (CRM) et de M5 (~14 000 lignes) est-il conservé, porté sur OPSYS-CORE ou réécrit ? Décision explicite et documentée, avec audit préalable.
8. **Portée de M5.** L'extension CFO IA (paie, impôt, achat de bâtiment, stratégie fiscale) est très large et sensible. Confirmer ce qui est livré aux clients SaaS et ce qui reste réservé au propriétaire.
9. **L'app mobile dans le pivot.** L'app existante (« forge-app ») est-elle conservée, portée ou réécrite sur OPSYS-CORE ? Quelle stack (React Native/Expo « probable » selon les prompts) ? À décider tôt : chaque département en dépend, et le hors-ligne, le GPS et la caméra contraignent le choix.
10. **M6 dépend de M1 pour l'envoi des commandes** (courriel sortant). Prévoir le repli manuel que le prompt M6 exige (« fallback manuel documenté »).
11. **Seuils non chiffrés.** Les prompts parlent de seuils (variance des matériaux, confiance, montants élevés, marge minimale) sans valeurs, sauf quelques exemples (M5). Chaque département doit les définir, configurables depuis le dashboard.

---

## 14. Consignes à l'agent qui lit ce fichier

1. **Lire les sections 1, 5, 6 et 7 avant d'écrire du code.** Chaque livraison se rattache à un département et à un flux de la section 6.
2. **Auditer avant de modifier.** Pour chaque département : ce qui existe, ce qui est réutilisable, ce qui est dangereux, la première phase minimale.
3. **Les briques sont des ingrédients.** Prendre du code mûr, l'adapter, le fusionner, puis homogénéiser. Ne pas empiler.
4. **Ne pas livrer d'infrastructure sans département.** Le Core, le dashboard et le RAG existent pour que M1–M10 fonctionnent, pas l'inverse.
5. **Documenter chaque décision** (raison, options, conséquences), y compris les rejets de briques.
6. **Traiter l'app mobile comme un livrable de premier rang.** Chaque département livre ses écrans pour les profils concernés (section 9), en particulier le punch, le formulaire de matériaux utilisés, les approbations et le parcours du vendeur.

**Garde-fous recommandés (proposés par Claude, à valider par Nathan, non décidés) :**
- Avant le grand ménage : étiqueter l'état actuel (tag ou branche) et **archiver plutôt que supprimer**, surtout le plan v1.2 et les ADR.
- Inventaire des **licences** de toutes les briques retenues, pas seulement du Core. Une licence copyleft peut contraindre un produit SaaS.
- Choix du Core par comparatif documenté (point de la section 3), pas par intuition. **Fait : ADR-0008.**
- Le dashboard sera exposé sur un VPS : authentification, stockage chiffré des clés d'API et des modèles dès la conception ; isolation entre clients si le SaaS est multi-instances.
- Suivi minimal des correctifs de sécurité des briques forkées, puisqu'elles ne seront plus mises à jour automatiquement.

---

## 15. Glossaire

| Terme | Sens |
|---|---|
| **Gate Nathan / porte fermée** | Action ou accès qui exige une décision ou des identifiants du propriétaire |
| **Dépôt Forge** | Ancien dépôt d'infrastructure et de méthode de développement, mis de côté |
| **Cédule** | Planification des chantiers et des équipes |
| **Chantier / job** | Travail exécuté chez un client, issu d'une soumission acceptée |
| **Soumission** | Offre de prix présentée au client |
| **Client 360** | Fiche client complète (interactions, soumissions, factures, chantiers, mémoire) |
| **Dispatch** | Affectation et suivi des équipes sur le terrain |
| **VRP / VRPTW** | Problème de tournées de véhicules, avec fenêtres horaires |
| **Géorepérage** | Détection d'arrivée et de départ d'une zone géographique |
| **AR / AP** | Comptes à recevoir / comptes à payer |
| **PO (bon de commande)** | Commande d'achat envoyée à un fournisseur |
| **Livre de prix (price book)** | Prix des matériaux par fournisseur, avec source et date |
| **Variance** | Écart entre matériel, coût ou durée estimé et réel |
| **Facteur de perte (waste factor)** | Marge de matériel perdu prévue dans une estimation |
| **Punch** | Pointage d'entrée et de sortie d'un employé dans l'app |
| **TPS / TVQ** | Taxes de vente fédérale et québécoise |
| **DAS** | Déductions à la source (retenues d'employeur) |
| **T4 / RL-1** | Relevés d'emploi fédéral et québécois |
| **CNESST** | Commission des normes, de l'équité, de la santé et de la sécurité du travail |
| **CPA** | Comptable professionnel agréé |
| **CCA** | Déduction pour amortissement (fiscalité) |
| **Loi 25** | Loi québécoise sur la protection des renseignements personnels |
| **UTM** | Paramètres de suivi de la source d'un visiteur ou d'un lead |
| **SEO local** | Référencement pour les recherches par ville et par service |
| **PII / renseignements personnels** | Données permettant d'identifier une personne |
| **RBAC** | Contrôle d'accès basé sur les rôles |
| **Paquet de contexte** | Ensemble de mémoire préparé et injecté avant une tâche |
| **Paquet de preuves** | Métriques, sources, fraîcheur et qualité fournies à l'appui d'une décision |
| **ADR** | Enregistrement d'une décision d'architecture |
| **Mode bridé / repli** | Fonctionnement dégradé quand un prérequis manque |
| **`fallback_price_book`** | Grille de prix interne versionnée utilisée quand M6 n'est pas prêt |
| **Zone desservie (exemple)** | Lanaudière ; Repentigny est cité dans un scénario de test de M7 |

---

## Annexe A — Sources

| Source | Contenu utilisé |
|---|---|
| Prompt maître M7 (2026-06-08+) | M7 complet |
| Prompt maître M10 (2026-06-08+) | M10 complet |
| Prompt maître M5 et addendum CFO IA (courriel « Départements Comptable », 8 juin 2026) | Base et addendum complets (livrés en version complète lors de la 2e transmission) |
| Extension prioritaire M5 « CFO IA ultime » (Quadruple A+) | Numérotation M5.1–M5.20 ; fait foi |
| Prompt maître M1 (2026-06-08+) | M1 complet |
| Prompt maître M2 (2026-06-08+) | M2 complet |
| Prompt maître M3 (2026-06-08+) | M3 complet |
| Prompt maître M4 (courriel « GRS M4 », 9 juin 2026) | M4 complet (la 1re copie était tronquée au critère 23) |
| Prompt maître M9 (courriel « Intelligence Stratégique », 9 juin 2026) | M9 complet ; la 2e copie ajoute le critère 27 |
| Prompt maître M8 (2026-06-09) | M8 complet |
| Prompt maître M6 (2026-06-23) | M6 complet ; remplace la fiche reconstituée de la révision 1 |
| Plan maître v1.2 et session GRS (juillet–août 2026) | Services partagés du Core, contraintes fondatrices, liste des 10 modules, ordre de développement |
| Directives de Nathan (septembre 2026) | Section 3 : pivot VPS, dashboard, OPSYS-CORE, économie de tokens, RAG premium, briques open source ; **l'app mobile est primordiale (inventaire, punch, vendeurs et autres profils)** |
