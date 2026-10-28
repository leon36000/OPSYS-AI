#!/bin/sh
QA="$PWD/../preuves-qa/private"
env HOME="$QA/home" OPSYS_HOME="$QA/opsys" XDG_CONFIG_HOME="$QA/xdg" XDG_CACHE_HOME="$QA/xdg" XDG_DATA_HOME="$QA/xdg" TMPDIR="$QA/tmp" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 timeout 90s bwrap --unshare-net --unshare-pid --ro-bind / / --dev /dev --proc /proc --bind "$QA" "$QA" --chdir "$PWD" -- python3 docs/grs/crm/preuves-visites-20261028/runner-logs-01.py ../preuves-qa/venv/bin/python -m pytest -p no:cacheprovider -q --junitxml="$QA/serveur-logs-04.xml" tests/test_console_logs_visites.py
