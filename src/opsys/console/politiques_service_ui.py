"""Console admin : opérateur des politiques de service M4 → M5 (D1, E4).

Octroyer, renouveler ou révoquer `m4.verifier_v3`, `m4.recalculer_v3` et `m4.relire_faits_pour_m5_v1` : session
console serveur, jeton CSRF, rôle `admin` relu en base à chaque geste (`service_politiques`), champs fermés, motif
obligatoire, journal append-only. Aucun outil d'agent ne mène ici.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import service_politiques as operateur
from . import pages, securite
from .securite import Session

_ENTETES = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
_LIBELLES = {
    "m4.verifier_v3": "Relire les faits M4 vérifiés pour M5",
    "m4.recalculer_v3": "Recalculer le coût certifié (moteur et réconciliateur automatique)",
    "m4.relire_faits_pour_m5_v1": "Revalider la lecture du coût par M5",
}
_STATUTS = {"active": "active", "expiree": "expirée", "revoquee": "révoquée", "absente": "jamais octroyée"}
_CODES_HTTP = {
    "ADMIN_REQUIS": 403, "SESSION_INVALIDE": 403, "APPEL_AGENT_INTERDIT": 403, "BACKEND_NON_QUALIFIE": 503,
    "CONTEXTE_INVALIDE": 503, "DEJA_ACTIVE": 409, "NON_RENOUVELABLE": 409, "DEJA_INACTIVE": 409,
}


def _date(epoch):
    return "" if epoch is None else datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d %H:%M UTC")


def creer_router(
    *,
    session_page: Callable[..., Session],
    session_api: Callable[..., Session],
    ecriture_api: Callable[..., Session],
    formulaire: Callable[[Request], Any],
    objet_json: Callable[[Request], Any],
    cnx_factory: Callable[[], Any],
    prefixe: str,
    **_autres: Any,
) -> APIRouter:
    router = APIRouter(tags=["politiques de service"])

    def _executer(session: Session, data: Mapping[str, Any] | None) -> dict[str, Any]:
        try:
            with cnx_factory() as cnx:
                if data is None:
                    return operateur.etat(cnx, session)
                if set(data) != {"action", "operation", "motif"}:
                    raise HTTPException(400, "champs : action, operation, motif")
                resultat = operateur.appliquer(cnx, session, data["action"], data["operation"],
                                               motif=data["motif"])
                return {"resultat": resultat, "etat": operateur.etat(cnx, session)}
        except operateur.RefusOperateur as exc:
            raise HTTPException(_CODES_HTTP.get(exc.code, 400), exc.code) from None
        except PermissionError:
            raise HTTPException(403, "Accès admin requis") from None

    @router.get("/api/administration/politiques-service")
    def lire(request: Request) -> JSONResponse:
        session = session_api(request)
        if request.query_params:
            raise HTTPException(400, "Paramètres invalides")
        return JSONResponse(_executer(session, None), headers=_ENTETES)

    @router.post("/api/administration/politiques-service")
    async def appliquer_api(request: Request) -> JSONResponse:
        session = ecriture_api(request)
        if request.query_params:
            raise HTTPException(400, "Paramètres invalides")
        data = await objet_json(request)
        if not isinstance(data, Mapping):
            raise HTTPException(400, "Objet JSON requis")
        return JSONResponse(_executer(session, data), headers=_ENTETES)

    @router.get("/administration/politiques-service", response_class=HTMLResponse)
    def page(request: Request) -> HTMLResponse:
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, "Paramètres invalides")
        vue = _executer(session, None)
        e = pages.e
        lignes = []
        for p in vue["politiques"]:
            actions = (("renouveler", "Renouveler 90 jours"), ("revoquer", "Révoquer maintenant")) if p["statut"] in (
                "active", "expiree") else (("octroyer", "Octroyer 90 jours"),)
            formulaires = "".join(
                f'<form method="post" action="{e(prefixe)}/administration/politiques-service">'
                f'<input type="hidden" name="csrf" value="{e(session.csrf)}">'
                f'<input type="hidden" name="operation" value="{e(p["operation"])}">'
                f'<input type="hidden" name="action" value="{e(action)}">'
                f'<label>Motif <input name="motif" required minlength="3" maxlength="500"></label>'
                f'<button type="submit">{e(libelle)}</button></form>'
                for action, libelle in actions)
            lignes.append(
                f'<tr><td><code>{e(p["operation"])}</code><br>{e(_LIBELLES[p["operation"]])}</td>'
                f'<td>{e(_STATUTS[p["statut"]])}</td><td>{e(p["revision"])}</td>'
                f'<td>{e(_date(p["expire_le"]))}</td><td>{formulaires}</td></tr>')
        journal = "".join(
            f'<tr><td>{e(_date(j["epoch"]))}</td><td><code>{e(j["operation"])}</code></td><td>{e(j["action"])}</td>'
            f'<td>{e(j["acteur"])}</td><td>{e(j["motif"])}</td><td>{e(_date(j["expire_le"]))}</td></tr>'
            for j in vue["journal"])
        corps = (
            "<p>Politiques de service du coût certifié M4 → M5 (consommateur <code>m05-financecore</code>). "
            f"Chaque octroi ou renouvellement expire après {vue['duree_jours']} jours ; la révocation est immédiate. "
            "Le recalcul automatique par l'acteur système <code>opsys-systeme</code> exige "
            "<code>m4.recalculer_v3</code> et <code>m4.verifier_v3</code> actives. "
            "Aucun agent ne peut octroyer ni révoquer.</p>"
            "<table><thead><tr><th>Politique</th><th>Statut</th><th>Révision</th><th>Expire le</th><th>Geste</th>"
            f"</tr></thead><tbody>{''.join(lignes)}</tbody></table>"
            "<h2>Journal</h2><table><thead><tr><th>Quand</th><th>Politique</th><th>Action</th><th>Par</th>"
            f"<th>Motif</th><th>Expiration</th></tr></thead><tbody>{journal}</tbody></table>")
        reponse = HTMLResponse(pages.gabarit("Politiques de service", corps, prefixe=prefixe, session=session))
        reponse.headers.update(_ENTETES)
        return reponse

    @router.post("/administration/politiques-service")
    async def appliquer_formulaire(request: Request) -> RedirectResponse:
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, "Paramètres invalides")
        champs = await formulaire(request)
        if not isinstance(champs, Mapping) or not securite.csrf_valide(champs.get("csrf"), session):
            raise HTTPException(403, "Jeton CSRF absent ou invalide")
        if set(champs) != {"csrf", "action", "operation", "motif"}:
            raise HTTPException(400, "Champs invalides")
        _executer(session, {k: champs[k] for k in ("action", "operation", "motif")})
        return RedirectResponse(f"{prefixe}/administration/politiques-service", status_code=303,
                                headers={"Cache-Control": "no-store"})

    return router
