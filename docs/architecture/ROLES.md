# Portée des rôles d'appareil (T1.4-j)

> Complète [MOBILE.md](MOBILE.md) (appairage, jeton d'appareil), [IDEMPOTENCE.md](IDEMPOTENCE.md)
> §7 bis (le core refuse un outil hors portée) et [ADR-0009](../decisions/ADR-0009-socle-metier.md)
> §4-§5. Les profils viennent de la [définition produit](../produit/DEFINITION-PRODUIT.md) §9.
> La table ci-dessous est épinglée par `tests/test_portees_appareil.py`.

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

### `employee` (10 outils) : §9.3, le terrain

| Outil | Pourquoi |
|---|---|
| `m4_lister_interventions`, `m4_statut_intervention` | §9.3 « Cédule et route : chantiers du jour ». Lit toutes les interventions (voir *Limites*). |
| `m4_demarrer_route` | §9.3 Exécution : « en route ». |
| `m4_signaler_report` | Client absent, météo (§9.3 Exécution). Le motif `decision_admin` reste celui de l'admin. |
| `m4_pointer` | §9.3 « Punch (M4.4) : entrée et sortie ». |
| `m4_creer_demande_ecart` | §9.3 « demande de support ou de changement » ; l'admin l'arbitre. |
| `m4_deposer_fichier`, `m4_etat_fichier` | §9.2 « photos envoyées en arrière-plan », §9.3 photos avant/après, signature du client. |
| `m4_completer_intervention` | §9.7 « Terminer ». |
| `m6_declarer_materiaux_utilises` | §9.3 Inventaire et §9.7 étape 3 : formulaire des matériaux utilisés, « aucun coût affiché ». |

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

Les 10 outils de l'employé, les 9 du vendeur, et :

| Département | Outils réservés à l'admin | Pourquoi |
|---|---|---|
| M1 | `m1_produire_digest` | §9.5 M1 : appels manqués, rappels, messages urgents. |
| M2 | `m2_produire_digest`, `m2_detecter_doublons`, `m2_signaler_doublon`, `m2_arbitrer_doublon` | §9.5 M2 : pipeline, leads chauds, doublons. |
| M4 | `m4_lister_pending_review`, `m4_volumetrie_pending_review`, `m4_produire_digest` | §9.5 M4 : dispatch du jour, file de complétion. |
| M4 | `m4_resoudre_demande`, `m4_resoudre_revue_completion` (N4) | §9.5 M4 : approbation des complétions. |
| M4 | `m4_produire_brouillon_temps` | §9.3 : brouillon de feuille de temps envoyé à M5. |
| M4 | `m4_lire_position_gps` | §9.2 « accès admin journalisé » ; POLITIQUE-geolocalisation §6. |
| M4 | `m4_definir_consentement_gps` | Consigne un consentement ou son retrait « par écrit » (POLITIQUE-geolocalisation §4). |
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

## Limites : ce que la portée par outil ne règle pas

La portée dit QUEL outil, pas SUR QUOI ni AU NOM DE QUI. Restent ouverts :

1. **Identité prise dans les arguments.** `m4_pointer(technicien_id)`, `m2_enregistrer_interaction(auteur)`,
   `m4_lire_position_gps(accede_par)`, `m4_definir_consentement_gps(technicien_id)`,
   `m5_etat_tresorerie(role, autorise_couts)`, `m3_lire_devis(role)` : l'appelant les choisit.
   C'est pourquoi `employee` n'a ni `m3_lire_devis` ni le consentement GPS. À lier à la personne
   authentifiée (`opsys/personne`), suite de T1.4-k.
2. **Portée par instance.** Un employé voit les interventions de tous (`m4_lister_interventions`) et
   agit sur celle d'un autre ; un vendeur lit le Client 360 de tous les leads (T1.4-k pour les
   interventions ; rien encore pour le propriétaire d'un lead).
3. **Voie des agents.** Le secret partagé de la passerelle garde l'accès complet aux outils
   (documenté, voulu) : seule la voie du jeton d'appareil passe par `roles.json`.

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
