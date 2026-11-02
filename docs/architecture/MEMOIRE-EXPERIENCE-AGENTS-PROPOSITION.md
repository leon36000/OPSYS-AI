# Mémoire d'expérience des agents : proposition de conception

Statut : **proposition, rien n'est implémenté** (2026-11-02, ligne de base `e0424b040`). Fondée sur la veille
[VEILLE-MEMOIRE-EXPERIENCE-AGENTS-2026-11](../research/VEILLE-MEMOIRE-EXPERIENCE-AGENTS-2026-11.md) (ReasoningBank, Agent Memory Distillation, voisins, risques).
Elle prolonge, sans le remplacer, l'apprentissage continu gouverné de [M10-SOI-GRAPHE § 5](M10-SOI-GRAPHE.md) et la boucle de [M9-ATHENA § 7](M9-ATHENA.md).
Aucun code de production n'accompagne ce document. Tout ce qui est écrit au futur est une **intention à prouver**, pas une capacité.

## 1. But et non-buts

**But.** Qu'un agent de département, y compris un **petit modèle local** (4 à 8 Md de paramètres), fasse moins d'erreurs d'appel d'outil MCP et suive de meilleurs flux de travail,
grâce à de courts éléments d'expérience tirés de **réussites et d'échecs** passés (d'un enseignant fort local, de références écrites à la main, plus tard des signaux de production
sans contenu), approuvés par une personne, retirables.

**Non-buts.**
- Aucune **valeur** apprise (prix, solde, score, quantité, date, identifiant) : la mémoire enseigne une stratégie ou une convention d'appel, jamais une valeur (`AGENTS.md`).
- Aucun contournement d'approbation : un élément ne peut ni abaisser un niveau N, ni suggérer un détour, ni raccourcir le sas humain.
- Aucun entraînement de modèle, aucun achat de crédits, aucune donnée réelle avant EFVP.
- Aucune dépendance nouvelle dans le socle. Aucun service de mémoire externe.

## 2. Principes (hérités du dépôt et de la veille)

1. **Schéma fermé, texte borné.** Un élément n'a pas de champ libre non filtré. Le texte passe le garde-fou de texte et le masquage PII existants.
2. **Les oracles tranchent, les modèles proposent.** Un LLM peut rédiger un candidat ; il ne décide jamais qu'un essai est une réussite ni qu'un élément aide.
3. **Origine liée à l'écriture.** Chaque élément déclare d'où il vient ; les origines non fiables (courriel, document ingéré, web) sont **interdites** comme source d'induction.
4. **Append-only, état rejoué.** Registre chaîné comme les leçons ; jamais de suppression, des états (*archivé*, *révoqué*).
5. **Lié à la version de l'outil.** Un élément qui parle d'un outil porte l'**empreinte** du registre MCP ; si l'empreinte change, l'élément est *périmé* (quarantaine) jusqu'à nouvelle évaluation.
6. **Mesurer avant de croire** : chaque élément et l'ensemble sont évalués avec/sans mémoire, contre un témoin placebo et un RAG brut.
7. **Petit et rare** : au plus 1 flux + 2 exemples au début de tâche, au plus 1 fiche sur erreur (k=1 est quasi optimal chez AMD et ReasoningBank).

## 3. Types d'éléments

Trois genres, calqués sur les trois niveaux d'AMD, adaptés à la gouvernance OPSYS. Le genre est une valeur d'un vocabulaire fermé ; l'ensemble s'ajoute aux quatre genres de leçons existants.

| Genre | Rôle | Contenu autorisé | Interdit | Format |
|---|---|---|---|---|
| `strategie_flux` | Plan d'une tâche (quelles étapes, dans quel ordre, quelles vérifications) | Intention (vocabulaire fermé), 2 à 8 étapes de la forme « outil + condition de passage », points de contrôle | Valeur, nom de personne ou d'entreprise, lien, chiffre, tout outil absent du registre | Prose courte guidée par le code (modèle de phrase) |
| `exemple_sous_tache` | Appel type d'une sous-tâche | Séquence d'appels : nom d'outil du registre, **clés** des arguments, **marques de substitution typées** (`<MONTANT>`, `<ID_AFFAIRE>`, `<DATE>`), forme attendue de la réponse (clés), codes `REJ-…` possibles | Toute valeur réelle ou vraisemblable ; observation brute | Structure JSON validée contre `schema_entree` de l'outil |
| `convention_outil` | Piège ou règle d'appel d'un seul outil | Argument obligatoire souvent omis, énuméré valide, motif attendu, code `REJ-…` et correction, outil voisin à appeler avant | Conseil de contournement de l'approbation ; outil N3+ : seulement des conventions d'**arguments** | Fiche : (outil, empreinte, code, correction) |

