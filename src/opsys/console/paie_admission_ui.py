"""Diagnostic documentaire propriétaire; aucun calcul ni autorisation de paie."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .. import identite
from . import metier, pages, securite

_CHAMPS = frozenset({"annee", "date_paie", "juridiction", "frequence", "periode_annuelle", "pm"})
_ENTIERS = {"annee": 9999, "periode_annuelle": 366, "pm": 12}
_OUTIL = "m5_verifier_admission_paie_preparatoire"


def _arguments(data: Any) -> dict[str, Any]:
    if not isinstance(data, Mapping) or set(data) != _CHAMPS:
        raise HTTPException(400, "les six champs du contexte documentaire sont requis")
    for cle, maximum in _ENTIERS.items():
        if type(data[cle]) is not int or not 1 <= data[cle] <= maximum:
            raise HTTPException(400, f"{cle} invalide")
    for cle, maximum in {"date_paie": 10, "juridiction": 8, "frequence": 32}.items():
        if not isinstance(data[cle], str) or not 1 <= len(data[cle]) <= maximum:
            raise HTTPException(400, f"{cle} invalide")
    try:
        if date.fromisoformat(data["date_paie"]).isoformat() != data["date_paie"]:
            raise ValueError("date non canonique")
    except ValueError as exc:
        raise HTTPException(400, "date de paie au format AAAA-MM-JJ requise") from exc
    return dict(data)


def creer_router(*, session_page, session_api, formulaire, objet_json, cnx_factory, deps, prefixe) -> APIRouter:
    router = APIRouter(tags=["diagnostic documentaire paie"])

    def owner(cnx, session):
        personne = identite.personne_active(cnx, session.utilisateur)
        if (session.expire <= datetime.now(UTC).timestamp() or personne is None
                or "nathan_owner" not in personne.roles):
            raise HTTPException(403, "diagnostic de paie réservé au propriétaire actif")

    def diagnostic(session, arguments):
        with cnx_factory() as cnx:
            owner(cnx, session)
            reponse = metier.executer(cnx, deps, session, _OUTIL, arguments)
            owner(cnx, session)
        return reponse

    def page(session, reponse=None):
        contenu = (
            "<p>Vérifier les préconditions documentaires pour la paie préparatoire. "
            "Ce diagnostic ne valide pas les règles fiscales et n’autorise aucune paie ou opération financière.</p>"
            "<p>Contexte proposé : Québec 2026, fréquence bihebdomadaire (26 périodes).</p>"
            f'<form class="pile carte" method="post" action="{pages.e(prefixe)}/finance/paie/admission">'
            f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
            '<input type="hidden" name="annee" value="2026">'
            '<input type="hidden" name="juridiction" value="QC">'
            '<input type="hidden" name="frequence" value="bihebdomadaire">'
            '<input type="hidden" name="pm" value="12">'
            '<label>Date de paie<input name="date_paie" type="date" required></label>'
            '<label>Numéro de période annuelle<input name="periode_annuelle" type="number" '
            'min="1" max="26" required></label>'
            '<button type="submit">Vérifier les préconditions documentaires</button></form>'
        )
        if reponse is not None:
            enveloppe = reponse.get("resultat")
            resultat = enveloppe.get("resultat") if isinstance(enveloppe, Mapping) else None
            if (not isinstance(enveloppe, Mapping) or enveloppe.get("accepte") is not True
                    or not isinstance(resultat, Mapping)):
                contenu += '<p class="message message-erreur">Diagnostic indisponible.</p>'
            else:
                etat = "satisfaites" if resultat.get("admissible") is True else "non satisfaites"
                motifs = resultat.get("motifs", [])
                sources = resultat.get("sources_verifiees", [])
                contenu += (
                    '<section class="carte pile"><h2>Résultat documentaire</h2>'
                    f'<p>Préconditions documentaires {etat}.</p>'
                    f'<p>{pages.e(resultat.get("qualification_regles"))}</p>'
                    '<p>Actions financières bloquées. Aucune autorisation d’outil ou d’acteur accordée.</p>'
                    '<h3>Pièces vérifiées</h3><ul>'
                    + "".join(f"<li>{pages.e(s)}</li>" for s in sources)
                    + '</ul><h3>Préconditions à régler</h3><ul>'
                    + "".join(f"<li>{pages.e(m)}</li>" for m in motifs) + '</ul></section>'
                )
        return HTMLResponse(
            pages.gabarit("Préconditions documentaires de paie", contenu,
                          prefixe=prefixe, session=session, actif="finance"),
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/finance/paie/admission")
    def afficher(request: Request):
        session = session_page(request, administrateur=False)
        with cnx_factory() as cnx:
            owner(cnx, session)
        return page(session)

    @router.post("/finance/paie/admission")
    async def verifier_formulaire(request: Request):
        session = session_page(request, administrateur=False)
        with cnx_factory() as cnx:
            owner(cnx, session)
        data = await formulaire(request)
        if not securite.csrf_valide(data.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        if set(data) != _CHAMPS | {"csrf"}:
            raise HTTPException(400, "champs du formulaire documentaire invalides")
        arguments = {cle: data[cle] for cle in _CHAMPS}
        for cle in _ENTIERS:
            value = arguments[cle]
            if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or len(value) > 4:
                raise HTTPException(400, f"{cle} invalide")
            arguments[cle] = int(value)
        return page(session, diagnostic(session, _arguments(arguments)))

    @router.post("/api/finance/paie/admission")
    async def verifier_json(request: Request):
        session = session_api(request, administrateur=False)
        with cnx_factory() as cnx:
            owner(cnx, session)
        if not securite.csrf_valide(request.headers.get("x-csrf-token"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        arguments = _arguments(await objet_json(request))
        return JSONResponse(diagnostic(session, arguments), headers={"Cache-Control": "no-store"})

    return router
