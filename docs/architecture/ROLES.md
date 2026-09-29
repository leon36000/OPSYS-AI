# Portée des rôles d'appareil (T1.4-j)

> Complète [MOBILE.md](MOBILE.md) (appairage, jeton d'appareil), [IDEMPOTENCE.md](IDEMPOTENCE.md)
> §7 bis (le core refuse un outil hors portée) et [ADR-0009](../decisions/ADR-0009-socle-metier.md)
> §4-§5. Les profils viennent de la [définition produit](../produit/DEFINITION-PRODUIT.md) §9.
> La table ci-dessous est épinglée par `tests/test_portees_appareil.py` ; le contrôle d'accès par personne
> et par intervention (T1.4-k) par `tests/test_acces_par_intervention.py` et les tests de M4 et de M6 ; la
> vue financière de M5 (T1.4-k2) par `tests/test_acces_tresorerie.py` et les tests de M5 ; les leads de M2 et
> les devis de M3 (T1.4-k2) par `tests/test_acces_par_proprietaire.py` et les tests de M2 et de M3 ; la liste des
> leads du vendeur (T4.6) par `tests/e2e/test_liste_leads_vendeur.py` (la vraie porte d'appareil) et les tests de M2 ;
> la réassignation d'un lead et la republication de son fait (T1.4-m) par `tests/e2e/test_reassignation_lead_appareil.py`
> (la vraie porte d'appareil), `tests/test_republication_devis_vendeur.py` (M2, bus, M3) et les tests de M2.

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
  (`opsys-metier openclaw configurer`), que `core/src/gateway/opsys-device-roles.ts` lit. Le core n'a rien
  à changer. Depuis T1.4-c6, le même fichier porte `serveurs` (`openclaw.serveurs_outils`) : le
  serveur MCP de chaque outil permis, sous le même nom nu. Le core compare la portée au nom nu, puis
  appelle CE serveur sous CE nom ([MOBILE.md](MOBILE.md), « Nom d'un outil de l'app au moteur »).
- **T3/N5 jamais.** Un outil T3 ou de niveau N5 (`Outil.frontiere_humaine`) n'est projeté dans aucun
  rôle, quoi que déclare l'outil. Ces gestes restent à `nathan_owner` et à l'attestation du
  professionnel (ADR-0009 §5).
- **Contrôle.** `opsys-metier verifier` échoue si une déclaration cite un rôle qui n'est pas un rôle
  d'appareil (inconnu, `client`, `nathan_owner`...) ou si un outil T3/N5 en déclare une.
  `openclaw.generer` refuse de même, avant d'écrire quoi que ce soit.

### Pas de rôle `client`, pas de rôle `nathan_owner`

Le client (§9.6) passe par un lien tokenisé et expirant, jamais par un appareil apparié
(`appareils.ROLES_APPAREIL`, R12 §6) : `client` n'a pas d'entrée dans `roles.json`, donc le core le
refuse en `role_unknown`, et une déclaration qui le cite est refusée par `opsys-metier verifier`. L'appareil
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

Les références sont celles de `DEFINITION-PRODUIT.md`. 87 outils sur 165 sont déclarés.

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

### `seller` (11 outils) : §9.4, ses leads et ses soumissions

| Outil | Pourquoi |
|---|---|
| `m2_lister_leads` (T0) | §9.4 « ses leads », « pipeline personnel », priorité (T4.6, M2.11). La liste de SES leads seulement, filtrable par statut et par segment (14, la règle citée avec la donnée qui la déclenche ; « non calculable, manque X » sinon), paginée (`decalage`, `suivant`), sans montant ni contact. Un vendeur ne compte jamais les leads des autres dans `total`. |
| `m2_obtenir_client_360`, `m2_trouver_client_de_lead` | §9.4 « Client 360 ». Ses leads seulement (T1.4-k2, plus bas). |
| `m2_suggerer_prochaine_action` | §9.4 « prochaine meilleure action ». Ses leads seulement. |
| `m2_evaluer_readiness` | §9.4 M3 « lead prêt pour l'estimation ». Ses leads seulement. |
| `m2_transitionner_statut` | §9.4 « pipeline personnel » (perdu avec motif, converti). Ses leads seulement. |
| `m2_enregistrer_interaction` | §9.4 « notes ». Ses leads seulement, sous son propre nom. |
| `m3_lire_devis` | §9.4 M3 « voir risques et marge » ; « ne voit pas les coûts internes au-delà de sa soumission ». Les devis de ses leads seulement. |
| `m3_generer_soumission_brouillon` | §9.4 « soumissions ». HTML ou PDF (`format`), mêmes gardes. Sans coût ni marge. Les devis de ses leads seulement. |
| `m3_demander_envoi_devis` (T2, **N4**) | §9.4 « soumissions », §7 M3.14 « revue et approbation humaine » (T4.7). Il DEMANDE : le socle met la demande dans la file du propriétaire, rien n'est envoyé, rien ne change. Il ne décide jamais (voir « L'envoi d'un devis par approbation N4 » plus bas). |
| `m3_qualifier_photos` | §9.4 « demander des photos au client » : ce qui manque. |

Aucun outil M4, M5, M6, M7, M8, M9, M10 : ni finances (« ne voit pas : finances globales »), ni prix
fournisseurs, ni coûts réels (`m3_lire_ecarts_estime_reel`).

### `admin` (87 outils) : §9.5 + employé + vendeur

Les 11 outils de l'employé, les 10 du vendeur, et :

| Département | Outils réservés à l'admin | Pourquoi |
|---|---|---|
| M1 | `m1_produire_digest` | §9.5 M1 : appels manqués, rappels, messages urgents. |
| M1 | `m1_lire_transfert` (T0), `m1_clore_transfert` (N3) | §7 M1.8, M1.12 et §9.5 M1 « plaintes, transferts, prendre en charge » (T4.5) : l'admin lit le contexte d'une plainte, d'une urgence de sécurité ou d'un transfert (résumé, contact, messages du client) puis le clôt. La clôture est une décision HUMAINE : voir « Les transferts à un humain de M1 » plus bas. Ni l'employé ni le vendeur : le contact et les mots d'un client qui se plaint sont pour le propriétaire. |
| M2 | `m2_produire_digest`, `m2_detecter_doublons`, `m2_signaler_doublon`, `m2_arbitrer_doublon` | §9.5 M2 : pipeline, leads chauds, doublons. |
| M2 | `m2_reassigner_lead` (N3), `m2_republier_assignations` (N3) | §9.5 (le propriétaire ou son gestionnaire reprend le dossier d'un vendeur ; T1.4-m). La réassignation est une décision HUMAINE : voir « La réassignation d'un lead » plus bas. La republication remet au bus le fait de propriété que les leads qualifiés avant T1.4-k2 n'ont jamais publié ; outil de mise en service, idempotent, dérivé du registre. Ni l'employé ni le vendeur (un vendeur ne « prend » ni ne « cède » un lead). |
| M4 | `m4_lister_pending_review`, `m4_volumetrie_pending_review`, `m4_produire_digest` | §9.5 M4 : dispatch du jour, file de complétion. |
| M4 | `m4_resoudre_demande`, `m4_resoudre_revue_completion` (N4) | §9.5 M4 : approbation des complétions. |
| M4 | `m4_produire_brouillon_temps` | §9.3 : brouillon de feuille de temps envoyé à M5. |
| M4 | `m4_lire_position_gps` | §9.2 « accès admin journalisé » ; POLITIQUE-geolocalisation §6. `accede_par` doit être sa propre personne (T1.4-k). |
| M4 | `m4_proposer_localisation`, `m4_confirmer_localisation` (N3) | §9.5 M4 « dispatch du jour » (T4.1-a, R15 §3) : l'admin voit la proposition de coordonnées d'un chantier (index RQA local) puis la confirme ; `confirme_par` doit être sa propre personne. Réservés à l'admin : c'est l'adresse d'un client, et une coordonnée confirmée décide d'une tournée. L'employé n'a aucun besoin de géocoder une adresse ; le vendeur non plus. Les deux outils refusent aussi, dans le code, tout rôle d'appareil autre qu'`admin`. |
| M4 | `m4_proposer_cedule` (N1), `m4_appliquer_cedule` (N3) | §9.5 M4 « dispatch du jour » (T4.1-d, R15 §4 ; T4.12) : l'admin fait proposer une cédule par tournées depuis son téléphone (brouillon : aucune assignation, aucune vérité écrite), la lit (mode bridé, non cédulées et leurs raisons, provenance de chaque valeur : profil des équipes ou surcharge) puis l'applique ; appliquer fait sortir de `a_planifier` les interventions prêtes que le plan place ; `confirme_par` doit être sa propre personne. Réservés à l'admin : une tournée regroupe des chantiers de clients (adresses, coordonnées confirmées), et l'application décide qui voit quelles interventions. Le brouillon lui-même écrit un maillon au registre : l'ouvrir à l'employé ou au vendeur permettrait d'y déposer des plans à volonté. Les deux outils refusent aussi, dans le code, tout rôle d'appareil autre qu'`admin`. |
| M4 | `m4_verifier_preparation` (T0) | §9.5 M4 « dispatch du jour » (T4.10-b, M4.6) : l'admin lit, pour une intervention née d'un devis accepté, si elle peut être planifiée, volet par volet, et ce qui manque (soumission, adresse confirmée, équipe, matériel, météo). Lecture pure : rien n'est écrit, aucun volet non vérifiable n'est présenté comme prêt, aucune date ni aucun créneau n'est promis. Réservé à l'admin : c'est l'état d'un chantier de client (adresse confirmée ou non). L'outil refuse aussi, dans le code, tout rôle d'appareil autre qu'`admin`. |
| M4 | `m4_verifier_meteo_creneau` (T0) | §9.5 M4 « dispatch du jour » (T4.13, M4.10, M4.21) : l'admin lit, pour un plan de cédule proposé, la météo de chaque créneau (bloquant, validation requise, ok ou inconnu, avec la prévision, sa source et son heure d'émission) contre les seuils que le propriétaire a déclarés (`opsys-metier meteo declarer`) ; un créneau bloquant donne un report proposé (motif `meteo`) et une nouvelle cédule pour les jours restants. Lecture pure : rien n'est écrit, aucune intervention ne change d'état, aucune cédule n'est rangée ni appliquée ; le report d'une intervention planifiée reste `m4_signaler_report` et l'application d'une cédule `m4_appliquer_cedule` (N3). Une donnée absente (seuil, prévision, date, fournisseur en panne) donne `inconnu`, jamais `ok`. Réservé à l'admin : un plan regroupe des chantiers de clients (adresses confirmées, tournées). L'outil refuse aussi, dans le code, tout rôle d'appareil autre qu'`admin`. |
| M5 | `m5_etat_tresorerie`, `m5_lister_attentes_facturation` | §9.5 M5 : trésorerie, cash libre réel, factures à approuver. Identité confirmée en base ; la vue vient du rôle authentifié, jamais des arguments (T1.4-k2, plus bas). T4.16 : `m5_etat_tresorerie` AJOUTE `cash_libre` (avec sa décomposition), `argent_disponible_note` et `mention` sans changer ses clés d'avant ; le cash libre suit la même vue : un rôle sans droit de voir les coûts ne le voit pas. |
| M5 | `m5_lire_echeances_fiscales` (T0) | §7 M5.5 « calendrier fiscal vivant » (T4.16) : les prochaines échéances TPS/TVQ, les retards et la taxe nette de chaque période. Lecture pure, même règle d'accès que la trésorerie (identité confirmée en base, la vue vient du rôle, `autorise_couts` ne peut que restreindre : sans droit, les dates sans aucun montant). La fréquence de production, la fin d'exercice et la date de dernière remise sont au propriétaire (`department.yaml`, GATE NATHAN) : absentes, refus nommé qui dit quoi déclarer ; une année non déclarée au calendrier est refusée. `aujourd_hui` est un argument requis (M5 n'a pas d'horloge) ; aucun montant ni date limite ne se passe en argument. Ni remise, ni déclaration, ni paiement : le calendrier propose (N5, Nathan et le CPA). |
| M5 | `m5_lire_rentabilite_chantier`, `m5_lire_comptes_a_recevoir` | §6 « travaux terminés », §9.5 M5 : coût réel et marge par chantier, comptes à recevoir (factures envoyées). Lecture pure, même règle d'accès que la trésorerie (T1.5-d) : coûts, marges et créances sont des finances, jamais pour l'employé ni le vendeur (§9.2, §9.4) ; aucun montant, prix ni taux ne se passe en argument. |
| M5 | `m5_lister_comptes_a_payer` (T0), `m5_saisir_facture_fournisseur` (T1, N3) | §7 M5.2 « comptes à payer », M6.16, §9.5 M5 « dépenses à valider » (T4.15) : ce que l'entreprise doit aux fournisseurs, par PO reçu (l'« à payer attendu » de ce que M6 a réceptionné, le facturé, le rapprochement PROPOSÉ avec ses écarts), et la saisie d'une facture fournisseur, repli documenté de l'OCR fermé. Finances : jamais pour l'employé ni le vendeur (§9.2, §9.4). La lecture a la même règle d'accès que la trésorerie et rend des pages sous la limite de 6 000 caractères ; la saisie exige un HUMAIN (section plus bas). Depuis T4.15-c, la lecture rend l'état COURANT des factures et compte les factures sans PO ; `sans_po=true` les liste une à une. Aucun outil ne paie un fournisseur : c'est N5, Nathan et le CPA. |
| M5 | `m5_saisir_facture_sans_po` (T1, N3), `m5_corriger_facture_fournisseur` (T2, **N4**), `m5_annuler_facture_fournisseur` (T2, **N4**) | §7 M5.2 et §9.5 M5 « dépenses à valider » (T4.15-c) : une dépense que M6 n'a pas commandée (carburant, outils), et la correction ou l'annulation d'une facture fournisseur saisie, sans jamais modifier la facture d'origine (une pièce s'ajoute au registre, motif obligatoire). Finances : jamais pour l'employé ni le vendeur. Les trois exigent un HUMAIN, et les deux N4 attendent la décision du propriétaire ou de la finance : section « Corriger, annuler et saisir sans PO » plus bas. |
| M6 | `m6_approuver_po`, `m6_annuler_po` | §9.2 « le propriétaire approuve les bons de commande » ; §9.5 « PO à approuver ». |
| M6 | `m6_receptionner_commande`, `m6_soumettre_comptage` | §9.5 « réception rapide » ; §9 « inventaire ». |
| M6 | `m6_produire_digest`, `m6_evaluer_variance_chantier` | §9.5 « stock critique », « rapport de pertes et bris », « écarts de chantier ». |
| M6 | `m6_reserver_materiel` (N2), `m6_liberer_reservation` (N2), `m6_transferer_stock` (T1, N3), `m6_lire_disponibilite` (T0) | §7 M6.8 « réservation par chantier », M6.9 « emplacements de stock », §9.5 tableau de bord « stock réservé et disponible », « chantiers sans matériel prêt » (T4.14). L'admin réserve le matériel d'un devis accepté (le bus le fait déjà à l'acceptation ; l'outil sert au prévu saisi à la main et à re-réserver), libère une réservation (annulation : N2, rien n'est dépensé ni supprimé, la trace reste), déplace du stock entre emplacements (audité : acteur, motif, avant et après ; N3 par défaut, l'humain qui agit lui-même n'attend rien) et lit ce qui est en main, réservé et disponible, et où. Fermés à l'employé : un transfert vers le rebut ou le fournisseur retire du stock de ce qu'on peut réserver, et la lecture porte des quantités sur tous les chantiers. Les quatre refusent aussi, dans le code, tout rôle d'appareil autre qu'`admin` (`REJ-IDENTITE-APPAREIL-INVALIDE`) : le socle n'applique pas `roles_appareil` à la lecture (T0) hors du core. Aucun ne crée de bon de commande. |
| M7 | `m7_lister_file_approbation` | §9.5 M7 : contenus et réponses aux avis à approuver. |
| M7 | `m7_lister_demandes_avis` (T0) | §9.5 M7 « avis à répondre » et §6 « travaux terminés » (T1.5-d) : le brouillon de demande d'avis né d'un « Terminer » avec le consentement du client, avec la preuve de ce consentement (qui, quand, quel texte). Lecture seule, bornée à huit brouillons (`Capacites` tronque à 6 000 caractères) : rien n'est envoyé, l'envoi au client reste une décision humaine. Ni l'employé (il recueille le consentement, il ne lit pas ce que le propriétaire décide d'en faire) ni le vendeur. |
| M7 | `m7_lister_contenus_chantier` (T0), `m7_decider_contenu` (N3), `m7_exporter_paquet_manuel` (N2), `m7_enregistrer_retrait_consentement_marketing` (N2) | §7 M7 « usine à contenu » et M7.2 « paquet manuel » (T4.17) : le propriétaire lit les cinq contenus d'un chantier terminé en entier, décide (approuver ou rejeter), prend le paquet à publier LUI-MÊME et enregistre le retrait du consentement d'un client. Règles plus bas (« L'usine à contenu de M7 »). Ni l'employé (il recueille le consentement, il ne voit pas ce qu'on en fait) ni le vendeur. |
| M9 | `m9_produire_briefing_matin`, `m9_lire_alertes_m8`, `m9_lire_etat_consolide` | §7 M9 mobile : « Admin/Nathan seulement ». |
| M9 | `m9_lister_demandes_approbation` (T0), `m9_decider_demande_approbation` (T1, N2) | §9.2 « le propriétaire approuve tout depuis le téléphone », §9.5 « Approbations » (T1.4-f). Règles ci-dessous : `admin` ouvre l'outil, la PERSONNE doit être le propriétaire. |
| M10 | `m10_statut_decision`, `m10_statut_revision`, `m10_arbitrer_revision`, `m10_paquet_contexte_affaire` | §7 M10 mobile : décisions à valider, contradictions, recherche dans la mémoire. |
| M10 | `m10_lister_signaux` (T0), `m10_prendre_en_compte_signal`, `m10_clore_signal`, `m10_lier_session_affaire` (N3) | §9.5 « alertes critiques » (T3.3-suite-b). Les trois écritures sont des décisions HUMAINES : voir « Les écritures humaines de M10 » plus bas. |

M8 n'a aucun outil d'appareil : ses outils ingèrent ou calculent à partir de données que l'appelant
fournit ; aucun ne rend de valeurs pour le tableau de bord exécutif (§9.5).

### Les écritures humaines de M10 (T3.3-suite-b)

`m10_prendre_en_compte_signal`, `m10_clore_signal` et `m10_lier_session_affaire` sont ouverts à `admin` et à
personne d'autre, et ne s'exécutent que pour un HUMAIN identifié : un signal critique n'est jamais pris en
compte ni clos par le modèle seul, et une session n'est jamais liée à une affaire par un texte de client. Ce
n'est pas seulement la portée du jeton : l'outil refuse lui-même (`REJ-HUMAIN-REQUIS`) tout appel qui n'est ni
(1) un appel d'appareil dont l'identité est confirmée en base (personne active, rôle `admin`), ni (2)
l'exécution d'une demande qu'un humain vient d'approuver dans la file (depuis T4.15-d, c'est le SOCLE qui dit qui a
approuvé, `approbations.approbateur_en_cours`, et l'outil ne reconnaît que `admin` et `nathan_owner`). Un appel d'agent
dans un département en mode `supervise` ou `autonome`, où un N3 s'exécute sans file, est donc refusé. L'écriture porte
le nom de la personne, sa voie (`appareil` ou `approbation`), son rôle et son motif ; l'heure de réception du serveur
fait foi pour un appel d'appareil. `m10_affaire_de_la_session` (lecture du lien) reste fermé à tous les appareils :
le moteur de contexte du core est son seul appelant.

### L'usine à contenu de M7 (T4.17)

Un chantier terminé avec le consentement du client à l'usage de son chantier donne cinq contenus (Facebook,
Instagram, fiche Google, script de vidéo courte, demande de témoignage), que M7 propose et que le PROPRIÉTAIRE décide.
Deux outils n'ont aucune portée d'appareil : `m7_proposer_contenus_chantier` (brouillon N1, que le consommateur du bus
crée déjà sans approbation, ou l'agent avec des textes qu'il rédige) et `m7_lire_matiere_chantier` (ce dont le modèle a
besoin pour rédiger). Les quatre autres sont ouverts à `admin` seulement.

| Déclaration ou garde | Pourquoi |
|---|---|
| `m7_decider_contenu` : T1, **N3** (le défaut), `roles_appareil = {"admin"}` | La décision d'approuver un contenu public est du propriétaire. N3 : la personne authentifiée qui agit tient lieu de validation au départ (ADR-0009 §4, T1.4-h), tracée par le socle (`approbations`, `motif_decision` de la validation au départ). En mode `ombre`, l'appel d'un agent attend dans la file. |
| **Le propriétaire, pas seulement `admin`** | Comme l'app d'approbation (plus bas), le rôle du jeton ne prouve pas qui est le propriétaire : l'outil exige que la PERSONNE porte `nathan_owner`. Un gestionnaire `admin` reçoit `REJ-HUMAIN-ROLE-INSUFFISANT`, et sa tentative est tracée par le socle (`resultat.accepte` faux). |
| Deux voies, jamais une troisième (patron M10) | (1) un appel d'appareil dont l'identité est confirmée en base ; (2) l'exécution d'une demande que le propriétaire vient d'approuver dans la file : depuis T4.15-d, le SOCLE dit qui a approuvé (`approbations.approbateur_en_cours`) et seul `nathan_owner` compte, même si le manifeste élargit la politique N3 ; `decider` rejoue les arguments exacts enregistrés, l'outil ne les compare plus. Un agent en mode `supervise` ou `autonome`, où un N3 s'exécute sans file, reçoit `REJ-HUMAIN-REQUIS` : il n'approuve jamais son propre contenu. |
| La décision porte l'empreinte du texte décidé ; le contrôle est rejoué | Approuver comme exporter refusent un texte qui n'est plus celui qui a été approuvé ou qui ne passe plus le contrôle en code (`REJ-CONTENU-MODIFIE-APRES-APPROBATION`, `REJ-TEXTE-NON-CONFORME`). Le contenu vient de la file de M7, jamais d'un argument. |
| `m7_exporter_paquet_manuel` : T1, **N2**, `admin` | Une tâche interne : la décision humaine est déjà prise. Il ne publie rien et n'appelle aucune API de plateforme : le paquet (texte, mots-clics, lien de suivi, médias « à flouter à la main », heure du profil, instructions) est remis à celui qui le demande. |
| `m7_enregistrer_retrait_consentement_marketing` : T1, **N2**, `admin` | Loi 25 : un retrait ne restreint que et doit prendre effet à l'instant, sans attendre une approbation. Aucun texte libre (canal, personne, heure). Il ne se lève pas : aucun outil ne le défait. L'employé et le vendeur relaient la demande du client à l'`admin`. Le STOP d'un client à M1 inscrit le même retrait par le bus (`m1.retrait_consentement`, T4.17-c) : c'est un consommateur de M7, sans outil ni rôle, dont le fait vient de M1 et non d'un argument ; il porte des `lead_id`, jamais un contact. |
| `m7_lister_contenus_chantier` : T0, `admin`, bornée | Le propriétaire lit le texte ENTIER avant de décider. Huit contenus au plus par appel et 4 500 caractères (`Capacites` tronque à 6 000) ; `suivant` donne le rang de la page suivante. |
| Aucune approbation de publication, jamais | Le contenu approuvé n'est pas publié : M7 n'a aucun outil de publication réelle (`m7_publier_post_social` est T3, refusé en écriture réelle). Le propriétaire publie à la main avec le paquet. |

### La saisie d'une facture fournisseur, par un humain (T4.15)

`m5_saisir_facture_fournisseur` est ouvert à `admin` et ne s'exécute que pour un HUMAIN identifié, comme les
écritures de M10, avec les mêmes deux voies : (1) un appel d'appareil dont l'identité est confirmée en base
(personne active, rôle `admin`) ; (2) l'exécution d'une demande qu'un humain (`finance` ou `nathan_owner`, actif et
portant ce rôle) vient d'approuver dans la file, aux arguments EXACTS enregistrés. Depuis T4.15-c, c'est le SOCLE qui dit
qui a approuvé (`approbations.approbateur_en_cours`) : voir plus bas. Tout le reste est refusé par l'outil
lui-même (`REJ-AP-HUMAIN-REQUIS`) : un appel d'agent dans un département en mode `supervise` ou `autonome`, où un N3
s'exécute sans file, ne saisit rien ; une demande seulement `en_attente` n'autorise rien. La facture porte `saisi_par`
et `voie`. Elle n'a qu'un statut, `SAISIE` : ni approuvée, ni payée. Le rapprochement PO, réception, facture est une
PROPOSITION recalculée à chaque lecture, jamais stockée ni appliquée.

Limites : une facture de PO est saisie contre un PO déjà reçu, au moins en partie (une facture SANS PO a son outil,
T4.15-c) ; la corriger ou l'annuler est un N4 (section suivante) ; l'unité des prix du livre de prix de M6 n'est pas
déclarée (GATE NATHAN), donc chaque montant attendu porte la réserve `REJ-AP-UNITE-PRIX-NON-CONFIRMEE`.

### Corriger, annuler et saisir sans PO (T4.15-c)

La facture d'origine n'est JAMAIS modifiée : corriger et annuler AJOUTENT une pièce au registre des comptes à payer
(chaînée, avec le motif, la personne, son rôle, la voie, l'avant et l'après), et l'état courant de la facture se relit de ses
pièces. Le rapprochement, les totaux, le doublon et le cash libre lisent cet état : une annulée ne compte plus, une corrigée
vaut sa correction.

| Déclaration ou garde | Pourquoi |
|---|---|
| `m5_corriger_facture_fournisseur`, `m5_annuler_facture_fournisseur` : T2, **N4**, `roles_appareil = {"admin"}` | Modifier une dépense saisie est une écriture finale (ADR-0009 §4). Le socle ne valide au départ que N3 au plus : depuis le téléphone de l'admin comme pour un agent, l'appel ATTEND dans la file du propriétaire (`ombre`, `supervise`) et ne s'exécute qu'après la décision de `finance` ou du propriétaire, aux arguments exacts. `admin` PROPOSE ; il ne décide pas. |
| `m5_saisir_facture_sans_po` : T1, **N3** (le défaut), `admin` | Comme la saisie d'une facture de PO : une écriture interne non finale, validée au départ par l'humain qui agit. La catégorie est de la liste fermée `configuration.categories_depense_sans_po` (`department.yaml`, GATE NATHAN) ; vide, elle dit « catégories à configurer ». |
| Deux voies, jamais une troisième | (1) un appel d'appareil dont l'identité est confirmée en base (personne active portant ce rôle) ; (2) l'exécution d'une demande qu'un humain vient d'approuver dans la file. Un appel d'agent qui n'a passé par aucune des deux (mode `supervise` ou `autonome` pour un N3 ; mode `autonome` pour un N4, où il s'exécute sans file) reçoit `REJ-AP-HUMAIN-REQUIS` : la file n'est pas la seule barrière. |
| **Le propriétaire ou la finance, pas seulement `admin`** (N4) | Le rôle du jeton ne dit pas qui est le propriétaire (un gestionnaire porte aussi `admin`) : par la voie directe, l'outil exige que la PERSONNE porte `nathan_owner` ou `finance`, les rôles de `department.yaml/approbations.n4` (un test lie le code au manifeste). Sinon `REJ-AP-APPROBATEUR-REQUIS`. La voie directe n'est jamais plus large que la file. |
| Le socle dit qui a approuvé (`approbations.approbateur_en_cours`) | `decider` pose l'identifiant de la demande qu'il exécute (`contexte.executer_demande_approuvee`) autour de l'outil ; l'outil demande, avec son propre nom et son département, qui a approuvé, et le socle lit la demande EN BASE : `en_cours`, de cet outil et de ce département, rôle ni d'agent ni de client (et, si l'outil le demande, dans sa liste), personne active portant encore ce rôle. La personne et le rôle viennent de la ligne que `decider` a réservée, jamais du contexte ni d'un argument. Une ligne `en_cours` écrite à la main ne vaut rien sans `decider` en cours d'exécution ; un pointeur contrefait non plus (demande `en_attente`, déjà décidée ou inconnue). Remplace la lecture de la table des approbations que M5, M1, M7 et M10 recopiaient : M5 l'appelle depuis T4.15-c, M1, M7 et M10 depuis T4.15-d, chacun avec sa propre liste de rôles (`admin` et `nathan_owner` pour M1 et M10, `nathan_owner` seul pour M7). Le socle ne compare pas les arguments, que les copies comparaient : `decider` rejoue les arguments exacts enregistrés et lui seul pose la demande en cours. |
| Motif obligatoire, pièce sans effet si rejouée | Une ligne, 300 caractères au plus. Rejouer la même correction (`REJ-AP-CORRECTION-SANS-CHANGEMENT`), la même annulation (`REJ-AP-FACTURE-DEJA-ANNULEE`) ou corriger une annulée (`REJ-AP-FACTURE-ANNULEE`) est refusé sans rien écrire. Un appel d'appareil rejoué avec la même clé rend la réponse enregistrée (idempotence du socle). |
| Aucun paiement | Annuler n'efface pas la dette (un PO reçu et non facturé redevient un « à payer attendu »). Aucune écriture aux mouvements : la garde AST couvre les trois outils (`conformite.verifier_aucun_decaissement`). |

L'heure de réception du serveur fait foi pour un appel d'appareil direct (la saisie sans PO) ; par la file, l'`horodatage`
enregistré avec la demande sert. Limites : la correction ne change ni le PO, ni le fournisseur, ni la catégorie (annuler puis
ressaisir) ; le cash libre suppose les crédits de taxes récupérables à 100 %, factures sans PO comprises (à valider par le CPA,
tout le carburant ne l'est pas) ; le fournisseur d'une facture sans PO, tapé à la main, se compare sans égard à la casse ni aux
espaces, pas aux variantes de nom.

### Les transferts à un humain de M1 (T4.5)

`m1_lire_transfert` et `m1_clore_transfert` sont ouverts à `admin` et à personne d'autre. `m1_transferer` et
`m1_escalader_plainte` ne sont ouverts à aucun appareil : c'est le jugement de l'agent dans la session d'un client (l'employé
qui signale une plainte du terrain, §9.3, est un autre outil, à faire). Le transfert lui-même n'a pas besoin d'un appareil : les
règles de M1 l'ouvrent à la réception du message (`attentes()` de M1, section « À voir » de l'app).

| Déclaration ou garde | Pourquoi |
|---|---|
| `m1_transferer`, `m1_escalader_plainte` : T1 mais **N2** | Ouvrir un transfert est une tâche interne : rien n'est externe, personne n'est engagé. En N3, le mode `ombre` mettrait la création de l'alerte d'une plainte en attente d'approbation, et le garde du core (N3+ exige une affaire liée à la session, ADR-0010) refuserait l'appel dans la session d'un client inconnu : la plainte serait perdue. Même choix que `m1_recevoir_message_canal`. |
| `m1_clore_transfert` : T1, **N3** (le défaut) | Écriture interne non finale. Un appel d'appareil `admin` s'exécute « au départ » (T1.4-h) avec sa trace ; un agent qui la propose attend une personne. |
| `m1_clore_transfert` refuse tout appel qui n'est pas une décision humaine | Sans elle, un agent viderait lui-même la file « À voir » de ce qu'il devrait faire lire. Deux voies seulement : identité d'appareil `admin` confirmée en base, ou exécution d'une demande qu'une personne vient d'approuver, dont le SOCLE dit l'approbateur (`approbations.approbateur_en_cours`, T4.15-d : demande de cet outil et de ce département, approbateur `admin` ou `nathan_owner` toujours actif ; `REJ-HUMAIN-REQUIS` sinon, même garde que `m10_clore_signal`). Un agent en `supervise` ou `autonome`, où un N3 s'exécute sans file, est donc refusé. |
| L'heure d'une clôture d'appareil est celle de réception du serveur | Jamais l'horloge de l'appareil ni l'argument `horodatage` (même patron que M10). |
| L'identité vient de `contexte.identite_appelante()`, relue en base | Jamais un argument : `additionalProperties: false` refuse `par` et `role`. |
| L'attente n'a ni contact ni texte du client | Les attentes sont des résumés (section « Pages d'attentes ») : le contexte se lit avec `m1_lire_transfert`, outil admin. La lecture est bornée pour rester sous les 6 000 caractères de `Capacites` (quatre messages couverts et quatre suivants au plus, 350 caractères chacun, résumé de 1 200 au plus ; le plus gros cas tient sous 6 000 : `test_outils_transfert.py`). |
| `employee` reçoit 403 sur la liste, la lecture et la clôture | `tool_out_of_scope` à la porte d'appareil (E2E `tests/e2e/test_plainte_urgence_appareil.py`). |

### Les deux outils d'approbation de l'app (T1.4-f, étape 6)

`m9_lister_demandes_approbation` et `m9_decider_demande_approbation` sont les seuls outils dont la portée
`admin` ne suffit pas : c'est la PERSONNE du jeton qui décide (`src/opsys/approbations_appareil.py`). Chaque
ligne dit ce qui est déclaré et pourquoi.

| Déclaration ou garde | Pourquoi |
|---|---|
| `roles_appareil = {"admin"}` sur les deux | §9.5 : l'admin est le profil qui voit les approbations. Ni `employee` ni `seller` : la file contient des prix, des factures, des bons de commande. |
| Hébergés par M9, pas par le socle | `roles_outils` et `opsys-metier verifier` ne lisent que les outils de département. Un outil commun `opsys_*` serait absent de `roles.json` (donc injoignable) et présent sur les dix serveurs à la fois (`Capacites` les liste tous). M9 lit déjà cette file (`m9_produire_briefing_matin`) et son mobile est « Admin/Nathan seulement » (§7). La logique reste au socle ; M9 ne décide rien. |
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
| La liste est bornée (`limite`, 4 600 caractères, attentes comprises : 1 500 au plus par page) | `Capacites` tronque au-delà de 6 000 caractères, et le téléphone ne lirait pas la suite. `reste` compte les demandes non montrées ; `attentes_reste` compte les attentes qui suivent la page. À titre de comparaison, `m9_produire_briefing_matin` n'est pas borné : mesuré en T1.5 avec des demandes N4 courtes, il tient à 22 décisions en attente (5 989 caractères) et dépasse 6 000 à 23 (un aperçu tronqué remplace alors la réponse). |
| Les attentes se lisent par pages : `decalage_attentes` (T1.5-e) | Au-delà d'environ trois attentes, les suivantes n'étaient que comptées : l'admin ne les lisait pas sur son téléphone. Le budget de 1 500 caractères n'est pas relevé (il garde la place des demandes sous la troncature) : la suite se demande. `decalage_attentes` est un **rang** (entier ≥ 0, 0 par défaut), jamais une personne : la portée `admin` et l'identité confirmée en base sont celles de la liste, et `additionalProperties: false` refuse tout autre paramètre. La réponse dit `attentes_decalage` (le rang lu) et `attentes_suivant` (le rang à demander, `null` quand rien ne suit). Voir « Pages d'attentes » ci-dessous. |

Décision attendue de Nathan : un `admin` qui n'est pas le propriétaire (un gestionnaire) ne décide rien depuis
l'app, même un N3 que le manifeste de son département lui laisse décider à la console (M4, M6). Le laisser
décider N3 depuis l'app est un changement de `approbations_appareil._lecture_seule` et un amendement d'ADR-0009 §4.

#### Pages d'attentes (T1.5-e)

- **Ordre stable.** `approbations.ordre_attente` : `depuis` croissant (le plus ancien d'abord, comparé comme texte,
  comme le briefing du matin de M9), puis `id`, `departement`, `type`. L'ordre est total : il ne dépend ni de
  l'ordre des départements ni de celui de leurs listes. Deux lectures du même état rendent la même suite ; la
  console (`file_proprietaire`) et l'app le partagent.
- **Une page.** Les attentes du rang `decalage_attentes` jusqu'à `BUDGET_ATTENTES` (1 500 caractères) ; une
  attente au moins, sinon la lecture ne progresserait jamais. Les demandes gardent leur budget (4 600 caractères
  pour la liste entière) : chaque page reste sous les 6 000 de `Capacites` (mesuré : E2E, huit attentes réelles,
  pages de 3, 3 et 2 attentes, 1 257 / 1 257 / 812 caractères d'attentes, jamais tronquées).
- **La liste des demandes accompagne chaque page** (mêmes règles, même `limite`), pour que la réponse garde une
  seule forme. Ses éléments peuvent différer d'une page à l'autre (la place qu'y laissent les attentes varie) :
  l'écran garde ceux de la première page et n'en recolle que les attentes.
- **Rang hors plage.** Au-delà de la fin : page vide, `attentes_suivant: null`, `attentes_reste: 0`, jamais une
  erreur ni une attente inventée. Seul un rang qui n'est pas un entier ≥ 0 est refusé (verdict
  `decalage_invalide`) ; un type faux (texte, décimal, booléen) l'est déjà par le schéma (`arguments_invalides`).
- **Pas de curseur.** Un rang glisse si une attente apparaît ou est traitée entre deux pages : elle peut manquer ou
  se répéter. Le signal est `total_attentes`, qui change. L'écran ne recolle une page que si elle est celle qu'il
  a demandée, que le total est inchangé et qu'aucune de ses attentes n'est déjà affichée ; sinon il relit depuis
  le début et le dit (MOBILE.md). Une attente nouvelle est presque toujours la plus récente, donc en fin de liste :
  elle ne déplace rien.

### L'envoi d'un devis par approbation N4 (T4.7)

`m3_demander_envoi_devis` (M3.14) est **T2, N4**, ouvert à `seller` et à `admin`. Le vendeur (ou le gestionnaire)
DEMANDE ; le propriétaire décide. Le devis approuvé ne part pas seul : le statut `envoye` dit « approuvé pour envoi »,
la livraison au client est à M1 (T2.1-c) et n'existe pas encore. Aucun outil d'envoi réel.

| Déclaration ou garde | Pourquoi |
|---|---|
| **N4 : `Capacites` ne l'exécute jamais sur un appel d'appareil ni d'agent** | À la demande (mode `ombre` ou `supervise`), le socle enregistre une demande `en_attente` au niveau N4 figé (`approbations.creer_demande`) et répond `en_attente_approbation`. Le devis reste `brouillon`. N4 dépasse le plafond de la validation humaine au départ (N3) : le vendeur ne se valide pas lui-même. |
| **Qui décide : `nathan_owner`, et lui seul** | `department.yaml/approbations.n4 = [nathan_owner]` (aussi le défaut du socle). `approbations.decider` refuse un gestionnaire (`admin` + `manager`), la finance et le vendeur (`aucun rôle autorisé pour N4`, rien exécuté, la demande reste en attente). L'app (`m9_decider_demande_approbation`) exige en plus que la PERSONNE porte `nathan_owner` : un `admin` qui ne l'est pas reçoit `reserve_au_proprietaire`, et lit la file sans les arguments. |
| **L'attente porte les motifs** | M3 déclare une `attentes()` : une entrée `revue_envoi_devis` par demande en attente, de même `id` que la demande, dont le `resume` est la revue du devis d'AUJOURD'HUI (`revue_devis.py`) : l'ALERTE ROUGE d'abord, les autres motifs, puis le nombre de critères non évaluables. Tout `admin` la lit (comme les autres attentes) ; elle ne se décide pas, la demande oui. Bornée à 240 caractères, ce que l'app montre : ce qui ne tient pas est compté (`+ 2 autres`). |
| **La revue ne devine rien** | Trois sources citées par chaque motif : le devis (`prix_total`, `taux_marge`), `contexte_revue` (faits recopiés de `m3_estimer_projet` ou connus d'une personne) et les seuils de `department.yaml/configuration/revue_devis`, VIDES à dessein. Un seuil vide ou un fait absent rend le critère « non évaluable » (« seuil à configurer : marge_minimale »), jamais « rien à signaler ». Le prix sous le minimum rentable et l'alerte de plancher de l'estimation sont ROUGES ; une alerte rouge n'empêche pas l'envoi, le propriétaire la lit et décide (§7 M3.11). |
| **L'outil refuse de s'exécuter hors d'une décision** | Le mode `autonome` ne met que N5 en file : un N4 s'y exécuterait sans humain. `m3_demander_envoi_devis` relit donc la demande `en_cours` que `approbations.decider` vient de réserver (mêmes arguments, approbateur `nathan_owner` actif ; M3 garde sa propre lecture de la table, que T4.15-e remplacera par `approbations.approbateur_en_cours` comme M1, M5, M7 et M10) et rend `REJ-ENVOI-SANS-APPROBATION` sinon. |
| **Une fois, à l'instant du socle** | Approuvé, le devis passe `envoye` à `decide_le` (l'horloge du socle, jamais une heure fournie) avec la personne, son rôle et la synthèse de la revue (codes seulement) ; `m3.devis_envoye` est publié dans la même transaction (`m3-devis-envoye-<devis_id>`, sans coût, marge ni prix). Un devis déjà `envoye` est un rejeu : rien n'est écrit ni republié (`deja_envoye`). Un devis `accepte` est refusé (transition illégale). |
| **Le rejeu de l'appareil** | Même clé d'idempotence, même demande (`rejoue: true`) : aucune seconde demande. Décider deux fois la même demande : `deja_decidee`. |

**Ce que cette section laisse ouvert.** L'outil ne s'exécute qu'à la décision, sans l'identité de l'appareil du
vendeur : le socle ne peut donc pas y filtrer par propriétaire du lead (T1.4-k2). Un vendeur peut demander l'envoi
du devis d'un lead qui n'est pas le sien ; il n'apprend rien (aucune lecture, aucune existence révélée) et le
propriétaire lit le devis, la revue et les faits avant d'approuver. Il faudrait un contrôle à la demande dans le socle
(`Outil` avec un garde d'appel), qui n'existe pas.

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
| `m7_proposer_contenus_chantier`, `m7_lire_matiere_chantier` | Brouillons N1 nés du bus (le consommateur de M7 les crée déjà) et matière du modèle qui rédige : le propriétaire lit et décide (`m7_lister_contenus_chantier`, `m7_decider_contenu`), il ne fait pas écrire de textes depuis son téléphone. |

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
| **Appel d'appareil, `employee`** | Seulement les interventions qui lui sont ASSIGNÉES (à lui, ou à une ÉQUIPE dont il est membre selon le profil de l'entreprise, T4.12 : voir plus bas), et seulement sous son propre identifiant. Autre intervention ou intervention inconnue : le même refus `REJ-INTERVENTION-NON-ASSIGNEE` (rien ne dit à un employé quelles interventions existent). `technicien_id` différent de la personne : `REJ-IDENTITE-FOURNIE-DIFFERENTE`, jamais préféré ni remplacé en silence. |
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
| `m4_verifier_preparation` | hors portée (T4.10-b) ; refusé aussi dans l'outil (`REJ-IDENTITE-APPAREIL-INVALIDE`) | lecture seule, aucune personne à nommer |
| `m4_verifier_meteo_creneau` | hors portée (T4.13) ; refusé aussi dans l'outil (`REJ-IDENTITE-APPAREIL-INVALIDE`) | lecture seule ; une prévision saisie à la main (`previsions_saisies.saisi_par`) nomme sa propre personne, sinon `REJ-IDENTITE-FOURNIE-DIFFERENTE` |
| `m4_deposer_fichier`, `m4_etat_fichier` | identité confirmée seulement | idem |
| `m6_declarer_materiaux_utilises` | le WCT doit porter son `technicien_id` | tous les WCT |

### Les équipes du profil de l'entreprise (T4.12)

La cédule par tournées assigne une intervention à une ÉQUIPE : le `technicien_id` de l'assignation est alors
l'identifiant de l'équipe (`opsys.equipes`, clé `equipes` de `entreprise.yaml`), pas celui d'une personne. Un
`employee` agit aussi sur l'intervention assignée à une équipe DONT IL EST MEMBRE (`acces.Acteur.equipes`, lues dans
le profil par l'adaptateur, jamais dans un argument) :

- il la voit (`m4_lister_interventions`, `m4_statut_intervention`) et peut partir (`m4_demarrer_route`), toujours
  sous son propre `technicien_id` : l'identifiant de l'équipe n'est jamais un `technicien_id` admis pour lui ;
- quand il part, le technicien de l'intervention devient la personne qui part (`etats.transitionner`) : les autres
  membres n'y ont plus accès, comme pour une assignation directe ; l'`admin` dispatche pour les autres, inchangé ;
- profil absent ou invalide : aucune équipe, donc aucun accès par équipe (fail-closed, jamais davantage de droits) ;
  un retrait du profil retire l'accès à la lecture suivante ;
- le profil refuse qu'une personne soit membre de deux équipes et qu'une équipe porte l'identifiant d'une personne
  qui n'en est pas membre (`opsys-metier equipes declarer` vérifie aussi que chaque membre est une personne OPSYS existante
  et active) : aucune équipe ne donne accès à quelqu'un qui n'en est pas membre ;
- aucune donnée de ressources humaines, de santé ni d'évaluation dans le profil : le schéma est fermé.

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

**La règle écrite : rôle -> droit de voir solde, argent disponible, cash libre et taux.** Fermée par défaut (un
rôle absent de la table ne voit rien). T4.16 : le cash libre réel (`cash_libre`, `argent_disponible_note`,
`mention`) est une clé sœur de l'état financier : il suit exactement la même vue, `argent_disponible` n'est jamais
affiché sans lui, et `m5_lire_echeances_fiscales` applique la même règle (sans droit : les dates, jamais un montant).

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
  registre de production, pas un historique fourni (T4.16 : avec un historique fourni, le solde et les
  réserves viennent de lui, les taxes, les comptes à payer et les déclarations du propriétaire viennent
  toujours des registres et du manifeste). À fermer quand l'app appellera l'outil.
- **`m5_enregistrer_mouvement(source)`, `m5_creer_facture_brouillon(client_id...)`** : étiquettes ou
  références de l'appelant, mais aucun appareil (T3, ou cascade §6).

### Ce qui reste

- **M2, M3** : faits (T1.4-k2, section suivante). `auteur` vient de la personne authentifiée, un vendeur ne
  voit que ses leads et que les devis de ses leads.
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
- **Sortie de `a_planifier` (T4.12).** `m4_appliquer_cedule` (N3) fait aussi passer `a_planifier -> planifiee` chaque
  intervention que le plan place, avec un verdict de préparation « prêt » recalculé à l'application (la porte
  d'empreinte de T4.10 : `etats.transitionner`). Le matériel se lit depuis T4.14-b (`m6.materiel_pret`) et la météo depuis
  T4.13 (règles du service dans le profil météo) : une intervention n'est « prête » que si M6 la dit prête et si le
  propriétaire a décidé ses règles météo pour son service ; sinon la porte reste fermée et le refus dit ce qui manque.
  `m4_planifier_intervention` refuse le devis dont l'intervention existe déjà (un devis n'a qu'une intervention).
  Décision à prendre par le propriétaire si l'exploitation ne peut pas attendre un volet : une attestation humaine
  nommée et motivée d'un volet non vérifiable (aucune n'existe).
- **Météo des créneaux (T4.13).** `m4_verifier_meteo_creneau` est T0 : il ne juge que la météo d'un plan déjà proposé et
  ne fait que proposer (un report `m4_signaler_report`, une nouvelle proposition de cédule dont l'aperçu est calculé sur
  une copie du registre) ; rien n'est appliqué sans un geste N3 de l'admin. Le fournisseur de prévisions est fermé par
  défaut : sans clé `fournisseur` dans le profil météo, aucune requête ne part et la prévision se saisit à la main
  (`previsions_saisies`). Open-Meteo (API gratuite non commerciale) n'est ouvrable qu'avec un forfait commercial déclaré et
  une clé d'API dans l'environnement : décision du propriétaire (GATE NATHAN). Seule la position générale d'un chantier
  (dixième de degré) quitte le serveur. La réponse d'un appareil est bornée (6 000 caractères) : elle est résumée
  (`detail_reduit`), puis refusée avec la consigne `jours`, jamais tronquée. Un plan périmé pour une intervention (un
  autre plan appliqué la tient) ne compte ni dans le statut, ni dans les reports.
  Les surcharges d'arguments de `m4_proposer_cedule` sont tracées (`provenance`) mais permises : le profil reste juge de
  l'équipe qui reçoit une intervention sortant de `a_planifier` (`REJ-TOURNEES-PLAN-INVALIDE` sinon).
- **Voie des agents.** Le secret partagé de la passerelle garde l'accès complet aux outils (documenté,
  voulu) : seule la voie du jeton d'appareil passe par `roles.json`, donc par ces contrôles.
- **Approbation différée.** Un appel d'appareil dont l'identité n'est pas valide part en file (T1.4-h) ; une
  fois approuvé, l'outil s'exécute sans identité d'appareil, donc sans ce contrôle : c'est la décision du
  propriétaire qui le couvre.

## Les leads de M2 et les devis de M3 (T1.4-k2)

Avant T1.4-k2, `m2_enregistrer_interaction(auteur)` prenait l'auteur de l'appelant : un vendeur pouvait
signer une note du nom d'un collègue, ou de l'admin. Et les six outils M2 ouverts au vendeur, comme
`m3_lire_devis` et `m3_generer_soumission_brouillon`, lui montraient les leads et les devis de tous les
vendeurs. Même patron que M4 et M5 : la personne vient du jeton (`contexte.identite_appelante()`, jamais les
arguments), confirmée en base à chaque appel (`approbations.signataire_valide`, T1.4-h), et chaque refus
précède toute écriture.

### La propriété d'un lead existait déjà : c'est `owner`

`owner` est exigé par la transition `nouveau -> qualifie` (`REJ-OWNER-ABSENT` sinon), consigné dans son maillon,
et déjà lu par la readiness et le digest. **Aucun maillon d'assignation n'est ajouté**, et le propriétaire n'est
jamais déduit d'un autre champ (ni l'`auteur` des notes, ni le statut, ni l'ordre d'ingestion) :
`m2_revenue_crm.acces.proprietaire_du_lead` relit ce seul maillon (le dernier `qualifie` qui porte un owner).

- **Le lien personne -> propriétaire est le même que pour M4** : `owner` EST l'identifiant de la personne OPSYS
  (`opsys.identite`, immuable). Pas de table de correspondance.
- **Un lead `nouveau` n'est à personne** : invisible à un vendeur. C'est l'admin (ou l'agent, sur décision
  humaine, SOUL de M2) qui l'assigne en le qualifiant. Un vendeur ne « prend » pas un lead.
