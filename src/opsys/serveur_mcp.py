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
import logging
import os
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC
from functools import partial
from typing import Any

import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from . import __version__, contexte, etat, evenements, idempotence, liaison_cibles, stockage
from .capacites import Capacites
from .departements import Departement, charger_departements
from .memoire import autorite as autorite_memoire
from .outils import Autonomie
from .stockage import base_cron_operateur

ENV_REPARTITEUR = "OPSYS_EVENEMENTS_REPARTITEUR"
_INTERVALLE_REPARTITEUR_S = 3.0
_DESACTIVE = {"0", "false", "non", "off"}

_ANNOTATIONS = {
    Autonomie.T0: types.ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True),
    Autonomie.T1: types.ToolAnnotations(read_only_hint=False, destructive_hint=False),
    Autonomie.T2: types.ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True),
    Autonomie.T3: types.ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True),
}


def creer_serveur(
    capacites: Capacites,
    *,
    outils_permis: frozenset[str] | None = None,
    outils_caches: frozenset[str] = frozenset(),
) -> Server[Any]:
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
                if outils_permis is None or outil.nom in outils_permis
                if outil.nom not in outils_caches
            ]
        )

    async def appeler_outil(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        del ctx
        if (outils_permis is not None and params.name not in outils_permis) or params.name in outils_caches:
            reponse = {"ok": False, "erreur": "outil_inconnu", "details": params.name}
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(reponse, ensure_ascii=False))],
                isError=True,
            )
        # Idempotence d'appareil (T1.4-b) : clé et identité voyagent dans le `_meta` MCP de
        # `tools/call`, jamais dans les arguments que le modèle produit (contrat complet :
        # docs/architecture/IDEMPOTENCE.md). Sans `opsys/idempotencyKey`, `meta` est None ;
        # une identité d'appareil ne peut alors appeler qu'une lecture T0/N0.
        try:
            meta = idempotence.depuis_meta_mcp(params.meta)
            ticket_cible = liaison_cibles.depuis_meta_mcp(params.meta)
            ticket_memoire = autorite_memoire.meta_ticket(params.meta)
            meta_brute = params.meta if isinstance(params.meta, dict) else {}
            ticket_cfo = meta_brute.get("opsys/cfoGrantTicket")
            profile_id = meta_brute.get("opsys/runtimeProfileId")
            profile_revision_raw = meta_brute.get("opsys/runtimeProfileRevision")
            profile_server = meta_brute.get("opsys/runtimeServer")
            profile_binding = None
            if profile_id is not None or profile_revision_raw is not None or profile_server is not None:
                if (
                    not isinstance(profile_id, str)
                    or not profile_id
                    or len(profile_id) > 64
                    or not isinstance(profile_revision_raw, str)
                    or not profile_revision_raw.isascii()
                    or not profile_revision_raw.isdigit()
                    or len(profile_revision_raw) > 16
                    or not isinstance(profile_server, str)
                    or len(profile_server) > 32
                ):
                    raise ValueError("liaison de profil runtime mal formée")
                profile_revision = int(profile_revision_raw)
                if not 1 <= profile_revision <= 9_007_199_254_740_991:
                    raise ValueError("liaison de profil runtime mal formée")
                profile_binding = (profile_id, profile_revision, profile_server)
            if ticket_cfo is not None and (not isinstance(ticket_cfo, str) or len(ticket_cfo) > 256):
                raise ValueError("ticket CFO mal formé")
        except ValueError as exc:
            reponse: dict[str, Any] = {"ok": False, "erreur": "meta_invalide", "details": str(exc)}
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(reponse, ensure_ascii=False))],
                isError=True,
            )
        # Identité de jeton d'appareil (T1.4-c2) : `opsys/personne`/`opsys/role`, transmis par
        # OPSYS-CORE (qui a déjà refusé un outil hors de la portée du rôle avant d'émettre cet
        # appel) — un appel sans ces clés (Hermes, Claude Code, un outil interne) rend None, sans
        # erreur (docs/architecture/IDEMPOTENCE.md §7 bis). M3 s'en sert pour choisir la vue d'un
        # devis ou d'une estimation (PLAN T2.3-c) : le rôle authentifié décide, le paramètre `role`
        # ne peut que restreindre.
        identite = contexte.depuis_meta_mcp_identite(params.meta)
        if ticket_cfo is not None and (
            params.name not in {"m5_preparer_dossier_decision_cfo", "m5_preparer_decision_capital"}
            or capacites.appelant is None
            or capacites.appelant.id != "m05-financecore"
            or identite is not None
        ):
            reponse = {"ok": False, "erreur": "ticket_cfo_hors_portee"}
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(reponse, ensure_ascii=False))],
                isError=True,
            )
        if (
            params.name in {"m5_preparer_dossier_decision_cfo", "m5_preparer_decision_capital"}
            and ticket_cfo is None
            and identite is None
        ):
            reponse = {"ok": False, "erreur": "autorisation_cfo_requise"}
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(reponse, ensure_ascii=False))],
                isError=True,
            )
        if profile_binding is not None and identite is not None:
            reponse = {"ok": False, "erreur": "admission_profil_refusee", "details": "appel humain profilé"}
        else:
            with (
                contexte.appele_par_appareil(identite),
                contexte.appele_avec_ticket_agent_cfo(ticket_cfo, params.arguments or {}),
            ):
                if profile_binding is None:
                    reponse = await anyio.to_thread.run_sync(
                        capacites.appeler, params.name, params.arguments or {}, meta, ticket_cible, ticket_memoire
                    )
                else:
                    profile_id, profile_revision, profile_server = profile_binding
                    reponse = await anyio.to_thread.run_sync(
                        partial(
                            capacites.appeler_profil_runtime,
                            params.name,
                            params.arguments or {},
                            meta,
                            ticket_cible,
                            profile_id=profile_id,
                            profile_revision=profile_revision,
                            server=profile_server,
                            ticket_memoire=ticket_memoire,
                        )
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


CHEMIN_SANTE = "/sante"
CHEMIN_CONTEXTE_PREFIXE = "/mcp/contexte/"
CHEMIN_RUNTIME_PREFIXE = "/mcp/runtime/"
CHEMIN_CRON_OPERATEUR_PREFIXE = "/cron-operateur/v1/"
ENV_CRON_OPERATEUR_JETON = "OPSYS_CRON_OPERATEUR_JETON"
_CRON_OPERATEUR_MAX_OCTETS = 20 * 1024
_REPONSE_SANTE = json.dumps({"statut": "ok", "service": "opsys-metier"}).encode()


async def _repondre_sante(scope: dict[str, Any], send: Any) -> None:
    """Point de santé du moteur : vivant si le serveur répond. Aucune donnée métier, aucun jeton.

    Le superviseur du core (PLAN T0.10) le sonde en boucle ; il ne prouve que la vie du processus
    HTTP, jamais l'état d'un département. Seuls GET et HEAD sont permis.
    """
    entetes = [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]
    methode = scope.get("method", "GET")
    if methode not in ("GET", "HEAD"):
        await send({"type": "http.response.start", "status": 405, "headers": [*entetes, (b"allow", b"GET, HEAD")]})
        await send({"type": "http.response.body", "body": b'{"erreur":"methode non permise"}'})
        return
    await send({"type": "http.response.start", "status": 200, "headers": entetes})
    await send({"type": "http.response.body", "body": b"" if methode == "HEAD" else _REPONSE_SANTE})


class _SansAccesSante(logging.Filter):
    """Retire du journal d'accès d'uvicorn les sondes `GET /sante` : sondées en boucle par le
    superviseur du core, elles noieraient le journal unifié sans rien dire."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Arguments d'uvicorn.access : (client, méthode, chemin avec requête, version HTTP, statut).
        arguments = record.args
        if isinstance(arguments, tuple) and len(arguments) >= 3:
            return arguments[2] != CHEMIN_SANTE
        return True


class _ExigerJeton:
    """Middleware ASGI : refuse toute requête HTTP sans `Authorization: Bearer <jeton>`.

    Seule exception : `GET /sante`, sonde de vie sans donnée métier (`_repondre_sante`).
    """

    def __init__(
        self,
        application: Any,
        jeton: str,
        jeton_contexte: str | None = None,
        jeton_cron_operateur: str | None = None,
    ) -> None:
        self._application = application
        self._attendu = f"Bearer {jeton}".encode()
        self._attendu_contexte = f"Bearer {jeton_contexte}".encode() if jeton_contexte else None
        self._attendu_cron_operateur = (
            f"Bearer {jeton_cron_operateur}".encode() if jeton_cron_operateur else None
        )

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        chemin = scope.get("path", "")

        async def envoyer(message: dict[str, Any]) -> None:
            if (scope["type"] == "http" and chemin.startswith(CHEMIN_CRON_OPERATEUR_PREFIXE)
                    and message.get("type") == "http.response.start"):
                entetes = list(message.get("headers", []))
                if not any(cle.lower() == b"cache-control" for cle, _ in entetes):
                    entetes.append((b"cache-control", b"no-store"))
                message = {**message, "headers": entetes}
            await send(message)

        if scope["type"] == "http":
            if scope.get("path") == CHEMIN_SANTE:
                await _repondre_sante(scope, envoyer)
                return
            if chemin.startswith(CHEMIN_CRON_OPERATEUR_PREFIXE) and self._attendu_cron_operateur is None:
                await envoyer({"type": "http.response.start", "status": 404,
                               "headers": [(b"content-type", b"application/json")]})
                await envoyer({"type": "http.response.body", "body": b'{"erreur":"not found"}'})
                return
            entetes = dict(scope.get("headers") or [])
            attendu = self._attendu
            if chemin.startswith(CHEMIN_CRON_OPERATEUR_PREFIXE):
                attendu = self._attendu_cron_operateur or b""
                if sum(cle.lower() == b"authorization" for cle, _ in scope.get("headers", [])) != 1:
                    attendu = b""
            elif chemin.startswith((CHEMIN_CONTEXTE_PREFIXE, CHEMIN_RUNTIME_PREFIXE)):
                attendu = self._attendu_contexte or b""
            if not attendu or not hmac.compare_digest(entetes.get(b"authorization", b""), attendu):
                await envoyer(
                    {"type": "http.response.start", "status": 401,
                     "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]}
                )
                await envoyer({"type": "http.response.body", "body": b'{"erreur":"jeton MCP invalide"}'})
                return
        await self._application(scope, receive, envoyer)


def application_http(capacites: Capacites, jeton: str, hote: str = "0.0.0.0") -> Any:  # noqa: S104
    """Application ASGI MCP « streamable HTTP » protégée par jeton (un seul point d'accès /mcp)."""
    if len(jeton) < 24:
        raise ValueError("OPSYS_MCP_JETON doit faire au moins 24 caractères")
    # L'ancien agrégat HTTP ne peut conserver le mode interne sans classification persistante.
    if capacites._memoire_politique is None:
        capacites._memoire_politique = autorite_memoire.lire_politique
    capacites._memoire_versionnee = False
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
    departements: Mapping[str, Departement],
    cnx_factory: Any,
    jeton: str,
    hote: str = "0.0.0.0",  # noqa: S104
    *,
    jeton_contexte: str | None = None,
    memoire_politique: Any = None,
) -> Any:
    """Un point d'accès MCP par département, `/mcp/<id>`, plus `/mcp` pour la direction.

    L'appel est attribué au département du chemin : ses outils, et les outils communs exécutés
    en son nom (mémoire cloisonnée, budget, approbations). `/mcp` expose tous les outils des
    départements, mais refuse les outils communs au-delà de la lecture (appelant inconnu).
    """
    if len(jeton) < 24:
        raise ValueError("OPSYS_MCP_JETON doit faire au moins 24 caractères")
    if jeton_contexte is not None and len(jeton_contexte) < 24:
        raise ValueError("OPSYS_CONTEXT_MCP_JETON doit faire au moins 24 caractères")
    if jeton_contexte is not None and hmac.compare_digest(jeton, jeton_contexte):
        raise ValueError("OPSYS_CONTEXT_MCP_JETON doit être distinct de OPSYS_MCP_JETON")
    jeton_cron_operateur = os.environ.get(ENV_CRON_OPERATEUR_JETON, "") or None
    identite_base_cron: tuple[str, str, tuple[tuple[str, Any], ...]] | None = None
    if jeton_cron_operateur is not None:
        if len(jeton_cron_operateur) < 24:
            raise ValueError(f"{ENV_CRON_OPERATEUR_JETON} doit faire au moins 24 caractères")
        if hmac.compare_digest(jeton, jeton_cron_operateur) or (
            jeton_contexte is not None and hmac.compare_digest(jeton_contexte, jeton_cron_operateur)
        ):
            raise ValueError(f"{ENV_CRON_OPERATEUR_JETON} doit être distinct des jetons MCP")
        identite_base_cron = _verifier_base_cron_operateur(cnx_factory)
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    politique_factory = memoire_politique or autorite_memoire.lire_politique
    sous_applications = [
        creer_serveur(
            Capacites(departements, cnx_factory, filtre={ident}, appelant=ident,
                      memoire_politique=politique_factory, memoire_versionnee=versionnee),
            outils_caches=frozenset({"m10_paquet_contexte_affaire", "opsys_contexte_creer_ticket_cible",
                                     autorite_memoire.NOM_EMISSION}),
        ).streamable_http_app(streamable_http_path=f"/mcp/{'v1/' if versionnee else ''}{ident}", host=hote)
        for ident in departements for versionnee in (False, True)
    ]
    outil_ticket_cible = "opsys_contexte_creer_ticket_cible"
    if jeton_contexte:
        if "m10-memoire" not in departements:
            raise ValueError("le département m10-memoire est requis pour le contexte d'entreprise")
        for ident in departements:
            prive = Capacites(departements, cnx_factory, filtre={"m10-memoire"}, appelant=ident)
            outil_ticket = liaison_cibles.outil_emission(cnx_factory, ident)
            prive.index[outil_ticket.nom] = (None, outil_ticket)
            lecture = autorite_memoire.outil_emission(cnx_factory, ident, politique_factory)
            prive.index[lecture.nom] = (None, lecture)
            sous_applications.append(
                creer_serveur(
                    prive,
                    outils_permis=frozenset({
                        "m10_paquet_contexte_affaire", outil_ticket_cible, autorite_memoire.NOM_EMISSION,
                    }),
                ).streamable_http_app(streamable_http_path=f"{CHEMIN_CONTEXTE_PREFIXE}{ident}", host=hote)
            )
    if jeton_contexte:
        # Route profile-bound: the model can never nominate an agent identity in MCP arguments.
        # Admission tools are private runtime plumbing and are never included in any department
        # catalogue or agent tool allow list.
        from . import agents as profils_configurables

        with cnx_factory() as cnx:
            from sqlalchemy import inspect

            profils = profils_configurables.lister(cnx) if inspect(cnx).has_table("agents_configurables") else []
        for profil in profils:
            ident = profil["id"]
            sous_applications.append(
                _creer_serveur_admission(departements, cnx_factory, ident).streamable_http_app(
                    streamable_http_path=f"{CHEMIN_RUNTIME_PREFIXE}{ident}", host=hote
                )
            )
    sous_applications.append(
        creer_serveur(
            Capacites(departements, cnx_factory, memoire_politique=politique_factory),
            outils_caches=frozenset({"m10_paquet_contexte_affaire", "opsys_contexte_creer_ticket_cible"}),
        ).streamable_http_app(streamable_http_path="/mcp", host=hote)
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
    if jeton_cron_operateur is not None:
        async def appel_cron_operateur(request: Any) -> Any:
            from . import agents_cron_autorite

            async def erreur(code: str, statut: int) -> Any:
                return JSONResponse({"ok": False, "erreur": code}, status_code=statut,
                                    headers={"Cache-Control": "no-store"})

            async def lire_objet(champs: frozenset[str]) -> dict[str, Any] | None:
                entetes = request.headers
                if any(len(entetes.getlist(nom)) > 1 for nom in (
                    "content-type", "content-length", "transfer-encoding", "content-encoding",
                )):
                    return None
                if entetes.get("content-type", "").lower() not in {
                    "application/json", "application/json; charset=utf-8",
                } or entetes.get("transfer-encoding") is not None or entetes.get("content-encoding") is not None:
                    return None
                longueur = entetes.get("content-length")
                if longueur is not None and (len(longueur) > 5 or not longueur.isascii() or not longueur.isdigit()
                                              or int(longueur) > _CRON_OPERATEUR_MAX_OCTETS):
                    return None
                morceaux = bytearray()
                async for fragment in request.stream():
                    if len(morceaux) + len(fragment) > _CRON_OPERATEUR_MAX_OCTETS:
                        return None
                    morceaux.extend(fragment)
                if not morceaux:
                    return None
                if longueur is not None and int(longueur) != len(morceaux):
                    return None
                try:
                    texte = morceaux.decode("utf-8", errors="strict")

                    def objet(paires: list[tuple[str, Any]]) -> dict[str, Any]:
                        resultat: dict[str, Any] = {}
                        for cle, valeur in paires:
                            if cle in resultat:
                                raise ValueError("doublon")
                            resultat[cle] = valeur
                        return resultat

                    def constante(_: str) -> None:
                        raise ValueError("constante")

                    valeur = json.loads(texte, object_pairs_hook=objet, parse_constant=constante)
                except (UnicodeError, ValueError, TypeError, RecursionError):
                    return None
                if type(valeur) is not dict or set(valeur) != champs:
                    return None
                return valeur

            profil_id = request.path_params.get("profil_id")
            if not isinstance(profil_id, str) or not agents_cron_autorite.intentions._ID.fullmatch(profil_id):
                return await erreur("requete_invalide", 400)
            try:
                if base_cron_operateur.identite_url_cron_operateur(stockage.url_base()) != identite_base_cron:
                    return await erreur("base_canonique_modifiee", 503)
            except Exception:
                return await erreur("base_canonique_modifiee", 503)
            operation = request.url.path.rsplit("/", 1)[-1]
            if operation in {"lire", "projeter", "preparer-retrait", "accuser-retrait"} and request.url.query:
                return await erreur("requete_invalide", 400)
            if operation == "lire":
                arguments = await lire_objet(frozenset())
                if arguments is None:
                    return await erreur("requete_invalide", 400)
                try:
                    resultat = await anyio.to_thread.run_sync(
                        lambda: _dans_base_cron_operateur(
                            cnx_factory, identite_base_cron,
                            lambda: agents_cron_autorite.ProprietaireCron(
                                departements, profil_id,
                            ).lire(),
                        )
                    )
                except (agents_cron_autorite.DeclencheurRefuse, PermissionError):
                    return await erreur("operation_refusee", 409)
                except Exception:
                    return await erreur("service_indisponible", 503)
            elif operation == "projeter":
                champs = frozenset({"intention_id"})
                arguments = await lire_objet(champs)
                if arguments is None:
                    return await erreur("requete_invalide", 400)
                try:
                    resultat = await anyio.to_thread.run_sync(
                        lambda: _dans_base_cron_operateur(
                            cnx_factory, identite_base_cron,
                            lambda: agents_cron_autorite.ProprietaireCron(
                                departements, profil_id,
                            ).projeter(arguments["intention_id"]),
                        )
                    )
                except (agents_cron_autorite.DeclencheurRefuse, PermissionError):
                    return await erreur("operation_refusee", 409)
                except Exception:
                    return await erreur("service_indisponible", 503)
            elif operation == "preparer":
                champs = frozenset({"intention_id", "empreinte_capacite", "declaration", "epoch_attendue",
                                    "revision_native_attendue", "lease_secondes"})
                arguments = await lire_objet(champs)
                if arguments is None:
                    return await erreur("requete_invalide", 400)
                try:
                    resultat = await anyio.to_thread.run_sync(
                        lambda: _dans_base_cron_operateur(
                            cnx_factory, identite_base_cron,
                            lambda: agents_cron_autorite.ProprietaireCron(departements, profil_id).preparer(
                                arguments["intention_id"], empreinte_capacite=arguments["empreinte_capacite"],
                                declaration=arguments["declaration"], epoch_attendue=arguments["epoch_attendue"],
                                revision_native_attendue=arguments["revision_native_attendue"],
                                lease_secondes=arguments["lease_secondes"],
                            ),
                        )
                    )
                except (agents_cron_autorite.DeclencheurRefuse, PermissionError):
                    return await erreur("operation_refusee", 409)
                except Exception:
                    return await erreur("service_indisponible", 503)
            elif operation == "accuser":
                champs = frozenset({"intention_id", "capabilite", "epoch", "lease_epoch", "job_id",
                                    "config_revision", "declaration"})
                arguments = await lire_objet(champs)
                if arguments is None:
                    return await erreur("requete_invalide", 400)
                try:
                    resultat = await anyio.to_thread.run_sync(
                        lambda: _dans_base_cron_operateur(
                            cnx_factory, identite_base_cron,
                            lambda: agents_cron_autorite.ProprietaireCron(departements, profil_id).accuser(
                                arguments["intention_id"], capabilite=arguments["capabilite"],
                                epoch=arguments["epoch"], lease_epoch=arguments["lease_epoch"],
                                job_id=arguments["job_id"], config_revision=arguments["config_revision"],
                                declaration=arguments["declaration"],
                            ),
                        )
                    )
                except (agents_cron_autorite.DeclencheurRefuse, PermissionError):
                    return await erreur("operation_refusee", 409)
                except Exception:
                    return await erreur("service_indisponible", 503)
            elif operation == "valider":
                champs = frozenset({"intention_id", "capabilite", "epoch", "job_id",
                                    "config_revision", "declaration"})
                arguments = await lire_objet(champs)
                if arguments is None:
                    return await erreur("requete_invalide", 400)
                try:
                    await anyio.to_thread.run_sync(
                        lambda: _dans_base_cron_operateur(
                            cnx_factory, identite_base_cron,
                            lambda: agents_cron_autorite.ProprietaireCron(departements, profil_id).valider(
                                arguments["intention_id"], capabilite=arguments["capabilite"],
                                epoch=arguments["epoch"], job_id=arguments["job_id"],
                                config_revision=arguments["config_revision"],
                                declaration=arguments["declaration"],
                            ),
                        )
                    )
                    resultat = {"valide": True}
                except (agents_cron_autorite.DeclencheurRefuse, PermissionError):
                    return await erreur("operation_refusee", 409)
                except Exception:
                    return await erreur("service_indisponible", 503)
            elif operation == "renouveler":
                champs = frozenset({"intention_id", "capabilite", "epoch", "lease_epoch",
                                    "declaration", "lease_secondes"})
                arguments = await lire_objet(champs)
                if arguments is None:
                    return await erreur("requete_invalide", 400)
                try:
                    resultat = await anyio.to_thread.run_sync(
                        lambda: _dans_base_cron_operateur(
                            cnx_factory, identite_base_cron,
                            lambda: agents_cron_autorite.ProprietaireCron(departements, profil_id).renouveler(
                                arguments["intention_id"], capabilite=arguments["capabilite"],
                                epoch=arguments["epoch"], lease_epoch=arguments["lease_epoch"],
                                declaration=arguments["declaration"],
                                lease_secondes=arguments["lease_secondes"],
                            ),
                        )
                    )
                except (agents_cron_autorite.DeclencheurRefuse, PermissionError):
                    return await erreur("operation_refusee", 409)
                except Exception:
                    return await erreur("service_indisponible", 503)
            elif operation in {"preparer-retrait", "accuser-retrait"}:
                from . import agents_cron_retraits

                champs = {"intention_id", "capabilite", "epoch", "declaration", "job_id", "native_revision"}
                if operation == "accuser-retrait":
                    champs.update({"source_hash", "receipt_id"})
                arguments = await lire_objet(frozenset(champs))
                if arguments is None:
                    return await erreur("requete_invalide", 400)

                def operateur_courant() -> None:
                    # The operator is the current private transport, not a former
                    # human author and never an actor/role supplied in the body.
                    courant = os.environ.get(ENV_CRON_OPERATEUR_JETON, "")
                    if not courant or not hmac.compare_digest(courant, jeton_cron_operateur):
                        raise PermissionError("opérateur cron courant requis")

                def retrait() -> Any:
                    operateur_courant()
                    owner = agents_cron_retraits.ProprietaireRetraitCron(
                        departements, profil_id, operateur_courant,
                    )
                    appel = owner.preparer if operation == "preparer-retrait" else owner.accuser
                    ident = arguments["intention_id"]
                    options = {cle: valeur for cle, valeur in arguments.items() if cle != "intention_id"}
                    return appel(ident, **options)

                try:
                    resultat = await anyio.to_thread.run_sync(lambda: _dans_base_cron_operateur(
                        cnx_factory, identite_base_cron, retrait,
                    ))
                except (agents_cron_autorite.DeclencheurRefuse, PermissionError):
                    return await erreur("operation_refusee", 409)
                except Exception:
                    return await erreur("service_indisponible", 503)
            else:
                return await erreur("requete_invalide", 400)
            return JSONResponse({"ok": True, "resultat": resultat}, headers={"Cache-Control": "no-store"})

        routes.extend([
            Route(CHEMIN_CRON_OPERATEUR_PREFIXE + "{profil_id:str}/lire", appel_cron_operateur,
                  methods=["POST"]),
            Route(CHEMIN_CRON_OPERATEUR_PREFIXE + "{profil_id:str}/projeter", appel_cron_operateur,
                  methods=["POST"]),
            Route(CHEMIN_CRON_OPERATEUR_PREFIXE + "{profil_id:str}/preparer", appel_cron_operateur,
                  methods=["POST"]),
            Route(CHEMIN_CRON_OPERATEUR_PREFIXE + "{profil_id:str}/accuser", appel_cron_operateur,
                  methods=["POST"]),
            Route(CHEMIN_CRON_OPERATEUR_PREFIXE + "{profil_id:str}/valider", appel_cron_operateur,
                  methods=["POST"]),
            Route(CHEMIN_CRON_OPERATEUR_PREFIXE + "{profil_id:str}/renouveler", appel_cron_operateur,
                  methods=["POST"]),
            Route(CHEMIN_CRON_OPERATEUR_PREFIXE + "{profil_id:str}/preparer-retrait", appel_cron_operateur,
                  methods=["POST"]),
            Route(CHEMIN_CRON_OPERATEUR_PREFIXE + "{profil_id:str}/accuser-retrait", appel_cron_operateur,
                  methods=["POST"]),
        ])
    return _ExigerJeton(Starlette(routes=routes, lifespan=cycle_de_vie), jeton, jeton_contexte,
                        jeton_cron_operateur)



def _verifier_base_cron_operateur(cnx_factory: Any) -> tuple[str, str, tuple[tuple[str, Any], ...]]:
    """Le propriétaire cron global est permis seulement si l'application sert la même base SQLite."""
    return base_cron_operateur.verifier_base_cron_operateur(cnx_factory)


def _dans_base_cron_operateur(
    cnx_factory: Any,
    identite_base: tuple[str, str, tuple[tuple[str, Any], ...]],
    operation: Any,
) -> Any:
    """Exécute le propriétaire dans la connexion fournie et vérifie son contexte DB capturé."""
    return base_cron_operateur.dans_base_cron_operateur(cnx_factory, identite_base, operation)


def _creer_serveur_admission(departements: Mapping[str, Departement], cnx_factory: Any, agent_id: str) -> Server[Any]:
    """Private token admission endpoint whose profile identity is fixed by the route."""
    from . import admission_agents

    noms = frozenset(
        {
            "opsys_runtime_admettre",
            "opsys_runtime_importer_appel_manque",
            "opsys_runtime_concilier",
            "opsys_runtime_liberer_avant_dispatch",
            "opsys_runtime_verifier_outil",
            "opsys_runtime_cfo_ticket",
        }
    )
    reserve_schema = {
        "type": "object",
        "properties": {
            "execution_id": {"type": "string", "minLength": 8, "maxLength": 128},
            "cle_idempotence": {"type": "string", "minLength": 8, "maxLength": 128},
            "tokens_plafond": {"type": "integer", "minimum": 1},
            "revision_profil": {"type": "integer", "minimum": 1},
            "tours": {"type": "integer", "const": 1},
            "attempt_id": {"type": "string"},
            "cycle_id": {"type": "string"},
            "candidate_index": {"type": "integer", "minimum": 0},
            "stream_ordinal": {"type": "integer", "minimum": 0},
            "is_fallback_retry": {"type": "boolean"},
        },
        "required": [
            "execution_id",
            "cle_idempotence",
            "tokens_plafond",
            "revision_profil",
            "tours",
            "attempt_id",
            "cycle_id",
            "candidate_index",
            "stream_ordinal",
            "is_fallback_retry",
        ],
        "additionalProperties": False,
    }
    reconcile_schema = {
        "type": "object",
        "properties": {
            "reservation_id": {"type": "string", "minLength": 8, "maxLength": 128},
            "tokens_reels": {"type": "integer", "minimum": 0},
        },
        "required": ["reservation_id", "tokens_reels"],
        "additionalProperties": False,
    }
    release_schema = {
        "type": "object",
        "properties": {
            "reservation_id": {"type": "string", "minLength": 8, "maxLength": 128},
            "execution_id": {"type": "string", "minLength": 8, "maxLength": 128},
            "attempt_id": {"type": "string", "minLength": 8, "maxLength": 160},
            "cycle_id": {"type": "string", "minLength": 8, "maxLength": 160},
            "candidate_index": {"type": "integer", "minimum": 0},
            "stream_ordinal": {"type": "integer", "minimum": 0},
            "revision_profil": {"type": "integer", "minimum": 1},
        },
        "required": ["reservation_id", "execution_id", "attempt_id", "cycle_id",
                     "candidate_index", "stream_ordinal", "revision_profil"],
        "additionalProperties": False,
    }
    cfo_ticket_schema = {
        "type": "object",
        "properties": {
            "outil": {"type": "string"},
            "arguments": {"type": "object"},
            "revision_profil": {"type": "integer", "minimum": 1},
        },
        "required": ["outil", "arguments", "revision_profil"],
        "additionalProperties": False,
    }
    appel_manque_schema = {
        "type": "object",
        "properties": {
            "provider": {"type": "string", "enum": ["mock", "twilio", "telnyx", "plivo"]},
            "event_id": {"type": "string", "minLength": 1, "maxLength": 200},
            "call_id": {"type": "string", "minLength": 1, "maxLength": 200},
            "occurred_at": {"type": "string", "minLength": 20, "maxLength": 40},
            "telephone": {"type": "string", "pattern": r"^\+[1-9][0-9]{6,14}$"},
            "revision_profil": {"type": "integer", "minimum": 1},
        },
        "required": ["provider", "event_id", "call_id", "occurred_at", "telephone", "revision_profil"],
        "additionalProperties": False,
    }
    verify_tool_schema = {
        "type": "object",
        "properties": {
            "outil": {"type": "string", "minLength": 1, "maxLength": 256},
            "revision_profil": {"type": "integer", "minimum": 1},
        },
        "required": ["outil", "revision_profil"],
        "additionalProperties": False,
    }

    async def lister_outils(ctx: Any, params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
        del ctx, params
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="opsys_runtime_admettre",
                    description="Admet un cycle fournisseur une seule fois.",
                    inputSchema=reserve_schema,
                ),
                types.Tool(
                    name="opsys_runtime_concilier",
                    description="Enregistre l'usage exact d'un stream.",
                    inputSchema=reconcile_schema,
                ),
                types.Tool(
                    name="opsys_runtime_liberer_avant_dispatch",
                    description="Cleanup hôte privé d'un cycle dont le provider n'a jamais été invoqué.",
                    inputSchema=release_schema,
                ),
                types.Tool(
                    name="opsys_runtime_importer_appel_manque",
                    description="Importe un appel manqué après validation webhook côté hôte; aucun voicemail ni envoi.",
                    inputSchema=appel_manque_schema,
                ),
                types.Tool(
                    name="opsys_runtime_verifier_outil",
                    description="Revalide un outil du profil courant avant son dispatch Core.",
                    inputSchema=verify_tool_schema,
                ),
                types.Tool(
                    name="opsys_runtime_cfo_ticket",
                    description="Émet un ticket CFO lié à ce profil fixe.",
                    inputSchema=cfo_ticket_schema,
                ),
            ]
        )

    async def appeler(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        del ctx
        if params.name not in noms:
            resultat: dict[str, Any] = {"ok": False, "erreur": "outil_inconnu"}
        else:
            arguments = params.arguments or {}
            try:
                if params.name == "opsys_runtime_admettre":
                    resultat = await anyio.to_thread.run_sync(_reserver, arguments)
                elif params.name == "opsys_runtime_concilier":
                    resultat = await anyio.to_thread.run_sync(_concilier, arguments)
                elif params.name == "opsys_runtime_liberer_avant_dispatch":
                    resultat = await anyio.to_thread.run_sync(_liberer_avant_dispatch, arguments)
                elif params.name == "opsys_runtime_importer_appel_manque":
                    resultat = await anyio.to_thread.run_sync(_importer_appel_manque, arguments)
                elif params.name == "opsys_runtime_verifier_outil":
                    resultat = await anyio.to_thread.run_sync(_verifier_outil, arguments)
                else:
                    resultat = await anyio.to_thread.run_sync(_emettre_cfo_ticket, arguments)
            except Exception as exc:
                resultat = ({"ok": False, "erreur": "import_appel_refuse"}
                            if params.name == "opsys_runtime_importer_appel_manque"
                            else {"ok": False, "erreur": "admission_refusee", "details": str(exc)})
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(resultat, ensure_ascii=False))],
            isError=not resultat.get("ok", False),
        )

    def _reserver(arguments: Mapping[str, Any]) -> dict[str, Any]:
        if arguments.get("tours") != 1:
            raise ValueError("tours doit valoir 1 pour une invocation fournisseur")
        with cnx_factory() as cnx:
            admission = admission_agents.admettre_cycle_runtime(
                cnx,
                agent_id,
                departements,
                arguments["execution_id"],
                arguments["cle_idempotence"],
                arguments["tokens_plafond"],
                revision_profil=arguments["revision_profil"],
                attempt_id=arguments["attempt_id"],
                cycle_id=arguments["cycle_id"],
                candidate_index=arguments["candidate_index"],
                stream_ordinal=arguments["stream_ordinal"],
                is_fallback_retry=arguments["is_fallback_retry"],
            )
        accord_neuf = admission.get("accord_neuf") is True
        admission.pop("accord_neuf", None)
        return {"ok": True, "resultat": admission, "accord_neuf": accord_neuf}

    def _concilier(arguments: Mapping[str, Any]) -> dict[str, Any]:
        with cnx_factory() as cnx:
            reservation = admission_agents.lire_reservation(cnx, arguments["reservation_id"], agent_id=agent_id)
            resultat = admission_agents.concilier(cnx, reservation["id"], arguments["tokens_reels"])
        return {"ok": True, "resultat": resultat}

    def _liberer_avant_dispatch(arguments: Mapping[str, Any]) -> dict[str, Any]:
        from .outils import valider_arguments

        # Validate here too: the private handler never accepts extra identity/reason fields.
        if valider_arguments(release_schema, arguments):
            raise ValueError("capture de libération runtime invalide")
        with cnx_factory() as cnx:
            resultat = admission_agents.liberer_cycle_runtime_avant_dispatch(
                cnx, arguments["reservation_id"], agent_id=agent_id,
                execution_id=arguments["execution_id"], attempt_id=arguments["attempt_id"],
                cycle_id=arguments["cycle_id"], candidate_index=arguments["candidate_index"],
                stream_ordinal=arguments["stream_ordinal"], revision_profil=arguments["revision_profil"],
            )
        return {"ok": True, "resultat": resultat}

    def _importer_appel_manque(arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Private host-only ingress. The host owns webhook signature verification."""
        from datetime import datetime

        from . import admission_agents
        from . import contexte as contexte_appel
        from .outils import valider_arguments

        if valider_arguments(appel_manque_schema, arguments):
            raise ValueError("arguments invalides")
        if isinstance(arguments.get("revision_profil"), bool):
            raise ValueError("revision de profil invalide")
        if arguments["revision_profil"] < 1:
            raise ValueError("revision de profil invalide")

        def _identifiant(cle: str) -> str:
            valeur = arguments[cle]
            if (not isinstance(valeur, str) or len(valeur) > 200 or not valeur.strip()
                    or any(unicodedata.category(caractere) == "Cc" for caractere in valeur)):
                raise ValueError("identifiant provider invalide")
            return valeur.strip()

        event_id = _identifiant("event_id")
        call_id = _identifiant("call_id")
        date_source = arguments["occurred_at"]
        if (not isinstance(date_source, str) or len(date_source) > 40
                or re.fullmatch(
                    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
                    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])",
                    date_source,
                ) is None):
            raise ValueError("horodatage RFC3339 invalide")
        instant = datetime.fromisoformat(date_source.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            raise ValueError("horodatage sans fuseau")
        recu_le = instant.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        with cnx_factory() as cnx:
            if stockage.connexion_courante() is not cnx or cnx.engine.url != stockage.moteur().url:
                raise ValueError("base durable canonique requise")
            departement_m1 = departements.get("m01-front-office")
            if departement_m1 is None:
                raise ValueError("département M1 indisponible")
            nom_outil_m1 = "m1_importer_appel_manuellement"
            nom_outil_runtime = f"opsys_{departement_m1.prefixe_outils}__{nom_outil_m1}"
            admission_agents.verifier_outil_runtime(
                cnx, agent_id, departements, nom_outil_runtime,
                arguments["revision_profil"], verrouiller=True,
            )
            from m1_front_office import outils as outils_m1

            source = f"voice-call:{arguments['provider']}"
            with contexte_appel.appeler_en_tant_que("m01-front-office"):
                retour_m1 = outils_m1.importer_appel_manque_hote(
                    provider=arguments["provider"], event_id=event_id, call_id=call_id,
                    recu_le=recu_le, telephone=arguments["telephone"],
                )
            if (not isinstance(retour_m1, Mapping) or retour_m1.get("accepte") is not True
                    or retour_m1.get("source") != source or retour_m1.get("appel_id") != call_id
                    or retour_m1.get("statut") != "manque"):
                raise ValueError("résultat M1 non conforme")
            # Une bascule de configuration de stockage pendant l'appel ne doit pas valider
            # une mutation écrite dans l'ancienne base.
            if stockage.connexion_courante() is not cnx or cnx.engine.url != stockage.moteur().url:
                raise ValueError("base durable modifiée durant l'import")
            # Revalide sous la même transaction/verrou après tous les effets M1; un retrait
            # intervenu durant l'import invalide l'unité complète et déclenche son rollback.
            admission_agents.verifier_outil_runtime(
                cnx, agent_id, departements, nom_outil_runtime,
                arguments["revision_profil"], verrouiller=True,
            )
        return {"ok": True, "source": source, "call_id": call_id, "status": "manque"}

    def _verifier_outil(arguments: Mapping[str, Any]) -> dict[str, Any]:
        with cnx_factory() as cnx:
            resultat = admission_agents.verifier_outil_runtime(
                cnx,
                agent_id,
                departements,
                arguments["outil"],
                arguments["revision_profil"],
            )
        return {"ok": True, "resultat": resultat}

    def _emettre_cfo_ticket(arguments: Mapping[str, Any]) -> dict[str, Any]:

        from . import agent_cfo_grants
        from .outils import valider_arguments

        outil = arguments["outil"]
        args_metier = arguments["arguments"]
        outil_public = next(
            (candidate for candidate in departements["m05-financecore"].charger_outils() if candidate.nom == outil),
            None,
        )
        if outil_public is None or valider_arguments(outil_public.parametres, args_metier):
            raise ValueError("arguments CFO invalides")

        with cnx_factory() as cnx:
            grant = agent_cfo_grants.emettre(
                cnx,
                agent_id,
                outil,
                args_metier,
                instance_id=agent_cfo_grants.instance_id(cnx),
                revision_profil=arguments["revision_profil"],
            )
        return {"ok": True, "resultat": grant}

    return Server(f"opsys-runtime-{agent_id}", version=__version__, on_list_tools=lister_outils, on_call_tool=appeler)


def main(argv: list[str] | None = None) -> None:
    parseur = argparse.ArgumentParser(prog="opsys-mcp", description="Serveur MCP des départements OPSYS")
    parseur.add_argument(
        "--departement", action="append", default=[], help="id du département à exposer (répétable ; défaut : tous)"
    )
    parseur.add_argument("--http", action="store_true", help="HTTP streamable au lieu de stdio")
    parseur.add_argument("--hote", default="0.0.0.0")  # noqa: S104 — réseau interne docker
    parseur.add_argument("--port", type=int, default=8765)
    args = parseur.parse_args(argv)
    stockage.migrer()  # base de l'instance à jour avant le premier appel d'outil (ADR-0009)
    departements = charger_departements()
    if not args.http:
        appelant = args.departement[0] if len(args.departement) == 1 else None
        anyio.run(
            _servir, Capacites(departements, etat.session, filtre=set(args.departement) or None, appelant=appelant,
                              memoire_politique=autorite_memoire.lire_politique, memoire_versionnee=True)
        )
        return
    jeton = os.environ.get("OPSYS_MCP_JETON", "")
    jeton_contexte = os.environ.get("OPSYS_CONTEXT_MCP_JETON", "") or None
    import uvicorn

    logging.getLogger("uvicorn.access").addFilter(_SansAccesSante())
    application = application_http_departements(
        departements, etat.session, jeton, args.hote, jeton_contexte=jeton_contexte
    )
    uvicorn.run(application, host=args.hote, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
