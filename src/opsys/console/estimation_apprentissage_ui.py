"""Diagnostic M4→M3 natif de la console; aucune identité d'appareil fabriquée."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from importlib import import_module
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError

from opsys import stockage
from opsys.departements import Departement

from . import pages
from .securite import Session

CHEMIN = "/estimation/apprentissage/couverture"
MAX_REPONSE_OCTETS = 64 * 1024
_INDISPONIBLES = frozenset({
    "backend_source_non_qualifie", "transaction_lecture_requise", "sources_lecture_indisponibles",
})


def _contenu(rapport: Mapping[str, Any], prefixe: str) -> str:
    e = pages.e
    statut = {
        "univers_vide": "Aucune publication M4 dans l’univers lu; aucun succès de calibration déduit.",
        "ecarts": "Des identités ne se recoupent pas. Aucune cause d’écart n’est déduite.",
        "identites_recues": "Les identités publiées se retrouvent parmi les reçus M3.",
    }[rapport["statut"]]
    html = [
        '<section class="carte pile"><h2>Réception des chantiers M4 par M3</h2>',
        f'<p>{e(statut)}</p>',
        '<p>Complétude du corpus chantier : non prouvée. Contenu et provenance non attestés. '
        'Aucun barème activé; aucun gain de précision mesuré.</p><dl>',
    ]
    for cle, libelle in (
        ("publications_m4", "Publications M4"), ("recus_m3", "Reçus M3"),
        ("recoupes", "Identités recoupées"), ("manquants_m3", "Publications sans reçu M3"),
        ("hors_univers_m4", "Reçus hors de l’univers publié"),
    ):
        html.append(f'<dt>{e(libelle)}</dt><dd>{e(str(rapport["compteurs"][cle]))}</dd>')
    html.append('</dl></section>')
    for cle, titre in (
        ("manquants_m3", "Identités publiées sans reçu M3"),
        ("hors_univers_m4", "Identités reçues hors de l’univers publié"),
    ):
        section = rapport[cle]
        html.append(f'<section class="carte pile"><h2>{e(titre)}</h2><ul>')
        html.extend(f'<li>{e(ident)}</li>' for ident in section["exemples"])
        html.append('</ul>' if section["exemples"] else '</ul><p>Aucune identité dans cette catégorie.</p>')
        html.append(f'<p>Identités supplémentaires non affichées : {e(str(section["omis"]))}</p></section>')
    html.append('<section class="carte pile"><h2>Sources et limites</h2><dl>')
    for cle, valeur in rapport["sources"].items():
        html.append(f'<dt>{e(cle)}</dt><dd><code>{e(valeur)}</code></dd>')
    html.append('</dl><ul>')
    html.extend(f'<li>{e(limite)}</li>' for limite in rapport["limites"])
    html.append(
        '</ul><p>Les empreintes permettent de comparer une lecture; elles ne prouvent pas la mesure terrain.</p>'
        f'<p><a href="{e(prefixe + "/api" + CHEMIN)}">Consulter le diagnostic JSON</a> · '
        f'<a href="{e(prefixe + "/memoire/apprentissages-affaires")}">Aperçu des faits candidats M10</a>'
        '</p></section>'
    )
    return "".join(html)


def creer_router(
    *,
    session_page: Callable[[Request], Session],
    session_api: Callable[[Request], Session],
    cnx_factory: Callable[[], AbstractContextManager[Connection]],
    verifier_administration: Callable[[Connection, Session], None],
    revalider_administration: Callable[[Session], None],
    deps: Mapping[str, Departement],
    prefixe: str,
) -> APIRouter:
    router = APIRouter()

    def lire(request: Request, session: Session) -> dict[str, Any]:
        if request.query_params:
            raise HTTPException(400, "diagnostic sans paramètres de filtrage")
        dep = deps.get("m03-estimation")
        if dep is None or dep.module_outils != "m3_estimation.outils":
            raise HTTPException(503, "catalogue M3 indisponible")
        try:
            if "m3_auditer_couverture_apprentissage" not in {o.nom for o in dep.charger_outils()}:
                raise HTTPException(503, "catalogue M3 indisponible")
            outils = import_module("m3_estimation.outils")
            service = import_module("m3_estimation.couverture_apprentissage")
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(503, "catalogue M3 indisponible") from exc
        try:
            with cnx_factory() as cnx:
                if stockage.connexion_courante() is not cnx or not cnx.in_transaction():
                    raise HTTPException(503, "connexion_canonique_requise")

                def autorise() -> bool:
                    verifier_administration(cnx, session)
                    return True

                rapport = service.auditer(lire_prefixe=outils._prefixe_recu_wct, autorise=autorise)
                verifier_administration(cnx, session)
        except SQLAlchemyError as exc:
            raise HTTPException(503, "sources_lecture_indisponibles") from exc
        if rapport["statut"] == "refuse":
            raison = rapport["raison"]
            raise HTTPException(503 if raison in _INDISPONIBLES else 409, raison)
        return rapport

    def terminer(response: Response, session: Session) -> Response:
        if len(response.body) > MAX_REPONSE_OCTETS:
            raise HTTPException(413, "diagnostic hors plafond de réponse")
        # Après sérialisation/rendu : nouvelle lecture des droits actuels, sans cookie figé.
        revalider_administration(session)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response

    @router.get(CHEMIN, response_class=HTMLResponse)
    def couverture_html(request: Request) -> Response:
        session = session_page(request)
        rapport = lire(request, session)
        html = pages.gabarit(
            "Réception des chantiers et apprentissage M3", _contenu(rapport, prefixe),
            prefixe=prefixe, session=session, actif="connecteurs", en_attente=0,
        )
        return terminer(HTMLResponse(html), session)

    @router.get("/api" + CHEMIN, response_class=JSONResponse)
    def couverture_json(request: Request) -> Response:
        session = session_api(request)
        return terminer(JSONResponse(lire(request, session)), session)

    return router
