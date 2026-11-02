"""Console « Wallboards » (M8.8) : tableaux de bord en direct, en LECTURE seule, accessibles, rafraîchis par flux SSE
borné
avec repli sur interrogation.

Les définitions, l'évaluation et la règle de fraîcheur sont celles de M8 (`m8_lire_wallboard`, outil T0/N0 réservé à
l'admin) :
cette page ne calcule rien et n'invente aucun état. Une mesure périmée, de fraîcheur inconnue ou non calculable est
montrée comme
telle EN TOUTES LETTRES (et par un symbole et un motif, jamais par la couleur seule) ; la bannière ne dit jamais «
tout va bien »
tant qu'une tuile l'est.

Gardes (mêmes que la console Plateforme) : session obligatoire, rôle `admin` RELU EN BASE avant ET après chaque
lecture, en-têtes
`no-store`, aucune écriture, aucun formulaire. Le flux SSE relit session et rôle à CHAQUE envoi, se ferme de lui-même
après
`flux_max` envois (le navigateur se reconnecte) et rend une `fin` motivée à la perte de session ou de rôle. Avant
d'être servie,
chaque page est contrôlée comme celles de la Plateforme : un secret détecté = 500. Aucune donnée personnelle : les
tuiles portent
des mesures d'entreprise.

Routes : /wallboards (liste) ; /wallboards/{id} (page, `?tv=1` pour le mode télé) ; /api/wallboards/{id} (JSON) ;
/api/wallboards/{id}/flux (SSE : `instantane` puis, à la fermeture, `fin`).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from .. import identite
from ..secrets_coffre import masquage
from . import metier, pages
from .securite import Session

ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_IDENTIFIANT = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_PAGES_MAX = 6
_ICONES = {"normal": "✔", "attention": "▲", "critique": "✖", "indetermine": "?", "sans_seuil": "•"}


def _maintenant() -> str:
    """L'instant du serveur (RFC 3339 avec fuseau) : M8 n'a pas d'horloge, c'est la console qui donne `maintenant`.
    Les tests
    remplacent cette fonction (résolue à l'appel, jamais figée à l'import)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _dormir(secondes: float) -> None:
    time.sleep(secondes)


def _pastille_html(t: Mapping[str, Any]) -> str:
    """La pastille de confiance de la tuile (FRESH, STALE, PARTIAL, MISSING, QUALITY_FAIL, GATED), dite en toutes
    lettres et jamais par la seule couleur : le code est dans le texte et dans la classe. Une tuile sans pastille
    (donnée qui ne
    vient pas de M8) n'en montre aucune, plutôt qu'une pastille devinée."""
    code, libelle = t.get("pastille"), t.get("libelle_pastille")
    if not isinstance(code, str) or not isinstance(libelle, str):
        return ""
    return (
        f'<p class="pastille-ligne"><span class="pastille pastille-{pages.e(code)}" data-champ="pastille">'
        f"{pages.e(libelle)} ({pages.e(code)})</span></p>"
    )


def _tuile_html(t: Mapping[str, Any]) -> str:
    identifiant = pages.e(t["id"])
    icone = _ICONES.get(t["etat_seuil"], "•")
    if t["fraicheur"] in ("perime", "inconnu", "manquant"):
        icone = "⏱" if t["fraicheur"] == "perime" else "?"
    if t.get("qualite_en_echec") is True:
        icone = "⛔"
    detail = f"Dernier fait il y a {t['age_affiche']}" if t.get("age_affiche") else "Aucun âge connu"
    # Une valeur calculée sur une partie seulement de ce qu'elle devrait couvrir le dit sur la tuile (jamais complète).
    partielle = " · couverture partielle" if t.get("partielle") is True else ""
    return (
        f'<li class="tuile etat-{pages.e(t["etat_seuil"])} fraicheur-{pages.e(t["fraicheur"])}'
        f'{" qualite-echec" if t.get("qualite_en_echec") is True else ""}" '
        f'data-tuile="{identifiant}" '
        f'data-page="{int(t["page"])}"><article aria-labelledby="t-{identifiant}">'
        f'<h2 id="t-{identifiant}">{pages.e(t["titre"])}</h2>'
        f'<p class="valeur" data-champ="valeur">{pages.e(t["valeur_affichee"])}</p>'
        # La pastille (FRESH, STALE, PARTIAL, MISSING, QUALITY_FAIL, GATED) est DITE en toutes lettres, jamais par la
        # seule couleur : le code est dans le texte et dans la classe.
        f"{_pastille_html(t)}"
        f'<p class="etat"><span aria-hidden="true">{icone}</span> <span data-champ="etat">'
        f"{pages.e(t['libelle_fraicheur'])} · {pages.e(t['libelle_seuil'])}{partielle}</span></p>"
        f'<p class="detail" data-champ="detail">{pages.e(detail)}</p>'
        f'<p class="detail">Source : {pages.e(t["source"] or "aucune")}</p></article></li>'
    )


