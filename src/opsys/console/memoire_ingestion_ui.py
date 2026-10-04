"""Parcours administrateur borné pour les procédures internes du département M03."""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Callable
from email.message import Message
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.requests import Request as StarletteRequest

from . import pages, securite
from .securite import Session

_OCTETS = 1_048_576
_CORPS = _OCTETS + 65_536
_CORPS_ACTION = 16_384
_CHAMPS = frozenset({"csrf", "titre", "cle_admission", "attestation", "document_id", "source"})
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")


class _ErreurMultipart(HTTPException):
    def __init__(self, status_code: int, detail: str, reprise: dict[str, str] | None = None) -> None:
        super().__init__(status_code, detail)
        self.reprise = reprise


def _privee(reponse: Response) -> Response:
    reponse.headers["Cache-Control"] = "no-store"
    return reponse


def _media(request: Request) -> tuple[str, str | None]:
    message = Message()
    message["content-type"] = request.headers.get("content-type", "")
    return message.get_content_type(), message.get_param("boundary", header="content-type")


async def _corps_borne(request: Request, maximum: int = _CORPS) -> bytes:
    annonce = request.headers.get("content-length")
    if annonce is not None:
        if not annonce.isascii() or not annonce.isdecimal() or len(annonce) > 10:
            raise HTTPException(400, "taille de requête invalide")
        if int(annonce) > maximum:
            raise HTTPException(413, "requête trop volumineuse")
    morceaux: list[bytes] = []
    taille = 0
    async for morceau in request.stream():
        taille += len(morceau)
        if taille > maximum:
            raise HTTPException(413, "requête trop volumineuse")
        morceaux.append(morceau)
    return b"".join(morceaux)


async def _formulaire(request: Request) -> tuple[dict[str, str], bytes]:
    media, boundary = _media(request)
    if media != "multipart/form-data" or not isinstance(boundary, str) or not 1 <= len(boundary) <= 70:
        raise HTTPException(415, "formulaire multipart requis")
    raw = await _corps_borne(request)
    recu = False

    async def recevoir():
        nonlocal recu
        if recu:
            return {"type": "http.disconnect"}
        recu = True
        return {"type": "http.request", "body": raw, "more_body": False}

    clone = StarletteRequest(request.scope, receive=recevoir)
    form = None
    try:
        form = await clone.form(max_files=1, max_fields=5, max_part_size=16_384)
        items = form.multi_items()
        names = [name for name, _ in items]
        valeurs = dict(items)
        reprise = {
            key: value
            for key, value in valeurs.items()
            if key in {"cle_admission", "titre", "document_id"} and isinstance(value, str)
        }
        if "csrf" not in names:
            raise _ErreurMultipart(403, "jeton CSRF absent", reprise)
        if len(names) != len(set(names)) or set(names) != _CHAMPS:
            raise _ErreurMultipart(400, "champs multipart invalides", reprise)
        texte = {key: valeurs[key] for key in _CHAMPS if key != "source"}
        if any(not isinstance(value, str) for value in texte.values()):
            raise _ErreurMultipart(400, "champs multipart invalides", reprise)
        fichier = valeurs["source"]
        contenu = await _valider_upload(fichier, reprise)
        return texte, contenu
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "formulaire multipart invalide") from exc
    finally:
        if form is not None:
            await form.close()


