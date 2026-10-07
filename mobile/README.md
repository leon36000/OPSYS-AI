# App mobile OPSYS

Expo SDK 57, Expo Router, React Native 0.86, TypeScript strict. Quatre profils (un groupe de routes par profil) :
`(employee)`, `(seller)`, `(admin)`, `(client)`. Le profil est celui que le serveur confirme pour l'appareil
(`GET /opsys/identite`), jamais un choix de l'utilisateur. Décisions, pile et limites :
[`docs/architecture/MOBILE.md`](../docs/architecture/MOBILE.md) ; portée de chaque rôle :
[`docs/architecture/ROLES.md`](../docs/architecture/ROLES.md).

## Commandes

```bash
npm ci
npm run typecheck        # tsc --noEmit
npm test -- --ci         # Jest (preset jest-expo)
npx expo start           # développement
```

Le bac à sable de développement n'exécute pas le core : il se construit et se teste en CI (`.github/workflows/mobile.yml`
pour cette app). La logique des écrans vit dans `src/`, en fonctions pures testées. Le briefing dispose aussi de
tests ReactTestRenderer de rafraîchissement et de hors ligne, avec Router/i18n/transport contrôlés ;
ils ne prouvent ni le rendu sur téléphone ni le pont natif Expo SQLite.

## Écrans par profil

| Profil | Écrans (`app/`) | Outils appelés (nom nu) |
|---|---|---|
| Employé | `today`, `job/[id]` (statut, checklist, photos, signature, matériaux, terminer), `punch`, `consent` | `m4_*`, `m6_declarer_materiaux_utilises` |
| Vendeur | `leads`, `lead/[id]`, `quotes` | `m2_lister_leads`, `m2_suggerer_prochaine_action`, `m2_trouver_client_de_lead`, `m2_obtenir_client_360`, `m2_enregistrer_interaction`, `m3_lire_devis` |
| Admin | `admin` (« À voir »), `approvals`, `chiffres`, `chantiers`, `briefing`, `comptes`, `stock` | `m9_lister_demandes_approbation`, `m9_decider_demande_approbation`, `m8_lire_vue_executive`, `m5_etat_tresorerie`, `m5_prevoir_tresorerie`, `m5_lire_echeances_fiscales`, `m4_lister_interventions`, `m4_verifier_preparation`, `m4_produire_digest`, `m9_produire_briefing_matin`, `m9_lire_suite_briefing`, `m9_lire_alertes_m8`, `m9_lire_etat_consolide`, `m5_lire_comptes_a_recevoir`, `m5_lister_comptes_a_payer`, `m5_lister_attentes_facturation` |

### Employé (PLAN T1.4-e, T1.4-n)

- **`today`** : ses interventions actives, lues par `m4_lister_interventions` **un statut à la fois** (`en_route`,
  `sur_site`, `en_revue`, `planifiee`). La réponse n'a pas de pagination et le socle la coupe à 6 000 caractères
  (`{ok, tronque, apercu}`, sans `resultat`) : cette forme n'est ni une liste vide ni une liste complète. L'écran dit
  « incomplète », montre les groupes lus en entier, et n'écrit jamais le cache par-dessus une lecture incomplète.
- **`job/[id]`** : le statut par `m4_statut_intervention` ; `a_planifier` est un statut connu (`ETATS_INTERVENTION_M4`).
- **Hors ligne** : le cache (`employe:<personne>:chantiers_v1`) est rendu marqué (date, raison) quand le serveur ne
  répond pas. Un refus (jeton révoqué, personne désactivée) n'est jamais remplacé par le cache.

### Vendeur (PLAN T4.8, §9.4)

- **`leads`** : ses leads (`m2_lister_leads`), paginés (`decalage`, `suivant`), filtre par statut et par segment. Chaque
  segment cite sa règle et la donnée qui l'a déclenché. Un segment non calculable est dit « non calculable, manque X »,
  jamais une liste vide.
