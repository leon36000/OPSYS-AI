"""Harnais des tests de bout en bout « appareil -> porte du core -> moteur MCP » (PLAN T1.5).

Le core (TypeScript) ne tourne pas dans le bac à sable : ce harnais prouve tout ce qui est À PARTIR
du moteur, par le vrai chemin réseau du moteur.

- Le moteur est la VRAIE application HTTP MCP (`opsys.serveur_mcp.application_http_departements`, avec
  son jeton, un point d'accès par département) sur un VRAI uvicorn, sur une base temporaire migrée,
  avec les dix départements réels.
- `PorteAppareil` refait, en Python, ce que fait la porte d'appareil du core pour un appel de l'app
  (`core/src/gateway/tools-invoke-shared.ts::invokeOpsysDeviceTool`) :
  1. autorise le nom NU de l'outil pour le rôle de l'appareil (`opsys/appareils.json`, `opsys/roles.json`,
     comme `opsys-device-roles.ts::authorizeOpsysDeviceTool`, fermé par défaut) ;
  2. prend le serveur MCP de l'outil dans `roles.json` (`serveurs`) et son URL dans `mcp.json`, jamais
     dans la requête ;
  3. ouvre une session MCP PRIVÉE à ce seul serveur (initialize, tools/list), vérifie que le serveur
     liste l'outil (sinon 404), appelle l'outil sous son nom brut avec le `_meta` que pose
     `buildOpsysMcpCallMeta` (`opsys/idempotencyKey`, `opsys/appareil`, `opsys/horodatageAppareil`
     seulement avec une clé ; `opsys/personne` et `opsys/role` pour un appareil authentifié) ;
  4. lit l'enveloppe OPSYS (`opsys-device-mcp-target.ts::readOpsysEnvelope` : un seul bloc texte, JSON, avec
     un booléen `ok`), et rend à l'app `{ok: true, result: <enveloppe>}` (HTTP 200) ou `{ok: false, error}`
     (403, 404 ou 500), comme `tools-invoke-http.ts`.
  Ce n'est PAS le core : c'est sa règle, relue dans le fork, appliquée au vrai moteur. Ce qui reste à
  prouver avec un core réel (poignée de main, jeton d'appareil, `mcp.servers` du core) est dit dans
  `docs/architecture/MOBILE.md`.
- Les personnes et les appareils sont créés par les commandes réelles du socle (`opsys-metier personnes creer`,
  `opsys-metier appareils appairer`), jamais par une écriture directe en base ; les fragments de configuration
  viennent de `opsys.openclaw.generer`, que `opsys-metier openclaw configurer` appelle.
- L'heure de réception du serveur (`recu_le`, celle qui fait foi pour la paie) vient d'une horloge de test
  (`Horloge`) : aucun sommeil, aucune dépendance à l'heure réelle quand l'heure métier compte.

Données fictives (AGENTS.md) : personnes, appareils, clés et identifiants portent « fictif ».
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import json
import socket
import threading
import time
import types
from collections import Counter
from pathlib import Path
from typing import Any

import anyio
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from sqlalchemy import func, select

from opsys import capacites as module_capacites
from opsys import cli, etat, openclaw, stockage
from opsys.departements import Departement, charger_departements
from opsys.serveur_mcp import application_http_departements
from opsys.stockage.schema import (
    APPROBATIONS,
    EVENEMENTS_RECUS,
    EVENEMENTS_SORTANTS,
    JOURNAL,
    MUTATIONS_APPLIQUEES,
    REGISTRES,
)

JETON_MCP = "jeton-mcp-e2e-t1-5-fictif-0123456789"
MOT_DE_PASSE = "mot-de-passe-e2e-fictif-1234"
PALIERS = {
    "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "standard": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"},
}
ENVIRON_EMBEDDINGS = {"OPSYS_EMBEDDINGS_URL": "http://embeddings-test:11434/v1",
                      "OPSYS_EMBEDDINGS_MODELE": "bge-m3"}
DT_TZ = dt.timezone(dt.timedelta(hours=-4))  # Québec, heure avancée


def iso(t: dt.datetime, decalage_s: int = 0) -> str:
    return (t + dt.timedelta(seconds=decalage_s)).isoformat()


# -- horloge du serveur ------------------------------------------------------------------------------
class Horloge:
    """Horloge de test du moteur : `Capacites._appeler_idempotent` lit `dt.datetime.now(dt.UTC)` pour
    l'heure de réception (`recu_le`), la seule qui fait foi pour un pointage d'appareil. On la remplace
    dans le module `opsys.capacites` par un module `dt` de substitution dont `datetime.now` rend
    l'heure du test. Le test l'avance à la main : ni sommeil ni heure réelle."""

    def __init__(self, debut: dt.datetime) -> None:
        self.maintenant = debut

    def avancer(self, **duree: float) -> dt.datetime:
        self.maintenant += dt.timedelta(**duree)
        return self.maintenant

    def installer(self, monkeypatch: Any) -> None:
        horloge = self

        class _DateHeure(dt.datetime):
            @classmethod
            def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:  # noqa: D102
                return horloge.maintenant.astimezone(tz) if tz is not None else horloge.maintenant.replace(
                    tzinfo=None)

        monkeypatch.setattr(module_capacites, "dt", types.SimpleNamespace(
            datetime=_DateHeure, UTC=dt.UTC, timedelta=dt.timedelta))


# -- mesures -----------------------------------------------------------------------------------------
@dataclasses.dataclass
class Mesure:
    """Ce qu'un appel de l'app a coûté, du côté du moteur."""

    outil: str
    statut: int
    duree_s: float
    requetes_http: int
    messages_mcp: dict[str, int]  # par méthode JSON-RPC envoyée par le client
    octets_texte: int  # taille du bloc texte de l'enveloppe rendue par le moteur
    tronque: bool  # `Capacites._tronquer` a coupé la sortie (au-delà de 6 000 caractères)
    rejoue: bool | None


@dataclasses.dataclass
class Reponse:
    """Ce que l'app reçoit de `/tools/invoke`."""

    statut: int
    corps: dict[str, Any]
    mesure: Mesure

    @property
    def ok(self) -> bool:
        return self.corps.get("ok") is True

    @property
    def enveloppe(self) -> dict[str, Any]:
        """L'enveloppe OPSYS `{ok, resultat | erreur, rejoue}` que l'app lit (`corps.result`)."""
        assert self.ok, self.corps
        return self.corps["result"]

    @property
    def metier(self) -> Any:
        """Le résultat métier : `{accepte, resultat | verdict}` (patron `depuis_couple`) pour une écriture,
        la valeur lue telle quelle pour un outil de lecture (T0)."""
        env = self.enveloppe
        assert env.get("ok") is True, env
        return env["resultat"]

    @property
    def resultat(self) -> Any:
        """La donnée utile : `resultat` d'une écriture acceptée, ou la lecture elle-même. Un refus métier
        (`accepte: false`) fait échouer le test, avec son verdict."""
        m = self.metier
        if isinstance(m, dict) and "accepte" in m:
            assert m["accepte"] is True, m
            return m["resultat"]
        return m


