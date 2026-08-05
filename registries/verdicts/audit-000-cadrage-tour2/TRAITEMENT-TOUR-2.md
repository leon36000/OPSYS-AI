# Consensus élargi sur le cadrage AUDIT-000 — tour 2 : REJECTED, puis arbitrage sur pièces

## Dépouillement

```
$ python3 scripts/tally.py registries/verdicts/audit-000-cadrage-tour2 anthropic
{"resultat": "REJECTED",
 "rejects": ["Composer-2.5", "GLM-5.2", "Gemini-3.1-Pro", "Kimi-K3", "MiniMax-M3", "Qwen3.7-Max"],
 "objections_critiques": 7}
rc=3
```

| Modèle | Vendor | Tour 1 | Tour 2 | Objections T2 | Critiques T2 |
|---|---|---|---|---|---|
| DeepSeek-V4-Pro | deepseek | APPROVE (3 obj) | **APPROVE (0 obj)** | 0 | 0 |
| MiMo-Pro-V2 | xiaomi | APPROVE (2 obj) | APPROVE | 1 | 0 |
| GLM-5.2 | zhipu | APPROVE (4 obj) | **REJECT** | 1 | 0 |
| Gemini-3.1-Pro | google | REJECT (2 obj) | REJECT | 1 | 1 |
| Qwen3.7-Max | alibaba | REJECT (2 obj) | REJECT | 1 | 1 |
| Kimi-K3 | moonshot | REJECT (7 obj) | REJECT | 3 | 1 |
| Composer-2.5 | xai | REJECT (6 obj) | REJECT | 4 | 1 |
| MiniMax-M3 | minimax | REJECT (6 obj) | REJECT | 7 | 3 |

Sceau unique sur les 8 verdicts.

**Le volume d'objections s'effondre : 32 au tour 1, 19 au tour 2 ; 8 critiques puis 7.** Aucune
objection du tour 1 n'est reformulée : les objections du tour 2 portent toutes sur les corrections
elles-mêmes. C'est le signe attendu d'un cadrage qui converge, et non d'un désaccord de fond.

Le passage de GLM d'APPROVE à REJECT ne contredit pas ce constat : son unique objection du tour 2
est de sévérité **majeure**, et porte sur un point que le tour 1 n'avait pas soulevé.

## Ce que le tour 2 a trouvé — et qui était réel

### Contradiction entre le PRD et l'architecture (Composer + Kimi, critique)

Le PRD affectait `CA-AUD-13` au lot A8 ; le tableau §4 de l'architecture affectait `CA-AUD-05, 06`
à ce même A8, alors qu'A4 et A6 les portaient déjà. Dans l'architecture, `CA-AUD-13` n'était donc
porté par **aucun** lot, et `CA-AUD-05/06` par **deux** — en violation directe du principe que le
gate prétend vérifier. Le gate affichait `VERDICT : TOUT VERT`.

Cause : `check_ca_portes_par_lots` ne lisait que le PRD. Le gate était aveugle aux contradictions
**entre** documents.

Corrigé deux fois : dans les documents, et dans le gate. Un douzième contrôle
`check_ca_coherents_entre_documents` compare les deux affectations et nomme le critère et les deux
lots en cause. Vérifié mordant sur la contradiction réellement survenue.

### `--diff-filter=MD` bloquait CA-AUD-10 (Gemini, critique)

« Ajouter une entrée dans un registre existant est classé `M` par git, pas `A`. Cette règle bloque
mécaniquement l'enregistrement légitime des constats. »

Reproduit dans un dépôt jetable :

```
ajout d'une ligne à registries/ledger/journal.jsonl
  --diff-filter=MD -> 'registries/ledger/journal.jsonl'   => BLOQUÉ
```

CA-AUD-09 et CA-AUD-10 se contredisaient donc : l'un exigeait la traçabilité au registre, l'autre
l'interdisait. Corrigé par **deux régimes distincts** — préfixe exact pour les registres en journal
d'ajout, `MDTR` vide pour les preuves figées.

### `--diff-filter=MD` laissait passer renommage et symlink (Qwen, critique)

Reproduit dans le même dépôt jetable :