- **`lead/[id]`** : prochaine action suggérée avec sa règle citée, Client 360, historique, et une note
  (`m2_enregistrer_interaction`) qui part par la file sortante avec sa clé d'idempotence (300 caractères au plus).
- **`quotes`** : statut et prix de ses soumissions (`m3_lire_devis`), jamais le coût ni la marge. Aucun outil ne liste les
  soumissions d'un vendeur : la liste montre celles que ses leads citent, et une autre s'ouvre par son numéro.
- **Hors ligne** : lecture d'abord ; le cache SQLite (une clé par personne) est rendu marqué comme cache, avec sa date,
  quand le serveur ne répond pas. Un refus (401, 403, personne désactivée, segment non calculable, devis introuvable) n'est
  **jamais** remplacé par le cache, et n'écrit rien.

#
### Briefing admin (PLAN T4.21)

Accessible depuis « À voir ». Les quatre sections du briefing (décisions, alertes, faits de la veille,
manques) conservent leurs sources et dates ; les alertes reçues et l’état consolidé/contradictions se lisent
séparément. Aucun montant n’est recalculé, aucune décision n’est proposée par l’app ni appliquée.

Les premières lectures peuvent servir leur cache personnel normalisé, avec date et raison ;
les preuves M8 non affichées sont retirées, hormis la référence WCT. un refus serveur ne
les remplace jamais par ce cache. Les suites restent en ligne. Chaque suite **remplace** la page de sa
section : les sources peuvent changer entre pages, `maintenant` ne fige pas un snapshot. Rafraîchir
abandonne les suites et recommence depuis le début ; une réponse tardive est écartée, également après
changement de session/purge. L’état consolidé non paginé peut être tronqué : cette sortie est illisible,
jamais un état vide. Les références techniques internes ne sont pas affichées sur téléphone.

Preuves : contrats TypeScript contre réponses natives fictives, HTTP MCP réel/SQLite avec porte Core
simulée Python (admin permis, employee/seller refusés, tables inchangées), tests React contrôlés.
Compilation Metro Android JavaScript réussie, sans bytecode/APK ni publication ; cette gate est
ajoutée à la CI mobile avec dotenv/injection de variables désactivés.
Le CLI d’appairage ne supporte actuellement pas `client` : aucun client authentifié n’est prétendu
qualifié par ces tests. Téléphone, navigation Expo native et pont Expo SQLite restent à vérifier.

## Admin, le propriétaire (PLAN T4.20, §9.5)

Trois écrans de **lecture seule** au-delà des approbations (seul `approvals` décide, par la file sortante) :

- **`admin` (« À voir »)** : les demandes d'approbation en attente et les attentes des départements (complétion en revue avec
  écart de matériaux critique, facture prête, chantier à réviser, besoin de commande), avec le lien vers `approvals`, `chiffres`
  et `chantiers`. Ni arguments, ni motif, ni description d'outil (le cache non plus : Loi 25). « Rien à voir » n'est dit que
  si le serveur le dit : des attentes que le moteur ne donne pas, ou qu'un département n'a pas su dire, ne sont pas « aucune ».
- **`chiffres`** : trésorerie et cash libre (le solde de l'app est celui du cash libre : le « 0 » gelé d'un registre vide n'est
  jamais montré), prévision semaine par semaine (« Voir plus » ne prolonge qu'une lecture faite à l'instant, jamais une copie ;
  les pages ne se recollent que si `prevision_id` est le même), échéances TPS/TVQ, vue d'ensemble de M8. Chaque section se charge
  pour elle-même. Un « non calculable » ou un « à configurer » dit ce qui manque avec les mots du serveur, jamais un zéro ; la
  mention « Analyse préparatoire IA » de M5 est montrée avec la donnée.
