# Audit M4 — Field Operations

> Audit historique du 28 septembre 2026, conservé pour traçabilité. Les évolutions ultérieures
> ne sont pas inventoriées ici. Consulter le [plan de consolidation](../programme/RESTRUCTURATION-2026-09-30.md)
> et les [recherches actuelles](../research/R16-2026-09-30/README.md) pour M1/M5/M7/M10. Un statut
> ancien et un nombre de tests ne certifient pas le périmètre cible complet.


**Date :** 2026-09-28 · **Portée :** `departments/m04-field-ops/` seul, aucune modification hors ce
fichier. **Référence produit qui fait foi :** `docs/produit/DEFINITION-PRODUIT.md` §1, §5 (P14), §6,
§7 (M4), §8, §9.3/9.5/9.6/9.7, §10, §13. **Autres sources :** `AGENTS.md`,
`docs/architecture/ARCHITECTURE.md`, `DEPARTEMENTS.md`, `MOBILE.md`,
`docs/compliance/politiques/POLITIQUE-geolocalisation.md`, `docs/research/R7-m3-m4.md` et
`INGREDIENTS.md` (recherche de briques déjà vérifiée le 2026-09-28, licences via GitHub API et
fichiers `LICENSE` bruts), `departments/m03-estimation/` comme référence de format.

**Preuve d'exécution unique** (couvre tout le code métier cité ci-dessous) :
`/opt/opsys-venv/bin/python -m pytest departments/m04-field-ops/tests -q --import-mode=importlib -p no:cacheprovider`
→ code de sortie 0, aucun `F`/`E`. Cette configuration (`-q`) n'affiche pas la ligne de résumé ;
la même commande sans `-q` l'a confirmée : **451 passed in 1.04s**, 0 échec. Ni `ruff` ni
`opsys-metier verifier` n'ont été exécutés : hors du périmètre explicitement autorisé par cette mission.

## Résumé

