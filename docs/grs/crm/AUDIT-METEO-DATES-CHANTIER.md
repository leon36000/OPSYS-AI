# CRM-08 — météo des dates internes : audit et patch minimal

27 octobre 2026; parent d3cc6ba2fa2d609d32cae5696c57bc1d2769ed0a. PARTIAL.
Lecture indépendante wave1_m4_calendar, rapprochée des symboles propriétaires par ROOT.

## Existant et réutilisation

`m4_field_ops.outils.verifier_meteo_creneau` est un vrai outil admin T0. Le moteur
`meteo_creneaux.verifier` lit les visites du plan exact, les positions confirmées généralisées,
les seuils du profil et les prévisions; il ne modifie ni registre ni cédule. Sans fournisseur
ou couverture, le résultat reste inconnu. Les reports et relances retournés sont des propositions.
Le présent raccord réutilise ce moteur, ses fournisseurs et leurs licences déjà étudiées dans
INGREDIENTS; aucune nouvelle dépendance, aucun second moteur météo.

L’éditeur `cedule_plan_ui` montre déjà le calendrier civil courant et sa révision depuis
`m4_lire_calendrier_plan`. Le contrôle météo n’y est pas proposé. La datation civile reste une
opération interne distincte; elle ne prouve ni prévision, ni trajets entre plans, ni dispatch.

## Contrat de cette tranche

Ajouter un contrôle explicite POST des seules dates déjà enregistrées et non bloquées.
Le GET prépare seulement une empreinte (plan, révision, calendrier, tête M4, profil météo),
sans fournisseur ni réseau. Le POST fermé CSRF/empreinte relit l’admin SQL, le plan, ses dates,
la source bornée et le profil; il appelle le vrai T0, puis relit les mêmes sources pour refuser
un changement pendant la consultation. Aucun nouvel argument fournisseur/acteur/date libre.
Le fuseau du profil doit être compatible avec America/Montreal aux heures des visites datées.

La réponse complète doit contenir exactement les visites attendues, dates et horaires concordants;
une réduction/troncature ou un ancien plan ne devient pas un contrôle complet. Afficher verdicts,
règles, sources, type d’heure, heure citée, attributions et limites. Sortie JSON 64 Kio, HTML
128 Kio; pas de coordonnées précises, contacts, coûts ou données brutes de prévision.

## Limites de confiance à conserver

Le propriétaire n’impose aucun TTL, âge maximal ou refus d’émission future. Une ancienne saisie
couvrant les heures peut rendre ok. GeoMet cite sa mise à jour; Open-Meteo cite l’heure HTTP,
pas l’émission du modèle. L’écran doit dire « fraîcheur non qualifiée », même si les seuils sont
respectés. Ce contrôle ne devient ni preuve durable de dispatch ni confirmation client.
Aucun nouveau fournisseur n’est ouvert; un POST peut appeler seulement celui déjà configuré.

M10 possède `m10_lire_paquet_affaire_appareil` pour console et `m10_paquet_contexte_affaire`
pour serveur M4. `m10_contexte_preflight` est T1, peut écrire un refus et ne constitue pas un
garde bloquant. Cette tranche météo est une consultation sans changement critique de cédule;
le raccord du vrai paquet M10 avant changement critique reste une exigence suivante distincte.
Ne pas recopier la mémoire ni fabriquer un preflight.

## Qualification et suite

Tests de bout en bout HTTP/SQLite et vrai moteur : dates exactes, fournisseur fermé inconnu,
prévision manuelle fictive aux seuils, citation ancienne présentée sans qualification de fraîcheur;
CSRF, révocation, source/profil changé, fuseau incompatible, réponse réduite/excessive refusés,
aucune modification de base ni confirmation civile automatique. Réutiliser les cohortes de dates
et d’affectation existantes. QA privée bornée, Source lecture seule, réseau interdit.

Gates Nathan : aucun nouvel engagement ni paiement/fournisseur externe activé. Mobile et
navigateur ultérieurs. Après preuve de ce raccord, traiter fraîcheur propriétaire et préflight
M10 avant dispatch, puis capacité/trajets globaux. Ni CRM-08 ni M4 ni OPSYS complet.

## Revue ciblée avant qualification finale