```
renommer un verdict scellé          : MD -> ''   |  MDTR -> 'reviews/renomme.verdict.json'
le remplacer par un lien symbolique : MD -> ''   |  MDTR -> 'reviews/renomme.verdict.json'
```

Les deux altérations passaient. `MDTR` les attrape. Objection confirmée, corrigée.

Cette objection est d'autant plus fondée que l'audit a lui-même renommé des verdicts pendant ce
tour (`.json` -> `.verdict.json`, contenu vérifié byte-identique) : l'opération qu'elle décrit n'est
pas théorique.

### Un défaut collatéral trouvé en corrigeant

L'ouverture du lot A8 a révélé que `audit/contrats.py` rejetait `A8` (`_MOTIF_ID` en `A[1-7]`,
liste de lots close à A7). Tout constat d'intégration aurait été refusé par le contrat. Corrigé, et
les deux tests qui utilisaient `A8` comme valeur invalide ont été redirigés vers `A9` — ce sont eux
qui ont signalé le changement.

## Ce que le tour 2 a soulevé et qui est RÉFUTÉ par mesure

**MiniMax, critique** : « la liste des contrôles de la batterie est figée au moment de l'écriture du
script, non dérivée du code à mesurer ; toute évolution du gate y échappe. »

Faux. `_decouvrir_controles` fait `ast.parse` du vérificateur et retient tout nœud dont le nom
commence par `check_`, sans aucune liste maintenue à la main. La preuve expérimentale précède
l'objection : un contrôle `check_jamais_exerce` ajouté au gate a été détecté par la batterie —
`CONTRÔLE MORT (check_jamais_exerce)`, rc=1 — sans qu'aucune liste ne soit touchée.

L'objection était une inférence à partir du nombre affiché (« 11 contrôles »), pas une mesure.

## Ce qui reste ouvert, et pourquoi ce n'est pas un blocage

**Q1 du tour 2, posée à dessein** : « la batterie prouve maintenant que chaque CONTRÔLE est exercé.
Elle ne prouve toujours pas que l'ENSEMBLE des contrôles couvre la classe de défaut. »

C'est exact, et c'est irréductible. Prouver qu'un jeu de contrôles couvre une classe de défaut
supposerait une énumération close de cette classe — qui n'existe pas pour « défaut de code » ni pour
« faille de sécurité ». Toute prétention contraire serait une affirmation invérifiable, c'est-à-dire
exactement ce que l'audit reproche au dépôt lorsqu'il en trouve.

Ce reste est donc **déclaré**, pas masqué : le brief énonce que la complétude prouve qu'une mesure a
été exécutée **et a démontré sa capacité à détecter**, jamais qu'il n'existe aucun défaut.

**MiniMax, critique** : « DA-AUD-11 ne borne pas l'isolation du sous-processus (fork vs spawn,
PYTHONPATH hérité, .pyc partagés). » Fondé. Point de spécification à trancher à l'écriture de la
sonde A8, pas au cadrage : il appelle une mesure sur le comportement réel de l'interpréteur, non une
décision d'architecture prise à l'avance.

**MiniMax, critique** : « DA-AUD-10 dit que toute dérive invalide les revues conduites entre-temps,
mais ne dit pas COMMENT ; sans procédure de rollback, l'invalidation est déclarative. » Fondé.
À traiter dans la story de clôture, quand il y aura des revues à invalider.

## Arbitrage

Le protocole plafonne le Delphi à deux rounds, après quoi l'arbitrage revient à l'Orchestrateur
**sur pièces** — c'est-à-dire sur les mesures, jamais sur son appréciation.

Décision : **les six objections du tour 2 fondées sur une mesure sont corrigées** (contradiction
inter-documents, les deux défauts de `--diff-filter`, le contrat fermé à A8, plus le durcissement
du gate qui rendait la première invisible). **Une objection critique est réfutée par mesure**
(découverte dynamique des contrôles). **Deux points fondés sont reportés à la story qui les rendra
mesurables**, et inscrits comme tels plutôt que réputés traités.

Ce qui reste après cet arbitrage — l'impossibilité de prouver la couverture d'une classe non
énumérable — n'est pas un défaut du cadrage : c'est la limite de ce qu'un audit peut affirmer, et
elle est écrite dans le brief.
