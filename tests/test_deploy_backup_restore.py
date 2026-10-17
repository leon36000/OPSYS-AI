"""Sauvegarde/restauration Docker avec une commande docker factice et des volumes temporaires."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import tarfile
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOGIQUES = ("opsys_data", "openclaw_config", "openclaw_auth_secrets", "litellm_config", "caddy_data")
PERSISTANTS_NATIFS = ("opsys_data", "openclaw_config", "openclaw_auth_secrets", "caddy_data", "caddy_config")
LOGIQUES_FIXTURE = (*LOGIQUES, "caddy_config", "postgres_data")
PROJET = "client-production-fictif"


@pytest.fixture
def banc_docker(tmp_path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    shutil.copy2(ROOT / "deploy" / "backup.sh", deploy / "backup.sh")
    shutil.copy2(ROOT / "deploy" / "restore.sh", deploy / "restore.sh")
    shutil.copy2(ROOT / "deploy" / "docker-compose.yml", deploy / "docker-compose.yml")
    (deploy / ".env").write_text(
        "OPSYS_MODE_FOURNISSEUR=natif\nPOSTGRES_OPSYS_PASSWORD=secret-fictif\n",
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    volumes_dir = tmp_path / "volumes"
    volumes_dir.mkdir()
    mapping = {}
    modeled_volumes = {}
    for logical in LOGIQUES_FIXTURE:
        physical = f"{PROJET}_{logical}"
        mount = volumes_dir / physical
        mount.mkdir()
        (mount / "preuve.txt").write_text(f"donnee-{logical}-fictive\n", encoding="utf-8")
        mapping[physical] = str(mount)
        modeled_volumes[logical] = {"name": physical}

    compose_model = {"name": PROJET, "volumes": modeled_volumes}
    (tmp_path / "compose-model.json").write_text(json.dumps(compose_model), encoding="utf-8")
    (tmp_path / "compose-state.json").write_text(json.dumps({
        "postgres": "running", "opsys": "running", "openclaw-gateway": "running",
        "caddy": "running", "litellm": "exited",
    }), encoding="utf-8")
    (tmp_path / "volumes.json").write_text(json.dumps(mapping), encoding="utf-8")
    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import json, os, pathlib, shutil, sys, tarfile, time
args = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")
if args[:1] == ["compose"]:
    rest = args[1:]
    profiles = []
    while rest and rest[0] in ("--profile", "--env-file", "-f"):
        if rest[0] == "--profile":
            profiles.append(rest[1])
        rest = rest[2:]
    state_file = pathlib.Path(os.environ["FAKE_COMPOSE_STATE"])
    state = json.loads(state_file.read_text(encoding="utf-8"))
    def save_state():
        pending = state_file.with_suffix(".pending")
        pending.write_text(json.dumps(state), encoding="utf-8")
        pending.replace(state_file)
    late_stop = os.environ.get("FAKE_STOP_ACCEPTED_NONTERMINAL") == "1"
    daemon_file = state_file.with_suffix(".daemon")
    events_file = state_file.with_suffix(".events")
    def event(kind, **details):
        events = json.loads(events_file.read_text()) if events_file.exists() else []
        events.append({"event": kind, **details})
        events_file.write_text(json.dumps(events))
    if rest[:1] == ["ps"]:
        rows = [{"Service": name, "State": status,
                 "Health": "healthy" if status == "running" else ""}
                for name, status in state.items()]
        health_file = state_file.with_suffix(".health")
        if health_file.exists():
            pending = json.loads(health_file.read_text())
            for row in rows:
                if row["Service"] in pending["targets"] and row["State"] == "running":
                    row["Health"] = "starting" if time.monotonic() < pending["until"] else pending["after"]
        if os.environ.get("FAKE_COMPOSE_PS_DUPLICATE_POSTGRES") == "1":
            rows.extend(dict(row) for row in rows[:len(rows)] if row["Service"] == "postgres")
        if late_stop and daemon_file.exists():
            pending = json.loads(daemon_file.read_text())
            if pending["phase"] == "accepted_not_terminal":
                event("ps_snapshot_before_terminal", states={row["Service"]: row["State"] for row in rows})
                for name in pending["targets"]:
                    state[name] = "exited"
                save_state()
                pending["phase"] = "terminal"
                daemon_file.write_text(json.dumps(pending))
                event("daemon_stop_terminal")
        print(json.dumps(rows))
    if rest[:1] == ["stop"]:
        if late_stop:
            targets = [name for name in rest[1:] if name in state]
            intention = state_file.parent / "deploy/.opsys-backup-intention.json"
            before = json.loads(intention.read_text()) if intention.exists() else None
            daemon_file.write_text(json.dumps({"phase": "accepted_not_terminal", "targets": targets}))
            event("stop_accepted", intention=before,
                  mode=intention.stat().st_mode & 0o777 if intention.exists() else None)
            raise SystemExit(124)  # ACK inconnu simulé, pas un timeout Docker natif.
        time.sleep(float(os.environ.get("FAKE_STOP_DELAY", "0")))
        for name in rest[1:]:
            if name in state:
                if (os.environ.get("FAKE_STOP_NO_EFFECT") != "1"
                        and os.environ.get("FAKE_STOP_NO_EFFECT_SERVICE") != name):
                    state[name] = "exited"
                if os.environ.get("FAKE_FAIL_COMPOSE_STOP") == "1":
                    save_state()
                    sys.stderr.write("arrêt partiel fictif\\n")
                    raise SystemExit(1)
        save_state()
    if rest[:1] == ["up"] and "postgres" in rest:
        if "--wait" in rest and os.environ.get("FAKE_POSTGRES_UNHEALTHY") == "1":
            sys.stderr.write("postgres healthcheck fictif en échec\\n")
            raise SystemExit(1)
        state["postgres"] = "running"
        save_state()
    if rest[:1] == ["start"]:
        if late_stop:
            event("start_requested", phase=json.loads(daemon_file.read_text())["phase"])
        if any(arg.startswith("--") for arg in rest[1:]):
            raise SystemExit("unknown flag: --wait (contrat Compose 2.40.3)")
        if os.environ.get("FAKE_FAIL_COMPOSE_START") == "1":
            sys.stderr.write("reprise fictive en échec\\n")
            raise SystemExit(1)
        time.sleep(float(os.environ.get("FAKE_START_DELAY", "0")))
        for name in rest[1:]:
            if name in state:
                result_state = os.environ.get("FAKE_START_STATE_AFTER", "running")
                if result_state == "absent":
                    state.pop(name)
                else:
                    state[name] = result_state
        save_state()
        if os.environ.get("FAKE_START_REPLACE_INTENT") == "1":
            intention = state_file.parent / "deploy/.opsys-backup-intention.json"
            altered = json.loads(intention.read_text())
            altered["nonce"] = "autre-intention-fictive"
            intention.write_text(json.dumps(altered))
        if "FAKE_START_HEALTH_DELAY" in os.environ or "FAKE_START_HEALTH_RESULT" in os.environ:
            state_file.with_suffix(".health").write_text(json.dumps({
                "targets": rest[1:],
                "until": time.monotonic() + float(os.environ.get("FAKE_START_HEALTH_DELAY", "0")),
                "after": os.environ.get("FAKE_START_HEALTH_RESULT", "healthy"),
            }))
    if rest[:1] == ["exec"] and "postgres" in rest and state["postgres"] != "running":
        sys.stderr.write("service postgres fictif arrêté\\n")
        raise SystemExit(1)
    if rest[:1] == ["config"]:
        model = json.loads(pathlib.Path(os.environ["FAKE_COMPOSE_MODEL"]).read_text(encoding="utf-8"))
        if not {"database", "litellm"}.intersection(profiles):
            model["volumes"].pop("postgres_data", None)
        if os.environ.get("FAKE_HIDE_LITELLM_CONFIG_WITHOUT_PROFILE") == "1" and "litellm" not in profiles:
            model["volumes"].pop("litellm_config", None)
        print(json.dumps(model))
    elif "pg_dump" in rest:
        sys.stdout.write("-- fictitious database dump\\n")
    elif "psql" in rest:
        sys.stdin.read()
elif args[:2] == ["volume", "inspect"]:
    mapping = json.loads(pathlib.Path(os.environ["FAKE_VOLUMES"]).read_text(encoding="utf-8"))
    name = args[-1]
    if name not in mapping:
        raise SystemExit(1)
    print(mapping[name])
elif args[:1] == ["run"]:
    mapping = json.loads(pathlib.Path(os.environ["FAKE_VOLUMES"]).read_text(encoding="utf-8"))
    mount_arg = args[args.index("-v") + 1]
    volume, target = mount_arg.split(":", 1)
    target = target.split(":", 1)[0]
    if volume not in mapping:
        raise SystemExit(1)
    mount = pathlib.Path(mapping[volume])
    if "-c" in args and any("tar -C /volume -czf - ." in arg for arg in args):
        pathlib.Path(os.environ["FAKE_ARCHIVE_MARKER"]).touch()
        if volume.endswith("_opsys_data") and os.environ.get("FAKE_SQLITE_CLOSED_MARKER"):
            closed = pathlib.Path(os.environ["FAKE_SQLITE_CLOSED_MARKER"])
            deadline = time.monotonic() + 3
            while not closed.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not closed.exists():
                raise SystemExit("écrivain SQLite fictif encore actif")
        time.sleep(float(os.environ.get("FAKE_ARCHIVE_DELAY", "0")))
        if os.environ.get("FAKE_FAIL_VOLUME_BACKUP") == volume:
            raise SystemExit("archivage fictif en échec")
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w:gz") as archive:
            for child in mount.iterdir():
                archive.add(child, arcname=f"./{child.name}")
    elif "-c" in args and any("tar -C /volume -xzf -" in arg for arg in args):
        if volume.endswith("_postgres_data"):
            state = json.loads(pathlib.Path(os.environ["FAKE_COMPOSE_STATE"]).read_text(encoding="utf-8"))
            if state.get("postgres") == "running":
                raise SystemExit("PGDATA fictif actif : restauration physique refusée avant suppression")
        if os.environ.get("FAKE_FAIL_VOLUME_RESTORE") == volume:
            raise SystemExit("injected QA volume restore failure")
        for child in mount.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        with tarfile.open(fileobj=sys.stdin.buffer, mode="r:gz") as archive:
            archive.extractall(mount, filter="data")
    else:
        raise SystemExit("run call not understood by fake docker")
elif args[:2] == ["volume", "create"]:
    print(args[-1])
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"),
        "FAKE_COMPOSE_MODEL": str(tmp_path / "compose-model.json"),
        "FAKE_COMPOSE_STATE": str(tmp_path / "compose-state.json"),
        "FAKE_ARCHIVE_MARKER": str(tmp_path / "archive-started"),
        "FAKE_VOLUMES": str(tmp_path / "volumes.json"),
    }
    return deploy, volumes_dir, env, tmp_path


def _run(script: Path, *args: str, env: dict[str, str], permissive_umask: bool = False):
    prepare = (lambda: os.umask(0)) if permissive_umask else None
    return subprocess.run(
        ["bash", str(script), *args], env=env, capture_output=True, text=True, check=False, preexec_fn=prepare
    )


def _recalculer_integrite_fixture(archive):
    """Fixture cohérente pour atteindre les gardes de ressources, distinctes du hash."""
    noms = ["MANIFEST.txt", *[
        ligne.removeprefix("archive=")
        for ligne in (archive / "MANIFEST.txt").read_text().splitlines() if ligne.startswith("archive=")
    ]]
    (archive / "INTEGRITE.json").write_text(json.dumps({
        "format": "opsys-backup-integrity/1",
        "fichiers": {nom: {"sha256": hashlib.sha256((archive / nom).read_bytes()).hexdigest(),
                          "octets": (archive / nom).stat().st_size} for nom in noms},
    }))


def _etat_volumes_fixture(volumes):
    return {str(p.relative_to(volumes)): p.read_bytes() for p in volumes.rglob("*") if p.is_file()}


def _refus_integrite_sans_effet(deploy, volumes, env, archive, *options):
    log = Path(env["FAKE_DOCKER_LOG"])
    appels = log.read_bytes()
    etat = Path(env["FAKE_COMPOSE_STATE"]).read_bytes()
    avant = _etat_volumes_fixture(volumes)
    result = subprocess.run(
        ["bash", str(deploy / "restore.sh"), "--from", str(archive), "--yes", *options],
        env=env, capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode != 0 and "intégrité" in result.stderr, result.stderr
    assert log.read_bytes() == appels
    assert Path(env["FAKE_COMPOSE_STATE"]).read_bytes() == etat
    assert _etat_volumes_fixture(volumes) == avant
    return result


def test_restore_conserve_faits_m10_et_outbox_core_sqlite_reelles(banc_docker, monkeypatch):
    """Scripts réels et bases réelles; orchestration Docker factice, aucune reprise de worker."""
    from m10_memoire import faits_candidats, registre

    from opsys import stockage

    deploy, volumes, env, tmp_path = banc_docker
    metier = volumes / f"{PROJET}_opsys_data" / "opsys.db"
    core = volumes / f"{PROJET}_openclaw_config" / "agents/m03-estimation/agent/openclaw-agent.sqlite"
    core.parent.mkdir(parents=True)
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{metier}")
    faits = [dict(cle="tc-" + "a" * 40, outil="m3_estimer_projet", resultat="ok", code=None)]
    stockage.liberer()
    try:
        revision = stockage.migrer()
        journal = registre.Registre(stockage.maillons("m10-memoire", "affaires"))
        resultat, verdict = faits_candidats.deposer_faits_candidats(
            "LEAD-RESTORE-FICTIF", "m03-estimation", faits, "2030-01-01T10:00:00Z", journal
        )
        assert verdict is None and resultat["ecrits"] == 1
        avant = journal.lire()
        assert journal.valider_chaine() == (True, "")
    finally:
        # Aucun handle du moteur métier n'est retenu pendant l'archivage/remplacement.
        stockage.liberer()

    payload = json.dumps({
        "affaire_id": "LEAD-RESTORE-FICTIF", "departement_source": "m03-estimation",
        "profil_id": "profil-restore-fictif", "revision": 7, "engine_id": "opsys", "faits": faits,
    }, sort_keys=True)
    with sqlite3.connect(core) as db:
        db.executescript((ROOT / "core/src/state/openclaw-agent-schema.sql").read_text())
        for etat, cle, nombre in (("pending", "b", 0), ("retry", "a", 1)):
            fait_lot = {**faits[0], "cle": "tc-" + cle * 40}
            lot_payload = json.dumps({**json.loads(payload), "faits": [fait_lot]}, sort_keys=True)
            lot_key = "postflight-" + hashlib.sha256(fait_lot["cle"].encode()).hexdigest()
            db.execute(
                "INSERT INTO opsys_postflight_outbox "
                "(lot_key, affaire_id, departement_source, profil_id, revision_admission, engine_id, "
                "payload_json, state, attempt_count, created_at, updated_at, next_attempt_at, "
                "last_attempt_at, last_error_code) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (lot_key, "LEAD-RESTORE-FICTIF", "m03-estimation", "profil-restore-fictif",
                 7, "opsys", lot_payload, etat, nombre, 1000, 1000, 2000,
                 1000 if nombre else None, "M10_ACK_INCONNU" if nombre else None),
            )
        attendu_core = db.execute("SELECT * FROM opsys_postflight_outbox ORDER BY lot_key").fetchall()

    sauvegarde = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)
    assert sauvegarde.returncode == 0, sauvegarde.stderr
    [archive] = list((tmp_path / "backups").iterdir())
    for logique, relatif in (("opsys_data", "opsys.db"),
                            ("openclaw_config", "agents/m03-estimation/agent/openclaw-agent.sqlite")):
        with tarfile.open(archive / f"volume-{logique}.tar.gz") as contenu:
            assert "./" + relatif in contenu.getnames()
    # Une restauration doit remettre les générations archivées, pas lire les bases restées en place.
    for base in (metier, core):
        base.unlink()
        for suffixe in ("-wal", "-shm"):
            Path(str(base) + suffixe).unlink(missing_ok=True)
        with sqlite3.connect(base) as db:
            db.execute("CREATE TABLE generation_remplacee (fictif INTEGER)")
            db.execute("INSERT INTO generation_remplacee VALUES (1)")

    restauration = _run(deploy / "restore.sh", "--from", str(archive), "--yes", env=env)
    assert restauration.returncode == 0, restauration.stderr
    for base in (metier, core):
        with sqlite3.connect(base) as db:
            assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            assert not db.execute(
                "SELECT name FROM sqlite_master WHERE name='generation_remplacee'"
            ).fetchall()
    with sqlite3.connect(core) as db:
        assert db.execute("SELECT * FROM opsys_postflight_outbox ORDER BY lot_key").fetchall() == attendu_core
    try:
        assert stockage.revision_courante() == revision
        journal = registre.Registre(stockage.maillons("m10-memoire", "affaires"))
        assert journal.lire() == avant
        assert journal.valider_chaine() == (True, "")
        resultat, verdict = faits_candidats.deposer_faits_candidats(
            "LEAD-RESTORE-FICTIF", "m03-estimation", faits, "2030-01-02T10:00:00Z", journal
        )
        assert verdict is None and resultat["ecrits"] == 0 and resultat["deja_deposes"] == 1
        assert journal.lire() == avant
    finally:
        stockage.liberer()


@pytest.mark.parametrize("format_historique", [False, True])
def test_backup_then_restore_roundtrips_five_effective_volumes(banc_docker, format_historique):
    deploy, volumes_dir, env, tmp_path = banc_docker
    backup_dir = tmp_path / "backups"

    sauvegarde = _run(deploy / "backup.sh", "--out", str(backup_dir), env=env)

    assert sauvegarde.returncode == 0, sauvegarde.stderr
    [archive] = [p for p in backup_dir.iterdir() if p.is_dir()]
    attendus = {f"volume-{logical}.tar.gz" for logical in LOGIQUES_FIXTURE}
    assert attendus <= {p.name for p in archive.iterdir()}
    manifeste = (archive / "MANIFEST.txt").read_text(encoding="utf-8")
    assert "format=opsys-backup/4" in manifeste and "mode=natif" in manifeste
    assert "required=postgres:" not in manifeste and "postgres-opsys.sql.gz" not in manifeste
    if format_historique:
        import gzip
        for database in ("opsys", "litellm"):
            with gzip.open(archive / f"postgres-{database}.sql.gz", "wb") as stream:
                stream.write(b"-- dump fictif\n")
        for logical in LOGIQUES:
            (archive / f"volume-{logical}.tar.gz").rename(
                archive / f"volume-{PROJET}_{logical}.tar.gz"
            )
        (archive / "MANIFEST.txt").write_text(
            "20300101T000000Z\nbases: opsys litellm\n"
            "volumes: opsys_data openclaw_config openclaw_auth_secrets litellm_config caddy_data\n",
            encoding="utf-8",
        )
        (archive / "INTEGRITE.json").unlink()
    for logical in LOGIQUES_FIXTURE:
        (volumes_dir / f"{PROJET}_{logical}" / "preuve.txt").write_text("ancienne-generation\n", encoding="utf-8")

    restauration = _run(deploy / "restore.sh", "--from", str(archive), "--yes",
                        "--autoriser-sans-empreintes", env=env)

    assert restauration.returncode == 0, restauration.stderr
    assert ("AVERTISSEMENT" in restauration.stderr) is format_historique
    assert "volume opsys_data restauré" in restauration.stdout
    for logical in LOGIQUES if format_historique else LOGIQUES_FIXTURE:
        fichier = archive / f"volume-{logical}.tar.gz"
        if format_historique:
            fichier = archive / f"volume-{PROJET}_{logical}.tar.gz"
        with tarfile.open(fichier, "r:gz") as tar:
            assert tar.extractfile("./preuve.txt").read() == f"donnee-{logical}-fictive\n".encode()
        assert (volumes_dir / f"{PROJET}_{logical}" / "preuve.txt").read_text(encoding="utf-8") == (
            f"donnee-{logical}-fictive\n"
        )


def test_backup_force_permissions_privees_meme_sous_umask_permissif(banc_docker):
    deploy, _, env, tmp_path = banc_docker
    backup_dir = tmp_path / "backups"

    result = _run(deploy / "backup.sh", "--out", str(backup_dir), env=env, permissive_umask=True)

    assert result.returncode == 0, result.stderr
    [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
    assert backup_dir.stat().st_mode & 0o777 == 0o700
    assert archive.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in archive.iterdir())


def test_backup_volume_manquant_est_non_zero(banc_docker):
    deploy, _, env, tmp_path = banc_docker
    mapping_path = Path(env["FAKE_VOLUMES"])
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    mapping.pop(f"{PROJET}_caddy_data")
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")

    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)

    assert result.returncode != 0
    assert "sauvegarde incomplète" in result.stderr


@pytest.mark.parametrize("panne", ["aucune", "archive", "stop", "stop-timeout", "stop-no-effect", "start", "timeout"])
def test_backup_quiescence_reprend_seulement_services_initialement_actifs(banc_docker, panne):
    deploy, _, env, tmp_path = banc_docker
    state_file = Path(env["FAKE_COMPOSE_STATE"])
    initial = json.loads(state_file.read_text())
    initial["caddy"] = "exited"
    state_file.write_text(json.dumps(initial))
    if panne == "archive":
        env["FAKE_FAIL_VOLUME_BACKUP"] = f"{PROJET}_opsys_data"
    elif panne == "stop":
        env["FAKE_FAIL_COMPOSE_STOP"] = "1"
    elif panne == "stop-timeout":
        env["FAKE_STOP_DELAY"] = "10"
        env["OPSYS_BACKUP_STOP_TIMEOUT_SECONDS"] = "1"
    elif panne == "stop-no-effect":
        env["FAKE_STOP_NO_EFFECT"] = "1"
    elif panne == "start":
        env["FAKE_FAIL_COMPOSE_START"] = "1"
    elif panne == "timeout":
        env["FAKE_START_DELAY"] = "10"
        env["OPSYS_BACKUP_START_TIMEOUT_SECONDS"] = "1"

    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)

    assert (result.returncode == 0) is (panne == "aucune")
    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    stops = [call for call in calls if call[:1] == ["compose"] and "stop" in call]
    starts = [call for call in calls if call[:1] == ["compose"] and "start" in call]
    intention = deploy / ".opsys-backup-intention.json"
    if panne in ("stop", "stop-timeout"):
        assert len(stops) == 1 and not starts
        assert intention.is_file() and "inconnu" in result.stderr
        assert not list((tmp_path / "backups").glob("*/*"))
        assert not Path(env["FAKE_ARCHIVE_MARKER"]).exists()
        current = json.loads(state_file.read_text())
        assert current["caddy"] == current["litellm"] == "exited"
        assert current["postgres"] == initial["postgres"]
        if panne == "stop-timeout":
            assert current == initial
        else:
            assert current["opsys"] == "exited"
        return
    assert len(stops) == len(starts) == 1
    assert not any(arg.startswith("--") for arg in starts[0][starts[0].index("start") + 1:])
    assert "opsys" in stops[0] and "openclaw-gateway" in stops[0] and "postgres" in stops[0]
    assert "caddy" not in starts[0] and "litellm" not in starts[0]
    if panne in ("start", "timeout"):
        assert "PREUVE :" not in result.stdout
        assert "reprise" in result.stderr
        assert list((tmp_path / "backups").glob("*/MANIFEST.txt"))
        assert intention.is_file()
        before = (Path(env["FAKE_DOCKER_LOG"]).read_bytes(), state_file.read_bytes(), intention.read_bytes())
        retry = _run(deploy / "backup.sh", "--out", str(tmp_path / "autre-sortie"), env=env)
        assert retry.returncode != 0 and "intention" in retry.stderr
        assert (Path(env["FAKE_DOCKER_LOG"]).read_bytes(), state_file.read_bytes(), intention.read_bytes()) == before
    else:
        assert json.loads(state_file.read_text()) == initial
        assert not intention.exists()


@pytest.mark.parametrize("etat", ["restarting", "paused", "dead"])
def test_backup_etat_transitoire_refuse_avant_stop_et_archive(banc_docker, etat):
    deploy, _, env, tmp_path = banc_docker
    state_file = Path(env["FAKE_COMPOSE_STATE"])
    state = json.loads(state_file.read_text())
    state["opsys"] = etat
    state_file.write_text(json.dumps(state))

    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)

    assert result.returncode != 0
    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert not any("stop" in call or "start" in call or call[:1] == ["run"] for call in calls)
    assert json.loads(state_file.read_text()) == state


def test_backup_signal_reprend_services_et_reste_non_zero(banc_docker):
    deploy, _, env, tmp_path = banc_docker
    state_file = Path(env["FAKE_COMPOSE_STATE"])
    initial = json.loads(state_file.read_text())
    env["FAKE_ARCHIVE_DELAY"] = "0.2"
    process = subprocess.Popen(
        ["bash", str(deploy / "backup.sh"), "--out", str(tmp_path / "backups")],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not Path(env["FAKE_ARCHIVE_MARKER"]).exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert Path(env["FAKE_ARCHIVE_MARKER"]).exists()
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 143, (stdout, stderr)
        assert json.loads(state_file.read_text()) == initial
        assert "PREUVE :" not in stdout
        calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
        assert any(call[:1] == ["compose"] and "stop" in call for call in calls)
        assert any(call[:1] == ["compose"] and "start" in call for call in calls)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def test_backup_sqlite_ecrivain_reel_arrete_puis_repris_par_orchestration_factice(banc_docker):
    deploy, volumes, env, tmp_path = banc_docker
    base = volumes / f"{PROJET}_opsys_data" / "opsys.db"
    ready, closed, resumed = (tmp_path / name for name in ("sqlite-ready", "sqlite-closed", "sqlite-resumed"))
    env["FAKE_SQLITE_CLOSED_MARKER"] = str(closed)
    writer = subprocess.Popen([os.sys.executable, "-c", """
