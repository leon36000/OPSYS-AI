# Portée des rôles d'appareil (T1.4-j)

> Complète [MOBILE.md](MOBILE.md) (appairage, jeton d'appareil), [IDEMPOTENCE.md](IDEMPOTENCE.md)
> §7 bis (le core refuse un outil hors portée) et [ADR-0009](../decisions/ADR-0009-socle-metier.md)
> §4-§5. Les profils viennent de la [définition produit](../produit/DEFINITION-PRODUIT.md) §9.
> La table ci-dessous est épinglée par `tests/test_portees_appareil.py` ; le contrôle d'accès par personne
> et par intervention (T1.4-k) par `tests/test_acces_par_intervention.py` et les tests de M4 et de M6 ; la
> vue financière de M5 (T1.4-k2) par `tests/test_acces_tresorerie.py` et les tests de M5.

## La règle

**Fermé par défaut, pour tous les rôles.** Un jeton d'appareil (`employee`, `seller`, `admin`) ne peut
appeler que les outils qui le citent dans `Outil.roles_appareil` :

```python
Outil(
    nom="m4_pointer", ..., autonomie=Autonomie.T1,
    # §9.3 (punch).
    roles_appareil=frozenset({"employee", "admin"}),
)
```

- **Où.** L'attribut est sur l'`Outil`, à côté de l'autonomie et des paramètres, pas dans
  `department.yaml`. La relecture d'un outil montre qui peut l'appeler ; un renommage ne laisse
  aucune entrée orpheline (un manifeste garderait le vieux nom, qu'un autre outil pourrait un jour
  reprendre) ; un nouvel outil ne peut pas exister sans que le défaut (aucun appareil) soit visible
  dans le même diff.
- **Défaut.** Vide : aucun appareil. Un outil ajouté demain n'est appelable depuis aucun téléphone
  tant que quelqu'un n'a pas écrit, en relecture, qui le peut. Les outils communs `opsys_*`
  (`capacites.py`, mémoire) n'ont pas de déclaration et restent fermés aux appareils.
- **Source unique.** `opsys.openclaw.roles_outils` projette les déclarations en `opsys/roles.json`
  (`opsys openclaw configurer`), que `core/src/gateway/opsys-device-roles.ts` lit. Le core n'a rien
  à changer. Depuis T1.4-c6, le même fichier porte `serveurs` (`openclaw.serveurs_outils`) : le
  serveur MCP de chaque outil permis, sous le même nom nu. Le core compare la portée au nom nu, puis
  appelle CE serveur sous CE nom ([MOBILE.md](MOBILE.md), « Nom d'un outil de l'app au moteur »).
- **T3/N5 jamais.** Un outil T3 ou de niveau N5 (`Outil.frontiere_humaine`) n'est projeté dans aucun
  rôle, quoi que déclare l'outil. Ces gestes restent à `nathan_owner` et à l'attestation du
  professionnel (ADR-0009 §5).
- **Contrôle.** `opsys verifier` échoue si une déclaration cite un rôle qui n'est pas un rôle
  d'appareil (inconnu, `client`, `nathan_owner`...) ou si un outil T3/N5 en déclare une.
  `openclaw.generer` refuse de même, avant d'écrire quoi que ce soit.

### Pas de rôle `client`, pas de rôle `nathan_owner`

Le client (§9.6) passe par un lien tokenisé et expirant, jamais par un appareil apparié
(`appareils.ROLES_APPAREIL`, R12 §6) : `client` n'a pas d'entrée dans `roles.json`, donc le core le
refuse en `role_unknown`, et une déclaration qui le cite est refusée par `opsys verifier`. L'appareil
du propriétaire est appairé `admin` ; sa portée N5 dépend de la PERSONNE, jamais du rôle du jeton.

### Pourquoi `admin` déclare aussi, outil par outil

`admin` n'a pas reçu « tout hors T3 ». Raisons :

1. **T1.4-h.** Un humain authentifié exécutera lui-même les N3 de sa portée, sans approbation.
   « Tout hors T3 » ferait de l'admin (parfois un gestionnaire, pas Nathan) l'auteur direct de
   n'importe quelle écriture N3 : ingérer un snapshot de métriques ou de faits dans M8 et M9 avec
   les chiffres de son choix, écrire un prix au livre de prix, changer le courriel d'un fournisseur.
2. **Outils faits pour un agent.** Plusieurs prennent des chemins de fichiers du serveur
   (`m7_auditer_seo_site`, `m7_calculer_roi`) ou des données de l'appelant (`m6_consommer_materiaux`
   et son WCT).
3. **Un nouvel outil ne s'ouvre pas tout seul.** Ajouter `admin` à un outil est une ligne ; l'enlever
   après coup à un outil déjà utilisé par une app ne l'est pas.

L'admin reçoit ce que §9.5 lui donne, plus les gestes de l'employé et du vendeur (un propriétaire
qui travaille sur un toit, un gestionnaire qui reprend un dossier).

## La table

Les références sont celles de `DEFINITION-PRODUIT.md`. 54 outils sur 126 sont déclarés.

