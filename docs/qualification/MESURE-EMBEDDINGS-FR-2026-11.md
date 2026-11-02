# Mesure des embeddings en français québécois — banc reproductible (2026-11-02)

> **Statut : MESURÉ sur un corpus FICTIF, petit, écrit par une seule main. Ce n'est PAS une qualification.** Aucune donnée
> réelle, aucun client, aucune production. Les chiffres disent comment ces modèles se comportent sur ce corpus ; ils
> n'établissent pas leur qualité sur les documents réels d'un client. Aucun registre du produit n'est modifié (voir §8).
> Banc : [`install/qualification/embeddings_fr/`](../../install/qualification/embeddings_fr/) · Preuves brutes :
> [`docs/qualification/preuves-embeddings-fr/`](preuves-embeddings-fr/) · Tests : `tests/test_banc_embeddings_fr.py`.

Cette mesure répond à une phrase de l'analyse de M10 (« aucun vrai modèle d'embeddings n'a jamais été mesuré ») et à la
règle de la feuille de route technologique (« mesurer avant d'adopter »).

## 1. Ce qu'il faut retenir

1. **Sur ce corpus, tout vrai modèle d'embeddings dépasse nettement le BM25 local** : MRR@10 de 0,84 à 0,94 contre 0,65 (écarts
   appariés de +0,19 à +0,28, tous distinguables de 0). Le gain est surtout sur les **reformulations sans mots communs**
   (BM25 : 0,14 ; vecteurs : 0,64 à 0,92), les fautes de frappe et les anglicismes.
2. **Meilleur mesuré : Gemini Embedding 2 avec `input_type` requête/document** (MRR@10 0,937 [0,899 ; 0,973], rappel@5
   99,5 %), le seul dont l'avantage est distinguable de tous les autres modèles (écarts appariés de +0,04 à +0,10).
   **Voyage 4** (0,882) est le deuxième ; **Voyage 4 lite** (0,842), le moins cher, est significativement sous Voyage 4
   (−0,04) ; **multilingual-e5-large** (0,859) est entre les deux, sans écart distinguable de Voyage 4 ni de Voyage 4 lite.
3. **Le coût d'embedding n'est pas le facteur de décision** : de 0,05 USD (e5) à 0,96 USD (Gemini) pour 100 000 passages
   de ~50 jetons. Ce qui sépare les modèles : la qualité, la dimension du vecteur (1 024 contre 3 072 → stockage ×3 et
   colonne `vector(1024)` de la mémoire), la latence (Voyage 0,17 s, Gemini 0,45 s, e5 1,1 s en requête isolée, via un tunnel) et
   l'hébergement des données (§5).
4. **La fusion RRF « BM25 + vecteurs » à poids égaux N'A PAS aidé ici** : elle fait perdre 0,03 à 0,09 de MRR@10 par
   rapport aux vecteurs seuls (distinguable pour 3 des 8 configurations). À demi-poids pour le BM25 (essai exploratoire,
   choisi après coup) la perte se réduit sans que l'hybride dépasse les vecteurs. À ne pas généraliser : voir les limites.
5. **Le seuil cosinus fixe de 0,30 du produit (réglé pour bge-m3) ne sert à rien avec ces modèles** : il ne retire pratiquement
   aucun passage pertinent (au plus 1 %) et laisse passer 92 à 100 % des questions sans réponse. Le seuil doit être calibré par modèle (à 90 %
   de rappel : ~0,64–0,67 pour Gemini, ~0,44–0,52 pour Voyage, ~0,83 pour e5 sur ce corpus) ; avec 12 questions sans
   réponse, ces valeurs sont indicatives.
6. **Un petit modèle de discussion comme juge de pertinence (Haiku 5.5, 10 candidats) améliore un premier étage faible** :
   +0,079 de MRR@10 sur le BM25 seul et +0,057 sur l'hybride Gemini, pour environ 0,0001 USD et 0,66 s par question ;
   **+0,024 (non distinguable) sur les vecteurs Gemini**, déjà excellents. Ce n'est pas un reranker dédié (cross-encodeur) :
   celui-là reste à mesurer.
7. **Le repli local n'est PAS mesuré** : aucune bibliothèque d'embeddings locale n'est installée dans le venv, aucun
   service local ne répondait. Le seul point « local » est le BM25 du dépôt. bge-m3 et Qwen3-Embedding (catalogue) restent
   « à mesurer » avec ce banc sur le GB10.

Coût total de la mesure : **≈ 0,043 USD** (embeddings ≈ 0,0092 estimé au tarif OpenRouter ; juge 0,0338 rapporté par la
passerelle ; sondes ≈ 0,0004), sous le plafond visé de 0,50 USD. Les compteurs de la passerelle ne mesurent pas les
embeddings (§6).

## 2. Méthode

**Corpus fictif** (`docs/qualification/corpus-embeddings-fr/` : les données sont hors de `install/`, car la garde de
généralisation des packs interdit le vocabulaire du secteur dans le cœur ; empreinte SHA-256 `91dbf324…`, `fictif: true`
validé par le chargeur) : **255 passages** courts (≈ 50 jetons) en français québécois de rénovation extérieure, huit
catégories — gouttières (35), revêtement (35), soffite et fascia (30), soumissions (35), plaintes (30), factures (30),
fiches fournisseurs (30), notes de chantier (30). Entreprise, clients, fournisseurs, numéros, montants et règles sont
inventés (courriels `@…example.test`). Les prix, délais et règles sont des énoncés de fiction pour tester la recherche :
ce ne sont ni des références techniques, ni tarifaires, ni fiscales, ni juridiques.

