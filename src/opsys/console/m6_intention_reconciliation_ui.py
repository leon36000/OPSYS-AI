"""Formulaire admin, sans identifiants dans l'URL, pour vérifier une intention M6 en lecture seule."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractContextManager
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import Connection

from ..secrets_coffre import masquage
from . import m6_intention_reconciliation, pages
from .securite import Session

BASE = "/materiaux/intention"
ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_CHAMPS = frozenset({"csrf", "appareil", "cle_idempotence"})
_RESULTATS = {
    "acceptee": (
        "Acceptée",
        "Le reçu conservé indique une acceptation. Cette vérification n’a rien rejoué.",
    ),
    "refusee": (
        "Refusée",
        "Le reçu conservé indique un refus. Cette vérification n’a rien rejoué.",
    ),
    "indeterminee": (
        "Indéterminée",
        (
            "Le reçu est absent ou ne permet pas de confirmer l’issue. Gardez la même intention et "
            "demandez une vérification avant tout nouvel envoi."
        ),
    ),
}


def _lire_champs(corps: bytes) -> dict[str, str]:
    try:
        texte = corps.decode("utf-8", errors="strict")
        valeurs = parse_qs(
            texte,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=4,
            encoding="utf-8",
            errors="strict",
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(400, "formulaire invalide") from exc
    if any(len(items) != 1 for items in valeurs.values()):
        raise HTTPException(400, "formulaire invalide")
    return {cle: items[0] for cle, items in valeurs.items()}


def _contenu(prefixe: str, csrf: str, etat: str | None = None) -> str:
    formulaire = (
        f'<form method="post" action="{pages.e(prefixe + BASE)}" class="pile carte">'
        f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">'
        '<label for="appareil">Identifiant de l’appareil</label>'
        '<input id="appareil" name="appareil" type="text" maxlength="128" required '
        'autocomplete="off" autocapitalize="none" spellcheck="false">'
        '<label for="cle-idempotence">Clé de l’intention</label>'
        '<input id="cle-idempotence" name="cle_idempotence" type="text" maxlength="128" required '
        'autocomplete="off" autocapitalize="none" spellcheck="false">'
        '<button type="submit" class="principal">Vérifier en lecture seule</button></form>'
    )
    resultat = ""
    if etat is not None:
        titre, explication = _RESULTATS.get(etat, _RESULTATS["indeterminee"])
        resultat = (
            '<section aria-live="polite" aria-label="Résultat de la vérification">'
            f'<h2>Résultat : {pages.e(titre)}</h2><p>{pages.e(explication)}</p></section>'
        )
    return (
        '<p>Utilisez l’identifiant d’appareil et la clé de la même intention, fournis par la personne '
        'qui utilise l’application. Un ID courant ne prouve pas l’origine : si l’appareil a été réinitialisé, '
        'confirmez l’identifiant à utiliser avec cette personne. Cette page lit le reçu existant et ne relance '
        'aucune déclaration.</p>'
        f'{formulaire}{resultat}'
        f'<p><a href="{pages.e(prefixe)}/commandes">Retour aux commandes</a></p>'
    )


def creer_router(
    *,
    session_page: Callable[[Request], Session],
    verifier_formulaire: Callable[[Mapping[str, str], Session], None],
    lire_corps: Callable[[Request], Awaitable[bytes]],
    cnx_factory: Callable[[], AbstractContextManager[Connection]],
    prefixe: str,
) -> APIRouter:
    router = APIRouter(tags=["réconciliation M6"])
    masquage.installer()

    def servir(session: Session, etat: str | None = None) -> HTMLResponse:
        html = pages.gabarit(
            "Vérifier une intention de matériaux",
            _contenu(prefixe, session.csrf, etat),
            prefixe=prefixe,
            session=session,
            actif="commandes",
        )
        if masquage.contient_secret(html):
            raise HTTPException(500, "rendu refusé : contenu sensible détecté")
        return HTMLResponse(html, headers=ENTETES)

    @router.get(BASE, response_class=HTMLResponse)
    def page(request: Request) -> Response:
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, "Paramètres invalides")
        return servir(session)

    @router.post(BASE, response_class=HTMLResponse)
    async def verifier(request: Request) -> Response:
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, "Paramètres invalides")
        type_contenu = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if type_contenu != "application/x-www-form-urlencoded":
            raise HTTPException(400, "formulaire invalide")
        champs = _lire_champs(await lire_corps(request))
        if set(champs) != _CHAMPS:
            raise HTTPException(400, "Champs invalides")
        verifier_formulaire(champs, session)
        with cnx_factory() as cnx:
            etat = m6_intention_reconciliation.lire_etat(
                cnx, champs["appareil"], champs["cle_idempotence"],
            )
        session = session_page(request)
        return servir(session, etat)

    return router
