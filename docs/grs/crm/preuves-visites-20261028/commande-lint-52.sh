#!/bin/sh
QA="$PWD/../preuves-qa/private"
env HOME="$QA/home" OPSYS_HOME="$QA/opsys" XDG_CONFIG_HOME="$QA/xdg" XDG_CACHE_HOME="$QA/xdg" XDG_DATA_HOME="$QA/xdg" TMPDIR="$QA/tmp" RAYON_NUM_THREADS=1 MALLOC_ARENA_MAX=1 timeout 90s bwrap --unshare-net --unshare-pid --ro-bind / / --dev /dev --proc /proc --bind "$QA" "$QA" --chdir "$PWD" -- python3 ../preuves-qa/runner-03.py ../preuves-qa/venv/bin/ruff check --no-cache $(cat "$QA/lint-48-fichiers.txt")