Valeurs-sentinelles : tout exemple d'`exemple_sous_tache` embarque, pour la mesure seulement, des valeurs bidon reconnaissables (voir § 9) ; elles ne sont jamais promues en production.

**Enregistrement type** (fictif, cœur générique) :

```json
{
  "id_element": "sha256:…(contenu canonique)",
  "genre": "convention_outil",
  "departement": "m02-revenue-crm",
  "domaine": "affaires",
  "pack": null,
  "declencheur": {"outil": "m2_creer_opportunite", "code_refus": "REJ-…"},
  "contenu": {"cle_argument": "affaire_id", "regle": "forme lead_id ou <lead>~opp~<wct_id>", "correction": "relire l'affaire avec l'outil de liaison avant l'appel"},
  "portee_outils": [{"outil": "m2_creer_opportunite", "empreinte": "sha256:…"}],
  "provenance": {"origine": "fiche_deterministe", "registre_mcp_revision": 13, "version_generateur": "…"},
  "statut": "candidat"
}
```

(Les noms d'outils de l'exemple illustrent la forme ; le registre réel est la seule source des noms valides.)

## 4. Sources (d'où vient l'expérience)

| Source | Réussites | Échecs | Contenu conservé | Phase |
|---|---|---|---|---|
| **Réponses de référence** du gabarit d'évaluation (130 cas écrits à la main) | oui | non | Séquences d'outils attendues | A, sans modèle |
| **Trajectoires fictives d'un enseignant** (modèle local fort sur l'instance fictive d'évaluation, avec un enregistreur **propre au banc**, pas les traces de production) | oui | oui | Appels (outil, clés, substitutions), issues typées, codes `REJ` | A, bloquée par la mesure des modèles |
| **Refus d'outils** déjà déposés (POSTFLIGHT : outil, ok/refus, code) | non | oui | Outil + code, support en affaires distinctes | B (déjà existant) |
| **Journal d'approbations** (approuvé, refusé, corrigé par une personne) | oui | oui | Décision, niveau, outil, code ; **jamais** le texte corrigé | B |
| **Corrections humaines** (M1.13 : faits de correction, pas le texte du client) | oui | oui | Classe de correction, outil | B |
| **Résultat mesuré par le code** (M9 : sens de variation d'une mesure) | oui | oui | Sens seulement | hors périmètre ici |

**Règles d'admission des sources.**
- Phase A : **fictives seulement**. Aucune donnée d'affaires ne sert à induire.
- Phase B : seuls des **signaux sans contenu** (identifiants du registre, codes, issues, comptes). Le prolongement du POSTFLIGHT à la **forme** des arguments (clés présentes, types, jamais les valeurs) est un chantier propre (§ 11, J7).
- Phase C (non proposée) : toute induction depuis du contenu réel exige une EFVP Loi 25 et l'accord de Nathan.
- Les trajectoires **influencées par la mémoire** sont étiquetées (liste des éléments injectés) et **exclues de l'induction** sans témoin sans mémoire de la même tâche (anti reproduction d'erreurs).
- Aucune source n'est un contenu non fiable (courriel, pièce jointe, page web) : la règle de deux (`registre_mcp/rule_of_two.py`) classe ces surfaces ; elles sont **interdites** comme origine d'induction.

## 5. Cycle de vie

```
 candidat ──► évalué hors ligne ──► promu (N3, humain) ──► canari/ombre ──► complet ──► révoqué
    │             │ échec               │ refus              │ régression      │
    └── rejeté ◄──┴─────────────────────┘                    └── retour arrière┘
                         (périmé : l'empreinte d'un outil a changé → retour à « évalué hors ligne »)
```

