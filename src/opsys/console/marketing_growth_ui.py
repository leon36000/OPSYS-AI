"""Consultation privée et saisie humaine des observations Growth déclarées."""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from m7_marketing import growth_lecture
from starlette.concurrency import run_in_threadpool

from .. import identite
from . import metier, pages, securite
from .securite import Session

_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_ENTIER = re.compile(r"^(0|[1-9][0-9]{0,3})$")
_PARAMETRES = frozenset({"debut", "fin", "decalage", "limite"})
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}


def _parametres(request: Request) -> dict[str, Any]:
    valeurs: dict[str, str] = {}
    for cle, valeur in request.query_params.multi_items():
        if cle not in _PARAMETRES or cle in valeurs:
            raise HTTPException(400, "paramètre inconnu ou répété")
        valeurs[cle] = valeur
    if not {"debut", "fin"}.issubset(valeurs):
        raise HTTPException(400, "début et fin de période obligatoires")
    try:
        if not all(_DATE.fullmatch(valeurs[cle]) for cle in ("debut", "fin")):
            raise ValueError
        debut, fin = (date.fromisoformat(valeurs[cle]) for cle in ("debut", "fin"))
        if debut > fin or (fin - debut).days > 365:
            raise ValueError
        decalage_texte, limite_texte = valeurs.get("decalage", "0"), valeurs.get("limite", "25")
        if not _ENTIER.fullmatch(decalage_texte) or not _ENTIER.fullmatch(limite_texte):
            raise ValueError
        decalage, limite = int(decalage_texte), int(limite_texte)
        if not 0 <= decalage <= 1000 or not 1 <= limite <= 100:
            raise ValueError
    except (ValueError, OverflowError) as exc:
        raise HTTPException(400, "période ou pagination invalide") from exc
    return {"debut": debut.isoformat(), "fin": fin.isoformat(), "decalage": decalage, "limite": limite}


def _autoriser(cnx: Any, session: Session) -> None:
    personne = identite.personne_active(cnx, session.utilisateur)
    if personne is None:
        raise HTTPException(401, "authentification requise")
    if not personne.roles.intersection({"nathan_owner", "admin"}):
        raise HTTPException(403, "lecture réservée au propriétaire ou à un administrateur actif")


def creer_router(
    *, session_page: Callable[..., Session], session_api: Callable[..., Session],
    ecriture_api: Callable[[Request], Session], formulaire: Callable[[Request], Any],
    objet_json: Callable[[Request], Any], cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any], prefixe: str,
) -> APIRouter:
    del formulaire, objet_json
    router = APIRouter(tags=["marketing Growth M7"])

    def autoriser(session: Session) -> None:
        with cnx_factory() as cnx:
            _autoriser(cnx, session)

    def lire(session: Session, parametres: Mapping[str, Any]) -> Mapping[str, Any]:
        with cnx_factory() as cnx:
            _autoriser(cnx, session)
            departement = deps.get("m07-marketing")
            if departement is None or departement.module_outils.rsplit(".", 1)[0] != "m7_marketing":
                raise HTTPException(404, "source Growth indisponible")
            try:
                resultat = growth_lecture.lire(cnx, **parametres)
            except ValueError as exc:
                raise HTTPException(409, "registre Growth invalide ou trop volumineux; lecture refusée") from exc
        # Une nouvelle transaction vérifie les droits après la lecture, avant la réponse.
        autoriser(session)
        if not isinstance(resultat, Mapping) or resultat.get("statut") != "OBSERVATIONS_DECLAREES":
            raise HTTPException(409, "réponse Growth invalide")
        return resultat

    @router.get("/marketing/growth", response_class=HTMLResponse)
    def page_growth(request: Request) -> HTMLResponse:
        session = session_page(request)
        autoriser(session)
        resultat = lire(session, _parametres(request)) if request.query_params else None
        return HTMLResponse(
            pages.gabarit("Observations Growth", _contenu(resultat, prefixe, csrf=session.csrf), prefixe=prefixe,
                           session=session, actif="marketing"), headers=_NO_STORE,
        )

    @router.get("/api/marketing/growth")
    def api_growth(request: Request) -> JSONResponse:
        session = session_api(request)
        return JSONResponse({"ok": True, "resultat": lire(session, _parametres(request))}, headers=_NO_STORE)

    def ecrire(session: Session, corps: Mapping[str, Any]) -> Mapping[str, Any]:
        with cnx_factory() as cnx:
            _autoriser(cnx, session)
            reponse = metier.executer(
                cnx, deps, session, "m7_enregistrer_observation_humaine",
                {"observation": {k: corps[k] for k in _CHAMPS_OBSERVATION},
                 "rang_attendu": corps["rang_attendu"], "empreinte_attendue": corps["empreinte_attendue"]},
                mutation_id=corps["mutation_id"],
            )
        autoriser(session)
        return reponse

    async def commande(session: Session, corps: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            return await run_in_threadpool(ecrire, session, corps)
        except PermissionError as exc:
            raise HTTPException(403, "autorité Growth retirée") from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, "commande Growth refusée; relire la période et sa tête") from exc

    @router.post("/api/marketing/growth/observations")
    async def api_observation(request: Request) -> JSONResponse:
        session = await run_in_threadpool(ecriture_api, request)
        await run_in_threadpool(autoriser, session)
        brut = await _corps_borne(request)
        try:
            corps = json.loads(brut.decode("utf-8"), object_pairs_hook=_objet_sans_doublon)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise HTTPException(400, "objet JSON fermé attendu") from exc
        _valider_corps(corps)
        return JSONResponse({"ok": True, "resultat": await commande(session, corps)}, headers=_NO_STORE)

    @router.post("/marketing/growth/observations")
    async def page_observation(request: Request) -> RedirectResponse:
        session = await run_in_threadpool(session_page, request)
        await run_in_threadpool(autoriser, session)
        try:
            valeurs = parse_qs((await _corps_borne(request)).decode("utf-8"),
                               keep_blank_values=True, max_num_fields=20, errors="strict")
            if any(len(v) != 1 for v in valeurs.values()):
                raise ValueError
            corps = {k: v[0] for k, v in valeurs.items()}
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(400, "formulaire fermé attendu") from exc
        if not securite.csrf_valide(corps.pop("csrf", None), session):
            raise HTTPException(403, "jeton CSRF invalide")
        try:
            corps["rang_attendu"] = int(corps["rang_attendu"])
            corps["valeur"] = float(corps["valeur"])
            corps["confiance"] = float(corps["confiance"])
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(400, "valeur numérique ou tête invalide") from exc
        _valider_corps(corps)
        await commande(session, corps)
        return RedirectResponse(
            prefixe + "/marketing/growth?" + urlencode({"debut": corps["debut"], "fin": corps["fin"]}),
            status_code=303, headers=_NO_STORE,
        )

    return router