### `employee` (11 outils) : §9.3, le terrain

Chaque outil qui porte une identité ou une intervention ne s'exécute que pour la personne authentifiée et
pour SES interventions (section « Contrôle d'accès par personne et par intervention » plus bas, T1.4-k).

| Outil | Pourquoi |
|---|---|
| `m4_lister_interventions`, `m4_statut_intervention` | §9.3 « Cédule et route : chantiers du jour ». Filtrés à SES interventions ; celle d'un autre rend `statut: null`, comme une inconnue. |
| `m4_demarrer_route` | §9.3 Exécution : « en route ». Sa propre intervention, sous son propre identifiant. |
| `m4_signaler_report` | Client absent, météo (§9.3 Exécution). Le motif `decision_admin` reste celui de l'admin (non appliqué par le code : voir *Ce qui reste*). |
| `m4_pointer` | §9.3 « Punch (M4.4) : entrée et sortie ». Sa propre intervention, sous son propre identifiant. |
| `m4_creer_demande_ecart` | §9.3 « demande de support ou de changement » ; l'admin l'arbitre. Sa propre intervention. |
| `m4_deposer_fichier`, `m4_etat_fichier` | §9.2 « photos envoyées en arrière-plan », §9.3 photos avant/après, signature du client. Aucune intervention portée (adressés par contenu) : identité confirmée seulement. |
| `m4_completer_intervention` | §9.7 « Terminer ». Sa propre intervention. |
| `m4_definir_consentement_gps` | POLITIQUE-geolocalisation §4 « l'employé peut retirer son consentement via l'app employé », §7 droit de retrait à tout moment. SON consentement seulement (`technicien_id` = sa personne), jamais celui d'un autre. |
| `m6_declarer_materiaux_utilises` | §9.3 Inventaire et §9.7 étape 3 : formulaire des matériaux utilisés, « aucun coût affiché ». Le WCT de sa propre intervention seulement. |

Rien qui lise les données des autres (`m4_lire_outbox`, `m4_lire_position_gps`,
`m4_lister_pending_review`, `m4_produire_brouillon_temps`) ni qui approuve (`m4_resoudre_demande`,
`m4_resoudre_revue_completion`, `m6_approuver_po`, `m6_annuler_po`), ni aucun outil M5, M7, M8, M9,
M10.

### `seller` (9 outils) : §9.4, ses leads et ses soumissions

| Outil | Pourquoi |
|---|---|
| `m2_obtenir_client_360`, `m2_trouver_client_de_lead` | §9.4 « Client 360 ». |
| `m2_suggerer_prochaine_action` | §9.4 « prochaine meilleure action ». |
| `m2_evaluer_readiness` | §9.4 M3 « lead prêt pour l'estimation ». |
| `m2_transitionner_statut` | §9.4 « pipeline personnel » (perdu avec motif, converti). |
| `m2_enregistrer_interaction` | §9.4 « notes ». |
| `m3_lire_devis` | §9.4 M3 « voir risques et marge » ; « ne voit pas les coûts internes au-delà de sa soumission ». |
| `m3_generer_soumission_brouillon` | §9.4 « soumissions ». Sans coût ni marge. |
| `m3_qualifier_photos` | §9.4 « demander des photos au client » : ce qui manque. |

Aucun outil M4, M5, M6, M7, M8, M9, M10 : ni finances (« ne voit pas : finances globales »), ni prix
fournisseurs, ni coûts réels (`m3_lire_ecarts_estime_reel`).

### `admin` (54 outils) : §9.5 + employé + vendeur

Les 11 outils de l'employé, les 9 du vendeur, et :

| Département | Outils réservés à l'admin | Pourquoi |
|---|---|---|
| M1 | `m1_produire_digest` | §9.5 M1 : appels manqués, rappels, messages urgents. |
| M2 | `m2_produire_digest`, `m2_detecter_doublons`, `m2_signaler_doublon`, `m2_arbitrer_doublon` | §9.5 M2 : pipeline, leads chauds, doublons. |
| M4 | `m4_lister_pending_review`, `m4_volumetrie_pending_review`, `m4_produire_digest` | §9.5 M4 : dispatch du jour, file de complétion. |
| M4 | `m4_resoudre_demande`, `m4_resoudre_revue_completion` (N4) | §9.5 M4 : approbation des complétions. |
| M4 | `m4_produire_brouillon_temps` | §9.3 : brouillon de feuille de temps envoyé à M5. |
| M4 | `m4_lire_position_gps` | §9.2 « accès admin journalisé » ; POLITIQUE-geolocalisation §6. `accede_par` doit être sa propre personne (T1.4-k). |
| M4 | `m4_proposer_localisation`, `m4_confirmer_localisation` (N3) | §9.5 M4 « dispatch du jour » (T4.1-a, R15 §3) : l'admin voit la proposition de coordonnées d'un chantier (index RQA local) puis la confirme ; `confirme_par` doit être sa propre personne. Réservés à l'admin : c'est l'adresse d'un client, et une coordonnée confirmée décide d'une tournée. L'employé n'a aucun besoin de géocoder une adresse ; le vendeur non plus. Les deux outils refusent aussi, dans le code, tout rôle d'appareil autre qu'`admin`. |
| M4 | `m4_proposer_cedule` (N1), `m4_appliquer_cedule` (N3) | §9.5 M4 « dispatch du jour » (T4.1-d, R15 §4) : l'admin fait proposer une cédule par tournées depuis son téléphone (brouillon : aucune assignation, aucune vérité écrite), la lit (mode bridé, non cédulées et leurs raisons) puis l'applique ; `confirme_par` doit être sa propre personne. Réservés à l'admin : une tournée regroupe des chantiers de clients (adresses, coordonnées confirmées), et l'application décide qui voit quelles interventions. Le brouillon lui-même écrit un maillon au registre : l'ouvrir à l'employé ou au vendeur permettrait d'y déposer des plans à volonté. Les deux outils refusent aussi, dans le code, tout rôle d'appareil autre qu'`admin`. |
| M5 | `m5_etat_tresorerie`, `m5_lister_attentes_facturation` | §9.5 M5 : trésorerie, cash libre réel, factures à approuver. Identité confirmée en base ; la vue vient du rôle authentifié, jamais des arguments (T1.4-k2, plus bas). |
| M6 | `m6_approuver_po`, `m6_annuler_po` | §9.2 « le propriétaire approuve les bons de commande » ; §9.5 « PO à approuver ». |
| M6 | `m6_receptionner_commande`, `m6_soumettre_comptage` | §9.5 « réception rapide » ; §9 « inventaire ». |
| M6 | `m6_produire_digest`, `m6_evaluer_variance_chantier` | §9.5 « stock critique », « rapport de pertes et bris », « écarts de chantier ». |
| M7 | `m7_lister_file_approbation` | §9.5 M7 : contenus et réponses aux avis à approuver. |
| M9 | `m9_produire_briefing_matin`, `m9_lire_alertes_m8`, `m9_lire_etat_consolide` | §7 M9 mobile : « Admin/Nathan seulement ». |
| M9 | `m9_lister_demandes_approbation` (T0), `m9_decider_demande_approbation` (T1, N2) | §9.2 « le propriétaire approuve tout depuis le téléphone », §9.5 « Approbations » (T1.4-f). Règles ci-dessous : `admin` ouvre l'outil, la PERSONNE doit être le propriétaire. |
| M10 | `m10_statut_decision`, `m10_statut_revision`, `m10_arbitrer_revision`, `m10_paquet_contexte_affaire` | §7 M10 mobile : décisions à valider, contradictions, recherche dans la mémoire. |

M8 n'a aucun outil d'appareil : ses outils ingèrent ou calculent à partir de données que l'appelant
fournit ; aucun ne rend de valeurs pour le tableau de bord exécutif (§9.5).

### Les deux outils d'approbation de l'app (T1.4-f, étape 6)

`m9_lister_demandes_approbation` et `m9_decider_demande_approbation` sont les seuls outils dont la portée
`admin` ne suffit pas : c'est la PERSONNE du jeton qui décide (`src/opsys/approbations_appareil.py`). Chaque
ligne dit ce qui est déclaré et pourquoi.

| Déclaration ou garde | Pourquoi |
|---|---|
| `roles_appareil = {"admin"}` sur les deux | §9.5 : l'admin est le profil qui voit les approbations. Ni `employee` ni `seller` : la file contient des prix, des factures, des bons de commande. |
| Hébergés par M9, pas par le socle | `roles_outils` et `opsys verifier` ne lisent que les outils de département. Un outil commun `opsys_*` serait absent de `roles.json` (donc injoignable) et présent sur les dix serveurs à la fois (`Capacites` les liste tous). M9 lit déjà cette file (`m9_produire_briefing_matin`) et son mobile est « Admin/Nathan seulement » (§7). La logique reste au socle ; M9 ne décide rien. |
| Liste : T0, pas d'écriture | Lecture pure : `N0`, aucune approbation. |
| Les attentes des départements suivent la liste (T1.5) | `m9_lister_demandes_approbation` rend aussi l'autre moitié de la file du propriétaire (`approbations.attentes_departements`) : complétion en revue avec écart de matériaux critique (M4), facture prête à envoyer, chantier à réviser (M5). Toute personne de rôle `admin` les voit, comme le briefing du matin de M9 (`m9_produire_briefing_matin`, déjà de portée `admin`) : ce sont des résumés sans argument ni donnée personnelle, et elles ne se décident pas ici (`m9_decider_demande_approbation` ne s'y applique pas). Un département dont les attentes n'ont pas pu être lues est nommé (`attentes_illisibles`). |
| Décision : T1 mais **N2**, pas le N3 par défaut | L'outil EST la décision humaine. En mode `ombre`, N3 le renverrait dans la file qu'il sert à vider (circulaire). Sa garde est ailleurs (lignes suivantes). Même choix que `m4_deposer_fichier`. |
| L'identité vient de `contexte.identite_appelante()`, relue en base | Jamais un argument : les outils n'ont ni `personne` ni `role`, et `additionalProperties: false` refuse tout paramètre inconnu. Sans identité, personne inactive, ou rôle retiré depuis l'appairage : refus. |
| Rôle d'appareil `admin` revérifié dans le socle | Le core refuse déjà l'outil hors portée ; le socle ne s'y fie pas seul. |
| **Plafond : `nathan_owner`** pour décider N3 et N4 | L'appareil du propriétaire est appairé `admin`, mais un gestionnaire l'est aussi. Le rôle du jeton ne prouve pas qui est le propriétaire ; la personne, si (`identite.Role.NATHAN_OWNER`). Un `admin` qui ne l'est pas voit la file sans les arguments, en lecture seule. La décision est signée `nathan_owner` (et non `admin`, premier rôle alphabétique autorisé dans M4/M6). |
| La politique du département s'applique en plus | `Departement.roles_autorises`, inchangée : si N4 d'un département ne nomme pas `nathan_owner`, l'app ne l'élargit pas (`politique_du_departement`). |
| **N5 jamais** (et l'absence de niveau, lue N5) | L'attestation du professionnel (ADR-0009 §5) n'a pas d'écran dans l'app. La demande est montrée en lecture seule, « à décider à la console ». Approuver comme refuser. |
| Outil T3 jamais, même à un niveau N4 enregistré | `Outil.frontiere_humaine`. Défense en profondeur : `roles_outils` ne projette déjà aucun T3/N5. |
| Arguments affichés en entier, sinon lecture seule | On ne décide pas depuis un téléphone ce qu'il ne peut pas lire. `fix_gps` est masqué (`approbations.arguments_masques`, comme la trace). Au-delà de 1500 caractères : console. |
| Appareil obligatoire (clé d'idempotence et appareil du `_meta`) | Sans lui, refus. L'appareil entre au journal d'audit (`approbation.approuver` / `approbation.refuser`, champ `appareil`). |
| L'outil approuvé s'exécute sans l'identité ni les horloges de l'appareil | Comme depuis la console. Sinon `m4_pointer`, qui prend l'heure de réception de l'appareil courant, daterait le pointage d'un tiers à l'heure de l'approbation. |
| Refus d'une personne authentifiée : entrée d'audit `approbation.refus_appareil` | Une tentative de décider hors de ses droits (un gestionnaire, un N5) se voit. Pas d'audit pour une demande inconnue ou déjà décidée. |
| Rejeu : réponse enregistrée ; autre clé : `deja_decidee` | L'idempotence est celle du transport. La même clé rend la même réponse sans rien refaire ; une autre clé pour une demande déjà décidée reçoit un verdict clair. |
| La liste est bornée (`limite`, 4 600 caractères, attentes comprises : 1 500 au plus) | `Capacites` tronque au-delà de 6 000 caractères, et le téléphone ne lirait pas la suite. `reste` et `attentes_reste` comptent ce qui n'est pas montré. À titre de comparaison, `m9_produire_briefing_matin` n'est pas borné : mesuré en T1.5 avec des demandes N4 courtes, il tient à 22 décisions en attente (5 989 caractères) et dépasse 6 000 à 23 (un aperçu tronqué remplace alors la réponse). |

Décision attendue de Nathan : un `admin` qui n'est pas le propriétaire (un gestionnaire) ne décide rien depuis
l'app, même un N3 que le manifeste de son département lui laisse décider à la console (M4, M6). Le laisser
décider N3 depuis l'app est un changement de `approbations_appareil._lecture_seule` et un amendement d'ADR-0009 §4.

### Fermés à tous les appareils

Restent appelables par les agents (serveur MCP du département), jamais par un jeton d'appareil.
Les plus sensibles :

| Outil | Raison |
|---|---|
| `m4_lire_outbox` | WCT complets : positions GPS et identités de tous les techniciens ; outil des modules aval. |
| `m6_consommer_materiaux` | Prend encore un WCT fourni par l'appelant ; remplacé par `m6_declarer_materiaux_utilises` (T1.4-i). |
| `m3_estimer_projet`, `m3_creer_devis` | Le barème, le plancher rentable, le coût de chaque ligne et le taux de marge viendraient de l'appelant. |
| `m6_enregistrer_prix`, `m6_enregistrer_fournisseur`, `m6_enregistrer_besoins_prevus`, `m6_marquer_po_envoye` | Livre de prix, courriel de commande d'un fournisseur, prévu issu du devis accepté, engagement externe (N4). |
| `m8_rapport_metriques`, `m9_etat_consolide` | Ingèrent un snapshot fourni par l'appelant dans le registre de vérité. |
| `m7_auditer_seo_site`, `m7_calculer_roi` | Chemins de fichiers du serveur. |

## Contrôle d'accès par personne et par intervention (T1.4-k, M4 et M6)

La portée par outil dit QUEL outil ; celle-ci dit SUR QUOI et AU NOM DE QUI. Jusqu'à T1.4-k, M4 et M6
prenaient `technicien_id` (et `accede_par`) des arguments : un employé pouvait pointer, terminer, déposer
ou déclarer des matériaux pour l'intervention d'un collègue, et `m4_lister_interventions` lui montrait
celles de tous.

### Le lien personne -> technicien

**L'identifiant de technicien EST l'identifiant de la personne OPSYS** (`opsys.identite`, minuscules et
chiffres, immuable) pour tout appel d'appareil. Pas de table de correspondance :

- rien de plus à tenir à jour à chaque embauche, et aucun état intermédiaire « personne sans technicien » ;
- explicite (une personne n'agit que sous son propre identifiant), durable (l'identifiant ne change jamais),
  lu et non deviné (`contexte.identite_appelante()`, jamais les arguments) ;
- fail-closed : une intervention assignée à un identifiant qui n'est celui d'aucune personne (une ancienne
  valeur de cédule) n'est visible ni actionnable par aucun employé, seul l'`admin` y accède.

Conséquence pour l'exploitation : `techniciens_disponibles` de `m4_planifier_intervention` contient des
identifiants de personnes OPSYS. Un identifiant de personne ne se réutilise pas : la nouvelle personne
hériterait des interventions de l'ancienne.

**L'assignation entre au registre à la planification.** Avant T1.4-k elle n'y entrait qu'avec la
transition `en_route` : avant de partir, aucune intervention n'était « à quelqu'un ».
`m4_planifier_intervention` consigne maintenant le technicien de la cédule (maillon
`assignation_technicien`, sans statut : ce n'est pas une transition). Le DERNIER fait d'assignation
l'emporte (`etats.technicien_assigne`), qu'il vienne de la planification ou d'un départ : si l'admin
envoie un autre technicien, c'est lui qui a l'intervention. Une intervention que la cédule n'a pu assigner (aucune fenêtre) n'est à personne.
`m4_lister_interventions.technicien_assigne` porte ce même fait.

### Qui peut quoi

| Appelant | Règle |
|---|---|
| **Appel d'appareil, `employee`** | Seulement les interventions qui lui sont ASSIGNÉES, et seulement sous son propre identifiant. Autre intervention ou intervention inconnue : le même refus `REJ-INTERVENTION-NON-ASSIGNEE` (rien ne dit à un employé quelles interventions existent). `technicien_id` différent de la personne : `REJ-IDENTITE-FOURNIE-DIFFERENTE`, jamais préféré ni remplacé en silence. |
| **Appel d'appareil, `admin`** | Toutes les interventions ; il dispatche, pointe et déclare pour les autres, donc `technicien_id` est honoré tel quel. Exception : `accede_par` de `m4_lire_position_gps` doit être sa propre personne. |
| **Sans identité d'appareil** (agent, console, secret partagé) | Comportement d'avant T1.4-k, aucun contrôle de personne : voulu et documenté (voie des agents, ci-dessous). Seules les deux concordances du formulaire de M6 valent pour tous. |
| **Identité non confirmée en base** (personne inconnue, désactivée, rôle retiré depuis l'appairage, rôle sans portée sur M4/M6, ou aucune base jointe) | `REJ-IDENTITE-APPAREIL-INVALIDE`, avant toute écriture. La règle est celle de T1.4-h (`approbations.signataire_valide`) : `identite_appelante()` ne rend que ce que le core a transmis. Les lectures (liste, statut) lèvent un refus métier plutôt que de rendre une liste vide qui masquerait l'échec. |

| Outil (appel d'appareil) | `employee` | `admin` |
|---|---|---|
| `m4_pointer`, `m4_demarrer_route` | `technicien_id` = sa personne ET intervention assignée | libre |
| `m4_signaler_report`, `m4_creer_demande_ecart`, `m4_completer_intervention` | intervention assignée | libre |
| `m4_lister_interventions` | la liste est filtrée à ses interventions | toutes |
| `m4_statut_intervention` | son intervention : le statut ; une autre : `statut: null` (comme une inconnue) | toujours le statut |
| `m4_definir_consentement_gps` | `technicien_id` = sa personne (donne ou retire) | libre : consigne un consentement « par écrit » |
| `m4_lire_position_gps` | hors portée (T1.4-j) | `accede_par` = sa personne |
| `m4_proposer_localisation`, `m4_confirmer_localisation` | hors portée (T4.1-a) ; refusés aussi dans l'outil (`REJ-IDENTITE-APPAREIL-INVALIDE`) | `confirme_par` = sa personne, sinon `REJ-IDENTITE-FOURNIE-DIFFERENTE` ; l'heure du serveur fait foi |
| `m4_proposer_cedule`, `m4_appliquer_cedule` | hors portée (T4.1-d) ; refusés aussi dans l'outil (`REJ-IDENTITE-APPAREIL-INVALIDE`) | `confirme_par` = sa personne pour l'application, sinon `REJ-IDENTITE-FOURNIE-DIFFERENTE` ; l'heure du serveur fait foi |
| `m4_deposer_fichier`, `m4_etat_fichier` | identité confirmée seulement | idem |
| `m6_declarer_materiaux_utilises` | le WCT doit porter son `technicien_id` | tous les WCT |

Ordre des contrôles : identité confirmée, puis `technicien_id`, puis assignation ; toujours AVANT toute
écriture, y compris la clé de chiffrement GPS que `m4_pointer` crée pour un technicien (un refus n'en laisse
aucune). Chaque refus est prouvé sans écriture par les tests (registre comparé avant et après).

### `m6_declarer_materiaux_utilises` : le formulaire confronté au WCT

M6 relit le WCT à la source (T1.4-i) et le confronte au formulaire, dans cet ordre :

1. identité d'appareil confirmée ; WCT connu (`REJ-WCT-INCONNU`) ;
2. `employee` : le `technicien_id` du WCT (le technicien du dernier pointage de départ) doit être sa
   personne, sinon `REJ-INTERVENTION-NON-ASSIGNEE` ;
3. `intervention_id` du formulaire = celui du WCT (`REJ-FORMULAIRE-MATERIAUX-INTERVENTION-INCOHERENTE`),
   pour tous les appelants ;
4. `chantier_id` du formulaire = celui que la source impose (`REJ-FORMULAIRE-MATERIAUX-CHANTIER-INCOHERENT`).

**Le WCT ne porte aucun `chantier_id`** (`m4.travaux_termines` : `intervention_id`, `lead_id`, `technicien_id`,
`devis_id`…) : il ne peut donc pas être confronté au WCT lui-même. Il l'est à ce que M6 tient de la
source par le devis du WCT (`devis_id` -> besoins prévus, écrits depuis `m3.devis_accepte`) :

- le prévu du devis connaît son chantier : le formulaire doit le porter, pour TOUS les appelants ;
- sinon (aucun devis, aucun prévu, prévu sans chantier : `m3.devis_accepte.chantier_id` est nullable) :
  un `employee` n'a d'autre source que son intervention (un chantier de M4 EST une intervention, et c'est ce
  qu'envoie l'app) : son `chantier_id` doit être l'`intervention_id` du WCT ; un `admin` ou un agent, qui
  connaissent légitimement le chantier d'un bon de commande, ne sont pas contraints, et rien n'est deviné.

Le refus ne révèle jamais le chantier attendu. Cela ferme le dernier champ libre qui décidait où le stock
sort : `wct_id` (lu à la source), `intervention_id` (confronté), `chantier_id` (confronté ou dérivé).

## La vue financière de M5 (T1.4-k2, `m5_etat_tresorerie`)

Avant T1.4-k2, `m5_etat_tresorerie(role, autorise_couts)` laissait l'appelant choisir ce qu'il avait le
droit de voir : un appel d'appareil pouvait se déclarer autorisé aux coûts. Le module pur
`departments/m05-financecore/src/m5_financecore/acces.py` décide (il ne lit jamais l'identité) ;
`outils.py` la lit dans `contexte.identite_appelante()` et la fait confirmer en base à chaque appel
(`approbations.signataire_valide`, la règle de T1.4-h et de M4).

**La règle écrite : rôle -> droit de voir solde, argent disponible et taux.** Fermée par défaut (un rôle
absent de la table ne voit rien).

| Rôle du jeton | Voit les coûts | Source |
|---|---|---|
| `admin` | oui | §9.5 « M5 : trésorerie et cash libre réel » ; §7 M5 Mobile « Admin : ... trésorerie » |
| `employee` | non | §9.2 « l'employé ne voit jamais coûts, marges ni finances » |
| `seller` | non | §9.4 « Ne voit pas : finances globales » (le solde et l'argent disponible en sont) |

`employee` et `seller` n'ont de toute façon aucune portée sur l'outil (`roles_appareil` = `admin` seul,
T1.4-j : le core ne leur donne pas M5, prouvé par `tests/test_acces_tresorerie.py` sur
`openclaw.roles_outils`). Le socle n'applique pas `roles_appareil` aux outils T0 hors du core : le code de
M5 refuse donc lui aussi un rôle hors portée (`REJ-IDENTITE-APPAREIL-INVALIDE`), avant de lire quoi que ce
soit. La table garde leurs lignes pour le jour où la portée s'élargirait (ex. `seller` et la marge d'une
soumission, §9.4) : ils obtiendraient alors la vue sans montant, jamais plus.

### Ce que les arguments peuvent faire (appel d'appareil)

Même règle que `m3_lire_devis` (M3, T2.3-c) : **un argument ne peut que RESTREINDRE la vue, jamais
l'élargir**, et un refus est nommé, jamais une correction silencieuse (un appelant qui se trompe doit le
savoir).

| Argument | Effet |
|---|---|
| `autorise_couts` absent ou nul | vaut le droit du rôle (`admin` : montants) |
| `autorise_couts=false` | honoré : vue sans solde, argent disponible ni taux, sous le rôle authentifié |
| `autorise_couts=true` sans le droit du rôle | `REJ-ROLE-ELARGI`, rien n'est lu |
| `autorise_couts` non booléen (`"false"`, `0`...) | `REJ-AUTORISE-COUTS-REQUIS` : jamais interprété par sa « vérité » |
| `role` absent, nul ou égal au rôle authentifié | la réponse porte le rôle authentifié |
| `role` différent | `REJ-IDENTITE-FOURNIE-DIFFERENTE`, jamais remplacé en silence |

Pourquoi `role` n'est pas « restreignable » comme dans M3 : dans M5, `role` ne règle aucune vue (c'est
`autorise_couts`) ; c'est l'étiquette que la réponse porte et que son empreinte `etat_id` scelle. La seule
étiquette fidèle est celle du jeton. Un aperçu « comme un employé » se demande par `autorise_couts=false`.

Ordre des contrôles, tous AVANT la lecture du registre (un refus n'ouvre même pas le registre des
mouvements) et sans aucune écriture (lecture T0 : ni file, ni trace) : identité confirmée en base
(personne inconnue, désactivée, rôle retiré depuis l'appairage, ou aucune base jointe :
`REJ-IDENTITE-APPAREIL-INVALIDE`), rôle dans la portée de l'outil, `autorise_couts` booléen, `role`
concordant, puis `autorise_couts` sans élargissement.

### Sans identité d'appareil (agent, console, outil interne)

Comportement d'avant, sans contrôle de personne : `role` est l'étiquette de l'appelant et `autorise_couts`
reste **obligatoire et explicite** (fail-closed : jamais une valeur par défaut qui exposerait un montant).
Le secret partagé de la passerelle garde l'accès complet (« Voie des agents »).

Seul changement de contrat : `role` et `autorise_couts` ne sont plus `required` au schéma (l'app admin n'a pas
à réclamer ce que son rôle lui donne). L'absence d'`autorise_couts` chez un agent, autrefois un refus de
schéma (`arguments_invalides`), est maintenant un verdict nommé, `REJ-AUTORISE-COUTS-REQUIS`, qui dit quoi
fournir : même refus fermé, sans montant. La réponse d'un accord garde exactement sa forme (mêmes clés,
même `etat_id` que l'appel d'agent explicite pour le même rôle) ; un refus est `{"accepte": false,
"verdict": {...}}`.

`m5_lister_attentes_facturation` (sans argument) exige la même identité confirmée en base et le même rôle
pour un appel d'appareil ; sans identité d'appareil, la liste, comme avant. La file du propriétaire
(`attentes()`) et la console appellent la fonction métier directement, sans ce contrôle.

### Ce que M5 laisse ouvert

- **`m5_enregistrer_paiement_facture(approbateur)`** (T3/N5, aucun appareil : `Outil.frontiere_humaine`)
  inscrit à la facture l'`approbateur` que la demande d'approbation a reçu en argument, pas la personne qui
  signe la décision. La vraie signature est au journal des approbations (`nathan_owner` et l'attestation) ;
  la facture peut nommer quelqu'un d'autre. Il faudrait que le socle transmette l'identité de la décision à
  l'outil exécuté après approbation : hors de cette tranche.
- **`mouvements_historique`** (simulation en mémoire) reste accepté pour un appel d'appareil : il ne
  révèle rien qui ne vienne de l'appelant, mais l'écran « cash libre réel » de l'admin devrait lire le
  registre de production, pas un historique fourni. À fermer quand l'app appellera l'outil.
- **`m5_enregistrer_mouvement(source)`, `m5_creer_facture_brouillon(client_id...)`** : étiquettes ou
  références de l'appelant, mais aucun appareil (T3, ou cascade §6).

### Ce qui reste

- **M2, M3** : `m2_enregistrer_interaction(auteur)` prend encore l'identité d'un argument ; pour
  `m3_lire_devis`, `role` ne peut que restreindre la vue du rôle authentifié (T2.3-c) ; aucun filtre par
  propriétaire de lead (vendeur, Client 360, M3). Même mécanisme à appliquer : lire `identite_appelante()`,
  la confirmer en base, refuser l'argument qui la contredit. M5 est fait (section précédente).
- **Aucun rattachement fichier -> intervention** : `m4_deposer_fichier` ne porte pas d'intervention (un
  fichier est adressé par son SHA-256), donc rien à contrôler au dépôt ; `m4_completer_intervention` accepte
  la référence de n'importe quel fichier complet et du bon type. Un employé qui connaît l'empreinte d'un
  fichier d'un collègue pourrait le citer dans SA complétion.
- **L'admin pointe pour autrui avec sa propre position** : `m4_pointer` par un admin enregistre le fix GPS de
  l'appareil de l'admin au nom du technicien (si celui-ci a consenti). Voulu tant que le dispatch se fait
  ainsi ; à revoir avec la capture GPS réelle. Le maillon de pointage ne nomme pas qui l'a saisi (la trace de
  T1.4-h, seulement en mode `ombre`).
- **`decision_admin`** : le motif de report réservé à l'admin n'est pas refusé à un employé par le code.
- **Droit d'accès de l'employé à SES positions** (§7) : aucun outil ; `m4_lire_position_gps` reste à l'admin.
- **L'app apprend sa personne et son rôle (T1.4-c5)** : elle ne demande plus son identifiant à l'employé
  (`punch.tsx`, `job/[id]`, `consent.tsx`). Elle lit `GET /opsys/identite` avec son jeton d'appareil, qui
  rend la personne et le rôle nommé de `opsys/appareils.json`, par le même code que la porte d'outils ; le
  serveur confronte toujours l'identifiant envoyé à l'identité authentifiée (un autre est refusé). Ce n'est
  pas un outil : aucune portée à déclarer dans `roles_appareil`, aucune ligne de la table ci-dessus. Un
  appareil sans attribution, ou avec un rôle que `roles.json` ne déclare pas, n'a aucune identité et
  n'ouvre aucun profil (`docs/architecture/MOBILE.md`, « Identité de l'appareil »). Hors ligne, l'app garde
  la dernière identité confirmée, marquée « à reconfirmer » : une mutation créée alors porte la personne
  gardée, et le serveur la refuse si l'appareil a été réattribué entre-temps.
- **Localisation d'un chantier (T4.1-a).** `m4_confirmer_localisation` est N3 : en mode `ombre`, l'appel d'un
  agent attend une personne ; en `supervise` et `autonome`, un N3 s'exécute sans file, et « une personne a
  confirmé » ne repose plus que sur `confirme_par`, que rien ne prouve pour un appel sans identité d'appareil.
  Décision à prendre avant de promouvoir M4 : garder N3, ou exiger une identité d'appareil (ou passer N4).
  Aussi, l'`adresse` et les coordonnées saisies d'un appel d'agent restent en clair dans la file
  d'approbation (`approbations.arguments`) : seule la trace « valider au départ » les masque.
- **Cédule par tournées (T4.1-d).** `m4_appliquer_cedule` est N3, comme `m4_confirmer_localisation` : en mode
  `ombre`, l'appel d'un agent attend une personne ; en `supervise` et `autonome`, un N3 s'exécute sans file, et « une
  personne a appliqué » ne repose plus que sur `confirme_par` pour un appel sans identité d'appareil. Décision à
  prendre avant de promouvoir M4 : garder N3, ou exiger une identité d'appareil (ou passer N4, l'assignation
  décidant de ce que voit chaque employé). `m4_proposer_cedule` est N1 (brouillon, automatique) : elle écrit un
  maillon `cedule_proposee`, jamais une assignation. Les deux gardes de l'application (état des interventions,
  entrée du solveur reconstruite avec les coordonnées d'aujourd'hui) et `verifier_plan` ne remplacent pas cette
  décision : ils empêchent d'appliquer un plan périmé, pas un plan qu'un agent aurait mal paramétré.
