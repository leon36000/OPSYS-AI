"""Console « Courriel » : état des connecteurs en LECTURE — connexion, dernier synchro, erreurs typées, brouillons
d'envoi.

Lecture seule, métadonnées seulement : état du compte, fournisseur, portées accordées, consentement (Loi 25), dernier
synchro, dernier CODE d'erreur typé (`REJ-COURRIEL-…`), compteurs, journal sans contenu, statut des brouillons sortants
(jamais leur texte, leurs destinataires ni leur objet). Aucun jeton, aucun mot de passe, aucun contenu de courriel n'est
rendu ici. La connexion d'un compte, la décision d'envoi (N3) et la révocation passent par le service et la file
d'approbation. Session obligatoire, rôle d'administration relu en base avant ET après la lecture, `Cache-Control:
no-store`.

Routes : /courriel, /courriel/comptes/{compte_id} (pages) ; /api/courriel/comptes, /api/courriel/comptes/{compte_id}
(JSON). """

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import select

from ..courriel_connecteurs import comptes
from ..courriel_connecteurs.erreurs import ErreurCourriel
from ..stockage.schema import COURRIEL_BROUILLONS
from . import pages
from .securite import Session

ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_COMPTE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_LIBELLES_ETAT = {
    "non_connecte": "Non connecté", "autorisation_en_cours": "Autorisation en cours", "connecte": "Connecté",
    "reconnexion_requise": "Reconnexion requise", "revoque": "Révoqué", "erreur": "Erreur",
}


def contenu_comptes(liste: Sequence[Mapping[str, Any]], *, prefixe: str) -> str:
    if not liste:
        return "<p>Aucun compte courriel. Les comptes se créent et se connectent par le service d'administration.</p>"
    lignes = "".join(
        f'<tr><td><a href="{pages.e(prefixe)}/courriel/comptes/{pages.e(c["compte_id"])}">'
        f'{pages.e(c["compte_id"])}</a></td>'
        f'<td>{pages.e(c["fournisseur"])}</td><td>{pages.e(c["adresse"])}</td>'
        f'<td>{pages.e(_LIBELLES_ETAT.get(c["etat"], c["etat"]))}</td>'
        f'<td>{pages.e((c["derniere_synchro_le"] or "jamais")[:19])} {pages.e(c["derniere_synchro_statut"] or "")}</td>'
        f'<td><code>{pages.e(c["derniere_erreur_code"] or "")}</code></td><td>{int(c["messages_total"])}</td></tr>'
        for c in liste)
    return ("<table><thead><tr><th>Compte</th><th>Fournisseur</th><th>Adresse</th><th>État</th><th>Dernier synchro</th>"
            f"<th>Dernière erreur</th><th>Messages</th></tr></thead><tbody>{lignes}</tbody></table>")


def contenu_compte(c: Mapping[str, Any]) -> str:
    journal = "".join(
        f'<tr><td>{pages.e(j["quand"][:19])}</td><td>{pages.e(j["evenement"])}</td>'
        f'<td><code>{pages.e(j["code"] or "")}</code></td>'
        f'<td>{pages.e(j["acteur"])}</td></tr>' for j in c["journal"])
    brouillons = "".join(
        f'<tr><td><code>{pages.e(b["brouillon_id"])}</code></td><td>{int(b["revision"])}</td><td>{pages.e(b["statut"])}</td>'
        f'<td>{pages.e(b["approuve_par"] or "")}</td><td><code>{pages.e(b["code"] or "")}</code></td></tr>'
        for b in c["brouillons"])
    consentement = (f"consigné le {pages.e(c['consentement_le'][:19])} par {pages.e(c['consentement_par'] or '')}"
                    if c["consentement_le"] else "NON consigné")
    return (
        f"<p>État : <strong>{pages.e(_LIBELLES_ETAT.get(c['etat'], c['etat']))}</strong> · "
        f"fournisseur {pages.e(c['fournisseur'])} · "
        f"usage {pages.e(c['usage'])}</p>"
        f"<ul><li>Finalité : {pages.e(c['finalite'])}</li><li>Consentement (Loi 25) : {consentement}</li>"
        f"<li>Rétention déclarée : {int(c['retention_jours'])} jours</li>"
        f"<li>Portées accordées : {pages.e(', '.join(c['portees']) or 'aucune')}</li>"
        f"<li>Dossiers suivis : {pages.e(', '.join(c['dossiers_suivis']))}</li>"
        f"<li>Dernier synchro : {pages.e((c['derniere_synchro_le'] or 'jamais')[:19])} "
        f"{pages.e(c['derniere_synchro_statut'] or '')}"
        f" · erreur : <code>{pages.e(c['derniere_erreur_code'] or 'aucune')}</code></li></ul>"
        "<h2>Brouillons d'envoi</h2><p>Aucun n'est transmis sans approbation humaine (N3) : voir la file "
        "d'approbation. "
        "Le texte n'est pas affiché ici.</p>"
        "<table><thead><tr><th>Brouillon</th><th>Révision</th><th>Statut</th><th>Approuvé par</th><th>Code</th>"
        "</tr></thead>"
        f"<tbody>{brouillons}</tbody></table>"
        "<h2>Journal (sans contenu de courriel)</h2><table><thead><tr><th>Quand</th><th>Événement</th><th>Code</th>"
        f"<th>Acteur</th></tr></thead><tbody>{journal}</tbody></table>"
    )