- **Depuis un appareil** (l'admin), `owner` doit être l'identifiant d'une personne ACTIVE qui peut posséder un lead
  (rôle `seller` ou `admin`) : sinon `REJ-OWNER-INCONNU`, avant toute écriture. Le propriétaire n'est consigné
  qu'une fois, un `owner` saisi de travers rendrait le lead invisible à tous les vendeurs, sans recours.
- **Sans identité d'appareil** (agent, console), `owner` reste du texte libre, comme avant : voulu et documenté.
  Un `owner` qui n'est l'identifiant d'aucune personne n'appartient à aucun vendeur (fail-closed) ; les
  consignes de M2 disent de passer l'identifiant, pas le nom.
- **La qualification publie `m2.lead_assigne`** (`{lead_id, proprietaire, horodatage_assignation}`), dans la même
  transaction, avec l'`evenement_id` déterministe `m2-lead-assigne-<lead_id>` (un lead ne se qualifie qu'une
  fois). C'est ce fait que M3 relit. **Depuis T1.4-m**, le propriétaire courant est celui de la DERNIÈRE assignation
  (la qualification, puis les réassignations), lue en un seul endroit (`assignation.proprietaires`) : voir
  « La réassignation d'un lead » plus bas.

### M2 : qui peut quoi (appel d'appareil)

