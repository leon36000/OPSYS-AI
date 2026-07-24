#!/usr/bin/env bash
# v0 — bloque les patrons interdits (exit 2 = blocage, stderr = raison). Durci en Phase 0.
IN=$(cat)
CMD=$(printf '%s' "$IN" | python3 -c "import sys,json;print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)
case "$CMD" in
  *--no-verify*) echo "INTERDIT (PROOF §8): --no-verify" >&2; exit 2;;
  *"push"*"--force"*main*|*"push"*"-f"*main*) echo "INTERDIT (PROOF §8): force-push main" >&2; exit 2;;
esac
exit 0
