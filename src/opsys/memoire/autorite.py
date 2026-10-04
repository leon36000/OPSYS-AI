"""Autorité serveur de lecture client; tickets séparés des mutations C02/CFO.

La classification est un fragment persistant du générateur, jamais une valeur MCP du modèle.
L'autorité client est SQLite; la mémoire PostgreSQL reste un magasin séparé.
"""
from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
import hashlib
import json
import os
import secrets
import stat
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import insert, select, update

from .. import idempotence, liaison_cibles, stockage
from ..outils import Autonomie, Outil, valider_arguments
from ..stockage.schema import LIAISONS_TICKETS

NOM_OUTIL = "opsys_memoire_rechercher"
NOM_EMISSION = "opsys_contexte_creer_ticket_memoire"
META = "opsys/memoireLectureTicket"
FICHIER = "memoire-autorites.json"
TTL = 120
_CHAMPS = {"version", "departements", "agents", "procedures_globales"}
_SCOPE: contextvars.ContextVar[tuple[tuple[str, ...], tuple[str, ...]] | None] = contextvars.ContextVar(
    "opsys_autorite_memoire", default=None
)


def valider_politique(valeur: Any) -> dict[str, Any]:
    if (not isinstance(valeur, dict) or set(valeur) != _CHAMPS
            or type(valeur["version"]) is not int or valeur["version"] != 1
            or not isinstance(valeur["departements"], dict) or not isinstance(valeur["agents"], dict)
            or valeur["procedures_globales"] != ["procedures"]):
        raise ValueError("MEMOIRE-CLASSIFICATION-INVALIDE: régénérer les fragments serveur")
    for departement, mode in valeur["departements"].items():
        if (not isinstance(departement, str) or not departement.startswith("m")
                or not isinstance(mode, str) or mode not in {"global", "client_session"}):
            raise ValueError("MEMOIRE-CLASSIFICATION-INVALIDE: département ou mode invalide")
    for agent, binding in valeur["agents"].items():
        if (not isinstance(agent, str) or not 1 <= len(agent) <= 96 or not isinstance(binding, dict)
                or set(binding) != {"departement", "mode"}
                or not isinstance(binding["departement"], str)
                or binding["departement"] not in valeur["departements"]
                or binding["mode"] != valeur["departements"][binding["departement"]]):
            raise ValueError("MEMOIRE-CLASSIFICATION-INVALIDE: identité d'agent incohérente")
    return valeur