import json, pathlib, sqlite3, sys, time
state, base, ready, closed, resumed = map(pathlib.Path, sys.argv[1:])
db = sqlite3.connect(base)
db.execute('PRAGMA journal_mode=WAL')
db.execute('CREATE TABLE transactions (id INTEGER PRIMARY KEY, fictif INTEGER NOT NULL)')
while json.loads(state.read_text())['opsys'] == 'running':
    db.execute('INSERT INTO transactions (fictif) VALUES (1)')
    db.commit()
    ready.touch()
    time.sleep(0.01)
db.close()
closed.touch()
while json.loads(state.read_text())['opsys'] != 'running':
    time.sleep(0.01)
db = sqlite3.connect(base)
db.execute('INSERT INTO transactions (fictif) VALUES (1)')
db.commit()
db.close()
resumed.touch()
""", env["FAKE_COMPOSE_STATE"], str(base), str(ready), str(closed), str(resumed)])
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)
        assert result.returncode == 0, result.stderr
        writer.wait(timeout=5)
        assert writer.returncode == 0 and closed.exists() and resumed.exists()
        [archive] = list((tmp_path / "backups").glob("*/volume-opsys_data.tar.gz"))
        snapshot = tmp_path / "snapshot.db"
        with tarfile.open(archive) as contents:
            snapshot.write_bytes(contents.extractfile("./opsys.db").read())
        with sqlite3.connect(snapshot) as db:
            assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            before = db.execute("SELECT COUNT(*) FROM transactions WHERE fictif=1").fetchone()[0]
            assert before >= 1
        with sqlite3.connect(base) as db:
            assert db.execute("SELECT COUNT(*) FROM transactions WHERE fictif=1").fetchone()[0] > before
    finally:
        if writer.poll() is None:
            writer.kill()
            writer.wait()


def test_backup_concurrent_refuse_meme_avec_autre_sortie(banc_docker):
    deploy, _, env, tmp_path = banc_docker
    env["FAKE_ARCHIVE_DELAY"] = "0.2"
    process = subprocess.Popen(
        ["bash", str(deploy / "backup.sh"), "--out", str(tmp_path / "premiere")],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not Path(env["FAKE_ARCHIVE_MARKER"]).exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert Path(env["FAKE_ARCHIVE_MARKER"]).exists()
        second = _run(deploy / "backup.sh", "--out", str(tmp_path / "seconde"), env=env)
        assert second.returncode != 0 and "autre sauvegarde" in second.stderr
        assert not (tmp_path / "seconde").exists()
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, (stdout, stderr)
        calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
        assert len([call for call in calls if call[:1] == ["compose"] and "stop" in call]) == 1
        assert len([call for call in calls if call[:1] == ["compose"] and "start" in call]) == 1
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def test_backup_reprise_cli_start_sans_options_non_supportees(banc_docker):
    deploy, _, env, tmp_path = banc_docker
    (deploy / ".env").write_text("OPSYS_MODE_FOURNISSEUR=natif\nOPSYS_DATABASE_URL=postgresql://opsys:fake@postgres/opsys\n")
    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(x) for x in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    [start] = [c for c in calls if c[:1] == ["compose"] and "start" in c]
    assert not any(x.startswith("--") for x in start[start.index("start") + 1:])
    assert "postgres" not in start and "litellm" not in start
    assert not any(c[:1] == ["compose"] and "up" in c for c in calls)


def test_backup_volumes_historiques_resolus_par_profils_sans_les_demarrer(banc_docker):
    deploy, _, env, tmp_path = banc_docker
    env["FAKE_HIDE_LITELLM_CONFIG_WITHOUT_PROFILE"] = "1"
    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)
    assert result.returncode == 0, result.stderr
    [archive] = list((tmp_path / "backups").glob("*/MANIFEST.txt"))
    manifest = archive.read_text()
    assert "optional=volume:postgres_data" in manifest and "optional=volume:litellm_config" in manifest
    calls = [json.loads(x) for x in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert any("config" in c and "database" in c for c in calls)
    assert any("config" in c and "litellm" in c for c in calls)
    assert not any(c[:1] == ["compose"] and "up" in c for c in calls)
    assert all("database" not in c and "--profile" not in c for c in calls if "stop" in c or "start" in c)


def test_restore_volumes_historiques_resolus_malgre_profils_inactifs(banc_docker):
    deploy, volumes, env, tmp_path = banc_docker
    env["FAKE_HIDE_LITELLM_CONFIG_WITHOUT_PROFILE"] = "1"
    archive = tmp_path / "archive-v3-fictive"
    archive.mkdir()
    declarations = ["format=opsys-backup/3", "mode=natif", "database=sqlite"]
    for logical in (*PERSISTANTS_NATIFS, "postgres_data", "litellm_config"):
        prefix = "required" if logical in PERSISTANTS_NATIFS else "optional"
        declarations += [f"{prefix}=volume:{logical}", f"archive=volume-{logical}.tar.gz"]
        with tarfile.open(archive / f"volume-{logical}.tar.gz", "w:gz") as contents:
            contents.add(volumes / f"{PROJET}_{logical}" / "preuve.txt", arcname="./preuve.txt")
        (volumes / f"{PROJET}_{logical}" / "preuve.txt").write_text("generation-modifiee-fictive\n")
    (archive / "MANIFEST.txt").write_text("\n".join(declarations) + "\n")

    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes",
                  "--autoriser-sans-empreintes", env=env)

    assert result.returncode == 0, result.stderr
    assert (volumes / f"{PROJET}_postgres_data" / "preuve.txt").read_text() == "donnee-postgres_data-fictive\n"
    assert (volumes / f"{PROJET}_litellm_config" / "preuve.txt").read_text() == "donnee-litellm_config-fictive\n"
    calls = [json.loads(x) for x in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert any("config" in c and "database" in c for c in calls)
    assert any("config" in c and "litellm" in c for c in calls)


@pytest.mark.parametrize("sante", ["starting-puis-healthy", "timeout", "timeout-avant-observation", "unhealthy"])
def test_backup_attente_sante_reprise_bornee_sans_recreation(banc_docker, sante):
    deploy, _, env, tmp_path = banc_docker
    state_file = Path(env["FAKE_COMPOSE_STATE"])
    initial = json.loads(state_file.read_text())
    initial["caddy"] = "exited"
    state_file.write_text(json.dumps(initial))
    env["FAKE_START_HEALTH_DELAY"] = (
        "0.4" if sante == "starting-puis-healthy" else "60" if sante.startswith("timeout") else "0"
    )
    env["FAKE_START_HEALTH_RESULT"] = "unhealthy" if sante == "unhealthy" else "healthy"
    env["OPSYS_BACKUP_START_TIMEOUT_SECONDS"] = "2" if sante == "starting-puis-healthy" else "1"

    if sante == "unhealthy":
        # Ce cas éprouve le refus de santé, pas la frontière de SECONDS à la seconde près.
        # Horloge fictive figée uniquement ici ; les cas de délai gardent l'horloge réelle.
        horloge = tmp_path / "horloge-sante-fictive.sh"
        horloge.write_text("unset SECONDS\nSECONDS=0\n", encoding="utf-8")
        env["BASH_ENV"] = str(horloge)

    if sante == "timeout-avant-observation":
        # Le start aboutit, puis le parent ne reprend son CPU qu'après la limite commune.
        # Le wrapper ne modifie pas le script réel ni ses gardes.
        timeout = Path(env["PATH"].split(os.pathsep)[0]) / "timeout"
        timeout.write_text(
            """#!/usr/bin/env python3