- **`chantiers`** : les interventions par statut (un appel par statut : la réponse de `m4_lister_interventions` n'a pas de
  pagination et le socle la tronque à 6 000 caractères), le digest du jour, la préparation d'une intervention à la demande, volet
  par volet. **Un manque se dit en mots simples** (fr-CA, en-CA), par une phrase de l'app choisie d'après le code du manque
  (`src/ecrans/manquesM4.ts`) : jamais le texte de M4, qui cite le fichier du serveur et les commandes `opsys-metier`. Un manque
  que l'app ne connaît pas se dit « à configurer côté serveur » avec son code. **La météo d'un créneau n'est pas lue** :
  aucun outil ne la rend sans écrire (`m4_verifier_meteo_creneau` exige un `plan_id` de `m4_proposer_cedule`) ; le volet
  « météo » de la préparation ne dit que si les RÈGLES météo sont déclarées, et l'écran le dit.
- **Hors ligne** : lecture d'abord ; le cache SQLite (une clé par personne, `admin:<personne>:<section>_v1`) est rendu marqué
  (date et raison). Un refus du serveur (401, 403, personne désactivée, « à déclarer ») n'est **jamais** remplacé par le
  cache, et n'écrit rien. Le jour de référence de M5 et de M4 est celui de l'heure locale de l'appareil.
- **Preuves** : `tests/e2e/test_admin_appareil.py` appelle les huit outils par la vraie porte d'appareil (200 pour `admin`,
  403 pour `seller` et `employee`, sans rien écrire) et enregistre les vraies réponses dans `src/admin/fixtures/` ; Jest les
  fait passer par les lecteurs, les chargeurs et les modèles de vue. `tests/e2e/test_manques_m4_appareil.py` épingle la table
  des manques de l'app à ce que M4 produit (dans les deux sens). Régénération :
  `OPSYS_REGENERER_FIXTURES_MOBILE=1 pytest tests/e2e/test_admin_appareil.py -k fixture` (idem pour
  `test_manques_m4_appareil.py`, `test_vendeur_appareil.py` et `test_liste_employe_appareil.py`).

## Règles de l'app

- **Fail-closed.** Une valeur absente est dite absente ; une réponse illisible n'est jamais un succès ; un élément
  illisible est compté, jamais deviné. L'app ne calcule ni prix, ni solde, ni score, ni date.