def creer_router(*, session_page: Callable[..., Session], session_api: Callable[..., Session],
                 cnx_factory: Callable[[], Any], prefixe: str) -> APIRouter:
    router = APIRouter(tags=["courriel"])

    def lire(session: Session) -> list[dict[str, Any]]:
        try:
            with cnx_factory() as cnx:
                comptes.exiger_admin(cnx, session.utilisateur)
                return comptes.lister(cnx)
        except ErreurCourriel as exc:
            raise HTTPException(403, exc.code) from None

    def lire_compte(session: Session, compte_id: str) -> dict[str, Any]:
        if not _COMPTE.fullmatch(compte_id):
            raise HTTPException(422, "REJ-COURRIEL-ARGUMENT-INVALIDE")
        try:
            with cnx_factory() as cnx:
                comptes.exiger_admin(cnx, session.utilisateur)
                vue = comptes.lire(cnx, compte_id)
                brouillons = [dict(r) for r in cnx.execute(select(
                    COURRIEL_BROUILLONS.c.brouillon_id, COURRIEL_BROUILLONS.c.revision, COURRIEL_BROUILLONS.c.statut,
                    COURRIEL_BROUILLONS.c.approuve_par, COURRIEL_BROUILLONS.c.code).where(
                    COURRIEL_BROUILLONS.c.compte_id == compte_id).order_by(
                    COURRIEL_BROUILLONS.c.cree_le.desc()).limit(50)
                ).mappings()]
                journal = [{k: j[k] for k in ("quand", "evenement", "code", "acteur")}
                           for j in comptes.journal(cnx, compte_id, 50)]
        except ErreurCourriel as exc:
            raise HTTPException(404 if exc.statut_http == 404 else 403, exc.code) from None
        return {**vue, "brouillons": brouillons, "journal": journal}

    @router.get("/courriel", response_class=HTMLResponse)
    def page_comptes(request: Request) -> Response:
        session = session_page(request)
        liste = lire(session)
        session_page(request)
        return HTMLResponse(pages.gabarit("Courriel — connecteurs", contenu_comptes(liste, prefixe=prefixe),
                                          prefixe=prefixe,
                                          session=session), headers=ENTETES)

    @router.get("/courriel/comptes/{compte_id}", response_class=HTMLResponse)
    def page_compte(request: Request, compte_id: str) -> Response:
        session = session_page(request)
        compte = lire_compte(session, compte_id)
        session_page(request)
        return HTMLResponse(pages.gabarit(f"Courriel — {compte['compte_id']}", contenu_compte(compte), prefixe=prefixe,
                                          session=session), headers=ENTETES)

    @router.get("/api/courriel/comptes")
    def api_comptes(request: Request) -> Response:
        session = session_api(request)
        liste = lire(session)
        session_api(request)
        return JSONResponse({"comptes": liste}, headers=ENTETES)

    @router.get("/api/courriel/comptes/{compte_id}")
    def api_compte(request: Request, compte_id: str) -> Response:
        session = session_api(request)
        compte = lire_compte(session, compte_id)
        session_api(request)
        return JSONResponse(compte, headers=ENTETES)

    return router