M4 est en mode ombre, statut interne « EPIC G — vague 1 » : un noyau très solide et intégralement
prouvé (encodage canonique injectif, registre append-only hash-chaîné, machine à états à 7 statuts,
pointage horodaté/géolocalisé, écarts avec file `pending_review`, Work Completion Trigger atomique,
digest déterministe — ≈3 000 lignes de code métier, ≈5 160 lignes de tests, 451 tests verts,
mesuré par `wc -l`). C'est cependant un sous-ensemble étroit du M4 décrit par le produit : pas de
VRP, pas de météo, pas de GPS continu ni de géorepérage dynamique, pas d'équipes/véhicules/
équipements, pas d'app mobile ni de tableau de dispatch, pas de cascade réelle vers les six modules
avals (aucun n'existe assez pour la consommer), pas de pont paie M5 ni de mémoire M10. Le PRD BMAD
du département (`docs/bmad/02-PRD-PM.md`) assume et documente lui-même ce périmètre réduit — ce
n'est pas un oubli, c'est une v1 volontairement bornée « prouvable en CI Python, zéro réseau, zéro
horloge, zéro matériel réel ».

## 1. Inventaire M4.1 – M4.24

| # | Fonction (résumé produit) | Statut | Fichiers | Preuve / note |
|---|---|---|---|---|
| M4.1 | Modèle de données terrain (équipes, employés, véhicules, équip., jobs, visites, routes, GPS, sessions, incidents, complétions) | PARTIEL | `contrats.py`, `etats.py`, `pointage.py`, `ecarts.py`, `outbox.py`, `registre.py` | Intervention/Pointage/DemandeRevue/WCT présents et testés (`test_contrats.py`, `test_etats.py`, `test_pointage.py`, `test_ecarts.py`, `test_outbox.py`) ; Équipe, Employé, Véhicule, Équipement, Visite, Route, Incident nommé absents |
| M4.2 | Profils équipes/employés (compétences, dispo, charge, fiabilité) | ABSENT | — | `technicien_id` est une chaîne opaque sans profil |
| M4.3 | Compétences, rôles, certifications, admissibilité | ABSENT | — | — |
| M4.4 | Punch in/out, pauses, temps déplacement, dépassement, pont paie M5 | PARTIEL | `pointage.py` | `test_pointage.py` : punch in/out seul (arrivée/départ) ; pauses, déplacement, dépassement, brouillon feuille de temps absents |
| M4.5 | Réception job M2/M3 (soumission acceptée) | PARTIEL | `contrats.py` | `test_contrats.py` : lead qualifié M2 (7 clés gelées) seul ; `devis_id` M3 toujours `null` dans le WCT |
| M4.6 | Préparation du job (client, adresse, matériel M6, équipe admissible, météo, dépôt/finance) | ABSENT | — | Aucune de ces vérifications n'existe |
| M4.7 | Cédule intelligente (fenêtres, durées, compétences, véhicules, urgence, regroupement géo) | PARTIEL (faible) | `cedule.py` | `test_cedule.py` : tri round-robin sur (ville tokenisée, type, lead_id) ; `urgence_declaree` jamais lu ; tri sur un hash opaque = aucun regroupement géographique réel possible |
| M4.8 | Optimisation de tournées (VRP, fenêtres horaires) | ABSENT | — | Confirmé par `R7-m3-m4.md` §0 : « pas un VRP » |
| M4.9 | Couche de fournisseurs de routage | ABSENT | — | — |
| M4.10 | Météo et risques terrain | ABSENT | — | `meteo` n'est qu'une valeur d'énuméré de motif de report (`etats.MOTIFS_REPORT`), aucun appel réel |
| M4.11 | Score d'équipe et d'adéquation (opérationnel, jamais psychologique) | ABSENT — et bloqué par construction | `digest.py::garde_conformite_r020` | Garde AST qui interdit tout terme `score/performance/classement/…`, y compris un futur usage légitime |
| M4.12 | Tableau de dispatch (jour/semaine/carte, jobs bloqués/en retard, file de complétion) | ABSENT | — | Aucune route M4 dans `src/opsys/console/` (vérifié par recherche) |
| M4.13 | GPS en direct et géorepérage | PARTIEL (faible) | `pointage.py::distance_km` | Géorepérage ponctuel au punch (Haversine vs rayon), testé ; pas de suivi continu ; consentement de `POLITIQUE-geolocalisation.md` non câblé dans le code |
| M4.14 | ETA client et fenêtre de suivi | ABSENT | — | — |
| M4.15 | App terrain employé, hors ligne d'abord | ABSENT | — | `MOBILE.md` Phase 1 = app OpenClaw générique (chat+GPS+caméra), aucun écran M4 dédié, hors-ligne non traité |
| M4.16 | Exécution du job (machine à états) | PARTIEL | `etats.py` | `test_etats.py` : 7 statuts fermés, table de transitions ratifiée et bien prouvée, vs ~16 statuts du produit (pas de `paused`/`blocked`/`materials_ready`/`completed_verified`/`invoiced`/`closed`) |
| M4.17 | Déclencheur de fin de travaux (cascade §6) | PARTIEL | `outbox.py` | `test_outbox.py` : WCT atomique et prouvé (garde AST + invariants + consommateur idempotent) ; 0 consommateur réel |
| M4.18 | Matériel utilisé et synchronisation M6 | ABSENT | — | `ecarts.py` porte un champ `materiaux: list[str]` dans un écart déclaré, pas un formulaire de sortie de stock |
| M4.19 | Preuves terrain (photos, signature, note, GPS, temps) | PARTIEL | `pointage.py` | GPS + horodatage seuls ; aucune photo, signature ni note |
| M4.20 | Incidents, retards, avenants (avenant $ ⇒ validation humaine + M3/M5/M2) | PARTIEL | `etats.py`, `ecarts.py` | Report (motifs fermés) + écart métier factuel avec double version des faits ; pas d'entité Incident distincte ; avenant à impact prix structurellement impossible dans M4 (voir §2.5) |
| M4.21 | Replanification et dépannage | PARTIEL (faible) | `etats.py` | `reportee → planifiee` légal ; aucune logique de réassignation automatique |
| M4.22 | Analytique terrain vers M8/M9 | ABSENT | — | `digest.py` reste interne, rien n'est poussé vers M8 |
| M4.23 | Pont temps → paie M5 | ABSENT | — | `outbox.calculer_duree_reelle` calcule une durée, rien n'est formaté ni envoyé à M5 |
| M4.24 | Intégration mémoire M10 | ABSENT | — | Déclaré dans `department.yaml` (`memoire: lecture/écriture`), non câblé dans `src/` |

**Totaux : 0 PRÉSENT · 10 PARTIEL · 14 ABSENT.**

## 2. Écarts

### 2.1 Modèle de données
Le registre (`registre.py`) est une liste Python **en mémoire**, jamais persistée : rien ne
survit à un redémarrage du processus. `ARCHITECTURE.md` vise PostgreSQL 17 + pgvector comme socle
métier ; rien n'y est branché pour M4. Le job du produit devient une « intervention » unique
(un seul cycle de vie, pas de multi-visites) portée par un technicien seul (pas d'équipe). Aucune
entité Véhicule, Équipement, Route n'existe : la cédule ne manipule que des identifiants et des
fenêtres, jamais une capacité de véhicule ni un trajet.

### 2.2 Machine à états
Fermée et rigoureusement prouvée (table `TRANSITIONS_AUTORISEES`, refus `REJ-TRANSITION-ILLEGALE`,
garde d'écriture unique par AST pour `terminee`) — c'est la pièce la plus mature du département et
un patron à réutiliser tel quel en l'étendant. Deux écarts de fond avec le produit : (1) granularité
— 7 statuts contre ~16, sans distinction post-complétion `completed_pending_review` vs
`completed_verified` (le code ne route en revue qu'**avant** `terminee` ; §6 du produit prévoit
aussi un statut incertain **après** complétion, ex. écart matériel constaté par M6) ; (2) aucun état
n'est conditionné à M6 (`materials_ready`) ni à M5 (`invoiced`, `closed`) puisque ces départements
n'existent pas encore réellement pour M4.

### 2.3 API
Aucune API REST/JSON pour l'app mobile ou le dashboard, contrairement à la décision de l'ingénieur
en chef n°2 (« exposés aux agents comme outils **et** à l'app/dashboard par API »). Le seul canal
est le serveur MCP (`src/opsys/serveur_mcp.py`, stdio + HTTP « streamable »), consommé par un agent
LLM, pas par un client générique. Un tableau de dispatch temps réel a besoin de lectures typées
rapides et de push (WebSocket/SSE) ; ni l'un ni l'autre n'existe. `src/opsys/console/` (dashboard
admin) ne contient aucune route M4 (vérifié par recherche).

### 2.4 Événements — cascade « Travaux terminés »
Le contrat `WorkCompletionTriggerV1` (`outbox.py`) est bien formé et atomique (une seule écriture
de registre porte la transition et le WCT — CA-M4-11, prouvé par balayage, inspection AST et
consommateur de référence idempotent). Écart concret et citable : `CONSOMMATEURS_CIBLES` ne liste
que `(M6, M5, M2, M7, M8, M10)`, alors que le tableau de cascade §6 de `DEFINITION-PRODUIT.md`
fait aussi réagir **M3** (calibrage estimé/réel) et **M9** (lecture stratégique) à « travaux
terminés ». Le fichier produit fait foi (`CLAUDE.md`) : à trancher explicitement, pas seulement
hériter du brief BMAD de M4 (antérieur, et lui-même limité à six). Aucun transport n'existe entre
le WCT et un module aval réel : les six sont eux-mêmes STUB/PARTIEL, donc rien ne consomme le WCT
en dehors du `ConsommateurReference` de test. Le formulaire de matériaux M6 (9.3/9.7 étape 3) n'est
pas déclenché : M6 est STUB. `m4_notifier_client_completion` (T2) prépare un message correct
(aucun GPS/technicien/lead_id en clair — vérifié par test) mais reste local, sans canal M1/SMS réel
(correctement gaté, cf. §10 produit).

### 2.5 Outils d'agent
13 outils bien construits sur le contrat `opsys.outils` (`Autonomie` T0/T1/T2,
`additionalProperties: false`), testés y compris par une chaîne bout-en-bout réelle
(`test_outils_agent.py::test_chaine_complete_planification_pointage_completion_digest_notification`,
8 appels d'outils enchaînés). Aucun outil T3 : cohérent, puisque `frontieres.py` interdit tout champ
financier dans M4. Conséquence structurelle : un « avenant qui augmente le prix » (M4.20) ne peut
techniquement pas se résoudre à l'intérieur de M4 — M4 ne peut porter que le fait (durée/périmètre/
matériaux déclarés), jamais son impact monétaire ; la composition avec M3/M5 reste à construire et
n'existe pas aujourd'hui (aucun appel MCP inter-département depuis M4).

### 2.6 Écrans mobiles (employé / admin / client)
Zéro écran M4 dédié. La stratégie documentée (`MOBILE.md`, Phase 1) est l'app OpenClaw générique
(chat, localisation, caméra) qui parle à l'agent M4 en conversation — fonctionnellement suffisant
pour déclencher les outils (`m4_pointer`, `m4_creer_demande_ecart`…) mais sans aucun des écrans
natifs attendus en 9.3 : checklist de chantier, formulaire de matériaux, photos avant/après,
signature client, achat imprévu + reçu, réception de stock ; ni du profil admin 9.5 (dispatch,
approbations) ni du profil client 9.6 (ETA tokenisé et expirant). Aucune file hors ligne nulle
part dans le dépôt — contradiction directe avec **P14**, invariant non négociable du produit.

### 2.7 Tableau de dispatch
Absent (M4.12/9.9). `m4_lister_pending_review` et `m4_volumetrie_pending_review` fournissent déjà
les données brutes qu'un tableau de dispatch consommerait, mais aucune surface (API ni UI) ne les
rend visibles à un répartiteur.

### 2.8 Portes et replis
§10 du produit prévoit des replis documentés pour le routage payant (Google/Mapbox → moteurs
auto-hébergés/distance approximative) et pour Twilio (SMS via M1). Aujourd'hui il n'existe pas de
chemin principal dont ces éléments seraient le repli : le round-robin de `cedule.py` et
l'Haversine de `pointage.py` **sont déjà** le mode dégradé, mais rien ne l'affiche comme tel à un
opérateur (pas de badge « mode bridé »), ce qui contredit P10 (« un repli est implémenté **et
documenté** », visible, pas silencieux).

### 2.9 E2E exigés
Le produit exige (§7 M4) : soumission acceptée→chantier, optimisation d'une journée, équipe en
route + suivi client, travaux terminés, météo bloquante, incident terrain. Présent : un seul
scénario heureux en un seul processus (`test_chaine_complete_planification_pointage_completion_
digest_notification`), bon analogue pour « travaux terminés » uniquement, sans persistance ni appel
réel à un module aval. Les cinq autres scénarios n'ont pas d'équivalent testable : VRP, météo, ETA
client, incident distinct d'un écart, et intégration inter-départements réelle n'existent pas
encore.

## 3. Briques candidates

*(Licences et dates déjà vérifiées le 2026-09-28 dans `docs/research/R7-m3-m4.md` via l'API GitHub
et les fichiers `LICENSE` bruts ; Timefold recorroboré indépendamment par recherche web le même
jour.)*

### 3.1 VRP / cédule optimisée (M4.7–M4.8)
| Brique | Dépôt | Licence | Maturité (2026-09-28) | Verdict |
|---|---|---|---|---|
| OR-Tools | google/or-tools | Apache-2.0 | 14 112⭐, push 2026-09-27 | **Retenu** — VRPTW complet, dépendance pip directe, pas de sidecar |
| PyVRP | PyVRP/PyVRP | MIT | 701⭐, push 2026-09-27 | Retenu (alternative) — API Python plus idiomatique, recherche génétique hybride |
| Timefold Solver | TimefoldAI/timefold-solver | Apache-2.0 (édition Community ; Enterprise séparée = multi-thread/nearby-selection haute échelle payants — reconfirmé par recherche web indépendante) | 1 796⭐, push 2026-09-27 | Écarté en v1 — JVM hors stack Python ; à reconsidérer si le rostering d'équipes devient un besoin propre |

Recommandation : OR-Tools en dépendance pip directe dans `cedule.py`, en conservant le contrat de
sortie `{assignations, non_cedulees}` déjà testé, pour ne rien casser côté outils d'agent.

### 3.2 Routage réel — matrices temps/distance (M4.9)
| Brique | Dépôt | Licence | Verdict |
|---|---|---|---|
| OSRM | Project-OSRM/osrm-backend | BSD-2-Clause | **Retenu** — sidecar Docker, extrait `.osm.pbf` Québec, remplace l'Haversine à vol d'oiseau |
| Valhalla | valhalla/valhalla | MIT (vérifié dans `COPYING`) | Alternative — isochrones natifs, utile pour des zones de service |
| GraphHopper | graphhopper/graphhopper | Apache-2.0 (moteur cœur ; API « Directions/Route Optimization » hébergée commerciale séparée) | Écarté v1 — lib Java, redondant avec un conteneur OSRM unique |

### 3.3 Météo (M4.10)
| Brique | Licence | Verdict |
|---|---|---|
| Open-Meteo (API hébergée) | code self-host AGPL-3.0 (non concerné : on consomme l'API, pas le code) ; données CC-BY-4.0 ; gratuit non-commercial 10 000 appels/j | **Retenu** — appel HTTP simple, jamais héberger le code AGPL |
| MSC GeoMet (Environnement Canada) | licence gouv. du Canada, régime proche mais clause exacte non lue intégralement | Retenu en source croisée « données canadiennes officielles » — faire confirmer la clause par un juriste avant usage commercial |

### 3.4 GPS continu / géorepérage de flotte (M4.13)
| Brique | Licence | Verdict |
|---|---|---|
| Traccar | Apache-2.0, 7 810⭐, push 2026-09-27 | Retenu **seulement si** un suivi véhicule continu est demandé (besoin distinct du pointage ponctuel déjà couvert) — sinon effort injustifié pour la taille de flotte visée |

Aucune brique ne couvre le consentement/rétention exigés par `POLITIQUE-geolocalisation.md`
(`employee_consent_location`, purge 12 mois, droits d'accès) : logique métier propre à construire
dans `pointage.py` et dans le futur registre persistant.

### 3.5 App terrain hors ligne (M4.15)
| Brique | Licence | Verdict |
|---|---|---|
| Apps officielles OpenClaw (`apps/ios`, `apps/android`) | MIT | Retenu Phase 1 (déjà décidé dans `MOBILE.md`) — nœud générique, aucun écran ni file hors ligne dédiés à M4 |
| Workbox (Google) | MIT, 13 024⭐ | Patron de référence (Service Worker + file de synchronisation) pour un futur front PWA dédié — aucune brique « appli terrain » complète n'est vendorisable telle quelle (R7) |

OpenFieldService (MIT, 31⭐, trop jeune, hors stack Python) et Field Service Management/ERPNext
(AGPL-3.0, suite lourde) restent écartés — confirmé par R7.

### 3.6 Feuilles de temps / pont paie M5 (M4.4, M4.23)
Aucune brique externe requise : `outbox.calculer_duree_reelle` calcule déjà une durée déterministe
depuis les pointages. Ce qui manque (pauses, temps de déplacement, dépassement d'heures, format
« brouillon feuille de temps » vers M5) est de la logique métier propre. Kimai et suites
comparables (typiquement AGPL-3.0) sont écartées : redondantes, copyleft fort pour un besoin que
la primitive punch+durée d'OPSYS couvre déjà mieux, en fail-closed et append-only.

## 4. Plan par phases

### Phase 0 — déjà livrée (rappel, non refaite)
Le socle EPIC G v1 : encodage, registre, contrats/frontières, machine à états, cédule round-robin,
pointage, écarts, WCT, digest, 13 outils d'agent, 2 skills. 451 tests verts. Base saine pour bâtir
la Phase 1 sans réécriture.

### Phase 1 — tranche verticale « soumission acceptée → job planifié → punch → Travaux terminés → cascade »
Tâches petites, chacune testable indépendamment et n'agrandissant jamais le périmètre financier
de M4 (`frontieres.py` reste intact) :

1. **Contrat d'entrée « soumission acceptée »** — étendre le contrat gelé consommé par M4 pour
   porter un `devis_id`/`soumission_id` réel quand M3 le fournit (aujourd'hui toujours `null`).
   Test : contrat avec `devis_id` non nul accepté ; absence tolérée (rétrocompatibilité avec les
   451 tests existants).
2. **Cédule optimisée** — nouvel outil `m4_optimiser_cedule` (T0) appelant OR-Tools sur une matrice
   de distances (Haversine d'abord, OSRM ensuite), en conservant le contrat de sortie
   `{assignations, non_cedulees}`. Test : deux jobs proches assignés au même technicien avant un
   job éloigné ; fixture round-robin actuelle conservée comme repli documenté.
3. **Formulaire de matériaux M6 à la complétion** — nouveau maillon `materiel_declare` (items
   prévus vs réels, retour/perte/bris, achat terrain avec reçu obligatoire, **aucun coût affiché**,
   conforme 9.3) émis entre le pointage de départ et `m4_completer_intervention`. Test : complétion
   refusée fail-closed si la liste prévue est non vide et qu'aucun formulaire n'a été soumis.
4. **Cascade réelle vers M6** — remplacer `ConsommateurReference` par un appel MCP réel
   (`m6_recevoir_wct`, côté M6, hors fichier mais à cadrer ici) consommant le WCT + le formulaire
   de la tâche 3. Test d'intégration : rejouabilité du curseur sans double effet (idempotence déjà
   prouvée côté M4, à re-prouver côté consommateur réel).
5. **Pont temps → M5** — outil `m4_produire_brouillon_temps` (T1) agrégeant les pointages d'une
   période en lignes `{technicien_id, intervention_id, minutes, date}`, aucun calcul de paie. Test :
   somme des minutes égale au calcul manuel sur une fixture connue.
6. **Distinction post-complétion** — champ ou état `verifie: bool` sur le maillon `terminee` pour
   séparer un écart matériel fort (détecté par la tâche 3) de la complétion propre, avant
   facturation M5 (analogue à `completed_pending_review`/`completed_verified` du produit). Test :
   un écart matériel critique déclaré à la tâche 3 bascule l'intervention hors de « vérifiée ».
7. **E2E de bout en bout** — un test d'intégration enchaînant 1→6 sur une fixture `fictif: true`
   unique (scénario type « gouttières, Repentigny »), le plus proche possible du parcours §6/9.7
   réel. Condition de sortie de la Phase 1 : ce test est vert.

### Phase 2 — dispatch, météo, GPS continu, écrans mobiles dédiés
Tableau de dispatch (nouvelle surface API + lecture live des outils existants) ; `m4_verifier_meteo
_creneau` (Open-Meteo) avant confirmation d'un créneau ; écrans mobiles natifs Phase 2 de
`MOBILE.md` (checklist, formulaire matériaux, ETA client tokenisé) ; consentement GPS
(`employee_consent_location`) câblé dans `pointage.py` conformément à la politique.

### Phase 3 — équipes/véhicules/équipements, analytique, mémoire
Entités Équipe/Véhicule/Équipement et admissibilité (M4.2–M4.3) ; score d'adéquation opérationnel
(M4.11, nécessite de réviser `garde_conformite_r020` — voir risque 2) ; export du digest vers M8 ;
écriture M10.

## 5. Risques et points ouverts

1. **GPS et Loi 25.** `POLITIQUE-geolocalisation.md` exige un consentement documenté
   (`employee_consent_location`), une rétention de 12 mois et des droits d'accès/rectification ;
   rien de tout cela n'est câblé dans `pointage.py` (mode ombre, fixtures `fictif: true`
   uniquement). À construire avant tout GPS réel — pas après.
2. **Jamais d'étiquette psychologique ni de sanction automatique.** Bien gardé aujourd'hui
   (`garde_conformite_r020`, analyse AST, whitelist de clés fermée par test) — mais la garde
   interdit dans sa forme actuelle **même** un futur score d'adéquation opérationnel légitime
   (M4.11). Elle devra distinguer score punitif et mesure opérationnelle sans s'affaiblir.
3. **Hors ligne : absence totale.** P14 en fait un invariant non négociable et le PRD BMAD de M4
   le renvoie lui-même en GATED (polling GPS réel, attestation d'appareil). L'écart entre
   l'ambition produit et le plan du département doit être tranché explicitement, pas seulement
   repoussé indéfiniment.
4. **Cascade sans destinataire.** Le WCT est prêt et prouvé, mais aucun des modules avals n'existe
   assez pour le consommer réellement ; aucun transport (bus, webhook, sondage) n'est choisi.
5. **Divergence documentaire sur les consommateurs.** `CONSOMMATEURS_CIBLES` (M6,M5,M2,M7,M8,M10)
   omet M3 et M9, que §6 du produit fait aussi réagir à « travaux terminés » — à trancher, le
   fichier produit faisant foi.
6. **Dépendance manifeste non exercée.** `department.yaml` déclare `dependances: [m03-estimation]`
   alors qu'aucun code M4 n'importe ni ne consomme M3 (`devis_id` toujours `null`) — à corriger ou
   à justifier avant qu'`opsys-metier verifier` ne la prenne pour argent comptant.
7. **Terminologie.** Le code parle d'« intervention »/« technicien » là où le produit et les autres
   départements parlent de « job »/« employé »/« équipe » — un mapping explicite est nécessaire
   avant intégration inter-départements (risque de confusion M4/M6 déjà noté en §13 du produit).
8. **Persistance.** Le registre est une liste Python en mémoire ; rien ne survit à un redémarrage.
   Bloquant au-delà de la CI/démonstration, malgré PostgreSQL déjà visé par l'architecture.
9. **Cédule non géographique.** Le tri s'effectue sur un hash (token) de ville sans aucune
   proximité géographique réelle ; brancher OR-Tools ne suffira pas sans coordonnées/distances
   réelles (OSRM) en entrée.
10. **Champ mort.** `urgence_declaree` est collecté au contrat mais jamais lu par `cedule.py` —
    à activer ou à documenter explicitement comme différé.
