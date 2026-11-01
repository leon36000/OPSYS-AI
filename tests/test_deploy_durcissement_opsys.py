"""Le service `opsys` de deploy/docker-compose.yml porte le durcissement que le banc de qualification en conteneur a
éprouvé (install/qualification/banc.py : étape « durcissement » et tout le parcours sous ces réglages).

Ce test lit le fichier Compose : il refuse qu'un de ces réglages disparaisse sans que le banc soit rejoué. Il ne prouve
pas le comportement du daemon (c'est le rôle du banc) ni le profil ingestion-pdf (non requalifié).
"""

from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[1] / "deploy" / "docker-compose.yml"


def _opsys() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["opsys"]


def test_opsys_racine_en_lecture_seule_avec_tmp_en_memoire():
    service = _opsys()
    assert service["read_only"] is True
    assert any(str(t).startswith("/tmp:") for t in service["tmpfs"])


def test_opsys_sans_capacite_ni_elevation_et_avec_limites():
    service = _opsys()
    assert service["cap_drop"] == ["ALL"] and "cap_add" not in service
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["pids_limit"] == 256 and service["mem_limit"] == "512m"


def test_opsys_ne_publie_aucun_port_et_ne_monte_que_ses_volumes():
    service = _opsys()
    assert "ports" not in service and "privileged" not in service
    cibles = [str(v).split(":")[1] for v in service["volumes"]]
    assert cibles == ["/opt/data", "/openclaw-config", "/shared/litellm-config"]
