#!/usr/bin/env bash
# Injecte 00-DIGEST.md tous les 10 tours (compteur fichier) — stdout = contexte (doc officielle hooks).
C=".claude/.digest_count"; n=$(cat "$C" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$C"
if [ $((n % 10)) -eq 1 ]; then cat 00-DIGEST.md; fi
exit 0
