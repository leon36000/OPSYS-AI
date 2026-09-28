"""Console OPSYS : application web FastAPI servie par le conteneur Python opsys (0.0.0.0:8700).

- Pages HTML en français rendues côté serveur : Départements, Approbations, Budgets, Modèles.
- API JSON sous /api : mêmes données, mêmes actions.
- Données et actions passent toutes par `opsys.tableau_de_bord`, donc par le socle.

Sécurité (voir `securite`) :
- mot de passe administrateur obligatoire ; session par cookie signé (HttpOnly, Secure,
  SameSite=Strict), limité au préfixe de la console ;
- jeton CSRF sur chaque écriture : champ `csrf` des formulaires, en-tête `X-CSRF-Token` de l'API ;
- chaque écriture est signée par l'utilisateur connecté, jamais par une valeur envoyée ;
- CSP stricte : aucune ressource externe, aucun script en ligne.

Client de l'API : POST <préfixe>/connexion (formulaire nom, mot_de_passe) pose le cookie ;
GET <préfixe>/api/session donne le jeton CSRF ; les écritures portent l'en-tête X-CSRF-Token.
Derrière Caddy, la console vit sous OPSYS_CONSOLE_PREFIXE (défaut /opsys), que le proxy retire
ce préfixe ou non.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .. import etat, tableau_de_bord
from ..departements import Departement, charger_departements
from . import pages, ressources, securite
from .securite import Configuration, Session

logger = logging.getLogger("opsys.console")

HOTE = "0.0.0.0"
PORT = 8700
LIMITE_CORPS = 64 * 1024  # octets : largement assez pour un formulaire ou un JSON de pilotage
CSP = ("default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; form-action 'self'; "
       "frame-ancestors 'none'; base-uri 'none'")
_STATIQUES = {
    "console.css": (ressources.CSS, "text/css; charset=utf-8"),
    "console.js": (ressources.JS, "text/javascript; charset=utf-8"),
}

FabriqueConnexion = Callable[[], AbstractContextManager[sqlite3.Connection]]


class _ConnexionRequise(Exception):
    """Page demandée sans session valide : redirection vers la connexion."""


class _JetonInvalide(Exception):
    """Écriture sans jeton CSRF valide."""


class _EntetesSecurite:
    """En-têtes de sécurité sur chaque réponse ; pas de cache sauf pour les ressources statiques."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def envoyer(message: Message) -> None:
            if message["type"] == "http.response.start":
                entetes = MutableHeaders(scope=message)
                entetes["Content-Security-Policy"] = CSP
                entetes["X-Content-Type-Options"] = "nosniff"
                entetes["X-Frame-Options"] = "DENY"
                entetes["Referrer-Policy"] = "no-referrer"
                if "cache-control" not in entetes:
                    entetes["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, envoyer)


def _message(exc: Exception) -> str:
    return str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)


def _code(exc: Exception) -> int:
    return 404 if isinstance(exc, KeyError) else 400


async def _corps(request: Request) -> bytes:
    annonce = request.headers.get("content-length", "")
    if annonce.isdigit() and int(annonce) > LIMITE_CORPS:
        raise HTTPException(413, "requête trop volumineuse")
    morceaux, taille = [], 0
    async for morceau in request.stream():
        taille += len(morceau)
        if taille > LIMITE_CORPS:
            raise HTTPException(413, "requête trop volumineuse")
        morceaux.append(morceau)
    return b"".join(morceaux)


async def _formulaire(request: Request) -> dict[str, str]:
    corps = await _corps(request)
    try:
        champs = parse_qs(corps.decode("utf-8"), keep_blank_values=True, max_num_fields=20)
    except ValueError as exc:
        raise HTTPException(400, "formulaire illisible") from exc
    return {cle: valeurs[0] for cle, valeurs in champs.items()}


async def _objet_json(request: Request) -> dict[str, Any]:
    corps = await _corps(request)
    try:
        donnees = json.loads(corps) if corps.strip() else {}
    except ValueError as exc:
        raise HTTPException(400, "corps JSON invalide") from exc
    if not isinstance(donnees, dict):
        raise HTTPException(400, "objet JSON attendu")
    return donnees


