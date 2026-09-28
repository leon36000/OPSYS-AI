# Portée des rôles d'appareil (T1.4-j)

> Complète [MOBILE.md](MOBILE.md) (appairage, jeton d'appareil), [IDEMPOTENCE.md](IDEMPOTENCE.md)
> §7 bis (le core refuse un outil hors portée) et [ADR-0009](../decisions/ADR-0009-socle-metier.md)
> §4-§5. Les profils viennent de la [définition produit](../produit/DEFINITION-PRODUIT.md) §9.
> La table ci-dessous est épinglée par `tests/test_portees_appareil.py` ; le contrôle d'accès par personne
> et par intervention (T1.4-k) par `tests/test_acces_par_intervention.py` et les tests de M4 et de M6.

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
  à changer.
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

Les références sont celles de `DEFINITION-PRODUIT.md`. 48 outils sur 119 sont déclarés.

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

### `admin` (48 outils) : §9.5 + employé + vendeur

Les 11 outils de l'employé, les 9 du vendeur, et :

| Département | Outils réservés à l'admin | Pourquoi |
|---|---|---|
| M1 | `m1_produire_digest` | §9.5 M1 : appels manqués, rappels, messages urgents. |
| M2 | `m2_produire_digest`, `m2_detecter_doublons`, `m2_signaler_doublon`, `m2_arbitrer_doublon` | §9.5 M2 : pipeline, leads chauds, doublons. |
| M4 | `m4_lister_pending_review`, `m4_volumetrie_pending_review`, `m4_produire_digest` | §9.5 M4 : dispatch du jour, file de complétion. |
| M4 | `m4_resoudre_demande`, `m4_resoudre_revue_completion` (N4) | §9.5 M4 : approbation des complétions. |
| M4 | `m4_produire_brouillon_temps` | §9.3 : brouillon de feuille de temps envoyé à M5. |
| M4 | `m4_lire_position_gps` | §9.2 « accès admin journalisé » ; POLITIQUE-geolocalisation §6. `accede_par` doit être sa propre personne (T1.4-k). |
| M5 | `m5_etat_tresorerie`, `m5_lister_attentes_facturation` | §9.5 M5 : trésorerie, cash libre réel, factures à approuver. |
| M6 | `m6_approuver_po`, `m6_annuler_po` | §9.2 « le propriétaire approuve les bons de commande » ; §9.5 « PO à approuver ». |
| M6 | `m6_receptionner_commande`, `m6_soumettre_comptage` | §9.5 « réception rapide » ; §9 « inventaire ». |
| M6 | `m6_produire_digest`, `m6_evaluer_variance_chantier` | §9.5 « stock critique », « rapport de pertes et bris », « écarts de chantier ». |
| M7 | `m7_lister_file_approbation` | §9.5 M7 : contenus et réponses aux avis à approuver. |
| M9 | `m9_produire_briefing_matin`, `m9_lire_alertes_m8`, `m9_lire_etat_consolide` | §7 M9 mobile : « Admin/Nathan seulement ». |
| M10 | `m10_statut_decision`, `m10_statut_revision`, `m10_arbitrer_revision`, `m10_paquet_contexte_affaire` | §7 M10 mobile : décisions à valider, contradictions, recherche dans la mémoire. |

M8 n'a aucun outil d'appareil : ses outils ingèrent ou calculent à partir de données que l'appelant
fournit ; aucun ne rend de valeurs pour le tableau de bord exécutif (§9.5).

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

### Ce qui reste

- **M2, M3, M5** : `m2_enregistrer_interaction(auteur)` et `m5_etat_tresorerie(role, autorise_couts)`
  prennent encore l'identité d'un argument ; pour `m3_lire_devis`, `role` ne peut que restreindre la vue du
  rôle authentifié (T2.3-c) ; aucun filtre par propriétaire de lead (vendeur, Client 360, M3). Même
  mécanisme à appliquer : lire `identite_appelante()`, la confirmer en base, refuser l'argument qui la
  contredit.
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
- **L'app ne connaît pas la personne appairée** : l'employé saisit encore son identifiant à la main
  (`punch.tsx`, `job/[id]`, `consent.tsx`) ; le serveur le confronte à l'identité authentifiée.
- **Voie des agents.** Le secret partagé de la passerelle garde l'accès complet aux outils (documenté,
  voulu) : seule la voie du jeton d'appareil passe par `roles.json`, donc par ces contrôles.
- **Approbation différée.** Un appel d'appareil dont l'identité n'est pas valide part en file (T1.4-h) ; une
  fois approuvé, l'outil s'exécute sans identité d'appareil, donc sans ce contrôle : c'est la décision du
  propriétaire qui le couvre.

## Limites de la portée par outil (T1.4-j)

La portée par outil ne dit toujours pas AU NOM DE QUI pour les départements qui n'ont pas encore
été adaptés (M2, M3, M5, voir « Ce qui reste » ci-dessus). Pour M4 et M6, T1.4-k a fermé les deux
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
