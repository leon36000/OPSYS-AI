"""Consolidation développement sous grant humain et capacité de service ; aucun outil d'affaires.

Le canon des grants, leases, rapports et checkpoints est un registre OPSYS append-only.
Les vues se reconstruisent intégralement : les caps d'analyse ne bornent pas cette reconstruction.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.engine import make_url

from opsys import memoire_consolidation as runtime
from opsys import stockage

from . import developpement as dev
from . import registre

REGISTRE = "consolidation_developpement"
PRINCIPAL = "service:m10-consolidation"
VERSION_ANALYSE = "m10-development-audit/v1"
MAX_CREDENTIAL_BYTES = 4096
LIMITES = {
    "max_events": dev.MAX_AUDIT_EVENTS,
    "max_relations": dev.MAX_AUDIT_RELATIONS,
    "max_sources": dev.MAX_AUDIT_SOURCES,
    "max_findings": dev.MAX_AUDIT_FINDINGS,
    "max_file_bytes": dev.MAX_FILE_BYTES,
    "max_total_bytes": dev.MAX_SCAN_BYTES,
    "timeout_seconds": 600,
    "max_report_bytes": dev.MAX_PAYLOAD_CHARS,
}


class AccesConsolidationRefuse(PermissionError):
    """Grant/capacité invalide ou révoqué : aucune sortie d'audit autorisée."""


class ConflitJob(RuntimeError):
    """Worker expiré, entrée changée ou autre worker courant : lot non validé."""


class BackendConsolidationNonPrisEnCharge(AccesConsolidationRefuse):
    """Les preuves de sérialisation de ce lot couvrent uniquement SQLite BEGIN IMMEDIATE."""


def _sqlite_seulement() -> None:
    courante = stockage.connexion_courante()
    url = courante.engine.url if courante is not None else make_url(stockage.url_base())
    dialecte = courante.dialect.name if courante is not None else url.get_backend_name()
    volatile = not url.database or url.database == ":memory:" or url.query.get("mode") == "memory"
    volatile |= bool(url.database and url.database.startswith("file:") and ":memory:" in url.database)
    if dialecte != "sqlite" or volatile:
        raise BackendConsolidationNonPrisEnCharge(
            "backend_non_pris_en_charge : jobs développement SQLite fichier uniquement"
        )


def _maintenant() -> dt.datetime:
    return runtime.horloge_serveur()


def _journal() -> registre.Registre:
    return registre.Registre(maillons=stockage.maillons("m10-memoire", REGISTRE))


def _lire() -> list[dict[str, Any]]:
    journal = _journal()
    valide, _ = journal.valider_chaine()
    if not valide:
        raise ConflitJob("chaîne canonique du job invalide")
    return journal.lire()


def _ajouter(paquet: dict[str, Any]) -> str:
    _sqlite_seulement()
    return _journal().ajouter(
        {
            "type_entree": "memoire_developpement",
            "horodatage": _maintenant().isoformat(),
            "paquet": paquet,
        }
    )


def _identifiant(job_id: str) -> None:
    if not isinstance(job_id, str) or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", job_id) is None:
        raise ValueError("identifiant de job invalide")