def creer_application(
    configuration: Configuration,
    departements: Mapping[str, Departement] | None = None,
    cnx_factory: FabriqueConnexion = etat.session,
    chemin_paliers: Path | None = None,
) -> FastAPI:
    """Application de la console. Les départements sont chargés une fois (défaut : les manifestes)."""
    deps = dict(charger_departements() if departements is None else departements)
    prefixe = configuration.prefixe
    # Pas de /docs : ces pages chargent leurs scripts depuis un CDN et exposeraient le schéma sans session.
    app = FastAPI(title="Console OPSYS", docs_url=None, redoc_url=None, openapi_url=None, root_path=prefixe)
    app.add_middleware(_EntetesSecurite)

    # -- sessions et jetons ----------------------------------------------------------------------
    def session_de(request: Request) -> Session | None:
        return securite.lire_session(request.cookies.get(securite.NOM_COOKIE), configuration.secret)

    def session_page(request: Request) -> Session:
        session = session_de(request)
        if session is None:
            raise _ConnexionRequise
        return session

    def session_api(request: Request) -> Session:
        session = session_de(request)
        if session is None:
            raise HTTPException(401, "authentification requise")
        return session

    def ecriture_api(request: Request) -> Session:
        session = session_api(request)
        if not securite.csrf_valide(request.headers.get("x-csrf-token"), session):
            raise _JetonInvalide
        return session

    def verifier_formulaire(champs: Mapping[str, str], session: Session) -> None:
        if not securite.csrf_valide(champs.get("csrf"), session):
            raise _JetonInvalide

    def est_api(request: Request) -> bool:
        chemin = request.url.path
        if prefixe and chemin.startswith(f"{prefixe}/"):
            chemin = chemin[len(prefixe):]
        return chemin.startswith("/api/")

    @app.exception_handler(_ConnexionRequise)
    async def _vers_connexion(request: Request, exc: _ConnexionRequise) -> Response:
        return RedirectResponse(f"{prefixe}/connexion", status_code=303)

    @app.exception_handler(_JetonInvalide)
    async def _jeton_invalide(request: Request, exc: _JetonInvalide) -> Response:
        texte = "jeton CSRF absent ou invalide : rechargez la page, puis recommencez"
        if est_api(request):
            return JSONResponse({"detail": texte}, status_code=403)
        return HTMLResponse(pages.page_erreur("Action refusée", texte, prefixe=prefixe), status_code=403)

    # -- actions (fil de travail : SQLite et outils sont bloquants) --------------------------------
    def changer_mode(ident: str, mode: Any, session: Session) -> dict[str, Any]:
        with cnx_factory() as cnx:
            return tableau_de_bord.changer_mode(cnx, deps, ident, mode, session.utilisateur)

    def decider(ident: str, decision: Any, motif: str, session: Session) -> dict[str, Any]:
        with cnx_factory() as cnx:
            return tableau_de_bord.decider_approbation(cnx, deps, ident, decision, session.utilisateur, motif.strip())

    def ecrire_palier(palier: str, conf: Any, session: Session) -> dict[str, Any]:
        return tableau_de_bord.ecrire_palier(palier, conf, session.utilisateur, chemin_paliers)

    async def executer_api(action: Callable[..., dict[str, Any]], *arguments: Any) -> dict[str, Any]:
        try:
            return await run_in_threadpool(action, *arguments)
        except (ValueError, KeyError) as exc:
            raise HTTPException(_code(exc), _message(exc)) from exc
        except ImportError as exc:
            raise HTTPException(500, f"outils des départements illisibles, rien n'a été exécuté : {exc}") from exc

    # -- pages -----------------------------------------------------------------------------------
    def html(session: Session, actif: str, titre: str, corps: str, en_attente: int, code: int = 200,
             bandeau: pages.Bandeau | None = None) -> HTMLResponse:
        page = pages.gabarit(titre, corps, prefixe=prefixe, session=session, actif=actif, en_attente=en_attente,
                             bandeau=bandeau)
        return HTMLResponse(page, status_code=code)

    def page_departements(session: Session, code: int = 200, bandeau: pages.Bandeau | None = None) -> HTMLResponse:
        with cnx_factory() as cnx:
            vues = tableau_de_bord.vue_departements(cnx, deps)
            en_attente = tableau_de_bord.nombre_en_attente(cnx, pages.PLAFOND_PASTILLE)
        corps = pages.contenu_departements(vues, tableau_de_bord.modes_disponibles(), prefixe=prefixe,
                                           csrf=session.csrf)
        return html(session, "departements", "Départements", corps, en_attente, code, bandeau)

    def page_approbations(session: Session, statut: str = "", code: int = 200,
                          bandeau: pages.Bandeau | None = None) -> HTMLResponse:
        with cnx_factory() as cnx:
            try:
                demandes = tableau_de_bord.lister_approbations(cnx, deps, statut or None)
            except ValueError as exc:
                statut, code, bandeau = "", 400, (str(exc), "erreur")
                demandes = tableau_de_bord.lister_approbations(cnx, deps)
            en_attente = tableau_de_bord.nombre_en_attente(cnx, pages.PLAFOND_PASTILLE)
        corps = pages.contenu_approbations(demandes, statut=statut, prefixe=prefixe, csrf=session.csrf)
        return html(session, "approbations", "Approbations", corps, en_attente, code, bandeau)

    def page_budgets(session: Session) -> HTMLResponse:
        with cnx_factory() as cnx:
            donnees = tableau_de_bord.budgets(cnx, deps)
            en_attente = tableau_de_bord.nombre_en_attente(cnx, pages.PLAFOND_PASTILLE)
        return html(session, "budgets", "Budgets", pages.contenu_budgets(donnees, prefixe=prefixe), en_attente)

    def page_modeles(session: Session, code: int = 200, bandeau: pages.Bandeau | None = None,
                     saisie: Mapping[str, Mapping[str, str]] | None = None) -> HTMLResponse:
        try:
            vue = tableau_de_bord.lire_paliers(deps, chemin_paliers)
            corps = pages.contenu_modeles(vue, prefixe=prefixe, csrf=session.csrf, saisie=saisie)
        except ValueError as exc:  # fichier des paliers illisible : le dire, ne rien écraser
            corps, code, bandeau = "", 500, (f"paliers illisibles : {exc}", "erreur")
        with cnx_factory() as cnx:
            en_attente = tableau_de_bord.nombre_en_attente(cnx, pages.PLAFOND_PASTILLE)
        return html(session, "modeles", "Modèles", corps, en_attente, code, bandeau)

    # -- routes publiques --------------------------------------------------------------------------
    @app.get("/sante")
    def sante() -> dict[str, str]:
        return {"statut": "ok"}

    @app.get("/statique/{nom}")
    def statique(nom: str) -> Response:
        if nom not in _STATIQUES:
            raise HTTPException(404, "ressource inconnue")
        contenu, type_media = _STATIQUES[nom]
        return Response(contenu, media_type=type_media, headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/")
    def accueil() -> Response:
        return RedirectResponse(f"{prefixe}/departements", status_code=303)

    @app.get("/connexion")
    def formulaire_connexion(request: Request) -> Response:
        if session_de(request) is not None:
            return RedirectResponse(f"{prefixe}/departements", status_code=303)
        return HTMLResponse(pages.page_connexion(prefixe=prefixe))

    @app.post("/connexion")
    async def connexion(request: Request) -> Response:
        champs = await _formulaire(request)
        nom = champs.get("nom", "")
        if not securite.mot_de_passe_valide(champs.get("mot_de_passe", ""), configuration.mot_de_passe):
            logger.warning("échec de connexion")
            page = pages.page_connexion(prefixe=prefixe, erreur="Mot de passe incorrect.", nom=nom)
            return HTMLResponse(page, status_code=401)
        try:
            session = securite.ouvrir_session(nom, configuration.duree_session)
        except ValueError as exc:
            return HTMLResponse(pages.page_connexion(prefixe=prefixe, erreur=str(exc), nom=nom), status_code=400)
        reponse = RedirectResponse(f"{prefixe}/departements", status_code=303)
        reponse.set_cookie(
            securite.NOM_COOKIE, securite.signer_session(session, configuration.secret),
            max_age=configuration.duree_session, path=prefixe or "/", secure=configuration.cookie_securise,
            httponly=True, samesite="strict",
        )
        logger.info("connexion de %r", session.utilisateur)
        return reponse

    # -- pages authentifiées ---------------------------------------------------------------------
    @app.post("/deconnexion")
    async def deconnexion(request: Request) -> Response:
        session = session_page(request)
        verifier_formulaire(await _formulaire(request), session)
        reponse = RedirectResponse(f"{prefixe}/connexion", status_code=303)
        reponse.delete_cookie(securite.NOM_COOKIE, path=prefixe or "/", secure=configuration.cookie_securise,
                              httponly=True, samesite="strict")
        return reponse

    @app.get("/departements")
    def departements_(request: Request, ok: str = "") -> Response:
        return page_departements(session_page(request), bandeau=pages.bandeau_succes(ok))

    @app.post("/departements/{ident}/mode")
    async def mode_(ident: str, request: Request) -> Response:
        session = session_page(request)
        champs = await _formulaire(request)
        verifier_formulaire(champs, session)
        try:
            await run_in_threadpool(changer_mode, ident, champs.get("mode", ""), session)
        except (ValueError, KeyError) as exc:
            return await run_in_threadpool(page_departements, session, _code(exc), (_message(exc), "erreur"))
        return RedirectResponse(f"{prefixe}/departements?ok=mode#{quote(ident, safe='')}", status_code=303)

    @app.get("/approbations")
    def approbations_(request: Request, statut: str = "", ok: str = "") -> Response:
        return page_approbations(session_page(request), statut, bandeau=pages.bandeau_succes(ok))

    @app.post("/approbations/{ident}/decision")
    async def decision_(ident: str, request: Request) -> Response:
        session = session_page(request)
        champs = await _formulaire(request)
        verifier_formulaire(champs, session)
        try:
            resultat = await run_in_threadpool(decider, ident, champs.get("decision", ""), champs.get("motif", ""),
                                               session)
        except (ValueError, KeyError) as exc:
            return await run_in_threadpool(page_approbations, session, "", _code(exc), (_message(exc), "erreur"))
        except ImportError as exc:
            texte = f"outils des départements illisibles, rien n'a été exécuté : {exc}"
            return await run_in_threadpool(page_approbations, session, "", 500, (texte, "erreur"))
        return RedirectResponse(f"{prefixe}/approbations?ok={quote(resultat['statut'], safe='')}", status_code=303)

    @app.get("/budgets")
    def budgets_(request: Request) -> Response:
        return page_budgets(session_page(request))

    @app.get("/modeles")
    def modeles_(request: Request, ok: str = "") -> Response:
        return page_modeles(session_page(request), bandeau=pages.bandeau_succes(ok))

    @app.post("/modeles/{palier}")
    async def palier_(palier: str, request: Request) -> Response:
        session = session_page(request)
        champs = await _formulaire(request)
        verifier_formulaire(champs, session)
        saisie = {cle: champs.get(cle, "") for cle in ("provider", "model", "base_url")}
        try:
            await run_in_threadpool(ecrire_palier, palier, saisie, session)
        except ValueError as exc:
            return await run_in_threadpool(page_modeles, session, 400, (str(exc), "erreur"), {palier: saisie})
        return RedirectResponse(f"{prefixe}/modeles?ok=palier", status_code=303)

    # -- API JSON ----------------------------------------------------------------------------------
    @app.get("/api/session")
    def api_session(request: Request) -> dict[str, str]:
        session = session_api(request)
        return {"utilisateur": session.utilisateur, "csrf": session.csrf}

    @app.get("/api/departements")
    def api_departements(request: Request) -> dict[str, Any]:
        session_api(request)
        with cnx_factory() as cnx:
            vues = tableau_de_bord.vue_departements(cnx, deps)
        return {"departements": vues, "modes": tableau_de_bord.modes_disponibles()}

    @app.post("/api/departements/{ident}/mode")
    async def api_mode(ident: str, request: Request) -> dict[str, Any]:
        session = ecriture_api(request)
        corps = await _objet_json(request)
        return await executer_api(changer_mode, ident, corps.get("mode", ""), session)

    @app.get("/api/approbations")
    def api_approbations(request: Request, statut: str = "") -> dict[str, Any]:
        session_api(request)
        with cnx_factory() as cnx:
            try:
                return {"approbations": tableau_de_bord.lister_approbations(cnx, deps, statut or None)}
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc

    @app.post("/api/approbations/{ident}/decision")
    async def api_decision(ident: str, request: Request) -> dict[str, Any]:
        session = ecriture_api(request)
        corps = await _objet_json(request)
        motif = corps.get("motif", "")
        if not isinstance(motif, str):
            raise HTTPException(400, "motif : texte attendu")
        return await executer_api(decider, ident, corps.get("decision", ""), motif, session)

    @app.get("/api/budgets")
    def api_budgets(request: Request) -> dict[str, Any]:
        session_api(request)
        with cnx_factory() as cnx:
            return {"budgets": tableau_de_bord.budgets(cnx, deps)}

    @app.get("/api/paliers")
    def api_paliers(request: Request) -> dict[str, Any]:
        session_api(request)
        try:
            return tableau_de_bord.lire_paliers(deps, chemin_paliers)
        except ValueError as exc:
            raise HTTPException(500, f"paliers illisibles : {exc}") from exc

    @app.put("/api/paliers/{palier}")
    async def api_palier(palier: str, request: Request) -> dict[str, Any]:
        session = ecriture_api(request)
        corps = await _objet_json(request)
        return await executer_api(ecrire_palier, palier, corps, session)

    return app


def lancer(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    """Démarre la console. Refuse de démarrer (code 2) sans configuration valide."""
    parseur = argparse.ArgumentParser(prog="opsys-console",
                                      description="Console web OPSYS : départements, approbations, budgets, paliers")
    parseur.add_argument("--hote", default=HOTE, help=f"adresse d'écoute (défaut : {HOTE})")
    parseur.add_argument("--port", type=int, default=PORT, help=f"port d'écoute (défaut : {PORT})")
    args = parseur.parse_args(argv)
    try:
        application = creer_application(Configuration.depuis_environnement(os.environ if environ is None else environ))
    except (OSError, ValueError) as exc:
        print(f"opsys-console : {exc}", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    uvicorn.run(application, host=args.hote, port=args.port)
    return 0
