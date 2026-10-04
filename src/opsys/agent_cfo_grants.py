"""Grant humain révocable, quota et tickets privés pour les deux outils CFO préparatoires."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, func, insert, select, update

from . import agents, contexte, identite
from .stockage.schema import (
    AGENTS_GRANTS_CFO,
    AGENTS_GRANTS_CFO_HISTORIQUE,
    AGENTS_TICKETS_CFO,
    OPSYS_INSTANCE,
)

OUTILS = frozenset({"m5_preparer_dossier_decision_cfo", "m5_preparer_decision_capital"})
META = "opsys/cfoGrantTicket"
TTL_SECONDS = 90
_ROLES = frozenset({"admin", "nathan_owner"})


class GrantCfoRefuse(PermissionError):
    """Grant absent, expiré, révoqué ou hors portée."""


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat(timespec="seconds")


def _sqlite_uniquement(cnx: Connection) -> None:
    if cnx.dialect.name != "sqlite":
        raise GrantCfoRefuse("grants CFO agents non disponibles hors SQLite à ce jalon")


def _lire_date_rapport(arguments: Mapping[str, Any]) -> dt.date:
    value = arguments.get("aujourd_hui")
    if not isinstance(value, str):
        raise GrantCfoRefuse("date de rapport CFO absente")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise GrantCfoRefuse("date de rapport CFO invalide") from exc
    if value != parsed.isoformat():
        raise GrantCfoRefuse("date de rapport CFO doit être au format AAAA-MM-JJ")
    return parsed


def _date_dans_grant(arguments: Mapping[str, Any], grant: Mapping[str, Any]) -> None:
    report_date = _lire_date_rapport(arguments).isoformat()
    if not grant["report_date_start"] <= report_date <= grant["report_date_end"]:
        raise GrantCfoRefuse("date de rapport hors de l’intervalle autorisé par le grant")


def instance_id(cnx: Connection) -> str:
    """Stable identity created once by migration and stored with this database."""
    value = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
    if not isinstance(value, str) or not value:
        raise GrantCfoRefuse("identifiant d’instance durable indisponible")
    return value


def _instance(cnx: Connection, value: str) -> None:
    current = instance_id(cnx)
    if not isinstance(value, str) or not value or value != current:
        raise GrantCfoRefuse("scope d’instance CFO différent de cette base")


def _actor(cnx: Connection, par: str) -> tuple[str, str]:
    caller = contexte.identite_appelante()
    if caller is None or caller.source != "console" or caller.personne != par or caller.role not in _ROLES:
        raise GrantCfoRefuse("grant CFO réservé à une personne admin/propriétaire authentifiée en console")
    person = identite.personne_active(cnx, par)
    if person is None or caller.role not in person.roles:
        raise GrantCfoRefuse("rôle humain révoqué ou personne inactive")
    return par, caller.role


def _autorite(cnx: Connection, grant: Mapping[str, Any]) -> bool:
    person = identite.personne_active(cnx, grant["granted_by"])
    return person is not None and grant["granted_role"] in person.roles and grant["granted_role"] in _ROLES


def _snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: (json.loads(row[key]) if key == "tools" and isinstance(row[key], str) else row[key]) for key in row}


def _historiser(cnx: Connection, row: Mapping[str, Any], event: str, actor: str, role: str, now: str) -> None:
    cnx.execute(
        insert(AGENTS_GRANTS_CFO_HISTORIQUE).values(
            agent_id=row["agent_id"],
            version=row["version"],
            event=event,
            snapshot=json.dumps(_snapshot(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            actor=actor,
            actor_role=role,
            created_at=now,
        )
    )


def lire(cnx: Connection, agent_id: str, *, instance_id: str) -> dict[str, Any] | None:
    _sqlite_uniquement(cnx)
    _instance(cnx, instance_id)
    row = cnx.execute(select(AGENTS_GRANTS_CFO).where(AGENTS_GRANTS_CFO.c.agent_id == agent_id)).mappings().fetchone()
    if row is None or row["instance_id"] != instance_id:
        return None
    data = _snapshot(row)
    return data


def accorder(
    cnx: Connection,
    agent_id: str,
    *,
    par: str,
    instance_id: str,
    revision_attendue: int,
    version_attendue: int,
    date_debut_rapport: str,
    date_fin_rapport: str,
    outils: list[str] | None = None,
    rapports_par_jour: int = 3,
    expire_le: str | None = None,
) -> dict[str, Any]:
    _sqlite_uniquement(cnx)
    _instance(cnx, instance_id)
    tools = sorted(set(OUTILS if outils is None else outils))
    if not tools or not set(tools) <= OUTILS:
        raise ValueError("seuls les deux outils CFO préparatoires sont admissibles")
    if (
        isinstance(rapports_par_jour, bool)
        or not isinstance(rapports_par_jour, int)
        or not 1 <= rapports_par_jour <= 20
    ):
        raise ValueError("quota de rapports invalide (1..20)")
    try:
        date_debut = dt.date.fromisoformat(date_debut_rapport)
        date_fin = dt.date.fromisoformat(date_fin_rapport)
    except (TypeError, ValueError) as exc:
        raise ValueError("intervalle de rapport requis au format AAAA-MM-JJ") from exc
    if (
        date_debut.isoformat() != date_debut_rapport
        or date_fin.isoformat() != date_fin_rapport
        or date_debut > date_fin
        or (date_fin - date_debut).days > 90
    ):
        raise ValueError("intervalle de rapport invalide (ordre requis, 90 jours maximum)")
    now = _now()
    expiry = dt.datetime.fromisoformat(expire_le) if expire_le else now + dt.timedelta(days=30)
    if expiry.tzinfo is None or expiry <= now or expiry > now + dt.timedelta(days=90):
        raise ValueError("expiration future requise, 90 jours maximum")
    actor, role = _actor(cnx, par)
    profile = agents.obtenir(cnx, agent_id)
    if (
        profile is None
        or profile["departement"] != "m05-financecore"
        or not profile["actif"]
        or profile["revision"] != revision_attendue
        or not set(tools) <= set(profile["outils"])
    ):
        raise GrantCfoRefuse("profil M5 actif, révision courante et allowlist explicite requis")
    old = (
        cnx.execute(select(AGENTS_GRANTS_CFO).where(AGENTS_GRANTS_CFO.c.agent_id == agent_id).with_for_update())
        .mappings()
        .fetchone()
    )
    if isinstance(version_attendue, bool) or not isinstance(version_attendue, int):
        raise ValueError("version de grant attendue invalide")
    if (old is None and version_attendue != 0) or (old is not None and old["version"] != version_attendue):
        raise GrantCfoRefuse("version de grant périmée; rechargez la page avant la mutation")
    version = 1 if old is None else old["version"] + 1
    created_at = old["created_at"] if old is not None else _iso(now)
    values = {
        "agent_id": agent_id,
        "instance_id": instance_id,
        "profile_revision": revision_attendue,
        "version": version,
        "active": True,
        "tools": json.dumps(tools),
        "reports_per_day": rapports_par_jour,
        "expires_at": _iso(expiry),
        "report_date_start": date_debut.isoformat(),
        "report_date_end": date_fin.isoformat(),
        "granted_by": actor,
        "granted_role": role,
        "created_at": created_at,
        "modified_at": _iso(now),
        "modified_by": actor,
        "modified_role": role,
    }
    if old is None:
        cnx.execute(insert(AGENTS_GRANTS_CFO).values(**values))
    else:
        cnx.execute(update(AGENTS_GRANTS_CFO).where(AGENTS_GRANTS_CFO.c.agent_id == agent_id).values(**values))
    _historiser(cnx, values, "grant", actor, role, _iso(now))
    return {**values, "tools": tools}


def revoquer(cnx: Connection, agent_id: str, *, par: str, instance_id: str, version_attendue: int) -> dict[str, Any]:
    _sqlite_uniquement(cnx)
    _instance(cnx, instance_id)
    if isinstance(version_attendue, bool) or not isinstance(version_attendue, int):
        raise ValueError("version de grant attendue invalide")
    actor, role = _actor(cnx, par)
    row = (
        cnx.execute(select(AGENTS_GRANTS_CFO).where(AGENTS_GRANTS_CFO.c.agent_id == agent_id).with_for_update())
        .mappings()
        .fetchone()
    )
    if row is None or row["instance_id"] != instance_id or not row["active"] or row["version"] != version_attendue:
        raise GrantCfoRefuse("aucun grant CFO actif pour cette instance")
    now = _iso(_now())
    values = {
        **_snapshot(row),
        "version": row["version"] + 1,
        "active": False,
        "modified_at": now,
        "modified_by": actor,
        "modified_role": role,
    }
    cnx.execute(
        update(AGENTS_GRANTS_CFO)
        .where(AGENTS_GRANTS_CFO.c.agent_id == agent_id)
        .values(version=values["version"], active=False, modified_at=now, modified_by=actor, modified_role=role)
    )
    _historiser(cnx, values, "revocation", actor, role, now)
    return {"agent_id": agent_id, "active": False, "version": values["version"]}


def emettre(
    cnx: Connection,
    agent_id: str,
    outil: str,
    arguments: Mapping[str, Any],
    *,
    instance_id: str,
    revision_profil: int,
) -> dict[str, str]:
    _sqlite_uniquement(cnx)
    _instance(cnx, instance_id)
    if (
        outil not in OUTILS
        or not isinstance(arguments, Mapping)
        or isinstance(revision_profil, bool)
        or not isinstance(revision_profil, int)
    ):
        raise GrantCfoRefuse("outil CFO, révision profil ou arguments invalides")
    profile = agents.obtenir(cnx, agent_id)
    grant_row = (
        cnx.execute(select(AGENTS_GRANTS_CFO).where(AGENTS_GRANTS_CFO.c.agent_id == agent_id).with_for_update())
        .mappings()
        .fetchone()
    )
    now = _now()
    if grant_row is None:
        raise GrantCfoRefuse("grant CFO absent")
    if profile is not None and profile["revision"] != revision_profil:
        raise GrantCfoRefuse("révision de profil transmise périmée")
    grant = _snapshot(grant_row)
    if (
        profile is None
        or not profile["actif"]
        or profile["departement"] != "m05-financecore"
        or not grant["active"]
        or outil not in grant["tools"]
        or outil not in profile["outils"]
        or profile["revision"] != revision_profil
        or profile["revision"] != grant["profile_revision"]
        or grant["instance_id"] != instance_id
        or dt.datetime.fromisoformat(grant["expires_at"]) <= now
        or not _autorite(cnx, grant)
    ):
        raise GrantCfoRefuse("grant CFO expiré, révoqué, profil modifié ou autorité humaine révoquée")
    _date_dans_grant(arguments, grant)
    day_start = now.date().isoformat() + "T00:00:00"
    count = cnx.execute(
        select(func.count())
        .select_from(AGENTS_TICKETS_CFO)
        .where(AGENTS_TICKETS_CFO.c.agent_id == agent_id, AGENTS_TICKETS_CFO.c.created_at >= day_start)
    ).scalar_one()
    if count >= grant["reports_per_day"]:
        raise GrantCfoRefuse("quota quotidien d’émission de tickets CFO atteint")
    outstanding = cnx.execute(
        select(AGENTS_TICKETS_CFO.c.ticket_hash).where(
            AGENTS_TICKETS_CFO.c.agent_id == agent_id,
            AGENTS_TICKETS_CFO.c.grant_version == grant["version"],
            AGENTS_TICKETS_CFO.c.profile_revision == profile["revision"],
            AGENTS_TICKETS_CFO.c.status == "available",
            AGENTS_TICKETS_CFO.c.expires_at > _iso(now),
        )
    ).first()
    if outstanding is not None:
        raise GrantCfoRefuse("un ticket CFO est déjà en attente")
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    expiry = _iso(now + dt.timedelta(seconds=TTL_SECONDS))
    raw_args = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    cnx.execute(
        insert(AGENTS_TICKETS_CFO).values(
            ticket_hash=digest,
            agent_id=agent_id,
            grant_version=grant["version"],
            profile_revision=profile["revision"],
            instance_id=instance_id,
            tool=outil,
            arguments_hash=hashlib.sha256(raw_args.encode()).hexdigest(),
            created_at=_iso(now),
            expires_at=expiry,
        )
    )
    return {"ticket": raw, "expire_le": expiry}


def consommer(cnx: Connection, ticket: str, outil: str, arguments: Mapping[str, Any], *, instance_id: str) -> None:
    _sqlite_uniquement(cnx)
    _instance(cnx, instance_id)
    if not isinstance(ticket, str) or len(ticket) < 32 or len(ticket) > 256:
        raise GrantCfoRefuse("ticket CFO absent ou invalide")
    digest = hashlib.sha256(ticket.encode()).hexdigest()
    now = _now()
    row = (
        cnx.execute(select(AGENTS_TICKETS_CFO).where(AGENTS_TICKETS_CFO.c.ticket_hash == digest).with_for_update())
        .mappings()
        .fetchone()
    )
    if row is None:
        raise GrantCfoRefuse("ticket CFO inconnu")
    grant_row = (
        cnx.execute(select(AGENTS_GRANTS_CFO).where(AGENTS_GRANTS_CFO.c.agent_id == row["agent_id"]).with_for_update())
        .mappings()
        .fetchone()
    )
    profile = agents.obtenir(cnx, row["agent_id"])
    grant = _snapshot(grant_row) if grant_row is not None else None
    raw_args = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    args_hash = hashlib.sha256(raw_args.encode()).hexdigest()
    if (
        row["status"] != "available"
        or row["tool"] != outil
        or row["instance_id"] != instance_id
        or row["arguments_hash"] != args_hash
        or dt.datetime.fromisoformat(row["expires_at"]) <= now
        or grant is None
        or not grant["active"]
        or dt.datetime.fromisoformat(grant["expires_at"]) <= now
        or row["grant_version"] != grant["version"]
        or row["profile_revision"] != grant["profile_revision"]
        or row["profile_revision"] != (profile or {}).get("revision")
        or grant["instance_id"] != instance_id
        or outil not in grant["tools"]
        or not _autorite(cnx, grant)
        or profile is None
        or not profile["actif"]
        or profile["departement"] != "m05-financecore"
    ):
        raise GrantCfoRefuse("ticket CFO réutilisé, hors portée, expiré ou autorité invalidée")
    _date_dans_grant(arguments, grant)
    changed = cnx.execute(
        update(AGENTS_TICKETS_CFO)
        .where(AGENTS_TICKETS_CFO.c.ticket_hash == digest, AGENTS_TICKETS_CFO.c.status == "available")
        .values(status="consumed", consumed_at=_iso(now))
    )
    if changed.rowcount != 1:
        raise GrantCfoRefuse("ticket CFO déjà consommé")