| État | Entrée | Garde |
|---|---|---|
| `candidat` | produit par un générateur déterministe, un enseignant ou une personne | **Garde d'admission** (§ 7) : schéma, texte, outils du registre, aucune valeur ; refus typé `REJ-EXPERIENCE-…` |
| `evalue` | banc hors ligne (§ 9) | Aucune régression bloquante ; gain net > 0 avec borne basse d'intervalle > 0 sur les cas visés ; taux de copie de sentinelle nul ; garde du gabarit |
| `promu` | **décision humaine N3** motivée (comme `m10_decider_lecon`) | Évaluation favorable **sur le corpus de garde courant** (sinon refus comme `REJ-MNEMO-LECON-NON-EVALUEE`) |
| `canari` / `ombre` | tirage par hachage de (élément, clé de cas) à 1-50 %, un canari à la fois | Mode `ombre` : l'élément est calculé et **consigné « aurait été injecté »**, non injecté |
| `complet` | décision humaine après canari | Surveillance continue (§ 9.4) |
| `revoque` | retour arrière humain, ou *périmé* | Jamais supprimé ; l'historique reste |

Les transitions réutilisent `opsys.mnemo.promotion` (mêmes états, canari par hachage, retour arrière sans ordre strict). **Aucun élément ne s'applique seul** : la récupération le *rend lisible* au département, qui l'injecte selon son mode.

**Modes ombre / supervisé / autonome.** `ombre` : calcul et journalisation seulement (mesure du taux de déclenchement, aucun effet). `supervisé` : injection de la part canari et des éléments complets, visibles dans la console. `autonome` : même comportement ; **la décision r8 (mode autonome non activé tant que Nathan n'a pas tranché) s'applique telle quelle** : la mémoire d'expérience ne demande rien de plus et n'élargit aucun droit.

## 6. Récupération

**Au début de tâche** (bloc `experience` du paquet de contexte, préflight du moteur de contexte du Core) :
1. Filtre dur : (département, domaine, pack), statut `complet` ou `canari` tiré, empreintes d'outils **actuelles**.
2. Classement : recherche lexicale + similarité sur l'intention et les outils de la tâche (réutiliser le moteur de la base de connaissances : FTS5 + similarité exacte + fusion RRF, plongements locaux déjà prévus) ; **seuil minimal**, sinon rien (« rien » est une réponse valide).
3. Sélection : au plus **1 `strategie_flux` + 2 `exemple_sous_tache`** ; budget en **caractères** calculé par le code (comme le paquet actuel, 4 000 caractères pour les faits) ; jamais plus de 1 500 caractères d'expérience au départ (valeur de départ à mesurer).
4. Chaque élément injecté est **consigné** (id, version, empreinte) dans la trace de la tâche pour le calcul des compteurs et l'exclusion de l'induction.

**Sur erreur d'outil** (réactif, sans modèle) : clé exacte (outil, empreinte, code `REJ-…`) → **au plus une** `convention_outil`. Le plus sûr est que **l'outil lui-même** joigne l'indice à son refus structuré (champ `indice_correction`), pour que tous les clients MCP en profitent et que l'indice soit couvert par l'empreinte du registre. Rien n'est injecté en cas de succès.

Pas de décomposition de la tâche par le petit modèle (AMD en a besoin ; ici l'intention vient d'un vocabulaire fermé et des outils déjà exposés au département).

## 7. Anti-PII, anti-valeur, anti-injection (garde d'admission)

Réutilise `mnemo/vie_privee.py`, `garde_fou_texte` (profil `mnemo_texte` : longueur, lien, adresse, coordonnées, nom de client), `observabilite/pii.py` et le détecteur de secret. Règles propres :

1. Tout champ textuel est borné (≈ 400 caractères) et issu d'un **modèle de phrase** quand c'est possible.
2. **Aucun chiffre** hors d'un identifiant de registre (nom d'outil, nom d'argument, énuméré déclaré dans le schéma). Un nombre dans la prose est refusé.
3. Tout nom d'outil et tout nom d'argument doivent exister dans `registre.v1.json` (révision courante) et dans le `schema_entree` ; un exemple est **validé contre ce schéma** avec les marques de substitution.
4. Aucune consigne glissée (filtre de provenance) ; une consigne détectée est **refusée**, pas neutralisée.
5. Aucune mention de contournement (« sans approbation », « en passant par… ») ; pour un outil N3 ou plus, seul le genre `convention_outil` d'arguments est admis.
6. Aucun renseignement personnel : pseudonymes seulement dans les références de source ; les `ligne_id` sont des empreintes.

**Droit à l'effacement.** Les éléments ne contiennent aucun renseignement personnel par construction ; ils référencent leurs sources par empreinte opaque. L'effacement d'une affaire diminue le support d'un élément (support minimal : ≥ 3 affaires distinctes, comme `refus_recurrent`) et le fait passer à *à réévaluer* sans le détruire. La purge définitive reste une frontière humaine (limite déjà consignée, M10-SOI-GRAPHE § 9.12). Tout contenu *réel* (phase C) exigerait en plus une destruction vérifiée des sources.

## 8. Isolation

Clé de partition **(département, domaine)** obligatoire sur chaque élément et chaque lecture.
- **Département** : un département ne lit que ses éléments, plus ceux que la direction a marqués `partageable` par décision N3.
- **Domaine** : `affaires` et `developpement` sont deux espaces **séparés**, jamais fusionnés (ADR-0012, M10). Le domaine développement ne reçoit que des conventions de dépôt et d'outillage (aucun contenu d'affaires) ; mêmes états, même revue humaine.
- **Pack sectoriel** : un élément qui suppose le secteur porte `pack` (décision r7) ; le cœur reste neutre.
- Niveau de confidentialité : les éléments sont au niveau le plus bas (aucune donnée) mais **n'entrent pas** dans les paquets des départements non propriétaires sans partage explicite.