| Appelant | Règle |
|---|---|
| **`seller`** | Seulement les leads dont il est propriétaire. Un lead d'un autre, un lead sans propriétaire et un lead inconnu donnent le MÊME refus, `REJ-LEAD-NON-ASSIGNE` (rien ne dit à un vendeur quels leads existent). Client 360 : seulement ses opportunités (statut, prochaine action, interactions) ; un client dont aucune n'est à lui donne le même refus qu'un client inconnu. |
| **`admin`** | Tous les leads. Il assigne en qualifiant (`owner` validé). |
| **Sans identité d'appareil** (agent, console, consommateurs d'événements) | Comportement d'avant, aucun contrôle de personne (« Voie des agents »). |
| **Identité non confirmée en base**, ou rôle hors portée de l'outil (employé, ou vendeur sur un outil d'admin) | `REJ-IDENTITE-APPAREIL-INVALIDE`, avant toute lecture ou écriture. Hors transaction (aucune base jointe) : le même refus. |

| Outil (appel d'appareil) | `seller` | `admin` |
|---|---|---|
| `m2_transitionner_statut`, `m2_trouver_client_de_lead`, `m2_evaluer_readiness`, `m2_suggerer_prochaine_action` | son lead | tous |
| `m2_lister_leads` (T4.6) | la liste de ses leads ; un lead d'un autre, un lead sans propriétaire et un lead inconnu ne sont ni listés ni comptés ni cités (aucun refus à lire : ils n'existent pas pour lui) ; `past_customer` ne lit que ses opportunités du client | tous les leads (pipeline, leads chauds) |
| `m2_enregistrer_interaction` | son lead, `auteur` = sa personne | tous les leads, `auteur` = sa personne |
| `m2_obtenir_client_360` | ses opportunités du client | toutes |
| `m2_produire_digest`, `m2_detecter_doublons`, `m2_signaler_doublon`, `m2_arbitrer_doublon` | hors portée : refusés aussi dans l'outil | oui |
| `m2_reassigner_lead`, `m2_republier_assignations` (T1.4-m) | hors portée : refusés aussi dans l'outil (`REJ-IDENTITE-APPAREIL-INVALIDE`) | oui (la réassignation exige en plus une décision humaine) |

