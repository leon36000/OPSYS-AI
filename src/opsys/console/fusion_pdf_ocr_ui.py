"""Revue privée, en lecture seule, des candidats OCR liés aux lots PDF refusés."""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from .. import fusion_ap, fusion_pdf, fusion_pdf_ocr
from . import pages, securite
from .securite import Session

_FORM_MAX = 16_384
_FORM_FIELDS = {"csrf", "revision_source", "mutation_id"}
_FORM_FIELDS_AP = {"csrf", "revision_source", "revision_run", "mutation_id"}
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_REVISION = re.compile(r"[1-9][0-9]{0,9}\Z")
_MUTATION = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_BLOC = re.compile(r"[1-9][0-9]?\Z")
_TOKENS_PAR_BLOC = 128
_TOKENS_MAX = 2_048
_ETATS_SANS_RESULTAT = {
    "RESERVE": (
        "Calcul réservé",
        "Le résultat n’est pas disponible. Cet état ne confirme pas qu’un calcul est encore actif. "
        "Une vérification d’exploitation est nécessaire.",
    ),
    "REFUSE": (
        "Document refusé",
        "Ce document ne peut pas être traité par le profil de reconnaissance configuré.",
    ),
    "ERREUR_REPRENABLE": (
        "Calcul interrompu",
        "Aucun résultat n’est disponible. Une intervention d’exploitation est nécessaire. "
        "Relancer cette demande ne lance pas un nouveau calcul.",
    ),
    "PERIME": (
        "Résultat périmé",
        "La source ou la configuration a changé. Aucun texte ne peut être affiché pour cette demande.",
    ),
}


def _privee(reponse: Response) -> Response:
    reponse.headers["Cache-Control"] = "private, no-store, max-age=0"
    reponse.headers["Pragma"] = "no-cache"
    reponse.headers["X-Content-Type-Options"] = "nosniff"
    return reponse


def _reponse(prefixe: str, session: Session, contenu: str, status: int = 200) -> HTMLResponse:
    html = pages.gabarit("Revue OCR privée", contenu, prefixe=prefixe, session=session, actif="fusion")
    return _privee(HTMLResponse(html, status_code=status))  # type: ignore[return-value]


def _erreur(prefixe: str, session: Session, status: int) -> HTMLResponse:
    contenu = (
        '<section class="carte pile"><h1>Revue OCR indisponible</h1>'
        '<p role="alert">La demande OCR n’a pas pu être affichée.</p>'
        f'<p><a href="{pages.e(prefixe)}/fusion/pdf">Retour aux lots PDF</a></p></section>'
    )
    return _reponse(prefixe, session, contenu, status)


def _uuid_valide(value: str) -> bool:
    return bool(_UUID.fullmatch(value)) and str(uuid.UUID(value)) == value


def _verifier_admin(session: Session) -> None:
    if not session.roles.intersection({"admin", "nathan_owner"}):
        raise HTTPException(403, "administration requise")


def _eligible(lot: Mapping[str, Any]) -> bool:
    return (
        lot.get("statut") == "REFUSE" and lot.get("code") == "PDF_IMAGE_OU_MIXTE"
        and type(lot.get("revision")) is int and 1 <= lot["revision"] <= 2_147_483_647
    )


def action_ocr(prefixe: str, session: Session, lot: Mapping[str, Any], *, actif: bool) -> str:
    """Retourne un POST OCR explicite seulement pour un refus image/mixte et un opt-in actif."""
    identifiant = lot.get("lot_id")
    if (
        actif is not True or not session.roles.intersection({"admin", "nathan_owner"})
        or not _eligible(lot) or not isinstance(identifiant, str) or not _uuid_valide(identifiant)
    ):
        return ""
    mutation = uuid.uuid4().hex
    return (
        '<section class="carte pile"><h2>Revue OCR</h2>'
        '<p>Le texte OCR est une suggestion non fiable à vérifier. Aucun champ comptable ne sera prérempli.</p>'
        f'<form method="post" action="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(identifiant)}/ocr">'
        f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
        f'<input type="hidden" name="revision_source" value="{pages.e(lot["revision"])}">'
        f'<input type="hidden" name="mutation_id" value="{pages.e(mutation)}">'
        '<button class="principal" type="submit">Calculer un candidat OCR</button></form></section>'
    )


