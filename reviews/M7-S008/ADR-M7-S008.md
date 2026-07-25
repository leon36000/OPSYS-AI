ADR M7-S008 — Workflow campagne saisonnière (planification déterministe)

Statut : Proposé
Dépend de : M7-S008a (calendrier-quebec.v1.yaml), M7-S006 (Content Factory + approval)
Décideurs : équipe architecture ForgeAI

1. Périmètre et autorité

Le workflow vit dans src/workflows/campagne_saisonniere.py et orchestre la planification déterministe d'une campagne marketing à partir d'une date de référence ISO-8601 fournie par l'appelant.
Aucune horloge interne n'est consultée : la reproductibilité exige que deux appels avec la même date produisent exactement le même plan, byte pour byte.
Le calendrier S008a est la seule source de thèmes ; aucun thème, mot-clé ou slogan n'est inventé par le workflow.
Le workflow ne publie jamais : il propose uniquement via approval.propose, laissant la gate humaine (S006 file 0-6) inchangée.
Zéro appel réseau, zéro LLM, zéro I/O disque hors lecture du YAML calendrier et écriture du fichier d'approbation.

2. Sélection de fenêtre saisonnière

Une fenêtre est active si la date de référence tombe dans l'intervalle [mois_debut, mois_fin] exprimé en mois calendaires.
Si mois_debut <= mois_fin, l'appartenance est triviale : mois_debut <= mois_ref <= mois_fin.
Si mois_debut > mois_fin (chevauchement d'année, ex. hiver 12→2), l'appartenance est mois_ref >= mois_debut OR mois_ref <= mois_fin.
Le jour du mois n'intervient pas : la granularité du calendrier S008a est mensuelle, toute précision supérieure serait une invention.
Plusieurs fenêtres peuvent être actives simultanément (ex. fw-transition-hiver-printemps en mars chevauche printemps) ; le workflow les retourne toutes, sans arbitrage.
Les fenêtres sont triées par id lexicographique pour garantir un ordre stable et reproductible.
Une date hors toute fenêtre retourne un plan valide avec fenetres_actives=[] et items_proposes=0, jamais une exception.

3. Structure du plan retourné

Le plan est un dict à quatre clés : date_reference (str ISO), fenetres_actives (list[dict]), items_proposes (list[dict]), compteurs (dict).
Chaque fenetre_active porte id, nom, mois_debut, mois_fin, themes (copie exacte du champ themes_marketing du calendrier).
Chaque item_propose porte content_item (dict complet retourné par build_content_item), fenetre_id, theme_source, statut="proposed".
Le sujet passé à build_content_item est construit factuellement : titre = "{nom_fenêtre} — {thème}", description = "Campagne saisonnière pour le thème « {thème} » de la fenêtre « {nom_fenêtre} ».", mots_cles = [nom_fenêtre, thème] normalisés en minuscules sans ponctuation.
L'acteur proposeur est la chaîne constante "workflow-campagne-saisonniere" pour tracer l'origine automatisée.
Le timestamp passé à build_content_item et à approval.propose est la date_reference elle-même, pas l'instant d'exécution, pour préserver le déterminisme.
Les items_proposes sont triés par (fenetre_id, theme_source) pour un ordre stable indépendant de l'ordre d'itération du YAML.
Les compteurs sont {fenetres_actives: int, items_proposes: int, themes_couverts: int} et dérivés strictement des listes, jamais saisis manuellement.

4. Interfaces publiques

Une seule fonction publique : planifier_campagne_saisonniere(date_reference: str, chemin_calendrier: str) -> dict.
Une fonction privée _charger_calendrier(chemin: str) -> dict lit et valide le YAML S008a (schema_version == 1, présence de fenetres_marketing).
Une fonction privée _fenetres_actives(calendrier: dict, mois_ref: int) -> list[dict] applique la règle de sélection de la section 2.
Une fonction privée _construire_sujet(fenetre: dict, theme: str) -> dict retourne le triplet {titre, description, mots_cles}.
Une fonction privée _proposer_item(brand: dict, fenetre: dict, theme: str, timestamp: str) -> dict encapsule l'appel à build_content_item puis approval.propose.
Aucune autre fonction publique n'est exposée : le module est un point d'entrée unique, testable sans mock.

5. Anti-dérive

Aucun marqueur fictif n'est requis sur le calendrier S008a : il s'agit de donnée marketing réelle du produit (saisons québécoises, thèmes sectoriels), pas d'un chantier d'essai comme en S007.
Le marqueur fictif de S007 protégeait contre la fuite de données clients réelles en mode ombre ; ici, aucune donnée client n'entre dans le pipeline.
Aucun thème n'est synthétisé : si le calendrier est vide, le plan est vide, et c'est un comportement correct.
Aucun appel à approval.approve ni approval.publish : le workflow s'arrête à propose, la gate humaine reste souveraine.
Aucun import de requests, httpx, urllib, socket, datetime.now, time.time : une vérification statique (test d'interdiction d'imports) verrouille cette contrainte.
Le brand est chargé via le même helper _charger_brand() que chantier_social.py (S007), pour cohérence de source.

6. Tests RED/GREEN (TDD)

Test RED-1 : une date au 15 juillet retourne exactement la fenêtre fw-haute-saison-estivale et un item par thème de cette fenêtre, compteurs cohérents.
Test RED-2 : une date au 15 janvier retourne uniquement fw-creux-hivernal, aucun thème estival ne fuit.
Test RED-3 : une date au 15 mars active simultanément fw-transition-hiver-printemps et la saison printemps, les deux listes de thèmes sont concaténées.
Test RED-4 : une date au 15 janvier avec mois_debut=12, mois_fin=2 (chevauchement d'année) active correctement la fenêtre hiver, validant la règle OR.
Test RED-5 : deux appels successifs avec la même date_reference retournent des plans strictement égaux (assert plan1 == plan2), validant le déterminisme.
Test RED-6 : aucun item retourné n'a statut autre que "proposed" ; aucun appel à approval.approve ni approval.publish n'est observé (mock espion).
Test RED-7 : l'import du module ne déclenche aucun appel réseau (patch socket.socket qui lève, le simple import ne doit pas lever).
Test RED-8 : une date hors toute fenêtre (ex. 15 avril si aucune fenêtre ne couvre avril) retourne un plan valide avec fenetres_actives=[] et items_proposes=0, sans exception.
Test RED-9 : le timestamp passé à build_content_item est égal à date_reference, pas à l'instant courant (freeze_time ne modifie pas le résultat).
Test RED-10 : le sha256 du calendrier S008a est épinglé dans un test consommateur (pattern D-015), toute modification du YAML casse le test et force une révision d'ADR.

---
> **ANNEXE D'ADAPTATION (R1, journalisée)** : (a) le calendrier RÉEL sépare `saisons` (données
> descriptives, printemps 3→5) et `fenetres_marketing` (fenêtres de CAMPAGNE avec `themes` —
> fw-creux-hivernal 12→1) : la planification consomme les fenetres_marketing SEULES ; le RED-3 de
> l'ADR (« mars active transition ET printemps ») reposait sur une lecture fusionnée erronée — en
> mars, seule fw-transition-hiver-printemps (2→3) est une fenêtre de campagne, le test encode la
> réalité. (b) RED-7 (patch socket à l'import) remplacé par l'assertion getsource déterministe —
> pattern établi S010/S011 (un patch d'import est fragile et n'apporte rien de plus). (c) La
> validation schema_version==1 (§4) est appliquée (correctif R1, fail-closed).
