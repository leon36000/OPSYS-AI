# Consensus élargi sur le cadrage AUDIT-000 — tour 1 : REJECTED

## Dépouillement (par script, jamais par un modèle)

```
$ python3 scripts/tally.py registries/verdicts/audit-000-cadrage anthropic
{"resultat": "REJECTED",
 "rejects": ["Composer-2.5", "Gemini-3.1-Pro", "Kimi-K3", "MiniMax-M3", "Qwen3.7-Max"],
 "objections_critiques": 8,
 "suite": "Delphi anonymise (max 2 rounds) -> arbitrage Orchestrateur SUR PIECES"}
rc=3
```

| Modèle | Vendor | Verdict | Objections | Critiques |
|---|---|---|---|---|
| Composer-2.5 | xai | REJECT | 6 | 2 |
| DeepSeek-V4-Pro | deepseek | APPROVE | 3 | 0 |
| GLM-5.2 | zhipu | APPROVE | 4 | 0 |
| Gemini-3.1-Pro | google | REJECT | 2 | 1 |
| Kimi-K3 | moonshot | REJECT | 7 | 2 |
| MiMo-Pro-V2 | xiaomi | APPROVE | 2 | 0 |
| MiniMax-M3 | minimax | REJECT | 6 | 2 |
| Qwen3.7-Max | alibaba | REJECT | 2 | 1 |

Sceau : un seul `prompt_sha256` sur les 8 verdicts — tous ont vu le pack byte-identique.

## Couverture réelle du panel : 8 vendors sur 12 sollicités

Quatre routes n'ont pas répondu, en deux tentatives espacées et sans autre charge concurrente :
`Kimi-2.7` (HTTP 500), `LongCat-2.0` (HTTP 429), `Gemini-3.6-Flash` (HTTP 429), `Grok-4.5`
(HTTP 408). Le cadrage annonçait « 12 modèles / 9 vendors » ; la mesure donne 8 modèles /
8 vendors. Le chiffre annoncé est corrigé dans l'architecture plutôt que maquillé.

Cela reste au-dessus du seuil de décorrélation (3 vendors distincts, REG-05), et les quatre
absents n'auraient ajouté qu'un seul vendor nouveau (meituan) : `Kimi-2.7` double moonshot,
`Gemini-3.6-Flash` double google, `Composer-2.5` — qui, lui, a répondu — double xai.

## Traitement des objections

Règle appliquée : une objection est une **hypothèse**, pas un ordre. Chacune est soit mesurée et
corrigée, soit réfutée par une mesure contraire, soit assumée avec sa raison. Aucune n'est
appliquée sur la seule autorité de son auteur.

### CONFIRMÉES ET CORRIGÉES

**1. La batterie de mutation ne prouve pas la couverture** — portée par Composer, Kimi, MiniMax et
Qwen (4 vendors), sous des formulations convergentes : « une mutation co-conçue avec sa sonde ne
prouve que la sensibilité à un motif choisi ».

Mesurée sur le gate de ce cadrage lui-même. Chaque contrôle a été neutralisé à tour de rôle (corps
remplacé par un retour vide) et la batterie relancée :

```
  MORT   check_existence_et_sections  — neutralisé, la batterie reste VERTE
  MORT   check_ca_portes_par_lots     — neutralisé, la batterie reste VERTE
  MORT   check_mots_interdits         — neutralisé, la batterie reste VERTE
  contrôles exercés par au moins une mutation : 8/11
```

L'affichage « BATTERIE COMPLÈTE : 9/9 mutations mordent » était donc un faux vert : trois
contrôles sur onze pouvaient disparaître sans que rien ne le signale.

Correction : CA-AUD-06 exige désormais que la batterie neutralise chaque contrôle et devienne
rouge ; CA-AUD-05 exige que chaque sonde publie la liste des fichiers qu'elle a réellement ouverts.
La ligne de gouvernance « sonde + batterie = T0, aucun LLM n'a à approuver un instrument qui prouve
sa propre morsure » est retirée : elle était la justification du faux vert.

