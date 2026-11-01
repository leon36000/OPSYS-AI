"""Console « Observabilité » : coût et latence par département, tirés du journal de traces, en LECTURE seule.

Mêmes gardes que la console Plateforme : session obligatoire, rôle `nathan_owner`/`admin` RELU EN BASE avant ET après la
lecture, `Cache-Control: no-store`, aucune écriture, aucun formulaire. Le journal est ouvert en lecture seule (sans
clé) :
la page ne peut ni écrire, ni purger, ni vérifier la chaîne (voir `opsys-metier traces verifier`). Les montants sont des
ESTIMATIONS d'après les tarifs configurés, jamais la facture d'un fournisseur ; un coût inconnu est compté à part.
Avant d'être servie, la page est contrôlée comme celles de la Plateforme : un secret détecté = 500.

Routes : /observabilite (page, `?jours=N`) ; /api/observabilite (JSON).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import identite
from ..observabilite import tableaux
from ..observabilite.traces import JournalTraces, lire_spans
from ..secrets_coffre import masquage
from . import pages
from .securite import Session

ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache"}
ROLES_ADMIN = frozenset({"nathan_owner", "admin"})
JOURS_MAX = 90


def contenu(lignes: list[tableaux.LigneDepartement], refus: list[tuple[str, int]], jours: int) -> str:
    if not lignes:
        return f"<p>Aucune trace enregistrée sur les {jours} derniers jours.</p>"
    corps = "".join(
        f"<tr><td>{pages.e(ln.departement)}</td><td>{ln.appels_outils}</td><td>{ln.tours_agent}</td>"
        f"<td>{ln.refus} ({pages.e(ln.taux_refus)})</td><td>{ln.attentes_approbation}</td><td>{ln.erreurs}</td>"
        f"<td>{ln.latence_p50_ms if ln.latence_p50_ms is not None else '—'}</td>"
        f"<td>{ln.latence_p95_ms if ln.latence_p95_ms is not None else '—'}</td>"
        f"<td>{ln.latence_max_ms if ln.latence_max_ms is not None else '—'}</td>"
        f"<td>{ln.jetons_entree} / {ln.jetons_sortie}</td><td>{pages.e(ln.cout_estime_usd)}</td>"
        f"<td>{ln.spans_sans_cout}</td></tr>" for ln in lignes)
    codes = "".join(f"<li><code>{pages.e(code)}</code> × {n}</li>" for code, n in refus) or "<li>Aucun refus.</li>"
    return (
        f"<p>Période : {jours} derniers jours. Lecture seule. Les coûts sont des <strong>estimations</strong> "
        "d'après les tarifs configurés, pas la facture du fournisseur ; « Sans coût » compte les tours dont le coût "
        "est inconnu.</p>"
        "<table><thead><tr><th>Département</th><th>Appels d'outils</th><th>Tours d'agent</th><th>Refus</th>"
        "<th>En attente</th><th>Erreurs</th><th>p50 ms</th><th>p95 ms</th><th>max ms</th><th>Jetons (e/s)</th>"
        f"<th>Coût estimé USD</th><th>Sans coût</th></tr></thead><tbody>{corps}</tbody></table>"
        f"<h2>Refus les plus fréquents</h2><ul>{codes}</ul>"
        "<p>L'intégrité du journal se vérifie en ligne de commande : <code>opsys-metier traces verifier</code>.</p>"
    )


def creer_router(*, session_page: Callable[..., Session], session_api: Callable[..., Session],
                 cnx_factory: Callable[[], Any], prefixe: str, dossier_traces: Callable[[], Path]) -> APIRouter:
    router = APIRouter(tags=["observabilite"])
    masquage.installer()

    def exiger_admin(session: Session) -> None:
        with cnx_factory() as cnx:
            personne = identite.personne_active(cnx, session.utilisateur)
        if personne is None or not personne.roles.intersection(ROLES_ADMIN):
            raise HTTPException(403, "administration requise")

    def lire(session: Session, jours: int) -> tuple[list[tableaux.LigneDepartement], list[tuple[str, int]]]:
        exiger_admin(session)
        depuis = (dt.datetime.now(dt.UTC) - dt.timedelta(days=jours)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        spans = lire_spans(JournalTraces.lecture_seule(dossier_traces()), depuis=depuis)
        return tableaux.agreger(spans), tableaux.refus_par_code(spans)

    def borne(valeur: str | None) -> int:
        try:
            return max(1, min(int(valeur or "7"), JOURS_MAX))
        except ValueError:
            raise HTTPException(422, "jours : entier de 1 à 90") from None

    @router.get("/observabilite", response_class=HTMLResponse)
    def page(request: Request) -> Response:
        session = session_page(request)
        jours = borne(request.query_params.get("jours"))
        lignes, refus = lire(session, jours)
        session_page(request)
        html = pages.gabarit("Observabilité — coût et latence", contenu(lignes, refus, jours), prefixe=prefixe,
                             session=session, actif="observabilite")
        if masquage.contient_secret(html):
            raise HTTPException(500, "rendu refusé : contenu sensible détecté")
        return HTMLResponse(html, headers=ENTETES)

    @router.get("/api/observabilite")
    def api(request: Request) -> Response:
        session = session_api(request)
        jours = borne(request.query_params.get("jours"))
        lignes, refus = lire(session, jours)
        session_api(request)
        return JSONResponse(masquage.masquer({"ok": True, "jours": jours, **tableaux.vers_json(lignes, refus)}),
                            headers=ENTETES)

    return router
