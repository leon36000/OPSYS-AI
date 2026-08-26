# RAPPORT D'AUDIT — OPSYS-AI

> Ce fichier est **généré** par `audit/rapport.py` depuis `audit/constats/*.json`.
> Ne pas l'éditer : toute modification manuelle sera écrasée à la prochaine
> exécution. Chaque affirmation ci-dessous vient d'un constat validé par
> `audit/contrats.py`, dont la sévérité est **recalculée** par `audit/rubrique.py`
> au moment de la génération — un constat dont la sévérité aurait été retouchée à
> la main empêche la génération.

## Ce que cet audit prouve, et ce qu'il ne prouve pas

Il prouve que, pour chaque constat listé, un témoin rejouable sort en code non nul
sur le dépôt, et que la réfutation a été tentée avant de conclure.

Il ne prouve **pas** qu'il n'existe aucun autre défaut. Une zone sans constat n'est
réputée propre que si elle porte une preuve de morsure — un défaut synthétique
injecté et détecté. Les zones sans constat ni preuve de morsure ne sont pas
couvertes, et le tableau de complétude le dit.

## Constats

| Constat | Sévérité | Lot | Classe | Titre |
|---|---|---|---|---|
| `AUD-A1-001` | **critique** | A1 | defaut-code | Le verificateur de registres rapporte OK sur un fichier absent et sort en code 0. |
| `AUD-A1-002` | **critique** | A1 | defaut-code | Un module sans instruction executable passe le controle de statut en code 0. |
| `AUD-A2-001` | **critique** | A2 | defaut-code | Aucun des 646 verdicts de reviews/ ne porte les champs que le depouilleur exige. |
| `AUD-A2-002` | **critique** | A2 | defaut-code | Une entree a quitte un registre en ajout seul sans que la verification le voie. |
| `AUD-A2-003` | **critique** | A2 | defaut-code | Aucun verdict ne porte de lien vers le code qu'il approuve. |
| `AUD-A2-004` | **critique** | A2 | defaut-code | Aucun tour de revue ne conserve son pack : le sceau n'est recalculable par personne. |
| `AUD-A3-001` | **critique** | A3 | ecart-plan | Quatre identifiants sont cites comme references au referentiel sans y etre definis. |
| `AUD-A3-002` | **critique** | A3 | ecart-plan | Les services transversaux de D-010 ne sont pas dans le core, l'un vit dans un module. |
| `AUD-A4-001` | **critique** | A4 | defaut-code | Sept copies d'encoder_canonique, deux conventions de retour inverses. |
| `AUD-A4-002` | **critique** | A4 | ecart-plan | Le code de production importe une bibliotheque tierce dans 22 fichiers. |
| `AUD-A5-001` | **critique** | A5 | faille-securite | RESOLU (PR #567, issue #565) -- Les tests d'autorisation et de coffre a secrets tournent dans un job non bloquant. |
| `AUD-A7-001` | **critique** | A7 | incoherence-documentaire | Six README de module annoncent moins de stories que ce qui a ete revu. |

## Détail, constat par constat

### AUD-A1-001 — Le verificateur de registres rapporte OK sur un fichier absent et sort en code 0.

- **sévérité** : critique — calculée par la règle `regle_critique:frontiere_t3`
- **entrées mesurées** : contrat_gele='D-042', frontiere_t3=True, gate_couvrant=True, rayon=4
- **emplacement** : `scripts/ledger_append.py:34`, `.github/workflows/ci.yml:13`
- **témoin** : `audit/temoins/AUD-A1-001/reproduction.py` — rejoué, rouge comme attendu

**Ce que la mesure a donné**

```
3 manifestations : installations.jsonl absent rapporte OK ; preuves.jsonl (49 entrees) supprime -> OK rc=0 ; les 3 registres (101 entrees) supprimes -> OK rc=0
```

**Réfutation tentée**

Refutation tentee par deux voies. (1) Le verificateur echoue-t-il deja sur la copie intacte, ce qui rendrait la mesure sans valeur ? Non : rc=0 sur l'etat intact, la pre-condition tient. (2) Le gate est-il non couvrant, ce qui rendrait le defaut sans portee ? Non : gh api sur la protection de branche renvoie ["gates"], et ce job execute la commande sous le libelle « Ledger integrity (D-042) ». Les deux voies de refutation echouent : le constat tient.

### AUD-A1-002 — Un module sans instruction executable passe le controle de statut en code 0.

- **sévérité** : critique — calculée par la règle `regle_critique:contrat_gele_rayon_ge_2`
- **entrées mesurées** : contrat_gele='REG-12', frontiere_t3=False, gate_couvrant=True, rayon=2
- **emplacement** : `scripts/statut_lint.py:59`, `.github/workflows/ci.yml:14`
- **témoin** : `audit/temoins/AUD-A1-002/reproduction.py` — rejoué, rouge comme attendu

**Ce que la mesure a donné**

```
Module M99-fantome fabrique : arborescence conforme, README « PARTIAL (vague 1 livree) », 1 fichier source sans aucune instruction executable, 1 test sans assertion, inscrit au registre. statut_lint -> rc=0, module NON signale.
```

**Réfutation tentée**

Deux refutations tentees, dont une a corrige la mesure. (1) Le controle refuse-t-il le module creux ? Une premiere version du temoin n'inscrivait PAS le module au registre : le controle le rejetait alors, mais pour une garde ANTERIEURE (« present sur le disque, absent du registre »). On aurait conclu que la vacuite etait detectee alors que rien ne l'avait examinee — le decor doit etre juste pour que le refus porte sur ce qu'on mesure. Une fois le module inscrit, rc=0. (2) Le controle est-il execute par un gate bloquant, ce qui donnerait sa portee au defaut ? Oui : statut_lint.py est une etape du job « gates », seul check exige par la protection de branche. Ce que le constat n'affirme PAS : qu'un tel module existe dans le depot — la sonde A1 mesure le contraire, 7771 instructions sur 135 fichiers. Il etablit que rien n'empecherait qu'il y en ait un.

### AUD-A2-001 — Aucun des 646 verdicts de reviews/ ne porte les champs que le depouilleur exige.

- **sévérité** : critique — calculée par la règle `regle_critique:contrat_gele_rayon_ge_2`
- **entrées mesurées** : contrat_gele='REG-05', frontiere_t3=False, gate_couvrant=False, rayon=3
- **emplacement** : `scripts/tally.py:8`, `scripts/consensus_run.py:250`
- **témoin** : `audit/temoins/AUD-A2-001/reproduction.py` — rejoué, rouge comme attendu

**Ce que la mesure a donné**

```
reviews : 646 verdicts lus, 0 exploitable, champs manquants ['reviewer','vendor'] ; 179 dossiers a >=3 verdicts, 0 depouillable ; execution reelle sur reviews/M4-S009-r1 -> rc=2 « champ manquant 'reviewer' »
```

**Réfutation tentée**

Trois refutations tentees. (1) L'echantillon est-il non representatif ? Non : la mesure porte sur les 646 verdicts, pas sur un tirage. (2) tally.py est-il casse en soi, ce qui deplacerait le constat ? Non : 31 des 40 verdicts de registries/verdicts/ passent, car consensus_run.py normalise reviewer et vendor avant d'ecrire — le depouilleur fonctionne quand on lui donne le schema qu'il attend. (3) L'identite du relecteur est-elle recuperable autrement ? Elle est dans le NOM du fichier, mais tally.py ne la lit pas, et un nom de fichier n'est pas scelle par le prompt_sha256. Les trois voies echouent : le constat tient, et il vise l'absence de contrat commun entre les deux producteurs, non tally.py.

### AUD-A2-002 — Une entree a quitte un registre en ajout seul sans que la verification le voie.

- **sévérité** : critique — calculée par la règle `regle_critique:frontiere_t3`
- **entrées mesurées** : contrat_gele='D-042', frontiere_t3=True, gate_couvrant=True, rayon=2
- **emplacement** : `registries/ledger/preuves.jsonl:1`, `scripts/ledger_append.py:32`
- **témoin** : `audit/temoins/AUD-A2-002/reproduction.py` — rejoué, rouge comme attendu

**Ce que la mesure a donné**

```
preuves.jsonl : 49 entrees, chaine COHERENTE ; 1 hachage ajoute puis disparu — c6e6873e (tache M7-S002), ajoute par a3b0230, retire par le revert 555ec49 de la PR #37. decisions.jsonl et executions.jsonl : 0 disparu.
```

**Réfutation tentée**

Trois refutations tentees. (1) L'entree a-t-elle ete reintroduite ailleurs dans le fichier ? Non : le temoin ne retient un hachage que s'il est absent du contenu courant, et il l'est. (2) La chaine porte-t-elle une trace de la coupure, qui rendrait la disparition detectable ? Non : elle est coherente sur les 49 entrees, et aucune ligne ne pointe sur le hachage disparu — elle a donc ete recalculee. (3) Le defaut est-il isole a un accident de ce registre ? Non : il est structurel, puisque verify ne compare a aucun etat anterieur et validerait de meme n'importe quelle reecriture coherente. Ce que le constat n'affirme PAS : que la suppression soit malveillante. Elle resulte d'un revert de PR, operation legitime. Ce qu'il etablit est qu'un journal d'ajout a SUIVI ce revert, alors qu'une annulation aurait du s'y inscrire comme une entree SUPPLEMENTAIRE.

### AUD-A2-003 — Aucun verdict ne porte de lien vers le code qu'il approuve.

- **sévérité** : critique — calculée par la règle `regle_critique:contrat_gele_rayon_ge_2`
- **entrées mesurées** : contrat_gele='REG-04', frontiere_t3=False, gate_couvrant=False, rayon=2
- **emplacement** : `reviews/M1-S005/DeepSeek-V4-Pro.verdict.json:1`, `scripts/consensus_run.py:250`
- **témoin** : `audit/temoins/AUD-A2-003/reproduction.py` — rejoué, rouge comme attendu

**Ce que la mesure a donné**

```
691 verdicts inventories ; cles : verdict, objections, date_heure, prompt_sha256, reviewer_model, modele_servi, gateway_resilience. 0 verdict porte un champ liant a un commit, un arbre, une branche ou une empreinte de diff.
```

**Réfutation tentée**

Deux refutations tentees. (1) Le lien existe-t-il sous un nom inattendu ? Le temoin cherche douze racines differentes (commit, sha1, diff_sha, head, branche, revision, tree, arbre, base, merge...) plutot qu'un nom precis, pour ne pas manquer une convention locale : aucune ne repond. (2) Le sceau prompt_sha256 suffit-il a lier au code ? Non : il scelle le PACK, ce qui prouve que les relecteurs ont lu le meme texte — garantie reelle, que le constat ne remet pas en cause — mais rien ne relie ce pack au commit fusionne. Ce que le constat n'affirme PAS : qu'un code non approuve ait ete fusionne. Il etablit que rien, dans le dossier de revue, ne permettrait de le savoir.

### AUD-A2-004 — Aucun tour de revue ne conserve son pack : le sceau n'est recalculable par personne.

- **sévérité** : critique — calculée par la règle `regle_critique:contrat_gele_rayon_ge_2`
- **entrées mesurées** : contrat_gele='REG-05', frontiere_t3=False, gate_couvrant=False, rayon=2
- **emplacement** : `reviews/M1-S001/round-1:1`, `reviews/M10-S006/round-1:1`
- **témoin** : `audit/temoins/AUD-A2-004/reproduction.py` — rejoué, rouge comme attendu

**Ce que la mesure a donné**

```
57 tours porteurs de verdicts, 0 avec pack archive, 57 SANS. 2 tours a sceau multiple, dont l'un nomme round-3-sceau-rompu (donc documente).
```

**Réfutation tentée**

Deux refutations tentees. (1) Le pack est-il archive sous un nom inattendu ? Le temoin cherche quatre extensions et trois racines de nom (pack, prompt, soumission) plutot qu'un nom precis : aucune ne repond sur aucun des 57 tours. (2) Le sceau suffit-il sans le pack ? Non, et c'est le coeur du constat : un prompt_sha256 partage prouve que trois relecteurs ont lu le MEME texte — garantie reelle, mesuree ici et non remise en cause — mais sans le texte, il n'atteste pas QUEL texte. Nul ne peut verifier que le pack contenait le diff annonce, ni qu'il n'a pas ete substitue. Ce que le constat n'affirme PAS : que des sceaux soient faux ou qu'un pack ait ete remplace. Il etablit qu'aucune de ces deux hypotheses n'est verifiable. Ce constat complete AUD-A2-003 : non seulement le verdict ne pointe vers aucun commit, mais le texte juge n'est pas conserve.

### AUD-A3-001 — Quatre identifiants sont cites comme references au referentiel sans y etre definis.

- **sévérité** : critique — calculée par la règle `regle_critique:contrat_gele_rayon_ge_2`
- **entrées mesurées** : contrat_gele='REG-12', frontiere_t3=False, gate_couvrant=False, rayon=2
- **emplacement** : `docs/decisions/ADR-0003-RATIFICATION.md:16`, `registries/verdicts/phaseC-live/Grok-4.5.json:1`
- **témoin** : `audit/temoins/AUD-A3-001/reproduction.py` — rejoué, rouge comme attendu

**Ce que la mesure a donné**

```
91 identifiants au plan, 80 cites dans le depot, 7 hors referentiel. Parmi eux : R-037, R-038, R-039 sont DEFINIS dans docs/decisions/ADR-0003-RATIFICATION.md — extensions ratifiees, legitimes. Restent D-047 (cite dans ADR-0003), R-034, R-035, R-036 (cites uniquement dans des verdicts de modeles) : aucune definition nulle part.
```

**Réfutation tentée**

Trois refutations tentees. (1) Sont-ils definis dans un document de decision posterieur, ce qui en ferait des extensions legitimes ? Le temoin cherche une DEFINITION (identifiant ouvrant son propre enonce, en tete de ligne ou apres une puce) et non une simple mention : R-037/038/039 repondent et sont ecartes du constat ; les quatre autres non. (2) La regle de detection est-elle trop stricte, prenant une mention pour une absence ? Elle a justement distingue trois extensions legitimes sur sept candidats — elle discrimine. (3) S'agit-il d'une coquille isolee ? Non : R-034, R-035 et R-036 n'apparaissent dans AUCUN document du depot, uniquement dans des sorties de modele, et D-047 a ete repris dans un ADR ratifie. Ce que le constat n'affirme PAS : que ces identifiants soient malveillants ni qu'ils designent des risques imaginaires. Il etablit qu'un lecteur cherchant a les resoudre ne trouverait rien. Quatrieme point, souleve en revue par deux relecteurs : « D-047 est cite dans un ADR ratifie, il ne devrait pas compter ». La distinction est CITE contre DEFINI. ADR-0003 ecrit « Le roster D-040/D-047 est adopte tel quel » : c'est une mention, elle ne dit pas ce qu'est D-047. Le temoin l'affiche desormais explicitement (« CITE dans une decision sans y etre DEFINI ») plutot que de laisser le lecteur y voir une contradiction. Cinquieme point, objection critique d'un troisieme relecteur : le temoin annoncait « 324 identifiants » la ou le plan en fige 91. CONFIRMEE et corrigee : il faisait .split() sur le fichier de referentiel, dont la seconde section porte le texte de la decision D-010 ; chaque mot etait compte pour un identifiant. Le resultat restait juste — les identifiants reels figuraient bien dans l'ensemble — mais le chiffre publie etait faux, et un audit qui publie un chiffre faux se disqualifie sur le reste.

### AUD-A3-002 — Les services transversaux de D-010 ne sont pas dans le core, l'un vit dans un module.

- **sévérité** : critique — calculée par la règle `regle_critique:contrat_gele_rayon_ge_2`
- **entrées mesurées** : contrat_gele='D-010', frontiere_t3=False, gate_couvrant=False, rayon=4
- **emplacement** : `core/src/.gitkeep:1`, `Modules M/M7-marketing/src/content/approval.py:1`
- **témoin** : `audit/temoins/AUD-A3-002/reproduction.py` — rejoué, rouge comme attendu

**Ce que la mesure a donné**

```
5 services enumeres par D-010 : 1 dans le core (Autorisation fine -> core/src/authz/), 1 dans un module (Approval Engine -> Modules M/M7-marketing/src/content/approval.py), 3 absents du depot entier (Audit/Ledger, Gate Engine, Bus de notifications).
```

**Réfutation tentée**

Trois refutations tentees, dont une a REUSSI et a corrige le constat. (1) Les services existent-ils sous un nom technique different du libelle du plan ? OUI pour l'autorisation fine : « Autorisation fine » ne se trouve nulle part litteralement, mais core/src/authz/ l'implemente. Une premiere mesure annoncait « 5 services a zero fichier » : elle etait FAUSSE, et le temoin cherche desormais par mots-cles. (2) Les trois absents sont-ils implementes ailleurs sous un autre nom ? Les mots-cles couvrent ledger, audit_log, gate_engine, event_bus, bus : aucun ne repond hors du core. (3) L'ecart est-il sans objet puisque rien n'est en production ? C'est vrai et le constat le dit — mais D-010 ne conditionne pas sa decision a une mise en production, et l'approbation vit deja dans un module, ce que la decision voulait precisement empecher. Ce que le constat n'affirme PAS : que ces services soient necessaires des aujourd'hui.

### AUD-A4-001 — Sept copies d'encoder_canonique, deux conventions de retour inverses.

- **sévérité** : critique — calculée par la règle `regle_critique:contrat_gele_rayon_ge_2`
- **entrées mesurées** : contrat_gele='R-011', frontiere_t3=False, gate_couvrant=True, rayon=7
- **emplacement** : `Modules M/M2-revenue-crm/src/m2_revenue_crm/encodage.py:1`, `Modules M/M10-memoire/src/m10_memoire/encodage.py:1`
- **témoin** : `audit/temoins/AUD-A4-001/reproduction.py` — rejoué, rouge comme attendu

**Ce que la mesure a donné**

```
7 copies executees sur la MEME valeur : 6 rendent la chaine '30:["__dict__",[["a",1],["b",2]]]', M2-revenue-crm rend le digest sha256 'ade50aabfe0b3d3...'.
```

**Réfutation tentée**

Trois refutations tentees. (1) La divergence vient-elle d'une lecture erronee du code ? Non : le temoin n'a pas lu, il a IMPORTE chaque copie dans un sous-processus isole et lui a fait encoder la meme valeur. (2) La signature ou le type de retour signalent-ils la difference ? Non : les deux renvoient str, les deux s'appellent encoder_canonique, aucune annotation ne distingue. (3) Un appelant se trompe-t-il aujourd'hui ? Aucun appel croise entre modules n'a ete trouve — le constat ne l'affirme donc pas. Ce qu'il etablit est qu'un lecteur qui a compris la fonction dans un module la comprend de travers dans l'autre, et qu'un futur appel qui hacherait le retour de M2 hacherait un hachage sans que rien ne l'arrete.

### AUD-A4-002 — Le code de production importe une bibliotheque tierce dans 22 fichiers.

- **sévérité** : critique — calculée par la règle `regle_critique:contrat_gele_rayon_ge_2`
- **entrées mesurées** : contrat_gele='REG-08', frontiere_t3=False, gate_couvrant=False, rayon=22
- **emplacement** : `Modules M/M1-front-office/src/m1_front_office/registre.py:1`, `Modules M/M5-financecore/src/m5_financecore/taux_fiscaux.py:1`
- **témoin** : `audit/temoins/AUD-A4-002/reproduction.py` — rejoué, rouge comme attendu

**Ce que la mesure a donné**

```
22 fichiers de production importent « yaml » (PyYAML). Une seule dependance tierce trouvee sur l'ensemble du code de production.
```

**Réfutation tentée**

Trois refutations tentees. (1) yaml fait-il partie de la bibliotheque standard ? Non : il est absent de sys.stdlib_module_names. (2) Est-ce un module local du depot portant ce nom ? Non : le temoin construit l'ensemble des noms locaux depuis git ls-files et yaml n'y figure pas. (3) Ces imports sont-ils confines aux tests, ou la contrainte ne s'applique pas ? Non : le temoin ne retient que les fichiers sous src/ hors tests. Ce que le constat n'affirme PAS : que ces imports soient injustifies — analyser du YAML sans bibliotheque demande d'en ecrire une. Il etablit que la contrainte « bibliotheque standard uniquement », repetee dans les cadrages de module, n'est pas tenue, et qu'aucun gate ne le signale.

### AUD-A5-001 — RESOLU (PR #567, issue #565) -- Les tests d'autorisation et de coffre a secrets tournent dans un job non bloquant.

- **sévérité** : critique — calculée par la règle `regle_critique:frontiere_t3`
- **entrées mesurées** : contrat_gele='REG-09', frontiere_t3=True, gate_couvrant=False, rayon=4
- **emplacement** : `.github/workflows/ci.yml:47`, `.github/workflows/ci.yml:68`
- **témoin** : `audit/temoins/AUD-A5-001/reproduction.py` — REJOUÉ : rc=0 (attendu 1)

**Ce que la mesure a donné**

```
checks exiges par la protection de main : ['gates']

-- job « gates » (ligne 4) -- bloquant, exige par la protection
-- job « e2e » (ligne 60) -- bloquant, NON exige par la protection
-- job « e2e-load » (ligne 76) -- bloquant, NON exige par la protection

CONSTAT NON REPRODUIT : plus aucun test sensible dans un job non bloquant.
AUD-A5-001 est perime et doit etre retire du rapport.
(rc=0 -- rejoue le 2026-08-26 sur claude/aud-ci-003-004-gating-bloquant, commit 3d57b50 puis le present commit de revue)
```

**Réfutation tentée**

RESOLU -- mesure le 2026-08-26 sur la branche claude/aud-ci-003-004-gating-bloquant (issue #565, PR #567 ; correctif initial commit 3d57b50, complete par le present commit de revue). Le correctif deplace les trois steps critiques (dashboard P0-5a, authz P0-5c, config/vault P0-5d) du job `e2e` (continue-on-error: true) vers le job `gates` -- le seul contexte required en branch protection sur `main`, mesure via `gh api repos/leon36000/OPSYS-AI/branches/main/protection` -- et retire `continue-on-error: true` des jobs `e2e` et `e2e-load`. Rejoue sur cet etat, `audit/temoins/AUD-A5-001/reproduction.py` rend desormais rc=0 (« CONSTAT NON REPRODUIT : plus aucun test sensible dans un job non bloquant. AUD-A5-001 est perime et doit etre retire du rapport. »), sortie complete ci-dessus dans `refutation.sortie`. `check_temoins_rouges()` (audit/verif_audit.py) le confirme independamment : liste vide sur `main`, mais encore ['AUD-A5-001.json : temoin rc=0, attendu 1'] sur cette branche tant que ce fichier declare `temoin_rc: 1`.

Ce champ `temoin_rc` reste a 1 en connaissance de cause, pas par omission : `audit/contrats.py::valider_constat` REJETTE `temoin_rc == 0` pour TOUT constat (`TEMOIN_RC_VALEUR_INVALIDE:0`, verifie empiriquement en ecrivant temporairement 0 dans ce fichier -- `audit/rapport.py` refuse alors de regenerer QUELQUE rapport que ce soit, meme pour les 11 autres constats, valides eux). Ce format n'a donc pas de representation valide pour « defaut resolu » ; seul le retrait de ce fichier de `audit/constats/` (ce que le temoin recommande lui-meme) ferait rendre une liste vide a `check_temoins_rouges()`. `git rm audit/constats/AUD-A5-001.json` a ete tente dans cette session et bloque par le classifieur de securite de l'environnement (suppression hors perimetre auto-approuve, validation humaine explicite requise) -- ce qui rejoint la consigne de ne pas supprimer sans cette validation. Le contenu integral de ce constat reste recuperable a l'identique via `git show 3d57b50:audit/constats/AUD-A5-001.json` (sha256 du blob : 7a04333143a5345a8729fced4764164908b6254093f3ebb1730f2fb1cfe06ebe) des qu'un humain autorise son retrait effectif. L'`emplacement` ci-dessus reste la localisation HISTORIQUE du defaut confirme (ci.yml avant correctif) ; le code a cette localisation n'existe plus a l'identique apres le deplacement des trois steps vers `gates`.

--- Raisonnement original, au moment de la confirmation (avant correctif) ---
Deux refutations tentees. (1) Le job e2e est-il exige par la protection de branche malgre son continue-on-error, ce qui rendrait le drapeau inoperant ? Non : l'API renvoie exactement ['gates']. (2) Ces tests sont-ils rejoues ailleurs, dans le job bloquant ? Non : les 15 etapes de « gates » sont enumerees par le temoin et aucune ne porte sur core/src/authz ni core/src/config. Les deux voies echouent. Ce que le constat n'affirme PAS : aucune faille d'autorisation n'est montree — seule l'absence de garde l'est, conformement au standard « exposition prouvee, jamais exploitation ». Troisieme verification, sur le contrat gele lui-meme : R-015 avait ete retenu par supposition, puis resolu au plan de reference — il porte sur l'injection de prompt indirecte, sans rapport. Le contrat reellement contredit est REG-09 (« Securite par defaut. Secrets chiffres, exposition minimale, autorisation fine, journaux d'audit »), ligne 45 de l'extraction du plan. Un identifiant cite de memoire n'est pas une preuve : il doit etre resolu au referentiel. Quatrieme point, souleve par deux relecteurs independants : le constat porte classe=faille-securite et severite=critique alors que sa conclusion dit qu'aucune faille n'est montree — ils y ont vu une contradiction qui fausserait tout routage automatique. L'objection est reelle pour un lecteur, mais elle est levee par le cadrage lui-meme : le PRD §8.5 definit la limite d'un constat de securite comme « exposition prouvee, JAMAIS exploitation ». Dans cet audit, la classe faille-securite designe donc une exposition prouvee, et non une exploitation demontree ; les deux enonces sont coherents. Ce qui manquait etait la CITATION de ce standard dans le constat — un lecteur ne devrait pas avoir a retrouver le cadrage pour comprendre qu'il n'y a pas contradiction. Elle est ajoutee ici.

### AUD-A7-001 — Six README de module annoncent moins de stories que ce qui a ete revu.

- **sévérité** : critique — calculée par la règle `regle_critique:contrat_gele_rayon_ge_2`
- **entrées mesurées** : contrat_gele='REG-12', frontiere_t3=False, gate_couvrant=False, rayon=6
- **emplacement** : `Modules M/M7-marketing/README.md:1`, `Modules M/M3-estimation/README.md:1`
- **témoin** : `audit/temoins/AUD-A7-001/reproduction.py` — rejoué, rouge comme attendu

**Ce que la mesure a donné**

```
M7 annonce S000 alors que S015 est revue (retard de 15) ; M3 annonce S001 pour S009 (8) ; M6 S001 pour S009 (8) ; M5 S001 pour S007 (6) ; M8 S001 pour S006 (5) ; M9 S001 pour S005 (4). M10 est a jour. M1, M2 et M4 ne citent aucun numero de story.
```

**Réfutation tentée**

Trois refutations tentees. (1) La convention de nommage des dossiers de revue est-elle uniforme, ou la mesure rate-t-elle des modules ? Elle a change en cours de projet (M1-S001 puis m10-s001) : une comparaison sensible a la casse aurait perdu 5 modules et conclu a tort qu'ils n'avaient aucune revue. Le temoin compare sans tenir compte de la casse. (2) Le statut PARTIAL est-il faux ? Non, il est exact pour les dix modules, et le constat ne le remet pas en cause. (3) Un dossier de revue prouve-t-il qu'une story est livree ? Il prouve qu'elle a ete soumise a une revue scellee, ce qui est l'etape terminale du pipeline du depot — c'est la meilleure source disponible, et elle est independante du README qu'elle contredit. Ce que le constat etablit : la ligne consultee en premier par un lecteur annonce moins d'avancement qu'il n'y en a, et aucun gate ne compare ces deux sources.