import subprocess, sys, time
args = sys.argv[1:]
result = subprocess.run(["/usr/bin/timeout", *args], check=False)
if "start" in args and result.returncode == 0:
    time.sleep(1.1)
raise SystemExit(result.returncode)
""",
            encoding="utf-8",
        )
        timeout.chmod(0o755)

    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)

    assert (result.returncode == 0) is (sante == "starting-puis-healthy"), result.stderr
    assert state_file.with_suffix(".health").exists()
    assert json.loads(state_file.read_text()) == initial
    calls = [json.loads(x) for x in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    starts = [i for i, c in enumerate(calls) if c[:1] == ["compose"] and "start" in c]
    assert len(starts) == 1 and "caddy" not in calls[starts[0]] and "litellm" not in calls[starts[0]]
    observations = [c for c in calls[starts[0] + 1:] if c[:1] == ["compose"] and "ps" in c]
    if sante == "timeout-avant-observation":
        assert observations == []
    elif not sante.startswith("timeout"):
        assert observations, result.stderr
    if sante.startswith("timeout"):
        assert any(message in result.stderr for message in (
            "reprise hors délai; archives conservées.",
            "reprise non vérifiable; archives conservées.",
        )), result.stderr

    assert not any(c[:1] == ["compose"] and "up" in c for c in calls)
    if sante != "starting-puis-healthy":
        assert "PREUVE :" not in result.stdout
        assert list((tmp_path / "backups").glob("*/MANIFEST.txt"))


def test_backup_budget_reprise_global_couvre_start_et_sante(banc_docker):
    deploy, _, env, tmp_path = banc_docker
    env["FAKE_START_DELAY"] = "1.1"
    env["FAKE_START_HEALTH_DELAY"] = "1.1"
    env["OPSYS_BACKUP_START_TIMEOUT_SECONDS"] = "2"

    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)

    assert result.returncode != 0
    assert "reprise hors délai" in result.stderr
    assert "PREUVE :" not in result.stdout
    assert Path(env["FAKE_COMPOSE_STATE"]).with_suffix(".health").exists()
    assert list((tmp_path / "backups").glob("*/MANIFEST.txt"))
    # Chaque phase isolée tient en deux secondes ; leur somme doit épuiser le budget commun.
    calls = [json.loads(x) for x in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert sum(c[:1] == ["compose"] and "start" in c for c in calls) == 1
    assert not any(c[:1] == ["compose"] and "up" in c for c in calls)


@pytest.mark.parametrize("etat", ["absent", "exited", "restarting"])
def test_backup_reprise_etat_absent_ou_ambigu_refuse(banc_docker, etat):
    deploy, _, env, tmp_path = banc_docker
    env["FAKE_START_STATE_AFTER"] = etat
    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)
    assert result.returncode != 0
    assert "PREUVE :" not in result.stdout
    assert list((tmp_path / "backups").glob("*/MANIFEST.txt"))
    calls = [json.loads(x) for x in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    [start] = [i for i, c in enumerate(calls) if c[:1] == ["compose"] and "start" in c]
    assert any(c[:1] == ["compose"] and "ps" in c for c in calls[start + 1:])
    assert not any(c[:1] == ["compose"] and "up" in c for c in calls)


def test_legacy_archive_mapping_uses_source_project_manifest(banc_docker):
    deploy, volumes_dir, env, tmp_path = banc_docker
    backup_dir = tmp_path / "backups"
    assert _run(deploy / "backup.sh", "--out", str(backup_dir), env=env).returncode == 0
    [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
    manifest = (archive / "MANIFEST.txt").read_text(encoding="utf-8")
    for logical in LOGIQUES:
        old_name = f"volume-{PROJET}_{logical}.tar.gz"
        (archive / f"volume-{logical}.tar.gz").rename(archive / old_name)
        manifest = manifest.replace(f"archive=volume-{logical}.tar.gz", f"archive={old_name}")
    (archive / "MANIFEST.txt").write_text(manifest, encoding="utf-8")
    _recalculer_integrite_fixture(archive)

    nouveau_projet = "autre-projet-client-fictif"
    model_path = Path(env["FAKE_COMPOSE_MODEL"])
    model = json.loads(model_path.read_text(encoding="utf-8"))
    nouveaux_volumes = {}
    mapping_path = Path(env["FAKE_VOLUMES"])
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    for logical in LOGIQUES_FIXTURE:
        physical = f"{nouveau_projet}_{logical}"
        mount = volumes_dir / physical
        mount.mkdir()
        (mount / "preuve.txt").write_text("ancienne-generation\n", encoding="utf-8")
        nouveaux_volumes[logical] = {"name": physical}
        mapping[physical] = str(mount)
    model.update(name=nouveau_projet, volumes=nouveaux_volumes)
    model_path.write_text(json.dumps(model), encoding="utf-8")
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")

    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes", env=env)

    assert result.returncode == 0, result.stderr
    for logical in LOGIQUES:
        assert (volumes_dir / f"{nouveau_projet}_{logical}" / "preuve.txt").read_text(encoding="utf-8") == (
            f"donnee-{logical}-fictive\n"
        )


def test_backup_litellm_declare_et_dump_seulement_les_bases_actives(banc_docker):
    deploy, _, env, tmp_path = banc_docker
    env_file = deploy / ".env"
    env_file.write_text(
        "OPSYS_MODE_FOURNISSEUR=litellm\nOPSYS_DATABASE_URL=postgresql://opsys:fake@postgres/opsys\n",
        encoding="utf-8",
    )
    backup_dir = tmp_path / "backups"

    result = _run(deploy / "backup.sh", "--out", str(backup_dir), env=env)

    assert result.returncode == 0, result.stderr
    [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
    manifest = (archive / "MANIFEST.txt").read_text(encoding="utf-8")
    assert "mode=litellm" in manifest
    assert "required=postgres:opsys" in manifest and "required=postgres:litellm" in manifest
    assert "required=volume:litellm_config" in manifest
    assert (archive / "postgres-opsys.sql.gz").is_file()
    assert (archive / "postgres-litellm.sql.gz").is_file()
    assert "volume:postgres_data" not in manifest
    assert not (archive / "volume-postgres_data.tar.gz").exists()
    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert all("--profile" in call and "litellm" in call for call in calls if call[:1] == ["compose"])


def test_backup_natif_postgres_dump_la_base_sans_archiver_le_cluster_actif(banc_docker):
    deploy, _, env, tmp_path = banc_docker
    (deploy / ".env").write_text(
        "OPSYS_MODE_FOURNISSEUR=natif\nOPSYS_DATABASE_URL=postgresql://opsys:fake@postgres/opsys\n",
        encoding="utf-8",
    )

    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)

    assert result.returncode == 0, result.stderr
    [archive] = [path for path in (tmp_path / "backups").iterdir() if path.is_dir()]
    manifest = (archive / "MANIFEST.txt").read_text(encoding="utf-8")
    assert "database=postgres" in manifest
    assert "required=postgres:opsys" in manifest
    assert (archive / "postgres-opsys.sql.gz").is_file()
    assert "postgres-litellm.sql.gz" not in manifest
    assert "optional=volume:postgres_data" not in manifest
    assert not (archive / "volume-postgres_data.tar.gz").exists()
    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert not any(call[:1] == ["compose"] and "stop" in call and "postgres" in call for call in calls)


@pytest.mark.parametrize("postgres_initial", ["running", "exited", "absent"])
def test_restore_v4_sqlite_confirme_arret_postgres_avant_volume_historique(banc_docker, postgres_initial):
    deploy, volumes_dir, env, tmp_path = banc_docker
    state_file = Path(env["FAKE_COMPOSE_STATE"])
    state = json.loads(state_file.read_text())
    if postgres_initial == "absent":
        state.pop("postgres")
    else:
        state["postgres"] = postgres_initial
    state_file.write_text(json.dumps(state))
    backup_dir = tmp_path / "backups"
    sauvegarde = _run(deploy / "backup.sh", "--out", str(backup_dir), env=env)
    assert sauvegarde.returncode == 0, sauvegarde.stderr
    [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
    assert "optional=volume:postgres_data\n" in (archive / "MANIFEST.txt").read_text()
    pgdata = volumes_dir / f"{PROJET}_postgres_data" / "preuve.txt"
    pgdata.write_text("ancienne-generation-pgdata-fictive\n")
    Path(env["FAKE_DOCKER_LOG"]).write_text("")

    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes", env=env)

    assert result.returncode == 0, result.stderr
    assert pgdata.read_text() == "donnee-postgres_data-fictive\n"
    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    stops = [i for i, call in enumerate(calls) if call[:1] == ["compose"] and "stop" in call]
    observations = [i for i, call in enumerate(calls) if call[:1] == ["compose"] and "ps" in call]
    physical = [i for i, call in enumerate(calls)
                if call[:1] == ["run"] and f"{PROJET}_postgres_data:/volume" in call]
    assert len(stops) == len(observations) == len(physical) == 1
    assert "postgres" in calls[stops[0]] and stops[0] < observations[0] < physical[0]
    assert not any(call[:1] == ["compose"] and "up" in call for call in calls[:physical[0]])
    assert not any("psql" in call for call in calls)


@pytest.mark.parametrize("panne", ["stop-no-effect", "observation-ambigue"])
def test_restore_v4_pgdata_arret_non_confirme_refuse_avant_toute_ecriture(banc_docker, panne):
    deploy, volumes_dir, env, tmp_path = banc_docker
    backup_dir = tmp_path / "backups"
    sauvegarde = _run(deploy / "backup.sh", "--out", str(backup_dir), env=env)
    assert sauvegarde.returncode == 0, sauvegarde.stderr
    [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
    for logical in LOGIQUES_FIXTURE:
        (volumes_dir / f"{PROJET}_{logical}" / "preuve.txt").write_text("ancienne-generation-fictive\n")
    if panne == "stop-no-effect":
        env["FAKE_STOP_NO_EFFECT_SERVICE"] = "postgres"
    else:
        env["FAKE_COMPOSE_PS_DUPLICATE_POSTGRES"] = "1"
    Path(env["FAKE_DOCKER_LOG"]).write_text("")

    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes", env=env)

    assert result.returncode != 0
    assert "arrêt de PostgreSQL non confirmé" in result.stderr
    assert "PREUVE :" not in result.stdout
    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert any(call[:1] == ["compose"] and "stop" in call and "postgres" in call for call in calls)
    assert not any(call[:1] == ["run"] or call[:2] == ["volume", "create"] for call in calls)
    assert not any("psql" in call or (call[:1] == ["compose"] and "up" in call) for call in calls)
    for logical in LOGIQUES_FIXTURE:
        assert (volumes_dir / f"{PROJET}_{logical}" / "preuve.txt").read_text() == "ancienne-generation-fictive\n"


@pytest.mark.parametrize("mode", ["natif", "litellm"])
def test_restore_v4_postgres_logique_sans_archive_physique_du_cluster(banc_docker, mode):
    deploy, _, env, tmp_path = banc_docker
    (deploy / ".env").write_text(
        f"OPSYS_MODE_FOURNISSEUR={mode}\nOPSYS_DATABASE_URL=postgresql://opsys:fake@postgres/opsys\n",
        encoding="utf-8",
    )
    backup_dir = tmp_path / "backups"
    sauvegarde = _run(deploy / "backup.sh", "--out", str(backup_dir), env=env)
    assert sauvegarde.returncode == 0, sauvegarde.stderr
    [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
    manifest = (archive / "MANIFEST.txt").read_text()
    assert "required=postgres:opsys\n" in manifest
    assert "volume:postgres_data" not in manifest
    assert not (archive / "volume-postgres_data.tar.gz").exists()
    Path(env["FAKE_DOCKER_LOG"]).write_text("")

    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes", env=env)

    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    starts = [i for i, call in enumerate(calls)
              if call[:1] == ["compose"] and "up" in call and "postgres" in call and "--wait" in call]
    sql = [i for i, call in enumerate(calls) if "psql" in call]
    assert starts and sql and starts[0] < sql[0]
    assert result.stdout.count("base opsys restaurée") == 1
    assert result.stdout.count("base litellm restaurée") == (1 if mode == "litellm" else 0)
    assert not any(call[:1] == ["run"] and f"{PROJET}_postgres_data:/volume" in call for call in calls)


@pytest.mark.parametrize("mode", ["natif", "litellm"])
def test_restore_v4_refuse_melange_sql_logique_et_pgdata_physique_avant_arret(banc_docker, mode):
    deploy, volumes_dir, env, tmp_path = banc_docker
    (deploy / ".env").write_text(
        f"OPSYS_MODE_FOURNISSEUR={mode}\nOPSYS_DATABASE_URL=postgresql://opsys:fake@postgres/opsys\n",
        encoding="utf-8",
    )
    backup_dir = tmp_path / "backups"
    sauvegarde = _run(deploy / "backup.sh", "--out", str(backup_dir), env=env)
    assert sauvegarde.returncode == 0, sauvegarde.stderr
    [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
    with tarfile.open(archive / "volume-postgres_data.tar.gz", "w:gz") as contents:
        contents.add(volumes_dir / f"{PROJET}_postgres_data", arcname=".")
    with (archive / "MANIFEST.txt").open("a") as manifest:
        manifest.write("optional=volume:postgres_data\narchive=volume-postgres_data.tar.gz\n")
    _recalculer_integrite_fixture(archive)
    Path(env["FAKE_DOCKER_LOG"]).write_text("")

    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes", env=env)

    assert result.returncode != 0
    assert "restauration SQL logique et volume physique PostgreSQL incompatibles" in result.stderr
    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert not any(call[:1] == ["compose"] and "stop" in call for call in calls)
    assert not any(call[:1] == ["run"] or call[:2] == ["volume", "create"] for call in calls)
    assert not any("psql" in call for call in calls)


def test_restore_v4_refuse_changement_de_profil_avant_arret(banc_docker):
    deploy, _, env, tmp_path = banc_docker
    backup_dir = tmp_path / "backups"
    assert _run(deploy / "backup.sh", "--out", str(backup_dir), env=env).returncode == 0
    [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
    (deploy / ".env").write_text("OPSYS_MODE_FOURNISSEUR=litellm\n", encoding="utf-8")
    Path(env["FAKE_DOCKER_LOG"]).write_text("")

    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes", env=env)

    assert result.returncode != 0
    assert "profil source 'natif' différent" in result.stderr
    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert not any(call[:1] == ["compose"] and "stop" in call for call in calls)
    assert not any(call[:2] == ["volume", "create"] for call in calls)


def test_restore_v4_refuse_changement_backend_sqlite_postgres_avant_arret(banc_docker):
    deploy, _, env, tmp_path = banc_docker
    backup_dir = tmp_path / "backups"
    assert _run(deploy / "backup.sh", "--out", str(backup_dir), env=env).returncode == 0
    [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
    (deploy / ".env").write_text(
        "OPSYS_MODE_FOURNISSEUR=natif\nOPSYS_DATABASE_URL=postgresql://qa:fake@postgres/opsys\n",
        encoding="utf-8",
    )
    Path(env["FAKE_DOCKER_LOG"]).write_text("")

    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes", env=env)

    assert result.returncode != 0
    assert "backend source 'sqlite' différent du backend cible 'postgres'" in result.stderr
    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert not any(call[:1] == ["compose"] and "stop" in call for call in calls)
    assert not any(call[:2] == ["volume", "create"] for call in calls)


def test_restore_v4_refuse_manifeste_sans_volume_requis_avant_arret(banc_docker):
    deploy, _, env, tmp_path = banc_docker
    backup_dir = tmp_path / "backups"
    assert _run(deploy / "backup.sh", "--out", str(backup_dir), env=env).returncode == 0
    [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
    manifest = (archive / "MANIFEST.txt").read_text(encoding="utf-8")
    manifest = manifest.replace("required=volume:caddy_data\n", "")
    (archive / "MANIFEST.txt").write_text(manifest, encoding="utf-8")
    _recalculer_integrite_fixture(archive)
    Path(env["FAKE_DOCKER_LOG"]).write_text("")

    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes", env=env)

    assert result.returncode != 0
    assert "ressources requises v3/v4 incompatibles" in result.stderr
    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert not any(call[:1] == ["compose"] and "stop" in call for call in calls)
    assert not any(call[:2] == ["volume", "create"] for call in calls)


def test_restore_v4_refuse_archive_optionnelle_declaree_mais_absente(banc_docker):
    deploy, _, env, tmp_path = banc_docker
    backup_dir = tmp_path / "backups"
    assert _run(deploy / "backup.sh", "--out", str(backup_dir), env=env).returncode == 0
    [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
    (archive / "volume-litellm_config.tar.gz").unlink()
    Path(env["FAKE_DOCKER_LOG"]).write_text("")

    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes", env=env)

    assert result.returncode != 0
    assert "intégrité de sauvegarde refusée" in result.stderr
    assert "volume-litellm_config.tar.gz" in result.stderr
    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert not any(call[:1] == ["compose"] and "stop" in call for call in calls)
    assert not any(call[:2] == ["volume", "create"] for call in calls)


def test_restore_interrompue_signale_absence_de_rollback_et_services_arretes(banc_docker):
    deploy, volumes_dir, env, tmp_path = banc_docker
    backup_dir = tmp_path / "backups"
    assert _run(deploy / "backup.sh", "--out", str(backup_dir), env=env).returncode == 0
    [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
    for logical in LOGIQUES_FIXTURE:
        (volumes_dir / f"{PROJET}_{logical}" / "preuve.txt").write_text("ancienne-generation\n")
    env["FAKE_FAIL_VOLUME_RESTORE"] = f"{PROJET}_openclaw_config"

    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes", env=env)

    assert result.returncode != 0
    assert "rollback automatique absent" in result.stderr
    # La première ressource a été restaurée, la deuxième a échoué avant écriture; la pile reste arrêtée.
    assert (volumes_dir / f"{PROJET}_opsys_data" / "preuve.txt").read_text() == "donnee-opsys_data-fictive\n"
    assert (volumes_dir / f"{PROJET}_openclaw_config" / "preuve.txt").read_text() == "ancienne-generation\n"
    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert any(call[:1] == ["compose"] and "stop" in call for call in calls)
    assert not any(call[:1] == ["compose"] and "up" in call for call in calls)


@pytest.mark.parametrize("postgres_sain", [True, False])
def test_restore_format_v2_exige_encore_deux_dumps_et_cinq_volumes(banc_docker, postgres_sain):
    deploy, volumes_dir, env, tmp_path = banc_docker
    backup_dir = tmp_path / "backups"
    assert _run(deploy / "backup.sh", "--out", str(backup_dir), env=env).returncode == 0
    [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
    import gzip
    for database in ("opsys", "litellm"):
        with gzip.open(archive / f"postgres-{database}.sql.gz", "wb") as stream:
            stream.write(b"-- dump historique fictif\n")
    declarations = [
        "format=opsys-backup/2", "mode=legacy",
        "archive=postgres-opsys.sql.gz", "archive=postgres-litellm.sql.gz",
        *(f"archive=volume-{logical}.tar.gz" for logical in LOGIQUES),
        *(f"volume_name.{logical}={PROJET}_{logical}" for logical in LOGIQUES),
    ]
    (archive / "MANIFEST.txt").write_text("\n".join(declarations) + "\n", encoding="utf-8")
    (archive / "INTEGRITE.json").unlink()
    for logical in LOGIQUES:
        (volumes_dir / f"{PROJET}_{logical}" / "preuve.txt").write_text("nouvelle-generation\n", encoding="utf-8")
    if not postgres_sain:
        env["FAKE_POSTGRES_UNHEALTHY"] = "1"
    Path(env["FAKE_DOCKER_LOG"]).write_text("")

    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes",
                  "--autoriser-sans-empreintes", env=env)

    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    starts = [index for index, call in enumerate(calls)
              if call[:1] == ["compose"] and "up" in call and "postgres" in call and "--wait" in call]
    sql = [index for index, call in enumerate(calls) if call[:1] == ["compose"] and "psql" in call]
    if not postgres_sain:
        assert result.returncode != 0
        assert "postgres healthcheck fictif en échec" in result.stderr
        assert starts and not sql
        for logical in LOGIQUES:
            assert (volumes_dir / f"{PROJET}_{logical}" / "preuve.txt").read_text() == "nouvelle-generation\n"
        return

    assert result.returncode == 0, result.stderr
    assert starts and sql and starts[0] < sql[0]
    assert result.stdout.count("base opsys restaurée") == 1
    assert result.stdout.count("base litellm restaurée") == 1
    for logical in LOGIQUES:
        assert (volumes_dir / f"{PROJET}_{logical}" / "preuve.txt").read_text() == f"donnee-{logical}-fictive\n"


@pytest.mark.parametrize("missing", ["volume-opsys_data.tar.gz", "volume-caddy_data.tar.gz"])
def test_restore_archive_manquante_refuse_avant_toute_modification(banc_docker, missing):
    deploy, _, env, tmp_path = banc_docker
    backup_dir = tmp_path / "backups"
    assert _run(deploy / "backup.sh", "--out", str(backup_dir), env=env).returncode == 0
    [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
    (archive / missing).unlink()
    log_path = Path(env["FAKE_DOCKER_LOG"])
    log_path.write_text("", encoding="utf-8")

    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes", env=env)

    assert result.returncode != 0
    appels = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert not any(call[:1] == ["compose"] and "stop" in call for call in appels)
    assert not any(call[:2] == ["volume", "create"] for call in appels)
    assert not any("psql" in call for call in appels)


def _ignore_match(path: str, pattern: str) -> bool:
    pattern = pattern.strip().lstrip("/")
    if not pattern:
        return False
    candidates = [path, *[f"{parent}/" for parent in Path(path).parents if str(parent) != "."]]
    simple_pattern = pattern.removeprefix("**/")
    return any(fnmatch.fnmatchcase(candidate.rstrip("/"), pattern.rstrip("/")) or
               fnmatch.fnmatchcase(candidate.rstrip("/"), simple_pattern.rstrip("/")) for candidate in candidates)


def test_dockerignore_exclut_secrets_et_backups_du_contexte_et_garde_le_code():
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    chemins_sensibles = (
        ".env", "core/.env", ".forge/secrets/token", "deploy/backups/20300101/dump.sql.gz",
        "cache/backups/archive.tar.gz",
    )

    for chemin in chemins_sensibles:
        ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        ignore_etat = False
        for ligne in ignore:
            if ligne and not ligne.startswith("#") and _ignore_match(chemin, ligne.lstrip("!")):
                ignore_etat = not ligne.startswith("!")
        assert ignore_etat, chemin
    code_source = "src/opsys/exportation.py"
    assert not any(_ignore_match(code_source, ligne) for ligne in ignore if ligne and not ligne.startswith("!"))


@pytest.mark.skipif(os.environ.get("OPSYS_DOCKER_INTEGRATION") != "1", reason="intégration Docker explicite requise")
def test_restauration_reelle_volumes_docker_qa_jetables(tmp_path):
    docker = shutil.which("docker")
    assert docker
    version = subprocess.check_output([docker, "info", "--format", "{{.ServerVersion}}"], text=True).strip()
    assert version.startswith("28."), version

    token = uuid.uuid4().hex[:12]
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    shutil.copy2(ROOT / "deploy" / "backup.sh", deploy / "backup.sh")
    shutil.copy2(ROOT / "deploy" / "restore.sh", deploy / "restore.sh")
    noms = {logical: f"qa-{token}-{logical}" for logical in LOGIQUES_FIXTURE}
    (deploy / "docker-compose.yml").write_text(
        "name: qa-opsys-" + token + "\nvolumes:\n"
        + "".join(f"  {logical}:\n    name: {physical}\n" for logical, physical in noms.items())
        + "services:\n  qa:\n    image: busybox\n    volumes:\n"
        + "".join(f"      - {logical}:/mnt/{logical}\n" for logical in noms),
        encoding="utf-8",
    )
    (deploy / ".env").write_text(
        "OPSYS_MODE_FOURNISSEUR=natif\nPOSTGRES_OPSYS_PASSWORD=unused-fictif\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "docker"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import os, subprocess, sys\n"
        f"real = {docker!r}\n"
        "args = sys.argv[1:]\n"
        "if args[:1] == ['compose']:\n"
        "    if 'config' in args: raise SystemExit(subprocess.call([real, *args]))\n"
        "    if 'ps' in args: print('[]'); raise SystemExit(0)  # aucun écrivain applicatif dans ce banc QA\n"
        "    if 'pg_dump' in args: print('-- qa fictitious dump'); raise SystemExit(0)\n"
        "    if 'psql' in args: sys.stdin.read(); raise SystemExit(0)\n"
        "    if any(x in args for x in ('stop', 'up')): raise SystemExit(0)\n"
        "    raise SystemExit('compose call not expected in qa test')\n"
        "raise SystemExit(subprocess.call([real, *args]))\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    image = os.environ.get("OPSYS_BACKUP_IMAGE", "opsys:local")

    def run(*args):
        return subprocess.run(args, env=env, capture_output=True, text=True, check=False)

    created = []
    try:
        for logical in PERSISTANTS_NATIFS:
            name = noms[logical]
            assert name.startswith("qa-")
            result = run(docker, "volume", "create", name)
            assert result.returncode == 0, result.stderr
            created.append(name)
            result = run(
                docker, "run", "--rm", "--user", "0", "--entrypoint", "sh", "-v", f"{name}:/data",
                image, "-c", f"printf 'generation-{logical}\\n' > /data/proof.txt",
            )
            assert result.returncode == 0, result.stderr

        backup_dir = tmp_path / "backups"
        result = run("bash", str(deploy / "backup.sh"), "--out", str(backup_dir))
        assert result.returncode == 0, result.stderr
        [archive] = [path for path in backup_dir.iterdir() if path.is_dir()]
        for logical in PERSISTANTS_NATIFS:
            name = noms[logical]
            result = run(
                docker, "run", "--rm", "--user", "0", "--entrypoint", "sh", "-v", f"{name}:/data",
                image, "-c", "printf 'ancienne-generation\\n' > /data/proof.txt",
            )
            assert result.returncode == 0, result.stderr

        result = run("bash", str(deploy / "restore.sh"), "--from", str(archive), "--yes")
        assert result.returncode == 0, result.stderr
        for logical in PERSISTANTS_NATIFS:
            name = noms[logical]
            result = run(
                docker, "run", "--rm", "--user", "0", "--entrypoint", "cat", "-v", f"{name}:/data",
                image, "/data/proof.txt",
            )
            assert result.returncode == 0, result.stderr
            assert result.stdout == f"generation-{logical}\n"
    finally:
        for name in created:
            assert name.startswith(f"qa-{token}-")
            run(docker, "volume", "rm", name)


def test_backup_stop_inconnu_conserve_intention_et_bloque_nouveaux_effets(banc_docker):
    """Script réel; ACK124/arrêt tardif simulés, sans délai ni démon Docker réel."""
    deploy, _, env, tmp_path = banc_docker
    env.update({
        "OPSYS_DATABASE_URL": "postgresql://opsys:mot-de-passe-fictif@postgres:5432/opsys",
        "FAKE_STOP_ACCEPTED_NONTERMINAL": "1",
    })
    state_file = Path(env["FAKE_COMPOSE_STATE"])
    initial = json.loads(state_file.read_text())
    intention = deploy / ".opsys-backup-intention.json"
    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)
    assert result.returncode != 0
    calls = [json.loads(line) for line in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert not any(call[:1] == ["compose"] and "start" in call for call in calls), (
        "STOP accepté mais non terminal : aucune reprise automatique autorisée"
    )
    assert "intention" in result.stderr and "inconnu" in result.stderr
    assert "PREUVE :" not in result.stdout
    assert not list((tmp_path / "backups").glob("*/*"))
    assert not Path(env["FAKE_ARCHIVE_MARKER"]).exists()
    events = json.loads(state_file.with_suffix(".events").read_text())
    assert [e["event"] for e in events] == ["stop_accepted"]
    intent = json.loads(intention.read_text())
    assert events[0]["intention"] == intent and events[0]["mode"] == 0o600
    assert intention.stat().st_mode & 0o777 == 0o600
    assert set(intent["services"]) == {"opsys", "openclaw-gateway", "caddy"}
    assert intent["nonce"] and "mot-de-passe-fictif" not in intention.read_text()
    assert json.loads(state_file.read_text()) == initial
    # Une lecture factice réalise maintenant l'arrêt tardif. Elle n'est pas une
    # preuve que le protocole réel Docker est réconcilié, ni une autorisation de clear.
    subprocess.run(
        [str(tmp_path / "bin/docker"), "compose", "ps", "--all", "--format", "json"],
        env=env, check=True, capture_output=True, timeout=5,
    )
    terminal = json.loads(state_file.read_text())
    assert terminal == dict(initial, opsys="exited", **{"openclaw-gateway": "exited", "caddy": "exited"})
    before_retry = Path(env["FAKE_DOCKER_LOG"]).read_bytes()
    before_intent = intention.read_bytes()
    retry = _run(deploy / "backup.sh", "--out", str(tmp_path / "autre-sortie"), env=env)
    assert retry.returncode != 0 and "intention" in retry.stderr
    assert Path(env["FAKE_DOCKER_LOG"]).read_bytes() == before_retry
    assert intention.read_bytes() == before_intent
    assert json.loads(state_file.read_text()) == terminal
    assert not (tmp_path / "autre-sortie").exists()


@pytest.mark.parametrize("forme", ["invalide", "lien-pendant", "dossier"])
def test_backup_intention_preexistante_refuse_avant_docker(banc_docker, forme):
    deploy, _, env, tmp_path = banc_docker
    intention = deploy / ".opsys-backup-intention.json"
    if forme == "invalide":
        intention.write_text("inconnue-incomplete-fictive")
    elif forme == "lien-pendant":
        intention.symlink_to(tmp_path / "cible-absente-fictive")
    else:
        intention.mkdir()
    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "sortie"), env=env)
    assert result.returncode != 0 and "intention" in result.stderr
    assert not Path(env["FAKE_DOCKER_LOG"]).exists()
    assert not (tmp_path / "sortie").exists()
    assert intention.exists() or intention.is_symlink()


def test_backup_reprise_ne_supprime_pas_une_intention_remplacee(banc_docker):
    deploy, _, env, tmp_path = banc_docker
    env["FAKE_START_REPLACE_INTENT"] = "1"
    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)
    assert result.returncode != 0 and "intention non réconciliée" in result.stderr
    assert "PREUVE :" not in result.stdout
    assert len(list((tmp_path / "backups").glob("*/MANIFEST.txt"))) == 1
    intention = deploy / ".opsys-backup-intention.json"
    assert json.loads(intention.read_text())["nonce"] == "autre-intention-fictive"
    calls = Path(env["FAKE_DOCKER_LOG"]).read_bytes()
    before = intention.read_bytes()
    retry = _run(deploy / "backup.sh", "--out", str(tmp_path / "autre-sortie"), env=env)
    assert retry.returncode != 0 and "intention" in retry.stderr
    assert Path(env["FAKE_DOCKER_LOG"]).read_bytes() == calls
    assert intention.read_bytes() == before


def test_restore_refuse_archive_modifiee_mais_lisible_avant_arret_et_ecriture(banc_docker):
    deploy, volumes_dir, env, tmp_path = banc_docker
    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)
    assert result.returncode == 0, result.stderr
    [archive] = list((tmp_path / "backups").iterdir())
    cible = archive / "volume-opsys_data.tar.gz"
    empreinte_originale = hashlib.sha256(cible.read_bytes()).hexdigest()
    contenu_altere = tmp_path / "contenu-altere-fictif.txt"
    contenu_altere.write_text("contenu-altere-fictif\n", encoding="utf-8")
    with tarfile.open(cible, "w:gz") as tar:
        tar.add(contenu_altere, arcname="./preuve.txt")
    assert hashlib.sha256(cible.read_bytes()).hexdigest() != empreinte_originale
    with tarfile.open(cible, "r:gz") as tar:
        assert tar.extractfile("./preuve.txt").read() == b"contenu-altere-fictif\n"

    for fichier in volumes_dir.rglob("preuve.txt"):
        fichier.write_text("generation-courante-fictive\n", encoding="utf-8")
    avant = {str(p.relative_to(volumes_dir)): p.read_bytes() for p in volumes_dir.rglob("*") if p.is_file()}
    log = Path(env["FAKE_DOCKER_LOG"])
    appels_avant = len(log.read_text().splitlines())
    etat_avant = Path(env["FAKE_COMPOSE_STATE"]).read_bytes()

    restauration = _run(deploy / "restore.sh", "--from", str(archive), "--yes", env=env)

    assert restauration.returncode != 0, "une archive modifiee mais valide a ete restauree"
    appels = [json.loads(ligne) for ligne in log.read_text().splitlines()[appels_avant:]]
    assert not any("stop" in appel or "up" in appel or appel[:1] == ["run"] for appel in appels)
    assert Path(env["FAKE_COMPOSE_STATE"]).read_bytes() == etat_avant
    assert {str(p.relative_to(volumes_dir)): p.read_bytes() for p in volumes_dir.rglob("*") if p.is_file()} == avant


def test_backup_v4_empreintes_exactes_et_restauration_valide_meme_avec_option_legacy(banc_docker):
    deploy, volumes, env, tmp_path = banc_docker
    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)
    assert result.returncode == 0, result.stderr
    [archive] = list((tmp_path / "backups").iterdir())
    assert (archive / "MANIFEST.txt").read_text().splitlines()[0] == "format=opsys-backup/4"
    document = json.loads((archive / "INTEGRITE.json").read_text())
    assert document["format"] == "opsys-backup-integrity/1"
    assert set(document["fichiers"]) == {"MANIFEST.txt", *(p.name for p in archive.glob("*.tar.gz"))}
    for nom, preuve in document["fichiers"].items():
        brut = (archive / nom).read_bytes()
        assert preuve == {"sha256": hashlib.sha256(brut).hexdigest(), "octets": len(brut)}
    assert (archive / "INTEGRITE.json").stat().st_mode & 0o777 == 0o600
    for fichier in volumes.rglob("preuve.txt"):
        fichier.write_text("autre-generation-fictive\n")
    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes",
                  "--autoriser-sans-empreintes", env=env)
    assert result.returncode == 0, result.stderr
    assert "AVERTISSEMENT" not in result.stderr
    for logical in LOGIQUES_FIXTURE:
        assert (volumes / f"{PROJET}_{logical}" / "preuve.txt").read_text() == f"donnee-{logical}-fictive\n"


@pytest.mark.parametrize("nom", ["volume-opsys_data.tar.gz", "volume-litellm_config.tar.gz", "postgres-opsys.sql.gz"])
def test_restore_refuse_empreinte_changee_a_taille_identique(banc_docker, nom):
    import gzip

    deploy, volumes, env, tmp_path = banc_docker
    if nom.startswith("postgres-"):
        (deploy / ".env").write_text("OPSYS_MODE_FOURNISSEUR=natif\nOPSYS_DATABASE_URL=postgresql://qa:fake@postgres/opsys\n")
    result = _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env)
    assert result.returncode == 0, result.stderr
    [archive] = list((tmp_path / "backups").iterdir())
    cible = archive / nom
    brut = bytearray(cible.read_bytes())
    contenu = gzip.decompress(brut)
    brut[4] ^= 1  # MTIME gzip : octets différents, même taille, même contenu lisible.
    cible.write_bytes(brut)
    assert gzip.decompress(brut) == contenu
    result = _refus_integrite_sans_effet(deploy, volumes, env, archive)
    assert "empreinte discordante" in result.stderr


@pytest.mark.parametrize("entete", ["format=opsys-backup/3", "20300101T000000Z"])
def test_restore_refuse_declassement_v4_meme_avec_option_legacy(banc_docker, entete):
    deploy, volumes, env, tmp_path = banc_docker
    assert _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env).returncode == 0
    [archive] = list((tmp_path / "backups").iterdir())
    manifeste = archive / "MANIFEST.txt"
    lignes = manifeste.read_text().splitlines()
    lignes[0] = entete
    manifeste.write_text("\n".join(lignes) + "\n")
    cible = archive / "volume-opsys_data.tar.gz"
    brut = bytearray(cible.read_bytes())
    brut[4] ^= 1
    cible.write_bytes(brut)
    _refus_integrite_sans_effet(deploy, volumes, env, archive, "--autoriser-sans-empreintes")


@pytest.mark.parametrize("forme", [
    "absent", "lien", "lien-pendant", "dossier", "fifo", "duplique", "manquant",
    "extra", "traversee", "taille-bool", "sha-majuscules", "trop-grand",
])
def test_restore_refuse_integrite_absente_ou_invalide_sans_effet(banc_docker, forme):
    deploy, volumes, env, tmp_path = banc_docker
    assert _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env).returncode == 0
    [archive] = list((tmp_path / "backups").iterdir())
    cible = archive / "INTEGRITE.json"
    document = json.loads(cible.read_text())
    if forme in {"absent", "lien", "lien-pendant", "dossier", "fifo"}:
        sauvegarde = tmp_path / "integrite-originale-fictive.json"
        cible.rename(sauvegarde)
        if forme == "lien":
            cible.symlink_to(sauvegarde)
        elif forme == "lien-pendant":
            cible.symlink_to(tmp_path / "absent-fictif")
        elif forme == "dossier":
            cible.mkdir()
        elif forme == "fifo":
            os.mkfifo(cible)
    elif forme == "duplique":
        cible.write_text('{"format":"opsys-backup-integrity/1",' + json.dumps(document)[1:])
    elif forme == "trop-grand":
        cible.write_text(" " * (64 * 1024 + 1))
    else:
        if forme == "manquant":
            document["fichiers"].pop("volume-opsys_data.tar.gz")
        elif forme in {"extra", "traversee"}:
            document["fichiers"]["extra-fictif" if forme == "extra" else "../hors-archive-fictif"] = {
                "sha256": "0" * 64, "octets": 0,
            }
        elif forme == "taille-bool":
            document["fichiers"]["MANIFEST.txt"]["octets"] = True
        elif forme == "sha-majuscules":
            document["fichiers"]["MANIFEST.txt"]["sha256"] = "A" * 64
        cible.write_text(json.dumps(document))
    if forme in {"lien-pendant", "dossier", "fifo"}:
        manifeste = archive / "MANIFEST.txt"
        manifeste.write_text(manifeste.read_text().replace("format=opsys-backup/4", "format=opsys-backup/3", 1))
    _refus_integrite_sans_effet(deploy, volumes, env, archive, "--autoriser-sans-empreintes")


def test_restore_v3_historique_exige_option_explicite_sans_supprimer_capacite(banc_docker):
    deploy, volumes, env, tmp_path = banc_docker
    assert _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env).returncode == 0
    [archive] = list((tmp_path / "backups").iterdir())
    manifeste = archive / "MANIFEST.txt"
    manifeste.write_text(manifeste.read_text().replace("format=opsys-backup/4", "format=opsys-backup/3", 1))
    (archive / "INTEGRITE.json").unlink()  # Fixture d'une vraie ancienne sauvegarde sans sidecar.
    _refus_integrite_sans_effet(deploy, volumes, env, archive)
    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes",
                  "--autoriser-sans-empreintes", env=env)
    assert result.returncode == 0, result.stderr
    assert "archive historique sans empreintes" in result.stderr
    for logical in LOGIQUES_FIXTURE:
        assert (volumes / f"{PROJET}_{logical}" / "preuve.txt").read_text() == f"donnee-{logical}-fictive\n"


@pytest.mark.parametrize("nom", ["volume-opsys_data.tar.gz", "postgres-opsys.sql.gz"])
def test_restore_refuse_archive_illisible_meme_avec_empreinte_coherente(banc_docker, nom):
    deploy, volumes, env, tmp_path = banc_docker
    if nom.startswith("postgres-"):
        (deploy / ".env").write_text("OPSYS_MODE_FOURNISSEUR=natif\nOPSYS_DATABASE_URL=postgresql://qa:fake@postgres/opsys\n")
    assert _run(deploy / "backup.sh", "--out", str(tmp_path / "backups"), env=env).returncode == 0
    [archive] = list((tmp_path / "backups").iterdir())
    (archive / nom).write_bytes(b"gzip-corrompu-fictif")
    _recalculer_integrite_fixture(archive)  # Les empreintes passent : éprouver ensuite tar/gzip.
    avant = _etat_volumes_fixture(volumes)
    etat = Path(env["FAKE_COMPOSE_STATE"]).read_bytes()
    log = Path(env["FAKE_DOCKER_LOG"])
    debut = len(log.read_text().splitlines())

    result = _run(deploy / "restore.sh", "--from", str(archive), "--yes", env=env)

    assert result.returncode != 0 and "illisible" in result.stderr, result.stderr
    appels = [json.loads(ligne) for ligne in log.read_text().splitlines()[debut:]]
    assert not any("stop" in appel or "up" in appel or "psql" in appel
                   or appel[:1] == ["run"] or appel[:2] == ["volume", "create"] for appel in appels)
    assert _etat_volumes_fixture(volumes) == avant
    assert Path(env["FAKE_COMPOSE_STATE"]).read_bytes() == etat
