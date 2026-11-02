# M2-revenue-crm

Revenue CRM — Client 360, pipeline, scoring, anti-doublons

Statut: PARTIAL (EPIC F — vague 1 livrée en mode ombre : registre hash-chaîné, contrat gelé
LeadQualifie (+ source/utm/campagne optionnels, PLAN T2.2), machine à états du cycle de vie
(nouveau/qualifie/perdu, puis converti/cédule/chantier/facture/paiement/avis — PLAN T1.1-a),
interactions et readiness gate, anti-doublons, Client 360 (identité, vue compacte, réouverture
d'opportunité pour affaire répétée — PLAN T2.2), suggestion de prochaine action (M2.6), digest,
adaptateurs fail-closed.)

Identité authentifiée (PLAN T1.4-k2, `src/m2_revenue_crm/acces.py`, docs/architecture/ROLES.md) : pour un
appel d'appareil, `auteur` de `m2_enregistrer_interaction` vient de la personne du jeton, confirmée en base
(un `auteur` différent est refusé, `REJ-IDENTITE-FOURNIE-DIFFERENTE`), et un vendeur ne voit et n'agit que
sur ses leads (`owner` de la qualification ; Client 360 limité à ses opportunités ; le même refus,
`REJ-LEAD-NON-ASSIGNE`, pour un lead d'un autre, sans propriétaire ou inconnu). L'admin voit tout. La
qualification depuis un appareil exige que `owner` soit l'identifiant d'une personne active (seller ou
admin) et publie `m2.lead_assigne`, que M3 relit. Sans identité d'appareil (agent, console, consommateurs
d'événements) : comportement d'avant, `owner` en texte libre. Voir « Ce que T1.4-k2 laisse ouvert » ; la
réassignation et la republication du fait, qui en fermaient deux, sont plus bas (PLAN T1.4-m).

## Ventes : profil de propriété, score, coach, analytique et prévisions (m2-victor, M2.3 / M2.4 / M2.9 / M2.15)

Seize outils (niveaux et portées : [ROLES.md](../../docs/architecture/ROLES.md), « Les outils « ventes » de M2 » ; conception,
preuves et limites : [M2-VICTOR.md](../../docs/architecture/M2-VICTOR.md)). Autonome (N0 à N2) : lire, calculer, classer, préparer un
brouillon ; humain (N3) : confirmer un profil de propriété, déclarer une valeur ; jamais d'envoi, de changement de statut ni de remise.
- **Profil de propriété** (`propriete.py`, registre `profils_propriete`) : liste blanche minimisée (Loi 25), chaque fait sourcé,
  versionné, en BROUILLON jusqu'à la confirmation d'une personne ; alimenté par saisie, courriel (motifs fixes, extrait comme preuve)
  et onboarding ; fait minimisé `m2.profil_propriete_confirme` au bus.
- **Score de lead 2.0** (`scoring.py`, `scoring_faits.py`, `calibration_scoring.py`) : six facteurs de poids déclarés, explication
  par facteur et par signal, signaux « non évalués » nommés, déterministe (fractions exactes), reçu rejouable ; il ORDONNE la file
  (`m2_classer_file_leads`, permutation) et ne décide jamais ; liste de champs interdits testée ; calibration (AUC, Brier, courbe)
  mesurée sur un jeu FICTIF.
- **Coach de vente** (`coach.py`) : faits du CRM + extraits de connaissances avec provenance, suggestions en brouillon (N2) qui
  citent leurs faits, garde-fou de texte (aucun prix, remise, engagement ni nombre inventé), journal et taux d'acceptation ; fermé
  aux appareils ; le vendeur décide ; l'envoi reste au sas courriel (N3).
- **Analytique et prévisions** (`previsions.py`, `moteurs_commerciaux.py`) : pipeline, conversion, délai de cycle, valeur pondérée,
  prévision par INTERVALLE (moyenne mobile, lissage exponentiel, bootstrap à graine), refus sous les seuils d'échantillon, reçu
  `recu-calcul.v1` de M5 rejouable.

Preuve : `tests/test_propriete*.py`, `test_scoring*.py`, `test_previsions*.py`, `test_coach*.py`, `test_moteurs_commerciaux.py`
et, du socle, `tests/e2e/test_ventes_vendeur_appareil.py` (la vraie porte d'appareil, SQLite et PostgreSQL). Corpus d'évaluation :
28 cas (`evals/gabarit.v1.yaml`).

## Réassigner un lead, republier le fait de propriété (PLAN T1.4-m)

Deux outils d'admin (`m2_reassigner_lead`, `m2_republier_assignations`, T1, N3, `admin` seulement ; ROLES.md, « La
réassignation d'un lead » et « La republication du fait de propriété »). `assignation.py` (module pur) tient la propriété
dans le temps ; le propriétaire courant est celui de la DERNIÈRE assignation, lue en un seul endroit, sur lequel `acces.py`,
la readiness et le digest s'alignent.
- **Réassigner** (`m2_reassigner_lead(lead_id, nouveau_proprietaire, motif, horodatage)`) : une décision HUMAINE, patron de
  `m1_clore_transfert`, `m5_saisir_facture_fournisseur` et `m10_clore_signal`. Décideur : jeton d'appareil `admin` confirmé
  en base, ou demande qu'une personne vient d'approuver ; sinon `REJ-HUMAIN-REQUIS`, même en `supervise` ou `autonome`.
  Motif de 10 à 500 caractères. Cible : personne active de rôle `seller`, sinon `REJ-OWNER-INCONNU`. Le lead doit avoir un
  propriétaire (`REJ-OWNER-ABSENT` : un lead `nouveau` se qualifie), différent de la cible (`REJ-PROPRIETAIRE-INCHANGE`) ;
  tous les statuts, `perdu` compris. Résultat : le nouveau vendeur voit le lead, l'ancien non (liste, total, Client 360, notes).
  Un maillon `reassignation` s'ajoute (qui, pourquoi, de qui à qui, rang, voie) ; la qualification n'est jamais modifiée. Le
  fait `m2.lead_assigne` de rang n >= 2 (additif : `rang`, `proprietaire_precedent`) est publié dans la MÊME transaction.
  M3 lit le plus grand rang publié : le devis suit le lead (ROLES.md, `tests/test_reassignation_suit_m3.py`).
- **Republier** (`m2_republier_assignations()`) : pour chaque assignation du registre dont le fait manque au bus (les leads
  qualifiés avant T1.4-k2), publie le MÊME fait que la publication d'origine. Idempotent, n'écrit pas au registre,
  n'invente aucun propriétaire ; refusé hors stockage durable (`REJ-BUS-INDISPONIBLE`). À lancer une fois à la mise en
  service.
- Cinq identifiants de verdict s'ajoutent (groupe 7 : `REJ-HUMAIN-REQUIS`, `REJ-MOTIF-INVALIDE`, `REJ-LEAD-INCONNU`,
  `REJ-PROPRIETAIRE-INCHANGE`, `REJ-BUS-INDISPONIBLE`) ; le gel de `verdicts.py` est rescellé (addendum T1.4-m de
  `docs/bmad/03-ARCHITECTURE.md`).
- Preuve : `tests/test_assignation.py` (module pur), `tests/test_reassignation.py` (l'outil réel, la file d'approbation, l'idempotence),
  `tests/test_republication_assignations.py` (une base qui contient des leads d'avant T1.4-k2) et, du socle,
  `tests/e2e/test_reassignation_lead_appareil.py` (la vraie porte d'appareil) et `tests/test_republication_devis_vendeur.py`
  (M2, bus, M3 : le vendeur lit enfin les devis de ses leads d'avant).

## Le lead d'un canal arrive par le bus (PLAN T2.1-b)

M2 consomme `m1.lead_qualifie` (`evenements.consomme` de `department.yaml`, `_recevoir_lead_qualifie` dans
`outils.py`) : le lead v2 que M1 qualifie à partir d'un message de canal du core (SMS) est ingéré par la chaîne complète
(`ingerer_lead` : contrat, frontières, unicité, doublons probables signalés, Client 360, `m2.client_associe`), avec l'heure
de réception de la plateforme. Un lead refusé (service retiré du profil depuis la qualification, contrat invalide) lève
`LeadRefuse` : le répartiteur réessaie, puis met l'événement en quarantaine, sans écriture ; jamais d'acceptation silencieuse.
Un événement rejoué, ou le même lead sous un autre identifiant d'événement, ne crée ni second lead ni seconde opportunité
(`deja_applique`) ; le même `lead_id` avec un autre contenu lève aussi. Voir
[M1-canaux](../../docs/departements/M1-canaux.md) §7, et `tests/test_consommer_lead_de_m1.py`.

## Une soumission acceptée convertit le lead par le bus (PLAN T4.10-a)

M2 consomme `m3.devis_accepte` (`evenements.consomme` de `department.yaml`, `_recevoir_devis_accepte` dans
`outils.py` ; DEFINITION-PRODUIT §6 « soumission acceptée → M4 planifie », §7 M2.8). Avant, le lead restait `qualifie`
après l'acceptation. Maintenant, sans qu'un humain l'écrive :
- lead `qualifie` : transition `qualifie → converti` avec `reference_devis_m3` = le devis, à l'heure de l'acceptation
  fournie par M3 (jamais une horloge de M2) ; la **prochaine action** « planifier le chantier » (règle
  `planifier_chantier`, `suggestions.prochaine_action_planifier_chantier`, texte fixe qui cite sa règle, échéance =
  l'heure réelle de l'acceptation) est portée par la transition, donc lue par le Client 360 ; une **activité** système
  (`system:m3`) rattache le fait au dossier. `m2_suggerer_prochaine_action` d'un lead `converti` rend la même règle.
  Aucune date ni aucun créneau n'est promis au client : c'est M4 qui planifie (§7 M2, règles dures) ;
- lead déjà `converti` (ou plus loin) par CE devis : rien à refaire (`deja_converti`), c'est le flux d'avant où un humain
  convertissait avant l'acceptation ;
- lead `perdu` : le fait est gardé (`ignore: lead_clos`), sans conversion, interaction ni quarantaine (patron de
  `m3.devis_sans_reponse`) ;
- lead inconnu : `LeadIntrouvable` ; lead jamais qualifié (`nouveau`), ou déjà converti par UN AUTRE devis :
  `AcceptationIncompatible`. Le répartiteur réessaie, puis met l'événement en quarantaine, sans écriture, visible d'un
  humain (`opsys-metier evenements etat`) : aucune transition n'est fabriquée sans propriétaire ni décision.

Un événement rejoué, ou le même devis sous un autre identifiant d'événement, ne convertit pas deux fois
(registre `devis_acceptes_recus`, clé `devis_id`). La conversion et son activité sont dans la même transaction : si
l'une échoue, l'autre est annulée. Aucun prix, coût ni marge du devis n'est lu ni gardé (M2 n'est pas la source de vérité
financière). `statuts.transitionner` accepte désormais, sans l'exiger, une `prochaine_action` à la conversion ; sans
elle le maillon reste celui d'avant, octet pour octet. Preuve : `tests/test_consommer_devis_accepte.py` (22 tests, dont
le rejeu, l'ordre inversé et l'atomicité) et, avec M4, M5, M6 et M8 par le même bus, `tests/test_cascade_devis_accepte.py`
du socle.

## La liste des leads et les 14 segments (PLAN T4.6)

`m2_lister_leads` (T0, lecture pure) liste les leads que l'appelant peut voir, par statut et par segment, une page à la
fois (`liste_leads.py` ; règles des segments : `segments.py`, purs). DEFINITION-PRODUIT §9.4 « ses leads », §9.5
« pipeline, leads chauds », §7 M2.11.
- **Qui voit quoi** : un vendeur (appareil `seller`) ne voit que SES leads, par l'identité confirmée en base, comme le
  reste de M2 (T1.4-k2) ; l'admin voit tout ; un employé est refusé. Un lead d'un autre vendeur, un lead `nouveau` et un
  lead sans propriétaire ne sont ni listés, ni comptés dans `total`, ni cités dans une règle. Aucun paramètre ne désigne
  une personne. Déclaré dans `ROLES.md`.
- **Ordre stable** : le plus ancien lead ingéré d'abord (instants comparés en UTC), puis `lead_id`. **Pages** : même
  mécanisme que `attentes_decalage` du socle et `m9_lire_suite_briefing` : `decalage` (rang), `suivant` (`None` à la
  fin), `reste`, sous la limite de sortie du socle (mesurée), au moins un lead par page ; hors de la fin, une page vide.
- **Aucun montant, aucun contact.** Un item : lead, statut, propriétaire, travaux, ville, urgence déclarée, deux dates,
  prochaine action, segments.
- **Segments** (l'ordre de §7 M2.11). Chaque segment appliqué cite sa règle (`regle`, énoncé dans `regles`) et la
  donnée qui le déclenche (`donnee`). Ces définitions sont celles du code ; à valider par le propriétaire.

  | Segment | Règle |
  |---|---|
  | `hot_lead` | urgence déclarée à l'ingestion, lead ouvert (`nouveau` ou `qualifie`) |
  | `estimate_ready` | `qualifie` et `readiness.evaluer` satisfaite (pas recalculée) |
  | `quote_sent` | `qualifie` et un devis `envoye` (M2-C5 : `m3.devis_envoye`, déjà reçu ; aucun seuil) |
  | `quote_stale` | `qualifie` et un devis `envoye` sans réponse (`m3.devis_sans_reponse`) depuis au moins `jours_soumission_perimee` jours |
  | `won_pending_schedule` | `converti` (règle `planifier_chantier`) |
  | `active_job` | `cedule` ou `chantier` |
  | `invoice_pending` | `facture` ou `paiement` (paiement non confirmé) |
  | `past_customer` | le client a une opportunité VISIBLE de l'appelant au statut `avis` (chantier payé) |
  | `referral_candidate` / `complaint_risk` | (M2-C5) le dernier chantier terminé du lead a rapporté `client_satisfait` vrai / faux (`m4.travaux_termines`, gardé au registre `satisfactions_recues` : un booléen et des identifiants, jamais un contact) |
  | `dormant_lead` | lead ouvert sans activité humaine depuis au moins `jours_inactivite_dormant` jours |

  Les trois autres (`needs_photos`, `high_value_customer`, `seasonal_opportunity`) reposent sur une donnée qui
  n'atteint pas M2 : « non calculable, manque X », pour tous les leads, jamais devinés. `quote_sent`,
  `referral_candidate` et `complaint_risk` (M2-C5) sont calculables des faits déjà reçus ; leur source illisible
  (registre absent) les rend « non calculables » comme avant, jamais « aucun lead ». Un filtre sur un segment non calculable est REFUSÉ (`REJ-SEGMENT-NON-CALCULABLE`, avec ce qui
  manque) : une liste vide se lirait « aucun lead ».
- **Seuils** : `configuration.segments` de `department.yaml`, VIDES à dessein (patron de M8 et de M6). Sans seuil,
  `dormant_lead` et `quote_stale` sont « non calculables, seuil à configurer » ; un seuil invalide est dit « invalide ».
  Relus à chaque appel. `horodatage` (l'instant de référence) est un argument : aucune horloge dans le code.
- **Limites** : `quote_stale` part de l'envoi que M3 publie à l'approbation (`m3.devis_envoye`, PLAN T4.9), ou, à
  défaut, du constat `m3.devis_sans_reponse` : l'envoi l'emporte, l'instant est celui de l'APPROBATION, pas de la
  livraison au client (T2.1-c). Le message « non calculable » de `quote_sent`, `referral_candidate` et `complaint_risk` que l'app garde dans ses
  fixtures Jest n'est plus rendu par M2 (M2-C5) : les fixtures mobiles sont à rafraîchir avec le lot mobile. `past_customer` diffère selon l'appelant (l'admin voit
  les opportunités de tous les vendeurs) : voulu. Un décalage est un rang : un lead qui change de statut ou de segment
  entre deux pages d'un filtre peut manquer ou se répéter.
  Preuve : `tests/test_segments.py`, `tests/test_liste_leads.py`, `tests/test_lister_leads_outil.py` et, par la vraie porte
  d'appareil, `tests/e2e/test_liste_leads_vendeur.py` du socle.

## Les relances dues, avec consentement et fréquence limitée (PLAN T4.9)

Trois outils (`relances.py`, `consentements.py`, `gabarits_relance.py`, purs ; `outils.py` lit le registre, l'identité et
`department.yaml`). DEFINITION-PRODUIT §7 M2.7 et M2.13 (règles dures : pas de spam, opt-in respecté, fréquence limitée,
validation humaine au départ), §9.4 « relances autorisées ». Déclarés dans `ROLES.md` (seller et admin, jamais l'employé).
- **`m2_lister_relances`** (T0, lecture pure) : les relances DUES, une page à la fois. Deux règles, les seules dont M2
  tient déjà les faits : `relance_devis_sans_reponse` (segment `quote_stale`) et `relance_lead_dormant` (segment
  `dormant_lead`). Chaque relance cite sa règle et le fait de départ, dit sa dernière relance, la prochaine date permise
  et les canaux permis (« appel seulement » ou « appel ou message »). Un vendeur ne voit que les relances de SES leads.
- **`m2_preparer_relance`** (T1, N3) : prépare UNE relance due avec le texte FIXE du gabarit de (règle, canal). **N'envoie
  rien** : l'envoi réel est T2.1-c (N4, une personne). Refuse une relance non due, trop proche de la précédente ou par un
  canal sans consentement actif. Aucun texte ne se passe en argument ; les six gabarits sont validés au chargement par le
  garde-fou de texte, et un SMS ou un courriel se termine par « répondez STOP ».
- **`m2_enregistrer_consentement_contact`** (T1, N3) : une PERSONNE inscrit le consentement d'un client pour `sms` ou
  `courriel` (énoncé versionné, source, preuve sans numéro ni courriel). Refusé à un agent seul (`REJ-HUMAIN-REQUIS`).
- **Le départ du délai** est un fait publié : `m3.devis_envoye` (`horodatage_envoi`, consommé par
  `_recevoir_devis_envoye`, idempotent par `devis_id`) ; la dernière activité humaine pour un lead dormant. Le fait de M3
  date l'APPROBATION de l'envoi, pas sa livraison (T2.1-c) : chaque relance de devis le dit.
- **Le STOP** : M2 consomme `m1.retrait_consentement` (`_recevoir_retrait_consentement`) : un retrait par lead, le
  `lead_id` du client et jamais son numéro. Il vaut pour la PERSONNE (les leads d'un même client) et pour ses deux
  canaux écrits, prime sur tout consentement, et aucun outil ne le lève. L'appel reste permis.
- **Créance levée par le paiement** : M2 consomme `m5.facture_emise_constatee` (déjà publié par M5 pour M8) : une facture `PAYEE` ou
  `ANNULEE` lève la relance de créance de cette facture (`faits_interconnexion.creances_ouvertes`, calculé à la lecture : un
  état plus ancien rejoué ne la rouvre jamais) ; un paiement partiel n'est jamais `PAYEE`, la relance reste. M2 ne garde que
  l'identifiant et le statut. Preuve : `tests/test_creance_levee_paiement.py` du socle.
- **Constat contradictoire** : un fait d'interconnexion rejoué avec la même clé mais un contenu différent (relance de créance,
  conversion, contexte de site) garde le PREMIER état, est rangé au registre `constats_contradictoires` (noms des champs, jamais
  les valeurs) et dit par `m2_lister_relances` (`constats_contradictoires`) ; le rejeu identique reste silencieux.
- **La fréquence** est celle de la personne (`jours_entre_relances`) ; la dernière relance est la dernière PRÉPARÉE.
  Permis pile à la prochaine date permise. Pour un appel d'appareil idempotent, l'heure du serveur fait foi.
- **GATE NATHAN** : `configuration.relances.jours_entre_relances` et `configuration.segments` (les délais) sont VIDES à
  dessein : « à configurer » (`REJ-RELANCES-A-CONFIGURER`), jamais un défaut. La politique de consentement au SMS
  (`docs/compliance/politiques/POLITIQUE-consentement-sms.md`) attend sa validation ; le STOP couvre le SMS et le
  courriel ; lever un retrait, le libellé et l'identification de l'expéditeur des gabarits, et un plafond du nombre de
  relances sont à décider. **T3** : l'envoi lui-même.
- **Limites** : aucun envoi réel n'existe pour dater la fréquence ; pas de règle pour l'ancien client, l'avis, la
  référence ni le saisonnier (leur donnée n'atteint pas M2) ; aucun outil humain ne retire un consentement (le retrait
  vient du STOP par le bus) ; la fréquence n'est pas plafonnée en nombre de relances par devis ; un appel d'appareil
  sans clé d'idempotence n'a pas d'heure de réception : l'`horodatage` fourni fait alors foi (même limite que M1, M5 et
  M10).
  Preuve : `tests/test_relances.py`, `test_consentements.py`, `test_gabarits_relance.py`, `test_evaluer_leads.py`,
  `test_consommer_devis_envoye.py`, `test_consommer_retrait_consentement.py`, `test_relances_outils.py` (493 tests) et,
  du socle, `tests/test_cascade_relances.py` (le vrai M1, le vrai M3, le vrai bus) et
  `tests/e2e/test_relances_vendeur_appareil.py` (la vraie porte d'appareil).


## Notes commerciales — borne de la façade (T4.8-b, 2026-10-08)

`m2_enregistrer_interaction` refuse un `resume` reçu non vide de plus de 300 points Unicode,
après identité courante, auteur et contrôle du lead. Refus `REJ-CONTRAT-INVALIDE`, sans copier
ou tronquer le texte. `maxLength: 300` est publié par le schéma ; la garde métier est appliquée
par la façade, car le validateur minimal du socle ne traite pas ce mot-clé. Le mobile compte
300 unités UTF16 sur son texte épuré, ce qui respecte cette borne.

La primitive interne et les traces des cascades M3/M4 gardent leur contrat. Aucun historique
n’est réécrit et la taille de toute réponse Client360 n’est pas garantie par cette borne.
En HTTP, un refus métier garde ses traces d’approbation/idempotence : même clé et même payload
rejouent le refus, même clé et autre payload font un conflit ; une correction est une nouvelle
intention. Les données métier restent inchangées.

Qualification locale : 1 849 tests département/verticale sans skip, puis 121 tests sur le
principal ; Ruff et vérificateur verts, revue indépendante de 30 cas. Porte Python du harnais
vers HTTP MCP/SQLite, Gateway TypeScript et téléphone distincts. Publication et CI exactes
suivantes requises. [Audit et limites](../../docs/reprise/NOTES-M2-2026-10-08/AUDIT-NOTES-M2-2026-10-08-r1.md).

## Résumé du pipeline publié pour M8 — `m2_constater_pipeline`

(phase 2 de l'entrepôt de M8, D2 : `docs/architecture/M8-ENTREPOT-SOURCES.md`) L'outil (T1/N2, agent seulement, aucun droit d'appareil) établit le pipeline de TOUS les leads comme `m2_analyser_pipeline` (module pur `constat_pipeline.py`) et publie `m2.pipeline_constate` : comptes par statut, ouverts, convertis, perdus, résolus, taux de conversion des résolus et valeur pondérée DÉCLARÉE (centre de l'estimation). Un taux ou une valeur que M2 refuse d'établir part en `null`. Aucun lead, contact ni vendeur. Un vendeur n'a pas de périmètre global : refusé. L'identifiant porte l'instant du constat, de sorte qu'un retour à une version antérieure des données ne se confond pas avec la première publication.

**Déclenchement.** Ce constat est déclaré par `constats_planifies` du `department.yaml` et lancé par le planificateur durable
(exécuteur `m2.constat.pipeline`, inactif par défaut, cadence par défaut dérivée du catalogue de M8) : `horodatage` = le début du créneau. Aucun agent n'a besoin de le
faire à la main. Voir `docs/architecture/PLANIFICATION.md` §9.

## Le filet anti-perte — SLA, audit d'intégrité, plan de réparation (M2-C1)

« Ne perdre aucun lead » (DEFINITION-PRODUIT §7 M2.1 et M2.13). Avant ce chantier, M2 empêchait les mauvaises écritures
(machine à états, registre chaîné) mais ne regardait pas ce qui se perd EN SILENCE : un lead sans propriétaire, un lead chaud que
personne n'a appelé, un devis jamais relancé. Quatre outils, sans aucun droit d'appareil (agent ou administrateur seulement : le
filet porte sur TOUS les leads), qui LISENT les registres existants et n'écrivent rien (`filet.py`, `sla.py`, `integrite.py`,
`reparation.py`, `constat_filet.py` : modules purs, aucune horloge ; `outils_integrite.py` : la couture) :

- **`m2_scanner_sla`** (T0/N0) : sept règles déclaratives — prochaine action obligatoire, lead chaud contacté vite, photos reçues,
  soumission relancée, plainte escaladée, lead avec propriétaire, tâche en retard. Chaque violation dit sa règle, sa raison,
  depuis quand (`depuis`, `ecoule_heures`) et le seuil déclaré. **Les délais sont DÉCLARÉS par le propriétaire**, jamais inventés :
  `configuration.sla` de `department.yaml` (sept clés d'heures, listées dans le manifeste), plus `jours_soumission_perimee` de
  `configuration.segments` pour la règle de soumission. Un délai absent ou invalide rend la règle **non évaluée** : elle dit
  quoi déclarer et ne rend aucune violation (`violations: null`, jamais un zéro) ; les règles de propriétaire et de prochaine action
  gardent leur partie sans délai (un lead avancé sans propriétaire ni action est une incohérence immédiate) et sont alors
  « partielles ». Le dépassement est STRICT (pile à la limite, le SLA est tenu). Les relire à chaque appel : aucun redémarrage.
  La lecture des cinq nombres de M2 (dormance, devis périmé, fréquence de relance, SLA, bandes de valeur) passe par UNE seule fonction,
  `outils._bloc_configuration` : le futur mécanisme de réglages de direction n'a qu'elle à brancher.
- **`m2_auditer_integrite`** (T0/N0) : huit contrôles — leads sans statut, clients sans contact (ni téléphone ni courriel),
  tâches sans propriétaire, soumissions orphelines, activités sans lead, leads sans client, pipeline incohérent (chaîne rompue,
  transition illégale, converti sans devis, perdu sans motif, qualifié sans propriétaire ni action, facturé sans action),
  doublons probables (le MÊME critère et la MÊME fenêtre de 7 jours que l'ingestion ; **lecture seule, aucune fusion**,
  un arbitrage « distincts » les écarte). Un contrôle dont la source est illisible est « non évalué ».
- **`m2_planifier_reparations`** (T0/N0) : le plan par cible (lead, sinon client ou devis), par urgence (plainte, lead chaud, lead
  sans propriétaire, première action, soumission, retard, photos, intégrité). Des actions **proposées, jamais exécutées**
  (`execute: false`) ; une action qui passe par un outil de niveau N3 (niveau relu des outils réels) dit
  `approbation_requise: true` — une personne l'approuve dans le sas ; aucun message n'est envoyé, aucune demande
  d'approbation n'est créée, rien n'est fusionné. La prochaine meilleure action existante (`m2_suggerer_prochaine_action`, règle citée)
  accompagne chaque lead.
- **`m2_constater_filet`** (T1/N2) : publie `m2.filet_anti_perte_constate` (comptes seulement : violations par règle, anomalies par
  contrôle, règles non évaluées ; ni lead, ni client, ni contact, ni vendeur) pour M8, qui en tire `m8_violations_sla_commercial` et
  `m8_anomalies_integrite_crm` (wallboard « ventes et clientèle »). **Déclenchement** : constat `filet` de `constats_planifies`,
  exécuteur `m2.constat.filet` du planificateur durable (inactif par défaut, `ombre` dit « aurait » sans rien publier, un même créneau ne
  publie rien de plus : `docs/architecture/PLANIFICATION.md` §9). Mesure des violations : **non calculable** tant qu'aucune règle
  n'est évaluée en entier (aucun délai déclaré), couverture partielle dite quand certaines le sont.

**M2-C5 (quick wins livrés avec le filet).** `client_satisfait` (reçu de M4) et `quote_sent` (reçu de M3) sont désormais gardés et
lus : trois segments deviennent calculables (voir plus haut) et la règle « plainte escaladée » existe. Et **une relance préparée que
personne n'a notée au dossier ne retarde plus la suivante** : M2 n'envoie rien et ne reçoit aucun accusé, le seul signe qu'une relance a
eu lieu est la note d'une personne (`m2_enregistrer_interaction`, ce que `a_faire` demande). La fréquence part de la première note d'une
personne postérieure à la préparation ; une relance préparée non notée reste « en attente » (`preparee_en_attente`) et n'est pas
préparée deux fois pour le même canal (`REJ-RELANCE-DEJA-PREPAREE`). **Conséquence à connaître** : tant que personne ne note, M2 ne sait
pas qu'un client a été relancé, donc une relance réellement faite mais non notée peut être proposée de nouveau.

**Ce qui n'est PAS prouvé (sans euphémisme).** Les valeurs réelles des délais sont une décision de Nathan : aucune n'est livrée,
les tests utilisent des valeurs de preuve. M2 n'a ni entité « tâche » ni accusé d'envoi : « contacté » et « escaladé » se lisent à la
note d'une personne, « tâche en retard » est la prochaine action échue sans activité humaine postérieure, « photos demandées » se lit à
l'arrivée des photos dans le profil confirmé (M2 ne sait pas si la demande a été faite). Les clients importés à l'onboarding
(`clients_importes`) ne sont pas dans l'audit. Preuves : SQLite, données fictives, horloge injectée ; jamais PostgreSQL, jamais la boucle
réelle du serveur pendant des jours, jamais de vraies données. Voir `docs/utilisation/LIMITES-CONNUES.md`.
Preuve : `tests/test_sla.py`, `test_integrite.py`, `test_reparation.py`, `test_constat_filet.py`, `test_filet_outils.py`,
`test_filet_scenario.py` (douze leads fictifs, vrais outils), `test_c5_donnees_gardees.py` et, du socle,
`tests/test_filet_anti_perte_planifie.py` (planificateur, bus, M8, wallboard).