def _contenu(resultat: Mapping[str, Any] | None, prefixe: str, *, csrf: str = "") -> str:
    periode = resultat["periode"] if resultat else {}
    sections = [
        f'<p><a href="{pages.e(prefixe)}/marketing">Retour au marketing</a> · '
        f'<a href="{pages.e(prefixe)}/marketing/cmo">Plan CMO préparatoire</a></p>',
        '<section class="carte pile"><h2>Observations Growth</h2>',
        '<p>Consultez les observations enregistrées et leurs références. Les chiffres, unités et niveaux '
        'de confiance sont déclarés; leur source externe n’est pas vérifiée. Une provenance humaine '
        'identifie la saisie console seulement; les auteurs historiques restent inconnus.</p>',
        f'<form method="get" action="{pages.e(prefixe)}/marketing/growth" class="formulaire">',
        '<label>Début de période <input type="date" name="debut" required '
        f'value="{pages.e(periode.get("debut", ""))}"></label>',
        '<label>Fin de période <input type="date" name="fin" required '
        f'value="{pages.e(periode.get("fin", ""))}"></label>',
        '<button type="submit">Consulter les observations</button></form>',
        '<p>Seules les observations entièrement comprises dans les deux dates inclusives sont retenues. '
        'Cette consultation ne crée aucun plan et ne modifie aucune observation.</p>',
    ]
    if resultat is None:
        return "".join(sections) + "</section>"
    sections.append(
        f'<p>Observations enregistrées : {pages.e(resultat["total_observations"])} · '
        f'dans la période : {pages.e(resultat["total_periode"])} · '
        f'hors période ou chevauchant les bornes : {pages.e(resultat["hors_periode"])}.</p>'
    )
    sections.append(_formulaire_observation(resultat, prefixe, csrf))
    observations = resultat["observations"]
    if observations:
        sections.append('<div class="table-defilante"><table><thead><tr><th>Référence</th><th>Période</th>'
                        '<th>Canal / campagne</th><th>Métrique</th><th>Valeur / unité</th><th>Source déclarée</th>'
                        '<th>Référence de preuve</th><th>Confiance déclarée</th><th>Saisie</th></tr></thead><tbody>')
        for item in observations:
            sections.append(
                '<tr>'
                f'<td>{pages.e(item["observation_id"])}<br>Déclarée, non vérifiée</td>'
                f'<td>{pages.e(item["periode"]["debut"])} au {pages.e(item["periode"]["fin"])}</td>'
                f'<td>{pages.e(item["plateforme"])} / {pages.e(item["campagne"])}</td>'
                f'<td>{pages.e(item["metrique"])}</td>'
                f'<td>{pages.e(item["valeur"])} {pages.e(item["unite"])}</td>'
                f'<td>{pages.e(item["source"])}</td><td>{pages.e(item["preuve"])}</td>'
                f'<td>{pages.e(item["confiance"])}</td>'
                f'<td>{pages.e(item.get("auteur") or "Auteur historique inconnu")} '
                f'{pages.e(item.get("provenance", {}).get("horodatage", ""))}</td></tr>'
            )
        sections.append('</tbody></table></div>')
    elif resultat["total_periode"]:
        sections.append('<p>Aucune observation sur cette page; utilisez les liens de pagination.</p>')
    else:
        sections.append('<p>Aucune observation enregistrée pour cette période; cela ne prouve pas zéro activité.</p>')
    decalage, limite = resultat["decalage"], resultat["limite"]
    if decalage:
        params = {**periode, "decalage": max(0, decalage - limite), "limite": limite}
        sections.append(
            f'<p><a href="{pages.e(prefixe)}/marketing/growth?{pages.e(urlencode(params))}">Précédent</a></p>'
        )
    if resultat["suivant"] is not None:
        params = {**periode, "decalage": resultat["suivant"], "limite": limite}
        sections.append(
            f'<p><a href="{pages.e(prefixe)}/marketing/growth?{pages.e(urlencode(params))}">Suivant</a></p>'
        )
    sections.append('<h3>Limites des observations</h3><ul>' + ''.join(
        f'<li>{pages.e(limite)}</li>' for limite in resultat["limites"]
    ) + '</ul></section>')
    return "".join(sections)