def _serveur_http(app: Any, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    for _ in range(200):
        if serveur.started:
            return serveur, fil
        time.sleep(0.05)
    raise RuntimeError("le serveur MCP de test n'a pas démarré")


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# -- la porte d'appareil -----------------------------------------------------------------------------
class PorteAppareil:
    """Un appareil appairé vu du moteur : `appeler` = un `POST /tools/invoke` de l'app."""

    def __init__(self, moteur: Moteur, appareil_id: str) -> None:
        self._moteur = moteur
        self.appareil_id = appareil_id

    def appeler(
        self, outil: str, args: dict[str, Any] | None = None, *, cle: str | None = None,
        horodatage_appareil: str | None = None,
    ) -> Reponse:
        return self._moteur.invoquer(self.appareil_id, outil, args or {}, cle, horodatage_appareil)


class Moteur:
    """Le moteur réel : base migrée, dix départements, application HTTP MCP sur un vrai uvicorn, fragments
    de configuration du core, et la table des mesures de tous les appels."""

    def __init__(self, dossier: Path, url_base: str) -> None:
        self.dossier = dossier
        self.url_base = url_base
        self.config_dir = dossier / "config-core"
        self.mesures: list[Mesure] = []
        self.departements: dict[str, Departement] = charger_departements()
        self._serveur: uvicorn.Server | None = None
        self._fil: threading.Thread | None = None
        self.port = 0

    # -- cycle de vie ----------------------------------------------------------------------------
    def demarrer(self) -> None:
        self.port = _port_libre()
        app = application_http_departements(self.departements, etat.session, JETON_MCP, hote="127.0.0.1")
        self._serveur, self._fil = _serveur_http(app, self.port)
        openclaw.generer(self.departements, self.config_dir, PALIERS, url_mcp=f"http://127.0.0.1:{self.port}/mcp",
                         environ=ENVIRON_EMBEDDINGS)

    def arreter(self) -> None:
        if self._serveur is not None:
            self._serveur.should_exit = True
        if self._fil is not None:
            self._fil.join(timeout=10)

    # -- personnes et appareils : les commandes réelles du socle -----------------------------------------
    def creer_personne(self, identifiant: str, nom: str, roles: list[str], monkeypatch: Any) -> None:
        monkeypatch.setenv(cli.ENV_MOT_DE_PASSE_PERSONNE, MOT_DE_PASSE)
        argv = ["personnes", "creer", identifiant, "--nom", nom]
        for role in roles:
            argv += ["--role", role]
        assert cli.main(argv) == 0

    def appairer(self, personne: str, role: str) -> PorteAppareil:
        appareil_id = hashlib.sha256(f"appareil-{personne}-{role}-fictif".encode()).hexdigest()
        assert cli.main(["appareils", "appairer", appareil_id, "--personne", personne, "--role", role,
                         "--config-dir", str(self.config_dir)]) == 0
        return PorteAppareil(self, appareil_id)

    # -- la règle de la porte d'appareil du core ---------------------------------------------------------
    def _fragment(self, nom: str) -> dict[str, Any]:
        try:
            return json.loads((self.config_dir / "opsys" / nom).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}  # fermé par défaut : un fragment illisible n'autorise rien (opsys-device-roles.ts)

    def _autoriser(self, appareil_id: str, outil: str) -> tuple[dict[str, str] | None, str | None]:
        appareil = (self._fragment("appareils.json").get("appareils") or {}).get(appareil_id)
        if not appareil or not appareil.get("personne") or not appareil.get("role"):
            return None, "device_unknown"
        roles = self._fragment("roles.json")
        permis = (roles.get("roles") or {}).get(appareil["role"])
        if permis is None:
            return None, "role_unknown"
        if outil not in permis:
            return None, "tool_out_of_scope"
        serveur = (roles.get("serveurs") or {}).get(outil)
        if not serveur:
            return None, "server_unknown"
        return {"personne": appareil["personne"], "role": appareil["role"], "serveur": serveur}, None

    def invoquer(
        self, appareil_id: str, outil: str, args: dict[str, Any], cle: str | None,
        horodatage_appareil: str | None,
    ) -> Reponse:
        debut = time.perf_counter()
        identite, refus = self._autoriser(appareil_id, outil)
        if identite is None:
            corps = {"ok": False, "error": {
                "type": "tool_call_blocked",
                "message": f'OPSYS device is not authorized to call "{outil}" ({refus}).'}}
            return Reponse(403, corps, Mesure(outil, 403, time.perf_counter() - debut, 0, {}, 0, False, None))
        serveur = self._fragment("mcp.json")["servers"][identite["serveur"]]
        url = serveur["url"]
        # Comme le core : les variables `${...}` de la configuration sont substituées (le jeton du moteur), et
        # `requestTimeoutMs` borne chaque requête MCP.
        entetes = {nom: valeur.replace("${OPSYS_MCP_JETON}", JETON_MCP) for nom, valeur in serveur["headers"].items()}
        delai = serveur["requestTimeoutMs"] / 1000
        meta: dict[str, Any] = {}
        if cle is not None:  # buildOpsysMcpCallMeta : la clé d'abord, l'appareil et l'heure avec elle
            meta["opsys/idempotencyKey"] = cle
            meta["opsys/appareil"] = appareil_id
            if horodatage_appareil is not None:
                meta["opsys/horodatageAppareil"] = horodatage_appareil
        meta["opsys/personne"] = identite["personne"]
        meta["opsys/role"] = identite["role"]

        compteur: Counter[str] = Counter()
        requetes_http = 0

        async def _crochet(requete: Any) -> None:
            nonlocal requetes_http
            requetes_http += 1
            if requete.method == "POST" and requete.content:
                with contextlib.suppress(ValueError):
                    compteur[json.loads(requete.content).get("method", "reponse")] += 1

        async def _session() -> tuple[str, Any]:
            client_http = create_mcp_http_client(headers=entetes)
            client_http.event_hooks["request"].append(_crochet)
            async with (client_http, streamable_http_client(url, http_client=client_http) as flux,
                        ClientSession(flux[0], flux[1]) as session_mcp):
                await session_mcp.initialize()
                catalogue = await session_mcp.list_tools()
                if outil not in {t.name for t in catalogue.tools}:
                    return "absent", None
                return "ok", await session_mcp.call_tool(outil, args, read_timeout_seconds=delai, meta=meta)

        issue, resultat = anyio.run(_session)
        if issue == "absent":
            corps = {"ok": False, "error": {"type": "not_found", "message": f"Tool not available: {outil}"}}
            return self._rendre(outil, 404, corps, debut, requetes_http, compteur, 0, False, None)
        blocs = resultat.content
        texte = blocs[0].text if len(blocs) == 1 and getattr(blocs[0], "type", None) == "text" else None
        try:
            enveloppe = json.loads(texte) if texte is not None else None
        except ValueError:
            enveloppe = None
        if not isinstance(enveloppe, dict) or not isinstance(enveloppe.get("ok"), bool):
            corps = {"ok": False, "error": {"type": "tool_error", "message": "tool execution failed"}}
            return self._rendre(outil, 500, corps, debut, requetes_http, compteur, len(texte or ""), False, None)
        corps = {"ok": True, "result": enveloppe}
        return self._rendre(outil, 200, corps, debut, requetes_http, compteur, len(texte),
                            enveloppe.get("tronque") is True, enveloppe.get("rejoue"))

    def _rendre(self, outil: str, statut: int, corps: dict[str, Any], debut: float, requetes_http: int,
                compteur: Counter[str], octets: int, tronque: bool, rejoue: bool | None) -> Reponse:
        mesure = Mesure(outil, statut, time.perf_counter() - debut, requetes_http, dict(compteur), octets,
                        tronque, rejoue)
        self.mesures.append(mesure)
        return Reponse(statut, corps, mesure)

    # -- le bus : livraison explicite, sans sommeil ------------------------------------------------------
    def drainer_bus(self, depuis: dt.datetime, *, max_tours: int = 15, pas_s: int = 90) -> dict[str, int]:
        """Répartiteur réel (`evenements.repartir`, tous les départements) jusqu'au repos, borné. Le
        répartiteur de fond du serveur est éteint (`OPSYS_EVENEMENTS_REPARTITEUR=0`) : la livraison
        est déterministe, et l'heure des réessais vient du test."""
        from opsys import evenements

        t = depuis
        total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
        for _ in range(max_tours):
            resume = evenements.repartir(self.departements, maintenant=iso(t))
            for cle in total:
                total[cle] += resume[cle]
            if resume["livres"] == 0:
                return total
            t += dt.timedelta(seconds=pas_s)
        raise AssertionError(f"le bus n'a pas atteint le repos après {max_tours} tours : {total}")

    # -- instantané de l'état durable : « aucun double effet » ------------------------------------------
    def empreinte_etat(self) -> dict[str, Any]:
        """Ce qu'un rejeu ne doit JAMAIS changer : maillons de chaque registre de département, événements
        publiés et reçus, demandes d'approbation, journal d'audit."""
        with stockage.transaction() as cnx:
            registres = {
                f"{ligne.departement}/{ligne.registre}": ligne.n
                for ligne in cnx.execute(select(REGISTRES.c.departement, REGISTRES.c.registre,
                                                func.count().label("n"))
                                         .group_by(REGISTRES.c.departement, REGISTRES.c.registre))
            }
            return {
                "registres": registres,
                "evenements_sortants": cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one(),
                "evenements_recus": cnx.execute(select(func.count()).select_from(EVENEMENTS_RECUS)).scalar_one(),
                "approbations": cnx.execute(select(func.count()).select_from(APPROBATIONS)).scalar_one(),
                "journal": cnx.execute(select(func.count()).select_from(JOURNAL)).scalar_one(),
                "mutations": cnx.execute(select(func.count()).select_from(MUTATIONS_APPLIQUEES)).scalar_one(),
            }

    # -- synthèse ----------------------------------------------------------------------------------------
    def bilan(self, depuis: int = 0, jusqu_a: int | None = None) -> dict[str, Any]:
        """Nombre d'appels, de requêtes, durée cumulée et troncatures des mesures `[depuis, jusqu_a[`."""
        mesures = self.mesures[depuis:jusqu_a]
        messages: Counter[str] = Counter()
        par_outil: dict[str, list[float]] = {}
        for m in mesures:
            messages.update(m.messages_mcp)
            par_outil.setdefault(m.outil, []).append(m.duree_s)
        return {
            "appels_app": len(mesures),
            "requetes_http": sum(m.requetes_http for m in mesures),
            "messages_mcp": dict(messages),
            "duree_appels_s": round(sum(m.duree_s for m in mesures), 3),
            "moyenne_par_appel_s": round(sum(m.duree_s for m in mesures) / len(mesures), 3) if mesures else 0.0,
            "plus_lent": max(((round(m.duree_s, 3), m.outil) for m in mesures), default=(0.0, "")),
            "par_outil_ms": {nom: round(1000 * sum(v) / len(v)) for nom, v in sorted(par_outil.items())},
            "troncatures": [m.outil for m in mesures if m.tronque],
            "octets_max": max(((m.octets_texte, m.outil) for m in mesures), default=(0, "")),
        }
