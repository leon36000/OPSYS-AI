# M8-analytics

Analytics — vérité chiffrée, XmR, le LLM ne calcule jamais.

Statut : département OPSYS complet (manifeste, SOUL, skill, outils d'agent) sur le modèle de
M3-estimation, mode `ombre`. Les six stories de domaine S001-S006 du PRD sont livrées et
vertes : contrats gelés, validation d'entrée, dictionnaire de métriques (avec garde de
devise CAD), registre append-only hash-chaîné, couche sémantique, détection XmR, rapports
filtrés par rôle, conformité statique et digest quotidien.

- `department.yaml` — manifeste (`m8_analytics.outils`, dépend de `m01-front-office`, `m03-estimation`, `m04-field-ops`,
  `m06-material-control` et `m07-marketing`) ; `configuration` : seuils d'alerte des mesures de chantier
  (vides à dessein) et minimum de chantiers par technicien.
- `SOUL.md` — identité de l'agent.
- `skills/rapport-analytique-quotidien/` — procédure d'ingestion → rapport.
- `src/m8_analytics/outils.py` — outil composé `m8_rapport_metriques` (validation → registre →
  sémantique → XmR → rapport) + 5 outils unitaires.
- Correctifs de fiabilité (TDD, tests dans `tests/`) : `ZeroDivisionError` sur un historique
  vide dans `xmr.py` ; `rapports.py` fail-closed pour un rôle sans liste d'autorisations ;
  `validation.py` refuse désormais les valeurs de snapshot non textuelles (PRD §5.2) ;
  `dictionnaire.py` refuse une devise monétaire non CAD (garde qui rejette nommément la
  métrique M7 historiquement en EUR — docs/research/R9-m7-m8.md §1.3).

- `metrics/m8-metrics.v1.yaml` et `src/m8_analytics/mesures_chantier.py` (PLAN T1.5-d) — mesure d'un
  chantier terminé par des métriques gouvernées : temps réel contre prévu, marge prévue contre réelle,
  écart de matériaux (repris de M6), écart de temps par technicien (admin seulement, sans classement ni
  alerte). Donnée absente : « non calculable, manque X ». Seuil franchi : alerte proposée à M9 ; seuil
  absent : rappel « seuil à configurer », jamais un seuil inventé. Outils : `m8_lire_mesures_chantier`,
  `m8_performance_equipe`. La marge réelle vient de M5 (`m5.rentabilite_chantier`) : elle n'existe que quand
  le coût réel de M5 est complet ; sinon « non calculable » avec les codes de ce que M5 n'a pas pu chiffrer.
  La durée estimée vient de M3 (`m3.devis_accepte`), quand l'estimation du devis la porte.