def _action_ap_ocr(prefixe: str, session: Session, lot_id: str, run: Mapping[str, Any], *, actif: bool) -> str:
    run_id = run.get("ocr_run_id")
    revision_source = run.get("revision_pdf_source")
    revision_run = run.get("revision_run")
    if (
        actif is not True or not session.roles.intersection({"admin", "nathan_owner"})
        or not isinstance(run_id, str) or not _uuid_valide(run_id)
        or type(revision_source) is not int or type(revision_run) is not int
        or run.get("pdf_lot_id") != lot_id or run.get("statut") != "A_REVOIR"
    ):
        return ""
    return (
        '<section class="carte pile"><h2>Préparer une revue AP</h2>'
        '<p>Le brouillon commence vide. Les données OCR ne remplissent aucun champ AP.</p>'
        f'<form method="post" action="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}'
        f'/ocr/{pages.e(run_id)}/ap/creer">'
        f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
        f'<input type="hidden" name="revision_source" value="{revision_source}">'
        f'<input type="hidden" name="revision_run" value="{revision_run}">'
        f'<input type="hidden" name="mutation_id" value="{uuid.uuid4().hex}">'
        '<button class="principal" type="submit">Créer un brouillon AP vide</button></form></section>'
    )


async def _formulaire(request: Request, attendus: set[str] = _FORM_FIELDS) -> dict[str, str]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise HTTPException(415, "formulaire invalide")
    annonce = request.headers.get("content-length")
    if annonce is not None:
        if not annonce.isascii() or not annonce.isdecimal() or len(annonce) > 10:
            raise HTTPException(400, "formulaire invalide")
        if int(annonce) > _FORM_MAX:
            raise HTTPException(413, "formulaire invalide")
    morceaux: list[bytes] = []
    taille = 0
    async for morceau in request.stream():
        taille += len(morceau)
        if taille > _FORM_MAX:
            raise HTTPException(413, "formulaire invalide")
        morceaux.append(morceau)
    corps = b"".join(morceaux)
    if re.search(rb"%(?![0-9A-Fa-f]{2})", corps):
        raise HTTPException(400, "formulaire invalide")
    try:
        valeurs = parse_qs(
            corps.decode("utf-8", errors="strict"), keep_blank_values=True,
            strict_parsing=True, max_num_fields=len(attendus), encoding="utf-8", errors="strict",
        )
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(400, "formulaire invalide") from None
    if set(valeurs) != attendus or any(len(v) != 1 for v in valeurs.values()):
        raise HTTPException(400, "formulaire invalide")
    return {k: v[0] for k, v in valeurs.items()}