## 9. Mesure

### 9.1 Corpus fictif en français

Famille de cas de plus au format `opsys.evaluation.corpus/v1` (même exécuteur, mêmes attentes déterministes) : fictifs, `fictif: true`, courriels `@example.test`. Familles visées : appel d'outil correct ; **reprise après refus `REJ`** ; flux multi-étapes dans un département ; flux interdépartements ; refus et approbation (aucune régression) ; injection ; honnêteté (inconnu) ; québécois familier ; copie de valeurs (sentinelles). Les cas sont rédigés **avant** toute exécution, à la main, à partir des `SOUL.md` et des outils réels. Taille de départ : environ 12 cas par département (≈ 120), à ajuster par un calcul de puissance fait sur un pilote.

### 9.2 Plan d'expérience

- **Conditions** : (a) sans mémoire ; (b) mémoire d'expérience complète ; (c) **placebo** (éléments de même longueur d'un autre département) ; (d) **RAG brut** de trajectoires fictives ; (e) éléments **écrits par un humain** ; (f) niveau par niveau (flux seul, + exemples, + fiches).
- **Modèles** : petit (4-8 Md), moyen, enseignant ; paliers `local` / `rapide` / `standard` / `fort` du dépôt. *Quels modèles occupent quel palier n'est pas mesuré* (§ 12).
- **Répétitions** : ≥ 5 par cas et condition, température fixée et consignée. La variance sans mémoire est elle-même observée (un tiers a mesuré un écart de ± 1,6 point entre cinq passages sans mémoire sur ReasoningBank).
- **Séparation** : induction sur des **gabarits de cas** d'entraînement, évaluation sur d'autres gabarits ; récupération qui exclut le gabarit courant ; **manifeste d'audit haché** (banque, identifiants éligibles, modèle, invite) conservé avec chaque rapport. Idée reprise des demandes déposées par des tiers sur ReasoningBank (#17, #40), pas de leur code.
- **Statistique** : différences appariées par cas ; on rapporte les cas gagnés et perdus (discordants) et un intervalle (bootstrap par gabarit). Gain net > 0 à borne basse > 0 **et** zéro régression bloquante.

### 9.3 Mesures

Réussite par oracle ; nombre d'appels d'outils et de refus avant réussite ; tours ; refus de sécurité (doivent rester à 100 %) ; chiffres inventés (0) ; **taux de copie de sentinelles** (0) ; taux d'adoption de l'élément ; jetons injectés et jetons totaux ; latence ; **écart comblé** = (réussite avec − sans) / (enseignant − sans), avec intervalle, indéfini si l'écart enseignant/sans est trop petit.

### 9.4 En production (canari et surveillance)

Compteurs **utile / nuisible par élément** alimentés par des signaux déterministes seulement : un appel suivant l'injection réussi ou refusé, décision d'approbation, correction humaine ; jamais par un LLM. Dépassement d'un seuil → alerte et *conseil* de retour arrière ; seule une personne l'exécute (comme `m10_surveiller_lecons`). Plafond du nombre d'éléments actifs par (département, genre) ; retrait par contribution mesurée.