def rendre_page(etat: Mapping[str, Any], *, prefixe: str, tv: bool, session: Session | None = None) -> str:
    """La page d'un wallboard : rendu serveur complet (la page sert sans script), le script ne fait que la
    rafraîchir."""
    wb = etat["wallboard"]
    ident = pages.e(wb["id"])
    rafraichissement = etat["rafraichissement"]
    rotation = etat["rotation"]
    banniere = etat["banniere"]
    messages = "".join(f"<p>{pages.e(m)}</p>" for m in banniere["messages"])
    tuiles = "".join(_tuile_html(t) for t in etat["tuiles"])
    api = f"{prefixe}/api/wallboards/{ident}"
    lien_tv = f"{prefixe}/wallboards/{ident}" + ("" if tv else "?tv=1")
    libelle_tv = "Quitter le mode télé" if tv else "Mode télé"
    corps_classe = ' class="tv"' if tv else ""
    return (
        "<!doctype html>\n"
        '<html lang="fr-CA"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{pages.e(wb['titre'])} · Wallboard OPSYS</title>"
        f'<link rel="stylesheet" href="{pages.e(prefixe)}/statique/wallboard.css">'
        f'<script src="{pages.e(prefixe)}/statique/wallboard.js" defer></script></head>'
        f'<body{corps_classe}><a class="saut" href="#contenu">Aller au contenu</a>'
        f'<main id="wallboard" class="wb" data-api="{api}" data-flux="{api}/flux" '
        f'data-intervalle="{int(rafraichissement["intervalle_s"])}" '
        f'data-flux-max="{int(rafraichissement["flux_max"])}" '
        f'data-rotation="{"1" if rotation["actif"] else "0"}" data-rotation-s="{int(rotation["intervalle_s"])}">'
        f'<h1 id="contenu">{pages.e(wb["titre"])}</h1>'
        f'<p class="sous-titre">{pages.e(wb["description"])}</p>'
        f'<p class="mise-a-jour" id="mise-a-jour">Mis à jour : {pages.e(etat["maintenant"])}</p>'
        '<p class="mise-a-jour">Connexion : <span data-champ="connexion">Rendu initial</span></p>'
        '<div class="controles">'
        '<button type="button" id="pause" aria-pressed="false">Mettre en pause</button>'
        f'<a href="{pages.e(lien_tv)}">{libelle_tv}</a>'
        f'<a href="{pages.e(prefixe)}/wallboards/{ident}">Actualiser la page</a>'
        f'<a href="{pages.e(prefixe)}/wallboards">Tous les wallboards</a></div>'
        f'<div id="banniere" class="banniere banniere-{pages.e(banniere["niveau"])}" role="status" aria-live="polite" '
        f'aria-atomic="true"><h2 class="cache">État général</h2><div data-champ="messages">{messages}</div></div>'
        f'<ul class="grille" aria-label="Mesures">{tuiles}</ul>'
        "<noscript><p>JavaScript est désactivé : les valeurs ne se rafraîchissent pas. "
        "Utilisez « Actualiser la page ».</p>"
        "</noscript></main></body></html>\n"
    )


def rendre_liste(wallboards: list[Mapping[str, Any]], *, prefixe: str) -> str:
    lignes = "".join(
        f'<tr><th scope="row"><a href="{pages.e(prefixe)}/wallboards/{pages.e(w["id"])}">{pages.e(w["titre"])}</a></th>'
        f"<td>{pages.e(w['description'])}</td><td>{int(w['nb_tuiles'])}</td><td>{int(w['intervalle_s'])} s</td></tr>"
        for w in wallboards
    )
    return (
        "<p>Tableaux de bord en direct, en lecture seule. Chaque valeur dit sa fraîcheur ; une valeur périmée n'est "
        "jamais "
        "montrée comme à jour.</p>"
        '<div class="table-defilante"><table><caption class="cache">Wallboards disponibles</caption><thead><tr>'
        '<th scope="col">Wallboard</th><th scope="col">Description</th><th scope="col">Tuiles</th>'
        f'<th scope="col">Rafraîchissement</th></tr></thead><tbody>{lignes}</tbody></table></div>'
    )


def _fusionner(pages_lues: list[dict[str, Any]]) -> dict[str, Any]:
    """Une page de l'outil est bornée par la limite du socle : on reprend à `prochain_depart` jusqu'au bout."""
    etat = dict(pages_lues[0])
    etat["tuiles"] = [t for p in pages_lues for t in p["tuiles"]]
    etat.pop("prochain_depart", None)
    return etat