def _etat(job_id: str, maillons: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    state: dict[str, Any] = {"grant": None, "lease": None, "reports": [], "checkpoint": None}
    for maillon in _lire() if maillons is None else maillons:
        item = maillon["paquet"]
        if item["job_id"] != job_id:
            continue
        if item["kind"] == "grant":
            state["grant"] = item
        elif item["kind"] == "revocation" and state["grant"] is not None:
            state["grant"] = {**state["grant"], "active": False}
        elif item["kind"] == "lease":
            state["lease"] = item
        elif item["kind"] == "report":
            state["reports"].append(item)
        elif item["kind"] == "checkpoint":
            state["checkpoint"] = item
    return state


def _hash_capacite(capability: str) -> str:
    return hashlib.sha256((PRINCIPAL + "\0" + capability).encode()).hexdigest()


def _dossier_sans_symlink(path: Path) -> tuple[int, str]:
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise AccesConsolidationRefuse("credentials OS protégés indisponibles sur cette plateforme")
    absolute = Path(os.path.abspath(path))
    if ".." in path.parts:
        raise AccesConsolidationRefuse("chemin de credential invalide")
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in absolute.parts[1:-1]:
            suivant = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = suivant
        return descriptor, absolute.name
    except Exception:
        os.close(descriptor)
        raise


def _credential(job_id: str, path: str | Path) -> str:
    descriptor = None
    parent = None
    try:
        parent, name = _dossier_sans_symlink(Path(path))
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o777 != 0o600
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_size > MAX_CREDENTIAL_BYTES
        ):
            raise AccesConsolidationRefuse("credential régulier privé requis")
        raw = os.read(descriptor, MAX_CREDENTIAL_BYTES + 1)
        if len(raw) > MAX_CREDENTIAL_BYTES:
            raise AccesConsolidationRefuse("credential trop volumineux")
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or set(data) != {"job_id", "capability", "schema"}
            or data["schema"] != "opsys.m10-job-credential/v1"
            or data["job_id"] != job_id
            or not isinstance(data["capability"], str)
            or len(data["capability"]) != 43
        ):
            raise AccesConsolidationRefuse("credential de job invalide")
        return _hash_capacite(data["capability"])
    except (OSError, ValueError, TypeError) as exc:
        raise AccesConsolidationRefuse("credential de job inaccessible ou invalide") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent is not None:
            os.close(parent)


