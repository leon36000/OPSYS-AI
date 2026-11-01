"""deploy/entrypoint.sh : un arrêt demandé (SIGTERM, `docker stop`) sort avec 0 ; un processus qui meurt sort avec 1.

Relevé par la qualification en conteneur : avant le correctif, `docker stop` donnait le code 1 et un message
« un processus longue durée s'est arrêté » mensonger. Ici le MCP et la console sont de faux processus (`sleep`) ;
le vrai script et le vrai `permissions.py` s'exécutent. Données fictives, aucun réseau.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(os.geteuid() == 0, reason="permissions.py refuse root (service non-root requis)")


def _faux_binaires(dossier: Path, mcp_meurt: bool) -> None:
    dossier.mkdir()
    for nom, corps in (
        ("opsys-metier", "exit 0"),
        ("opsys-mcp", 'echo demarre >>"$MARQUEUR"; ' + ("exit 3" if mcp_meurt else "exec sleep 300")),
        ("opsys-console", 'echo demarre >>"$MARQUEUR"; exec sleep 300'),
    ):
        script = dossier / nom
        script.write_text(f"#!/bin/sh\n{corps}\n")
        script.chmod(0o755)


def _lancer(tmp_path: Path, mcp_meurt: bool) -> tuple[subprocess.Popen, Path, Path]:
    config, data = tmp_path / "config", tmp_path / "data"
    config.mkdir(mode=0o700)
    data.mkdir(mode=0o700)
    _faux_binaires(tmp_path / "bin", mcp_meurt)
    marqueur, journal = tmp_path / "marqueur", tmp_path / "journal"
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}", "OPSYS_HOME": str(data),
           "OPENCLAW_CONFIG_DIR": str(config), "LITELLM_CONFIG_DIR": str(tmp_path / "absent"),
           "OPSYS_MODE_FOURNISSEUR": "natif",
           "OPSYS_SYNC_INTERVAL_SECONDS": "1", "MARQUEUR": str(marqueur)}
    env.pop("OPSYS_DATABASE_URL", None)
    with journal.open("wb") as sortie:
        processus = subprocess.Popen(["sh", str(RACINE / "deploy/entrypoint.sh")], env=env, stdout=sortie,
                                     stderr=subprocess.STDOUT, start_new_session=True)
    return processus, marqueur, journal


def _attendre_deux_demarrages(marqueur: Path, processus: subprocess.Popen) -> None:
    fin = time.monotonic() + 15
    while time.monotonic() < fin and processus.poll() is None:
        if marqueur.exists() and len(marqueur.read_text().split()) >= 2:
            return
        time.sleep(0.05)


def test_sigterm_sort_avec_zero_sans_faux_message_de_panne(tmp_path):
    processus, marqueur, journal = _lancer(tmp_path, mcp_meurt=False)
    try:
        _attendre_deux_demarrages(marqueur, processus)
        assert processus.poll() is None, journal.read_text()
        processus.send_signal(signal.SIGTERM)
        assert processus.wait(timeout=15) == 0
    finally:
        if processus.poll() is None:
            os.killpg(processus.pid, signal.SIGKILL)
    texte = journal.read_text()
    assert "arrêt demandé" in texte and "un processus longue durée s'est arrêté" not in texte


def test_un_processus_qui_meurt_fait_sortir_le_conteneur_avec_un_code_1(tmp_path):
    processus, marqueur, journal = _lancer(tmp_path, mcp_meurt=True)
    try:
        assert processus.wait(timeout=20) == 1
    finally:
        if processus.poll() is None:
            os.killpg(processus.pid, signal.SIGKILL)
    texte = journal.read_text()
    assert "un processus longue durée s'est arrêté" in texte and "arrêt demandé" not in texte
