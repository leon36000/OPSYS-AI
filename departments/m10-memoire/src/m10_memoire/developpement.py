"""Journal gouverné de mémoire de développement dans le stockage durable de l'instance.

Les objets sont append-only, sourcés et hash-chaînés dans le registre durable de l'instance.
Les dérivés de recherche sont reconstruits depuis ces maillons; un SQLite mémoire sert seulement
de vue de requête par opération. Le rappel reste lexical et relationnel, sans promesse exhaustif.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from opsys import contexte, etat, identite, stockage

from . import registre

DOMAINE = "development"
REGISTRE_DURABLE = "developpement"
MAX_SCAN_FILES = 500
MAX_FILE_BYTES = 256_000
MAX_SCAN_BYTES = 8_000_000
MAX_SNIPPET_CHARS = 3_000
MAX_PREFLIGHT_MUST_KNOW = 30
MAX_PREFLIGHT_CONTRADICTIONS = 30
MAX_PREFLIGHT_CONTRADICTION_EVIDENCE = 2
MAX_PREFLIGHT_LINEAGE_NODES = 1_000
MAX_PREFLIGHT_LINKS = 30
MAX_PROMPT_CHARS = 64_000
MAX_PAYLOAD_CHARS = 128_000
MAX_AUDIT_FINDINGS = 500
MAX_AUDIT_SOURCES = 500
MAX_AUDIT_EVENTS = 5_000
MAX_AUDIT_RELATIONS = 10_000
ROLES_AUTORISES = frozenset({"admin", "nathan_owner"})
EXTENSIONS_TEXTE = frozenset(
    {
        ".md",
        ".rst",
        ".txt",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".json",
        ".yaml",
        ".yml",
        ".sql",
        ".toml",
        ".sh",
        ".html",
        ".css",
    }
)
REPERTOIRES_INTERDITS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "backups",
        "backup",
        "archives",
        "archive",
        "data",
        "datasets",
        "uploads",
        "exports",
        "var",
        "tmp",
        "secrets",
        "private",
        "clients",
        "customers",
        "fixtures",
        "fixture",
        "testdata",
        "test-data",
        "leads",
        "contacts",
        "crm",
        "__pycache__",
        "dist",
        "build",
    }
)
STATUTS = frozenset(
    {
        "active",
        "draft",
        "verified",
        "stale",
        "superseded",
        "contradicted",
        "archived",
        "rejected",
        "sensitive",
        "requires_review",
    }
)

_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE = re.compile(r"(?<!\w)(?:\+?1[ .-]?)?\(?[2-9]\d{2}\)?[ .-][2-9]\d{2}[ .-]\d{4}(?!\w)")
_ASSIGNED_SECRET = re.compile(
    r"(?i)(\b[A-Z0-9_-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd|"
    r"secret|bearer|token|jeton|private[_-]?key)"
    r"\b\s*[:=]\s*)([\"']?)([^\s\"'`,;]+)"
)
_TOKEN_SECRET = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{15,})\b")
_BEARER_SECRET = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]{16,}")
_CLES_CHAMP_SENSIBLE = frozenset(
    {
        "password",
        "passwd",
        "apikey",
        "cleapi",
        "accesstoken",
        "refreshtoken",
        "clientsecret",
        "privatekey",
        "authorization",
        "secret",
        "secretref",
        "secretreference",
        "credentialref",
        "token",
        "bearer",
        "jeton",
    }
)
_STOP = frozenset(
    {
        "pour",
        "avec",
        "dans",
        "depuis",
        "apres",
        "avant",
        "sur",
        "sans",
        "entre",
        "et",
        "les",
        "des",
        "une",
        "aux",
        "this",
        "that",
        "from",
        "with",
        "the",
        "and",
        "for",
    }
)


class AccesDeveloppementRefuse(PermissionError):
    """Principal absent, inactif ou sans rôle humain autorisé."""


class ConflitIdempotence(ValueError):
    """Une opération identifiée a été rejouée avec un contenu différent."""


class SourceDeveloppementRefusee(ValueError):
    """Une source est hors du périmètre textuel autorisé."""


class _LimiteScanAtteinte(ValueError):
    """Le fichier dépasse la limite de lecture du scan."""


def _valider_horodatage(value: str) -> str:
    try:
        instant = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("horodatage ISO 8601 avec fuseau requis") from exc
    if instant.tzinfo is None:
        raise ValueError("horodatage ISO 8601 avec fuseau requis")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _nettoyer_texte(text: str) -> tuple[str, bool]:
    """Masque les secrets connus, coordonnées personnelles et téléphones avant persistance."""
    redacted = False

    def masque_secret(match: re.Match[str]) -> str:
        nonlocal redacted
        redacted = True
        return f"{match.group(1)}{match.group(2)}[REDACTED]"

    text = _ASSIGNED_SECRET.sub(masque_secret, text)
    text, count = _TOKEN_SECRET.subn("[REDACTED]", text)
    redacted |= count > 0
    text, count = _BEARER_SECRET.subn("Bearer [REDACTED]", text)
    redacted |= count > 0
    text, count = _EMAIL.subn("[EMAIL_REDACTED]", text)
    redacted |= count > 0
    text, count = _PHONE.subn("[PHONE_REDACTED]", text)
    redacted |= count > 0
    return text, redacted


def _nettoyer(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        return _nettoyer_texte(value)
    if isinstance(value, list):
        result = [_nettoyer(item) for item in value]
        return [item for item, _ in result], any(redacted for _, redacted in result)
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        redacted_any = False
        for key, item in value.items():
            safe_key = str(key)
            normalized_key = re.sub(r"[^a-z0-9]", "", safe_key.casefold())
            if normalized_key in _CLES_CHAMP_SENSIBLE:
                cleaned[safe_key] = "[REDACTED]"
                redacted_any = True
                continue
            cleaned_item, redacted = _nettoyer(item)
            cleaned[safe_key] = cleaned_item
            redacted_any |= redacted
        return cleaned, redacted_any
    if value is None or isinstance(value, (bool, int, float)):
        return value, False
    raise TypeError(f"valeur de mémoire non sérialisable : {type(value).__name__}")


def _acteur() -> tuple[str, str]:
    principal = contexte.identite_appelante()
    if principal is None or principal.role not in ROLES_AUTORISES:
        raise AccesDeveloppementRefuse("accès mémoire développement refusé")
    try:
        with etat.session() as cnx:
            personne = identite.personne_active(cnx, principal.personne)
    except Exception as exc:
        raise AccesDeveloppementRefuse("accès mémoire développement refusé") from exc
    if personne is None or principal.role not in personne.roles:
        raise AccesDeveloppementRefuse("accès mémoire développement refusé")
    return personne.identifiant, principal.role


def _charger_registre(cnx: sqlite3.Connection) -> tuple[set[str], set[str], set[str]]:
    journal = registre.Registre(maillons=stockage.maillons("m10-memoire", REGISTRE_DURABLE))
    valide, raison = journal.valider_chaine()
    if not valide:
        raise RuntimeError(f"registre durable de développement invalide: {raison}")
    for maillon in journal.lire():
        if maillon.get("type_entree") != "memoire_developpement":
            raise RuntimeError("type de maillon inattendu dans le registre de développement")
        paquet = maillon.get("paquet", {})
        for event in paquet.get("events", []):
            cnx.execute(
                "INSERT INTO events(event_id,event_type,entity_id,version,idempotency_key,payload_json,payload_hash,"
                "actor,actor_role,recorded_at,previous_hash,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event["event_id"],
                    event["event_type"],
                    event["entity_id"],
                    event["version"],
                    event["idempotency_key"],
                    event["payload_json"],
                    event["payload_hash"],
                    event["actor"],
                    event["actor_role"],
                    event["recorded_at"],
                    event["previous_hash"],
                    event["event_hash"],
                ),
            )
        for relation in paquet.get("relations", []):
            cnx.execute(
                "INSERT INTO relations(relation_id,from_event,to_ref,relation_type,created_at) VALUES(?,?,?,?,?)",
                tuple(relation[key] for key in ("relation_id", "from_event", "to_ref", "relation_type", "created_at")),
            )
        for source in paquet.get("sources", []):
            cnx.execute(
                "INSERT INTO sources(source_ref,repository,commit_id,path,sha256,module,excerpt,status,redacted,"
                "scanned_at,event_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                tuple(
                    source[key]
                    for key in (
                        "source_ref",
                        "repository",
                        "commit_id",
                        "path",
                        "sha256",
                        "module",
                        "excerpt",
                        "status",
                        "redacted",
                        "scanned_at",
                        "event_id",
                    )
                ),
            )
    return (
        {row[0] for row in cnx.execute("SELECT event_id FROM events")},
        {row[0] for row in cnx.execute("SELECT relation_id FROM relations")},
        {row[0] for row in cnx.execute("SELECT source_ref FROM sources")},
    )


def _connecter() -> tuple[sqlite3.Connection, tuple[set[str], set[str], set[str]]]:
    cnx = sqlite3.connect(":memory:", timeout=10, isolation_level=None)
    cnx.row_factory = sqlite3.Row
    cnx.execute("PRAGMA foreign_keys = ON")
    cnx.execute("PRAGMA busy_timeout = 10000")
    cnx.executescript(
        """
        CREATE TABLE events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, event_type TEXT NOT NULL,
            entity_id TEXT NOT NULL, version INTEGER NOT NULL, idempotency_key TEXT UNIQUE,
            payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, actor TEXT NOT NULL, actor_role TEXT NOT NULL,
            recorded_at TEXT NOT NULL, previous_hash TEXT, event_hash TEXT NOT NULL UNIQUE
        );
        CREATE INDEX ix_dev_events_entity ON events(entity_id, seq);
        CREATE INDEX ix_dev_events_type_module ON events(event_type, seq);
        CREATE TABLE relations (
            relation_id TEXT PRIMARY KEY, from_event TEXT NOT NULL REFERENCES events(event_id),
            to_ref TEXT NOT NULL, relation_type TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(from_event, to_ref, relation_type)
        );
        CREATE TABLE sources (
            source_ref TEXT PRIMARY KEY, repository TEXT NOT NULL, commit_id TEXT NOT NULL, path TEXT NOT NULL,
            sha256 TEXT NOT NULL, module TEXT NOT NULL, excerpt TEXT NOT NULL, status TEXT NOT NULL,
            redacted INTEGER NOT NULL, scanned_at TEXT NOT NULL, event_id TEXT NOT NULL REFERENCES events(event_id)
        );
        CREATE INDEX ix_dev_sources_module_path ON sources(module, path);
        """
    )
    baseline = _charger_registre(cnx)
    return cnx, baseline


@contextmanager
def _connexion():
    with stockage.transaction():
        cnx, baseline = _connecter()
        try:
            yield cnx
            if cnx.in_transaction:
                cnx.commit()
            event_ids, relation_ids, source_refs = baseline
            new_events = [
                dict(row)
                for row in cnx.execute("SELECT * FROM events ORDER BY seq")
                if row["event_id"] not in event_ids
            ]
            new_relations = [
                dict(row) for row in cnx.execute("SELECT * FROM relations") if row["relation_id"] not in relation_ids
            ]
            new_sources = [
                dict(row) for row in cnx.execute("SELECT * FROM sources") if row["source_ref"] not in source_refs
            ]
            if new_events or new_relations or new_sources:
                paquet = {"events": new_events, "relations": new_relations, "sources": new_sources}
                horodatage = new_events[-1]["recorded_at"]
                journal = registre.Registre(maillons=stockage.maillons("m10-memoire", REGISTRE_DURABLE))
                journal.ajouter({"type_entree": "memoire_developpement", "horodatage": horodatage, "paquet": paquet})
        except Exception:
            if cnx.in_transaction:
                cnx.rollback()
            raise
        finally:
            cnx.close()


def _event_dict(row: sqlite3.Row, *, replayed: bool = False) -> dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "type": row["event_type"],
        "entity_id": row["entity_id"],
        "version": row["version"],
        "payload": json.loads(row["payload_json"]),
        "content_hash": row["payload_hash"],
        "actor": row["actor"],
        "recorded_at": row["recorded_at"],
        "event_hash": row["event_hash"],
        "replayed": replayed,
    }


def _ajouter_evenement(
    cnx: sqlite3.Connection,
    *,
    event_type: str,
    entity_id: str,
    version: int,
    payload: dict[str, Any],
    actor: tuple[str, str],
    horodatage: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    payload_json = _json(payload)
    if len(payload_json) > MAX_PAYLOAD_CHARS:
        raise ValueError("charge mémoire trop volumineuse")
    payload_hash = _hash(payload_json)
    if idempotency_key is not None:
        existing = cnx.execute("SELECT * FROM events WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if existing is not None:
            if existing["payload_hash"] != payload_hash:
                raise ConflitIdempotence("même clé d'opération réutilisée avec un contenu différent")
            return _event_dict(existing, replayed=True)
    now = _valider_horodatage(horodatage)
    previous = cnx.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
    previous_hash = previous["event_hash"] if previous else None
    event_id = _hash(
        _json(
            {
                "domain": DOMAINE,
                "entity_id": entity_id,
                "version": version,
                "payload_hash": payload_hash,
                "actor": actor[0],
                "recorded_at": now,
                "previous_hash": previous_hash,
            }
        )
    )
    event_hash = _hash(
        _json(
            {
                "domain": DOMAINE,
                "event_id": event_id,
                "type": event_type,
                "entity_id": entity_id,
                "version": version,
                "payload_hash": payload_hash,
                "actor": actor[0],
                "recorded_at": now,
                "previous_hash": previous_hash,
            }
        )
    )
    cnx.execute(
        "INSERT INTO events(event_id,event_type,entity_id,version,idempotency_key,payload_json,payload_hash,"
        "actor,actor_role,recorded_at,previous_hash,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            event_id,
            event_type,
            entity_id,
            version,
            idempotency_key,
            payload_json,
            payload_hash,
            actor[0],
            actor[1],
            now,
            previous_hash,
            event_hash,
        ),
    )
    row = cnx.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
    return _event_dict(row)


def _dernier(cnx: sqlite3.Connection, entity_id: str) -> sqlite3.Row | None:
    return cnx.execute("SELECT * FROM events WHERE entity_id=? ORDER BY seq DESC LIMIT 1", (entity_id,)).fetchone()


def _relier(cnx: sqlite3.Connection, from_event: str, to_ref: str, relation_type: str, horodatage: str) -> None:
    safe_time = _valider_horodatage(horodatage)
    relation_id = _hash(_json([from_event, to_ref, relation_type]))
    cnx.execute(
        "INSERT OR IGNORE INTO relations(relation_id,from_event,to_ref,relation_type,created_at) VALUES(?,?,?,?,?)",
        (relation_id, from_event, to_ref, relation_type, safe_time),
    )


def _references_sures(values: list[str] | tuple[str, ...]) -> list[str]:
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise SourceDeveloppementRefusee("référence de source invalide")
        pathish = value.split("#", 1)[0].replace("\\", "/")
        parts = [part.lower() for part in pathish.split("/")]
        basename = parts[-1] if parts else ""
        if (
            Path(basename).name.startswith(".env")
            or Path(basename).suffix.lower() in {".db", ".sqlite", ".sqlite3", ".pem", ".key"}
            or any(part in REPERTOIRES_INTERDITS for part in parts)
        ):
            raise SourceDeveloppementRefusee("source hors périmètre de développement")
        result.append(value)
    return result


def enregistrer_prompt(
    prompt_id: str,
    texte: str,
    *,
    version: int,
    module: str,
    objectif: str,
    source_refs: list[str] | tuple[str, ...] = (),
    statut: str = "active",
    horodatage: str,
) -> dict[str, Any]:
    actor = _acteur()
    if not prompt_id or not module or not objectif or version < 1 or statut not in STATUTS:
        raise ValueError("identifiant, module, objectif, version et statut valides requis")
    if not isinstance(texte, str) or not texte.strip() or len(texte) > MAX_PROMPT_CHARS:
        raise ValueError("prompt exact requis (64 000 caractères au plus)")
    safe_refs = _references_sures(source_refs)
    content, redacted = _nettoyer_texte(texte)
    safe_objective, objective_redacted = _nettoyer_texte(objectif)
    redacted |= objective_redacted
    payload = {
        "prompt_id": prompt_id,
        "version": version,
        "module": module.upper(),
        "objectif": safe_objective,
        "content": content,
        "content_hash": _hash(content),
        "source_refs": safe_refs,
        "status": "sensitive" if redacted else statut,
        "redacted": redacted,
    }
    with _connexion() as cnx:
        cnx.execute("BEGIN IMMEDIATE")
        try:
            current = _dernier(cnx, f"prompt:{prompt_id}")
            if current and version <= current["version"]:
                if version == current["version"] and json.loads(current["payload_json"]) == payload:
                    cnx.commit()
                    return _event_dict(current, replayed=True)["payload"] | {"replayed": True}
                raise ConflitIdempotence("version de prompt déjà utilisée ou décroissante")
            event = _ajouter_evenement(
                cnx,
                event_type="prompt",
                entity_id=f"prompt:{prompt_id}",
                version=version,
                payload=payload,
                actor=actor,
                horodatage=horodatage,
            )
            for ref in safe_refs:
                _relier(cnx, event["event_id"], ref, "source", horodatage)
            if current:
                _relier(cnx, current["event_id"], event["event_id"], "superseded_by", horodatage)
            cnx.commit()
            return payload | {"event_id": event["event_id"], "replayed": False}
        except Exception:
            cnx.rollback()
            raise


def enregistrer_plan(
    plan_id: str,
    *,
    version: int,
    module: str,
    prompt_id: str,
    prompt_version: int,
    objectif: str,
    etapes: list[dict[str, Any]],
    fichiers: list[str],
    risques: list[str] = (),
    ecarts: list[str] = (),
    responsables: list[str] = (),
    statut: str = "active",
    horodatage: str,
) -> dict[str, Any]:
    actor = _acteur()
    if not plan_id or not module or version < 1 or prompt_version < 1 or statut not in STATUTS or not etapes:
        raise ValueError("plan, version, prompt, étapes et statut valides requis")
    safe_files = _references_sures(fichiers)
    clean, redacted = _nettoyer(
        {
            "objectif": objectif,
            "etapes": etapes,
            "risques": list(risques),
            "ecarts": list(ecarts),
            "responsables": list(responsables),
        }
    )
    payload = {
        "plan_id": plan_id,
        "version": version,
        "module": module.upper(),
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "objectif": clean["objectif"],
        "etapes": clean["etapes"],
        "fichiers": safe_files,
        "risques": clean["risques"],
        "ecarts": clean["ecarts"],
        "responsables": clean["responsables"],
        "status": "sensitive" if redacted else statut,
        "redacted": redacted,
    }
    with _connexion() as cnx:
        cnx.execute("BEGIN IMMEDIATE")
        try:
            prompt = cnx.execute(
                "SELECT event_id,payload_json FROM events WHERE entity_id=? AND version=?",
                (f"prompt:{prompt_id}", prompt_version),
            ).fetchone()
            if prompt is None:
                raise ValueError("le prompt source doit exister avant son plan")
            current = _dernier(cnx, f"plan:{plan_id}")
            if current and version <= current["version"]:
                if version == current["version"] and json.loads(current["payload_json"]) == payload:
                    cnx.commit()
                    return payload | {"event_id": current["event_id"], "replayed": True}
                raise ConflitIdempotence("version de plan déjà utilisée ou décroissante")
            event = _ajouter_evenement(
                cnx,
                event_type="plan",
                entity_id=f"plan:{plan_id}",
                version=version,
                payload=payload,
                actor=actor,
                horodatage=horodatage,
            )
            _relier(cnx, event["event_id"], prompt["event_id"], "prompt_for", horodatage)
            for ref in safe_files:
                _relier(cnx, event["event_id"], f"file:{ref}", "target_file", horodatage)
            if current:
                _relier(cnx, current["event_id"], event["event_id"], "superseded_by", horodatage)
            cnx.commit()
            return payload | {"event_id": event["event_id"], "replayed": False}
        except Exception:
            cnx.rollback()
            raise


def enregistrer_decision(
    decision_id: str,
    *,
    version: int,
    module: str,
    contexte_decision: str,
    options: list[str],
    raisons: list[str],
    consequences: list[str],
    autorite: str,
    source_refs: list[str],
    statut: str = "active",
    horodatage: str,
) -> dict[str, Any]:
    actor = _acteur()
    if not decision_id or version < 1 or not module or statut not in STATUTS or not raisons or not autorite:
        raise ValueError("décision, version, raison, autorité et statut valides requis")
    refs = _references_sures(source_refs)
    clean, redacted = _nettoyer(
        {"contexte": contexte_decision, "options": options, "raisons": raisons, "consequences": consequences}
    )
    payload = {
        "decision_id": decision_id,
        "version": version,
        "module": module.upper(),
        **clean,
        "autorite": _nettoyer_texte(autorite)[0],
        "source_refs": refs,
        "status": "sensitive" if redacted else statut,
        "redacted": redacted,
    }
    with _connexion() as cnx:
        cnx.execute("BEGIN IMMEDIATE")
        try:
            current = _dernier(cnx, f"decision:{decision_id}")
            if current and version <= current["version"]:
                if version == current["version"] and json.loads(current["payload_json"]) == payload:
                    cnx.commit()
                    return payload | {"event_id": current["event_id"], "replayed": True}
                raise ConflitIdempotence("version de décision déjà utilisée ou décroissante")
            event = _ajouter_evenement(
                cnx,
                event_type="decision",
                entity_id=f"decision:{decision_id}",
                version=version,
                payload=payload,
                actor=actor,
                horodatage=horodatage,
            )
            for ref in refs:
                _relier(cnx, event["event_id"], ref, "source", horodatage)
            if current:
                _relier(cnx, current["event_id"], event["event_id"], "superseded_by", horodatage)
            cnx.commit()
            return payload | {"event_id": event["event_id"], "replayed": False}
        except Exception:
            cnx.rollback()
            raise


def enregistrer_postflight(
    operation_id: str,
    *,
    module: str,
    plan_id: str,
    statut: str,
    resume: str,
    changements: list[dict[str, Any]],
    tests: list[dict[str, Any]],
    rapport_refs: list[str],
    claim_key: str | None = None,
    diagnostic: dict[str, Any] | None = None,
    version: int = 1,
    horodatage: str,
) -> dict[str, Any]:
    actor = _acteur()
    if not operation_id or not module or statut not in {"done", "partial", "failed", "blocked"} or version < 1:
        raise ValueError("identifiant, module, statut et version de postflight valides requis")
    refs = _references_sures(rapport_refs)
    changes, redacted_changes = _nettoyer(changements)
    test_results, redacted_tests = _nettoyer(tests)
    safe_changes = []
    for change in changes:
        if not isinstance(change, dict) or not isinstance(change.get("fichier"), str):
            raise ValueError("chaque changement doit nommer un fichier relatif")
        safe_changes.append(change | {"fichier": _references_sures([change["fichier"]])[0]})
    clean_summary, redacted_summary = _nettoyer_texte(resume)
    clean_diagnostic = None
    redacted_diagnostic = False
    if diagnostic is not None:
        diagnostic_cleaned, redacted_diagnostic = _nettoyer(diagnostic)
        fields = {
            "incident_id", "symptom", "cause", "cause_status", "prevention", "source_refs", "observed_at"
        }
        if not isinstance(diagnostic_cleaned, dict) or set(diagnostic_cleaned) != fields:
            raise ValueError("diagnostic invalide : champs exacts requis")
        incident_id = diagnostic_cleaned["incident_id"]
        if not isinstance(incident_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:_-]{0,127}", incident_id):
            raise ValueError("incident_id invalide")
        for field in ("symptom", "cause", "prevention"):
            value = diagnostic_cleaned[field]
            if not isinstance(value, str) or not value.strip() or len(value) > 2_000:
                raise ValueError(f"diagnostic.{field} invalide")
        cause_status = diagnostic_cleaned["cause_status"]
        if not isinstance(cause_status, str) or cause_status not in {
            "hypothesis", "supported", "confirmed", "disputed", "unknown"
        }:
            raise ValueError("diagnostic.cause_status invalide")
        source_refs = diagnostic_cleaned["source_refs"]
        if not isinstance(source_refs, list) or len(source_refs) > 50:
            raise ValueError("diagnostic.source_refs invalide")
        if cause_status != "unknown" and not source_refs:
            raise ValueError("source requise pour un diagnostic autre qu'inconnu")
        safe_diagnostic_refs = _references_sures(source_refs)
        observed_at = diagnostic_cleaned["observed_at"]
        if not isinstance(observed_at, str):
            raise ValueError("diagnostic.observed_at invalide")
        _valider_horodatage(observed_at)
        clean_diagnostic = diagnostic_cleaned | {"source_refs": safe_diagnostic_refs}
    payload = {
        "operation_id": operation_id,
        "module": module.upper(),
        "plan_id": plan_id,
        "status": statut,
        "summary": clean_summary,
        "changes": safe_changes,
        "tests": test_results,
        "report_refs": refs,
        "claim_key": claim_key,
        "version": version,
        "redacted": redacted_changes or redacted_tests or redacted_summary or redacted_diagnostic,
    }
    if clean_diagnostic is not None:
        payload["diagnostic"] = clean_diagnostic
    idempotency_key = f"{DOMAINE}:{operation_id}:{version}"
    with _connexion() as cnx:
        cnx.execute("BEGIN IMMEDIATE")
        try:
            event = _ajouter_evenement(
                cnx,
                event_type="postflight",
                entity_id=f"postflight:{operation_id}",
                version=version,
                payload=payload,
                actor=actor,
                horodatage=horodatage,
                idempotency_key=idempotency_key,
            )
            if event["replayed"]:
                cnx.commit()
                retour = payload | {"event_id": event["event_id"], "replayed": True}
                if clean_diagnostic is not None:
                    retour["diagnostic_assurance"] = "author_assertion_unverified"
                return retour
            current = cnx.execute(
                "SELECT * FROM events WHERE entity_id=? AND event_id<>? ORDER BY seq DESC LIMIT 1",
                (f"postflight:{operation_id}", event["event_id"]),
            ).fetchone()
            if current is not None and clean_diagnostic is not None:
                previous_payload = json.loads(current["payload_json"])
                previous_diagnostic = previous_payload.get("diagnostic")
                if (
                    isinstance(previous_diagnostic, dict)
                    and previous_diagnostic.get("incident_id") == clean_diagnostic["incident_id"]
                    and version > current["version"]
                ):
                    _relier(cnx, current["event_id"], event["event_id"], "superseded_by", horodatage)
            plan = _dernier(cnx, f"plan:{plan_id}")
            if plan:
                _relier(cnx, event["event_id"], plan["event_id"], "plan_for", horodatage)
                plan_payload = json.loads(plan["payload_json"])
                prompt = cnx.execute(
                    "SELECT event_id FROM events WHERE entity_id=? AND version=?",
                    (f"prompt:{plan_payload['prompt_id']}", plan_payload["prompt_version"]),
                ).fetchone()
                if prompt:
                    _relier(cnx, plan["event_id"], prompt["event_id"], "prompt_for", horodatage)
            for change in safe_changes:
                _relier(cnx, event["event_id"], f"file:{change['fichier']}", "changes", horodatage)
            for result in test_results:
                if isinstance(result, dict) and isinstance(result.get("source"), str):
                    for ref in _references_sures([result["source"]]):
                        _relier(cnx, event["event_id"], ref, "tests", horodatage)
            for ref in refs:
                _relier(cnx, event["event_id"], ref, "report", horodatage)
            cnx.commit()
            retour = payload | {"event_id": event["event_id"], "replayed": False}
            if clean_diagnostic is not None:
                retour["diagnostic_assurance"] = "author_assertion_unverified"
            return retour
        except Exception:
            cnx.rollback()
            raise


def _module_de(path: str) -> str:
    match = re.match(r"departments/(m\d{2})-[^/]+/", path)
    if match:
        return f"M{int(match.group(1)[1:])}"
    return "CORE" if path.startswith("core/") else "OPSYS"


def _chemin_interdit(path: str) -> bool:
    parts = [part.lower() for part in path.replace("\\", "/").split("/")]
    name = parts[-1] if parts else ""
    return (
        name.startswith(".env")
        or name.endswith((".bak", ".backup", ".old", ".sqlite", ".sqlite3", ".db", ".pem", ".key"))
        or any(part in REPERTOIRES_INTERDITS for part in parts)
    )


def _ouvrir_source_sans_symlink(repository: Path, relative: Path) -> int:
    """Ouvre un fichier relatif avec O_NOFOLLOW sur chaque composant quand dir_fd est disponible."""
    if relative.is_absolute() or not relative.parts or any(part in {".", ".."} for part in relative.parts):
        raise ValueError("chemin source invalide")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    if os.open in os.supports_dir_fd and directory and nofollow:
        directory_fd = os.open(repository, os.O_RDONLY | directory | nofollow)
        try:
            for part in relative.parts[:-1]:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = next_fd
            return os.open(
                relative.parts[-1],
                os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0),
                dir_fd=directory_fd,
            )
        finally:
            os.close(directory_fd)

    candidate = repository
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("source symbolique hors périmètre")
    return os.open(candidate, os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0))


def _lire_fichier_borne(repository: Path, relative: Path, limite: int) -> bytes:
    """Lit un fichier régulier sans lien, en consommant au plus `limite + 1` octets."""
    descriptor = _ouvrir_source_sans_symlink(repository, relative)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("source non régulière")
        if metadata.st_size > limite:
            raise _LimiteScanAtteinte("limite de taille du fichier")
        data = bytearray()
        while len(data) <= limite:
            restant = limite + 1 - len(data)
            chunk = os.read(descriptor, min(64_000, restant))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > limite:
                raise _LimiteScanAtteinte("limite de taille du fichier")
        return bytes(data)
    finally:
        os.close(descriptor)


def scanner_depot(
    repository: str | Path,
    *,
    max_files: int = MAX_SCAN_FILES,
    max_bytes: int = MAX_FILE_BYTES,
    max_total_bytes: int = MAX_SCAN_BYTES,
    horodatage: str,
) -> dict[str, Any]:
    """Indexe les fichiers texte suivis par Git sans les modifier; saute données, secrets et fichiers volumineux."""
    actor = _acteur()
    if (
        not 1 <= max_files <= MAX_SCAN_FILES
        or not 1 <= max_bytes <= MAX_FILE_BYTES
        or not 1 <= max_total_bytes <= MAX_SCAN_BYTES
    ):
        raise ValueError("bornes du scan au-delà des maximums autorisés")
    root = Path(repository).expanduser().resolve()
    try:
        top = Path(
            subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        ).resolve()
        commit = subprocess.check_output(
            ["git", "-C", str(top), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        tracked = subprocess.check_output(["git", "-C", str(top), "ls-files", "-z"], stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("le dépôt Git local n'est pas accessible") from exc
    try:
        root.relative_to(top)
    except ValueError as exc:
        raise ValueError("le chemin demandé doit rester dans son dépôt Git") from exc
    prefix = root.relative_to(top).as_posix()
    selected = []
    for raw in tracked.decode("utf-8", errors="strict").split("\0"):
        if not raw or (prefix != "." and raw != prefix and not raw.startswith(prefix + "/")):
            continue
        relative = Path(raw)
        path = relative.as_posix()
        if _chemin_interdit(path) or relative.suffix.lower() not in EXTENSIONS_TEXTE:
            continue
        selected.append((path, relative))
    selected.sort()
    stored: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    total = 0
    for path, relative in selected[:max_files]:
        limite = min(max_bytes, max_total_bytes - total)
        if limite <= 0:
            skipped.append({"path": path, "reason": "limite de taille totale du scan"})
            continue
        try:
            data = _lire_fichier_borne(top, relative, limite)
        except _LimiteScanAtteinte:
            skipped.append({"path": path, "reason": "limite de taille du fichier ou du scan total"})
            continue
        except (OSError, ValueError):
            skipped.append({"path": path, "reason": "absent, hors dépôt, symbolique ou non régulier"})
            continue
        if b"\x00" in data:
            skipped.append({"path": path, "reason": "fichier binaire ou limite de taille"})
            continue
        total += len(data)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            skipped.append({"path": path, "reason": "encodage non textuel"})
            continue
        excerpt, redacted = _nettoyer_texte(text[:MAX_SNIPPET_CHARS])
        sha = _hash_bytes(data)
        source_ref = f"git:{commit}:{path}@{sha}"
        payload = {
            "repository": str(top),
            "commit": commit,
            "path": path,
            "sha256": sha,
            "module": _module_de(path),
            "redacted": redacted,
        }
        with _connexion() as cnx:
            cnx.execute("BEGIN IMMEDIATE")
            try:
                event = _ajouter_evenement(
                    cnx,
                    event_type="source_snapshot",
                    entity_id=f"source:{source_ref}",
                    version=1,
                    payload=payload,
                    actor=actor,
                    horodatage=horodatage,
                    idempotency_key=f"snapshot:{source_ref}",
                )
                cnx.execute(
                    "INSERT OR IGNORE INTO sources(source_ref,repository,commit_id,path,sha256,module,excerpt,status,"
                    "redacted,scanned_at,event_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        source_ref,
                        str(top),
                        commit,
                        path,
                        sha,
                        payload["module"],
                        excerpt,
                        "redacted" if redacted else "active",
                        int(redacted),
                        horodatage,
                        event["event_id"],
                    ),
                )
                cnx.commit()
            except Exception:
                cnx.rollback()
                raise
        stored.append(
            {
                "source_ref": source_ref,
                "path": path,
                "sha256": sha,
                "module": payload["module"],
                "status": "redacted" if redacted else "active",
            }
        )
    if len(selected) > max_files:
        skipped.extend({"path": p, "reason": "limite de fichiers"} for p, _ in selected[max_files:])
    return {
        "status": "indexed" if stored else "unavailable",
        "repository": str(top),
        "commit": commit,
        "count": len(stored),
        "bytes": total,
        "sources": stored,
        "skipped": skipped,
        "reason": None if stored else "aucune source texte autorisée dans le dépôt",
    }


def _tokens(text: str) -> set[str]:
    return {word.lower() for word in re.findall(r"[\w-]{3,}", text, flags=re.UNICODE) if word.lower() not in _STOP}


def _score(terms: set[str], text: str) -> int:
    return len(terms & _tokens(text))


def _fraicheur(source: sqlite3.Row, repository: str | Path | None) -> str:
    if repository is None:
        return "unknown"
    top = Path(repository).resolve()
    source_root = Path(source["repository"]).resolve()
    relative = Path(source["path"])
    if relative.is_absolute() or ".." in relative.parts:
        return "missing"
    lexical = source_root / relative
    try:
        source_root.relative_to(top)
        # Une source qui est devenue un lien symbolique sort du périmètre d'indexation.
        current = lexical
        while current != source_root:
            if current.is_symlink():
                return "missing"
            current = current.parent
        path = lexical.resolve()
        path.relative_to(top)
        if path.stat().st_size > MAX_FILE_BYTES:
            return "too_large"
        digest = hashlib.sha256()
        total = 0
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            while chunk := stream.read(min(64_000, MAX_FILE_BYTES + 1 - total)):
                total += len(chunk)
                if total > MAX_FILE_BYTES:
                    return "too_large"
                digest.update(chunk)
    except (OSError, ValueError):
        return "missing"
    return "current" if digest.hexdigest() == source["sha256"] else "stale"


def _valeurs_structurees(value: Any, fields: set[str]) -> set[str]:
    values: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in fields:
                if isinstance(item, str):
                    values.add(item)
                elif isinstance(item, list):
                    values.update(entry for entry in item if isinstance(entry, str))
            elif isinstance(item, (dict, list)):
                values.update(_valeurs_structurees(item, fields))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                values.update(_valeurs_structurees(item, fields))
    return values


def _candidat_eligible(row: sqlite3.Row, module: str, remplaces: set[str]) -> dict[str, Any] | None:
    if row["event_type"] not in {"prompt", "plan", "decision", "postflight"}:
        return None
    payload = json.loads(row["payload_json"])
    if payload.get("module", "").upper() != module.upper():
        return None
    state = "superseded" if row["event_id"] in remplaces else payload.get("status", "active")
    if row["event_type"] in {"prompt", "plan", "decision"} and state not in {
        "active", "verified", "draft", "requires_review", "sensitive", "superseded"
    }:
        return None
    entity_key = {
        "prompt": "prompt_id",
        "plan": "plan_id",
        "decision": "decision_id",
        "postflight": "operation_id",
    }[row["event_type"]]
    return {
        "kind": row["event_type"],
        "entity_id": payload.get(entity_key, row["entity_id"]),
        "version": row["version"],
        "status": state,
        "event_id": row["event_id"],
        "recorded_at": row["recorded_at"],
        "content_hash": row["payload_hash"],
        "payload": payload,
        **(
            {"diagnostic_assurance": "author_assertion_unverified"}
            if row["event_type"] == "postflight" and isinstance(payload.get("diagnostic"), dict)
            else {}
        ),
    }


def _resoudre_lignees(
    eligible: dict[str, dict[str, Any]],
    direct_anchors: set[str],
    raw_successors: dict[str, list[str]],
) -> tuple[dict[str, set[str]], set[str], set[str], set[str], int, bool, int]:
    """Suit un graphe borné après filtrage module/statut; distingue cycles et convergences."""
    successors = {
        event_id: sorted(target for target in raw_successors.get(event_id, []) if target in eligible)
        for event_id in eligible
    }
    blocked_edges: set[tuple[str, str]] = set()
    endpoints: dict[str, set[str]] = {}
    lineage_nodes: set[str] = set()
    unresolved: set[str] = set()
    frontier: set[str] = set()
    visits = 0
    budget_exhausted = False
    for anchor in sorted(direct_anchors):
        if visits >= MAX_PREFLIGHT_LINEAGE_NODES:
            budget_exhausted = True
            unresolved.add(anchor)
            frontier.add(anchor)
            continue
        colors: dict[str, int] = {anchor: 1}  # 1 = actif sur la pile DFS, 2 = terminé.
        visits += 1
        stack: list[tuple[str, Any]] = [(anchor, iter(successors.get(anchor, [])))]
        sinks: set[str] = set()
        saw_blocked = saw_cycle = False
        for target in raw_successors.get(anchor, []):
            if target not in eligible:
                blocked_edges.add((anchor, target))
                saw_blocked = True
        if not raw_successors.get(anchor):
            sinks.add(anchor)
        while stack:
            current, children = stack[-1]
            try:
                target = next(children)
            except StopIteration:
                colors[current] = 2
                stack.pop()
                continue
            target_color = colors.get(target, 0)
            if target_color == 1:
                saw_cycle = True
                continue
            if target_color == 2:
                # Déjà complètement exploré depuis une autre branche : convergence acyclique.
                continue
            if visits >= MAX_PREFLIGHT_LINEAGE_NODES:
                budget_exhausted = True
                frontier.add(target)
                unresolved.add(anchor)
                continue
            colors[target] = 1
            visits += 1
            lineage_nodes.add(target)
            stack.append((target, iter(successors.get(target, []))))
            raw_targets = raw_successors.get(target, [])
            for blocked in raw_targets:
                if blocked not in eligible:
                    blocked_edges.add((target, blocked))
                    saw_blocked = True
            if not raw_targets:
                sinks.add(target)
        valid_sinks = {event_id for event_id in sinks if eligible[event_id]["status"] != "superseded"}
        if valid_sinks:
            endpoints[anchor] = valid_sinks
        if saw_blocked or saw_cycle or (not valid_sinks and budget_exhausted):
            unresolved.add(anchor)
    return endpoints, lineage_nodes, unresolved, frontier, len(blocked_edges), budget_exhausted, visits

def preflight(module: str, task: str, *, files: list[str], repository: str | Path | None = None) -> dict[str, Any]:
    """Construit un paquet sourcé de must-know, preuves, fraîcheur et contradictions."""
    _acteur()
    if not module or not task or len(task) > 8_000:
        raise ValueError("module et tâche bornés requis")
    safe_files = _references_sures(files)
    terms = _tokens(f"{module} {task} {' '.join(safe_files)}")
    with _connexion() as cnx:
        rows = cnx.execute("SELECT * FROM events ORDER BY seq DESC").fetchall()
        source_rows = cnx.execute("SELECT * FROM sources ORDER BY scanned_at DESC").fetchall()
        relation_rows = cnx.execute("SELECT * FROM relations ORDER BY created_at").fetchall()
    remplaces = {row["from_event"] for row in relation_rows if row["relation_type"] == "superseded_by"}
    raw_successors: dict[str, list[str]] = {}
    for relation in relation_rows:
        if relation["relation_type"] == "superseded_by":
            raw_successors.setdefault(relation["from_event"], []).append(relation["to_ref"])

    freshness_cache: dict[tuple[str, str, str], str] = {}

    def freshness_for_source(source: sqlite3.Row) -> str:
        identity = (str(Path(source["repository"]).resolve()), source["path"], source["sha256"])
        if identity not in freshness_cache:
            freshness_cache[identity] = _fraicheur(source, repository)
        return freshness_cache[identity]

    eligible: dict[str, dict[str, Any]] = {}
    for row in rows:
        candidate = _candidat_eligible(row, module, remplaces)
        if candidate is not None:
            eligible[candidate["event_id"]] = candidate

    path_fields = {"source_refs", "fichiers", "files", "source", "sources", "fichier"}
    id_fields = {"prompt_id", "plan_id", "decision_id", "operation_id"}
    # Preserve the historic tokenization for prompt/plan/decision IDs (notably
    # terminal prose punctuation), and add exact schema-bounded incident IDs.
    task_identifiers = set(re.findall(r"(?<![\w-])[\w-]{3,}(?![\w-])", task))
    incident_identifiers = set(
        re.findall(r"(?<![A-Za-z0-9._:-])[A-Za-z0-9][A-Za-z0-9._:-]{0,127}(?![A-Za-z0-9._:-])", task)
    )
    scores: dict[str, int] = {}
    direct_anchors: set[str] = set()
    anchor_paths: dict[str, set[str]] = {}
    for event_id, candidate in eligible.items():
        payload = candidate["payload"]
        scores[event_id] = _score(terms, _json(payload))
        refs = _valeurs_structurees(payload, path_fields)
        typed_ids = _valeurs_structurees(payload, id_fields)
        incident_ids = _valeurs_structurees(payload, {"incident_id"})
        paths = set(safe_files) & refs
        if (
            paths
            or task_identifiers & (typed_ids | {candidate["entity_id"]})
            or incident_identifiers & incident_ids
        ):
            direct_anchors.add(event_id)
            anchor_paths[event_id] = paths

    endpoints, lineage_nodes, unresolved, lineage_frontier, blocked_edges, budget_exhausted, lineage_visits = (
        _resoudre_lignees(eligible, direct_anchors, raw_successors)
    )
    endpoint_events = {endpoint for values in endpoints.values() for endpoint in values}
    result_event_ids = {
        event_id
        for event_id, score in scores.items()
        if score > 0 or event_id in direct_anchors or event_id in lineage_nodes or event_id in endpoint_events
    }

    sources_by_event: dict[str, list[sqlite3.Row]] = {}
    for source in source_rows:
        if source["module"].upper() in {module.upper(), "CORE", "OPSYS"}:
            sources_by_event.setdefault(source["event_id"], []).append(source)

    sequence_by_event = {row["event_id"]: row["seq"] for row in rows}

    def rank_record(event_id: str) -> tuple[int, int, float, int]:
        record = eligible[event_id]
        known_freshness = [freshness_for_source(source) for source in sources_by_event.get(event_id, [])]
        freshness_rank = (
            0 if "current" in known_freshness else
            1 if not known_freshness or "unknown" in known_freshness else
            2
        )
        timestamp = datetime.fromisoformat(record["recorded_at"]).timestamp()
        # Sets of anchors/endpoints must not change a bounded selection across processes.
        return (-scores[event_id], freshness_rank, -timestamp, -sequence_by_event[event_id])

    file_order = {path: index for index, path in enumerate(safe_files)}
    ordered_events: list[str] = []
    used_events: set[str] = set()
    # Current endpoints are selected before old anchors so bounded output retains current truth.
    targeted_endpoints = {event for values in endpoints.values() for event in values}
    ordered_events.extend(sorted(targeted_endpoints, key=rank_record))
    used_events.update(ordered_events)
    ordered_anchors = sorted(
        direct_anchors,
        key=lambda event: (
            min((file_order[path] for path in anchor_paths.get(event, set())), default=len(file_order)),
            *rank_record(event),
        ),
    )
    for anchor in ordered_anchors:
        if anchor not in used_events:
            ordered_events.append(anchor)
            used_events.add(anchor)
    intermediate_events = lineage_nodes - direct_anchors - endpoint_events
    for event_id in sorted(intermediate_events & result_event_ids, key=rank_record):
        if event_id not in used_events:
            ordered_events.append(event_id)
            used_events.add(event_id)
    ordinary_events = [
        event_id for event_id in eligible
        if event_id in result_event_ids and event_id not in used_events
    ]
    ordered_events.extend(sorted(ordinary_events, key=rank_record))
    candidates = [eligible[event_id] for event_id in ordered_events]
    must_know = candidates[:MAX_PREFLIGHT_MUST_KNOW]
    candidates_omitted = max(0, len(candidates) - len(must_know))
    evidence = []
    for source in source_rows:
        if source["module"].upper() not in {module.upper(), "CORE", "OPSYS"}:
            continue
        source_text = f"{source['path']} {source['excerpt']}"
        score = _score(terms, source_text)
        if safe_files and any(file in source["path"] for file in safe_files):
            score += 5
        if score <= 0:
            continue
        evidence.append(
            {
                "source_ref": source["source_ref"],
                "path": source["path"],
                "sha256": source["sha256"],
                "module": source["module"],
                "status": source["status"],
                "freshness": freshness_for_source(source),
                "event_id": source["event_id"],
                "excerpt": source["excerpt"][:800],
            }
        )
    evidence.sort(key=lambda item: (item["freshness"] != "current", item["path"]))
    by_claim: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        payload = candidate["payload"]
        if candidate["kind"] == "postflight" and payload.get("claim_key"):
            by_claim.setdefault(payload["claim_key"], []).append(candidate)
    unresolved_anchors = unresolved
    frontier_omitted = lineage_frontier
    expanded = lineage_visits
    known_events = {item["event_id"] for item in must_know}
    links_all = [row for row in relation_rows if row["from_event"] in known_events]
    anchor_order = {event_id: index for index, event_id in enumerate(ordered_anchors)}
    links_all.sort(key=lambda row: (
        0 if row["from_event"] in direct_anchors else 1,
        anchor_order.get(row["from_event"], len(anchor_order)),
        row["created_at"], row["from_event"], row["to_ref"],
    ))
    links = [
        {"from_event": row["from_event"], "to_ref": row["to_ref"], "type": row["relation_type"]}
        for row in links_all[:MAX_PREFLIGHT_LINKS]
    ]
    links_omitted = max(0, len(links_all) - len(links))
    all_contradictions = []
    contradiction_evidence_per_claim_omitted = 0
    for claim, items in by_claim.items():
        statuses = {item["status"] for item in items}
        if len(statuses) > 1:
            first = items[0]
            representative = [first]
            representative.extend(item for item in items[1:] if item["status"] != first["status"])
            contradiction_evidence = representative[:MAX_PREFLIGHT_CONTRADICTION_EVIDENCE]
            contradiction_evidence_per_claim_omitted += max(
                0, len(items) - len(contradiction_evidence)
            )
            all_contradictions.append(
                {
                    "claim_key": claim,
                    "statuses": sorted(statuses),
                    "evidence_count": len(items),
                    "evidence": [
                        {
                            "event_id": item["event_id"],
                            "status": item["status"],
                            "summary": item["payload"]["summary"],
                            "recorded_at": item["recorded_at"],
                        }
                        for item in contradiction_evidence
                    ],
                }
            )
    contradictions = all_contradictions[:MAX_PREFLIGHT_CONTRADICTIONS]
    contradictions_omitted = max(0, len(all_contradictions) - len(contradictions))
    evidence_total = sum(item["evidence_count"] for item in all_contradictions)
    evidence_returned = sum(len(item["evidence"]) for item in contradictions)
    evidence_omitted = evidence_total - evidence_returned
    lineage_traversal_truncated = budget_exhausted or bool(frontier_omitted)
    truncated = bool(
        candidates_omitted
        or lineage_traversal_truncated
        or unresolved_anchors
        or blocked_edges
        or links_omitted
        or contradictions_omitted
        or contradiction_evidence_per_claim_omitted
        or evidence_omitted
    )
    limits = {
        "must_know": MAX_PREFLIGHT_MUST_KNOW,
        "contradictions": MAX_PREFLIGHT_CONTRADICTIONS,
        "contradiction_evidence_per_claim": MAX_PREFLIGHT_CONTRADICTION_EVIDENCE,
    }
    counts = {
        "candidates": len(candidates),
        "must_know": len(must_know),
        "candidates_omitted": candidates_omitted,
        "lineage_traversal_truncated": lineage_traversal_truncated,
        "lineage_frontier_omitted": len(frontier_omitted),
        "lineage_unresolved": len(unresolved_anchors),
        "lineage_blocked_edges": blocked_edges,
        "lineage_nodes_examined": expanded,
        "lineage_node_limit": MAX_PREFLIGHT_LINEAGE_NODES,
        "lineage_endpoints": len(endpoint_events),
        "lineage_anchors": len(direct_anchors),
        "links_limit": MAX_PREFLIGHT_LINKS,
        "links_omitted": links_omitted,
        "contradictions": len(all_contradictions),
        "contradictions_returned": len(contradictions),
        "contradictions_omitted": contradictions_omitted,
        "evidence_total": evidence_total,
        "evidence_returned": evidence_returned,
        "evidence_omitted": evidence_omitted,
        "contradiction_evidence_per_claim_omitted": contradiction_evidence_per_claim_omitted,
    }
    available = bool(must_know or evidence)
    limitations = []
    if any(isinstance(item["payload"].get("diagnostic"), dict) for item in must_know):
        limitations.append("causes et résultats de test sont des déclarations d'auteur, non attestées automatiquement")
    if not evidence:
        limitations.append("aucune preuve de fichier récupérée; lancer un scan Git borné")
    if any(item["freshness"] in {"stale", "missing", "unknown", "too_large"} for item in evidence):
        limitations.append("fraîcheur des sources incomplète ou divergente")
    if contradictions:
        limitations.append("résultat contradictoire : vérifier les preuves avant de poursuivre")
    if truncated:
        limitations.append("sortie preflight bornée; consulter les compteurs pour les éléments omis")
    if lineage_traversal_truncated:
        limitations.append("lignée de remplacement partiellement omise; vérifier les liens conservés")
    if unresolved_anchors:
        limitations.append("lignée de remplacement non résolue dans le périmètre éligible")
    if links_omitted:
        limitations.append("liens de mémoire bornés; consulter les compteurs d’omission")
    if not available:
        return {
            "status": "unavailable",
            "reason": "aucune source ni mémoire pertinente pour cette tâche",
            "module": module.upper(),
            "task": task,
            "must_know": [],
            "evidence": [],
            "contradictions": [],
            "links": [],
            "limits": limits,
            "counts": counts,
            "truncated": truncated,
            "limitations": ["contexte indisponible; ne pas supposer que le travail est fait"],
        }
    return {
        "status": "available",
        "reason": None,
        "module": module.upper(),
        "task": task,
        "must_know": must_know,
        "evidence": evidence,
        "contradictions": contradictions,
        "links": links,
        "limits": limits,
        "counts": counts,
        "truncated": truncated,
        "limitations": limitations,
    }


def auditer_developpement(
    *, repository: str | Path | None = None, limite: int = 100
) -> dict[str, Any]:
    """Produit un rapport bounded de liens incomplets, résultats contradictoires et sources périmées.

    Le rapport est une vue de contrôle sourcée, sans modifier le registre ni déduire qu'une étape est achevée.
    """
    _acteur()
    if not isinstance(limite, int) or isinstance(limite, bool) or not 1 <= limite <= MAX_AUDIT_FINDINGS:
        raise ValueError(f"limite d'audit entre 1 et {MAX_AUDIT_FINDINGS} requise")
    snapshot = _snapshot_audit_developpement(
        max_events=MAX_AUDIT_EVENTS, max_relations=MAX_AUDIT_RELATIONS, max_sources=MAX_AUDIT_SOURCES,
    )
    snapshot["freshness"] = {
        source["source_ref"]: _fraicheur(source, repository) for source in snapshot["sources"][:MAX_AUDIT_SOURCES]
    }
    repository_normalise = str(Path(repository).resolve()) if repository is not None else None
    return _analyser_audit_developpement(snapshot, repository=repository_normalise, limite=limite)


def _snapshot_audit_developpement(
    *, max_events: int = MAX_AUDIT_EVENTS, max_relations: int = MAX_AUDIT_RELATIONS,
    max_sources: int = MAX_AUDIT_SOURCES,
) -> dict[str, Any]:
    """Lecture interne du canon complet ; les wrappers contrôlent leur autorité avant cet appel."""
    with _connexion() as cnx:
        rows = cnx.execute("SELECT * FROM events ORDER BY seq DESC LIMIT ?", (max_events + 1,)).fetchall()
        relations = cnx.execute(
            "SELECT * FROM relations ORDER BY created_at DESC, relation_id DESC LIMIT ?", (max_relations + 1,)
        ).fetchall()
        sources = cnx.execute(
            "SELECT * FROM sources ORDER BY scanned_at DESC, source_ref LIMIT ?", (max_sources + 1,)
        ).fetchall()
        source_count = cnx.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        event_count = cnx.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        relation_count = cnx.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        target_refs = sorted(
            {
                relation["to_ref"]
                for relation in relations[:max_relations]
                if relation["relation_type"] in {"prompt_for", "plan_for", "superseded_by"}
            }
        )
        existing_targets: set[str] = set()
        for start in range(0, len(target_refs), 500):
            chunk = target_refs[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            existing_targets.update(
                row[0] for row in cnx.execute(f"SELECT event_id FROM events WHERE event_id IN ({placeholders})", chunk)
            )
        postflight_plan_entities = sorted({
            f"plan:{json.loads(row['payload_json']).get('plan_id')}"
            for row in rows[:max_events] if row["event_type"] == "postflight"
        })
        existing_plan_entities: set[str] = set()
        for start in range(0, len(postflight_plan_entities), 500):
            chunk = postflight_plan_entities[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            existing_plan_entities.update(
                row[0] for row in cnx.execute(
                    f"SELECT DISTINCT entity_id FROM events WHERE entity_id IN ({placeholders})", chunk
                )
            )
        chain = registre.Registre(maillons=stockage.maillons("m10-memoire", REGISTRE_DURABLE))
        return {
            "rows": [dict(row) for row in rows], "relations": [dict(row) for row in relations],
            "sources": [dict(row) for row in sources], "source_count": source_count,
            "event_count": event_count, "relation_count": relation_count,
            "existing_targets": existing_targets, "existing_plan_entities": existing_plan_entities,
            "max_events": max_events, "max_relations": max_relations, "max_sources": max_sources,
            "head": chain.tete(),
        }


def _analyser_audit_developpement(
    snapshot: dict[str, Any], *, repository: str | Path | None, limite: int,
) -> dict[str, Any]:
    """Analyse déterministe d'un snapshot et de ses fraîcheurs déjà mesurées, sans IO ni identité."""
    rows, relations, sources = snapshot["rows"], snapshot["relations"], snapshot["sources"]
    max_events, max_relations, max_sources = snapshot["max_events"], snapshot["max_relations"], snapshot["max_sources"]
    source_count = snapshot["source_count"]
    existing_targets = snapshot["existing_targets"]
    existing_plan_entities = snapshot["existing_plan_entities"]
    event_scan_truncated = len(rows) > max_events
    relation_scan_truncated = len(relations) > max_relations
    events = [dict(row) for row in reversed(rows[:max_events])]
    relations = relations[:max_relations]
    by_id = {event["event_id"]: event for event in events}
    latest: dict[str, dict[str, Any]] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for event in events:
        latest[event["entity_id"]] = event
        payloads[event["event_id"]] = json.loads(event["payload_json"])
    relations_by_type: dict[str, list[sqlite3.Row]] = {}
    for relation in relations:
        relations_by_type.setdefault(relation["relation_type"], []).append(relation)

    findings: list[dict[str, Any]] = []
    findings_truncated = False
    counts: dict[str, int] = {
        "prompts_sans_plan": 0,
        "plans_sans_postflight": 0,
        "sources_perimees": 0,
        "relations_cibles_absentes": 0,
        "relations_hors_fenetre": 0,
        "claims_contradictoires": 0,
        "postflights_sans_plan": 0,
    }

    def ajouter(type_finding: str, *, event_ids: list[str], preuves: list[dict[str, Any]], detail: str) -> None:
        nonlocal findings_truncated
        counts[type_finding] += 1
        if len(findings) < MAX_AUDIT_FINDINGS:
            findings.append({"type": type_finding, "event_ids": event_ids, "preuves": preuves, "detail": detail})
        else:
            findings_truncated = True

    prompt_events = [event for event in latest.values() if event["event_type"] == "prompt"]
    linked_prompt_ids = {
        relation["to_ref"] for relation in relations_by_type.get("prompt_for", []) if relation["to_ref"] in by_id
    }
    for event in prompt_events:
        if event["event_id"] not in linked_prompt_ids:
            ajouter(
                "prompts_sans_plan",
                event_ids=[event["event_id"]],
                preuves=[{"event_id": event["event_id"], "type": "prompt", "hash": event["payload_hash"]}],
                detail="prompt courant sans relation vers un plan enregistré",
            )

    plan_events = [event for event in latest.values() if event["event_type"] == "plan"]
    linked_plan_ids = {
        relation["to_ref"] for relation in relations_by_type.get("plan_for", []) if relation["to_ref"] in by_id
    }
    for event in plan_events:
        if event["event_id"] not in linked_plan_ids:
            ajouter(
                "plans_sans_postflight",
                event_ids=[event["event_id"]],
                preuves=[{"event_id": event["event_id"], "type": "plan", "hash": event["payload_hash"]}],
                detail="plan courant sans postflight enregistré",
            )

    for event in latest.values():
        if event["event_type"] != "postflight":
            continue
        payload = payloads[event["event_id"]]
        plan_id = payload.get("plan_id")
        if f"plan:{plan_id}" not in existing_plan_entities:
            ajouter(
                "postflights_sans_plan",
                event_ids=[event["event_id"]],
                preuves=[{"event_id": event["event_id"], "plan_id": plan_id}],
                detail="postflight conservé avec une référence de plan absente du registre canonique",
            )

    internal_relations = {"prompt_for", "plan_for", "superseded_by"}
    for relation in relations:
        if relation["relation_type"] in internal_relations and relation["to_ref"] not in by_id:
            existe = relation["to_ref"] in existing_targets
            ajouter(
                "relations_hors_fenetre" if existe else "relations_cibles_absentes",
                event_ids=[relation["from_event"]],
                preuves=[{"relation_id": relation["relation_id"], "to_ref": relation["to_ref"]}],
                detail=(
                    f"relation {relation['relation_type']} vers un événement existant hors de la fenêtre d'audit"
                    if existe
                    else f"relation {relation['relation_type']} vers un événement absent du registre"
                ),
            )

    claims: dict[str, list[dict[str, Any]]] = {}
    for event in latest.values():
        if event["event_type"] != "postflight":
            continue
        payload = payloads[event["event_id"]]
        if payload.get("claim_key"):
            claims.setdefault((payload.get("module", "").upper(), payload["claim_key"]), []).append(event)
    for (module, claim), claim_events in claims.items():
        statuses = {payloads[event["event_id"]].get("status") for event in claim_events}
        if len(statuses) > 1:
            ajouter(
                "claims_contradictoires",
                event_ids=[event["event_id"] for event in claim_events],
                preuves=[
                    {
                        "event_id": event["event_id"],
                        "hash": event["payload_hash"],
                        "status": payloads[event["event_id"]].get("status"),
                    }
                    for event in claim_events
                ],
                detail=(
                    f"claim {claim!r} du module {module or 'inconnu'} conserve plusieurs verdicts; "
                    "aucune conclusion automatique"
                ),
            )

    source_limit_exceeded = len(sources) > max_sources
    freshness_counts = {status: 0 for status in ("current", "stale", "missing", "too_large", "unknown")}
    sources_audited = 0
    for source in sources[:max_sources]:
        freshness = snapshot["freshness"].get(source["source_ref"], "unknown")
        freshness_counts[freshness] += 1
        sources_audited += 1
        if freshness in {"stale", "missing", "too_large"}:
            ajouter(
                "sources_perimees",
                event_ids=[source["event_id"]],
                preuves=[
                    {
                        "event_id": source["event_id"],
                        "source_ref": source["source_ref"],
                        "path": source["path"],
                        "indexed_sha256": source["sha256"],
                        "freshness": freshness,
                    }
                ],
                detail="source absente, modifiée ou trop volumineuse pour une vérification bornée",
            )
    truncated = (
        source_limit_exceeded
        or event_scan_truncated
        or relation_scan_truncated
        or findings_truncated
        or sum(counts.values()) > limite
    )
    return {
        "status": "partial" if truncated else "available",
        "domain": DOMAINE,
        "repository": str(repository) if repository is not None else None,
        "freshness": {
            "status": "unknown" if repository is None else "partial" if source_limit_exceeded else "checked",
            "sources_checked": sources_audited if repository is not None else 0,
            "sources_in_registry": source_count,
            "sources_unknown": source_count if repository is None else freshness_counts["unknown"],
            "sources_unchecked_by_cap": max(0, source_count - sources_audited) if repository is not None else 0,
            "counts": freshness_counts,
            "source_scan_truncated": source_limit_exceeded,
        },
        "counts": counts,
        "findings": findings[:limite],
        "limit": limite,
        "truncated": truncated or len(findings) > limite,
        "source_scan_truncated": source_limit_exceeded,
        "event_scan_truncated": event_scan_truncated,
        "relation_scan_truncated": relation_scan_truncated,
        "note": "rapport de contrôle non destructif; les statuts et contradictions exigent une revue humaine",
    }


def verifier_chaine() -> dict[str, Any]:
    """Vérifie l'ancre et chaque empreinte du journal de développement; lecture admin/owner uniquement."""
    _acteur()
    with _connexion() as cnx:
        rows = cnx.execute("SELECT * FROM events ORDER BY seq").fetchall()
    previous = None
    for row in rows:
        payload_hash = _hash(row["payload_json"])
        if payload_hash != row["payload_hash"] or row["previous_hash"] != previous:
            return {"status": "invalid", "event_id": row["event_id"], "verified": 0, "total": len(rows)}
        expected = _hash(
            _json(
                {
                    "domain": DOMAINE,
                    "event_id": row["event_id"],
                    "type": row["event_type"],
                    "entity_id": row["entity_id"],
                    "version": row["version"],
                    "payload_hash": payload_hash,
                    "actor": row["actor"],
                    "recorded_at": row["recorded_at"],
                    "previous_hash": previous,
                }
            )
        )
        if expected != row["event_hash"]:
            return {"status": "invalid", "event_id": row["event_id"], "verified": 0, "total": len(rows)}
        previous = row["event_hash"]
    return {"status": "valid", "verified": len(rows), "total": len(rows), "head": previous}