Ordre des contrôles : identité confirmée et rôle dans la portée, puis `auteur`, puis propriété du lead, puis
`owner` (qualification seulement), toujours AVANT toute écriture. Chaque refus est prouvé sans écriture (toutes
les tables de la base comparées avant et après).

### La liste des leads et les segments (T4.6)

`m2_lister_leads` est la lecture du pipeline : `seller` (ses leads) et `admin` (tous). Même contrôle que le reste
de M2, même identité confirmée en base à chaque appel, aucun paramètre qui désigne une personne. Ce qu'il ajoute :

- **Un lead invisible n'existe pas pour le vendeur.** Il n'est ni listé, ni compté dans `total`, ni cité dans une
  règle. Il n'y a donc pas de refus à lire : la page d'un vendeur sans lead est vide. Un lead `nouveau` (sans
  propriétaire) ou dont `owner` est un nom libre n'est à aucun vendeur.
- **`past_customer` respecte cette portée** : le segment ne lit que les opportunités du client que l'appelant voit
  (comme le Client 360). Pour un même lead, l'admin peut donc voir `past_customer` (un autre vendeur a vendu ce
  client) là où le vendeur ne le voit pas : voulu, fail-closed.
- **Ordre stable, documenté** (`ordre` dans chaque page) : le plus ancien lead ingéré d'abord (instants comparés en
  UTC), puis `lead_id`. Un lead qui reçoit une note ne change pas de rang ; un lead ingéré pendant la lecture
  s'ajoute à la fin.