- `metrics/m8-entonnoir.v1.yaml`, `src/m8_analytics/entonnoir.py` et `vue_executive.py` (PLAN T4.19) — l'entonnoir
  commercial et la vue exécutive du propriétaire. M8 consomme les faits de M2 (`m2.client_associe`,
  `m2.lead_assigne`) et de M3 (`m3.devis_envoye`, `m3.devis_accepte`, `m3.devis_sans_reponse`), les range au
  registre `faits_entonnoir` (idempotent ; identifiants, instants et prix total arrêté par M3, jamais un contact)
  et mesure huit métriques gouvernées (définition, source, unité, propriétaire, version) : leads reçus et qualifiés,
  devis envoyés, acceptés et sans réponse, taux d'acceptation, délai lead-acceptation (médiane), carnet signé. Donnée
  absente : « non calculable, manque X », jamais un zéro. `m8_lire_vue_executive` (T0, admin, refus dans le code
  de tout autre rôle d'appareil) y ajoute la marge réelle telle que M5 l'a publiée (texte repris, aucun calcul), le
  stock à commander tel que M6 le met à la file du propriétaire et le cash libre (dernier constat de M5, voir
  plus bas ; « manque » tant que M5 n'a rien constaté). GATE NATHAN : les seuils de l'entonnoir
  (`configuration.seuils_entonnoir`, vide) et la période à mesurer (aujourd'hui, tous les faits reçus).

- `src/m8_analytics/cash_libre.py` (PLAN T4.19-b) — le cash libre que M5 a constaté, repris tel quel. M5 publie
  `m5.cash_libre_constate` quand l'admin le lui fait constater (`m5_constater_cash_libre`) ; M8 le consomme, range chaque
  constat au registre `faits_cash_libre` (idempotent : un fait par identifiant d'événement, la charge telle que M5 l'a
  publiée ; le résumé du reçu ne porte aucun montant) et `m8_lire_vue_executive` montre le DERNIER, celui de plus grand
  `sequence` quel que soit l'ordre de livraison du bus. La vue en reprend l'essentiel, valeur pour valeur : statut,
  montants en texte, ce qui manque (« composante : code »), réserves, la phrase et la mention de M5, le montant de chaque
  composante (`null` quand M5 n'a pas pu la chiffrer), le rang et le jour du constat. Elle DIT ce qu'elle ne reprend pas
  (`non_repris` : source et fraîcheur de chaque composante, hypothèses ; `m5_etat_tresorerie` les rend). M5 dit « non
  calculable, manque X » : la vue le montre tel quel et l'ajoute à ses manques, jamais un zéro. Aucun constat reçu :
  « manque », comme avant. M8 ne calcule aucun montant : garde statique (ni `Decimal`, ni `float`, ni `round`, ni `sum`,
  une seule soustraction dans tout le module, celle de deux dates). L'âge du constat vient de `aujourd_hui` (AAAA-MM-JJ,
  facultatif, donné par l'appelant : M8 n'a pas d'horloge) ; sans lui, l'âge est « non calculable » ; illisible, la vue est
  refusée avant toute lecture (`REJ-VUE-AUJOURD-HUI-INVALIDE`). La réponse reste sous la borne du socle : les listes
  raccourcissent d'abord (comptées dans `reste`), la décomposition du cash libre ne part qu'en dernier recours, comptée
  (`composantes_omises`) et dite ; les montants ne partent jamais. Limites : un seul constat est montré (le dernier) ; aucun
  seuil de péremption n'est inventé (l'âge est dit, le propriétaire juge : GATE NATHAN) ; le constat n'existe que si
  quelqu'un l'a demandé à M5 (le digest de 7 h ne le fait pas).

- `metrics/m8-contenus.v1.yaml`, `src/m8_analytics/contenus.py` et `vue_contenus.py` (PLAN T4.17-e) — la mesure par
  contenu : quels contenus de M7 amènent des leads, puis des devis. M8 consomme `m7.contenu_exporte` (un fait par
  contenu dont le paquet manuel est sorti : sa clé `utm_content`, son chantier, son canal, s'il portait un lien de
  suivi) et `m1.lead_qualifie` (dont il ne garde que le `lead_id`, la clé `utm_content` et l'instant : ni le contact, ni
  la ville, ni le service), les range au registre `faits_contenus` (idempotent, un fait par contenu ou par lead) et
  mesure six métriques gouvernées (définition, source, unité, propriétaire M7, version) : contenus exportés, leads,
  devis envoyés et devis acceptés par contenu, impressions et clics. Un lead est attribué à un contenu par l'égalité
  stricte de sa clé avec celle d'un contenu exporté avec un lien de suivi ; un lead sans clé n'est attribué à aucun
  contenu, une clé inconnue, ambiguë ou d'un contenu sans lien non plus, chaque cas compté à part. Un devis suit le lead
  qu'il porte (faits de l'entonnoir) ; celui dont le lead n'est pas connu de M1 (l'opportunité que M2 rouvre pour un
  client connu, par exemple) n'est attribué à rien. Donnée absente : « non calculable, manque X », jamais un zéro.
  **Impressions et clics n'ont aucune source** (ni le bus, ni Matomo, ni les statistiques des plateformes) : leurs
  métriques sont enregistrées et rendues « non calculable, manque la source des impressions et des clics ». Le
  connecteur reste à décider. `m8_lire_mesures_contenus` (T0, admin, refus dans le code de tout autre rôle
  d'appareil) rend les métriques, une ligne par contenu et les manques, par pages sous la limite du socle
  (`depart`). Limites : tous les faits reçus comptent (aucune fenêtre de période) ; l'attribution est à la clé, sans
  première ni dernière touche ; le trajet lien, formulaire, M1 est bouclé depuis T4.17-e3 (l'extrait de formulaire de
  M1 recopie les `utm_*` de la page, et le canal `formulaire` de `m1_recevoir_message_canal` les porte jusqu'au lead),
  mais rien ne reçoit encore le POST du formulaire sur le site (T3, `docs/departements/M1-canaux.md` §13) ; le compte
  est une borne basse (un client qui appelle ou écrit sans passer par le lien ne porte aucune clé : son lead n'est
  attribué à aucun contenu).

## Couche analytique d'entreprise (M8.2, M8.8, M8.11, M8.12, M8.14, M8.18)

Un catalogue fermé de 56 mesures d'entreprise (18 de la tranche 1, 20 interdépartements et 18 de la phase 2 ; `definitions/m8-catalogue.v1.yaml`), lues par un seul moteur (`moteur_mesures.py`) avec la fraîcheur
de chaque mesure (`fraicheur_mesures.py`, la plus stricte des fenêtres), alimente : l'**entrepôt** dérivé et versionné (`entrepot.py`,
`entrepot_stockage.py`, migration 0046), les **wallboards** déclaratifs (`wallboards/*.v1.yaml`, `wallboards.py`, servis par la console en SSE
borné), le **score de santé** transparent et indéterminé plutôt que faux (`sante.py`, `definitions/m8-sante.v1.yaml`), le **copilote** en français
sur catalogue fermé avec reçu (`copilote.py`, corpus `evals/copilote.v1.yaml`), le **pont BI** en lecture seule (`src/opsys/pont_bi/`, jeton du coffre,
quotas, journal) et l'**intégration mémoire** (`memoire.py`, événement `m8.fait_consolide` consommé par M10). Dix outils d'agent
(`analytique_outils.py`), skill `lecture-analytique-fermee`, planification `entrepot-et-memoire`. Tout est lecture ou calcul (N0–N2) ; l'émission d'un
jeton BI est un geste humain (N3). Documentation, preuves et limites : [`docs/architecture/M8-OLIVIER.md`](../../docs/architecture/M8-OLIVIER.md).
Données de démonstration et de calibration : `jeux_fictifs.py` (fictives).

### Entrepôt interdépartements (20 mesures de plus)

Le catalogue fermé compte 56 mesures (voir plus bas la phase 2) : aux 18 premières s'ajoutent vingt mesures tirées des constats que M1, M3, M4, M5, M6 et M7
publient déjà sur le bus (`metrics/m8-interdepartements.v1.yaml`, `src/m8_analytics/mesures_interdepartements.py`) : marge réelle
cumulée, chantiers à marge chiffrée et en perte, écart de marge réelle (M5) contre prévue (M3), créances (total et 90 jours et plus),
écritures en attente, comptes à payer, solde, taxes à remettre, somme des relevés de dépense publicitaire, conversions hors ligne,
anomalies critiques, heures sur site, réceptions et commandes de matériaux, demandes qualifiées par M1 et leur écart avec les leads de
M2. Un registre de plus (`operations`) entre dans l'empreinte de l'entrepôt ; deux consommateurs de plus (`m6.reception_enregistree`,
`m1.commande_courriel_envoyee`) ; chaque constat rangé porte sa provenance (événement, empreinte). Une valeur calculée sur une partie
seulement dit sa couverture (`couverture`, `detail`) ; une source absente reste « non calculable » ; un écart entre deux définitions est
une mesure nommée. Rien n'est ajouté aux droits d'appareil, aux outils ni aux migrations. Sources, états, décisions à prendre et limites :
[`docs/architecture/M8-ENTREPOT-SOURCES.md`](../../docs/architecture/M8-ENTREPOT-SOURCES.md).

#### Phase 2 : des résumés agrégés publiés par les départements (18 mesures de plus)

Les décisions D1 à D7 de l'architecte (r10) sont exécutées **sans lecture croisée ni droit d'appareil de plus** : sept départements
publient un événement NOUVEAU du catalogue (schéma fermé, minimisé, sans renseignement nominatif, identifiant déterministe) et M8 le
consomme dans `faits_operations` (`operations_recues.py`, la version publiée en dernier fait foi : `publie_le`) :
`m5.depense_publicitaire_constatee` et `m5.facture_emise_constatee`, `m7.performance_signaux_constatee`,
`m4.capacite_equipe_constatee`, `m2.pipeline_constate`, `m6.disponibilite_constatee`, `m1.plaintes_constatees`. Dix-huit mesures en
tirent (`mesures_constats.py`) : dépense publicitaire comptabilisée et son **écart** avec les relevés de M7 (désormais calculable),
factures émises et facturation avant taxes, clics, impressions et visites du site, heures d'équipe disponibles et planifiées et
leur rapport, leads ouverts, taux de conversion des résolus et valeur pondérée du pipeline, articles en rupture ou sur-réservés et
réservations incomplètes, plaintes, leads publicitaires et coût par lead (D6 : correspondance `canaux_marketing` d'`entreprise.yaml`,
sinon « non calculable »). D7 : chaque entrée du catalogue déclare sa `cadence_s` (ou `null`), la fenêtre du producteur est
`max(24 h, cadence)` et le propriétaire peut déclarer une cadence par mesure (`configuration.cadences_mesures_s`, vide). Trois
wallboards de plus (`acquisition`, `ventes-clientele`, `equipes-materiel`). Détail, preuves et limites :
[`docs/architecture/M8-ENTREPOT-SOURCES.md`](../../docs/architecture/M8-ENTREPOT-SOURCES.md).

DuckDB/Parquet (non installé), MMM (PyMC-Marketing) et l'orchestrateur horaire réel restent GATED (hors
périmètre v1, cf. `docs/bmad/02-PRD-PM.md` §3.2).

### Transmission factuelle des nouveaux chantiers à M9

Lors du premier enregistrement durable d'un WCT reçu de M4, M8 publie
`m8.snapshot_chantier` dans la même transaction que son snapshot. La charge
reprend le maillon enregistré : instant métier original, identifiants WCT et
intervention, durée réelle en texte et type de travaux seulement s'il était
fourni. Elle ne porte ni technicien, GPS, lead, photo, coût ni marge. La
transmission existe même sans alerte ; le bus peut la livrer à M9 au passage
suivant.

Une relivraison du même WCT ne republie rien, même si sa charge entrante porte
une autre durée. Le premier snapshot durable reste la référence. Une
publication refusée annule aussi son ajout : le reçu du bus conserve l'échec.
Les WCT déjà enregistrés avant cette évolution ne sont pas rattrapés
implicitement. Les autres snapshots ingérés par M8 et ses alertes gardent
leurs chemins existants.

## Fraîcheur attendue d'une lecture

Le propriétaire peut déclarer, pour `m8_lire_vue_executive` et `m8_lire_mesures_chantier`, la fenêtre en secondes dans laquelle il
attend le dernier fait de la lecture (`department.yaml`, `configuration.fraicheur_lectures_s`, vide à la livraison). Déclarée,
la lecture porte `fraicheur_attendue_s` et `version_definition_fraicheur` ; sinon rien n'est ajouté. M9 compare, M8 ne juge pas.
Contrat : [`docs/FRAICHEUR-ATTENDUE-LECTURES.md`](docs/FRAICHEUR-ATTENDUE-LECTURES.md).
