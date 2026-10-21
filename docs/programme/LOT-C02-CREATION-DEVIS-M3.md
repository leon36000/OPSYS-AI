# Design C02 — `m3_creer_devis` sous contexte M10 actif

## Qualification R22 postérieure à ce design

La résolution stricte est maintenant implémentée : lead M10 exact, existence et intégrité M2, devis neuf ou appartenant au même lead, chantier nul ou égal au lead selon M4 v1. Les chaînes M2 et M10 sont vérifiées avant usage. Core désigne cet outil précis sous `opsys_m3` avec ticket; les arguments finaux sont conservés dans l’empreinte. Les statuts N3 et validations différées restent ceux du runtime existant.

ROOT a exécuté les 37 cas de liaison Python et le parcours HTTP MCP avec serveur local/client officiel dans les 467 cas intégrés, puis 405 tests Core séparés. Le parcours crée un brouillon après validation locale, bloque des arguments altérés et une liaison M10 révoquée, et ne crée ni facture ni événement d’acceptation. Voir [R22](../research/R22-2026-10-02/README.md). Aucun appel LLM Gateway réel n’a été exercé; C02 global reste partiel. Le texte ci-dessous décrit le design préalable, pas l’état après livraison.

Lecture seule de l’arbre `/workspace/OPSYS-AI-recent` le 2 octobre 2026 UTC. Aucun test/build/réseau/install/modification source n’a été fait.

## Le manque existe, et son exclusion avait une raison réelle

À la version courante, `src/opsys/liaison_cibles.py:27-36` admet six mutations M2 à cible `lead_id` et deux mutations M3 à cible `devis_id`; `cible_de_l_outil()` refuse les autres outils (`:56-72`). `m3_creer_devis` est `Autonomie.T1`, donc N3 selon `src/opsys/outils.py:35-67`, et prend `devis_id`, `lead_id`, `chantier_id` (requis mais nullable), lignes et marge (`departments/m03-estimation/src/m3_estimation/outils.py:1069-1105`). Le générateur classe tout outil N3+ absent de `OUTILS_CIBLES` comme `inconnue` (`src/opsys/openclaw.py:574-594`); le garde Core bloque une cible inconnue pour le contexte d’un agent (`core/src/context-engine/opsys-contexte-garde.ts:209-220`). Les tests confirment la liste fermée (`core/src/context-engine/opsys-contexte-config.test.ts:312-354`; garde `:200-233`).

Ce n’est pas une simple omission de nom : le design original C02 dit explicitement de laisser `m3_creer_devis` bloqué, car `lead_id` et `chantier_id` doivent concorder et la création peut porter plusieurs identifiants (`docs/research/R17-2026-09-30/C02-DESIGN-LIAISON-CIBLES.md:15`; `C02-PLAN-LIAISON-CIBLES.md`, étape 4). La preuve antérieure pour les devis existants sait lire le record, vérifier `lead_id`, existence M2 et refuser les IDs de chantier/WCT non reliés (`liaison_cibles.py:118-146`; `tests/test_liaison_cibles.py:199-263`), mais ne résout pas la relation à la création car le devis n’existe pas encore. Les seuls champs inconnus ne doivent pas être supprimés de la vérification par une extension générale de la liste blanche.

Autre limite réelle, distincte de C02 : le brouillon stocke des coûts/lignes et calcule un prix déterministe, mais `taux_marge` et les coûts sont dans les arguments de l’agent; la docstring dit que la marge doit être fournie explicitement et qu’aucun défaut n’est inventé (`departments/m03-estimation/src/m3_estimation/devis_durable.py:22-25`). Un ticket valide prouverait l’appartenance au dossier, pas la provenance métier des montants. Le correctif C02 doit conserver la validation actuelle des arguments/prix et ne pas déclarer ces entrées qualifiées ou fiables.

## Invariant proposé — limité au lead, une cible de création distincte

Autoriser ce seul outil dans le contrat de ticket M3 avec une résolution `creation_devis_sur_lead`, sans le faire passer pour un devis existant :