async def _valider_upload(fichier: Any, reprise: dict[str, str] | None = None) -> bytes:
    """Validation commune du fichier historique et des emplacements de lot."""
    if not isinstance(fichier, UploadFile):
        raise _ErreurMultipart(400, "fichier invalide", reprise)
    nom = fichier.filename
    type_brut = fichier.content_type or ""
    message_type = Message()
    message_type["content-type"] = type_brut
    media_fichier = message_type.get_content_type().lower()
    parametres_type = message_type.get_params(header="content-type", unquote=True) or []
    base_type = str(parametres_type[0][0]).lower() if parametres_type else ""
    charset = [str(value).lower() for name, value in parametres_type[1:] if name.lower() == "charset"]
    autres_parametres = [name for name, _ in parametres_type[1:] if name.lower() != "charset"]
    if fichier.headers.get("content-transfer-encoding") is not None:
        raise _ErreurMultipart(400, "encodage de fichier inattendu", reprise)
    if (
        not nom or len(nom) > 160 or any(c in nom for c in ("/", "\\", "\x00"))
        or not nom.lower().endswith((".txt", ".md"))
    ):
        raise _ErreurMultipart(400, "nom ou format de fichier invalide", reprise)
    if (
        not type_brut.strip() or base_type != media_fichier
        or media_fichier not in {"text/plain", "text/markdown", "application/octet-stream"}
        or len(charset) > 1 or (charset and charset[0] not in {"utf-8", "utf8"}) or autres_parametres
    ):
        raise _ErreurMultipart(415, "type de fichier invalide", reprise)
    contenu = await fichier.read(_OCTETS + 1)
    if len(contenu) > _OCTETS:
        raise _ErreurMultipart(413, "fichier supérieur à 1 MiB", reprise)
    try:
        texte = contenu.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise _ErreurMultipart(400, "le fichier doit être en UTF-8 valide", reprise) from exc
    if "\x00" in texte:
        raise _ErreurMultipart(400, "le fichier contient un octet interdit", reprise)
    return contenu


def _service():
    from opsys.memoire.store import MemoireEntreprise

    return MemoireEntreprise(os.environ.get("OPSYS_DATABASE_URL", "")).procedures()


def _rend_page(session: Session, prefixe: str, contenu: str, code: int = 200) -> HTMLResponse:
    return _privee(
        HTMLResponse(
            pages.gabarit("Procédures internes M03", contenu, prefixe=prefixe, session=session, actif="memoire"),
            status_code=code,
        )
    )  # type: ignore[return-value]


def _form_admission(
    session: Session, prefixe: str, *, cle: str | None = None, titre: str = "", document_id: str = ""
) -> str:
    cle = cle or secrets.token_urlsafe(24)
    return (
        '<section class="carte pile"><h2>Admission</h2>'
        "<p>Documents internes de procédures M03 seulement. Attestez qu’ils ne contiennent ni donnée personnelle ni "
        "secret. Cette attestation humaine n’est pas un scan. Aucun aperçu ni service de modèle ou d’embeddings "
        "n’est utilisé.</p>"
        f'<form method="post" enctype="multipart/form-data" '
        f'action="{pages.e(prefixe)}/memoire/procedures/admettre" class="pile">'
        f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
        f'<input type="hidden" name="cle_admission" value="{pages.e(cle)}">'
        f'<input type="hidden" name="document_id" value="{pages.e(document_id)}">'
        f'<label>Titre<input name="titre" maxlength="300" value="{pages.e(titre)}" required></label>'
        '<label>Document TXT ou Markdown UTF-8<input type="file" name="source" '
        'accept=".txt,.md,text/plain,text/markdown" required></label>'
        '<label><input type="checkbox" name="attestation" value="oui" required>'
        "Je confirme que le document interne ne contient ni donnée personnelle ni secret.</label>"
        '<button type="submit">Admettre comme REÇU</button></form></section>'
    )


def _erreur(
    session: Session, prefixe: str, code: int, message: str, *, reprise: dict[str, str] | None = None
) -> HTMLResponse:
    form = ""
    if reprise is not None and _NONCE.fullmatch(reprise.get("cle_admission", "")):
        ident = reprise.get("document_id", "")
        if ident and not _UUID.fullmatch(ident):
            ident = ""
        form = _form_admission(
            session,
            prefixe,
            cle=reprise["cle_admission"],
            titre=reprise.get("titre", "")[:300],
            document_id=ident,
        )
    return _rend_page(
        session,
        prefixe,
        f'<section class="carte"><p role="alert">{pages.e(message)}</p>'
        f'<p><a href="{pages.e(prefixe)}/memoire/procedures">Recharger</a></p></section>{form}',
        code,
    )