Preuve après correction :
```
COUVERTURE : 11 contrôle(s) check_* découvert(s)  → 11/11 COUVERT
BATTERIE COMPLÈTE : 12/12 mutations mordent — couverture 11/11 contrôles
```
Contre-épreuve : un contrôle volontairement non couvert est ajouté au gate ; la batterie sort en
code 1 avec `CONTRÔLE MORT (check_jamais_exerce)`.

**2. Le critère de complétude s'appuie sur un instrument déjà mesuré menteur** — portée par
Composer, GLM et Kimi. « CA-AUD-10 exige que `ledger verify` reste vert, alors que H2 documente un
faux vert sur fichier absent : le critère est satisfait par le bug même que l'audit doit
documenter. »

Objection fondée et non contournable : l'audit se serait fait valider par son propre constat.
CA-AUD-10 exige désormais, en plus du code retour, un nombre d'entrées non nul **et** une chaîne
rejouée par le code de l'audit.

**3. L'angle mort de l'intégration entre modules** — portée par Composer, GLM et DeepSeek en
consensus, et par les trois modèles du round adverse, indépendamment : six sur onze. « Les sondes
lisent des fichiers isolément, donc un défaut qui n'existe qu'à l'intégration est structurellement
invisible. »

Le lot **A8** est ouvert, avec son critère propre CA-AUD-13, et **DA-AUD-11** borne la dérogation à
DA-AUD-07 : import autorisé, dans un sous-processus isolé, pour ce seul lot, sans exécution de
scénario métier.

**4. Le round adverse ne peut pas ouvrir un axe** — portée par GLM et MiniMax. « Le trio adverse
désigne où chercher dans les axes existants ; il ne peut pas en ouvrir un. »

CA-AUD-07 énonce désormais qu'une hypothèse adverse sans lot d'accueil **crée** le lot manquant.
A8 en est la première application.

**5. `reviews/` autorisé en écriture permet de réécrire un verdict scellé** — portée par Kimi.
CA-AUD-09 restreint les chemins autorisés à l'**ajout** seul :
`git diff --diff-filter=MD <base>..HEAD` doit être vide.

**6. La dépendance externe n'est pas traitée** — portée par MiMo et MiniMax. Les instruments réels
de la chaîne de preuve vivent dans `~/proof-method`, hors périmètre et libre de changer.

**DA-AUD-10** : le contenu reste hors périmètre, mais l'empreinte de chaque script utilisé est
gelée au manifeste et revérifiée à la clôture. La décision dit explicitement ce qu'elle ne couvre
pas : un instrument faux au gel restera faux, et l'empreinte le certifiera identique à lui-même.

### RÉFUTÉE PAR LA MESURE

**Les mutations #4 et #9 s'annuleraient** (MiniMax, critique). Elles ciblent `DA-AUD-04` et
`DA-AUD-09` dans le même fichier. Mesure : `03-ARCHITECTURE.md` est bit-à-bit identique avant et
après la batterie, chaque motif a exactement une occurrence, et les trois mutations qui touchent ce
fichier mordent chacune avec son motif attendu. La restauration entre mutations est effective.
L'objection est écartée sur pièce, non sur autorité.

### RETENUE, TRAITÉE PARTIELLEMENT

**La rubrique confond dispersion et impact** (Gemini, majeure) : « un défaut critique localisé dans
un seul fichier sera sous-évalué ». Exact sur le principe. `frontiere_t3` couvre déjà le cas le plus
grave d'un défaut localisé, et `contrat_gele` seul suffit à `majeure` sans condition de rayon. Reste
un cas non couvert : un défaut grave, localisé, sans contrat gelé violé et sous gate couvrant. Il
est consigné comme limite connue de la rubrique plutôt que corrigé à l'aveugle — une pondération
d'impact non mesurable rouvrirait la porte au jugement, que DA-AUD-03 ferme.

## Suite

Cadrage révisé : 13 critères, 8 lots, 11 décisions d'architecture. Gate TOUT VERT (11 contrôles),
batterie 12/12 avec couverture 11/11. Un tour 2 est distribué au panel sur le cadrage révisé.
