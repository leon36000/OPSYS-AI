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
  stock à commander tel que M6 le met à la file du propriétaire et le cash libre (M5 ne le publie pas : « manque »,
  renvoi à `m5_etat_tresorerie`). GATE NATHAN : les seuils de l'entonnoir (`configuration.seuils_entonnoir`, vide)
  et la période à mesurer (aujourd'hui, tous les faits reçus).

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
  première ni dernière touche ; le trajet physique lien, formulaire, M1 n'est pas bouclé (le site n'a pas de
  formulaire qui recopie `utm_*`, et le canal SMS de M1 n'accepte pas `utm`) ; le compte est une borne basse (un client
  qui appelle ou écrit sans passer par le lien ne porte aucune clé : son lead n'est attribué à aucun contenu).

DuckDB/Parquet, MMM (PyMC-Marketing) et l'orchestrateur horaire réel restent GATED (hors
périmètre v1, cf. `docs/bmad/02-PRD-PM.md` §3.2).