def creer_router(
    *,
    session_page: Callable[..., Session],
    prefixe: str,
    cnx_factory: Callable[..., Any],
    bundle_ocr: Path | None,
) -> APIRouter:
    router = APIRouter()

    def session_vivante(request: Request, utilisateur: str | None = None) -> Session:
        session = session_page(request)
        if utilisateur is not None and session.utilisateur != utilisateur:
            raise HTTPException(403, "identité modifiée pendant l’opération")
        return session

    def appeler(action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return action(*args, **kwargs)
        except fusion_pdf.FusionPDFErreur as exc:
            raise HTTPException(exc.statut_http, "opération OCR indisponible") from None
        except PermissionError:
            raise HTTPException(403, "accès OCR refusé") from None

    async def appeler_bloquant(action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await run_in_threadpool(appeler, action, *args, **kwargs)

    @router.post("/fusion/pdf/lots/{lot_id}/ocr")
    async def calculer(lot_id: str, request: Request) -> Response:
        session = session_vivante(request)
        try:
            _verifier_admin(session)
        except HTTPException:
            return _erreur(prefixe, session, 403)
        if request.query_params or not _uuid_valide(lot_id):
            return _erreur(prefixe, session, 400)
        try:
            champs = await _formulaire(request)
        except HTTPException as exc:
            return _erreur(prefixe, session_vivante(request, session.utilisateur), exc.status_code)
        if not securite.csrf_valide(champs["csrf"], session):
            return _erreur(prefixe, session, 403)
        revision_brute, mutation = champs["revision_source"], champs["mutation_id"]
        if not _REVISION.fullmatch(revision_brute) or not _MUTATION.fullmatch(mutation):
            return _erreur(prefixe, session, 400)
        if bundle_ocr is None:
            return _erreur(prefixe, session, 503)
        revision = int(revision_brute)
        session_vivante(request, session.utilisateur)
        _verifier_admin(session_vivante(request, session.utilisateur))
        try:
            lot = await appeler_bloquant(fusion_pdf.lire, cnx_factory, session.utilisateur, lot_id)
            session_vivante(request, session.utilisateur)
            _verifier_admin(session_vivante(request, session.utilisateur))
            if not _eligible(lot) or lot["revision"] != revision:
                return _erreur(prefixe, session, 409)
            run = await appeler_bloquant(
                fusion_pdf_ocr.preparer, cnx_factory, session.utilisateur, lot_id, revision, mutation,
                bundle=bundle_ocr,
            )
            session = session_vivante(request, session.utilisateur)
            _verifier_admin(session)
        except HTTPException as exc:
            return _erreur(prefixe, session_vivante(request, session.utilisateur), exc.status_code)
        except Exception:
            return _erreur(prefixe, session_vivante(request, session.utilisateur), 503)
        run_id = run.get("ocr_run_id") if isinstance(run, Mapping) else None
        if (
            not isinstance(run_id, str) or not _uuid_valide(run_id)
            or run.get("pdf_lot_id") != lot_id or run.get("revision_pdf_source") != revision
            or not isinstance(run.get("statut"), str)
            or run["statut"] not in {"A_REVOIR", *_ETATS_SANS_RESULTAT}
        ):
            return _erreur(prefixe, session, 503)
        return _privee(RedirectResponse(
            f"{prefixe}/fusion/pdf/lots/{lot_id}/ocr/{run_id}?bloc=1", status_code=303,
        ))

    @router.post("/fusion/pdf/lots/{lot_id}/ocr/{run_id}/ap/creer")
    async def creer_ap_ocr(lot_id: str, run_id: str, request: Request) -> Response:
        session = session_vivante(request)
        try:
            _verifier_admin(session)
        except HTTPException:
            return _erreur(prefixe, session, 403)
        if request.query_params or not _uuid_valide(lot_id) or not _uuid_valide(run_id):
            return _erreur(prefixe, session, 400)
        try:
            fields = await _formulaire(request, _FORM_FIELDS_AP)
        except HTTPException as exc:
            return _erreur(prefixe, session_vivante(request, session.utilisateur), exc.status_code)
        session_vivante(request, session.utilisateur)
        session = session_vivante(request, session.utilisateur)
        _verifier_admin(session)
        if not securite.csrf_valide(fields["csrf"], session):
            return _erreur(prefixe, session, 403)
        if (
            not _REVISION.fullmatch(fields["revision_source"])
            or not _REVISION.fullmatch(fields["revision_run"])
            or not _MUTATION.fullmatch(fields["mutation_id"])
        ):
            return _erreur(prefixe, session, 400)
        if bundle_ocr is None:
            return _erreur(prefixe, session, 503)
        revision_source = int(fields["revision_source"])
        revision_run = int(fields["revision_run"])
        try:
            await appeler_bloquant(fusion_pdf_ocr._bundle, bundle_ocr)
            lot = await appeler_bloquant(fusion_pdf.lire, cnx_factory, session.utilisateur, lot_id)
            session = session_vivante(request, session.utilisateur)
            _verifier_admin(session)
            run = await appeler_bloquant(fusion_pdf_ocr.lire, cnx_factory, session.utilisateur, run_id)
            session = session_vivante(request, session.utilisateur)
            _verifier_admin(session)
            candidat = await appeler_bloquant(
                fusion_pdf_ocr.lire_resultat, cnx_factory, session.utilisateur, run_id,
            )
            session = session_vivante(request, session.utilisateur)
            _verifier_admin(session)
            if (
                not _eligible(lot) or lot["revision"] != revision_source
                or run.get("pdf_lot_id") != lot_id or run.get("revision_pdf_source") != revision_source
                or run.get("revision_run") != revision_run or run.get("statut") != "A_REVOIR"
                or candidat.get("statut") != "CANDIDAT_A_REVOIR" or candidat.get("lot_id") != lot_id
                or candidat.get("revision_source") != revision_source
            ):
                return _erreur(prefixe, session, 409)
            tokens = candidat.get("page", {}).get("tokens")
            if not isinstance(tokens, list) or not 1 <= len(tokens) <= _TOKENS_MAX:
                return _erreur(prefixe, session, 409)
            await appeler_bloquant(
                fusion_ap.creer_brouillon_ocr, cnx_factory, session.utilisateur, lot_id,
                mutation_id=fields["mutation_id"], revision_pdf_attendue=revision_source,
                ocr_run_id=run_id, revision_run=revision_run,
            )
            session = session_vivante(request, session.utilisateur)
            _verifier_admin(session)
        except HTTPException as exc:
            return _erreur(prefixe, session_vivante(request, session.utilisateur), exc.status_code)
        except Exception:
            return _erreur(prefixe, session_vivante(request, session.utilisateur), 409)
        return _privee(RedirectResponse(
            f"{prefixe}/fusion/pdf/lots/{lot_id}/ap/ocr/{run_id}", status_code=303,
        ))

    @router.get("/fusion/pdf/lots/{lot_id}/ocr/{run_id}", response_class=HTMLResponse)
    async def lire_candidat(lot_id: str, run_id: str, request: Request) -> Response:
        session = session_vivante(request)
        _verifier_admin(session)
        params = request.query_params
        valeurs = params.getlist("bloc")
        if not _uuid_valide(lot_id) or not _uuid_valide(run_id) or set(params) != {"bloc"} or len(valeurs) != 1:
            return _erreur(prefixe, session, 400)
        if not _BLOC.fullmatch(valeurs[0]):
            return _erreur(prefixe, session, 400)
        bloc = int(valeurs[0])
        debut = (bloc - 1) * _TOKENS_PAR_BLOC
        if debut >= _TOKENS_MAX:
            return _erreur(prefixe, session, 400)
        try:
            run = await appeler_bloquant(fusion_pdf_ocr.lire, cnx_factory, session.utilisateur, run_id)
            session = session_vivante(request, session.utilisateur)
            _verifier_admin(session)
            if (
                not isinstance(run, Mapping) or run.get("ocr_run_id") != run_id
                or run.get("pdf_lot_id") != lot_id or not isinstance(run.get("statut"), str)
            ):
                return _erreur(prefixe, session, 404)
            if run["statut"] in _ETATS_SANS_RESULTAT:
                if bloc != 1:
                    return _erreur(prefixe, session, 400)
                titre, explication = _ETATS_SANS_RESULTAT[run["statut"]]
                contenu = (
                    f'<p><a href="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}">Retour au lot PDF</a></p>'
                    f'<section class="carte pile"><h1>{pages.e(titre)}</h1>'
                    f'<p>{pages.e(explication)}</p>'
                    '<p>Aucune donnée financière n’est créée ou validée par cette demande.</p></section>'
                )
                return _reponse(prefixe, session, contenu)
            if run["statut"] != "A_REVOIR":
                return _erreur(prefixe, session, 404)
            candidat = await appeler_bloquant(fusion_pdf_ocr.lire_resultat, cnx_factory, session.utilisateur, run_id)
            session = session_vivante(request, session.utilisateur)
            _verifier_admin(session)
        except HTTPException as exc:
            return _erreur(prefixe, session_vivante(request, session.utilisateur), exc.status_code)
        except Exception:
            return _erreur(prefixe, session_vivante(request, session.utilisateur), 404)
        try:
            page = candidat["page"]
            tokens = page["tokens"]
            if (
                candidat.get("statut") != "CANDIDAT_A_REVOIR" or candidat.get("lot_id") != lot_id
                or candidat.get("revision_source") != run.get("revision_pdf_source")
                or not isinstance(tokens, list) or not 1 <= len(tokens) <= _TOKENS_MAX
                or any(
                    not isinstance(token, Mapping) or not isinstance(token.get("texte"), str)
                    or type(token.get("confiance_brute")) not in (int, float)
                    or not math.isfinite(token["confiance_brute"])
                    or not 0 <= token["confiance_brute"] <= 100
                    for token in tokens
                )
            ):
                raise ValueError("candidat invalide")
        except (KeyError, TypeError, ValueError):
            return _erreur(prefixe, session, 503)
        selection = tokens[debut:debut + _TOKENS_PAR_BLOC]
        if not selection:
            return _erreur(prefixe, session, 400)
        lignes = "".join(
            f'<li id="token-{debut + index}"><strong>Token {debut + index}</strong> — '
            f'confiance brute {pages.e(token["confiance_brute"])} / 100, non calibrée'
            f"<pre>{pages.e(token['texte'])}</pre></li>"
            for index, token in enumerate(selection)
        )
        nombre_blocs = (len(tokens) + _TOKENS_PAR_BLOC - 1) // _TOKENS_PAR_BLOC
        navigation = []
        if bloc > 1:
            navigation.append(
                f'<a rel="prev" href="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}'
                f'/ocr/{pages.e(run_id)}?bloc={bloc - 1}">Bloc précédent</a>'
            )
        if bloc < nombre_blocs:
            navigation.append(
                f'<a rel="next" href="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}'
                f'/ocr/{pages.e(run_id)}?bloc={bloc + 1}">Bloc suivant</a>'
            )
        contenu = (
            f'<p><a href="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}">Retour au lot PDF</a></p>'
            '<section class="carte pile"><h1>Candidat OCR à vérifier</h1>'
            '<p>Texte reconnu à vérifier. Vérification humaine requise. '
            'Aucun montant ou fournisseur n’est validé. Cette revue ne crée aucune facture fournisseur '
            'ou écriture comptable.</p>'
            f'<p>Bloc {bloc} sur {nombre_blocs}</p><ol>{lignes}</ol>'
            f'<nav aria-label="Blocs du candidat">{" · ".join(navigation)}</nav>'
            f'{_action_ap_ocr(prefixe, session, lot_id, run, actif=bundle_ocr is not None)}</section>'
        )
        return _reponse(prefixe, session, contenu)

    return router
