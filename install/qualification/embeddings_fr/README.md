# Banc de mesure des embeddings (français québécois)

Mesure reproductible de modèles d'embeddings, du BM25 local (SQLite FTS5 du dépôt), de leur fusion RRF et d'un
reclassement par un petit modèle de discussion, sur un corpus **fictif** (voir le rapport pour son contenu). Résultats et lecture :
[`docs/qualification/MESURE-EMBEDDINGS-FR-2026-11.md`](../../../docs/qualification/MESURE-EMBEDDINGS-FR-2026-11.md).
Preuves brutes (JSON, sans vecteur ni clé) : [`docs/qualification/preuves-embeddings-fr/`](../../../docs/qualification/preuves-embeddings-fr/).

## Contenu

| Fichier | Rôle |
|---|---|
| [`docs/qualification/corpus-embeddings-fr/`](../../../docs/qualification/corpus-embeddings-fr/) | les DONNÉES (hors du cœur, car propres au secteur du premier client) : 255 passages, 104 requêtes jugées (92 avec réponse, 12 sans), consigne du juge, `fictif: true` |
| `corpus.py` | chargeur/validateur (refuse corpus non fictif, jugement orphelin, courriel réel…) et perturbation déterministe des requêtes |
| `metriques.py` | rappel@k, MRR, nDCG gradué, quantiles, intervalles bootstrap, différences appariées, RRF, AUC |
| `lexical_local.py` | BM25 du produit (`opsys.connaissances.lexical` + `normalisation`) en base SQLite mémoire |
| `passerelle.py` | client LiteLLM minimal (stdlib) : clé lue d'un fichier, expurgée des erreurs, aucune redirection |
| `cache.py` | cache disque SQLite des vecteurs et journal des appels (latence, jetons, coût), refusé dans le dépôt |
| `juge.py` | reclassement des 10 premiers par un modèle de discussion (notes JSON 0 à 3, présentation mélangée) |
| `banc.py` | orchestration, CLI `verifier` / `mesurer` / `rapport` |
| `tarifs.json` | tarifs OpenRouter lus le 2026-11-02 (la passerelle déclare 0 pour tout) |
| `mutations.py` | mutations de source rejouant `tests/test_banc_embeddings_fr.py` |

## Rejouer

```bash
# 1. valider le corpus (aucun réseau)
python install/qualification/embeddings_fr/banc.py verifier

# 2. mesurer (appelle la passerelle ; le cache évite tout appel répété ; la clé reste dans un fichier)
export OPSYS_LITELLM_TEST_URL=http://127.0.0.1:14400
export OPSYS_LITELLM_TEST_KEY_FILE=/chemin/vers/la.cle
python install/qualification/embeddings_fr/banc.py mesurer --cache ~/.cache/opsys-bench-embeddings-fr \
    --sortie docs/qualification/preuves-embeddings-fr --juge opsys-haiku-5-5

# 3. rejouer depuis le cache, sans aucun appel
python install/qualification/embeddings_fr/banc.py mesurer --cache ~/.cache/opsys-bench-embeddings-fr \
    --sortie /tmp/rejeu --sans-appel
```

Le cache (`--cache`) doit rester **hors du dépôt** (il est refusé sinon) : vecteurs et réponses de modèles n'y entrent pas.
Un fichier de résultats n'est jamais écrasé (horodatage + empreinte du corpus dans le nom). Les tests par défaut
(`tests/test_banc_embeddings_fr.py`) n'utilisent qu'un faux serveur local ; le test réel
(`tests/test_banc_embeddings_fr_reel.py`) est **opt-in** (mêmes deux variables d'environnement).

## Ajouter un modèle local plus tard

Le banc lit des embeddings par une URL compatible OpenAI. Pour mesurer bge-m3 ou Qwen3-Embedding servis sur le GB10 :
ajouter une `Config` dans `banc.py` (`CONFIGURATIONS`) pointant vers le nom de modèle exposé par ce service (la passerelle
peut le router) et rejouer `mesurer` : le corpus, les métriques, le cache et le rapport sont déjà prêts.