1. Le contexte vérifié doit être un M10 `GENRE_LEAD`, et `affaire_id` doit exactement égaler `arguments.lead_id`. Le lead doit exister dans le registre canonique M2. Ne jamais autoriser une M10 opportunité (`<lead>~opp~<wct>`) par le préfixe du lead; le résolveur M3 actuel exige déjà une preuve WCT/opportunité que le code n’a pas (`liaison_cibles.py:137-146`).
2. `devis_id` est l’identité de la ressource *à créer*, pas l’identité qui prouve l’affaire. Il reste dans l’empreinte complète des arguments. S’il existe déjà, lire le devis M3 et exiger son `lead_id` égal au lead M10 courant; l’API métier existante décide ensuite si le contenu est le rejeu idempotent exact ou une collision de contenu. Un ID existant lié à un autre dossier est refusé avant le dispatcher.
3. `chantier_id` ne peut pas être accepté comme une autre cible libre. Pour cette tranche, permettre `null` ou exactement le lead courant, seule sémantique M4 v1 observée dans `m4_confirmer_localisation` (`departments/m04-field-ops/src/m4_field_ops/outils.py:1966`) et le ticket M3 existant (`tests/test_liaison_cibles.py:220-229`). Tout autre ID reste refusé faute de relation chantier canonique démontrée. Si M4 stabilise plus tard des `chantier_id` différents, ajouter un résolveur M4 explicite avant d’élargir.
4. Tous les autres champs que `_CHAMPS_CIBLES` pourrait identifier sont absents des arguments (et `additionalProperties: false` reste appliqué par le contrat M3). Pour ce contrat spécial, la forme admet exactement `lead_id`, `devis_id`, et `chantier_id` nul/égal au lead; elle refuse tout champ redondant de cible (ex. `client_id`, `wct_id`) plutôt que d’ignorer une cible secondaire.
5. Lier le ticket à `departement=m03-estimation`, l’agent/session, l’affaire M10 exacte, `ligne_liaison_id` active, le nom exact d’outil, et l’empreinte canonique de *tous* les arguments finaux, avec expiration courante de 120 s. Le secret de ticket reste opaque sous `_meta`; jamais dans arguments, prompt, journal ou résultat. La génération de config doit désigner ce nom précis comme `ticket`, pas comme `globale` ni `affaire` directe.

Il ne faut pas retirer le contrôle des champs multiples pour les autres outils, ni transformer l’ensemble en whitelist de `lead_id` arbitrairement présente.

## Émission et exécution atomiques

Réutiliser l’émetteur existant (route MCP privée M3 → `outil_emission()` → `emettre_ticket`) et le transport `_meta` existant. À l’émission, dans la connexion SQLite courante : vérifier agent/session, liaison M10 active et ligne courante, genre `lead`, résolution M2, forme du contrat M3, règle stricte `chantier_id`, et toute collision de `devis_id`. Persister seulement hash du ticket, affaire/ligne M10, agent/session, outil, empreinte arguments, expiration, état. Le devis neuf n’est pas écrit par l’émission.

À l’exécution, `Capacites._appeler_avec_ticket()` vérifie ticket, expiration, outil/département/hash d’arguments, agent/session, lien M10 et cible vivante dans une transaction SQLite, distribue le tool, puis consomme ou scelle le ticket dans la même transaction (`src/opsys/capacites.py:315-342`; `liaison_cibles.py:204-251,285-305`). Refaire les lectures M10/M2/M3 immédiatement avant le dispatcher; ne s’appuyer ni sur l’état Core en cache ni sur les arguments de domaine seuls. Un changement de lien ou de lead entre émission et exécution refuse sans maillon devis. Un rollback annule la mutation métier et consommation du ticket ensemble.

Le cas de rejeu existe déjà au niveau métier : `devis_durable.creer_devis()` retourne l’existant sans nouveau maillon si le même `devis_id` porte le même contenu; contenu divergent renvoie `REJ-DEVIS-ID-DEJA-UTILISE` (`departments/m03-estimation/src/m3_estimation/devis_durable.py:55-59,296-371`; test `departments/m03-estimation/tests/test_devis_durable_stockage.py:131-139`). Le ticket ajoute une autorisation ponctuelle, pas un remplacement de cette idempotence. Le registre C02 ne supporte actuellement que SQLite et refuse autre dialecte (`liaison_cibles.py:86-88`); garder ce refus jusqu’à une qualification PG spécifique.

## Portée N3 et effets à ne pas confondre

Le draft reste T1→N3, comme il l’est déjà. Le ticket ne change aucun niveau, rôle, mode d’approbation, signature humaine ni validation M3. Le dispatcher existant soumet toujours un N3 à la politique de mode; la validation au départ d’un N3 par un humain authentifié reste liée à la portée de son rôle (`src/opsys/capacites.py:454-481,497-550`). Si le mode retient la demande, le ticket est scellé puis revérifié à l’approbation, modèle déjà utilisé par les mutations M3 N4/N5 (`liaison_cibles.py:234-239,254-294`; `src/opsys/approbations.py:259`). L’intégration doit prouver ce chemin pour la création M3 plutôt que contourner le contrôle différé.

`m3_creer_devis` n’accepte pas, ne publie pas `m3.devis_accepte` et n’envoie rien; ses tests vérifient qu’une création/lecture seule n’émet aucun événement (`departments/m03-estimation/tests/test_devis_durable_stockage.py:141-146`). `m3_demander_envoi_devis` reste N4; le manifeste garde l’envoi au propriétaire (`department.yaml:46-51`). Ne pas mélanger le prix du brouillon à une approbation de prix/envoi, ni permettre l’acceptation N5 ou la facturation par cette tranche.