def autoriser(
    job_id: str,
    repository: str | Path,
    credential_file: str | Path,
    *,
    fuseau: str = "America/Toronto",
    premier_jour: str | None = None,
    limites: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Crée/renouvelle un grant par humain authentifié ; fichier neuf, jamais de secret rendu."""
    _sqlite_seulement()
    actor = dev._acteur()
    _identifiant(job_id)
    try:
        zone = ZoneInfo(fuseau)
    except (ZoneInfoNotFoundError, TypeError) as exc:
        raise ValueError("fuseau de job invalide") from exc
    debut = premier_jour or _maintenant().astimezone(zone).date().isoformat()
    if dt.date.fromisoformat(debut).isoformat() != debut:
        raise ValueError("premier jour invalide")
    caps = {**LIMITES, "max_findings": 100}
    if limites is not None and not isinstance(limites, dict):
        raise ValueError("les plafonds de grant doivent former un objet")
    for key, value in (limites or {}).items():
        if (
            key not in LIMITES
            or not isinstance(value, int)
            or isinstance(value, bool)
            or not 1 <= value <= LIMITES[key]
        ):
            raise ValueError("plafonds de grant invalides")
        caps[key] = value
    if caps["max_report_bytes"] < 2048:
        raise ValueError("plafond de rapport minimal : 2048 octets")
    root = Path(repository).expanduser().resolve()
    try:
        top = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL, text=True, timeout=10
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("dépôt Git local inaccessible") from exc
    if Path(top).resolve() != root:
        raise ValueError("le grant exige la racine Git complète")
    capability = runtime.creer_capacite()
    parent, name = _dossier_sans_symlink(Path(credential_file))
    descriptor = None
    created = False
    try:
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        created = True
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump({"schema": "opsys.m10-job-credential/v1", "job_id": job_id, "capability": capability}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        with stockage.transaction():
            dev._acteur()
            previous = _etat(job_id)["grant"]
            grant = {
                "kind": "grant",
                "job_id": job_id,
                "principal": PRINCIPAL,
                "domain": "development",
                "version": 1 if previous is None else previous["version"] + 1,
                "active": True,
                "capability_hash": _hash_capacite(capability),
                "repository": str(root),
                "fuseau": fuseau,
                "credential_file": os.path.abspath(credential_file),
                "premier_jour": debut,
                "limits": caps,
                "actor": actor[0],
                "actor_role": actor[1],
            }
            _ajouter(grant)
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            os.unlink(name, dir_fd=parent)
        raise
    finally:
        os.close(parent)
    return {k: v for k, v in grant.items() if k not in {"capability_hash", "kind"}}


def revoquer(job_id: str) -> dict[str, Any]:
    _sqlite_seulement()
    _identifiant(job_id)
    with stockage.transaction():
        actor = dev._acteur()
        if _etat(job_id)["grant"] is None:
            raise ValueError("job inconnu")
        _ajouter({"kind": "revocation", "job_id": job_id, "actor": actor[0], "actor_role": actor[1]})
    return {"job_id": job_id, "active": False}


def _grant_valide(state: dict[str, Any], capability_hash: str) -> dict[str, Any]:
    grant = state["grant"]
    if (
        grant is None
        or not grant["active"]
        or grant["domain"] != "development"
        or grant["principal"] != PRINCIPAL
        or not hmac.compare_digest(grant["capability_hash"], capability_hash)
    ):
        raise AccesConsolidationRefuse("autorisation de service absente ou révoquée")
    return grant


def _creneaux(grant: dict[str, Any], reports: list[dict[str, Any]], now: dt.datetime) -> list[str]:
    zone = ZoneInfo(grant["fuseau"])
    jour = dt.date.fromisoformat(grant["premier_jour"])
    fin = now.astimezone(zone).date()
    # Le backlog est compté sans reconstruire des millions d'objets datetime.
    if (fin - jour).days > 3660:
        raise ConflitJob("backlog dépasse dix ans : réduire le périmètre du grant")
    faits = {r["slot"] for r in reports if r["grant_version"] == grant["version"]}
    dus = []
    while jour <= fin:
        instant = dt.datetime(jour.year, jour.month, jour.day, 3, tzinfo=zone)
        if instant <= now and instant.isoformat() not in faits:
            dus.append(instant.isoformat())
        jour += dt.timedelta(days=1)
    return dus


def _statut(job_id: str, state: dict[str, Any]) -> dict[str, Any]:
    grant = state["grant"]
    if grant is None:
        raise ValueError("job inconnu")
    reports = state["reports"]
    dernier = reports[-1] if reports else None
    now = _maintenant()
    dus = _creneaux(grant, reports, now)
    zone = ZoneInfo(grant["fuseau"])
    jour = max(now.astimezone(zone).date(), dt.date.fromisoformat(grant["premier_jour"]))
    prochain = dt.datetime(jour.year, jour.month, jour.day, 3, tzinfo=zone)
    if prochain <= now:
        jour += dt.timedelta(days=1)
        prochain = dt.datetime(jour.year, jour.month, jour.day, 3, tzinfo=zone)
    resume = (
        None
        if dernier is None
        else {
            "report_id": dernier["report_id"],
            "slot": dernier["slot"],
            "status": dernier["report"]["audit"]["status"],
            "input_head": dernier["report"]["input_head"],
            "observed_at": dernier["report"]["observed_at"],
            "grant_version": dernier["grant_version"],
        }
    )
    return {
        "job_id": job_id,
        "principal": PRINCIPAL,
        "domain": "development",
        "active": grant["active"],
        "version": grant["version"],
        "repository": grant["repository"],
        "fuseau": grant["fuseau"],
        "credential_file": grant["credential_file"],
        "premier_jour": grant["premier_jour"],
        "limits": grant["limits"],
        "backlog": len(dus),
        "next_slot": dus[0] if dus else prochain.isoformat(),
        "last_report": resume,
        "lease": state["lease"],
    }


def lire_statut(job_id: str) -> dict[str, Any]:
    _identifiant(job_id)
    with stockage.transaction():
        dev._acteur()
        return _statut(job_id, _etat(job_id))


def lister_jobs() -> list[dict[str, Any]]:
    with stockage.transaction():
        dev._acteur()
        maillons = _lire()
        identifiants = sorted({m["paquet"]["job_id"] for m in maillons if m["paquet"]["kind"] == "grant"})
        return [_statut(job_id, _etat(job_id, maillons)) for job_id in identifiants]


def lire_rapport(job_id: str, report_id: str | None = None) -> dict[str, Any] | None:
    _identifiant(job_id)
    with stockage.transaction():
        dev._acteur()
        state = _etat(job_id)
        if state["grant"] is None:
            raise ValueError("job inconnu")
        reports = state["reports"]
        if report_id is None:
            return reports[-1] if reports else None
        return next((report for report in reports if report["report_id"] == report_id), None)


def _tete_dev() -> str | None:
    journal = registre.Registre(maillons=stockage.maillons("m10-memoire", dev.REGISTRE_DURABLE))
    valide, _ = journal.valider_chaine()
    if not valide:
        raise ConflitJob("chaîne canonique de développement invalide")
    return journal.tete()


def _produire_rapport(grant: dict[str, Any]) -> dict[str, Any]:
    caps = grant["limits"]
    snapshot = dev._snapshot_audit_developpement(
        max_events=caps["max_events"],
        max_relations=caps["max_relations"],
        max_sources=caps["max_sources"],
    )
    root = Path(grant["repository"])
    remaining = caps["max_total_bytes"]
    freshness = {}
    scopes = {}
    observed_hashes = {}
    for source in snapshot["sources"][: caps["max_sources"]]:
        result = "unknown"
        observed_hashes[source["source_ref"]] = None
        source_root = Path(source["repository"])
        try:
            prefix = source_root.relative_to(root)
            if ".." in source_root.parts:
                raise ValueError("racine hors périmètre")
        except ValueError:
            freshness[source["source_ref"]] = "unknown"
            scopes[source["source_ref"]] = "outside_grant"
            continue
        scopes[source["source_ref"]] = "inside_grant"
        try:
            relative = Path(source["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("chemin hors périmètre")
            allowance = min(caps["max_file_bytes"], remaining - 1)
            if allowance > 0:
                # Réservation pessimiste : un fichier trop grand ne rend pas son contenu.
                remaining -= allowance + 1
                raw = dev._lire_fichier_borne(root, prefix / relative, allowance)
                observed_hashes[source["source_ref"]] = hashlib.sha256(raw).hexdigest()
                result = "current" if observed_hashes[source["source_ref"]] == source["sha256"] else "stale"
        except dev._LimiteScanAtteinte:
            result = "too_large"
        except (OSError, ValueError):
            result = "missing"
        freshness[source["source_ref"]] = result
    snapshot["freshness"] = freshness
    audit = dev._analyser_audit_developpement(snapshot, repository=str(root), limite=caps["max_findings"])
    if "unknown" in freshness.values():
        audit["status"] = "partial"
        audit["truncated"] = True
        audit["freshness"]["status"] = "partial"
        audit["freshness"]["sources_checked"] = sum(value != "unknown" for value in freshness.values())
        audit["freshness"]["sources_unchecked_by_cap"] = max(0, snapshot["source_count"] - len(freshness)) + sum(
            value == "unknown" and scopes[ref] == "inside_grant" for ref, value in freshness.items()
        )
    audit["freshness"]["sources_out_of_scope"] = sum(scope == "outside_grant" for scope in scopes.values())
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True, timeout=10
        ).strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
        audit["status"] = "partial"
    modules: dict[str, list[dict[str, Any]]] = {}
    for source in snapshot["sources"][: caps["max_sources"]]:
        modules.setdefault(source["module"], []).append(
            {
                "source_ref": source["source_ref"],
                "event_id": source["event_id"],
                "path": source["path"],
                "indexed_sha256": source["sha256"],
                "observed_sha256": observed_hashes[source["source_ref"]],
                "freshness": freshness[source["source_ref"]],
                "scope": scopes[source["source_ref"]],
            }
        )
    report = {
        "domain": "development",
        "analyzer_version": VERSION_ANALYSE,
        "input_head": snapshot["head"],
        "observed_at": _maintenant().isoformat(),
        "commit": commit,
        "limits": caps,
        "audit": audit,
        "self_model": {
            "identity": "OPSYS-AI/M10 développement",
            "completion": "not_evaluated",
            "modules": [
                {"module": module, "state": "sources_indexed", "proofs": refs}
                for module, refs in sorted(modules.items())
            ],
            "mission": {
                "state": "unknown",
                "source_refs": [],
                "reason": "aucune auto-description validée par cette analyse",
            },
            "tools_and_permissions": {"state": "unknown", "reason": "ce job n'évalue pas les permissions métier"},
            "limits": [
                "reconstruction complète du canon",
                "analyse partielle si plafonds atteints",
                "isolation OS C01 non démontrée",
            ],
        },
        "coverage": {
            "events_total": snapshot["event_count"],
            "relations_total": snapshot["relation_count"],
            "sources_total": snapshot["source_count"],
        },
    }
    report, _ = dev._nettoyer(report)
    # Une grande liste de constats n'autorise ni dépassement du canon ni silence sur les omissions.
    report["audit"]["findings_omitted_by_report_cap"] = 0
    while len(dev._json(report).encode()) > caps["max_report_bytes"] and report["audit"]["findings"]:
        report["audit"]["findings"].pop()
        report["audit"]["findings_omitted_by_report_cap"] += 1
        report["audit"]["status"] = "partial"
        report["audit"]["truncated"] = True
    if len(dev._json(report).encode()) > caps["max_report_bytes"]:
        raise ConflitJob("rapport dépasse le plafond canonique autorisé")
    return report


def executer(job_id: str, credential_file: str | Path) -> dict[str, Any]:
    """Un créneau dû par appel ; autorité et lease revérifiés atomiquement avant le rapport."""
    _sqlite_seulement()
    _identifiant(job_id)
    capability_hash = _credential(job_id, credential_file)
    with stockage.transaction():
        state = _etat(job_id)
        grant = _grant_valide(state, capability_hash)
        head = _tete_dev()
        reports = [r for r in state["reports"] if r["grant_version"] == grant["version"]]
        due = _creneaux(grant, reports, _maintenant())
        latest = reports[-1] if reports else None
        if not due:
            if latest is None:
                return {
                    "job_id": job_id,
                    "status": "not_due",
                    "report_id": None,
                    "slot": None,
                    "backlog": 0,
                    "replayed": False,
                }
            if latest["report"]["input_head"] == head:
                return {
                    "job_id": job_id,
                    "status": "replayed",
                    "report_id": latest["report_id"],
                    "slot": latest["slot"],
                    "backlog": 0,
                    "replayed": True,
                }
        slot = due[0] if due else latest["slot"]
        lease = state["lease"]
        if (
            lease is not None
            and not lease.get("finished", False)
            and dt.datetime.fromisoformat(lease["expires_at"]) > _maintenant()
        ):
            raise ConflitJob("job déjà pris par un worker vivant")
        epoch = 1 if lease is None else lease["epoch"] + 1
        run_key = dev._hash(dev._json([job_id, grant["version"], slot, head, VERSION_ANALYSE]))
        lease = {
            "kind": "lease",
            "job_id": job_id,
            "epoch": epoch,
            "run_key": run_key,
            "expires_at": (_maintenant() + dt.timedelta(seconds=grant["limits"]["timeout_seconds"])).isoformat(),
            "finished": False,
        }
        _ajouter(lease)
    report = _produire_rapport(grant)
    with stockage.transaction():
        courant = _etat(job_id)
        actuel = _grant_valide(courant, capability_hash)
        if actuel["version"] != grant["version"]:
            raise AccesConsolidationRefuse("grant renouvelé pendant le travail")
        actif = courant["lease"]
        if (
            actif is None
            or actif["epoch"] != epoch
            or actif["run_key"] != run_key
            or actif.get("finished")
            or dt.datetime.fromisoformat(actif["expires_at"]) <= _maintenant()
        ):
            raise ConflitJob("worker expiré ou remplacé")
        if _tete_dev() != head or report["input_head"] != head:
            raise ConflitJob("sources modifiées pendant le travail : lot à reprendre")
        entry = {
            "kind": "report",
            "job_id": job_id,
            "grant_version": grant["version"],
            "slot": slot,
            "report_id": run_key,
            "principal": PRINCIPAL,
            "report": report,
        }
        _ajouter(entry)
        _ajouter({"kind": "checkpoint", "job_id": job_id, "slot": slot, "report_id": run_key, "input_head": head})
        _ajouter({**lease, "finished": True})
    return {
        "job_id": job_id,
        "status": report["audit"]["status"],
        "report_id": run_key,
        "slot": slot,
        "backlog": max(0, len(due) - 1),
        "replayed": False,
    }