Deux P2 statiques à reproduire : une chaîne reconstituée peut conserver un plan aux empreintes
métier fausses; le contrôle avant/après ne prouve pas le profil réellement consommé en cas
A→B→A. Réutiliser la résolution d’ancre `annotations_calendrier._creneau` pour la proposition,
l’application et la datation (plans multiples conservés). Faire citer par le vrai outil T0
l’empreinte du profil effectivement chargé et comparer à celle préparée. Cet ajout propriétaire
est une preuve de provenance, pas une nouvelle politique de fraîcheur ou de dispatch.

## Jalon exécuté — contrôle explicite HTTP/SQLite

Le port `console/meteo_dates_chantier.py` prépare une empreinte sans consulter les prévisions.
L’éditeur civil affiche un formulaire distinct seulement pour un plan daté complet non bloqué.
POST `/crm/cedule/plan/{plan_id}/meteo` ferme CSRF/empreinte, relit l’admin SQL et utilise
uniquement les dates enregistrées. Aucun champ date, auteur, fournisseur ou prévision libre
n’est accepté. Le fournisseur reste celui déjà configuré, fermé par défaut.

Les ancres réelles proposition/application/date sont résolues par le propriétaire
`annotations_calendrier._creneau`; une chaîne valide aux empreintes métier incohérentes est
refusée. Le fuseau est comparé à America/Montreal à chaque minute des visites explicites.
Le vrai outil T0 cite désormais `profil_meteo_source` avec l’empreinte du profil effectivement
consommé et son fuseau; le port compare cette preuve au profil préparé. Il refuse aussi les
changements après appel, les visites/date/heures discordantes, les réponses réduites et les
volumes excessifs. L’écran cite les règles, sources/heures et attributions, avec l’avertissement
« Fraîcheur non qualifiée ». Aucun calendrier, statut, approbation ou notification n’est écrit.

Preuves privées : `weather-dates-red-v1` constate l’absence initiale du formulaire.
`weather-dates-v1` 56 PASS; `weather-integrity-red-v1` s’arrête au lint avant tout test;
`weather-integrity-red-v2` reproduit les deux vrais P2 (200 erroné pour profil A→B→A et plan
rechaîné altéré). Après correction, `weather-dates-v2` **76 PASS, 0 FAIL/SKIP, 25,51 s**, dont
21 cas du nouveau parcours, les dates existantes, l’application HTTP et le vrai moteur météo.
Une révocation entre la première lecture civile et la préparation GET produisait ensuite une
PermissionError non convertie : `weather-role-red-v1` le reproduit. Le contrôleur la traduit
maintenant en HTTP 403. `weather-dates-v3` **33 PASS, 0 FAIL/SKIP, 13,67 s** : les 22 cas météo
finaux et les 11 cas dates existants. Ces cohortes se recoupent et ne sont pas additionnées.
Le moteur et le port sont inchangés entre v2 et v3; seule la garde HTTP tardive est ajoutée.
Ruff ciblé et vérificateur 297 outils/173 portées passent. Revue indépendante finale des deux
P2 : aucun constat restant, lecture statique seulement.

Sont démontrés les seuils réels 24/25/40 km/h (ok/validation/bloquant), une prévision manuelle
fictive de 2020 couvrant la visite de 2030 (ok sans fraîcheur prétendue), l’échappement de sa
citation, le fournisseur absent, le profil changé pendant lecture, les dates/états changés,
les fuseaux compatible/incompatible, les rôles retirés, CSRF/champs/doublons/types/volumes,
les réponses altérées ou incomplètes et l’absence d’écriture de la consultation. Les seules
mutations dans les tests de perturbation sont celles explicitement injectées par leur fixture.
Source lecture seule pendant QA, réseau interdit, homes/tmp privés, 1 CPU/1 Gio/96 tâches;
commandes, scripts, empreintes, logs, JUnit et reçus distincts, rouges conservés.

**PARTIAL** : consultation datée qualifiée; aucune politique propriétaire de fraîcheur,
preuve durable de dispatch, capacité globale, trajet entre plans ou confirmation client ajoutée.
M10 avant changement critique, sources météo réelles autorisées, navigateur, PostgreSQL,
mobile et qualification finale M4 restent à traiter. Aucune commande fournisseur, dépense,
publication client, fusion ou déploiement.
