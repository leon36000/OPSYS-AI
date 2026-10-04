"""Interface administrateur de création et reprise des lots de procédures M03."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Mapping
from email.message import Message
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.requests import Request as StarletteRequest

from opsys.memoire.store import MemoireIndisponible

from . import pages, securite
from .memoire_ingestion_ui import _NONCE, _OCTETS, _privee, _valider_upload
from .securite import Session

_CORPS_LOT = 5 * _OCTETS + 65_536
_SLOTS = range(1, 6)
_ETATS = ("ATTENTE", "RECU", "INDEXE")


async def _formulaire_lot(request: Request) -> tuple[dict[str, str], dict[int, bytes]]:
    media = Message()
    media["content-type"] = request.headers.get("content-type", "")
    boundary = media.get_param("boundary", header="content-type")
    if (
        media.get_content_type() != "multipart/form-data"
        or not isinstance(boundary, str)
        or not 1 <= len(boundary) <= 70
    ):
        raise HTTPException(415, "formulaire multipart requis")
    annonce = request.headers.get("content-length")
    if annonce is not None:
        if not annonce.isascii() or not annonce.isdecimal() or len(annonce) > 10:
            raise HTTPException(400, "taille de requête invalide")
        if int(annonce) > _CORPS_LOT:
            raise HTTPException(413, "requête trop volumineuse")
    chunks: list[bytes] = []
    taille = 0
    async for chunk in request.stream():
        taille += len(chunk)
        if taille > _CORPS_LOT:
            raise HTTPException(413, "requête trop volumineuse")
        chunks.append(chunk)
    raw = b"".join(chunks)
    consumed = False

    async def receive():
        nonlocal consumed
        if consumed:
            return {"type": "http.disconnect"}
        consumed = True
        return {"type": "http.request", "body": raw, "more_body": False}

    clone = StarletteRequest(request.scope, receive=receive)
    form = None
    try:
        form = await clone.form(max_files=5, max_fields=12, max_part_size=16_384)
        items = form.multi_items()
        names = [name for name, _ in items]
        if len(names) != len(set(names)):
            raise HTTPException(400, "champs multipart invalides")
        values = dict(items)
        allowed = {"csrf", "attestation", "cle_lot"}
        for position in _SLOTS:
            allowed.update({f"titre_{position}", f"source_{position}"})
        if "csrf" not in values:
            raise HTTPException(403, "jeton CSRF absent")
        if set(values) - allowed or set(values) - {"csrf", "attestation"} == set():
            raise HTTPException(400, "champs multipart invalides")
        if any(not isinstance(values[key], str) for key in values if key not in {f"source_{i}" for i in _SLOTS}):
            raise HTTPException(400, "champs multipart invalides")
        uploads: dict[int, UploadFile] = {}
        for position in _SLOTS:
            title_key, source_key = f"titre_{position}", f"source_{position}"
            if source_key in values:
                uploaded = values[source_key]
                if not isinstance(uploaded, UploadFile):
                    if uploaded == "":
                        continue
                    raise HTTPException(400, "fichier invalide")
                if not uploaded.filename:
                    if await uploaded.read(1):
                        raise HTTPException(400, "fichier invalide")
                    continue
                if title_key not in values:
                    raise HTTPException(400, "titre invalide")
                uploads[position] = uploaded
        if not uploads:
            raise HTTPException(400, "aucun document fourni")
        if values.get("attestation") != "oui":
            raise HTTPException(400, "attestation requise")
        titles: dict[str, str] = {}
        for position in uploads:
            title = values[f"titre_{position}"]
            if not title.strip() or len(title) > 300:
                raise HTTPException(400, "titre invalide")
            titles[f"titre_{position}"] = title
        documents: dict[int, bytes] = {}
        # Lire et contrôler chaque fichier avant tout appel mutationnel.
        for position, upload in uploads.items():
            documents[position] = await _valider_upload(upload)
        champs = {"csrf": values["csrf"], "attestation": values["attestation"], **titles}
        if "cle_lot" in values:
            champs["cle_lot"] = values["cle_lot"]
        return champs, documents
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "formulaire multipart invalide") from exc
    finally:
        if form is not None:
            await form.close()


def _attribut(objet: Any, nom: str, defaut: Any = None) -> Any:
    if isinstance(objet, Mapping):
        return objet.get(nom, defaut)
    return getattr(objet, nom, defaut)


def _page(session: Session, prefixe: str, corps: str, code: int = 200) -> Response:
    return _privee(HTMLResponse(
        pages.gabarit("Import de procédures M03", corps, prefixe=prefixe, session=session, actif="memoire"),
        status_code=code,
    ))


def _erreur(session: Session, prefixe: str, code: int, message: str, *, cle: str | None = None) -> Response:
    cible = (
        f"{pages.e(prefixe)}/memoire/procedures/imports/{pages.e(cle)}"
        if cle is not None and _NONCE.fullmatch(cle)
        else f"{pages.e(prefixe)}/memoire/procedures/imports"
    )
    return _page(
        session, prefixe, f'<section class="carte"><p role="alert">{pages.e(message)}</p>'
        f'<p><a href="{cible}">Consulter ou reprendre</a></p></section>', code,
    )


def _form_creation(session: Session, prefixe: str, cle: str) -> str:
    blocks = [
        '<section class="carte pile"><h2>Nouveau lot</h2>'
        '<p>Procédures internes M03 uniquement. TXT ou Markdown UTF-8, sans données personnelles ni secrets. '
        'Aucun aperçu, modèle ou indexation automatique.</p>'
        f'<form method="post" enctype="multipart/form-data" '
        f'action="{pages.e(prefixe)}/memoire/procedures/imports/creer" class="pile">',
        f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">',
        f'<input type="hidden" name="cle_lot" value="{pages.e(cle)}">',
    ]
    for position in _SLOTS:
        blocks.append(
            f'<fieldset><legend>Emplacement {position}</legend>'
            f'<label>Titre<input name="titre_{position}" maxlength="300"></label>'
            f'<label>Document TXT ou Markdown UTF-8<input type="file" name="source_{position}" '
            'accept=".txt,.md,text/plain,text/markdown"></label></fieldset>'
        )
    blocks.extend([
        '<label><input type="checkbox" name="attestation" value="oui" required>'
        'Je confirme que ces documents internes ne contiennent ni donnée personnelle ni secret.</label>',
        '<button type="submit">Créer et admettre le lot</button></form></section>',
    ])
    return "".join(blocks)


def _form_reprise(session: Session, prefixe: str, key: str, emplacements: tuple[Any, ...]) -> str:
    waiting = [slot for slot in emplacements if _attribut(slot, "etat") == "ATTENTE"]
    if not waiting:
        return '<p>Tous les emplacements sont déjà reçus ou indexés.</p>'
    blocks = [
        f'<form method="post" enctype="multipart/form-data" '
        f'action="{pages.e(prefixe)}/memoire/procedures/imports/{pages.e(key)}/reprendre" class="pile">',
        f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">',
        f'<input type="hidden" name="cle_lot" value="{pages.e(key)}">',
    ]
    for slot in waiting:
        position = int(_attribut(slot, "position"))
        title = str(_attribut(slot, "titre", ""))
        digest = str(_attribut(slot, "sha256", ""))
        blocks.append(
            f'<fieldset><legend>Emplacement {position} · SHA-256 {pages.e(digest)}</legend>'
            f'<label>Titre attendu<input name="titre_{position}" maxlength="300" value="{pages.e(title)}"></label>'
            f'<label>Renvoyer le document exact<input type="file" name="source_{position}" '
            'accept=".txt,.md,text/plain,text/markdown"></label></fieldset>'
        )
    blocks.extend([
        '<label><input type="checkbox" name="attestation" value="oui" required>'
        'Je confirme que ces documents internes ne contiennent ni donnée personnelle ni secret.</label>',
        '<button type="submit">Reprendre les emplacements choisis</button></form>',
    ])
    return "".join(blocks)


def _afficher_lot(session: Session, prefixe: str, lot: Any, *, notice: str = "", code: int = 200) -> Response:
    key = str(_attribut(lot, "cle_lot", ""))
    slots = tuple(_attribut(lot, "emplacements", ()))
    counts = {state: sum(_attribut(slot, "etat") == state for slot in slots) for state in _ETATS}
    active = sum(bool(_attribut(slot, "active", False)) for slot in slots)
    body = [f'<section class="carte pile"><h2>État du lot</h2><p>Clé : {pages.e(key)}</p>']
    if notice:
        body.append(f'<p role="status">{pages.e(notice)}</p>')
    body.append(
        f'<p>ATTENTE {counts["ATTENTE"]} · RECU {counts["RECU"]} · INDEXE {counts["INDEXE"]} · actifs {active}</p>'
    )
    for slot in sorted(slots, key=lambda item: int(_attribut(item, "position", 0))):
        body.append(
            f'<p>Emplacement {pages.e(_attribut(slot, "position"))} · {pages.e(_attribut(slot, "titre", ""))} · '
            f'{pages.e(_attribut(slot, "etat", "ATTENTE"))} · SHA-256 {pages.e(_attribut(slot, "sha256", ""))}'
            f'{" · actif" if _attribut(slot, "active", False) else ""}</p>'
        )
    body.append("</section>")
    body.append(_form_reprise(session, prefixe, key, slots))
    return _page(session, prefixe, "".join(body), code)


def creer_router(
    *, session_page: Callable[..., Session], prefixe: str, service_factory: Callable[[], Any]
) -> APIRouter:
    router = APIRouter()

    def vivante(request: Request, initiale: Session | None = None) -> Session:
        session = session_page(request)
        if initiale is not None and session.utilisateur != initiale.utilisateur:
            raise HTTPException(403, "session modifiée pendant la requête")
        return session

    def sans_query(request: Request) -> None:
        if request.query_params:
            raise HTTPException(400, "paramètres invalides")

    async def lire_formulaire(request: Request, session: Session) -> tuple[dict[str, str], dict[int, bytes]]:
        fields, documents = await _formulaire_lot(request)
        if not securite.csrf_valide(fields.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF invalide")
        vivante(request, session)
        return fields, documents

    def reponse_refus(request: Request, initiale: Session, erreur: HTTPException) -> Response:
        try:
            session = vivante(request, initiale)
        except Exception:
            return _privee(HTMLResponse(
                pages.page_erreur("Action refusée", "La session administrateur n’est plus active.", prefixe=prefixe),
                status_code=403,
            ))
        return _erreur(
            session, prefixe, erreur.status_code, str(erreur.detail),
            cle=request.path_params.get("cle"),
        )

    async def partiel(
        request: Request, initiale: Session, cle: str, *, code: int, notice: str
    ) -> Response:
        try:
            session = vivante(request, initiale)
            lot = await run_in_threadpool(service_factory().lire_lot, cle, auteur=session.utilisateur)
            session = vivante(request, initiale)
            return _afficher_lot(session, prefixe, lot, notice=notice, code=code)
        except HTTPException as exc:
            return reponse_refus(request, initiale, exc)
        except Exception:
            # Garder la clé opaque suffit à reprendre quand le stockage sera disponible.
            return _erreur_partielle(request, initiale, cle, code, notice)

    def _erreur_partielle(
        request: Request, initiale: Session, cle: str, code: int, notice: str
    ) -> Response:
        try:
            session = vivante(request, initiale)
        except HTTPException as exc:
            return reponse_refus(request, initiale, exc)
        return _erreur(session, prefixe, code, notice, cle=cle)

    @router.get("/memoire/procedures/imports")
    async def page_imports(request: Request) -> Response:
        session = vivante(request)
        try:
            sans_query(request)
        except HTTPException as exc:
            return _erreur(session, prefixe, exc.status_code, str(exc.detail))
        return _page(session, prefixe, _form_creation(session, prefixe, secrets.token_urlsafe(32)))

    @router.post("/memoire/procedures/imports/creer")
    async def creer(request: Request) -> Response:
        session = vivante(request)
        manifeste_cree = False
        try:
            sans_query(request)
            fields, documents = await lire_formulaire(request, session)
            positions = sorted(documents)
            if not 1 <= len(positions) <= 5:
                raise HTTPException(400, "le lot doit contenir de un à cinq documents")
            cle = fields.get("cle_lot", "")
            if not _NONCE.fullmatch(cle):
                raise HTTPException(400, "clé de lot invalide")
            from opsys.memoire.ingestion_procedures import SourceLot

            sources = tuple(
                SourceLot(
                    position=position,
                    titre=fields[f"titre_{position}"],
                    sha256=hashlib.sha256(documents[position]).hexdigest(),
                )
                for position in positions
            )

            def creer_autorise():
                vivante(request, session)
                return service_factory().creer_lot(cle, sources, auteur=session.utilisateur)

            await run_in_threadpool(creer_autorise)
            manifeste_cree = True
            for position in positions:
                def admettre_autorise(position_courante: int = position):
                    vivante(request, session)
                    return service_factory().admettre_emplacement(
                        cle, position_courante, documents[position_courante], auteur=session.utilisateur
                    )

                await run_in_threadpool(admettre_autorise)
            lot = await run_in_threadpool(service_factory().lire_lot, cle, auteur=session.utilisateur)
            session = vivante(request, session)
            return _afficher_lot(session, prefixe, lot, notice="Lot créé et documents admis.")
        except HTTPException as exc:
            return reponse_refus(request, session, exc)
        except MemoireIndisponible:
            return await partiel(
                request, session, cle, code=503,
                notice="Lot partiel : mémoire indisponible; les emplacements reçus restent conservés.",
            )
        except ValueError:
            if not manifeste_cree:
                return _erreur_partielle(
                    request, session, cle, 409, "création refusée; vérifiez la clé et les documents"
                )
            return await partiel(
                request, session, cle, code=409,
                notice="Lot partiel : un emplacement a été refusé; les autres restent reprenables.",
            )
        except Exception:
            if "cle" in locals():
                return await partiel(
                    request, session, cle, code=503,
                    notice="Lot partiel : mémoire indisponible; les emplacements reçus restent conservés.",
                )
            return reponse_refus(request, session, HTTPException(503, "mémoire indisponible; réessayez plus tard"))

    @router.get("/memoire/procedures/imports/{cle}")
    async def etat(request: Request, cle: str) -> Response:
        session = vivante(request)
        try:
            sans_query(request)
            if not _NONCE.fullmatch(cle):
                raise HTTPException(404, "lot introuvable")
            lot = await run_in_threadpool(service_factory().lire_lot, cle, auteur=session.utilisateur)
            if lot is None:
                raise HTTPException(404, "lot introuvable")
            session = vivante(request, session)
            return _afficher_lot(session, prefixe, lot)
        except HTTPException as exc:
            return reponse_refus(request, session, exc)
        except MemoireIndisponible:
            return reponse_refus(request, session, HTTPException(503, "mémoire indisponible; réessayez plus tard"))
        except ValueError:
            return reponse_refus(request, session, HTTPException(404, "lot introuvable"))
        except Exception:
            return reponse_refus(request, session, HTTPException(503, "mémoire indisponible; réessayez plus tard"))

    @router.post("/memoire/procedures/imports/{cle}/reprendre")
    async def reprendre(request: Request, cle: str) -> Response:
        session = vivante(request)
        try:
            sans_query(request)
            if not _NONCE.fullmatch(cle):
                raise HTTPException(404, "lot introuvable")
            fields, documents = await lire_formulaire(request, session)
            if fields.get("cle_lot", cle) != cle:
                raise HTTPException(400, "clé de lot invalide")
            lot = await run_in_threadpool(service_factory().lire_lot, cle, auteur=session.utilisateur)
            if lot is None:
                raise HTTPException(404, "lot introuvable")
            slots = {int(_attribut(slot, "position")): slot for slot in _attribut(lot, "emplacements", ())}
            positions = sorted(documents)
            # Tout le lot soumis est comparé au manifeste immuable avant la première admission.
            for position in positions:
                slot = slots.get(position)
                if slot is None:
                    raise HTTPException(409, "emplacement absent du manifeste")
                expected_title = _attribut(slot, "titre")
                expected_sha = _attribut(slot, "sha256")
                if fields.get(f"titre_{position}") != expected_title:
                    raise HTTPException(409, "titre différent du manifeste")
                if hashlib.sha256(documents[position]).hexdigest() != expected_sha:
                    raise HTTPException(409, "empreinte différente du manifeste")
            for position in positions:
                def reprendre_autorise(position_courante: int = position):
                    vivante(request, session)
                    return service_factory().admettre_emplacement(
                        cle, position_courante, documents[position_courante], auteur=session.utilisateur
                    )

                await run_in_threadpool(reprendre_autorise)
            lot = await run_in_threadpool(service_factory().lire_lot, cle, auteur=session.utilisateur)
            session = vivante(request, session)
            return _afficher_lot(session, prefixe, lot, notice="Reprise terminée.")
        except HTTPException as exc:
            return reponse_refus(request, session, exc)
        except MemoireIndisponible:
            return await partiel(
                request, session, cle, code=503,
                notice="Reprise partielle : mémoire indisponible; les emplacements reçus restent conservés.",
            )
        except ValueError:
            return await partiel(
                request, session, cle, code=409,
                notice="Reprise partielle : lot introuvable ou emplacement refusé.",
            )
        except Exception:
            return await partiel(
                request, session, cle, code=503,
                notice="Reprise partielle : mémoire indisponible; les emplacements reçus restent conservés.",
            )

    return router