### 9.5 Validation du banc lui-même

Un **répondant double sensible à la mémoire** (comme les répondants de référence, dangereux et inventif existants) : il suit un élément quand il y en a un. Le banc doit (i) mesurer un gain avec un bon élément, (ii) détecter une régression avec un élément nocif planté, (iii) détecter une copie de sentinelle, (iv) refuser un élément qui contourne l'approbation. Sans cette preuve, une mesure sur un vrai modèle ne vaut rien. Elle ne dit rien d'un modèle réel.

## 10. Où ça se branche

| Point | Branchement | Remarque |
|---|---|---|
| **M10 leçons** (`opsys.mnemo`) | Nouveaux genres, même registre chaîné, mêmes décisions N3 et événement `m10.lecon_decidee` ; module voisin `mnemo` pour les éléments rédigés (nom à décider) | Le **texte d'une leçon actuelle est un gabarit du code** ; ici un texte rédigé est admis seulement après la garde d'admission et une décision humaine |
| **M10 préflight** (`m10_contexte_preflight`, `m10_paquet_contexte_affaire`) | Bloc additif `experience`, budget en caractères | Ne change pas les quatre couches que le Core valide |
| **M10 POSTFLIGHT** (`m10_deposer_faits_candidats`) | Source de refus d'outils (déjà là) ; extension à la forme des arguments : chantier séparé | Les traces de production restent **sans contenu** |
| **M9 boucle décision → résultat → leçon** | **Aucun flux automatique** : les leçons stratégiques de la direction restent au niveau FINANCIAL, hors expérience d'agent | Ressource partagée : la promotion et la surveillance |
| **Registre MCP** | Tableau « mémoire fonction » ci-dessous ; l'outil joint l'indice à son refus | Chaque élément `convention_outil` lie (outil, empreinte) |
| **Gabarit d'évaluation** | Famille de cas + variante de requête `memoire` + répondant double | Rien n'est montré aux attentes |
| **Console** (`/plateforme/mnemo`) | Éléments candidats, évaluation, compteurs ; décision N3 | Lecture seule comme aujourd'hui ; décision par l'outil N3 |
| **Traces** | Liste des éléments injectés par tâche (identifiants seulement) | Attribut borné ; pas de contenu |

**Tableau du registre MCP pour la mémoire « fonction »** (une ligne par outil exposé, 636 outils à la révision 13 : 332 N0, 14 N1, 123 N2, 138 N3, 23 N4, 6 N5) :

| Colonne | Source | Rôle |
|---|---|---|
| `outil`, `departement`, `niveau`, `surface` | registre scellé | Clé et périmètre ; limite le genre admis pour N3+ |
| `empreinte` | registre scellé (sha256 de nom + description + schéma) | Péremption automatique de la fiche |
| `cles_obligatoires`, `enumeres`, `motifs` | **dérivés du `schema_entree`** par le code | Fiche déterministe, aucune rédaction |
| `codes_refus_observes` | refus déposés (POSTFLIGHT), codes du manifeste | Déclencheur de la fiche |
| `fiche_id`, `statut`, `empreinte_fiche` | registre d'éléments | Lien et état |
| `support` | affaires/épisodes distincts | Seuil d'admission |

Démarrage par les outils **les plus refusés** d'abord, pas les 636 d'un coup.

## 11. Jalons livrables (petits, avec preuve exigée)

Chaque jalon suit la preuve exigée du dépôt : tests rouges avant le code, au moins 5 mutations tuées, cas négatifs et d'abus, limites dites. Aucun n'écrit « qualifié » pour ce qui tourne avec un double.