def _contenu(
    session: Session,
    prefixe: str,
    series: tuple[dict[str, object], ...],
    versions: dict[str, tuple[Any, ...]],
    *,
    offset: int,
    total: int,
    succes: str = "",
    avertissement: str = "",
) -> str:
    morceaux = [
        f'<p><a href="{pages.e(prefixe)}/memoire/procedures/imports">Créer ou reprendre un lot d’import</a></p>',
        _form_admission(session, prefixe),
    ]
    morceaux.append(
        '<form method="post" action="' + pages.e(prefixe) + '/memoire/procedures/indexer-recues">'
        '<input type="hidden" name="csrf" value="' + pages.e(session.csrf) + '">'
        '<button type="submit">Indexer les prochains reçus (maximum 5)</button></form>'
    )
    if succes:
        morceaux.append(f'<p class="message message-ok" role="status">{pages.e(succes)}</p>')
    if avertissement:
        morceaux.append(f'<p class="message message-erreur" role="alert">{pages.e(avertissement)}</p>')
    morceaux.append('<section class="carte pile"><h2>Versions admises</h2>')
    if not series:
        morceaux.append("<p>Aucune série admise.</p>")
    for serie in series:
        ident = str(serie["document_id"])
        morceaux.append(f"<article><h3>{pages.e(serie['titre'])}</h3><p>ID : {pages.e(ident)}</p>")
        morceaux.append(_form_admission(session, prefixe, document_id=ident, titre=str(serie["titre"])))
        for version in versions.get(ident, ()):
            sha = version.sha256
            etat = version.etat
            active = " · version active" if version.active else ""
            morceaux.append(
                f"<p>Version {pages.e(version.version)} · {pages.e(etat)} · SHA-256 {pages.e(sha)} · "
                f"auteur {pages.e(version.auteur)} · {pages.e(version.admise_le)}{pages.e(active)}</p>"
            )
            if etat == "RECU":
                morceaux.append(
                    f'<form method="post" action="{pages.e(prefixe)}/memoire/procedures/'
                    f'{pages.e(ident)}/{pages.e(sha)}/indexer">'
                    f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                    '<button type="submit">Indexer / reprendre</button></form>'
                )
            if etat == "INDEXE" and not version.active:
                courant = serie.get("version_courante")
                morceaux.append(
                    f'<form method="post" action="{pages.e(prefixe)}/memoire/procedures/'
                    f'{pages.e(ident)}/{pages.e(sha)}/activer">'
                    f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                    f'<input type="hidden" name="attendu_sha256" value="{pages.e(courant or "")}">'
                    '<button type="submit">Activer cette version</button></form>'
                )
        morceaux.append(
            f'<form method="post" action="{pages.e(prefixe)}/memoire/procedures/{pages.e(ident)}/oublier" class="pile">'
            f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
            '<label>Motif borné<input name="motif" maxlength="300" required></label>'
            "<label>Pour oublier toute cette série, saisir OUBLIER"
            '<input name="confirmation" maxlength="16" required></label>'
            '<button type="submit">Oublier toute la série</button></form></article>'
        )
    if total > offset + len(series) and offset < 50:
        morceaux.append(f'<a href="{pages.e(prefixe)}/memoire/procedures?offset={offset + 50}">Page suivante</a>')
    if offset:
        morceaux.append(
            f'<a href="{pages.e(prefixe)}/memoire/procedures?offset={max(0, offset - 50)}">Page précédente</a>'
        )
    morceaux.append(f"<p>{len(series)} série(s) affichée(s) sur {pages.e(total)}.</p></section>")
    return "".join(morceaux)


