#!/bin/bash
# Relevé de veille (lecture seule) : pour chaque dépôt, commit de tête, fichier de licence À LA RACINE lu en entier
# (empreinte SHA-256 du contenu), activité. Ne télécharge que des fichiers texte via l'API GitHub ; n'exécute rien du dépôt.
# Usage : GH_CONFIG_DIR=<config gh> ./releve-depots.sh > licences-verifiees.tsv
# La colonne `licence_lue` est MON classement après lecture du texte (heuristique de mots-clés puis relecture humaine),
# pas la bannière du README ni le champ `license` de l'API : voir la colonne `ecart_banniere`.
set -u
DEPOTS=(
google-research/reasoning-bank taeilkim2465/agentic_memory_distillation zorazrw/agent-workflow-memory noahshinn/reflexion
MineDojo/Voyager LeapLabTHU/ExpeL ace-agent/ace WujiangXu/A-mem agiresearch/A-mem mem0ai/mem0 letta-ai/letta letta-ai/letta-code
getzep/graphiti getzep/zep topoteretes/cognee langchain-ai/langmem MemTensor/MemOS stanfordnlp/dspy gepa-ai/gepa
OSU-NLP-Group/SkillWeaver suzgunmirac/dynamic-cheatsheet zjunlp/MemP vectorize-io/hindsight TencentCloud/TencentDB-Agent-Memory
volcengine/OpenViking NousResearch/hermes-agent Lanerra/reasoning-bank-slm apple/ToolSandbox ShishirPatil/gorilla
StonyBrookNLP/appworld sierra-research/tau2-bench
)
printf 'depot\tcommit_tete\tdate_commit\tetoiles\tfichier_licence\ttaille_octets\tsha256_contenu\tlicence_lue\tspdx_api\tecart_banniere\n'
for r in "${DEPOTS[@]}"; do
  b=$(gh api "repos/$r" --jq .default_branch 2>/dev/null) || { printf '%s\tINACCESSIBLE\n' "$r"; continue; }
  meta=$(gh api "repos/$r" --jq '[(.stargazers_count|tostring),(.license.spdx_id // "NONE")]|join("\t")')
  etoiles=${meta%%$'\t'*}; spdx=${meta##*$'\t'}
  head=$(gh api "repos/$r/commits/$b" --jq '[.sha[0:12],.commit.committer.date[0:10]]|join("\t")')
  f=$(gh api "repos/$r/contents" --jq '.[]|select(.type=="file")|select(.name|test("^(LICEN[SC]E|COPYING)";"i"))|.name' | head -1)
  if [ -z "$f" ]; then
    printf '%s\t%s\t%s\t(aucun)\t0\t-\tAUCUNE LICENCE (tous droits réservés par défaut)\t%s\tà-confirmer\n' "$r" "$head" "$etoiles" "$spdx"; continue; fi
  txt=$(gh api "repos/$r/contents/$f" -H "Accept: application/vnd.github.raw")
  taille=$(printf '%s' "$txt" | wc -c); sha=$(printf '%s' "$txt" | sha256sum | cut -d' ' -f1)
  if   printf '%s' "$txt" | grep -q -i "GNU AFFERO GENERAL PUBLIC LICENSE"; then lue="AGPL-3.0"
  elif printf '%s' "$txt" | grep -q -i "Apache License" && printf '%s' "$txt" | grep -q "Version 2.0"; then lue="Apache-2.0"
  elif printf '%s' "$txt" | grep -q -i "Permission is hereby granted, free of charge"; then lue="MIT"
  elif printf '%s' "$txt" | grep -q -i "Apple software is supplied"; then lue="Licence Apple propre (non OSI)"
  else lue="À RELIRE À LA MAIN"; fi
  ecart="non"; case "$spdx" in NOASSERTION|NONE) ecart="API sans verdict : texte lu";; esac
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$r" "$head" "$etoiles" "$f" "$taille" "$sha" "$lue" "$spdx" "$ecart"
done
