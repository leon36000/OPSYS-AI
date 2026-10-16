"""CF040 : scripts inchangés, PostgreSQL réel et volumes exclusivement fictifs.

Le Compose minimal emploie des conteneurs applicatifs inactifs : ni déploiement
complet, ni worker, ni fournisseur. Les tâches couvertes sont l'outbox Core
pending/retry et sa réservation uncertain, pas un nouveau système de tâches.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import ipaddress
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import tarfile
import time
import uuid
from pathlib import Path

import pytest
import yaml
from m10_memoire import faits_candidats, registre
from sqlalchemy import URL, select, text

from opsys import stockage
from opsys.stockage.schema import META

ROOT = Path(__file__).resolve().parents[2]
VOLUMES = ("opsys_data", "openclaw_config", "openclaw_auth_secrets",
           "caddy_data", "caddy_config", "litellm_config", "postgres_data")
CORE_PATH = "agents/m03-estimation/agent/openclaw-agent.sqlite"
MAX_BYTES = 8 * 1024 * 1024


def _image_preparee():
    """Réutilise exactement la référence que le job a préparée, sans pull."""
    spec = importlib.util.spec_from_file_location("cf040_preparation_pg", ROOT / "scripts/ci/preparer_pgvector.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert re.fullmatch(r"pgvector/pgvector@sha256:[0-9a-f]{64}", module.REFERENCE)
    return module.REFERENCE


def _archive_fichiers(fichiers):
    sortie = io.BytesIO()
    with tarfile.open(fileobj=sortie, mode="w:gz") as archive:
        for nom, donnees in fichiers.items():
            assert not nom.startswith("/") and ".." not in Path(nom).parts
            info = tarfile.TarInfo(nom)
            info.size, info.mode = len(donnees), 0o600
            archive.addfile(info, io.BytesIO(donnees))
    return sortie.getvalue()


def _fichiers_archive(donnees):
    assert len(donnees) <= MAX_BYTES
    with tarfile.open(fileobj=io.BytesIO(donnees), mode="r:gz") as archive:
        resultat = {}
        total = 0
        for membre in archive.getmembers():
            assert not membre.issym() and not membre.islnk()
            assert not membre.name.startswith("/") and ".." not in Path(membre.name).parts
            if membre.isdir():
                continue
            assert membre.isfile()
            total += membre.size
            assert total <= MAX_BYTES
            fichier = archive.extractfile(membre)
            assert fichier is not None
            resultat[membre.name.removeprefix("./")] = fichier.read()
        return resultat


def _core_fictif(chemin):
    with sqlite3.connect(chemin) as db:
        db.executescript((ROOT / "core/src/state/openclaw-agent-schema.sql").read_text())
        for etat, ident, tentatives in (("pending", "a", 0), ("retry", "b", 1)):
            payload = json.dumps({
                "affaire_id": "LEAD-CF040-FICTIF", "departement_source": "m03-estimation",
                "profil_id": "cf040-fictif", "revision": 1, "engine_id": "opsys",
                "faits": [{"cle": "tc-" + ident * 40, "outil": "m3_estimer_projet",
                           "resultat": "ok", "code": None}],
            }, separators=(",", ":"))
            lot_key = "postflight-" + hashlib.sha256(("tc-" + ident * 40).encode()).hexdigest()
            db.execute(
                "INSERT INTO opsys_postflight_outbox "
                "(lot_key,affaire_id,departement_source,profil_id,revision_admission,engine_id,payload_json,"
                "state,attempt_count,created_at,updated_at,next_attempt_at,last_attempt_at,last_error_code) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (lot_key, "LEAD-CF040-FICTIF", "m03-estimation", "cf040-fictif", 1,
                 "opsys", payload, etat, tentatives, 1000, 1000, 2000,
                 1000 if tentatives else None, "M10_ACK_INCONNU" if tentatives else None),
            )
        intention = {"factKey": "tc-" + "c" * 40, "affaireId": "LEAD-CF040-FICTIF",
                     "departementSource": "m03-estimation", "profilId": "cf040-fictif",
                     "revision": 1, "engineId": "opsys", "outil": "m3_creer_devis",
                     "serverName": "opsys_m3", "ownerKey": "d" * 64}
        db.execute("INSERT INTO opsys_postflight_intents VALUES (?,?,?,?)",
                   (intention["factKey"], json.dumps(intention, separators=(",", ":")), "uncertain", 1000))
    return chemin.read_bytes()


def _lire_core(chemin, contenu):
    chemin.write_bytes(contenu)
    with sqlite3.connect(f"file:{chemin}?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        db.row_factory = sqlite3.Row
        return {table: [dict(ligne) for ligne in db.execute(f"SELECT * FROM {table} ORDER BY 1")]
                for table in ("opsys_postflight_outbox", "opsys_postflight_intents")}



def _cible_pg_interne_possedee(detail, reseau, projet):
    """Lie la cible SQL au seul bridge interne possédé, sans port publié ni repli."""
    nom = projet + "_default"
    assert detail["Config"]["Labels"]["com.docker.compose.project"] == projet
    assert detail["Config"]["Labels"]["com.docker.compose.service"] == "postgres"
    assert not detail["HostConfig"]["PortBindings"]
    assert not any(detail["NetworkSettings"]["Ports"].values())
    assert set(detail["NetworkSettings"]["Networks"]) == {nom}
    assert reseau["Name"] == nom and reseau["Driver"] == "bridge" and reseau["Internal"] is True
    assert reseau["Labels"]["com.docker.compose.project"] == projet
    assert reseau["Labels"]["com.docker.compose.network"] == "default"
    assert reseau["Options"].get("com.docker.network.bridge.gateway_mode_ipv4", "nat") != "isolated"
    endpoint = detail["NetworkSettings"]["Networks"][nom]
    assert endpoint["NetworkID"] == reseau["Id"]
    assert set(reseau["Containers"]) == {detail["Id"]}
    membre = reseau["Containers"][detail["Id"]]
    assert endpoint["EndpointID"] == membre["EndpointID"] and endpoint["EndpointID"]
    assert membre["Name"] == detail["Name"].removeprefix("/")
    adresse = ipaddress.IPv4Interface(f"{endpoint['IPAddress']}/{endpoint['IPPrefixLen']}")
    assert adresse == ipaddress.IPv4Interface(membre["IPv4Address"])
    sous_reseaux = [c for c in reseau["IPAM"]["Config"] if ":" not in c["Subnet"]]
    assert len(sous_reseaux) == 1
    sous_reseau = ipaddress.IPv4Network(sous_reseaux[0]["Subnet"])
    assert adresse.network == sous_reseau and adresse.ip in sous_reseau
    assert adresse.ip.is_private and not any((adresse.ip.is_loopback, adresse.ip.is_link_local,
                                              adresse.ip.is_multicast, adresse.ip.is_unspecified,
                                              adresse.ip.is_reserved))
    assert adresse.ip not in (sous_reseau.network_address, sous_reseau.broadcast_address,
                              ipaddress.IPv4Address(sous_reseaux[0]["Gateway"]))
    return {"host": str(adresse.ip), "port": 5432, "container_id": detail["Id"],
            "network_id": reseau["Id"], "endpoint_id": endpoint["EndpointID"],
            "subnet": str(sous_reseau), "internal": True, "published_ports": False}


def _instantane_pg():
    with stockage.transaction() as cnx:
        return {nom: sorted(json.dumps(dict(ligne), sort_keys=True, default=str)
                            for ligne in cnx.execute(select(table)).mappings())
                for nom, table in META.tables.items()}


def _etat_arret_possede(details, ids, projet, image):
    """Métadonnées des seuls conteneurs déjà attribués ; aucun environnement exporté."""
    assert len(details) == len(ids) == len(set(ids)) == 4
    assert {d["Id"] for d in details} == set(ids)
    resultat = {}
    for detail in details:
        config = detail["Config"]
        labels = config["Labels"]
        assert labels["com.docker.compose.project"] == projet and config["Image"] == image
        service = labels["com.docker.compose.service"]
        assert service in {"opsys", "openclaw-gateway", "caddy", "postgres"} and service not in resultat
        resultat[service] = {
            "id": detail["Id"], "path": detail["Path"], "args": detail["Args"],
            "entrypoint": config.get("Entrypoint"), "cmd": config.get("Cmd"),
            "stop_signal": config.get("StopSignal"), "init": detail["HostConfig"].get("Init"),
            "state": {k: detail["State"][k] for k in (
                "Status", "Running", "Pid", "ExitCode", "Error", "OOMKilled", "StartedAt", "FinishedAt")},
            "restart_count": detail["RestartCount"],
        }
    return resultat


@pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="Restauration PostgreSQL réelle réservée au job frontiere-postgresql explicite",
)
def test_backup_restore_postgresql_et_outbox_inconnue_isoles(tmp_path, monkeypatch, record_property):
    """Ce test ne lance pas Docker à la collecte ; le conftest e2e peut sonder le démon."""
    debut = time.monotonic()
    limite = debut + 160  # vingt secondes restent réservées au nettoyage possédé
    projet = "cf040-" + uuid.uuid4().hex
    deploy = tmp_path / "deploy-fictif"
    deploy.mkdir(mode=0o700)
    home = tmp_path / "home-fictif"
    home.mkdir(mode=0o700)
    image = _image_preparee()
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": str(tmp_path),
           "LANG": "C.UTF-8", "DOCKER_CONFIG": str(home / ".docker"),
           "COMPOSE_PROJECT_NAME": projet, "RESTIC_REPOSITORY": "", "RESTIC_PASSWORD": "",
           "OPSYS_BACKUP_IMAGE": image, "OPSYS_BACKUP_STOP_TIMEOUT_SECONDS": "10",
           "OPSYS_BACKUP_START_TIMEOUT_SECONDS": "15"}
    assert not {"DOCKER_HOST", "DOCKER_CONTEXT", "HTTP_PROXY", "HTTPS_PROXY"} & env.keys()

    def run(args, *, entree=None, succes=True, nettoyage=False):
        restant = min(20, debut + 180 - time.monotonic()) if nettoyage else min(40, limite - time.monotonic())
        assert restant > 0, "budget de restauration CF040 épuisé"
        processus = subprocess.Popen(
            list(map(str, args)), cwd=deploy, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        try:
            stdout, stderr = processus.communicate(entree, timeout=restant)
        except subprocess.TimeoutExpired:
            # Uniquement le groupe de processus que ce test vient de créer.
            if processus.poll() is None:
                os.killpg(processus.pid, signal.SIGKILL)
            processus.communicate(timeout=5)
            raise
        assert len(stdout) + len(stderr) <= MAX_BYTES
        if succes:
            assert processus.returncode == 0, (args, stderr.decode(errors="replace")[-4000:])
        return processus.returncode, stdout, stderr

    compose = ["docker", "compose", "--profile", "database", "--env-file", deploy / ".env",
               "-f", deploy / "docker-compose.yml"]
    for nom in ("backup.sh", "restore.sh"):
        shutil.copyfile(ROOT / "deploy" / nom, deploy / nom)
        assert (deploy / nom).read_bytes() == (ROOT / "deploy" / nom).read_bytes()
    (deploy / ".env").write_text(
        "OPSYS_MODE_FOURNISSEUR=natif\n"
        "OPSYS_DATABASE_URL=postgresql://opsys:mot-de-passe-fictif@postgres:5432/opsys\n"
    )
    (deploy / ".env").chmod(0o600)
    services = {"postgres": {
        "image": image, "pull_policy": "never", "profiles": ["database"], "mem_limit": "1g",
        "environment": {"POSTGRES_USER": "opsys", "POSTGRES_PASSWORD": "mot-de-passe-fictif",
                        "POSTGRES_DB": "opsys"},
        "volumes": ["postgres_data:/var/lib/postgresql/data"],
        "healthcheck": {"test": ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U opsys -d opsys"],
                        "interval": "1s", "timeout": "2s", "retries": 30},
    }}
    montages = {"opsys": ["opsys_data:/data", "litellm_config:/litellm"],
                "openclaw-gateway": ["openclaw_config:/config", "openclaw_auth_secrets:/auth"],
                "caddy": ["caddy_data:/data", "caddy_config:/config"]}
    for nom, volumes in montages.items():
        services[nom] = {"image": image, "pull_policy": "never", "mem_limit": "64m",
                         "entrypoint": ["sleep", "infinity"], "network_mode": "none", "volumes": volumes}
    modele = {"name": projet, "services": services, "volumes": {n: {} for n in VOLUMES},
              "networks": {"default": {"internal": True}}}
    (deploy / "docker-compose.yml").write_text(yaml.safe_dump(modele, sort_keys=False))
    inspect_image = json.loads(run(["docker", "image", "inspect", image])[1])[0]
    assert image in inspect_image["RepoDigests"]
    configuration = json.loads(run([*compose, "config", "--format", "json"])[1])
    assert configuration["name"] == projet and set(configuration["services"]) == set(services)
    noms_volumes = {n: configuration["volumes"][n]["name"] for n in VOLUMES}
    assert all(nom == f"{projet}_{cle}" for cle, nom in noms_volumes.items())
    assert all(not v.get("external") for v in configuration["volumes"].values())
    # Une collision sans label n'autorise jamais la prise en charge d'une ressource.
    assert not json.loads(run(["docker", "volume", "inspect", *noms_volumes.values()], succes=False)[1])
    assert not json.loads(run(["docker", "network", "inspect", projet + "_default"], succes=False)[1])
    for kind in ("container", "volume", "network"):
        arguments = (["docker", "ps", "--all", "--quiet"] if kind == "container"
                     else ["docker", kind, "ls", "--quiet"])
        assert not run([*arguments, "--filter", f"label=com.docker.compose.project={projet}"])[1].strip()

    def proprietaires(*, nettoyage=False):
        ids = run([*compose, "ps", "--all", "--quiet"], nettoyage=nettoyage)[1].decode().split()
        if ids:
            details = json.loads(run(["docker", "inspect", *ids], nettoyage=nettoyage)[1])
            assert all(d["Config"]["Labels"]["com.docker.compose.project"] == projet for d in details)
        for nom in noms_volumes.values():
            code, stdout, _ = run(["docker", "volume", "inspect", nom], succes=False, nettoyage=nettoyage)
            if code == 0:
                assert json.loads(stdout)[0]["Labels"]["com.docker.compose.project"] == projet
        code, stdout, _ = run(["docker", "network", "inspect", projet + "_default"],
                              succes=False, nettoyage=nettoyage)
        if code == 0:
            assert json.loads(stdout)[0]["Labels"]["com.docker.compose.project"] == projet
        return ids

    def volume(cle, fichiers=None):
        assert cle in noms_volumes
        proprietaires()
        commande = ["docker", "run", "--rm", "--pull=never", "--memory=128m", "--network=none",
                    "--label", f"com.docker.compose.project={projet}", "--label", "cf040.role=fixture-helper",
                    "--user", "0", "--entrypoint", "sh", "-v", f"{noms_volumes[cle]}:/volume", image]
        if fichiers is None:
            return _fichiers_archive(run([*commande, "-c", "tar -C /volume -czf - ."])[1])
        commande.insert(3, "-i")
        run([*commande, "-c",
             "find /volume -mindepth 1 -maxdepth 1 -exec rm -rf {} +; tar -C /volume -xzf -"],
            entree=_archive_fichiers(fichiers))

    def etats_services():
        details = json.loads(run(["docker", "inspect", *proprietaires()])[1])
        return {d["Id"]: (d["State"]["Status"], d["State"]["StartedAt"], d["RestartCount"])
                for d in details}  # les dates du journal healthcheck ne sont pas de la donnée métier

    demarrage_tente = False
    try:
        demarrage_tente = True
        run(["docker", "run", "--rm", "--name", projet + "-preflight", "--pull=never",
             "--label", f"com.docker.compose.project={projet}", "--label", "cf040.role=preflight",
             "--network=none", "--memory=128m", "--read-only", "--entrypoint", "sh", image, "-ec",
             "command -v tar; command -v gzip; command -v find; command -v sleep; "
             "pg_dump --version; psql --version"])
        run([*compose, "up", "-d", "--wait", "--wait-timeout", "30", "--pull", "never"])
        for d in json.loads(run(["docker", "inspect", *proprietaires()])[1]):
            assert d["Config"]["Image"] == image
            service = d["Config"]["Labels"]["com.docker.compose.service"]
            if service != "postgres":
                assert d["HostConfig"]["Memory"] == 64 * 1024**2
                assert d["Config"]["Entrypoint"] == ["sleep", "infinity"]
                assert not d["HostConfig"]["PortBindings"]
        postgres = run([*compose, "ps", "--quiet", "postgres"])[1].decode().strip()
        detail = json.loads(run(["docker", "inspect", postgres])[1])[0]
        assert detail["HostConfig"]["Memory"] == 1024**3
        reseau = json.loads(run(["docker", "network", "inspect", projet + "_default"])[1])[0]
        cible = _cible_pg_interne_possedee(detail, reseau, projet)
        record_property("cf040_network", json.dumps(cible, sort_keys=True))

        def verifier_cible():
            # restore.sh appelle compose up : une recréation ne permet aucun repli SQL.
            courant = json.loads(run(["docker", "inspect", postgres])[1])[0]
            bridge = json.loads(run(["docker", "network", "inspect", projet + "_default"])[1])[0]
            actuelle = _cible_pg_interne_possedee(courant, bridge, projet)
            # stop/start peut renouveler l’endpoint : son lien courant doit être valide,
            # tandis que conteneur, réseau et cible SQL restent strictement identiques.
            assert {k: v for k, v in actuelle.items() if k != "endpoint_id"} == {
                k: v for k, v in cible.items() if k != "endpoint_id"}
            return actuelle

        assert run([*compose, "exec", "-T", "postgres", "psql", "-At", "-U", "opsys", "-d", "opsys",
                    "-c", "SHOW server_version_num"])[1].strip().startswith(b"17")
        monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home-fictif"))
        url = URL.create(
            "postgresql+psycopg", username="opsys", password="mot-de-passe-fictif",
            host=cible["host"], port=cible["port"], database="opsys",
            query={"connect_timeout": "5", "options": "-c statement_timeout=5000 -c lock_timeout=2000"},
        )
        cible_url = url.render_as_string(hide_password=False)
        monkeypatch.setenv(stockage.ENV_URL, cible_url)
        assert stockage.connexion_courante() is None
        moteur_possede = stockage.moteur(cible_url)
        assert moteur_possede.dialect.name == "postgresql"
        assert moteur_possede.url == url
        # La cible est vérifiée avant la première écriture ; vider seulement son pool
        # impose une connexion fraîche à l’adresse interne dont on vient de prouver la propriété.
        moteur_possede.dispose()
        verifier_cible()
        stockage.migrer(cible_url)
        faits = [{"cle": "tc-" + "a" * 40, "outil": "m3_estimer_projet", "resultat": "ok", "code": None}]
        with stockage.transaction():
            journal = registre.Registre(stockage.maillons("m10-memoire", "affaires"))
            resultat, refus = faits_candidats.deposer_faits_candidats(
                "LEAD-CF040-FICTIF", "m03-estimation", faits, "2026-10-15T12:00:00Z", journal)
            assert refus is None and resultat["ecrits"] == 1
            attendu_m10 = journal.lire()
            assert len(attendu_m10) == 1 and journal.valider_chaine() == (True, "")
        attendu_pg = _instantane_pg()
        core = _core_fictif(tmp_path / "core-source.sqlite")
        attendu_core = _lire_core(tmp_path / "core-inspection.sqlite", core)
        lots = attendu_core["opsys_postflight_outbox"]
        assert len(lots) == 2 and {lot["state"] for lot in lots} == {"pending", "retry"}
        assert [(lot["attempt_count"], lot["last_error_code"]) for lot in lots if lot["state"] == "retry"] == [
            (1, "M10_ACK_INCONNU")]
        (reserve,) = attendu_core["opsys_postflight_intents"]
        assert reserve["state"] == "uncertain" and reserve["fact_key"] == "tc-" + "c" * 40
        fichiers_attendus = {n: {"generation-fictive.txt": b"generation-source-fictive"}
                            for n in VOLUMES if n != "postgres_data"}
        fichiers_attendus["openclaw_config"][CORE_PATH] = core
        for cle, fichiers in fichiers_attendus.items():
            volume(cle, fichiers)
        stockage.liberer()
        ids_avant_backup = proprietaires()

        def observer_arret(etape):
            # Réinspecter les ID exacts, sans repli sur un nom ni export de Config.Env.
            details = json.loads(run(["docker", "inspect", *ids_avant_backup])[1])
            record_property("cf040_stop_" + etape, json.dumps(
                _etat_arret_possede(details, ids_avant_backup, projet, image), sort_keys=True))

        observer_arret("avant")
        avant_backup = time.monotonic()
        code_backup, stdout_backup, stderr_backup = run(
            ["bash", deploy / "backup.sh", "--out", tmp_path / "backups-fictifs"], succes=False)
        secondes_backup = time.monotonic() - avant_backup
        # Le repr pytest tronquait le stderr : conserver les deux flux bornés dans JUnit,
        # avant toute inspection susceptible d'échouer. Ce délai est celui du script entier.
        record_property("cf040_backup_command", json.dumps({
            "returncode": code_backup, "seconds": secondes_backup,
            "stdout": stdout_backup.decode(errors="backslashreplace"),
            "stderr": stderr_backup.decode(errors="backslashreplace"),
            "stdout_sha256": hashlib.sha256(stdout_backup).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr_backup).hexdigest(),
            "stdout_bytes": len(stdout_backup), "stderr_bytes": len(stderr_backup),
        }, sort_keys=True))
        try:
            observer_arret("apres")
        finally:
            # L'échec du backup reste primaire ; celui de l'inspection reste chaîné.
            # Si le backup réussit, une inspection invalide continue de faire échouer le test.
            assert code_backup == 0, "backup.sh en échec ; flux complets dans cf040_backup_command"
        (archive,) = list((tmp_path / "backups-fictifs").iterdir())
        manifeste = (archive / "MANIFEST.txt").read_text()
        empreintes_archives = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in archive.iterdir()}
        assert "database=postgres" in manifeste and "required=postgres:opsys" in manifeste
        assert "volume:postgres_data" not in manifeste
        assert (archive / "postgres-opsys.sql.gz").stat().st_size > 0
        copie_corrompue = tmp_path / "archive-corrompue-fictive"
        shutil.copytree(archive, copie_corrompue)
        (copie_corrompue / "postgres-opsys.sql.gz").write_bytes(b"gzip-corrompu-fictif")
        verifier_cible()
        avant_refus = _instantane_pg()
        etats = etats_services()
        code, _, erreur = run(["bash", deploy / "restore.sh", "--from", copie_corrompue, "--yes"], succes=False)
        assert code != 0 and b"illisible ou incomplet" in erreur
        verifier_cible()
        assert _instantane_pg() == avant_refus
        assert etats_services() == etats
        assert all(volume(cle) == fichiers for cle, fichiers in fichiers_attendus.items())
        proprietaires()
        verifier_cible()
        with stockage.transaction() as cnx:
            cnx.execute(text("DROP SCHEMA public CASCADE"))
            cnx.execute(text("CREATE SCHEMA public AUTHORIZATION opsys"))
            cnx.execute(text("CREATE TABLE cf040_generation_remplacee (fictif integer)"))
            cnx.execute(text("INSERT INTO cf040_generation_remplacee VALUES (1)"))
        stockage.liberer()
        for cle in fichiers_attendus:
            volume(cle, {"generation-remplacee-fictive.txt": b"ne-doit-pas-survivre"})
        avant_restore = time.monotonic()
        run(["bash", deploy / "restore.sh", "--from", archive, "--yes"])
        secondes_restore = time.monotonic() - avant_restore
        cible_apres_restore = verifier_cible()
        record_property("cf040_network_after_restore", json.dumps(cible_apres_restore, sort_keys=True))
        assert _instantane_pg() == attendu_pg
        with stockage.transaction() as cnx:
            assert cnx.execute(text("SELECT to_regclass('public.cf040_generation_remplacee')")).scalar_one() is None
            journal = registre.Registre(stockage.maillons("m10-memoire", "affaires"))
            assert journal.lire() == attendu_m10 and journal.valider_chaine() == (True, "")
        assert all(volume(cle) == fichiers for cle, fichiers in fichiers_attendus.items())
        restaure = volume("openclaw_config")[CORE_PATH]
        assert _lire_core(tmp_path / "core-restaure.sqlite", restaure) == attendu_core
        assert {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in archive.iterdir()} == empreintes_archives
        record_property("cf040", json.dumps({
            "fictif": True, "projet": projet, "network": cible, "image": image, "image_id": inspect_image["Id"],
            "seconds": round(time.monotonic() - debut, 3), "faits_m10": 1,
            "backup_command_seconds": round(secondes_backup, 3),
            "restore_command_seconds": round(secondes_restore, 3),
            "archives_sha256": empreintes_archives,
            "outbox": ["pending", "retry:M10_ACK_INCONNU"], "reservation": "uncertain",
            "archive_corrompue_refusee": True, "scripts_sha256": {
                n: hashlib.sha256((deploy / n).read_bytes()).hexdigest() for n in ("backup.sh", "restore.sh")},
            "limites": "Compose minimal/idle, digestCI pas imageComposeproduction; "
                       "aucun worker/provider/PGdata physique; tâches Core semées via schéma SQL, pas APIworker; "
                       "helpers tar des scripts non capés par leur CLI; "
                       "corruption gzip invalide, pas authentification cryptographique du backup; "
                       "durées pas RTOproduction",
        }, sort_keys=True))
    finally:
        stockage.liberer()
        if demarrage_tente:
            proprietaires(nettoyage=True)
            # Un CLI interrompu peut laisser un helper sans label. Image et montage
            # ne prouvent pas sa propriété : garder ce résultat inconnu, sans rejeu
            # ni suppression. Seuls nos conteneurs explicitement marqués sont retirés.
            ids = set(run(["docker", "ps", "--all", "--quiet", "--filter",
                           f"label=com.docker.compose.project={projet}"], nettoyage=True)[1].decode().split())
            attaches = set()
            for nom in noms_volumes.values():
                attaches.update(run(["docker", "ps", "--all", "--quiet", "--filter", f"volume={nom}"],
                                    nettoyage=True)[1].decode().split())
            assert not attaches - ids, "helper non attribué conservé ; aucun nettoyage destructif ni rejeu"
            if ids:
                for d in json.loads(run(["docker", "inspect", *sorted(ids)], nettoyage=True)[1]):
                    assert d["Config"]["Image"] == image
                    labels = d["Config"].get("Labels") or {}
                    assert labels.get("com.docker.compose.project") == projet
                run(["docker", "rm", "--force", *sorted(ids)], nettoyage=True)
            run([*compose, "down", "--volumes", "--timeout", "3"], nettoyage=True)
            assert not run(["docker", "ps", "--all", "--quiet", "--filter",
                            f"label=com.docker.compose.project={projet}"], nettoyage=True)[1].strip()
            for kind in ("volume", "network"):
                assert not run(["docker", kind, "ls", "--quiet", "--filter",
                                f"label=com.docker.compose.project={projet}"], nettoyage=True)[1].strip()