| Jalon | Contenu | Preuve exigée | Dépend de | Bloqué ? |
|---|---|---|---|---|
| **J1 Schéma et garde d'admission** | Types d'éléments, registre chaîné, états, refus `REJ-EXPERIENCE-…`, validation contre `registre.v1.json` | Tests rouges puis verts ; entrées hostiles (consigne, PII, faux nom d'outil, valeur, contournement d'approbation) ; mutations (désactiver la garde des chiffres, du registre, de l'origine) | — | Non |
| **J2 Banc avec/sans mémoire** | Famille de cas, variante de requête, répondant double sensible à la mémoire, manifeste d'audit, statistiques appariées | Le banc détecte gain, régression, copie de sentinelle, contournement ; un élément nocif planté est refusé | J1 | Non |
| **J3 Fiches de convention d'outil déterministes** | Génération depuis `schema_entree` et codes `REJ-…`, lien à l'empreinte, indice joint au refus de l'outil en mode ombre | Fiche = fonction pure du schéma ; changement d'empreinte ⇒ *périmé* ; aucun indice en cas de succès ; registre rescellé (`opsys-metier registre-mcp verifier`, puis `sceller`) | J1 | Non |
| **J4 Mesure réelle sur paliers locaux** | Banc sur ≥ 2 paliers, avec/sans, placebo, RAG brut | Rapports hachés ; décision écrite « on continue ou on arrête » | J2, J3, **modèles mesurés** | **Oui** (modèles non qualifiés sur GB10) |
| **J5 Éléments de l'enseignant** | Enregistreur du banc, trajectoires fictives, rédaction de candidats par l'enseignant, filtrage par J1 | Chaque candidat refusé ou admis avec raison ; amorçage possible avec les 130 réponses de référence | J1, J2 ; enseignant local | Partiellement (enseignant local non mesuré) |
| **J6 Promotion, canari, retour arrière, console** | Outils N3, tirage par hachage, surveillance, page Mnémo | Tests de transition (parité avec `opsys.mnemo.promotion`) ; registre MCP rescellé ; compteur d'outils régénéré | J1 | Non |
| **J7 Signaux de production sans contenu** | Forme des arguments (clés, types) dans le POSTFLIGHT ; compteurs d'approbation | Test que **aucune valeur** ne sort ; revue Loi 25 | J6 ; EFVP si doute | Oui si EFVP demandée |
| **J8 Pilote MemOS (plugin local), optionnel** | Bac à sable OpenClaw **fictif**, témoin « boîte noire » | Compatibilité avec le fork du Core ; ce qu'il stocke (PII) ; coût | J2 | Accord de Nathan |

Par défaut, J1 → J2 → J3 → J6 peuvent avancer **sans aucun modèle**. Le premier jugement utile (J4) attend les modèles.

## 12. Ce qui est bloqué ou doit être décidé

- **Modèles locaux non mesurés** : la qualification de vLLM sur GB10, les modèles occupant les paliers `local`/`rapide`/`standard`/`fort`, la tenue du français sur les appels d'outils sont **ouverts** ; le répondant passerelle du gabarit n'a jamais été exécuté.
- **Enseignant** : modèle local fort sur GB10 (non mesuré) ou références écrites à la main. Aucun achat de crédits sans l'accord de Nathan.
- **Rôle d'approbation** : qui décide la promotion N3 d'un élément ? (propriétaire seulement, ou responsable de département).
- **Mode autonome (décision r8)** : la mémoire d'expérience reste en `ombre` / `supervisé` tant que Nathan n'a pas tranché.
- **EFVP Loi 25** avant toute induction depuis du contenu réel (phase C) et avant J7 si les formes d'arguments étaient jugées identifiantes.
- **Licence d'AMD** : aucune ; on n'emprunte que l'idée publiée. Question à un avocat si l'on voulait davantage ([QUESTIONS-AVOCAT](../compliance/QUESTIONS-AVOCAT.md)).
- **Hypothèses non prouvées** (veille § 4-5) : transfert en français, sur MCP gouverné, sur des petits modèles ; gain des fiches de fonction (le plus faible d'AMD) ; apport de MaTTS (écarté en production).

## 13. Limites de cette proposition

- Fondée sur des **lectures** (code et articles), sans exécution ; les chiffres de ReasoningBank et d'AMD ne sont pas répliqués pour nous.
- Les seuils proposés (1 + 2 éléments, 1 500 caractères, 5 répétitions, support ≥ 3) sont des **valeurs de départ** à calibrer sur le banc.
- La forme exacte des modules (noms, tables, migration) n'est pas décidée ; un schéma de table imposerait une migration alembic et des tests de montée/descente, à décider en J1 (une alternative sans table : registre chaîné existant).
- Le déclenchement « sur erreur d'outil » modifie le contrat de réponse de l'outil (champ ajouté) : il passera par le registre MCP (empreinte) et ses tests de contrat.
