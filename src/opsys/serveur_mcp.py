"""Serveur MCP OPSYS : expose les capacités des départements à tout moteur d'agents MCP.

OPSYS-CORE (OpenClaw) s'y connecte en HTTP « streamable » sur le réseau interne :

    mcp.servers.opsys = {url: "http://opsys:8765/mcp", transport: "streamable-http",
                         headers: {Authorization: "Bearer ${OPSYS_MCP_JETON}"}}

Le mode stdio reste disponible (Hermes, Claude Code, tests). MCP est l'interface stable
entre le métier et le moteur d'agents : les départements ne dépendent d'aucun runtime.
"""

from __future__ import annotations

import argparse
import contextlib
import hmac
import json
import os
from collections.abc import Mapping
from typing import Any

import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from . import __version__, contexte, etat, evenements, idempotence, stockage
from .capacites import Capacites
from .departements import Departement, charger_departements
from .outils import Autonomie

ENV_REPARTITEUR = "OPSYS_EVENEMENTS_REPARTITEUR"
_INTERVALLE_REPARTITEUR_S = 3.0
_DESACTIVE = {"0", "false", "non", "off"}

_ANNOTATIONS = {
    Autonomie.T0: types.ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True),
    Autonomie.T1: types.ToolAnnotations(read_only_hint=False, destructive_hint=False),
    Autonomie.T2: types.ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True),
    Autonomie.T3: types.ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True),
}


def creer_serveur(capacites: Capacites) -> Server[Any]:
    async def lister_outils(ctx: Any, params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
        del ctx, params
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=outil.nom,
                    description=outil.description,
                    inputSchema=dict(outil.parametres),
                    annotations=_ANNOTATIONS[outil.autonomie],
                )
                for outil in capacites.lister()
            ]
        )

    async def appeler_outil(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        del ctx
        # Idempotence d'appareil (T1.4-b) : clé et identité voyagent dans le `_meta` MCP de
        # `tools/call`, jamais dans les arguments que le modèle produit (contrat complet :
        # docs/architecture/IDEMPOTENCE.md). Sans `opsys/idempotencyKey`, `meta` est None et
        # `Capacites.appeler` se comporte exactement comme avant T1.4-b.
        try:
            meta = idempotence.depuis_meta_mcp(params.meta)
        except ValueError as exc:
            reponse: dict[str, Any] = {"ok": False, "erreur": "meta_invalide", "details": str(exc)}
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(reponse, ensure_ascii=False))],
                isError=True,
            )
        # Identité de jeton d'appareil (T1.4-c2) : `opsys/personne`/`opsys/role`, transmis par
        # OPSYS-CORE (qui a déjà refusé un outil hors de la portée du rôle avant d'émettre cet
        # appel) — un appel sans ces clés (Hermes, Claude Code, un outil interne) rend None, sans
        # erreur (docs/architecture/IDEMPOTENCE.md §7 bis). Aucun outil de département ne lit encore
        # `contexte.identite_appelante()` (M3 reste à adapter, tâche séparée) ; l'exposer ici ne
        # change donc le comportement d'aucun outil existant.
        identite = contexte.depuis_meta_mcp_identite(params.meta)
        with contexte.appele_par_appareil(identite):
            reponse = await anyio.to_thread.run_sync(
                capacites.appeler, params.name, params.arguments or {}, meta
            )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(reponse, ensure_ascii=False))],
            isError=not reponse.get("ok", False),
        )

    noms = ", ".join(sorted(d.code for d in capacites.departements.values()))
    return Server(
        "opsys",
        version=__version__,
        instructions=(
            f"Capacités OPSYS des départements {noms}. Les outils calculent : ne jamais inventer "
            "un prix, un solde, un score ou une date. Une réponse 'en_attente_approbation' signifie "
            "que l'action n'est PAS faite tant qu'un humain ne l'a pas approuvée."
        ),
        on_list_tools=lister_outils,
        on_call_tool=appeler_outil,
    )


async def _servir(capacites: Capacites) -> None:
    serveur = creer_serveur(capacites)
    async with stdio_server() as (lecture, ecriture):
        await serveur.run(lecture, ecriture, serveur.create_initialization_options())