def creer_router(*, session_page: Callable[..., Session], prefixe: str) -> APIRouter:
    router = APIRouter()

    def session_vivante(request: Request, initiale: Session | None = None) -> Session:
        session = session_page(request)
        if initiale is not None and session.utilisateur != initiale.utilisateur:
            raise HTTPException(403, "session modifiée pendant la requête")
        return session

    def reponse_erreur(
        request: Request, initiale: Session, erreur: HTTPException, *, reprise: dict[str, str] | None = None
    ) -> Response:
        try:
            courante = session_vivante(request, initiale)
        except Exception:
            texte = pages.page_erreur("Action refusée", "La session administrateur n’est plus active.", prefixe=prefixe)
            return _privee(HTMLResponse(texte, status_code=403))
        return _erreur(courante, prefixe, erreur.status_code, str(erreur.detail), reprise=reprise)

    def sans_query(request: Request) -> None:
        if request.query_params:
            raise HTTPException(400, "paramètres invalides")

    async def formulaire_action(request: Request, initiale: Session, attendus: set[str]) -> dict[str, str]:
        content_type, _ = _media(request)
        if content_type != "application/x-www-form-urlencoded":
            raise HTTPException(415, "formulaire attendu")
        body = await _corps_borne(request, _CORPS_ACTION)

        recu = False

        async def recevoir():
            nonlocal recu
            if recu:
                return {"type": "http.disconnect"}
            recu = True
            return {"type": "http.request", "body": body, "more_body": False}

        clone = StarletteRequest(request.scope, receive=recevoir)
        form = None
        try:
            form = await clone.form(max_files=0, max_fields=4, max_part_size=16_384)
            items = form.multi_items()
            if len({key for key, _ in items}) != len(items):
                raise HTTPException(400, "champs dupliqués")
            fields = dict(items)
            if "csrf" not in fields:
                raise HTTPException(403, "jeton CSRF absent")
            if set(fields) != attendus:
                raise HTTPException(400, "champs invalides")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, "formulaire invalide") from exc
        finally:
            if form is not None:
                await form.close()
        if not securite.csrf_valide(fields.get("csrf"), initiale):
            raise HTTPException(403, "jeton CSRF invalide")
        session_vivante(request, initiale)
        return fields

    @router.get("/memoire/procedures")
    async def page_procedures(request: Request) -> Response:
        try:
            session = session_vivante(request)
            params = request.query_params
            if (
                set(params.keys()) - {"offset", "ok"}
                or len(params.getlist("offset")) > 1
                or len(params.getlist("ok")) > 1
            ):
                return _erreur(session, prefixe, 400, "paramètres invalides")
            raw_offset = params.get("offset", "0")
            if not raw_offset.isascii() or not raw_offset.isdecimal() or len(raw_offset) > 2 or int(raw_offset) > 64:
                return _erreur(session, prefixe, 400, "pagination invalide")
            offset = int(raw_offset)
            messages = {
                "admis": "Document admis comme REÇU.",
                "indexe": "Indexation terminée.",
                "active": "Version activée.",
                "oublie": "Série oubliée et journalisée.",
            }
            succes = messages.get(params.get("ok", ""), "")
            if params.get("ok") and not succes:
                return _erreur(session, prefixe, 400, "paramètres invalides")
            service = _service()
            page = await run_in_threadpool(service.lister_series, limite=50, offset=offset)
            versions = await run_in_threadpool(
                lambda: {
                    str(row["document_id"]): service.lister_versions(str(row["document_id"])) for row in page.series
                }
            )
            session = session_vivante(request, session)
            return _rend_page(
                session,
                prefixe,
                _contenu(session, prefixe, page.series, versions, offset=offset, total=page.total, succes=succes),
            )
        except HTTPException:
            raise
        except Exception:
            session = session_vivante(request)
            return _erreur(session, prefixe, 503, "mémoire indisponible; réessayez plus tard")

    @router.post("/memoire/procedures/admettre")
    async def admettre(request: Request) -> Response:
        session = session_vivante(request)
        fields: dict[str, str] | None = None
        try:
            sans_query(request)
            fields, source = await _formulaire(request)
            if not securite.csrf_valide(fields.get("csrf"), session):
                raise HTTPException(403, "jeton CSRF invalide")
            if fields["attestation"] != "oui" or not fields["titre"].strip() or len(fields["titre"]) > 300:
                raise HTTPException(400, "attestation ou titre invalide")
            if not _NONCE.fullmatch(fields["cle_admission"]):
                raise HTTPException(400, "clé de reprise invalide")
            document_id = fields["document_id"].strip() or None
            if document_id is not None and not _UUID.fullmatch(document_id):
                raise HTTPException(400, "identifiant de série invalide")
            session = session_vivante(request, session)
            from opsys.memoire.store import MemoireIndisponible

            try:
                await run_in_threadpool(
                    _service().admettre,
                    source,
                    fields["titre"],
                    auteur=session.utilisateur,
                    cle_admission=fields["cle_admission"],
                    document_id=document_id,
                )
            except MemoireIndisponible as exc:
                raise HTTPException(503, "mémoire indisponible; réessayez plus tard") from exc
            except ValueError as exc:
                status = 409 if "conflit" in str(exc).lower() or "quota" in str(exc).lower() else 400
                raise HTTPException(status, "admission refusée; rechargez la page et vérifiez le document") from exc
            session = session_vivante(request, session)
            return _privee(RedirectResponse(f"{prefixe}/memoire/procedures?ok=admis", status_code=303))
        except HTTPException as exc:
            return reponse_erreur(request, session, exc, reprise=fields or getattr(exc, "reprise", None))
        except Exception:
            try:
                session = session_vivante(request, session)
            except Exception:
                return _privee(
                    HTMLResponse(
                        pages.page_erreur(
                            "Action refusée", "La session administrateur n’est plus active.", prefixe=prefixe
                        ),
                        status_code=403,
                    )
                )
            return _erreur(session, prefixe, 503, "mémoire indisponible; réessayez plus tard", reprise=fields)

    @router.post("/memoire/procedures/indexer-recues")
    async def indexer_recues(request: Request) -> Response:
        session = session_vivante(request)
        try:
            sans_query(request)
            await formulaire_action(request, session, {"csrf"})
            service = _service()
            candidats = await run_in_threadpool(service.lister_recues, limite=5)
            indexees = 0
            deja_traitees = 0
            erreurs = 0
            for document_id, sha256 in candidats:
                session_vivante(request, session)
                try:
                    versions = await run_in_threadpool(service.lister_versions, document_id)
                    version = next((item for item in versions if item.sha256 == sha256), None)
                    session_vivante(request, session)
                    if version is None or version.etat != "RECU":
                        deja_traitees += 1
                        continue

                    def indexer_autorise(document_cible: str, empreinte_cible: str) -> Any:
                        # Revalider dans le thread qui exécutera la mutation, après l'attente du pool.
                        session_vivante(request, session)
                        return service.indexer(document_cible, empreinte_cible)

                    await run_in_threadpool(indexer_autorise, document_id, sha256)
                    indexees += 1
                except HTTPException:
                    raise
                except ValueError:
                    erreurs += 1
                except Exception:
                    erreurs += 1
            session = session_vivante(request, session)
            page = await run_in_threadpool(service.lister_series, limite=50, offset=0)
            versions_page = await run_in_threadpool(
                lambda: {
                    str(row["document_id"]): service.lister_versions(str(row["document_id"]))
                    for row in page.series
                }
            )
            session = session_vivante(request, session)
            succes = avertissement = ""
            if not candidats:
                succes = "Aucune version RECU à indexer."
            elif erreurs or deja_traitees:
                avertissement = (
                    f"Lot incomplet : {indexees} traitée(s), {deja_traitees} déjà traitée(s), "
                    f"{erreurs} refus stable(s) (ERREUR_INDEXATION). Les autres restent reprenables."
                )
            else:
                succes = f"Lot terminé : {indexees} traitée(s), {deja_traitees} déjà traitée(s)."
            return _rend_page(
                session, prefixe,
                _contenu(
                    session, prefixe, page.series, versions_page, offset=0, total=page.total,
                    succes=succes, avertissement=avertissement,
                ),
            )
        except HTTPException as exc:
            return reponse_erreur(request, session, exc)
        except Exception:
            try:
                session = session_vivante(request, session)
            except Exception:
                return _privee(HTMLResponse(
                    pages.page_erreur(
                        "Action refusée", "La session administrateur n’est plus active.", prefixe=prefixe
                    ),
                    status_code=403,
                ))
            return _erreur(session, prefixe, 503, "indexation du lot indisponible; les états reçus restent reprenables")

    @router.post("/memoire/procedures/{document_id}/{sha256}/indexer")
    async def indexer(request: Request, document_id: str, sha256: str) -> Response:
        session = session_vivante(request)
        try:
            sans_query(request)
            if not _UUID.fullmatch(document_id) or not _SHA.fullmatch(sha256):
                raise HTTPException(400, "identifiant invalide")
            await formulaire_action(request, session, {"csrf"})
            try:
                await run_in_threadpool(_service().indexer, document_id, sha256)
            except Exception as exc:
                status = 409 if isinstance(exc, ValueError) else 503
                raise HTTPException(status, "indexation refusée ou indisponible") from exc
            session = session_vivante(request, session)
            return _privee(RedirectResponse(f"{prefixe}/memoire/procedures?ok=indexe", status_code=303))
        except HTTPException as exc:
            return reponse_erreur(request, session, exc)

    @router.post("/memoire/procedures/{document_id}/{sha256}/activer")
    async def activer(request: Request, document_id: str, sha256: str) -> Response:
        session = session_vivante(request)
        try:
            sans_query(request)
            if not _UUID.fullmatch(document_id) or not _SHA.fullmatch(sha256):
                raise HTTPException(400, "identifiant invalide")
            fields = await formulaire_action(request, session, {"csrf", "attendu_sha256"})
            attendu = fields.get("attendu_sha256", "") or None
            if attendu is not None and not _SHA.fullmatch(attendu):
                raise HTTPException(400, "révision attendue invalide")
            try:
                await run_in_threadpool(
                    _service().activer, document_id, sha256, attendu_sha256=attendu, auteur=session.utilisateur
                )
            except Exception as exc:
                status = 409 if isinstance(exc, ValueError) else 503
                raise HTTPException(status, "activation refusée; rechargez l’état") from exc
            session = session_vivante(request, session)
            return _privee(RedirectResponse(f"{prefixe}/memoire/procedures?ok=active", status_code=303))
        except HTTPException as exc:
            return reponse_erreur(request, session, exc)

    @router.post("/memoire/procedures/{document_id}/oublier")
    async def oublier(request: Request, document_id: str) -> Response:
        session = session_vivante(request)
        try:
            sans_query(request)
            if not _UUID.fullmatch(document_id):
                raise HTTPException(400, "identifiant invalide")
            fields = await formulaire_action(request, session, {"csrf", "motif", "confirmation"})
            motif = fields.get("motif", "").strip()
            if fields.get("confirmation") != "OUBLIER" or not motif or len(motif) > 300:
                raise HTTPException(400, "confirmation et motif obligatoires")
            try:
                await run_in_threadpool(_service().oublier, document_id, demandeur=session.utilisateur, motif=motif)
            except Exception as exc:
                status = 409 if isinstance(exc, ValueError) else 503
                raise HTTPException(status, "oubli refusé ou indisponible") from exc
            session = session_vivante(request, session)
            return _privee(RedirectResponse(f"{prefixe}/memoire/procedures?ok=oublie", status_code=303))
        except HTTPException as exc:
            return reponse_erreur(request, session, exc)

    from .memoire_import_lots_ui import creer_router as creer_router_lots

    router.include_router(
        creer_router_lots(session_page=session_page, prefixe=prefixe, service_factory=_service)
    )
    return router