**104 requêtes** dont **92 avec réponse** et **12 sans bonne réponse** (par construction, hors corpus : télétravail,
toiture en bardeau d'asphalte, fenêtres, panneaux solaires, tarte au sucre…), réparties par difficulté :

| Type | n | Ce que ça éprouve |
|---|---|---|
| paraphrase | 16 | même sens, autres mots |
| reformulation | 16 | écrites pour ne **presque rien partager** avec le passage (« tuyaux de toit qui crachent l'eau près des murs de la cave » → descente et solage) |
| synonyme_qc | 14 | vocabulaire québécois (solage, clin, suisse, perron, cabanon, dépôt, banc de neige, planche de rive) |
| faute | 12 | orthographe et frappe, accents absents (« goutiere », « bareage de glasse ») |
| anglicisme | 10 | « quotes », « siding », « flashing », « drip edge », « lead time », « callback » |
| abreviation | 11 | « soum. », « fact. », « acpte », « pi lin. », NSF, TPS/TVQ, RBQ, FDS, CNESST, R-5 |
| nombre_unite | 13 | pi² / mm / m, pourcentages, montants, numéros de soumission et de facture |
| negative | 12 | aucune bonne réponse dans le corpus (mesure l'abstention) |

**Jugements.** Écrits à la main AVANT toute mesure (version 1) : `pertinents` (gain 2 ; comptés dans rappel@k et MRR) et
`partiels` (gain 1 ; seulement dans le nDCG gradué). **Version 2** (après la première mesure) : revue par mise en commun
(*pooling*) — les passages non jugés classés dans les 3 premiers par au moins 3 des 8 configurations vectorielles ont été
relus ; **13 passages réellement utiles ont été ajoutés comme partiels**, aucun pertinent n'a été ajouté, retiré ni déplacé.
Conséquence : rappel@k et MRR sont **identiques** entre v1 et v2 ; seul le nDCG varie (≤ 0,01 en valeur absolue,
comparer `mesure-20261102T093226Z-7f27ab07.json` à la version suivante). Cette revue a regardé les résultats des modèles
(biais possible en faveur de ce que les modèles remontent) ; le jeu v1 est conservé.

**Systèmes comparés.**

- *BM25 local* : l'adaptateur `LexicalSqliteFts5` et la normalisation française du dépôt, sur une base SQLite en mémoire,
  avec les règles de la recherche du produit (candidats « OU », couverture ≥ 0,25, tri BM25) — `lexical_local.py`.
- *Plancher* : le double de hachage de termes du dépôt (`EmbeddingsDeterministe`, 256 dimensions). Ce n'est **pas** un
  modèle ; il montre ce que vaut du pur recouvrement de mots et de trigrammes (MRR@10 0,583, sous le BM25).
- *Embeddings par la passerelle* (`/v1/embeddings`), quatre modèles × deux encodages = **8 configurations** : e5 (texte
  brut ; préfixes « query: » / « passage: » de sa fiche), et pour Gemini 2, Voyage 4 et Voyage 4 lite (appel OpenAI
  standard ; avec `input_type` query/document, que la passerelle transmet — vérifié : les vecteurs changent). Similarité
  cosinus exacte sur vecteurs normalisés.
- *Hybride* : RRF (k = 60, 50 candidats par voie, comme `recherche.Reglages` du produit — un test l'impose) du BM25 et du
  cosinus. Variante **exploratoire** à demi-poids pour le BM25, choisie APRÈS avoir vu les résultats à poids égaux.
- *Juge de reclassement* : `opsys-haiku-5-5`, consigne unique, 10 candidats présentés dans un ordre mélangé déterministe
  (le juge ne voit pas le rang), notes 0–3 en JSON, tri par note puis par rang initial. Appliqué à trois sources : BM25
  seul, le meilleur système vectoriel et le meilleur hybride.

**Métriques.** Rappel@1/5/10, MRR@10, nDCG@10 gradué (log2) sur les 92 questions avec réponse. **Intervalles de confiance à
95 %** par rééchantillonnage des questions (percentile, 2 000 tirages, graine fixe) ; **écarts appariés** (mêmes questions)
avec leur intervalle : un écart est dit « distinguable » si l'intervalle exclut 0. Questions sans réponse : AUC du score de
tête (avec contre sans réponse) et part des questions sans réponse acceptées à un seuil qui garde 90 % des questions avec
réponse. **Robustesse aux fautes** : les 92 mêmes requêtes rejouées après une perturbation déterministe (accents retirés,
lettre supprimée, permutée ou doublée dans ~40 % des mots de 5 lettres et plus ; nombres et identifiants intacts).
**Latence** : 40 requêtes envoyées une à une, séquentiellement, par configuration (p50/p95 ; le reste des requêtes et les
passages en lots de 64). **Coût** : jetons facturés (champ `usage` de la réponse) × tarif OpenRouter lu le 2026-11-02
(`tarifs.json`).

**Reproductibilité.** Vecteurs et journal des appels (latence, jetons, coût) dans un cache SQLite **hors dépôt** ; rejouer
`banc.py mesurer --sans-appel --juge …` redonne les mêmes métriques et les mêmes jugements sans aucun appel (vérifié : sections
`configurations`, `comparaisons`, `entre_modeles_mrr`, `juge` et `par_requete` identiques à celles du fichier de preuve). Le JSON de preuve ne contient ni
vecteur ni clé.

## 3. Résultats

Corpus v2 (`91dbf324…`), 92 questions avec réponse, 12 sans réponse. Source :
`preuves-embeddings-fr/mesure-20261102T094924Z-91dbf324.json` (régénérable : `banc.py rapport --resultats …`).

| Système | Questions | MRR@10 [IC95] | Rappel@1 | Rappel@5 | Rappel@10 | nDCG@10 [IC95] |
|---|---|---|---|---|---|---|
| BM25 FTS5 (local) | 92 | 0.654 [0.564 ; 0.738] | 0.533 | 0.728 | 0.761 | 0.646 [0.569 ; 0.719] |
| double de hachage (plancher) | 92 | 0.583 [0.497 ; 0.671] | 0.446 | 0.707 | 0.777 | 0.601 [0.532 ; 0.669] |
| e5-large (vecteurs) | 92 | 0.859 [0.791 ; 0.922] | 0.761 | 0.880 | 0.929 | 0.825 [0.771 ; 0.876] |
| e5-large + BM25 (RRF) | 92 | 0.818 [0.747 ; 0.886] | 0.707 | 0.864 | 0.935 | 0.810 [0.756 ; 0.859] |
| e5-large-prefixes (vecteurs) | 92 | 0.859 [0.793 ; 0.919] | 0.755 | 0.891 | 0.951 | 0.836 [0.787 ; 0.881] |
| e5-large-prefixes + BM25 (RRF) | 92 | 0.812 [0.744 ; 0.878] | 0.685 | 0.880 | 0.935 | 0.815 [0.761 ; 0.863] |
| gemini-2 (vecteurs) | 92 | 0.896 [0.845 ; 0.945] | 0.793 | 0.957 | 0.978 | 0.879 [0.840 ; 0.913] |
| gemini-2 + BM25 (RRF) | 92 | 0.858 [0.798 ; 0.914] | 0.750 | 0.913 | 0.978 | 0.858 [0.817 ; 0.894] |
| gemini-2-type (vecteurs) | 92 | 0.937 [0.899 ; 0.973] | 0.837 | 0.995 | 1.000 | 0.925 [0.896 ; 0.949] |
| gemini-2-type + BM25 (RRF) | 92 | 0.844 [0.781 ; 0.902] | 0.717 | 0.929 | 0.957 | 0.862 [0.818 ; 0.900] |
| voyage-4 (vecteurs) | 92 | 0.882 [0.828 ; 0.932] | 0.755 | 0.946 | 1.000 | 0.883 [0.846 ; 0.917] |
| voyage-4 + BM25 (RRF) | 92 | 0.823 [0.756 ; 0.886] | 0.696 | 0.913 | 0.967 | 0.841 [0.795 ; 0.883] |
| voyage-4-type (vecteurs) | 92 | 0.877 [0.823 ; 0.928] | 0.739 | 0.957 | 1.000 | 0.883 [0.847 ; 0.915] |
| voyage-4-type + BM25 (RRF) | 92 | 0.830 [0.764 ; 0.893] | 0.707 | 0.902 | 0.957 | 0.848 [0.801 ; 0.891] |
| voyage-4-lite (vecteurs) | 92 | 0.842 [0.778 ; 0.902] | 0.717 | 0.897 | 0.962 | 0.829 [0.778 ; 0.875] |
| voyage-4-lite + BM25 (RRF) | 92 | 0.809 [0.738 ; 0.874] | 0.685 | 0.880 | 0.929 | 0.810 [0.754 ; 0.862] |
| voyage-4-lite-type (vecteurs) | 92 | 0.850 [0.788 ; 0.907] | 0.723 | 0.924 | 0.951 | 0.838 [0.786 ; 0.884] |
| voyage-4-lite-type + BM25 (RRF) | 92 | 0.816 [0.746 ; 0.880] | 0.696 | 0.891 | 0.918 | 0.816 [0.758 ; 0.869] |

| Système (MRR@10) | paraphrase (16) | reformulation (16) | synonyme_qc (14) | faute (12) | anglicisme (10) | abreviation (11) | nombre_unite (13) |
|---|---|---|---|---|---|---|---|
| BM25 FTS5 (local) | 0.76 | 0.14 | 0.89 | 0.57 | 0.56 | 0.94 | 0.81 |
| e5-large (vecteurs) | 0.86 | 0.67 | 0.89 | 0.77 | 1.00 | 0.93 | 0.96 |
| e5-large + BM25 (RRF) | 0.84 | 0.62 | 0.88 | 0.64 | 0.95 | 1.00 | 0.89 |
| e5-large-prefixes (vecteurs) | 0.89 | 0.64 | 0.93 | 0.72 | 1.00 | 1.00 | 0.92 |
| e5-large-prefixes + BM25 (RRF) | 0.86 | 0.62 | 0.88 | 0.64 | 0.95 | 0.95 | 0.85 |
| gemini-2 (vecteurs) | 0.97 | 0.88 | 0.94 | 0.76 | 0.88 | 0.88 | 0.92 |
| gemini-2 + BM25 (RRF) | 0.94 | 0.66 | 1.00 | 0.73 | 0.95 | 0.91 | 0.85 |
| gemini-2-type (vecteurs) | 1.00 | 0.92 | 0.96 | 0.85 | 0.93 | 0.95 | 0.92 |
| gemini-2-type + BM25 (RRF) | 0.91 | 0.66 | 0.93 | 0.72 | 0.93 | 0.95 | 0.85 |
| voyage-4 (vecteurs) | 0.94 | 0.91 | 0.84 | 0.75 | 0.93 | 1.00 | 0.82 |
| voyage-4 + BM25 (RRF) | 0.86 | 0.68 | 0.87 | 0.70 | 0.95 | 0.95 | 0.80 |
| voyage-4-type (vecteurs) | 0.94 | 0.88 | 0.89 | 0.70 | 0.93 | 0.95 | 0.85 |
| voyage-4-type + BM25 (RRF) | 0.86 | 0.69 | 0.92 | 0.69 | 0.95 | 0.95 | 0.81 |
| voyage-4-lite (vecteurs) | 0.86 | 0.80 | 0.86 | 0.72 | 0.91 | 0.95 | 0.81 |
| voyage-4-lite + BM25 (RRF) | 0.90 | 0.63 | 0.88 | 0.67 | 0.90 | 0.95 | 0.79 |
| voyage-4-lite-type (vecteurs) | 0.84 | 0.81 | 0.88 | 0.77 | 0.90 | 0.91 | 0.86 |
| voyage-4-lite-type + BM25 (RRF) | 0.90 | 0.66 | 0.88 | 0.67 | 0.90 | 0.95 | 0.80 |

Lecture : le BM25 est bon quand la question reprend les mots du passage (abréviations 0,94, synonymes québécois 0,89) et
s'effondre sur les reformulations (0,14). Les vecteurs tiennent sur tout, avec leur point faible sur les **fautes** (0,70
à 0,85). La fusion RRF coûte surtout sur les reformulations (Gemini 0,92 → 0,66) et les fautes.

### 3.1 Qui est meilleur que qui

| ligne − colonne | e5-large | e5-large-prefixes | gemini-2 | gemini-2-type | voyage-4 | voyage-4-type | voyage-4-lite | voyage-4-lite-type |
|---|---|---|---|---|---|---|---|---|
| e5-large | · | -0.000 | -0.037 | -0.079* | -0.023 | -0.019 | +0.017 | +0.009 |
| e5-large-prefixes | +0.000 | · | -0.037 | -0.078* | -0.023 | -0.018 | +0.017 | +0.009 |
| gemini-2 | +0.037 | +0.037 | · | -0.042* | +0.014 | +0.018 | +0.054 | +0.046 |
| gemini-2-type | +0.079* | +0.078* | +0.042* | · | +0.055* | +0.060* | +0.096* | +0.087* |
| voyage-4 | +0.023 | +0.023 | -0.014 | -0.055* | · | +0.005 | +0.040* | +0.032 |
| voyage-4-type | +0.019 | +0.018 | -0.018 | -0.060* | -0.005 | · | +0.036 | +0.027 |
| voyage-4-lite | -0.017 | -0.017 | -0.054 | -0.096* | -0.040* | -0.036 | · | -0.008 |
| voyage-4-lite-type | -0.009 | -0.009 | -0.046 | -0.087* | -0.032 | -0.027 | +0.008 | · |

« * » : l'intervalle de confiance à 95 % de l'écart apparié exclut 0. Huit configurations sur les mêmes données et aucune
correction pour comparaisons multiples : un « * » isolé est un indice, pas une preuve. Seuls Gemini 2 avec `input_type`
(contre tous) et Voyage 4 contre Voyage 4 lite se détachent. Pour e5, les préfixes ne changent rien de mesurable
(MRR identique 0,859) ; pour Voyage 4 et Voyage 4 lite, `input_type` ne change rien de distinguable ; pour Gemini 2,
`input_type` gagne +0,042 [distinguable].

### 3.2 Hybride BM25 + vecteurs

| Configuration | MRR@10 vecteurs | MRR@10 + BM25 (RRF, poids égaux) | Écart [IC95] | Distinguable | MRR@10 BM25 à demi-poids (exploratoire) | Écart contre vecteurs [IC95] |
|---|---|---|---|---|---|---|
| e5-large | 0.859 | 0.818 | -0.040 [-0.098 ; +0.016] | non | 0.820 | -0.039 [-0.085 ; +0.006] |
| e5-large-prefixes | 0.859 | 0.812 | -0.046 [-0.099 ; +0.003] | non | 0.825 | -0.034 [-0.084 ; +0.010] |
| gemini-2 | 0.896 | 0.858 | -0.038 [-0.100 ; +0.025] | non | 0.861 | -0.035 [-0.090 ; +0.020] |
| gemini-2-type | 0.937 | 0.844 | -0.094 [-0.153 ; -0.038] | oui | 0.875 | -0.063 [-0.117 ; -0.015] |
| voyage-4 | 0.882 | 0.823 | -0.059 [-0.107 ; -0.014] | oui | 0.858 | -0.024 [-0.065 ; +0.015] |
| voyage-4-type | 0.877 | 0.830 | -0.047 [-0.095 ; -0.001] | oui | 0.865 | -0.013 [-0.053 ; +0.026] |
| voyage-4-lite | 0.842 | 0.809 | -0.032 [-0.079 ; +0.012] | non | 0.820 | -0.021 [-0.063 ; +0.015] |
| voyage-4-lite-type | 0.850 | 0.816 | -0.034 [-0.082 ; +0.013] | non | 0.832 | -0.018 [-0.062 ; +0.025] |

Sur ce corpus, l'hybride à poids égaux est **moins bon** que les vecteurs seuls pour les 8 configurations (distinguable
pour Gemini 2 avec `input_type`, Voyage 4 et Voyage 4 avec `input_type`). Il est en revanche **bien meilleur que le BM25
seul** (+0,16 à +0,20 de MRR@10, distinguable partout). Pourquoi, d'après les chiffres par type : le BM25 apporte des
candidats bruités (sémantique « OU » avec peu de mots rares sur 255 passages) qui, à poids égal, déplacent la bonne réponse
quand les vecteurs l'avaient déjà en tête. Le BM25 aide un peu sur les abréviations et les anglicismes. **Cela ne prouve
pas que l'hybride est inutile en production** : les requêtes sont écrites par le même auteur que les passages, les
identifiants exacts (numéros de facture) pèsent peut-être plus dans la vraie vie, et le volume change tout (255 passages).
La colonne « demi-poids » est exploratoire.

### 3.3 Robustesse aux fautes

| Système | MRR@10 requêtes propres | MRR@10 mêmes requêtes mal tapées | Perte [IC95] | Perte distinguable de 0 |
|---|---|---|---|---|
| BM25 FTS5 (local) | 0.654 | 0.472 | +0.182 [+0.103 ; +0.261] | oui |
| e5-large (vecteurs) | 0.859 | 0.705 | +0.154 [+0.090 ; +0.219] | oui |
| e5-large + BM25 (RRF) | 0.818 | 0.650 | +0.168 [+0.095 ; +0.239] | oui |
| e5-large-prefixes (vecteurs) | 0.859 | 0.682 | +0.176 [+0.113 ; +0.243] | oui |
| e5-large-prefixes + BM25 (RRF) | 0.812 | 0.676 | +0.136 [+0.069 ; +0.203] | oui |
| gemini-2 (vecteurs) | 0.896 | 0.881 | +0.015 [-0.015 ; +0.049] | non |
| gemini-2 + BM25 (RRF) | 0.858 | 0.756 | +0.101 [+0.043 ; +0.164] | oui |
| gemini-2-type (vecteurs) | 0.937 | 0.882 | +0.055 [+0.026 ; +0.088] | oui |
| gemini-2-type + BM25 (RRF) | 0.844 | 0.784 | +0.059 [+0.004 ; +0.118] | oui |
| voyage-4 (vecteurs) | 0.882 | 0.824 | +0.058 [+0.022 ; +0.101] | oui |
| voyage-4 + BM25 (RRF) | 0.823 | 0.777 | +0.046 [-0.009 ; +0.104] | non |
| voyage-4-type (vecteurs) | 0.877 | 0.836 | +0.041 [+0.003 ; +0.082] | oui |
| voyage-4-type + BM25 (RRF) | 0.830 | 0.770 | +0.060 [+0.009 ; +0.115] | oui |
| voyage-4-lite (vecteurs) | 0.842 | 0.735 | +0.106 [+0.048 ; +0.170] | oui |
| voyage-4-lite + BM25 (RRF) | 0.809 | 0.728 | +0.082 [+0.015 ; +0.148] | oui |
| voyage-4-lite-type (vecteurs) | 0.850 | 0.746 | +0.104 [+0.043 ; +0.174] | oui |
| voyage-4-lite-type + BM25 (RRF) | 0.816 | 0.731 | +0.086 [+0.021 ; +0.154] | oui |

Gemini 2 sans `input_type` perd le moins (−0,015, non distinguable de 0) ; le BM25 perd 0,18 ; e5 0,15–0,18 ; Voyage 4 lite
~0,10 ; Voyage 4 et Gemini 2 avec `input_type` 0,04–0,06. La perturbation est synthétique : de vraies fautes de
clavier ou de dictée peuvent différer.

### 3.4 Questions sans bonne réponse, et le seuil du produit

| Système (tête de liste) | AUC avec / sans réponse | Seuil à 90 % de rappel | Sans réponse acceptées à ce seuil | Médiane avec / sans | Pertinents sous 0,30 | Sans réponse au-dessus de 0,30 |
|---|---|---|---|---|---|---|
| BM25 (score -bm25) | 0.784 | 2.29 | 75% | 7.99 / 4.84 | n/a | n/a |
| e5-large | 0.948 | 0.83 | 25% | 0.87 / 0.82 | 0.0% | 100% |
| e5-large-prefixes | 0.910 | 0.83 | 42% | 0.87 / 0.83 | 0.0% | 100% |
| gemini-2 | 0.931 | 0.67 | 8% | 0.76 / 0.60 | 0.0% | 100% |
| gemini-2-type | 0.975 | 0.64 | 0% | 0.70 / 0.58 | 0.0% | 100% |
| voyage-4 | 0.886 | 0.52 | 33% | 0.65 / 0.47 | 0.0% | 92% |
| voyage-4-type | 0.869 | 0.46 | 42% | 0.60 / 0.43 | 0.0% | 92% |
| voyage-4-lite | 0.835 | 0.52 | 50% | 0.62 / 0.49 | 0.0% | 100% |
| voyage-4-lite-type | 0.787 | 0.44 | 67% | 0.55 / 0.46 | 1.0% | 92% |

Le score de tête sépare bien les questions avec et sans réponse pour Gemini (AUC 0,93–0,98), e5 (0,91–0,95) et moins pour
Voyage (0,79–0,89) et le BM25 (0,78). Mais **les cosinus de ces modèles sont hauts et compressés** (e5 : médiane 0,82 même
sans réponse) : le seuil fixe de 0,30 de `recherche.Reglages.seuil_vectoriel` ne coupe rien. Avec **12** questions sans
réponse (un seul cas = 8 points de pourcentage), les seuils à 90 % de rappel sont des ordres de grandeur, à recalibrer sur
au moins quelques dizaines de vraies questions sans réponse.

### 3.5 Taille, coût, latence

| Configuration | Dimension | Mo / 100 000 passages | Jetons / passage | USD / million de jetons | USD mesuré (corpus + requêtes) | USD / 100 000 passages | Requête isolée p50 / p95 (s) | Documents (s / texte) |
|---|---|---|---|---|---|---|---|---|
| e5-large | 1024 | 390.6 | 50.6 | 0.01 | 0.000163 | 0.05 | 1.138 / 4.867 | 0.0221 |
| e5-large-prefixes | 1024 | 390.6 | 52.6 | 0.01 | 0.000175 | 0.05 | 1.102 / 1.376 | 0.0218 |
| gemini-2 | 3072 | 1171.9 | 45.9 | 0.2 | 0.002906 | 0.92 | 0.444 / 0.55 | 0.0323 |
| gemini-2-type | 3072 | 1171.9 | 47.9 | 0.2 | 0.003294 | 0.96 | 0.47 / 0.553 | 0.0312 |
| voyage-4 | 1024 | 390.6 | 53.2 | 0.06 | 0.001005 | 0.32 | 0.166 / 0.206 | 0.0108 |
| voyage-4-type | 1024 | 390.6 | 52.1 | 0.06 | 0.000974 | 0.31 | 0.167 / 0.186 | 0.0111 |
| voyage-4-lite | 1024 | 390.6 | 53.2 | 0.02 | 0.000335 | 0.11 | 0.159 / 0.264 | 0.0073 |
| voyage-4-lite-type | 1024 | 390.6 | 52.1 | 0.02 | 0.000324 | 0.1 | 0.157 / 0.176 | 0.0075 |

- Coût : tarif OpenRouter × jetons facturés ; « USD mesuré » est le **cumul du journal** (corpus + requêtes + sondes), pas
  un relevé de facture. À 100 000 passages de ~50 jetons, l'indexation coûte entre 0,05 et 0,96 USD.
- Latence : requête isolée, séquentielle, **à travers un tunnel SSH vers la passerelle de pc1 puis OpenRouter** — elle
  mesure surtout le trajet et l'hébergeur, pas le modèle. Les p95 reposent sur 40 échantillons (e5 : un maximum de 7,8 s sur
  la première série, 2,4 s sur la seconde ; la première configuration mesurée a peut-être subi un démarrage à froid).
- Dimension : Gemini 2 rend 3 072 valeurs. La mémoire (`memoire/schema.sql`) est en `vector(1024)` ; la base M10 accepte 2 à
  8 192 dimensions mais calcule le cosinus exact en Python (plafond 20 000 vecteurs) : plus de dimensions = plus de temps.
  La troncature (Matryoshka) de Gemini 2 n'a PAS été essayée. Les index pgvector ont une limite de dimensions pour le type
  `vector` (2 000 selon la documentation de pgvector, à vérifier pour la version retenue).

### 3.6 Reclassement par un juge

Juge : opsys-haiku-5-5, 10 candidats par question, 300 appels, 0.033814 USD, p50 0.659 s / p95 0.836 s par appel.

| Source des 10 candidats | MRR@10 avant [IC95] | MRR@10 après [IC95] | Écart MRR [IC95] | Écart nDCG [IC95] | Sans réponse jugées « répondues » | Répondables jugées « sans réponse » | Réponses illisibles |
|---|---|---|---|---|---|---|---|
| lex | 0.654 [0.564 ; 0.738] | 0.734 [0.647 ; 0.815] | +0.079 [+0.032 ; +0.131] | +0.048 [+0.019 ; +0.076] | 1 / 12 | 4 / 92 | 0 |
| gemini-2-type:vec | 0.937 [0.899 ; 0.973] | 0.962 [0.928 ; 0.989] | +0.024 [-0.003 ; +0.055] | +0.025 [+0.012 ; +0.040] | 2 / 12 | 0 / 92 | 0 |
| gemini-2:hyb | 0.858 [0.798 ; 0.914] | 0.915 [0.866 ; 0.957] | +0.057 [+0.008 ; +0.106] | +0.055 [+0.026 ; +0.085] | 1 / 12 | 0 / 92 | 0 |

Le juge ne retire aucun candidat : il réordonne les 10 premiers, donc rappel@10 ne bouge pas. Il aide quand le premier étage
met la bonne réponse trop bas (BM25 : +0,079 ; hybride Gemini : +0,057) et peu quand elle est déjà première (vecteurs
Gemini : MRR +0,024 non distinguable, nDCG +0,025 distinguable). Il juge « répondue » 1 à 2 des 12 questions sans réponse :
il n'est pas un détecteur d'absence fiable. 300 appels, 0,0338 USD rapportés par la passerelle (≈ 0,00011 par question),
p50 0,66 s, p95 0,84 s, 0 réponse illisible. Une seule consigne, un seul modèle, aucune calibration.

## 4. Recommandation par rôle (à ne pas sur-déclarer)

Ce sont des **présomptions fondées sur un corpus fictif**, à confirmer avant toute adoption sur un échantillon anonymisé
de documents réels du premier client (mêmes métriques, même banc).

| Rôle | Présomption | Pourquoi | Réserves |
|---|---|---|---|
| **Embeddings par défaut du cloud** (qualité d'abord) | **Gemini Embedding 2 avec `input_type`** | Seul distinguable des sept autres ; rappel@5 99,5 % ; AUC d'abstention la plus haute (0,975) | 3 072 dim. (stockage ×3, `vector(1024)` de la mémoire à adapter ou troncature à mesurer) ; latence ~0,47 s ; données hors Québec |
| **Embeddings cloud économique** | **Voyage 4** (sans `input_type` suffit) | 2ᵉ meilleur (0,882), 1 024 dim. compatibles avec `vector(1024)`, le plus rapide (0,17 s), 3× moins cher que Gemini | −0,055 de MRR@10 contre Gemini avec `input_type` (distinguable) ; Voyage 4 lite (0,02 USD/M) est significativement sous Voyage 4 |
| **Repli local** | **Non mesuré.** À mesurer en premier : bge-m3 (catalogue : « adopté », « à mesurer ») et Qwen3-Embedding sur le GB10 avec ce banc | multilingual-e5-large, modèle ouvert, a donné 0,859 [0,79 ; 0,92] via le cloud : un modèle local de cette famille est plausible, **sans preuve que le service cloud ait servi les mêmes poids ni que le local reproduise ces vecteurs** ; sa licence et son inscription au catalogue ne sont pas vérifiées ici | Sans embeddings locaux, le repli est le BM25 (0,654) : faible sur les reformulations (0,14) et les fautes (perte 0,18) |
| **Hybride BM25 + vecteurs** | Ne pas présenter l'hybride comme un gain ; garder le BM25 comme **voie de secours** et pour les identifiants exacts, et re-mesurer les poids sur données réelles | Ici : −0,03 à −0,09 contre les vecteurs seuls ; +0,16 à +0,20 contre le BM25 seul | Corpus petit, auteur unique, poids exploratoire choisi après coup |
| **Abstention (« je ne sais pas »)** | Seuil de cosinus **par modèle**, jamais 0,30 pour tous | Voir §3.4 | 12 négatives seulement |
| **Reclassement** | Juge générique (Haiku) rentable derrière un premier étage faible (BM25 ou hybride) ; reranker dédié à mesurer | +0,06 à +0,08 de MRR@10 pour ~0,0001 USD/question | Pas de reranker dédié ni de comparaison avec bge-reranker-v2-m3 / Qwen3-Reranker ; presque rien à gagner sur les meilleurs vecteurs |

**Résidence des données.** Envoyer des documents de clients à ces API (Google, Voyage/MongoDB, hébergeurs de modèles via
OpenRouter) est un transfert hors Québec : une évaluation des facteurs relatifs à la vie privée (EFVP, Loi 25) est requise
avant tout usage réel. **À valider auprès d'un professionnel qualifié.** Cette mesure n'a envoyé que des textes fictifs.

## 5. Limites (sans euphémisme)

- **Corpus fictif, petit, auteur unique.** 255 passages de ~50 jetons, 104 requêtes, tous écrits par le même agent (un
  modèle de langage) dans le même style : recouvrement de vocabulaire et formulations plus « propres » que la réalité.
  Classer 255 passages est bien plus facile que classer 20 000 : les rappels sont optimistes. Les vrais documents (factures
  PDF, soumissions longues, courriels, notes dictées) sont plus longs, plus bruités et demandent un découpage qu'on n'a pas
  éprouvé ici.
- **Peu de questions.** 92 avec réponse (IC95 de MRR@10 de ±0,04 à ±0,09) et seulement **12 sans réponse** : les chiffres
  d'abstention sont fragiles. Les types ont 10 à 16 questions : un type = beaucoup de bruit.
- **Jugements d'une seule main**, révisés une fois après avoir vu les résultats des modèles (pooling, 13 partiels). Un
  passage utile non vu reste possible.
- **Huit configurations sur les mêmes données, sans correction pour comparaisons multiples**, et un essai exploratoire
  (demi-poids) choisi après coup.
- **Hébergement non contrôlé.** Les modèles sont atteints via LiteLLM → OpenRouter → fournisseur amont : précision,
  troncature, version réellement servie et même l'identité du fournisseur ne sont pas contrôlées. Le nom « e5-large » est
  celui du catalogue OpenRouter (`intfloat/multilingual-e5-large`, contexte 512 jetons).
- **Latence indicative.** Un seul passage de 40 requêtes séquentielles par configuration, à travers un tunnel SSH ; pas de
  concurrence, pas de charge, pas de démarrage à froid distingué.
- **Coût estimé, pas facturé.** Les tarifs viennent des listes publiques d'OpenRouter lues le 2026-11-02 ; la passerelle
  déclare 0 pour tous les modèles et son compteur de dépense n'a bougé que pour les appels de discussion (le juge). La
  facture réelle d'OpenRouter n'a pas été consultée.
- **Fautes synthétiques** (perturbation déterministe), pas de vraies fautes de dictée ni d'OCR.
- **BM25 sur un index minuscule** : l'IDF est écrasé quand 255 passages seulement existent (le code du produit le note
  aussi). Le BM25 mesuré est celui du dépôt, pas un BM25 optimisé.
- **Vecteurs en float32** dans le cache (arrondi identique au premier appel et au rejeu).
- **Pas mesuré du tout** : modèles locaux (bge-m3, Qwen3-Embedding, e5 local), reranker dédié, dimensions réduites
  (Matryoshka), quantification, index approximatif (pgvector/HNSW), débit sous charge, requêtes en anglais ou mélangées,
  documents longs et découpage, tables/chiffres à grande échelle, OCR, modèles vision-langage.
- **Non prouvé contre le produit complet** : le banc reproduit les règles de recherche du produit (BM25 avec couverture,
  RRF k = 60, candidats 50) mais n'appelle pas `recherche.rechercher` ni la base de connaissances réelle.

## 6. Coût réellement dépensé

| Poste | USD | Source |
|---|---|---|
| Embeddings, 8 configurations (corpus + 104 requêtes + 104 perturbées + sondes) | ≈ 0,0092 | jetons facturés × tarif OpenRouter (`tarifs.json`), cumul du journal du cache |
| Juge de reclassement, 300 appels | 0,0338 | champ `usage.cost` des réponses de la passerelle (et même total au tarif) |
| Sondes manuelles initiales (dimensions, `input_type`, forme des réponses) | ≈ 0,0004 | compteur de la clé |
| **Total** | **≈ 0,043** | plafond visé 0,50 ; plafond de la clé 10 USD / 30 jours |

Compteur `/key/info` de la clé : 0,0000861 avant, 0,0342946 après toute la session. Il ne comptabilise **pas** les
embeddings (écart attendu avec l'estimation ci-dessus).

## 7. Ce qui reste à mesurer

1. **Modèles locaux sur le GB10** (bge-m3, Qwen3-Embedding 0,6B/4B, e5) : ajouter une `Config` dans `banc.py` et rejouer ;
   comparer à Voyage 4 et Gemini 2 sur les mêmes questions. Tant que ce n'est pas fait, le repli local d'embeddings est une
   hypothèse.
2. **Reranker dédié** (bge-reranker-v2-m3, Qwen3-Reranker, mxbai) contre le juge générique, en coût, latence et gain.
3. **Corpus réel anonymisé** du premier client (soumissions, factures, plaintes, notes), avec des jugements faits par
   l'utilisateur, plus de questions sans réponse, des fautes réelles, des documents longs découpés.
4. **Poids de la fusion et seuil d'abstention** par modèle, sur ce corpus réel.
5. **Dimensions réduites** de Gemini 2 (et Voyage) pour tenir dans `vector(1024)` et réduire le stockage.
6. **OCR, vision-langage** (documents numérisés, photos de chantier) : non traités ici.
7. **Débit et latence sous charge**, depuis le serveur réel et non à travers un tunnel.

## 8. Comment enregistrer l'état « mesuré » dans les registres du produit

**Rien n'a été écrit dans `src/` ni dans le catalogue de fournisseurs.** État actuel :
`opsys.fournisseurs.modele.QUALIFICATIONS = ("a_mesurer", "qualifie")`, toutes les entrées du catalogue sont `a_mesurer` et
le catalogue ne contient aucun embeddings cloud (seulement bge-m3, Qwen3-Embedding, jina écarté…). Aucun des quatre modèles
mesurés ici n'y figure : les passer à un état « mesuré » serait faux (ils n'y sont pas) ou prématuré (corpus fictif).

Proposition (changement additif, à faire par l'architecte avec ses tests de migration/registre) :

1. **Ne pas réutiliser `qualifie`** : il doit rester réservé à une mesure sur un corpus réel anonymisé du client, approuvée
   par un humain (admin).
2. Ajouter à `Fournisseur` une liste **append-only** `mesures` (chaque entrée immuable) :
   `{banc: "embeddings_fr/v1", corpus_sha256, resultat_sha256, fichier_preuve, date, portee: "corpus_fictif" | "corpus_client_anonymise",
   metriques: {"mrr@10": {...}, "rappel@5": ..., "ic95": [...]}, execute_par}`. Une mesure n'est acceptée que si
   `resultat_sha256` correspond à un fichier de `docs/qualification/preuves-*` existant (le JSON publié ici convient).
3. Afficher « mesuré sur corpus fictif (date, MRR, IC) » **sans** changer `qualification`. Un état intermédiaire
   `mesure_fictif` dans `QUALIFICATIONS` est possible mais ne doit jamais autoriser l'activation à lui seul : la politique
   d'activation (`opsys.fournisseurs.politique`) continue d'exiger la licence lue et le profil du client.
4. Les quatre modèles de cette mesure seraient d'abord **déclarés** (`registre.configurer(declaration=…)`, statut
   `declare`, licence « Propriétaire (API) », usage commercial `sur_contrat`/`inconnu`, résidence des données `inconnue` tant
   qu'elle n'est pas lue), puis recevraient leur première `mesure` avec `portee: "corpus_fictif"`.
5. Tests à prévoir : refus d'une mesure dont le SHA ne correspond à aucune preuve ; refus de `qualifie` sans mesure de portée
   `corpus_client_anonymise` ; journal d'audit de chaque ajout ; migration montée/descendue si une table est ajoutée.

## 9. Reproduire et preuves

```bash
python install/qualification/embeddings_fr/banc.py verifier
OPSYS_LITELLM_TEST_URL=… OPSYS_LITELLM_TEST_KEY_FILE=… python install/qualification/embeddings_fr/banc.py mesurer \
    --cache ~/.cache/opsys-bench-embeddings-fr --sortie docs/qualification/preuves-embeddings-fr --juge opsys-haiku-5-5
python install/qualification/embeddings_fr/banc.py rapport --resultats docs/qualification/preuves-embeddings-fr/mesure-….json
python install/qualification/embeddings_fr/mutations.py     # 60 mutations de source
```

Fichiers de preuve (`preuves-embeddings-fr/`) : `mesure-20261102T093226Z-7f27ab07.json` (jugements v1, embeddings seuls),
`mesure-20261102T093958Z-91dbf324.json` (jugements v2 + juge), `mesure-20261102T094924Z-91dbf324.json` (rejeu des mêmes
vecteurs et jugements depuis le cache, avec la matrice d'écarts entre modèles : c'est la source des tableaux ci-dessus).
Tests : `tests/test_banc_embeddings_fr.py` (75 tests sur faux serveur, métriques à valeurs connues, chargeur de corpus, RRF,
perturbation, client, cache, juge, exécution de bout en bout) ; `tests/test_banc_embeddings_fr_reel.py` (10 tests **opt-in**,
`OPSYS_LITELLM_TEST_URL` et `OPSYS_LITELLM_TEST_KEY_FILE`).