class _ExigerJeton:
    """Middleware ASGI : refuse toute requête HTTP sans `Authorization: Bearer <jeton>`."""

    def __init__(self, application: Any, jeton: str) -> None:
        self._application = application
        self._attendu = f"Bearer {jeton}".encode()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            entetes = dict(scope.get("headers") or [])
            if not hmac.compare_digest(entetes.get(b"authorization", b""), self._attendu):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"erreur":"jeton MCP invalide"}'})
                return
        await self._application(scope, receive, send)


def application_http(capacites: Capacites, jeton: str, hote: str = "0.0.0.0") -> Any:  # noqa: S104
    """Application ASGI MCP « streamable HTTP » protégée par jeton (un seul point d'accès /mcp)."""
    if len(jeton) < 24:
        raise ValueError("OPSYS_MCP_JETON doit faire au moins 24 caractères")
    serveur = creer_serveur(capacites)
    return _ExigerJeton(serveur.streamable_http_app(streamable_http_path="/mcp", host=hote), jeton)


def _repartiteur_desactive() -> bool:
    return os.environ.get(ENV_REPARTITEUR, "1").strip().lower() in _DESACTIVE


async def _boucle_repartiteur(
    departements: Mapping[str, Departement], intervalle: float = _INTERVALLE_REPARTITEUR_S
) -> None:
    """Appelle `evenements.repartir` en boucle (sondage de secours, ADR-0009 §3), jusqu'à l'annulation
    de la portée qui l'a lancée (arrêt propre : le prochain réveil, sommeil compris, est interrompu)."""
    while True:
        await anyio.to_thread.run_sync(evenements.repartir, departements)
        await anyio.sleep(intervalle)


def application_http_departements(
    departements: Mapping[str, Departement], cnx_factory: Any, jeton: str, hote: str = "0.0.0.0",  # noqa: S104
) -> Any:
    """Un point d'accès MCP par département, `/mcp/<id>`, plus `/mcp` pour la direction.

    L'appel est attribué au département du chemin : ses outils, et les outils communs exécutés
    en son nom (mémoire cloisonnée, budget, approbations). `/mcp` expose tous les outils des
    départements, mais refuse les outils communs au-delà de la lecture (appelant inconnu).
    """
    if len(jeton) < 24:
        raise ValueError("OPSYS_MCP_JETON doit faire au moins 24 caractères")
    from starlette.applications import Starlette

    sous_applications = [
        creer_serveur(Capacites(departements, cnx_factory, filtre={ident}, appelant=ident))
        .streamable_http_app(streamable_http_path=f"/mcp/{ident}", host=hote)
        for ident in departements
    ]
    sous_applications.append(
        creer_serveur(Capacites(departements, cnx_factory)).streamable_http_app(streamable_http_path="/mcp",
                                                                                host=hote)
    )

    @contextlib.asynccontextmanager
    async def cycle_de_vie(_: Any) -> Any:
        async with contextlib.AsyncExitStack() as pile:
            for sous in sous_applications:
                await pile.enter_async_context(sous.router.lifespan_context(sous))
            if _repartiteur_desactive():
                yield
            else:
                async with anyio.create_task_group() as taches:
                    taches.start_soon(_boucle_repartiteur, departements)
                    yield
                    taches.cancel_scope.cancel()  # arrêt propre : la boucle est interrompue puis attendue

    routes = [route for sous in sous_applications for route in sous.routes]
    return _ExigerJeton(Starlette(routes=routes, lifespan=cycle_de_vie), jeton)


def main(argv: list[str] | None = None) -> None:
    parseur = argparse.ArgumentParser(prog="opsys-mcp", description="Serveur MCP des départements OPSYS")
    parseur.add_argument("--departement", action="append", default=[],
                         help="id du département à exposer (répétable ; défaut : tous)")
    parseur.add_argument("--http", action="store_true", help="HTTP streamable au lieu de stdio")
    parseur.add_argument("--hote", default="0.0.0.0")  # noqa: S104 — réseau interne docker
    parseur.add_argument("--port", type=int, default=8765)
    args = parseur.parse_args(argv)
    stockage.migrer()  # base de l'instance à jour avant le premier appel d'outil (ADR-0009)
    departements = charger_departements()
    if not args.http:
        appelant = args.departement[0] if len(args.departement) == 1 else None
        anyio.run(_servir, Capacites(departements, etat.session, filtre=set(args.departement) or None,
                                     appelant=appelant))
        return
    jeton = os.environ.get("OPSYS_MCP_JETON", "")
    import uvicorn

    application = application_http_departements(departements, etat.session, jeton, args.hote)
    uvicorn.run(application, host=args.hote, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
