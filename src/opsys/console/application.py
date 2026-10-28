"""Console OPSYS : application web FastAPI servie par le conteneur Python opsys (0.0.0.0:8700).

- Pages HTML en français rendues côté serveur : Départements, Approbations, Budgets, Modèles.
- API JSON sous /api : mêmes données, mêmes actions.
- Données et actions passent toutes par `opsys.tableau_de_bord`, donc par le socle.

Sécurité (voir `securite`) :
- connexion PAR PERSONNE (identifiant + mot de passe propre, `opsys.identite.authentifier`) — plus
  de mot de passe partagé (ADR-0009 §5). Amorçage de la toute première personne (`nathan_owner`) :
  CLI `opsys-metier personnes creer`, avant la première connexion.
- session par cookie signé (HttpOnly, Secure, SameSite=Strict), limité au préfixe de la console,
  portant l'identifiant de la personne ET ses rôles (`securite.Session`) ;
- jeton CSRF sur chaque écriture : champ `csrf` des formulaires, en-tête `X-CSRF-Token` de l'API ;
- chaque écriture est signée par la personne connectée, jamais par une valeur envoyée ;
- CSP stricte : aucune ressource externe, aucun script en ligne.

Client de l'API : POST <préfixe>/connexion (formulaire identifiant, mot_de_passe) pose le cookie ;
GET <préfixe>/api/session donne le jeton CSRF ; les écritures portent l'en-tête X-CSRF-Token.
Derrière Caddy, la console vit sous OPSYS_CONSOLE_PREFIXE (défaut /opsys), que le proxy retire
ce préfixe ou non.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import replace
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import Connection, select
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .. import admission_agents, agents, agents_declencheurs, contexte, etat, identite, stockage, tableau_de_bord
from ..capacites import Capacites
from ..departements import Departement, charger_departements
from ..stockage import base_cron_operateur
from ..stockage.schema import AGENTS_POLITIQUE_ENTREPRISE
from . import (
    agents_etat,
    agents_ui,
    banque_metier,
    banque_ui,
    brand_ui,
    calendrier_marketing_ui,
    cfo_ui,
    connecteurs_ui,
    crm_ui,
    estimation_apprentissage_ui,
    finance_snapshot_prive,
    finance_ui,
    formulaire_recepteur,
    frontoffice_marketing,
    fusion_ap_ui,
    fusion_pdf_ocr_ui,
    fusion_pdf_ui,
    fusion_synthese,
    fusion_ui,
    marketing_cmo_ui,
    marketing_growth_ui,
    marketing_performance_ui,
    memoire_api,
    memoire_apprentissage_ui,
    memoire_ingestion_ui,
    memoire_jobs_ui,
    memoire_ui,
    obligations_privees,
    obligations_rapprochement_ui,
    pages,
    paie_ui,
    reception_digest_ui,
    ressources,
    securite,
    strategie_suivis_ui,
    voicemail_ui,
)
from .securite import Configuration, Session

logger = logging.getLogger("opsys.console")

HOTE = "0.0.0.0"
PORT = 8700
LIMITE_CORPS = 64 * 1024  # octets : largement assez pour un formulaire ou un JSON de pilotage
CSP = (
    "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; form-action 'self'; "
    "frame-ancestors 'none'; base-uri 'none'"
)
_STATIQUES = {
    "console.css": (ressources.CSS, "text/css; charset=utf-8"),
    "console.js": (ressources.JS, "text/javascript; charset=utf-8"),
}

FabriqueConnexion = Callable[[], AbstractContextManager[Connection]]


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
                # Cumuler toutes les politiques locales et la protection obligatoire de la console.
                politiques = entetes.getlist("Content-Security-Policy")
                entetes["Content-Security-Policy"] = ", ".join([*politiques, CSP])
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
    if isinstance(exc, KeyError):
        return 404
    if isinstance(exc, PermissionError):
        return 403
    return 409 if "conflit" in str(exc).lower() else 400


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


def _attestation_depuis_formulaire(champs: Mapping[str, str]) -> dict[str, str] | None:
    """N5 seulement (ADR-0009 §5) : trois champs plats du formulaire HTML (pas d'objet imbriqué en
    `application/x-www-form-urlencoded`) ; absents pour toute autre décision. `approbations.decider`
    valide le contenu — ce formulaire ne fait que le rassembler."""
    valeurs = {
        "nom": champs.get("attestation_nom", ""),
        "profession": champs.get("attestation_profession", ""),
        "reference_document": champs.get("attestation_document", ""),
    }
    if not any(v.strip() for v in valeurs.values()):
        return None
    return valeurs


def creer_application(
    configuration: Configuration,
    departements: Mapping[str, Departement] | None = None,
    cnx_factory: FabriqueConnexion = etat.session,
    chemin_paliers: Path | None = None,
    *,
    bundle_ocr: Path | None = None,
    site_formulaire: str | None = None,
    secret_formulaire: bytes | None = None,
) -> FastAPI:
    """Application de la console. Les départements sont chargés une fois (défaut : les manifestes)."""
    from .ocr_configuration import valider_choix

    bundle_ocr = valider_choix(bundle_ocr)
    if isinstance(secret_formulaire, bytes) and secret_formulaire == configuration.secret.encode("utf-8"):
        raise ValueError("configuration formulaire invalide : clé dédiée requise")
    deps = dict(charger_departements() if departements is None else departements)
    prefixe = configuration.prefixe
    # Pas de /docs : ces pages chargent leurs scripts depuis un CDN et exposeraient le schéma sans session.
    app = FastAPI(title="Console OPSYS", docs_url=None, redoc_url=None, openapi_url=None, root_path=prefixe)
    app.add_middleware(_EntetesSecurite)

    # Livraison serveur-à-serveur : aucune session humaine n'est fabriquée. Le nom
    # de l'outil, l'origine M1 et le profil de l'instance sont fixés ici, hors requête.
    m1 = "m01-front-office"
    pont_m1 = Capacites(deps, cnx_factory, filtre={m1}, appelant=m1, memoire=False) if m1 in deps else None

    def recevoir_formulaire(nom: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if pont_m1 is None or nom != "m1_recevoir_message_canal":
            return {"ok": False, "erreur": "outil_indisponible"}
        return pont_m1.appeler("m1_recevoir_message_canal", arguments)

    app.include_router(formulaire_recepteur.creer_router(
        invoquer=recevoir_formulaire, site_id=site_formulaire, secret=secret_formulaire,
    ))

    # -- sessions et jetons ----------------------------------------------------------------------
    def session_de(request: Request) -> Session | None:
        session = securite.lire_session(request.cookies.get(securite.NOM_COOKIE), configuration.secret)
        if session is None:
            return None
        with cnx_factory() as cnx:
            personne = identite.personne_active(cnx, session.utilisateur)
        # Un cookie signé ne maintient ni un compte désactivé ni des rôles retirés en vie.
        return replace(session, roles=personne.roles) if personne is not None else None

    def verifier_administration(cnx: Connection, session: Session) -> None:
        personne = identite.personne_active(cnx, session.utilisateur)
        if personne is None:
            raise HTTPException(401, "authentification requise")
        if not personne.roles.intersection({"nathan_owner", "admin"}):
            raise HTTPException(403, "administration réservée au propriétaire ou à un administrateur")

    def administration(session: Session) -> None:
        with cnx_factory() as cnx:
            verifier_administration(cnx, session)

    def session_page(request: Request, *, administrateur: bool = True) -> Session:
        session = session_de(request)
        if session is None:
            raise _ConnexionRequise
        if administrateur:
            administration(session)
        return session

    def session_api(request: Request, *, administrateur: bool = True) -> Session:
        session = session_de(request)
        if session is None:
            raise HTTPException(401, "authentification requise")
        if administrateur:
            administration(session)
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
            chemin = chemin[len(prefixe) :]
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

    app.include_router(
        memoire_api.creer_router(
            session_api=session_api, ecriture_api=ecriture_api, cnx_factory=cnx_factory, objet_json=_objet_json
        )
    )
    app.include_router(connecteurs_ui.creer_router(
        session_page=session_page, session_api=session_api, cnx_factory=cnx_factory,
        deps=deps, prefixe=prefixe, ecriture_api=ecriture_api, objet_json=_objet_json, chemin_paliers=chemin_paliers,
    ))
    app.include_router(estimation_apprentissage_ui.creer_router(
        session_page=session_page, session_api=session_api, cnx_factory=cnx_factory,
        verifier_administration=verifier_administration, revalider_administration=administration,
        deps=deps, prefixe=prefixe,
    ))
    callbacks_metier = {
        "session_page": session_page,
        "session_api": session_api,
        "ecriture_api": ecriture_api,
        "formulaire": _formulaire,
        "objet_json": _objet_json,
        "cnx_factory": cnx_factory,
        "deps": deps,
        "prefixe": prefixe,
    }
    callbacks_frontoffice = {k: v for k, v in callbacks_metier.items() if k not in {"formulaire", "objet_json"}}
    app.include_router(
        frontoffice_marketing.creer_router(**callbacks_frontoffice, _formulaire=_formulaire, _objet_json=_objet_json)
    )
    app.include_router(crm_ui.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe,
        ecriture_api=ecriture_api, formulaire=_formulaire, objet_json=_objet_json,
        verifier_formulaire=verifier_formulaire,
    ))
    app.include_router(reception_digest_ui.creer_router(
        session_page=session_page, session_api=session_api, cnx_factory=cnx_factory,
        deps=deps, prefixe=prefixe,
    ))
    app.include_router(
        voicemail_ui.creer_router(session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe)
    )
    app.include_router(finance_ui.creer_router(**callbacks_metier))
    app.include_router(
        banque_ui.creer_router(
            session_page=session_page,
            session_api=session_api,
            ecriture_api=ecriture_api,
            formulaire=_formulaire,
            objet_json=_objet_json,
            autoriser_page=lambda session: banque_metier.autoriser_page(cnx_factory, session),
            lire_comptes=lambda: banque_metier.comptes_configures(deps),
            previsualiser=lambda session, demande: banque_metier.previsualiser(
                cnx_factory, deps, session, demande
            ),
            prefixe=prefixe,
        )
    )
    app.include_router(
        fusion_ui.creer_router(
            session_page=session_page, session_api=session_api, ecriture_api=ecriture_api,
            formulaire=_formulaire, cnx_factory=cnx_factory, deps=deps,
            lire_comptes=lambda: banque_metier.comptes_configures(deps), prefixe=prefixe,
        )
    )
    app.include_router(
        fusion_synthese.creer_router(
            session_page=session_page, prefixe=prefixe, cnx_factory=cnx_factory,
        )
    )
    app.include_router(
        fusion_pdf_ui.creer_router(
            session_page=session_page,
            prefixe=prefixe,
            cnx_factory=cnx_factory,
            bundle_ocr=bundle_ocr,
        )
    )
    app.include_router(
        fusion_pdf_ocr_ui.creer_router(
            session_page=session_page, prefixe=prefixe,
            cnx_factory=cnx_factory, bundle_ocr=bundle_ocr,
        )
    )
    app.include_router(
        fusion_ap_ui.creer_router(
            session_page=session_page,
            prefixe=prefixe,
            cnx_factory=cnx_factory,
            deps=deps,
        )
    )
    app.include_router(paie_ui.creer_router(**{k: v for k, v in callbacks_metier.items() if k != "ecriture_api"}))
    app.include_router(obligations_rapprochement_ui.creer_router(
        session_page=session_page, formulaire=_formulaire, cnx_factory=cnx_factory,
        journal=obligations_privees, finance_snapshot=finance_snapshot_prive, prefixe=prefixe,
    ))
    app.include_router(cfo_ui.creer_router(**callbacks_metier))
    app.include_router(calendrier_marketing_ui.creer_router(**callbacks_metier))
    app.include_router(marketing_performance_ui.creer_router(**callbacks_metier))
    app.include_router(strategie_suivis_ui.creer_router(**callbacks_metier))
    app.include_router(marketing_cmo_ui.creer_router(**callbacks_metier))
    app.include_router(marketing_growth_ui.creer_router(**callbacks_metier))
    app.include_router(brand_ui.creer_router(**callbacks_metier))

    def appeler_memoire(session: Session, action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        from m10_memoire import developpement

        # Fermer la lecture avant l'écriture du registre M10 dans sa propre transaction.
        with cnx_factory() as cnx:
            verifier_administration(cnx, session)
            personne = identite.personne_active(cnx, session.utilisateur)
            role = "nathan_owner" if "nathan_owner" in personne.roles else "admin"
        try:
            with contexte.appele_par_appareil(contexte.IdentiteAppelante(session.utilisateur, role)):
                return action(*args, **kwargs)
        except developpement.AccesDeveloppementRefuse as exc:
            raise HTTPException(403, "accès mémoire développement refusé") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, "commande mémoire invalide") from exc

    app.include_router(
        memoire_jobs_ui.creer_router(
            session_api=session_api,
            ecriture_api=ecriture_api,
            session_page=session_page,
            objet_json=_objet_json,
            formulaire=_formulaire,
            verifier_formulaire=verifier_formulaire,
            appeler_memoire=appeler_memoire,
            prefixe=prefixe,
        )
    )
    app.include_router(memoire_ingestion_ui.creer_router(session_page=session_page, prefixe=prefixe))

    def revalider_admin_memoire(session: Session) -> None:
        with cnx_factory() as cnx:
            verifier_administration(cnx, session)

    departement_m03 = deps.get("m03-estimation")
    if departement_m03 is None:
        outils_m03, codes_m3 = frozenset(), frozenset()
    else:
        outils_m03 = frozenset(outil.nom for outil in departement_m03.charger_outils())
        paquet_m03 = departement_m03.module_outils.rpartition(".")[0]
        catalogue_verdicts = import_module(f"{paquet_m03}.verdicts")
        codes_m3 = frozenset(catalogue_verdicts.CODES_M3_LIST)

    app.include_router(memoire_apprentissage_ui.creer_router(
        session_page=session_page,
        revalider_administration=revalider_admin_memoire,
        prefixe=prefixe,
        outils_m03=outils_m03,
        codes_m3=codes_m3,
    ))

    # -- actions (fil de travail : SQLite et outils sont bloquants) --------------------------------
    def authentifier(identifiant: str, mot_de_passe: str) -> identite.Personne | None:
        with cnx_factory() as cnx:
            return identite.authentifier(cnx, identifiant, mot_de_passe)

    def changer_mode(ident: str, mode: Any, session: Session) -> dict[str, Any]:
        with cnx_factory() as cnx:
            verifier_administration(cnx, session)
            return tableau_de_bord.changer_mode(cnx, deps, ident, mode, session.utilisateur)

    def decider(
        ident: str, decision: Any, motif: str, attestation: Mapping[str, Any] | None, session: Session
    ) -> dict[str, Any]:
        with cnx_factory() as cnx:
            verifier_administration(cnx, session)
            return tableau_de_bord.decider_approbation(
                cnx, deps, ident, decision, session.utilisateur, motif.strip(), attestation
            )

    def ecrire_palier(palier: str, conf: Any, session: Session) -> dict[str, Any]:
        with cnx_factory() as cnx:
            verifier_administration(cnx, session)
            return tableau_de_bord.ecrire_palier(palier, conf, session.utilisateur, chemin_paliers)

    def muter_agent(action: str, ident: str | None, corps: Mapping[str, Any], session: Session) -> dict[str, Any]:
        attendus = {"mutation_id"}
        attendus |= {"spec"} if action in {"creer", "modifier"} else set()
        attendus |= {"revision_attendue"} if action != "creer" else set()
        attendus |= {"actif"} if action == "activation" else set()
        if set(corps) != attendus:
            raise ValueError("champs de la commande invalides")
        spec = corps.get("spec")
        if action in {"creer", "modifier"} and not isinstance(spec, dict):
            raise ValueError("spec : objet requis")
        with cnx_factory() as cnx:
            verifier_administration(cnx, session)
            commun = {"par": session.utilisateur, "mutation_id": corps["mutation_id"]}
            if action == "creer":
                profil = agents.creer(cnx, deps, spec, **commun)
            elif action == "modifier":
                profil = agents.modifier(cnx, ident, deps, spec, revision_attendue=corps["revision_attendue"], **commun)
            elif action == "activation":
                profil = agents.definir_actif(
                    cnx, ident, deps, corps["actif"], revision_attendue=corps["revision_attendue"], **commun
                )
            else:
                profil = agents.supprimer(cnx, ident, deps, revision_attendue=corps["revision_attendue"], **commun)
        return {"agent": profil}

    def lire_plafonds(cnx: Connection) -> dict[str, Any] | None:
        ligne = (
            cnx.execute(select(AGENTS_POLITIQUE_ENTREPRISE).where(AGENTS_POLITIQUE_ENTREPRISE.c.id == 1))
            .mappings()
            .fetchone()
        )
        return dict(ligne) if ligne is not None else None

    def ecrire_plafonds(corps: Mapping[str, Any], session: Session) -> dict[str, Any]:
        if set(corps) != {"budget_jour", "budget_mois", "revision_attendue"}:
            raise ValueError("champs des plafonds invalides")
        with cnx_factory() as cnx:
            verifier_administration(cnx, session)
            politique = admission_agents.configurer_plafonds_entreprise(
                cnx,
                corps["budget_jour"],
                corps["budget_mois"],
                par=session.utilisateur,
                revision_attendue=corps["revision_attendue"],
            )
        return {"plafonds": politique}

    async def executer_api(action: Callable[..., dict[str, Any]], *arguments: Any) -> dict[str, Any]:
        try:
            return await run_in_threadpool(action, *arguments)
        except (ValueError, KeyError, PermissionError) as exc:
            raise HTTPException(_code(exc), _message(exc)) from exc
        except ImportError as exc:
            raise HTTPException(500, f"outils des départements illisibles, rien n'a été exécuté : {exc}") from exc

    # -- pages -----------------------------------------------------------------------------------
    def html(
        session: Session,
        actif: str,
        titre: str,
        corps: str,
        en_attente: int,
        code: int = 200,
        bandeau: pages.Bandeau | None = None,
    ) -> HTMLResponse:
        page = pages.gabarit(
            titre, corps, prefixe=prefixe, session=session, actif=actif, en_attente=en_attente, bandeau=bandeau
        )
        return HTMLResponse(page, status_code=code)

    def page_departements(session: Session, code: int = 200, bandeau: pages.Bandeau | None = None) -> HTMLResponse:
        with cnx_factory() as cnx:
            vues = tableau_de_bord.vue_departements(cnx, deps)
            en_attente = tableau_de_bord.nombre_en_attente(cnx, pages.PLAFOND_PASTILLE)
        corps = pages.contenu_departements(
            vues, tableau_de_bord.modes_disponibles(), prefixe=prefixe, csrf=session.csrf
        )
        return html(session, "departements", "Départements", corps, en_attente, code, bandeau)

    def page_approbations(
        session: Session, statut: str = "", code: int = 200, bandeau: pages.Bandeau | None = None
    ) -> HTMLResponse:
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
            verifier_administration(cnx, session)
            donnees = tableau_de_bord.budgets(cnx, deps)
            plafonds = lire_plafonds(cnx)
            en_attente = tableau_de_bord.nombre_en_attente(cnx, pages.PLAFOND_PASTILLE)
        corps = pages.contenu_budgets(donnees, prefixe=prefixe)
        corps += agents_ui.plafonds_entreprise(plafonds, prefixe=prefixe, csrf=session.csrf)
        return html(session, "budgets", "Budgets", corps, en_attente)

    def page_agents(
        session: Session,
        ident: str | None = None,
        code: int = 200,
        bandeau: pages.Bandeau | None = None,
        *,
        decalage: int = 0,
    ) -> HTMLResponse:
        try:
            agents_etat.valider_pagination(agents_etat.LIMITE_MAX, decalage)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        with cnx_factory() as cnx:
            verifier_administration(cnx, session)
            profil = agents.obtenir(cnx, ident) if ident else None
            if ident and profil is None:
                raise HTTPException(404, "profil inconnu")
            export = agents_etat.lire_export(agents_etat.dossier_configuration_core())
            pilotage = agents_etat.tableau(cnx, deps, decalage=decalage, export=export)
            etat_profil = agents_etat.etat_unique(cnx, deps, profil, export=export) if profil else None
            historique = agents.historique(cnx, ident) if ident else []
            reservations_actives = (
                admission_agents.lister_reservations_actives(cnx, ident)
                if ident and profil
                else None
            )
            instance = ""
            grant = None
            if ident and profil and profil["departement"] == "m05-financecore":
                from .. import agent_cfo_grants

                if cnx.dialect.name == "sqlite":
                    instance = agent_cfo_grants.instance_id(cnx)
                    grant = agent_cfo_grants.lire(cnx, ident, instance_id=instance)
            en_attente = tableau_de_bord.nombre_en_attente(cnx, pages.PLAFOND_PASTILLE)
        corps = agents_ui.contenu(
            pilotage["agents"], deps, profil=profil, historique=historique, prefixe=prefixe, csrf=session.csrf,
            reservations_actives=reservations_actives, pilotage=pilotage, etat_profil=etat_profil,
        )
        if profil:
            corps += agents_ui.demandes_cron(profil, prefixe=prefixe, csrf=session.csrf)
        if profil and profil["departement"] == "m05-financecore":
            corps += agents_ui.grant_cfo(
                profil, grant, prefixe=prefixe, csrf=session.csrf, instance_configuree=bool(instance)
            )
        return html(session, "agents", "Configuration des agents", corps, en_attente, code, bandeau)

    def page_modeles(
        session: Session,
        code: int = 200,
        bandeau: pages.Bandeau | None = None,
        saisie: Mapping[str, Mapping[str, str]] | None = None,
    ) -> HTMLResponse:
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
        identifiant = champs.get("identifiant", "").strip()
        authentifiee = await run_in_threadpool(authentifier, identifiant, champs.get("mot_de_passe", ""))
        if authentifiee is None:
            logger.warning("échec de connexion pour %r", identifiant)
            page = pages.page_connexion(
                prefixe=prefixe, erreur="Identifiant ou mot de passe incorrect.", identifiant=identifiant
            )
            return HTMLResponse(page, status_code=401)
        try:
            session = securite.ouvrir_session(authentifiee.identifiant, authentifiee.roles, configuration.duree_session)
        except ValueError as exc:
            return HTMLResponse(
                pages.page_connexion(prefixe=prefixe, erreur=str(exc), identifiant=identifiant), status_code=400
            )
        reponse = RedirectResponse(f"{prefixe}/departements", status_code=303)
        reponse.set_cookie(
            securite.NOM_COOKIE,
            securite.signer_session(session, configuration.secret),
            max_age=configuration.duree_session,
            path=prefixe or "/",
            secure=configuration.cookie_securise,
            httponly=True,
            samesite="strict",
        )
        logger.info("connexion de %r", session.utilisateur)
        return reponse

    # -- pages authentifiées ---------------------------------------------------------------------
    @app.get("/memoire/audit")
    def audit_memoire(request: Request) -> HTMLResponse:
        from m10_memoire import developpement

        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, "le contrôle utilise les limites de la console")
        rapport = appeler_memoire(
            session, developpement.auditer_developpement, repository=memoire_api._repository(), limite=100
        )
        return HTMLResponse(
            pages.gabarit(
                "Contrôle de la mémoire",
                memoire_ui.audit_contenu(rapport, prefixe),
                prefixe=prefixe,
                session=session,
                actif="memoire",
            )
        )

    @app.get("/memoire")
    def memoire_page(
        request: Request, module: str = "M10", task: str = "mémoire développement", files: str = ""
    ) -> Response:
        from m10_memoire import developpement

        session = session_page(request)
        if module not in {"OPSYS", "CORE", *(f"M{i}" for i in range(1, 11))} or len(task) > 2000 or len(files) > 4000:
            raise HTTPException(400, "recherche mémoire invalide")
        statut = appeler_memoire(session, developpement.verifier_chaine)
        paquet = appeler_memoire(
            session,
            developpement.preflight,
            module,
            task,
            files=[f.strip() for f in files.splitlines() if f.strip()],
            repository=memoire_api._repository(),
        )
        with cnx_factory() as cnx:
            en_attente = tableau_de_bord.nombre_en_attente(cnx, pages.PLAFOND_PASTILLE)
        corps = memoire_ui.contenu(
            statut, paquet, prefixe=prefixe, csrf=session.csrf, module=module, task=task, files=files
        )
        return html(session, "memoire", "Mémoire de développement", corps, en_attente)

    @app.post("/memoire/scanner")
    async def memoire_scanner(request: Request) -> Response:
        from m10_memoire import developpement

        session = session_page(request)
        champs = await _formulaire(request)
        verifier_formulaire(champs, session)
        await run_in_threadpool(
            appeler_memoire,
            session,
            developpement.scanner_depot,
            memoire_api._repository(),
            horodatage=memoire_api._horodatage_serveur(),
        )
        return RedirectResponse(f"{prefixe}/memoire", status_code=303)

    @app.post("/budgets/agents")
    async def plafonds_agents_formulaire(request: Request) -> Response:
        session = session_page(request)
        champs = await _formulaire(request)
        verifier_formulaire(champs, session)
        try:
            corps = {cle: int(champs.get(cle, "")) for cle in ("budget_jour", "budget_mois", "revision_attendue")}
            await run_in_threadpool(ecrire_plafonds, corps, session)
        except (ValueError, PermissionError) as exc:
            raise HTTPException(_code(exc), _message(exc)) from exc
        return RedirectResponse(f"{prefixe}/budgets", status_code=303)

    @app.get("/agents")
    def agents_(request: Request, decalage: int = 0) -> Response:
        return page_agents(session_page(request), decalage=decalage)

    @app.get("/agents/{ident}")
    def agent_(ident: str, request: Request) -> Response:
        bandeau = None
        if request.query_params.get("rapprochement") == "declare":
            bandeau = ("Déclaration manuelle enregistrée; son contenu n’est pas vérifié par OPSYS.", "succes")
        return page_agents(session_page(request), ident, bandeau=bandeau)

    @app.post("/agents")
    @app.post("/agents/{ident}")
    async def agent_formulaire(request: Request, ident: str | None = None) -> Response:
        session = session_page(request)
        champs = await _formulaire(request)
        verifier_formulaire(champs, session)
        try:
            spec = agents_ui.specification(champs)
            commande = {"spec": spec, "mutation_id": champs.get("mutation_id", "")}
            action = "modifier" if ident else "creer"
            if ident:
                commande["revision_attendue"] = int(champs.get("revision_attendue", ""))
            resultat = await run_in_threadpool(muter_agent, action, ident, commande, session)
        except (ValueError, KeyError, PermissionError) as exc:
            return await run_in_threadpool(page_agents, session, ident, _code(exc), (_message(exc), "erreur"))
        return RedirectResponse(f"{prefixe}/agents/{quote(resultat['agent']['id'], safe='')}", status_code=303)

    async def _demande_intention_cron(ident: str, request: Request, *, retirer: bool) -> Response:
        session = session_page(request)
        if request.headers.get("content-type", "").lower() not in {
            "application/x-www-form-urlencoded", "application/x-www-form-urlencoded; charset=utf-8",
        }:
            raise HTTPException(400, "formulaire cron invalide")
        try:
            paires = parse_qs(
                (await _corps(request)).decode("utf-8", errors="strict"),
                keep_blank_values=True,
                max_num_fields=8,
                strict_parsing=True,
                encoding="utf-8",
                errors="strict",
            )
        except (UnicodeError, ValueError) as exc:
            raise HTTPException(400, "formulaire cron invalide") from exc
        if any(len(valeurs) != 1 for valeurs in paires.values()):
            raise HTTPException(400, "formulaire cron invalide")
        champs = {cle: valeurs[0] for cle, valeurs in paires.items()}
        verifier_formulaire(champs, session)
        attendus = {"csrf", "mutation_id", "revision_attendue", "confirme"}
        if not retirer:
            attendus.add("fuseau")
        if set(champs) != attendus or champs.get("confirme") != "oui":
            return await run_in_threadpool(
                page_agents, session, ident, 400,
                ("Formulaire de demande cron incomplet ou invalide.", "erreur"),
            )
        revision_brute = champs.get("revision_attendue", "")
        if not revision_brute.isascii() or not revision_brute.isdecimal() or len(revision_brute) > 16:
            return await run_in_threadpool(
                page_agents, session, ident, 400, ("Révision de profil invalide.", "erreur"),
            )
        revision = int(revision_brute)
        if not 1 <= revision <= 2**53 - 1:
            return await run_in_threadpool(
                page_agents, session, ident, 400, ("Révision de profil invalide.", "erreur"),
            )

        def effectuer() -> dict[str, Any]:
            identite_base = base_cron_operateur.verifier_base_cron_operateur(cnx_factory)

            def operation() -> dict[str, Any]:
                if retirer:
                    return agents_declencheurs.retirer(
                        deps, ident, par=session.utilisateur, revision_attendue=revision,
                        mutation_id=champs["mutation_id"],
                    )
                return agents_declencheurs.demander(
                    deps, ident, par=session.utilisateur, revision_attendue=revision,
                    fuseau=champs["fuseau"], mutation_id=champs["mutation_id"],
                )

            return base_cron_operateur.dans_base_cron_operateur(cnx_factory, identite_base, operation)

        try:
            resultat = await run_in_threadpool(effectuer)
            if resultat.get("execute") is not False:
                raise ValueError("le propriétaire n’a pas confirmé l’état inerte")
        except (ValueError, KeyError, PermissionError) as exc:
            return await run_in_threadpool(page_agents, session, ident, _code(exc), (_message(exc), "erreur"))
        action = "retrait demandé" if retirer else "demande préparée"
        return await run_in_threadpool(
            page_agents, session, ident, 200,
            (f"Cron : {action}. Aucune tâche Core n’a été créée ou exécutée.", "succes"),
        )

    @app.post("/agents/{ident}/declencheurs/cron/demander")
    async def agent_demander_cron(ident: str, request: Request) -> Response:
        return await _demande_intention_cron(ident, request, retirer=False)

    @app.post("/agents/{ident}/declencheurs/cron/retirer")
    async def agent_retirer_cron(ident: str, request: Request) -> Response:
        return await _demande_intention_cron(ident, request, retirer=True)

    @app.post("/agents/{ident}/reservations/{reservation_id}/concilier")
    async def agent_reservation_concilier(ident: str, reservation_id: str, request: Request) -> Response:
        session = session_page(request)
        champs = await _formulaire(request)
        verifier_formulaire(champs, session)
        try:
            total_brut = champs.get("tokens_reels", "")
            if not total_brut.isascii() or not total_brut.isdecimal() or len(total_brut) > 19:
                raise ValueError("le total déclaré doit être un entier décimal entre 0 et 2^63-1")
            total = int(total_brut)
            if total > (1 << 63) - 1:
                raise ValueError("le total déclaré dépasse la limite 64 bits")
            if champs.get("attestation") != "oui":
                raise ValueError("la déclaration du relevé final est requise")
            with cnx_factory() as cnx:
                verifier_administration(cnx, session)
                admission_agents.concilier_manuellement(
                    cnx,
                    reservation_id,
                    ident,
                    total,
                    par=session.utilisateur,
                    reference_releve=champs.get("reference_releve", ""),
                )
        except (ValueError, KeyError, PermissionError, admission_agents.AdmissionRefusee) as exc:
            return await run_in_threadpool(
                page_agents, session, ident, _code(exc), (_message(exc), "erreur")
            )
        return RedirectResponse(
            f"{prefixe}/agents/{quote(ident, safe='')}?rapprochement=declare", status_code=303
        )

    @app.post("/agents/{ident}/activation")
    async def agent_activation_formulaire(ident: str, request: Request) -> Response:
        session = session_page(request)
        champs = await _formulaire(request)
        verifier_formulaire(champs, session)
        try:
            if champs.get("actif") not in {"true", "false"}:
                raise ValueError("activation invalide")
            corps = {
                "actif": champs["actif"] == "true",
                "mutation_id": champs.get("mutation_id", ""),
                "revision_attendue": int(champs.get("revision_attendue", "")),
            }
            await run_in_threadpool(muter_agent, "activation", ident, corps, session)
        except (ValueError, KeyError, PermissionError) as exc:
            return await run_in_threadpool(page_agents, session, ident, _code(exc), (_message(exc), "erreur"))
        return RedirectResponse(f"{prefixe}/agents/{quote(ident, safe='')}", status_code=303)

    @app.post("/agents/{ident}/archivage")
    async def agent_archivage_formulaire(ident: str, request: Request) -> Response:
        session = session_page(request)
        champs = await _formulaire(request)
        verifier_formulaire(champs, session)
        try:
            corps = {
                "mutation_id": champs.get("mutation_id", ""),
                "revision_attendue": int(champs.get("revision_attendue", "")),
            }
            await run_in_threadpool(muter_agent, "supprimer", ident, corps, session)
        except (ValueError, KeyError, PermissionError) as exc:
            return await run_in_threadpool(page_agents, session, ident, _code(exc), (_message(exc), "erreur"))
        return RedirectResponse(f"{prefixe}/agents", status_code=303)

    @app.post("/agents/{ident}/droit-cfo")
    async def agent_grant_cfo(ident: str, request: Request) -> Response:
        session = session_page(request)
        champs = await _formulaire(request)
        verifier_formulaire(champs, session)
        try:
            from .. import agent_cfo_grants

            role = "nathan_owner" if "nathan_owner" in session.roles else "admin"
            identity = contexte.IdentiteAppelante(session.utilisateur, role, source="console")
            with contexte.appele_par_appareil(identity), cnx_factory() as cnx:
                agent_cfo_grants.accorder(
                    cnx,
                    ident,
                    par=session.utilisateur,
                    instance_id=agent_cfo_grants.instance_id(cnx),
                    revision_attendue=int(champs.get("revision_attendue", "")),
                    version_attendue=int(champs.get("version_grant_attendue", "")),
                    date_debut_rapport=champs.get("date_debut_rapport", ""),
                    date_fin_rapport=champs.get("date_fin_rapport", ""),
                    outils=[x.strip() for x in champs.get("outils", "").splitlines() if x.strip()],
                    rapports_par_jour=int(champs.get("rapports_par_jour", "3")),
                    expire_le=champs.get("expire_le") or None,
                )
        except (ValueError, KeyError, PermissionError) as exc:
            return await run_in_threadpool(page_agents, session, ident, _code(exc), (_message(exc), "erreur"))
        return RedirectResponse(f"{prefixe}/agents/{quote(ident, safe='')}", status_code=303)

    @app.post("/agents/{ident}/droit-cfo/retrait")
    async def agent_revoquer_cfo(ident: str, request: Request) -> Response:
        session = session_page(request)
        champs = await _formulaire(request)
        verifier_formulaire(champs, session)
        try:
            from .. import agent_cfo_grants

            role = "nathan_owner" if "nathan_owner" in session.roles else "admin"
            identity = contexte.IdentiteAppelante(session.utilisateur, role, source="console")
            with contexte.appele_par_appareil(identity), cnx_factory() as cnx:
                agent_cfo_grants.revoquer(
                    cnx,
                    ident,
                    par=session.utilisateur,
                    instance_id=agent_cfo_grants.instance_id(cnx),
                    version_attendue=int(champs.get("version_grant_attendue", "")),
                )
        except (ValueError, KeyError, PermissionError) as exc:
            return await run_in_threadpool(page_agents, session, ident, _code(exc), (_message(exc), "erreur"))
        return RedirectResponse(f"{prefixe}/agents/{quote(ident, safe='')}", status_code=303)

    @app.post("/deconnexion")
    async def deconnexion(request: Request) -> Response:
        session = session_page(request, administrateur=False)
        verifier_formulaire(await _formulaire(request), session)
        reponse = RedirectResponse(f"{prefixe}/connexion", status_code=303)
        reponse.delete_cookie(
            securite.NOM_COOKIE,
            path=prefixe or "/",
            secure=configuration.cookie_securise,
            httponly=True,
            samesite="strict",
        )
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
        attestation = _attestation_depuis_formulaire(champs)
        try:
            resultat = await run_in_threadpool(
                decider, ident, champs.get("decision", ""), champs.get("motif", ""), attestation, session
            )
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
        saisie = {cle: champs.get(cle, "") for cle in ("provider", "model", "base_url", "api_key_env")}
        saisie["fallbacks"] = [nom.strip() for nom in champs.get("fallbacks", "").split(",") if nom.strip()]
        try:
            await run_in_threadpool(ecrire_palier, palier, saisie, session)
        except ValueError as exc:
            return await run_in_threadpool(page_modeles, session, 400, (str(exc), "erreur"), {palier: saisie})
        return RedirectResponse(f"{prefixe}/modeles?ok=palier", status_code=303)

    # -- API JSON ----------------------------------------------------------------------------------
    @app.get("/api/agents-plafonds")
    def api_plafonds_agents(request: Request) -> dict[str, Any]:
        session = session_api(request)
        with cnx_factory() as cnx:
            verifier_administration(cnx, session)
            return {"plafonds": lire_plafonds(cnx)}

    @app.put("/api/agents-plafonds")
    async def api_configurer_plafonds_agents(request: Request) -> dict[str, Any]:
        session = ecriture_api(request)
        return await executer_api(ecrire_plafonds, await _objet_json(request), session)

    @app.get("/api/agents")
    def api_agents(
        request: Request, departement: str | None = None, limite: int = agents_etat.LIMITE_MAX, decalage: int = 0
    ) -> dict[str, Any]:
        session = session_api(request)
        try:
            agents_etat.valider_pagination(limite, decalage)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        with cnx_factory() as cnx:
            verifier_administration(cnx, session)
            return agents_etat.tableau(cnx, deps, departement=departement, limite=limite, decalage=decalage)

    @app.get("/api/agents/{ident}")
    def api_agent(ident: str, request: Request) -> dict[str, Any]:
        session = session_api(request)
        with cnx_factory() as cnx:
            verifier_administration(cnx, session)
            profil = agents.obtenir(cnx, ident)
            if profil is None:
                raise HTTPException(404, "profil inconnu")
            return {"agent": profil, "etat": agents_etat.etat_unique(cnx, deps, profil)}

    @app.get("/api/agents/{ident}/historique")
    def api_historique_agent(ident: str, request: Request) -> dict[str, Any]:
        session = session_api(request)
        with cnx_factory() as cnx:
            verifier_administration(cnx, session)
            if agents.obtenir(cnx, ident, inclure_supprime=True) is None:
                raise HTTPException(404, "profil inconnu")
            return {"historique": agents.historique(cnx, ident)}

    @app.post("/api/agents")
    async def api_creer_agent(request: Request) -> dict[str, Any]:
        session = ecriture_api(request)
        return await executer_api(muter_agent, "creer", None, await _objet_json(request), session)

    @app.patch("/api/agents/{ident}")
    async def api_modifier_agent(ident: str, request: Request) -> dict[str, Any]:
        session = ecriture_api(request)
        return await executer_api(muter_agent, "modifier", ident, await _objet_json(request), session)

    @app.post("/api/agents/{ident}/activation")
    async def api_activer_agent(ident: str, request: Request) -> dict[str, Any]:
        session = ecriture_api(request)
        return await executer_api(muter_agent, "activation", ident, await _objet_json(request), session)

    @app.delete("/api/agents/{ident}")
    async def api_supprimer_agent(ident: str, request: Request) -> dict[str, Any]:
        session = ecriture_api(request)
        return await executer_api(muter_agent, "supprimer", ident, await _objet_json(request), session)

    @app.get("/api/session")
    def api_session(request: Request) -> dict[str, Any]:
        session = session_api(request, administrateur=False)
        return {"utilisateur": session.utilisateur, "roles": sorted(session.roles), "csrf": session.csrf}

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

    @app.get("/api/approbations/file")
    def api_approbations_file(request: Request) -> dict[str, Any]:
        """File du propriétaire (ADR-0009 §5, PLAN T1.3-a §6) : demandes du socle en attente, plus
        les attentes déclarées par les départements (`opsys.approbations.file_proprietaire`)."""
        session_api(request)
        with cnx_factory() as cnx:
            return {"file": tableau_de_bord.file_proprietaire(cnx, deps)}

    @app.post("/api/approbations/{ident}/decision")
    async def api_decision(ident: str, request: Request) -> dict[str, Any]:
        session = ecriture_api(request)
        corps = await _objet_json(request)
        motif = corps.get("motif", "")
        if not isinstance(motif, str):
            raise HTTPException(400, "motif : texte attendu")
        attestation = corps.get("attestation")
        if attestation is not None and not isinstance(attestation, dict):
            raise HTTPException(400, "attestation : objet attendu")
        return await executer_api(decider, ident, corps.get("decision", ""), motif, attestation, session)

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
    parseur = argparse.ArgumentParser(
        prog="opsys-console", description="Console web OPSYS : départements, approbations, budgets, paliers"
    )
    parseur.add_argument("--hote", default=HOTE, help=f"adresse d'écoute (défaut : {HOTE})")
    parseur.add_argument("--port", type=int, default=PORT, help=f"port d'écoute (défaut : {PORT})")
    args = parseur.parse_args(argv)
    stockage.migrer()  # base de l'instance à jour avant la première approbation (ADR-0009)
    try:
        from .ocr_configuration import chemin_bundle

        choix_environ = os.environ if environ is None else environ
        application = creer_application(
            Configuration.depuis_environnement(choix_environ), bundle_ocr=chemin_bundle(choix_environ),
        )
    except (OSError, ValueError) as exc:
        print(f"opsys-console : {exc}", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    from .journaux_http import configuration_journaux

    uvicorn.run(application, host=args.hote, port=args.port, log_config=configuration_journaux())
    return 0