- **Voie des agents.** Le secret partagé de la passerelle garde l'accès complet aux outils (documenté,
  voulu) : seule la voie du jeton d'appareil passe par `roles.json`, donc par ces contrôles.
- **Approbation différée.** Un appel d'appareil dont l'identité n'est pas valide part en file (T1.4-h) ; une
  fois approuvé, l'outil s'exécute sans identité d'appareil, donc sans ce contrôle : c'est la décision du
  propriétaire qui le couvre.

## Limites de la portée par outil (T1.4-j)

La portée par outil ne dit toujours pas AU NOM DE QUI pour les départements qui n'ont pas encore
été adaptés (M2 et M3 pour le propriétaire d'un lead, voir « Ce qui reste » ci-dessus ; M5 l'est depuis
T1.4-k2). Pour M4 et M6, T1.4-k a fermé les deux
limites que ce document listait : l'identité prise dans les arguments (`m4_pointer(technicien_id)`,
`m4_lire_position_gps(accede_par)`, `m4_definir_consentement_gps(technicien_id)`) et la portée par
instance (un employé voyait et agissait sur les interventions de tous).

## Ce que §9 demande et qu'aucun outil sûr ne permet encore

Pas de déclaration possible sans outil : réception de stock par un employé assigné (§9.3, M6.7 : la
réponse porte des prix), photo de reçu et achat imprévu (§9.3, M5), note de chantier et « chose à ne
pas oublier » (§9.3, M10), lancer l'estimation, annoter une photo, ajouter une mesure manuelle
(§9.4 M3 : le barème doit rester sur le serveur), statut de paiement d'un client (§9.4 M5), analytique
de ses ventes (§9.4 M8), tableau de bord exécutif (§9.5 M8), incident (§9.3, M4).

## Ajouter ou élargir une portée

1. Écrire `roles_appareil=frozenset({...})` sur l'outil, avec en commentaire la ligne de §9 qui le
   justifie.
2. Ajouter l'outil à la table épinglée de `tests/test_portees_appareil.py` et à ce document.
3. `opsys verifier` et `pytest tests` doivent rester verts.

Demander à la relecture, pour tout outil ouvert à `employee` ou `seller` : lit-il des données d'un
autre, prend-il une identité, un prix, un rôle ou un chemin dans ses arguments, approuve-t-il, est-il
T3/N5 ?