_CHAMPS_OBSERVATION = frozenset({
    "observation_id", "metrique", "valeur", "unite", "debut", "fin", "plateforme", "campagne",
    "source", "preuve", "confiance",
})
_CHAMPS_COMMANDE = _CHAMPS_OBSERVATION | {"mutation_id", "rang_attendu", "empreinte_attendue"}


async def _corps_borne(request: Request) -> bytes:
    morceaux = []
    taille = 0
    async for morceau in request.stream():
        taille += len(morceau)
        if taille > 32 * 1024:
            raise HTTPException(413, "commande Growth trop volumineuse")
        morceaux.append(morceau)
    return b"".join(morceaux)


def _objet_sans_doublon(paires):
    resultat = {}
    for cle, valeur in paires:
        if cle in resultat:
            raise ValueError("champ répété")
        resultat[cle] = valeur
    return resultat


def _valider_corps(corps: Any) -> None:
    if not isinstance(corps, dict) or set(corps) != _CHAMPS_COMMANDE:
        raise HTTPException(400, "champs Growth inconnus ou absents")
    if (type(corps["rang_attendu"]) is not int or not 0 <= corps["rang_attendu"] <= 1000
            or not isinstance(corps["empreinte_attendue"], str)
            or re.fullmatch(r"[0-9a-f]{64}", corps["empreinte_attendue"]) is None
            or not isinstance(corps["mutation_id"], str) or not 1 <= len(corps["mutation_id"]) <= 200):
        raise HTTPException(400, "tête ou mutation invalide")


def _formulaire_observation(resultat: Mapping[str, Any], prefixe: str, csrf: str) -> str:
    tete = resultat["tete"]
    champs = [
        '<section class="carte"><h3>Déclarer une observation consultée manuellement</h3>',
        '<p>Votre identité et l’heure de saisie sont enregistrées par le serveur. La référence de '
        'preuve et la confiance restent déclarées, sans vérification externe ni calcul de croissance.</p>',
        f'<form method="post" action="{pages.e(prefixe)}/marketing/growth/observations">',
        f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">',
        f'<input type="hidden" name="mutation_id" value="{uuid.uuid4().hex}">',
        f'<input type="hidden" name="rang_attendu" value="{pages.e(tete["rang"])}">',
        f'<input type="hidden" name="empreinte_attendue" value="{pages.e(tete["empreinte"])}">',
    ]
    for nom, libelle, maximum in (
        ("observation_id", "Identifiant de l’observation", 128), ("metrique", "Métrique déclarée", 128),
        ("unite", "Unité", 64), ("plateforme", "Plateforme", 64), ("campagne", "Campagne", 128),
        ("source", "Source consultée (déclarée)", 2048), ("preuve", "Référence de preuve (non vérifiée)", 2048),
    ):
        champs.append(f'<label>{libelle}<input name="{nom}" required maxlength="{maximum}"></label>')
    for nom, libelle in (("debut", "Début"), ("fin", "Fin")):
        valeur = pages.e(resultat["periode"][nom])
        champs.append(f'<label>{libelle}<input type="date" name="{nom}" required value="{valeur}"></label>')
    champs.extend([
        '<label>Valeur déclarée<input type="number" step="any" name="valeur" required></label>',
        '<label>Confiance déclarée (0–1)<input type="number" step="any" min="0" max="1" '
        'name="confiance" required></label>',
        '<button type="submit">Enregistrer la déclaration</button></form></section>',
    ])
    return "".join(champs)
