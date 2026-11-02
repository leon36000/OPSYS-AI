# Mémoire d'expérience des agents : jalons J1 et J2 (livré)

Statut au 2026-11-02 (ligne de base `ea631e4bc`) : **J1 (schéma fermé et garde d'admission) et J2 (banc « avec / sans mémoire » et répondant double qui le valide)
sont livrés et éprouvés par des tests. Aucun modèle réel n'est appelé, aucun élément n'est lu par un département, rien n'est appliqué.** Tout le reste de la
proposition (J3 fiches déterministes, J4 mesure réelle, J5 enseignant, J6 promotion/canari/console, J7 signaux de production, J8 pilote MemOS) n'est **pas** construit.

La conception et la veille qui la fondent (ReasoningBank, Agent Memory Distillation, risques) sont dans `MEMOIRE-EXPERIENCE-AGENTS-PROPOSITION.md` et
`docs/research/VEILLE-MEMOIRE-EXPERIENCE-AGENTS-2026-11.md`, sur la branche `claude/veille-memoire-agents` (pas encore sur la ligne au moment de cette livraison).
Ce document dit ce qui a été **implémenté** et prouvé, pas ce qui est espéré.

## J1. Le schéma fermé et la garde d'admission (`opsys.mnemo.experience`)

Trois genres d'élément (`strategie_flux`, `exemple_sous_tache`, `convention_outil`), chacun un objet à champs exacts : département, domaine (`affaires` ou
`developpement`, jamais mêlés), pack éventuel, déclencheur (outil, code `REJ-…`), contenu typé, origine. Un élément admis reçoit son identifiant (`sha256` du contenu canonique),
la liste (outil, **empreinte**) de sa portée et la révision du registre MCP : si l'empreinte d'un outil change, il est `perime` (rejoué à la lecture).

| Règle de la garde | Code |
|---|---|
| origine non fiable (courriel, document ingéré, web, pièce jointe, conversation client) ; origine inconnue ; origine réservée au code | `…-ORIGINE-NON-FIABLE`, `-INCONNUE`, `-RESERVEE` |
| genre ou domaine inconnu ; développement : conventions d'outillage seulement | `…-GENRE-INCONNU`, `-DOMAINE-INCONNU`, `-DOMAINE-GENRE` |
| tout nom d'outil existe au registre MCP **scellé** et dans la portée du département (ou commun `opsys`) | `…-OUTIL-INCONNU`, `-OUTIL-HORS-PORTEE` |
| tout nom d'argument existe au `schema_entree` ; les obligatoires sont présents ; une valeur est une **marque typée** (`<MONTANT>`, `<ID_AFFAIRE>`, `<DATE>`…) ou un énuméré du schéma, jamais une valeur | `…-ARGUMENT-INCONNU`, `-ARGUMENT-MANQUANT`, `-VALEUR` |
| aucun chiffre dans la prose, sauf un identifiant du registre ou un code de refus | `…-CHIFFRE` |
| aucun renseignement personnel, secret ni consigne glissée (garde-fou de texte, détecteur de secret et filtre de provenance **existants**, refus et non neutralisation) | `…-DONNEE-PERSONNELLE`, `-SECRET`, `-CONSIGNE` |
| aucun conseil de contourner l'approbation, une garde ou un refus | `…-CONTOURNEMENT` |
| un outil N3 ou plus ne figure que dans une **convention d'arguments** | `…-NIVEAU-ELEVE` |
| texte borné (400 caractères), plafond de 50 candidats par (département, domaine, genre), forme exacte | `…-TEXTE`, `-PLAFOND`, `-FORME` |

Un refus ne cite jamais le contenu refusé. Le registre `experiences` (chaîné, append-only) garde `experience_proposee` (état `candidat`) et `experience_refusee` (le code,
l'empreinte de ce qui a été soumis, le genre et le département quand ils sont bien formés, **jamais** le contenu). Outils : `m10_proposer_experience` (T1/N2, origines
`reference_ecrite_main` ou `enseignant_fictif` seulement) et `m10_lire_experiences` (T0/N0). Aucun droit d'appareil.

## J2. Le banc « avec / sans mémoire » (`opsys.evaluation.memoire_experience`)

- **Cas** : `departments/m10-memoire/evals/experience.v1.yaml`, 15 cas écrits à la main au format du gabarit commun (`opsys.evaluation.corpus/v1`), 7 catégories, jugés par
  les mêmes attentes déterministes (`executeur.verifier_cas`) ; 4 cas « piège » (l'agent seul oublie un argument obligatoire), 4 cas « contrôle » (réussissent seuls : détectent
  une régression), cas de sécurité (refus, injection, honnêteté). Les appels sont confrontés au registre scellé (outil, portée, schéma) et **jamais exécutés**.
- **Conditions** : `sans_memoire`, `avec_memoire` (au plus 1 flux, 2 exemples, 1 convention applicables à l'outil attendu), `placebo` (autant d'éléments, pour un autre outil).
  Les exemples sont rendus avec des **valeurs-sentinelles** à la place des marques ; recopier une sentinelle est mesuré.
- **Statistique** : différences appariées par cas, cas gagnés et perdus, intervalle bootstrap **par gabarit** (graine consignée), manifeste d'audit haché (banque, éléments, répondant,
  configuration, registre MCP). Décision : gain net > 0 avec borne basse > 0, zéro régression bloquante, zéro copie de sentinelle, sécurité intacte.
- **Le banc se valide lui-même** (`RepondantSensibleMemoire`, double déterministe qui suit l'expérience injectée) : un bon élément donne un gain démontré ; un élément **nocif** planté est vu
  comme régression bloquante ; une **copie de sentinelle** condamne l'élément ; un conseil de **contournement** est refusé par la garde et, forcé, échoue au banc ; le placebo et un
  répondant qui ignore la mémoire ne donnent **aucun** gain ; les doubles dangereux et inventif du gabarit sont vus. Tests : `tests/test_experience_j1.py`, `tests/test_experience_banc.py`,
  `departments/m10-memoire/tests/test_experience_outils.py`.

## Ce qui n'est PAS prouvé (sans euphémisme)

- **Rien sur un modèle réel.** Les répondants du banc sont des doubles : ils prouvent que le banc *sait mesurer*, pas que la mémoire aide un petit modèle, ni en français, ni sur MCP.
- Les seuils (1 flux + 2 exemples + 1 convention, 400 caractères, 50 candidats, 5 répétitions) sont des valeurs de départ non calibrées ; les répondants étant déterministes, la variance entre répétitions est nulle par construction.
- Le corpus de cas est petit (15), d'un seul auteur et d'un seul département (M10) ; biais à corriger par un second rédacteur.
- Pas de séparation induction / évaluation (les éléments sont écrits à la main : l'induction par un enseignant est J5), pas de RAG brut, pas de niveau par niveau, pas d'« écart comblé ».
- La garde repose sur des motifs (chiffres, contournement, consigne, PII) : une formulation d'attaque qui n'y ressemble pas passera la garde ; c'est le banc, puis la promotion humaine N3 (non construite), qui la rattrapent.
- Un élément `candidat` n'est lu par aucun département ni injecté dans aucun paquet : le branchement (récupération au début de tâche et sur erreur d'outil) est J6 et au-delà. La décision r8 (mode autonome réservé au propriétaire) s'applique telle quelle.