- **Tout passe par la porte d'appareil** (`src/protocole/`) : le nom NU de l'outil, jamais une personne ni un rôle en
  argument (le core pose `_meta` d'après le jeton). Le serveur décide de la portée ; l'app ne la recalcule pas.
- **Écritures par la file sortante** (`src/outbox/`) : l'id de la mutation, créé sur l'appareil, est la clé d'idempotence.
  Un renvoi rend la réponse enregistrée, sans second effet. Un refus du serveur est un échec permanent dont le verdict est
  montré.
- **Vues par rôle appliquées deux fois** : le serveur, puis l'app (elle ne garde pas ce qu'un rôle ne doit pas voir).
- **Refus ou panne : une seule règle** (`src/protocole/echec.ts`, `enveloppeOutil.ts`), la même pour les trois profils. Une
  panne (réseau, délai, 408, 429, 5xx, réponse qui n'est pas celle du core) peut montrer un cache marqué. Un refus (401, 403,
  `refus_metier`, verdict d'identité) ne montre jamais le cache et n'écrit rien.
- **Une liste coupée par le socle n'est ni vide ni complète** : l'app le dit (« incomplète ») et n'écrase jamais son cache.
- **Les caches sont à une personne** (`src/stockage/cles.ts`) et sont effacés quand le serveur confirme une autre personne
  ou refuse l'appareil (`src/identite/caches.ts`, Loi 25). La file sortante, sa quarantaine et les brouillons locaux ne le
  sont pas (`docs/architecture/MOBILE.md`, « La file suit le jeton et la personne »).
- **Ce que le serveur écrit pour un agent n'est pas montré** : ni chemin de fichier du serveur, ni commande `opsys-metier`
  (`src/ecrans/texteSur.ts`). L'écran dit quoi faire en mots simples, ou le code seul.
- Textes en `fr-CA` (défaut) et `en-CA` (`src/i18n/`), clés vérifiées par Jest.

## `src/`

`roles/` garde de routes · `appairage/`, `identite/` appairage et identité (`caches.ts` : effacement des caches de l'ancienne
personne) · `protocole/` client `/tools/invoke` et règle « refus ou panne » (`echec.ts`) · `outbox/` file sortante et vidangeur ·
`stockage/` dépôt clé/valeur et registre des clés de cache (`cles.ts`) · `m2/`, `m3/`, `m4/`, `m6/`, `approbations/` contrats
des outils · `vendeur/` chargeurs, cache et fusion de pages du profil vendeur (`fixtures/` : vraies réponses du moteur) ·
`admin/` chargeurs, cache, lecteurs et câblage (`service.ts`) du profil admin, `composants.tsx` et `vuesChiffres.tsx` rendu
(`fixtures/` : vraies réponses du moteur) · `m4/dispatch`, `m5/tresorerie`, `m5/pagesPrevision`, `m8/` lecteurs des outils du
propriétaire · `today/` (`fixtures/` : vraies réponses du moteur), `checklist/`, `photos/`, `signature/`, `fichiers/` profil employé ·
`ecrans/` logique pure des écrans (`admin`, `chiffres`, `vueExecutive`, `chantiers` : modèles de vue dont chaque texte à
variables est un `Message`, clé i18n et variables ; `manquesM4` et `texteSur` : les manques de M4 en mots simples) · `i18n/`
textes (`locales/admin.*.ts` : le profil admin).

### Comptes admin (PLAN T4.22)

Depuis « À voir », `/comptes` présente trois lectures indépendantes : créances envoyées, comptes à payer et prérequis manquants de facturation. Les montants et totaux viennent de M5 ; un inconnu reste inconnu. L’âge des créances commence à l’envoi, sans inventer une échéance. Les deux vues AP ne sont jamais additionnées.

Le cache est personnel, normalisé et limité à la première page AP ; celui des créances dépend du jour local. Les suites AP sont des pages courantes en ligne qui remplacent la page affichée. Une réponse devenue ancienne après changement de filtre, rafraîchissement ou départ de l’écran est écartée. Les refus ne sont pas remplacés par le cache. Aucun paiement, envoi ni application du rapprochement proposé.

Preuves et limites : [audit du 7 octobre](../docs/reprise/COMPTES-M5-2026-10-07/AUDIT-COMPTES-M5-2026-10-07-r1.md). L’export JavaScript et le rendu React contrôlé ne qualifient pas Hermes, Expo SQLite ou un téléphone natif.

### Stock admin (PLAN T4.23)

Depuis « À voir », `/stock` lit disponibilité et digest M6 dans deux sections indépendantes. Les quantités décimales natives sont conservées, y compris les valeurs négatives à vérifier. Les unités ne sont pas fournies pour le stock ; le comptage physique n’est pas déduit du théorique. Les unités des lignes manquantes restent propres à ces lignes.

La disponibilité est une fenêtre native de 15 articles et 10 réservations actives, avec deux indicateurs de troncature distincts. Il n’existe ni total ni curseur ni suite fournie par ces outils. Le digest couvre les écarts enregistrés, même nuls, sans fenêtre journalière ; l’appel sans seuils ne calcule aucune suggestion et ne prouve pas l’absence de besoin d’achat.

Cache personnel minimal et normalisé, gardes avant/après chaque lecture ; refus sans repli, résultat ancien écarté après refresh/purge/changement de session. Aucun mouvement, commande ou inventaire n’est écrit par l’écran. [Audit et limites](../docs/reprise/STOCK-M6-2026-10-07/AUDIT-STOCK-M6-2026-10-07-r1.md). Le rendu React contrôlé et l’export JavaScript ne qualifient pas un téléphone natif.