- **Pages** : `decalage` (rang du premier lead) et `suivant`, comme `attentes_decalage` (T1.5-e) et
  `m9_lire_suite_briefing`. La page tient sous la limite de sortie du socle (6 000 caractères, mesurés par le code) et
  porte toujours un lead au moins. Un décalage au-delà de la fin rend une page vide, jamais une erreur.
- **Aucun montant, aucun contact.** `high_value_customer` est non calculable : M2 n'a pas les montants de M3 ni de M5.
- **Les seuils** des segments `dormant_lead` et `quote_stale` sont dans `department.yaml`
  (`configuration.segments`), vides : « seuil à configurer ». Un filtre sur un segment non calculable est refusé
  (`REJ-SEGMENT-NON-CALCULABLE`, avec ce qui manque), jamais une liste vide.
- **`horodatage`** est un argument (l'instant de référence des deux segments datés) : c'est M2, pas l'appareil, qui
  décide quoi en faire, et un appareil qui le falsifie ne change que SA propre vue.

Limites : l'ordre est un rang, pas un curseur (un lead qui change de statut ou de segment entre deux pages d'un
filtre peut manquer ou se répéter : l'appelant relit depuis 0) ; le propriétaire lu est le courant : celui de la
qualification, ou de la dernière réassignation (T1.4-m).

### `auteur` d'une interaction

Pour tout appel d'appareil, **`admin` compris** (contrairement à `technicien_id` de M4 : l'admin qui dispatche
agit pour autrui, mais il n'écrit pas une note au nom d'un vendeur) :