def lire_politique(dossier: Path | None = None) -> dict[str, Any]:
    if dossier is None:
        from ..instance import dossier_core
        dossier = Path(os.environ["OPENCLAW_CONFIG_DIR"]) if os.environ.get("OPENCLAW_CONFIG_DIR") else dossier_core()
    fichier = dossier / "opsys" / FICHIER
    try:
        fd = os.open(fichier, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as flux:
            info = os.fstat(flux.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 131072:
                raise ValueError("MEMOIRE-CLASSIFICATION-INVALIDE: fragment non régulier ou trop volumineux")
            contenu = flux.read(131073)
        if len(contenu) > 131072:
            raise ValueError("MEMOIRE-CLASSIFICATION-INVALIDE: fragment trop volumineux")
        return valider_politique(json.loads(contenu))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("MEMOIRE-CLASSIFICATION-ABSENTE: régénérer les fragments serveur") from exc


def empreinte_politique(politique: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(politique, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def meta_ticket(meta: Mapping[str, Any] | None) -> str | None:
    if not meta or META not in meta:
        return None
    valeur = meta[META]
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > 4096:
        raise ValueError("MEMOIRE-TICKET-INVALIDE")
    return valeur


def sujets_de_lecture() -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    return _SCOPE.get()


@contextlib.contextmanager
def lecture_bornee(sujets: tuple[str, ...], procedures: tuple[str, ...]) -> Iterator[None]:
    token = _SCOPE.set((sujets, procedures))
    try:
        yield
    finally:
        _SCOPE.reset(token)


def _client(affaire: str) -> str:
    from m2_revenue_crm import clients, registre
    journal = registre.Registre(stockage.maillons("m02-revenue-crm", "principal"))
    if journal.valider_chaine() is not True:
        raise ValueError("MEMOIRE-REFERENCE-CLIENT-INVALIDE: registre M2 altéré")
    lead = affaire.split("~opp~", 1)[0]
    if not any(m.get("type_entree") == "lead_ingere" and m.get("lead_id") == lead for m in journal.lire()):
        raise ValueError("MEMOIRE-REFERENCE-CLIENT-ABSENTE: lead M2 inconnu")
    client = clients.client_de_lead(journal, lead)
    if not isinstance(client, str) or not client or len(client) > 128:
        raise ValueError("MEMOIRE-REFERENCE-CLIENT-ABSENTE")
    from .store import _SUJET
    if _SUJET.fullmatch("client:" + client) is None:
        raise ValueError("MEMOIRE-REFERENCE-CLIENT-INVALIDE")
    return client


def _liaison(session: str) -> dict[str, Any]:
    from m10_memoire import liaison
    active = liaison.liaison_courante(session, liaison_cibles._registre_m10())
    if active is None:
        raise ValueError("MEMOIRE-LIAISON-ABSENTE: aucune affaire client active")
    return active


def emettre(cnx: Any, politique: Mapping[str, Any], departement: str, agent_id: str,
            cle_session: str, arguments: Mapping[str, Any]) -> dict[str, str]:
    liaison_cibles._sqlite_uniquement(cnx)
    politique = valider_politique(politique)
    binding = politique["agents"].get(agent_id)
    if (binding != {"departement": departement, "mode": "client_session"}
            or not isinstance(cle_session, str) or not cle_session.startswith(f"agent:{agent_id}:")):
        raise ValueError("MEMOIRE-IDENTITE-SESSION-INVALIDE")
    from .outils import outils
    schema = next(o.parametres for o in outils() if o.nom == NOM_OUTIL)
    if valider_arguments(schema, arguments):
        raise ValueError("MEMOIRE-ARGUMENTS-INVALIDES")
    active = _liaison(cle_session)
    client = _client(active["affaire_id"])
    sujet = arguments.get("sujet")
    if sujet is not None and sujet != f"client:{client}":
        raise ValueError("MEMOIRE-SUJET-HORS-AUTORITE")
    maintenant = dt.datetime.now(dt.UTC)
    token = secrets.token_urlsafe(32)
    description = {"purpose": "memoire_client_v1", "client_id": client,
                   "politique_sha256": empreinte_politique(politique)}
    cnx.execute(insert(LIAISONS_TICKETS).values(
        ticket_hash=liaison_cibles.empreinte_ticket(token), cree_le=maintenant.isoformat(),
        expire_le=(maintenant + dt.timedelta(seconds=TTL)).isoformat(), departement=departement,
        agent_id=agent_id, cle_session=cle_session, affaire_id=active["affaire_id"],
        genre_affaire="opportunite" if "~opp~" in active["affaire_id"] else "lead",
        ligne_liaison_id=active["ligne_id"], outil=NOM_OUTIL,
        empreinte_arguments=idempotence.empreinte_arguments(arguments), statut="disponible",
        reponse=json.dumps(description, sort_keys=True),
    ))
    return {"ticket": token, "expire_le": (maintenant + dt.timedelta(seconds=TTL)).isoformat()}


def verifier(cnx: Any, politique: Mapping[str, Any], departement: str, token: str,
             arguments: Mapping[str, Any]) -> tuple[str, ...]:
    liaison_cibles._sqlite_uniquement(cnx)
    politique = valider_politique(politique)
    ligne = cnx.execute(select(LIAISONS_TICKETS).where(
        LIAISONS_TICKETS.c.ticket_hash == liaison_cibles.empreinte_ticket(token)
    )).mappings().one_or_none()
    if (ligne is None or ligne["outil"] != NOM_OUTIL or ligne["departement"] != departement
            or ligne["statut"] != "disponible" or ligne["demande_id"] is not None
            or ligne["empreinte_arguments"] != idempotence.empreinte_arguments(arguments)
            or dt.datetime.now(dt.UTC) >= dt.datetime.fromisoformat(ligne["expire_le"])):
        raise ValueError("MEMOIRE-TICKET-REFUSE: ticket invalide, expiré, consommé ou arguments différents")
    description = json.loads(ligne["reponse"] or "null")
    if (not isinstance(description, dict) or set(description) != {"purpose", "client_id", "politique_sha256"}
            or description["purpose"] != "memoire_client_v1"
            or description["politique_sha256"] != empreinte_politique(politique)
            or politique["agents"].get(ligne["agent_id"]) != {"departement": departement, "mode": "client_session"}):
        raise ValueError("MEMOIRE-TICKET-REFUSE: autorité serveur modifiée")
    active = _liaison(ligne["cle_session"])
    if (active["affaire_id"], active["ligne_id"]) != (ligne["affaire_id"], ligne["ligne_liaison_id"]):
        raise ValueError("MEMOIRE-LIAISON-MODIFIEE")
    client = _client(active["affaire_id"])
    if client != description["client_id"] or arguments.get("sujet") not in {None, f"client:{client}"}:
        raise ValueError("MEMOIRE-REFERENCE-CLIENT-MODIFIEE")
    return (f"client:{client}",)


def consommer(cnx: Any, token: str) -> None:
    resultat = cnx.execute(update(LIAISONS_TICKETS).where(
        LIAISONS_TICKETS.c.ticket_hash == liaison_cibles.empreinte_ticket(token),
        LIAISONS_TICKETS.c.outil == NOM_OUTIL, LIAISONS_TICKETS.c.statut == "disponible",
    ).values(statut="consomme", consomme_le=dt.datetime.now(dt.UTC).isoformat()))
    if resultat.rowcount != 1:
        raise ValueError("MEMOIRE-TICKET-DEJA-CONSOMME")


def outil_emission(cnx_factory: Callable[..., Any], departement: str,
                   politique_factory: Callable[[], dict[str, Any]]) -> Outil:
    def creer(agent_id: str, cle_session: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with cnx_factory() as cnx:
            ticket = emettre(cnx, politique_factory(), departement, agent_id, cle_session, arguments)
            verifier(cnx, politique_factory(), departement, ticket["ticket"], arguments)
            return ticket
    return Outil(nom=NOM_EMISSION, autonomie=Autonomie.T0, fonction=creer,
        description="Autorité privée de lecture mémoire client; réservée au contrôleur Core.",
        parametres={"type": "object", "properties": {
            "agent_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "cle_session": {"type": "string", "minLength": 1, "maxLength": 256},
            "arguments": {"type": "object"}},
            "required": ["agent_id", "cle_session", "arguments"], "additionalProperties": False})
