"""Console « Onboarding » : suivi en LECTURE des lots d'ingestion (documents, tâches, brouillons).

Lecture seule, métadonnées seulement : statuts, types, classes, codes de refus, compteurs, raisons (codes) des
brouillons. Aucun contenu de document, aucun montant ni nom de client n'est rendu ici ; la décision sur un brouillon
passe par la file d'approbation (outils `m5_valider_brouillon_onboarding_ap`, `m2_valider_brouillon_onboarding_client`).
Session obligatoire, rôle d'administration relu en base avant ET après la lecture (même règle que la Plateforme),
`Cache-Control: no-store`.

Routes : /onboarding, /onboarding/lots/{lot_id} (pages) ; /api/onboarding/lots, /api/onboarding/lots/{lot_id} (JSON).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..ingestion_onboarding import service
from ..ingestion_onboarding.codes import IngestionErreur
from . import pages
from .securite import Session

ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _compteurs(compteurs: Mapping[str, Mapping[str, int]]) -> str:
    morceaux = []
    for famille in ("documents", "taches", "brouillons"):
        valeurs = ", ".join(f"{pages.e(k)} {int(v)}" for k, v in sorted(compteurs[famille].items())) or "aucun"
        morceaux.append(f"<li>{pages.e(famille)} : {valeurs}</li>")
    return "<ul>" + "".join(morceaux) + "</ul>"


def contenu_lots(lots: Sequence[Mapping[str, Any]], *, prefixe: str) -> str:
    if not lots:
        return "<p>Aucun lot d'onboarding. Déposer les fichiers dans &lt;OPSYS_HOME&gt;/imports/onboarding/ puis " \
               "<code>opsys metier onboarding deposer</code>.</p>"
    lignes = "".join(
        f'<tr><td><a href="{pages.e(prefixe)}/onboarding/lots/{pages.e(lot["lot_id"])}">{pages.e(lot["nom_source"])}'
        f'</a></td><td>{pages.e(lot["statut"])}</td><td>{int(lot["nb_documents"])}</td>'
        f'<td>{pages.e(lot["cree_le"][:19])}</td></tr>' for lot in lots)
    return ("<table><thead><tr><th>Dépôt</th><th>Statut</th><th>Documents</th><th>Créé le</th></tr></thead>"
            f"<tbody>{lignes}</tbody></table>")


def contenu_lot(lot: Mapping[str, Any]) -> str:
    documents = "".join(
        f'<tr><td>{int(d["rang"])}</td><td>{pages.e(d["nom"])}</td><td>{pages.e(d["type_detecte"] or "—")}</td>'
        f'<td>{pages.e(d["classe"] or "—")}</td><td>{pages.e(d["statut"])}</td><td>{pages.e(d["code"] or "")}</td>'
        "</tr>" for d in lot["documents"])
    brouillons = "".join(
        f'<tr><td><code>{pages.e(b["brouillon_id"])}</code></td><td>{pages.e(b["genre"])}</td>'
        f'<td>{pages.e(b["statut"])}</td><td>{pages.e(", ".join(b["raisons"]))}</td><td>{int(b["revision"])}</td>'
        f'<td>{pages.e(b["reference_definitive"] or "")}</td></tr>' for b in lot["brouillons"])
    return (
        f"<p>Statut : {pages.e(lot['statut'])} · empreinte {pages.e(lot['source_sha256'][:16])}…</p>"
        f"{_compteurs(lot['compteurs'])}"
        "<h2>Documents</h2><table><thead><tr><th>#</th><th>Nom</th><th>Type</th><th>Classe</th><th>Statut</th>"
        f"<th>Code</th></tr></thead><tbody>{documents}</tbody></table>"
        "<h2>Brouillons</h2><p>Aucun n'est définitif : chacun se décide dans la file d'approbation.</p>"
        "<table><thead><tr><th>Brouillon</th><th>Genre</th><th>Statut</th><th>Raisons</th><th>Révision</th>"
        f"<th>Référence définitive</th></tr></thead><tbody>{brouillons}</tbody></table>"
    )


def creer_router(*, session_page: Callable[..., Session], session_api: Callable[..., Session],
                 cnx_factory: Callable[[], Any], prefixe: str) -> APIRouter:
    router = APIRouter(tags=["onboarding"])

    def lire_lot(lot_id: str) -> dict[str, Any]:
        try:
            with cnx_factory() as cnx:
                documents = service.lire_lot(cnx, lot_id, vue="documents", limite=50)
                brouillons = service.lire_lot(cnx, lot_id, vue="brouillons", limite=50)
                return {**documents, "brouillons": brouillons["brouillons"]}
        except IngestionErreur as exc:
            raise HTTPException(exc.statut_http if exc.statut_http in (404, 422) else 409, exc.code) from None

    @router.get("/onboarding", response_class=HTMLResponse)
    def page_lots(request: Request) -> Response:
        session = session_page(request)
        with cnx_factory() as cnx:
            lots = service.lister_lots(cnx)
        session_page(request)
        return HTMLResponse(pages.gabarit("Onboarding — lots", contenu_lots(lots, prefixe=prefixe), prefixe=prefixe,
                                          session=session), headers=ENTETES)

    @router.get("/onboarding/lots/{lot_id}", response_class=HTMLResponse)
    def page_lot(request: Request, lot_id: str) -> Response:
        session = session_page(request)
        lot = lire_lot(lot_id)
        session_page(request)
        return HTMLResponse(pages.gabarit(f"Onboarding — {lot['nom_source']}", contenu_lot(lot), prefixe=prefixe,
                                          session=session), headers=ENTETES)

    @router.get("/api/onboarding/lots")
    def api_lots(request: Request) -> Response:
        session_api(request)
        with cnx_factory() as cnx:
            lots = service.lister_lots(cnx)
        session_api(request)
        return JSONResponse({"lots": lots}, headers=ENTETES)

    @router.get("/api/onboarding/lots/{lot_id}")
    def api_lot(request: Request, lot_id: str) -> Response:
        session_api(request)
        lot = lire_lot(lot_id)
        session_api(request)
        return JSONResponse(lot, headers=ENTETES)

    return router
