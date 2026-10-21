"""API et page privée du pilote Fusion opérationnelle pour les lots CSV M5."""

from __future__ import annotations

import asyncio
import json
import re
import threading
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from email.message import Message
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.requests import Request as StarletteRequest

from .. import fusion_csv
from . import pages, securite
from .securite import Session

_JSON_BODY_MAX = 7 * 1_048_576
_TRAITER_JSON_MAX = 16_384
_MULTIPART_BODY_MAX = 1_048_576 + 65_536
_JSON_FIELDS = frozenset({"mutation_id", "compte_interne_id", "devise", "mapping_colonnes", "csv_utf8"})
_FORM_FIELDS = frozenset({"csrf", "mutation_id", "compte_interne_id", "devise", "mapping_date",
                          "mapping_montant", "mapping_reference_facture"})
_MAP_KEYS = ("date", "montant", "reference_facture")
_LOT_ID = re.compile(r"[0-9a-f-]{36}\Z")


async def _corps_borne(request: Request, maximum: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > maximum:
                raise HTTPException(413, "corps de requête trop volumineux")
        except ValueError as exc:
            raise HTTPException(400, "Content-Length invalide") from exc
    morceaux: list[bytes] = []
    total = 0
    async for morceau in request.stream():
        total += len(morceau)
        if total > maximum:
            raise HTTPException(413, "corps de requête trop volumineux")
        morceaux.append(morceau)
    return b"".join(morceaux)


def _objet_sans_doublons(paires: list[tuple[str, Any]]) -> dict[str, Any]:
    resultat: dict[str, Any] = {}
    for cle, valeur in paires:
        if cle in resultat:
            raise ValueError("clé JSON dupliquée")
        resultat[cle] = valeur
    return resultat


async def _json_borne(request: Request, maximum: int) -> dict[str, Any]:
    media, _ = _media(request)
    if media != "application/json":
        raise HTTPException(415, "Content-Type application/json requis")
    contenu = await _corps_borne(request, maximum)
    try:
        objet = json.loads(contenu.decode("utf-8", errors="strict"), object_pairs_hook=_objet_sans_doublons)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(400, "objet JSON UTF-8 invalide ou dupliqué") from exc
    if not isinstance(objet, dict):
        raise HTTPException(400, "objet JSON attendu")
    return objet


async def _formulaire_traitement_borne(request: Request) -> dict[str, str]:
    media, _ = _media(request)
    if media != "application/x-www-form-urlencoded":
        raise HTTPException(415, "formulaire urlencoded requis")
    contenu = await _corps_borne(request, _TRAITER_JSON_MAX)
    try:
        paires = parse_qs(contenu.decode("utf-8", errors="strict"), keep_blank_values=True, max_num_fields=2)
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(400, "formulaire de traitement invalide") from exc
    if set(paires) != {"csrf", "revision_attendue"} or any(len(values) != 1 for values in paires.values()):
        raise HTTPException(400, "champs de traitement invalides")
    return {key: values[0] for key, values in paires.items()}


def _revision_preparation(value: Any) -> int:
    if type(value) is not int or value < 1:
        raise HTTPException(400, "revision_attendue doit être un entier strict positif")
    return value


async def _executer_preparation(
    request: Request, cnx_factory: Callable[..., Any], acteur: str, lot_id: str, revision: int,
) -> dict[str, Any]:
    arret = threading.Event()
    travail = asyncio.create_task(run_in_threadpool(
        fusion_csv.preparer, cnx_factory, acteur, lot_id, revision, arret
    ))
    try:
        while not travail.done():
            if await request.is_disconnected():
                arret.set()
                break
            await asyncio.sleep(0.05)
        return await asyncio.shield(travail)
    except BaseException:
        arret.set()
        with suppress(BaseException):
            await asyncio.shield(travail)
        raise
    finally:
        arret.set()


def _media(request: Request) -> tuple[str, str | None]:
    message = Message()
    message["content-type"] = request.headers.get("content-type", "")
    return message.get_content_type(), message.get_param("boundary", header="content-type")


async def _formulaire_multipart(request: Request, *, html_form: bool) -> tuple[dict[str, Any], bytes]:
    media, boundary = _media(request)
    if media != "multipart/form-data" or not isinstance(boundary, str) or not 1 <= len(boundary) <= 70:
        raise HTTPException(415, "multipart/form-data avec boundary requis")
    contenu = await _corps_borne(request, _MULTIPART_BODY_MAX)
    lu = False

    async def recevoir():
        nonlocal lu
        if lu:
            return {"type": "http.disconnect"}
        lu = True
        return {"type": "http.request", "body": contenu, "more_body": False}

    clone = StarletteRequest(request.scope, receive=recevoir)
    form = None
    try:
        form = await clone.form(max_files=1, max_fields=8, max_part_size=16_384)
        items = form.multi_items()
        names = [key for key, _ in items]
        if len(names) != len(set(names)):
            raise HTTPException(400, "champs multipart dupliqués")
        values = dict(items)
        required = set(_FORM_FIELDS | {"csv_file"})
        if not html_form:
            required.remove("csrf")
        if set(values) != required:
            raise HTTPException(400, "champs multipart invalides")
        file = values.get("csv_file")
        if not isinstance(file, UploadFile):
            raise HTTPException(400, "fichier CSV absent")
        source = await file.read(fusion_csv.TAILLE_SOURCE_MAX + 1)
        if len(source) > fusion_csv.TAILLE_SOURCE_MAX:
            raise HTTPException(413, "source CSV supérieure à 1 Mio")
        fields = {key: values[key] for key in required if key != "csv_file"}
        if any(not isinstance(value, str) for value in fields.values()):
            raise HTTPException(400, "champ multipart invalide")
        return fields, source
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(400, "formulaire multipart invalide") from exc
    finally:
        if form is not None:
            await form.close()


async def _demande_creation(request: Request, *, html_form: bool = False) -> tuple[dict[str, Any], bytes]:
    media, _ = _media(request)
    if html_form and media != "multipart/form-data":
        raise HTTPException(415, "le formulaire HTML exige multipart/form-data")
    if media == "application/json":
        objet = await _json_borne(request, _JSON_BODY_MAX)
        if set(objet) != _JSON_FIELDS:
            raise HTTPException(400, "champs JSON de création invalides")
        source = objet.get("csv_utf8")
        if not isinstance(source, str):
            raise HTTPException(400, "csv_utf8 doit être une chaîne")
        try:
            source_bytes = source.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise HTTPException(400, "csv_utf8 invalide") from exc
        body = dict(objet)
        body.pop("csv_utf8")
        return body, source_bytes
    if media == "multipart/form-data":
        fields, source = await _formulaire_multipart(request, html_form=html_form)
        if html_form:
            body = {
                key: fields[key] for key in _FORM_FIELDS if key != "csrf"
            }
            if not securite.csrf_valide(fields.get("csrf"), request.state.fusion_session):
                raise HTTPException(403, "jeton CSRF absent ou invalide")
        else:
            body = dict(fields)
        body["mapping_colonnes"] = {
            "date": body.pop("mapping_date"), "montant": body.pop("mapping_montant"),
            "reference_facture": body.pop("mapping_reference_facture"),
        }
        return body, source
    raise HTTPException(415, "Content-Type application/json ou multipart/form-data requis")


def _normaliser(body: Mapping[str, Any]) -> dict[str, Any]:
    if set(body) != _JSON_FIELDS - {"csv_utf8"}:
        raise HTTPException(400, "champs de création invalides")
    mapping = body.get("mapping_colonnes")
    if not isinstance(mapping, Mapping) or set(mapping) != set(_MAP_KEYS):
        raise HTTPException(400, "mapping_colonnes invalide")
    return {
        "mutation_id": body.get("mutation_id"), "compte_interne_id": body.get("compte_interne_id"),
        "devise": body.get("devise"), "mapping_colonnes": dict(mapping),
    }


def _form_page(
    prefixe: str, session: Session, comptes: tuple[str, ...], lots: list[Mapping[str, Any]], notice: str = ""
) -> str:
    account_options = "".join(
        f'<option value="{pages.e(compte)}">{pages.e(compte)}</option>' for compte in comptes
    )
    lot_rows = []
    for lot in lots:
        status = pages.e(lot["statut"])
        rows = pages.e(lot.get("curseur", 0))
        total = pages.e(lot.get("total_lignes") if lot.get("total_lignes") is not None else "à traiter")
        propositions = pages.e(lot.get("nombre_propositions", 0))
        lot_id = pages.e(lot["lot_id"])
        action = ""
        if lot["statut"] in {"RECU", "EN_COURS", "ERREUR_REPRENABLE"}:
            action = (
                f'<form method="post" action="{pages.e(prefixe)}/fusion-operationnelle/lots/{lot_id}/preparer">'
                f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                f'<input type="hidden" name="revision_attendue" value="{pages.e(lot["revision"])}">'
                '<button type="submit" class="principal">Préparer le lot</button></form>'
                f'<form method="post" action="{pages.e(prefixe)}/fusion-operationnelle/lots/{lot_id}/traiter">'
                f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                f'<input type="hidden" name="revision_attendue" value="{pages.e(lot["revision"])}">'
                '<button type="submit">Traiter / reprendre</button></form>'
            )
        detail = (
            f'<a href="{pages.e(prefixe)}/fusion-operationnelle/lots/{lot_id}">Consulter</a>'
        )
        lot_rows.append(
            f"<tr><td><code>{lot_id}</code></td><td>{status}</td><td>{rows} / {total}</td>"
        f"<td>{propositions} potentielles</td><td>{detail} {action}</td></tr>"
        )
    table = (
        "<table><thead><tr><th>Lot</th><th>État</th><th>Lignes préparées</th>"
        "<th>Propositions potentielles</th><th>Action</th></tr></thead>"
        f"<tbody>{''.join(lot_rows)}</tbody></table>" if lot_rows else "<p>Aucun lot.</p>"
    )
    contenu = (
        f'<p class="note">{pages.e(notice)}</p>' if notice else ""
    ) + (
        f'<form method="post" enctype="multipart/form-data" action="{pages.e(prefixe)}/fusion-operationnelle/lots" '
        'class="carte pile"><input type="hidden" name="csrf" value="' + pages.e(session.csrf) + '">'
        f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
        '<label for="csv_file">Relevé CSV UTF-8 (1 Mio maximum)</label>'
        '<input id="csv_file" name="csv_file" type="file" accept=".csv,text/csv" required>'
        '<label for="compte_interne_id">Compte interne</label>'
        f'<select id="compte_interne_id" name="compte_interne_id" required>{account_options}</select>'
        '<input type="hidden" name="devise" value="CAD">'
        '<label for="mapping_date">Colonne date</label>'
        '<input id="mapping_date" name="mapping_date" maxlength="128" required>'
        '<label for="mapping_montant">Colonne montant</label>'
        '<input id="mapping_montant" name="mapping_montant" maxlength="128" required>'
        '<label for="mapping_reference_facture">Colonne référence facture</label>'
        '<input id="mapping_reference_facture" name="mapping_reference_facture" maxlength="128" required>'
        '<button type="submit" class="principal">Importer le CSV</button></form>'
        '<section class="carte pile"><h2>Lots de rapprochement préparatoire</h2>' + table + '</section>'
    )
    return pages.gabarit("Fusion opérationnelle", contenu, prefixe=prefixe, session=session, actif="fusion")


def _detail_page(prefixe: str, session: Session, lot: Mapping[str, Any], debut: int) -> str:
    status = pages.e(lot["statut"])
    total = lot.get("total_lignes")
    curseur = lot.get("curseur", 0)
    snapshot = pages.e(f'{lot.get("snapshot_version")} / {lot.get("snapshot_empreinte")}')
    contents = [
        f'<dl><dt>État</dt><dd>{status}</dd><dt>Progression</dt><dd>{pages.e(curseur)} / '
        f'{pages.e(total if total is not None else "à traiter")}</dd>'
        f'<dt>Snapshot M5</dt><dd><code>{snapshot}</code></dd></dl>'
    ]
    if lot["statut"] in {"RECU", "EN_COURS", "ERREUR_REPRENABLE"}:
        contents.append(
            '<p>Traitement incomplet : préparation des lignes en cours; '
            'les propositions potentielles restent masquées '
            'jusqu’à la revue après achèvement. '
            'La provenance M10 sera créée à la première transition terminale.</p>'
        )
        if lot["statut"] in {"RECU", "EN_COURS"}:
            contents.append(
                f'<form method="post" action="{pages.e(prefixe)}/fusion-operationnelle/lots/'
                f'{pages.e(lot["lot_id"])}/preparer"><input type="hidden" name="csrf" '
                f'value="{pages.e(session.csrf)}"><input type="hidden" name="revision_attendue" '
                f'value="{pages.e(lot["revision"])}"><button class="principal" type="submit">'
                'Préparer le lot</button></form>'
            )
    elif lot["statut"] == "SNAPSHOT_OBSOLETE":
        contents.append('<p>Snapshot obsolète : les lignes et propositions ne sont plus consultables.</p>')
    elif lot["statut"] == "REFUSE":
        contents.append('<p>Le parseur M5 a refusé ce relevé; aucune proposition n’est disponible.</p>')
    elif lot["statut"] in {"PROPOSITIONS", "AUCUNE_PROPOSITION"}:
        if lot["statut"] == "PROPOSITIONS":
            contents.append(
                '<p class="note">Propositions préparatoires uniquement. Vérification humaine requise; '
                'aucune facture, écriture, aucun solde ni paiement ne sont modifiés.</p>'
            )
        else:
            contents.append('<p>Aucune proposition de rapprochement.</p>')
        lines = lot.get("lignes", [])
        page_size = 100
        visibles = lines[debut:debut + page_size]
        if visibles:
            rows = []
            for line in visibles:
                cells = (line.get("numero"), line.get("date"), line.get("montant"),
                         line.get("reference_facture"), line.get("statut_rapprochement"))
                rows.append("<tr>" + "".join(f"<td>{pages.e(value)}</td>" for value in cells) + "</tr>")
            contents.append(
                '<table><thead><tr><th>Ligne</th><th>Date</th><th>Montant</th><th>Référence facture</th>'
                '<th>État</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>"
            )
            if len(lines) > page_size:
                previous = max(0, debut - page_size)
                next_start = debut + page_size
                contents.append('<nav aria-label="Pages de lignes">')
                if debut:
                    contents.append(
                        f'<a rel="prev" href="{pages.e(prefixe)}/fusion-operationnelle/lots/'
                        f'{pages.e(lot["lot_id"])}?debut={previous}">Précédent</a> '
                    )
                if next_start < len(lines):
                    contents.append(
                        f'<a rel="next" href="{pages.e(prefixe)}/fusion-operationnelle/lots/'
                        f'{pages.e(lot["lot_id"])}?debut={next_start}">Suivant</a>'
                    )
                contents.append('</nav>')
        if lot["statut"] == "PROPOSITIONS":
            propositions = [line for line in lines if line.get("statut_rapprochement") == "PROPOSITION_EXACTE"]
            contents.append(f'<p>Propositions préparatoires : {pages.e(len(propositions))}</p>')
    contents.append(f'<p><a href="{pages.e(prefixe)}/fusion-operationnelle">Retour aux lots</a></p>')
    return pages.gabarit(
        "Détail du lot Fusion", "".join(contents), prefixe=prefixe, session=session, actif="fusion"
    )


def _preparation_page(prefixe: str, session: Session, resultat: Mapping[str, Any]) -> str:
    lot = resultat["lot"]
    avance = f'{lot["curseur"]} / {lot["total_lignes"] if lot["total_lignes"] is not None else "à déterminer"}'
    status = lot["statut"]
    if status == "SNAPSHOT_OBSOLETE":
        titre_progression = "Snapshot M5 périmé; les propositions ne sont pas consultables."
    elif status == "REFUSE":
        titre_progression = "Le relevé a été refusé par le parseur M5."
    elif status in {"PROPOSITIONS", "AUCUNE_PROPOSITION"}:
        titre_progression = "Préparation achevée; le résultat reste une proposition préparatoire."
    else:
        titre_progression = "Préparation interrompue; le lot peut être repris."
    if status == "PROPOSITIONS":
        note = "Propositions préparatoires visibles dans le détail privé; une revue humaine reste nécessaire."
    elif status == "AUCUNE_PROPOSITION":
        note = "Préparation achevée sans proposition de rapprochement."
    elif status == "REFUSE":
        note = "Le parseur a refusé la source; aucune proposition n’est disponible."
    elif status == "SNAPSHOT_OBSOLETE":
        note = "Le snapshot M5 a changé; ce résultat ne peut pas être consulté."
    else:
        note = "Les propositions potentielles seront consultables après achèvement."
    contenu = (
        f'<p>{pages.e(titre_progression)}</p>'
        f'<dl><dt>État</dt><dd>{pages.e(lot["statut"])}</dd>'
        f'<dt>Progression des lignes</dt><dd>{pages.e(avance)}</dd>'
        f'<dt>Propositions potentielles</dt><dd>{pages.e(lot["nombre_propositions"])}</dd>'
        f'<dt>Tranches préparées</dt><dd>{pages.e(resultat["preparation"]["tranches_executees"])}</dd>'
        f'<dt>Limite serveur</dt><dd>{pages.e(resultat["preparation"]["limite_tranches"])}</dd>'
        f'<dt>Arrêt</dt><dd>{pages.e(resultat["preparation"]["arret"])}</dd></dl>'
        f'<p>{pages.e(note)}</p>'
        f'<p><a href="{pages.e(prefixe)}/fusion-operationnelle/lots/{pages.e(lot["lot_id"])}">Consulter le lot</a></p>'
    )
    return pages.gabarit("Préparation du lot", contenu, prefixe=prefixe, session=session, actif="fusion")


def creer_router(
    *, session_page: Callable[..., Session], session_api: Callable[..., Session],
    ecriture_api: Callable[[Request], Session], formulaire: Callable[[Request], Any],
    cnx_factory: Callable[..., Any], deps: Mapping[str, Any], lire_comptes: Callable[[], tuple[str, ...]],
    prefixe: str,
) -> APIRouter:
    router = APIRouter()

    def appeler(action: Callable, *args: Any, **kwargs: Any):
        try:
            return action(*args, **kwargs)
        except PermissionError as exc:
            raise HTTPException(403, "accès Fusion opérationnelle refusé") from exc
        except fusion_csv.FusionErreur as exc:
            raise HTTPException(exc.statut_http, exc.publique()) from exc

    def revalider_session(lecteur: Callable[..., Session], request: Request, acteur: str) -> None:
        session = lecteur(request)
        if session.utilisateur != acteur:
            raise HTTPException(403, "identité Fusion opérationnelle modifiée pendant la préparation")

    @router.get("/fusion-operationnelle", response_class=HTMLResponse)
    def page_fusion(request: Request) -> HTMLResponse:
        session = session_page(request)
        lots = appeler(fusion_csv.lister, cnx_factory, session.utilisateur)
        return HTMLResponse(_form_page(prefixe, session, lire_comptes(), lots))

    @router.get("/fusion-operationnelle/lots/{lot_id}", response_class=HTMLResponse)
    def detail_lot(lot_id: str, request: Request) -> HTMLResponse:
        session = session_page(request)
        if not _LOT_ID.fullmatch(lot_id):
            raise HTTPException(400, "identifiant de lot invalide")
        valeurs = request.query_params.getlist("debut")
        if set(request.query_params) - {"debut"} or len(valeurs) > 1:
            raise HTTPException(400, "paramètres de détail invalides")
        debut = 0
        if valeurs:
            if not re.fullmatch(r"(?:0|[1-9][0-9]{0,3})", valeurs[0]):
                raise HTTPException(400, "offset de détail invalide")
            debut = int(valeurs[0])
            if debut > 1_900 or debut % 100:
                raise HTTPException(400, "offset de détail hors limite")
        lot = appeler(fusion_csv.lire, cnx_factory, session.utilisateur, lot_id)
        return HTMLResponse(
            _detail_page(prefixe, session, lot, debut), headers={"Cache-Control": "no-store"}
        )

    @router.get("/api/fusion-operationnelle/lots")
    def liste_lots(request: Request) -> dict[str, Any]:
        session = session_api(request)
        if request.query_params:
            raise HTTPException(400, "paramètres de liste non pris en charge")
        return {"lots": appeler(fusion_csv.lister, cnx_factory, session.utilisateur)}

    @router.get("/api/fusion-operationnelle/lots/{lot_id}")
    def lire_lot(lot_id: str, request: Request) -> dict[str, Any]:
        session = session_api(request)
        if request.query_params or not _LOT_ID.fullmatch(lot_id):
            raise HTTPException(400, "identifiant ou paramètres de lot invalides")
        return {"lot": appeler(fusion_csv.lire, cnx_factory, session.utilisateur, lot_id)}

    @router.get("/api/fusion-operationnelle/lots/{lot_id}/provenance")
    def provenance(lot_id: str, request: Request) -> dict[str, Any]:
        session = session_api(request)
        if request.query_params or not _LOT_ID.fullmatch(lot_id):
            raise HTTPException(400, "identifiant ou paramètres de lot invalides")
        return {"provenance": appeler(fusion_csv.lire_provenance, cnx_factory, session.utilisateur, lot_id)}

    @router.post("/api/fusion-operationnelle/lots")
    async def creer_lot_api(request: Request) -> JSONResponse:
        session = ecriture_api(request)
        body, source = await _demande_creation(request)
        champs = _normaliser(body)
        resultat = appeler(
            fusion_csv.creer, cnx_factory, deps, session.utilisateur, **champs, csv_octets=source,
        )
        return JSONResponse({"lot": resultat}, status_code=201, headers={"Cache-Control": "no-store"})

    @router.post("/api/fusion-operationnelle/lots/{lot_id}/traiter")
    async def traiter_api(lot_id: str, request: Request) -> JSONResponse:
        session = ecriture_api(request)
        if not _LOT_ID.fullmatch(lot_id):
            raise HTTPException(400, "identifiant de lot invalide")
        data = await _json_borne(request, _TRAITER_JSON_MAX)
        if not isinstance(data, Mapping) or set(data) != {"revision_attendue"}:
            raise HTTPException(400, "champs de traitement invalides")
        resultat = appeler(fusion_csv.traiter, cnx_factory, session.utilisateur, lot_id, data["revision_attendue"])
        return JSONResponse({"lot": resultat}, headers={"Cache-Control": "no-store"})

    @router.post("/api/fusion-operationnelle/lots/{lot_id}/preparer")
    async def preparer_api(lot_id: str, request: Request) -> JSONResponse:
        session = ecriture_api(request)
        if not _LOT_ID.fullmatch(lot_id) or request.query_params:
            raise HTTPException(400, "identifiant ou paramètres de lot invalides")
        data = await _json_borne(request, _TRAITER_JSON_MAX)
        if set(data) != {"revision_attendue"}:
            raise HTTPException(400, "champs de préparation invalides")
        revision = _revision_preparation(data["revision_attendue"])
        try:
            resultat = await _executer_preparation(request, cnx_factory, session.utilisateur, lot_id, revision)
            revalider_session(session_api, request, session.utilisateur)
            resultat["lot"] = await run_in_threadpool(
                fusion_csv.relire_resume_preparation, cnx_factory, session.utilisateur, lot_id,
                resultat["lot"]["revision"],
            )
            revalider_session(session_api, request, session.utilisateur)
        except PermissionError as exc:
            raise HTTPException(403, "accès Fusion opérationnelle refusé") from exc
        except fusion_csv.FusionErreur as exc:
            raise HTTPException(exc.statut_http, exc.publique()) from exc
        return JSONResponse(resultat, headers={"Cache-Control": "no-store"})

    @router.post("/fusion-operationnelle/lots")
    async def creer_lot_form(request: Request) -> RedirectResponse:
        session = session_page(request)
        # Validation CSRF s'effectue après lecture bornée du formulaire, sans appel service préalable.
        request.state.fusion_session = session
        body, source = await _demande_creation(request, html_form=True)
        champs = _normaliser(body)
        appeler(fusion_csv.creer, cnx_factory, deps, session.utilisateur, **champs, csv_octets=source)
        return RedirectResponse(f"{prefixe}/fusion-operationnelle", status_code=303)

    @router.post("/fusion-operationnelle/lots/{lot_id}/traiter")
    async def traiter_form(lot_id: str, request: Request) -> HTMLResponse:
        session = session_page(request)
        if not _LOT_ID.fullmatch(lot_id):
            raise HTTPException(400, "identifiant de lot invalide")
        champs = await _formulaire_traitement_borne(request)
        if set(champs) != {"csrf", "revision_attendue"} or not securite.csrf_valide(champs.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou champs invalides")
        try:
            revision = int(champs["revision_attendue"])
            fusion_csv.traiter(cnx_factory, session.utilisateur, lot_id, revision)
        except fusion_csv.FusionErreur as exc:
            raise HTTPException(exc.statut_http, exc.publique()) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "revision_attendue invalide") from exc
        except PermissionError as exc:
            raise HTTPException(403, "accès Fusion opérationnelle refusé") from exc
        lots = appeler(fusion_csv.lister, cnx_factory, session.utilisateur)
        return HTMLResponse(_form_page(
            prefixe, session, lire_comptes(), lots, "Lot traité; rechargez son état pour continuer."
        ))

    @router.post("/fusion-operationnelle/lots/{lot_id}/preparer")
    async def preparer_form(lot_id: str, request: Request) -> HTMLResponse:
        session = session_page(request)
        if not _LOT_ID.fullmatch(lot_id) or request.query_params:
            raise HTTPException(400, "identifiant ou paramètres de lot invalides")
        champs = await _formulaire_traitement_borne(request)
        if not securite.csrf_valide(champs.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        try:
            raw_revision = champs["revision_attendue"]
            if not re.fullmatch(r"[1-9][0-9]{0,9}", raw_revision):
                raise HTTPException(400, "revision_attendue invalide")
            revision = _revision_preparation(int(raw_revision))
            resultat = await _executer_preparation(request, cnx_factory, session.utilisateur, lot_id, revision)
            revalider_session(session_page, request, session.utilisateur)
            resultat["lot"] = await run_in_threadpool(
                fusion_csv.relire_resume_preparation, cnx_factory, session.utilisateur, lot_id,
                resultat["lot"]["revision"],
            )
            revalider_session(session_page, request, session.utilisateur)
        except fusion_csv.FusionErreur as exc:
            raise HTTPException(exc.statut_http, exc.publique()) from exc
        except PermissionError as exc:
            raise HTTPException(403, "accès Fusion opérationnelle refusé") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(400, "revision_attendue invalide") from exc
        return HTMLResponse(_preparation_page(prefixe, session, resultat), headers={"Cache-Control": "no-store"})

    return router
