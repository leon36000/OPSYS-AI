"""OPT-IN (OPSYS_LITELLM_IMAGE) : la configuration GÉNÉRÉE est chargée par un vrai conteneur LiteLLM.

Le conteneur démarre sur 127.0.0.1 avec la configuration des rôles et le fichier d'environnement matérialisé
depuis le coffre (overlay `docker-compose.passerelle-coffre.yml`). On vérifie qu'il accepte la configuration,
que la clé du fichier d'environnement protège `/v1/models`, que les alias attendus sont servis et que l'alias
du raisonnement ne l'est pas tant qu'il n'est pas activé. AUCUN appel de modèle (aucune clé d'amont réelle).
Données fictives ; jamais requis par la CI.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid

import pytest
import yaml
from modeles_aide import ALIAS, AMONT, CLE_AMONT, PROPRIETAIRE, affecter, fournisseur_local

from opsys.roles_modeles import generation
from opsys.secrets_coffre import coffre

FICTIF = True
IMAGE = os.environ.get("OPSYS_LITELLM_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE or shutil.which("docker") is None,
                                reason="OPSYS_LITELLM_IMAGE absent ou docker indisponible (essai opt-in)")


def _get(url, cle=None):
    requete = urllib.request.Request(url, headers={"Authorization": f"Bearer {cle}"} if cle else {})
    try:
        with urllib.request.urlopen(requete, timeout=5) as r:  # noqa: S310 — boucle locale
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_un_vrai_litellm_charge_la_configuration_generee(pret, tmp_path):
    local = fournisseur_local(pret, "llm.local.fictif", "http://127.0.0.1:8000/v1")
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], amont=AMONT["llm_rapide"],
             replis=[{"fournisseur": local, "modele": "qwen-local-fictif"}])
    affecter(pret, "llm_fort", ALIAS["llm_fort"], amont=AMONT["llm_fort"])
    affecter(pret, "llm_raisonnement", ALIAS["llm_raisonnement"], amont=AMONT["llm_raisonnement"])
    with pret() as cnx:
        config = generation.config_depuis_roles(cnx, {})
    # Le banc local n'a ni Valkey ni PostgreSQL : on retire le cache et la base, pas la liste de modèles ni les replis.
    config["litellm_settings"].pop("cache"), config["litellm_settings"].pop("cache_params")
    config["general_settings"].pop("database_url")
    dossier = tmp_path / "litellm"
    dossier.mkdir(mode=0o755)
    (dossier / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    cle = "sk-" + uuid.uuid4().hex + uuid.uuid4().hex  # LiteLLM exige une clé maître forte préfixée `sk-` (générée ici)
    with pret() as cnx:
        coffre.rotation(cnx, acteur=PROPRIETAIRE, nom="passerelle.cle", valeur=cle)
    generation.ecrire_env(pret, dossier / "litellm.env")
    os.chmod(dossier / "litellm.env", 0o644)  # lisible par l'utilisateur du conteneur, sur ce banc seulement
    nom = f"opsys-litellm-test-{uuid.uuid4().hex[:8]}"
    entree = 'set -a; . /etc/litellm/litellm.env; set +a; exec docker/prod_entrypoint.sh "$@"'
    lancement = subprocess.run(
        ["docker", "run", "-d", "--name", nom, "-p", "127.0.0.1::4000", "-v", f"{dossier}:/etc/litellm:ro",
         "-e", "LITELLM_LOCAL_MODEL_COST_MAP=True", "-e", "DISABLE_SCHEMA_UPDATE=true",
         "--entrypoint", "/bin/sh", IMAGE,
         "-c", entree, "opsys-litellm", "--config", "/etc/litellm/config.yaml", "--port", "4000", "--num_workers", "1"],
        capture_output=True, text=True, timeout=60)
    assert lancement.returncode == 0, lancement.stderr[-300:]
    try:
        port = subprocess.run(["docker", "port", nom, "4000/tcp"], capture_output=True, text=True,
                              timeout=20).stdout.strip().split(":")[-1]
        base = f"http://127.0.0.1:{port}"
        for _ in range(25):
            try:
                if _get(base + "/health/liveliness")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(2)
        else:
            journal = subprocess.run(["docker", "logs", "--tail", "25", nom], capture_output=True, text=True)
            pytest.fail("LiteLLM n'a pas démarré : " + (journal.stdout + journal.stderr)[-1500:])
        assert _get(base + "/v1/models")[0] in (401, 403)  # sans clé : refusé
        statut, corps = _get(base + "/v1/models", cle)  # la clé du coffre, écrite par `ecrire_env`, protège
        assert statut == 200
        ids = {m["id"] for m in json.loads(corps)["data"]}
        assert {"opsys-haiku-5-5", "opsys-sonnet-5-5", "opsys-rapide", "opsys-standard", "opsys-fort",
                "opsys-haiku-5-5-repli1"} <= ids
        assert "opsys-opus-5-5" not in ids  # raisonnement inactif : même pas servi
        assert CLE_AMONT not in corps.decode()
    finally:
        subprocess.run(["docker", "rm", "-f", nom], capture_output=True, timeout=30)