def creer_router(
    *,
    session_page: Callable[..., Session],
    session_api: Callable[..., Session],
    cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any],
    prefixe: str,
    horloge: Callable[[], str] | None = None,
    dormir: Callable[[float], None] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["wallboards"])
    horloge = horloge or (lambda: _maintenant())
    dormir = dormir or (lambda secondes: _dormir(secondes))
    masquage.installer()

    def exiger_admin(session: Session) -> None:
        with cnx_factory() as cnx:
            personne = identite.personne_active(cnx, session.utilisateur)
        if personne is None or "admin" not in personne.roles:
            raise HTTPException(403, "administration requise")

    def appeler_outil(session: Session, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            with cnx_factory() as cnx:
                reponse = metier.executer(cnx, deps, session, "m8_lire_wallboard", arguments)
        except PermissionError as exc:
            raise HTTPException(403, "accès refusé") from exc
        except KeyError as exc:
            raise HTTPException(404, "analytique indisponible") from exc
        if not isinstance(reponse, Mapping) or reponse.get("ok") is not True:
            details = str(reponse.get("details", "")) if isinstance(reponse, Mapping) else ""
            if "REJ-WALLBOARD-INCONNU" in details:
                raise HTTPException(404, "wallboard inconnu")
            if "REJ-WALLBOARD-ROLE" in details or "REJ-IDENTITE" in details:
                raise HTTPException(403, "accès refusé")
            raise HTTPException(409, "lecture du wallboard refusée")
        return dict(reponse["resultat"])

    def lire(session: Session, wallboard_id: str) -> dict[str, Any]:
        if not _IDENTIFIANT.fullmatch(wallboard_id):
            raise HTTPException(404, "wallboard inconnu")
        exiger_admin(session)
        morceaux: list[dict[str, Any]] = []
        depart = 0
        for _ in range(_PAGES_MAX):
            page = appeler_outil(session, {"maintenant": horloge(), "wallboard_id": wallboard_id, "depart": depart})
            morceaux.append(page)
            if page.get("prochain_depart") is None:
                break
            depart = page["prochain_depart"]
        else:
            raise HTTPException(409, "wallboard trop volumineux")
        return _fusionner(morceaux)

    def controler(html: str) -> None:
        if masquage.contient_secret(html):
            raise HTTPException(500, "rendu refusé : contenu sensible détecté")

    @router.get("/wallboards", response_class=HTMLResponse)
    def liste(request: Request) -> Response:
        session = session_page(request)
        exiger_admin(session)
        reponse = appeler_outil(session, {"maintenant": horloge()})
        exiger_admin(session_page(request))
        html = pages.gabarit(
            "Wallboards",
            rendre_liste(reponse["wallboards"], prefixe=prefixe),
            prefixe=prefixe,
            session=session,
            actif="wallboards",
        )
        controler(html)
        return HTMLResponse(html, headers=ENTETES)

    @router.get("/wallboards/{wallboard_id}", response_class=HTMLResponse)
    def page(wallboard_id: str, request: Request) -> Response:
        session = session_page(request)
        parametres = list(request.query_params.multi_items())
        if (
            any(cle != "tv" for cle, _ in parametres)
            or len(parametres) > 1
            or (parametres and parametres[0][1] not in ("0", "1"))
        ):
            raise HTTPException(400, "seul tv=0 ou tv=1 est accepté")
        etat = lire(session, wallboard_id)
        exiger_admin(session_page(request))
        html = rendre_page(etat, prefixe=prefixe, tv=bool(parametres and parametres[0][1] == "1"), session=session)
        controler(html)
        return HTMLResponse(html, headers=ENTETES)

    @router.get("/api/wallboards/{wallboard_id}")
    def api(wallboard_id: str, request: Request) -> Response:
        session = session_api(request)
        etat = lire(session, wallboard_id)
        exiger_admin(session_api(request))
        return JSONResponse(masquage.masquer({"ok": True, **etat}), headers=ENTETES)

    @router.get("/api/wallboards/{wallboard_id}/flux")
    def flux(wallboard_id: str, request: Request) -> Response:
        session = session_api(request)
        premier = lire(session, wallboard_id)
        exiger_admin(session_api(request))
        intervalle = int(premier["rafraichissement"]["intervalle_s"])
        maximum = int(premier["rafraichissement"]["flux_max"])

        def evenements() -> Iterator[bytes]:
            yield f"retry: {intervalle * 1000}\n\n".encode()
            etat: dict[str, Any] | None = premier
            for envoi in range(maximum):
                try:
                    if envoi > 0:
                        session_courante = session_api(request)  # session relue à chaque envoi
                        etat = lire(session_courante, wallboard_id)
                        exiger_admin(session_api(request))
                except HTTPException as erreur:
                    motif = "session_ou_role_perdu" if erreur.status_code in (401, 403) else "lecture_refusee"
                    yield f"event: fin\ndata: {json.dumps({'raison': motif})}\n\n".encode()
                    return
                donnees = json.dumps(masquage.masquer({"ok": True, **(etat or {})}), ensure_ascii=False)
                yield f"id: {envoi}\nevent: instantane\ndata: {donnees}\n\n".encode()
                if envoi < maximum - 1:
                    dormir(intervalle)
            yield f"event: fin\ndata: {json.dumps({'raison': 'flux_borne', 'envois': maximum})}\n\n".encode()

        return StreamingResponse(
            evenements(),
            media_type="text/event-stream",
            headers={**ENTETES, "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    return router