## Fichiers exacts

- `src/opsys/liaison_cibles.py` : nouveau contrat spécial M3 « créer sur lead », projection des identifiants, revalidation du lead, chantier v1 et collision d’ID. Garder les deux groupes et refus actuels intacts.
- `core/src/context-engine/opsys-contexte-cibles.ts` : ajouter `m3_creer_devis: "opsys_m3"` à l’union exacte de tickets. Aucun changement d’agent/session/context engine sinon.
- `core/src/context-engine/opsys-contexte-config.test.ts` et `opsys-contexte-garde.test.ts` : couvrir autorisation de ce nom seulement, inconnue bloquée et ticket d’outil hors whitelist refusé.
- `tests/test_liaison_cibles.py` : tests forme, émission, revalidation avant mutation, `Capacites`, consommation/rejeu, révocation/course et approbation différée avec les fixtures existantes.
- `tests/test_openclaw_contexte.py` : génération qui marque M3 create en `ticket`, vérifie département M3, et conserve `inconnue` pour d’autres outils non couverts. `src/opsys/openclaw.py` lit déjà `OUTILS_CIBLES`; modification source a priori inutile.
- `departments/m03-estimation/src/m3_estimation/outils.py` et `devis_durable.py` devraient rester intacts : ils possèdent déjà le contrat du draft, calcul déterministe et idempotence. On ne leur ajoute un changement que si un test démontre un trou de validation métier indépendant de la cible.

## Tests utiles (8)

1. **Forme fermée :** `cible_de_l_outil("m3_creer_devis", args)` accepte `devis_id`, `lead_id`, `chantier_id=None`; accepte `chantier_id==lead_id`; refuse autre chantier, lead manquant, autre champ cible ou outil voisin non whitelisté.
2. **Émission positive :** préparation d’un lead M2 canonique + liaison M10 de session active; émettre ticket de création M3 produit un seul ticket opaque lié au bon département/session/ligne/empreinte, sans écrire au registre devis.
3. **Propriété affaire :** mismatch `lead_id` vs affaire, lead absent M2, session sans lien M10, ligne de liaison remplacée ou genre opportunité M10 tous refusent et ne créent ticket ni devis.
4. **Chantier non prouvé :** `None` puis lead-ID passent; identifiant chantier arbitraire/différent échoue à l’émission et à la revalidation, avec zéro maillon M3. C’est le cas précis qui doit empêcher une extension trop large.
5. **Collision d’ID entre affaires :** devis existant pour autre lead refuse même si appelant présente un autre `lead_id`; vérifier aucun nouveau maillon/event et aucun ticket utilisable.
6. **Course après émission :** créer ticket valide, puis remplacer la liaison M10 ou créer le `devis_id` dans un autre dossier; l’appel ticketé retourne `cible_refusee`, sans mutation/événement et sans consommer une nouvelle autorisation ailleurs.
7. **Rejeu business et ticket :** même ID + mêmes args, deuxième appel avec même ticket rejoue résultat sans exécuter deux fois; nouveau ticket et arguments identiques peuvent réutiliser le draft idempotent sans deuxième maillon; même ID/contenu différent est refusé.
8. **N3 et approbation différée :** via Core config/garde puis `Capacites`, ticket permet uniquement la cible M3 configurée; mode autonome respecte N3 existant et produit au plus un brouillon; mode exigeant validation scelle le ticket, puis une liaison remplacée ou ID réattribué avant clic propriétaire empêche la création. Aucun envoi, acceptation, event de devis accepté ou privilège humain ne doit être obtenu par le ticket.

Les points de départ testés existent déjà : fixtures M2/M10/tickets dans `tests/test_liaison_cibles.py:108-160`; résolveur M3 et vérification chantier `:199-263`; changement post-émission et approbation différée `:374-434`; contrat M3/information de rôle dans `departments/m03-estimation/tests/test_outils_agent.py:150-200`; stockage et idempotence `departments/m03-estimation/tests/test_devis_durable_stockage.py:52-66,131-178`; whitelist Core `core/src/context-engine/opsys-contexte-cibles.ts` et tests de config/garde cités plus haut.

## Décision recommandée

Oui, ajouter un ticket C02 pour le draft est techniquement défendable sous la condition étroite « lead M10 exact, lead M2 existant, chantier nul ou M4-v1 égal au lead, `devis_id` libre ou déjà sur ce même lead ». L’exclusion avait une raison valide et ne doit pas être levée par ajout nominal à une liste. Tout chantier non prouvé et toutes opportunités restent refusés. Ce ticket garantit seulement la frontière affaire et le rejeu d’autorisation; il ne qualifie pas les coûts/taux transmis par l’agent. La politique N3, la provenance des montants et l’envoi N4 restent distincts et doivent conserver leurs protections présentes.