| `auteur` fourni | Effet |
|---|---|
| absent ou nul | vaut la personne authentifiée |
| égal à la personne (aux espaces près) | honoré |
| différent (un collègue, un nom, `system:m3`, vide) | `REJ-IDENTITE-FOURNIE-DIFFERENTE`, jamais remplacé en silence |

Sans identité d'appareil : `auteur` est celui de l'appelant et reste obligatoire. Son absence était un refus de
schéma (`arguments_invalides`) ; c'est maintenant un verdict nommé, `REJ-CHAMP-VIDE`, comme pour M5
(`REJ-AUTORISE-COUTS-REQUIS`). Aucune personne ne peut imiter une écriture système : un identifiant OPSYS ne
contient pas de « : ».

### M3 : les devis des leads du vendeur

M3 ne reçoit jamais le propriétaire d'un lead de l'appelant, et n'en garde aucune copie : il le relit **à la
source du bus** (`evenements.charge_publiee("m2.lead_assigne", "m2-lead-assigne-<lead_id>")`), comme M6 relit le
WCT de M4 (T1.4-i), sans importer M2 (décision #109).

| Appelant | `m3_lire_devis`, `m3_generer_soumission_brouillon` |
|---|---|
| **`seller`** | Seulement le devis dont le `lead_id` a pour propriétaire sa personne. Le devis d'un autre, celui d'un lead sans propriétaire connu et un devis inconnu donnent le MÊME refus, `REJ-DEVIS-INTROUVABLE` (même code, même détail). |
| **`admin`** | Tous les devis. |
| **`employee`** | Jamais de coût, de marge ni de prix (T2.3-d, inchangé) : `m3_lire_devis` rend la vue employé (`role=interne` : `REJ-ROLE-ELARGI`) ; le brouillon de soumission, qui porte les prix, lui est refusé (`REJ-IDENTITE-APPAREIL-INVALIDE`). Aucune portée du core sur ces outils. |
| **Sans identité d'appareil** | Comme avant, aucun filtre. |

`m3_lire_devis` garde le `role` restreignable de T2.3-c : il ne peut que restreindre. Le filtre par propriétaire
s'ajoute, il ne remplace pas la vue. Un vendeur qui se restreint à `employe` sur son lead obtient la vue sans prix.

### La réassignation d'un lead (T1.4-m)

Avant T1.4-m, `owner` n'était consigné qu'une fois, à la qualification : un vendeur qui part, ou un `owner` saisi de
travers, laissait le lead sans recours. `m2_reassigner_lead(lead_id, nouveau_proprietaire, motif, horodatage)` le confie à
un autre vendeur. T1, **N3**, `admin` seulement. C'est une décision HUMAINE, du même patron que la clôture d'un
transfert de M1, la saisie d'une facture fournisseur de M5 et les écritures humaines de M10 : elle décide qui voit le
dossier et les devis d'un client.

| Règle | Détail |
|---|---|
| Décideur | Deux voies, jamais une troisième : (1) un appel d'appareil dont l'identité est CONFIRMÉE en base à l'instant même (personne active portant encore le rôle `admin`) ; (2) l'exécution d'une demande qu'une personne (`admin` ou `nathan_owner`, active et portant ce rôle) vient d'approuver, aux arguments EXACTS enregistrés. Tout le reste est `REJ-HUMAIN-REQUIS` : un appel d'agent dans un département en mode `supervise` ou `autonome`, où un N3 s'exécute sans file, ne réassigne rien ; une demande seulement `en_attente` n'autorise rien. Un vendeur ou un employé confirmé en base reçoit `REJ-IDENTITE-APPAREIL-INVALIDE`. La politique de M2 ne déclare pas de rôles pour N3 : le défaut le plus restrictif s'applique, seul `nathan_owner` approuve la proposition d'un agent (comme M1 et M10). |
| Pourquoi N3 (ADR-0009 §4) | Écriture interne non finale : le maillon de qualification reste, une nouvelle réassignation défait la précédente, rien n'est supprimé. Sans argent, sans prix, sans message au client. Pas N2 : une tâche interne automatique laisserait un agent décider qui voit un dossier de client. Pas N4 : aucun engagement externe. Un appel d'appareil `admin` s'exécute « au départ » (T1.4-h) avec sa trace (`approbations` : N3, `executee`, `decide_par`) ; un agent propose et attend. |
| Motif | Obligatoire, de 10 à 500 caractères (espaces de tête et de queue retirés) : `REJ-MOTIF-ABSENT` s'il manque, `REJ-MOTIF-INVALIDE` s'il est hors bornes. Il est consigné au maillon, pas au bus. |
| Cible | L'identifiant OPSYS d'une personne ACTIVE de rôle `seller`, sinon `REJ-OWNER-INCONNU` : ni un employé, ni un admin ou un propriétaire qui n'est pas vendeur (il voit déjà tous les leads), ni un nom, ni une personne désactivée. Une personne `admin` ET `seller` est acceptée. |
| Lead | Connu (`REJ-LEAD-INCONNU`) et qui a déjà un propriétaire (`REJ-OWNER-ABSENT` : un lead `nouveau` s'assigne en le qualifiant). Tous les statuts, `perdu` compris (le dossier clos suit son vendeur, ses devis aussi). Un `owner` en texte libre, saisi par un agent, se réassigne : c'est le recours qui manquait. Un propriétaire identique est `REJ-PROPRIETAIRE-INCHANGE`. |
| Ordre des contrôles | Décideur, cible, horodatage, motif, lead connu, lead avec un propriétaire, propriétaire différent : tous AVANT l'unique écriture. Chaque refus est prouvé sans aucune écriture. `additionalProperties: false` refuse `par`, `role`, `decide_par`, `voie`, `rang` : la personne vient du jeton, jamais des arguments. |
| Heure | Pour un appel d'appareil, l'heure de RÉCEPTION du serveur fait foi, jamais l'horloge de l'appareil ni l'argument `horodatage` (même patron que M1, M5 et M10). |
| Trace | Un maillon `reassignation` s'ajoute au registre, append-only : `rang`, `proprietaire_precedent`, `nouveau_proprietaire`, `motif`, `decide_par`, `decide_role`, `voie` (`appareil` ou `approbation`). Le maillon de qualification n'est jamais modifié. |
| Lecture unique | Le propriétaire courant est celui de la DERNIÈRE assignation, lue en un seul endroit (`assignation.proprietaires`). `acces.py` (qui voit quoi), la readiness (l'`owner` du marqueur) et le digest s'y alignent : un lead réassigné n'a jamais deux propriétaires selon l'endroit où on le lit. |
| Rejeu | Même clé d'idempotence : la réponse est rejouée, aucune écriture (E2E : l'empreinte de l'état ne change pas). Autre clé, même cible : `REJ-PROPRIETAIRE-INCHANGE`, sans écriture. |

**Le fait `m2.lead_assigne` est versionné, de façon additive** (`src/opsys/evenements/catalogue/m2.lead_assigne.json` ;
toute charge valide avant reste valide) :

| Rang | Quand | Identifiant | Charge |
|---|---|---|---|
| 1 | la qualification (T1.4-k2) | `m2-lead-assigne-<lead_id>` | `{lead_id, proprietaire, horodatage_assignation}`, sans `rang` : octet pour octet ce qui se publie depuis T1.4-k2 |
| n >= 2 | la n-1e réassignation, dans la MÊME transaction que son maillon | `m2-lead-reassigne-<n>-<lead_id>` | les trois mêmes clés, plus `rang` (>= 2) et `proprietaire_precedent` |

Les deux familles d'identifiants ne peuvent pas se confondre, quel que soit le `lead_id` (une chaîne libre) : `m2-lead-assigne-`
et `m2-lead-reassigne-` diffèrent avant tout `lead_id`, et le rang, en chiffres, précède le premier tiret. Le propriétaire
COURANT est celui du plus grand rang publié. Un fait déjà publié ne change jamais.

**Ce que M3 fait (intégré avec ce changement).** M3 (`_proprietaire_du_lead`, `m3_estimation/outils.py`) lit le rang 1,
puis les rangs 2, 3... jusqu'au premier absent (un rang 1 absent n'arrête pas la lecture), toujours sans importer M2
(#109). Un fait n'est retenu que s'il nomme le bon lead et le rang de son identifiant. Après une réassignation, le devis
suit donc le lead : le nouveau vendeur le voit, l'ancien non. Preuve : `m03-estimation/tests/test_proprietaire_reassigne.py`
(lecture par rang) et `tests/test_reassignation_suit_m3.py` (chaîne réelle M2, bus, M3).

### La republication du fait de propriété (T1.4-m)

`m2_republier_assignations()` (T1, N3, `admin`, sans argument) ferme le trou que T1.4-k2 avait laissé : un lead qualifié
avant T1.4-k2 n'a jamais publié `m2.lead_assigne`, donc M3 ne reconnaît pas son vendeur et lui refuse ses devis
(fail-closed), alors que M2 lui montre le lead. L'outil parcourt les assignations du registre (la source de vérité) et remet
au bus, pour chacune dont le fait est absent, le MÊME identifiant et la MÊME charge que la publication d'origine
(`assignation.fait_assigne`, l'unique construction de la charge).

- **Idempotent.** Un fait déjà publié est compté (`faits_deja_publies`) et laissé tel quel ; un second appel ne publie rien.
  Il couvre aussi un lead réassigné avant la republication : son rang 1 manquant est publié, son rang 2 existe déjà.
- **Il n'invente ni ne corrige rien.** Le propriétaire est celui du registre, tel quel : un `owner` en texte libre reste un
  texte libre, qui n'est à aucun vendeur (`m2_reassigner_lead` est le recours). Il n'écrit jamais au registre.
- **Refusé hors stockage durable** (`REJ-BUS-INDISPONIBLE`) : il n'y a alors aucun bus, et un succès silencieux serait un
  faux vert. Réservé à `admin` (aussi dans l'outil) ; un agent peut le proposer (validation au départ en `ombre`).
- **Sortie bornée** : les faits sont comptés (`faits_republies`, `faits_deja_publies`), et la réponse cite au plus 50 leads
  republiés (`leads_tronques`), sous la limite de sortie du socle.
- **À la mise en service** : le lancer une fois, depuis l'app admin, avant d'ouvrir les devis aux vendeurs. Preuve de bout en
  bout : `tests/test_republication_devis_vendeur.py` (le vendeur qui se voyait refuser les devis de ses leads d'avant les lit),
  `tests/e2e/test_reassignation_lead_appareil.py` (la porte d'appareil : 403 pour l'employé et le vendeur, rejeu sans effet).

Limites de T1.4-m : un lead par appel (aucune réassignation en lot) ; aucun message n'est envoyé à l'ancien ni au nouveau
vendeur ; désactiver une personne ne réassigne pas ses leads (ils restent à elle, donc invisibles à tout vendeur actif : c'est
l'admin qui les réassigne, un à un) ; une réassignation approuvée après coup s'exécute sans identité d'appareil, la décision de
l'approbateur la couvre ; un devis déjà envoyé au client ne change pas (M3 n'est pas contacté).

### Ce que T1.4-k2 laisse ouvert (M2 et M3)

- **Réassignation : faite (T1.4-m, plus haut).** `owner` reste consigné à la qualification, mais un maillon `reassignation`
  et un fait de rang 2 et plus confient le lead à un autre vendeur ; la dépendance de M3 y est dite.
- **Leads qualifiés avant T1.4-k2 : republication faite (T1.4-m, plus haut).** Ces leads n'avaient pas de fait
  `m2.lead_assigne` : M2 les montrait à leur vendeur, mais M3 ne les reconnaissait pas (fail-closed) et lui refusait ses
  devis. `m2_republier_assignations` les remet au bus ; à lancer une fois à la mise en service. Un `owner` en texte libre
  (un nom) reste à aucun vendeur : `m2_reassigner_lead` le confie à un vendeur.
- **Un lead réouvert (affaire répétée, M2.14) naît `nouveau`**, donc sans propriétaire : l'admin doit l'assigner
  avant que le vendeur le voie.
- **`m2_ingerer_lead`, `m2_marquer_chantier_termine` et les consommateurs d'événements** n'ont pas de portée
  d'appareil : sans identité, sans contrôle de personne (voie des agents).
- **Approbation différée.** Un appel d'appareil dont l'identité n'est plus valide part en file (T1.4-h) ; une fois
  approuvé, l'outil s'exécute sans identité d'appareil, donc sans ces contrôles : la décision du propriétaire le
  couvre (même remarque que plus haut).
- **`_acteur_appareil` est copié dans M2, M4, M5 et M6** (`_declarant_appareil` dans M6), et M3 en a une variante
  (`_vue_projection_effective`, qui relit `identite.personne_active` au lieu de `signataire_valide`) : cinq copies
  d'une même règle, voulues tant que les départements n'importent rien les uns des autres (#109). Un seul helper du
  socle serait plus sûr.

## Limites de la portée par outil (T1.4-j)

La portée par outil dit QUEL outil, pas AU NOM DE QUI ni SUR QUOI : c'est le contrôle par personne qui le dit
(T1.4-k pour M4 et M6, T1.4-k2 pour M2, M3 et M5). Il a fermé les deux limites que ce document listait :
l'identité prise dans les arguments (`m4_pointer(technicien_id)`, `m4_lire_position_gps(accede_par)`,
`m4_definir_consentement_gps(technicien_id)`, `m2_enregistrer_interaction(auteur)`, `role` et `autorise_couts` de
M5) et la portée par instance (un employé voyait et agissait sur les interventions de tous, un vendeur sur les leads
et les devis de tous). Restent les limites de « Ce que T1.4-k2 laisse ouvert » et de « Ce qui reste » ci-dessus.

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
3. `opsys-metier verifier` et `pytest tests` doivent rester verts.

Demander à la relecture, pour tout outil ouvert à `employee` ou `seller` : lit-il des données d'un
autre, prend-il une identité, un prix, un rôle ou un chemin dans ses arguments, approuve-t-il, est-il
T3/N5 ?
