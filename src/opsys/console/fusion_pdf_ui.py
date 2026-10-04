"""Pages privées d'admission et de consultation du pilote PDF natif Finance."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from email.message import Message
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.requests import Request as StarletteRequest

from .. import fusion_pdf, identite
from . import pages, securite
from .securite import Session

_SOURCE_MAX = fusion_pdf.SOURCE_MAX
_BODY_MAX = _SOURCE_MAX + 65_536
_ACTION_MAX = 16_384
_MUTATION = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_STATUTS = {"RECU", "EXTRAIT_PREPARATOIRE", "REFUSE", "ERREUR_REPRENABLE"}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_EXTRACTEUR = re.compile(r"pypdf-[0-9]+\.[0-9]+\.[0-9]+/pdf-natif-[1-9][0-9]*\Z")
_CHAMPS_PROVENANCE = frozenset({
    "type_entree", "genre", "lot_id", "reference_locale", "source_sha256", "classe", "auteur",
    "acteur_transition", "extracteur", "configuration_sha256", "source_revision", "revision",
    "statut", "total_pages", "code", "horodatage",
})


def _privee(reponse: Response) -> Response:
    reponse.headers["Cache-Control"] = "private, no-store, max-age=0"
    reponse.headers["Pragma"] = "no-cache"
    reponse.headers["X-Content-Type-Options"] = "nosniff"
    return reponse


def _reponse(prefixe: str, session: Session, contenu: str, status: int = 200) -> HTMLResponse:
    html = pages.gabarit("Fusion PDF préparatoire", contenu, prefixe=prefixe, session=session, actif="fusion")
    return _privee(HTMLResponse(html, status_code=status))  # type: ignore[return-value]


def _formulaire_admission(prefixe: str, session: Session, mutation_id: str, erreur: str = "") -> str:
    notice = f'<p role="alert">{pages.e(erreur)}</p>' if erreur else ""
    return (
        '<section class="carte pile"><h2>Admettre un PDF</h2>'
        "<p>Les lots et extraits sont partagés entre les administrateurs de cette base d’entreprise. "
        "Les extraits sont préparatoires, ne constituent pas des données comptables vérifiées et "
        "ne créent aucune écriture, facture, estimation ou paiement. Le worker peut finir et enregistrer "
        "son résultat même si la connexion à cette page est interrompue.</p>"
        f'{notice}<form method="post" enctype="multipart/form-data" '
        f'action="{pages.e(prefixe)}/fusion/pdf/lots" class="pile">'
        f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
        f'<input type="hidden" name="mutation_id" value="{pages.e(mutation_id)}">'
        '<label>Document PDF<input type="file" name="pdf_file" accept="application/pdf,.pdf" required></label>'
        '<button type="submit" class="principal">Admettre le PDF</button></form></section>'
    )


def _resume(lot: Mapping[str, Any]) -> str:
    cles = (
        ("lot_id", "Identifiant"),
        ("acteur", "Auteur"),
        ("type_source", "Type"),
        ("classe", "Classe"),
        ("source_sha256", "SHA-256 source"),
        ("source_octets", "Taille source"),
        ("extracteur", "Extracteur"),
        ("configuration_sha256", "Configuration SHA-256"),
        ("statut", "État"),
        ("revision", "Révision"),
        ("total_pages", "Pages"),
        ("cree_le", "Créé le"),
        ("modifie_le", "Modifié le"),
    )
    lignes = "".join(f"<dt>{pages.e(libelle)}</dt><dd>{pages.e(lot.get(cle, '—'))}</dd>" for cle, libelle in cles)
    code = lot.get("code")
    if code:
        lignes += f"<dt>Code de résultat</dt><dd>{pages.e(code)}</dd>"
    return f'<dl class="meta">{lignes}</dl>'


def _provenance(lot: Mapping[str, Any], trace: Any) -> str:
    """Rend les seules métadonnées du port PDF/M10, jamais le texte ni un lien exécutable."""
    debut = '<section class="carte pile"><h2>Provenance M10</h2>'
    if trace is None:
        return debut + (
            "<p>Provenance M10 absente pour ce lot. La consultation ne crée pas de trace historique.</p></section>"
        )
    invalide = fusion_pdf.FusionPDFErreur(
        "PDF_PROVENANCE_INDISPONIBLE", "provenance PDF temporairement indisponible", 503,
    )
    if not isinstance(trace, Mapping) or set(trace) != _CHAMPS_PROVENANCE:
        raise invalide
    attendus = {
        "type_entree": "provenance_documentaire", "genre": "m5.document_pdf_natif", "classe": "FINANCIAL",
        "lot_id": lot.get("lot_id"), "auteur": lot.get("acteur"), "source_sha256": lot.get("source_sha256"),
        "configuration_sha256": lot.get("configuration_sha256"), "extracteur": lot.get("extracteur"),
        "statut": lot.get("statut"), "source_revision": lot.get("revision"),
        "total_pages": lot.get("total_pages"), "code": lot.get("code"),
        "horodatage": lot.get("modifie_le"),
        "reference_locale": f"opsys-ingestion://m05-financecore/pdf/lots/{lot.get('lot_id')}",
    }
    if any(trace[cle] != valeur for cle, valeur in attendus.items()):
        raise invalide
    if (
        type(trace["revision"]) is not int or trace["revision"] < 1
        or type(trace["source_revision"]) is not int or trace["source_revision"] < 1
        or type(lot.get("revision")) is not int
        or type(trace["total_pages"]) is not int or not 0 <= trace["total_pages"] <= fusion_pdf.PAGES_MAX
        or type(lot.get("total_pages")) is not int
        or not isinstance(trace["statut"], str) or trace["statut"] not in _STATUTS
        or not isinstance(trace["lot_id"], str) or not _UUID.fullmatch(trace["lot_id"])
    ):
        raise invalide
    try:
        if str(uuid.UUID(trace["lot_id"])) != trace["lot_id"]:
            raise invalide
    except ValueError:
        raise invalide from None
    for cle in ("source_sha256", "configuration_sha256"):
        if not isinstance(trace[cle], str) or not _SHA256.fullmatch(trace[cle]):
            raise invalide
    for cle, maximum in (("auteur", 64), ("acteur_transition", 64), ("extracteur", 128), ("horodatage", 64)):
        valeur = trace[cle]
        if not isinstance(valeur, str) or not 1 <= len(valeur) <= maximum or not valeur.isprintable():
            raise invalide
    if (
        not identite.identifiant_valide(trace["auteur"]) or not identite.identifiant_valide(trace["acteur_transition"])
        or not _EXTRACTEUR.fullmatch(trace["extracteur"])
    ):
        raise invalide
    try:
        instant = datetime.fromisoformat(trace["horodatage"])
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise invalide
    except (ValueError, OverflowError):
        raise invalide from None
    if (trace["statut"] == "EXTRAIT_PREPARATOIRE") != (trace["total_pages"] > 0):
        raise invalide
    if trace["statut"] in {"RECU", "EXTRAIT_PREPARATOIRE"} and trace["code"] is not None:
        raise invalide
    if trace["code"] is not None and (
        not isinstance(trace["code"], str) or not 1 <= len(trace["code"]) <= 128 or not trace["code"].isprintable()
    ):
        raise invalide
    if (
        trace["statut"] == "REFUSE" and trace["code"] not in fusion_pdf._REFUS
        or trace["statut"] == "ERREUR_REPRENABLE" and trace["code"] not in fusion_pdf._TEMPORAIRES
    ):
        raise invalide
    cles = (
        ("classe", "Classe source"), ("statut", "État de la source"),
        ("source_revision", "Révision du lot PDF"), ("revision", "Révision M10"),
        ("total_pages", "Pages préparées"), ("extracteur", "Extracteur"),
        ("horodatage", "Trace enregistrée le"), ("reference_locale", "Référence locale"),
    )
    lignes = "".join(f"<dt>{pages.e(label)}</dt><dd>{pages.e(trace[cle])}</dd>" for cle, label in cles)
    return debut + (
        "<p>Source candidate préparatoire, non validée. Cette provenance ne constitue pas une validation comptable "
        "et ne copie pas le texte du PDF dans la mémoire.</p>"
        f'<dl class="meta">{lignes}</dl></section>'
    )


def _liste(
    prefixe: str,
    session: Session,
    lots: list[Mapping[str, Any]],
    erreur: str = "",
    mutation_id: str | None = None,
) -> str:
    form = _formulaire_admission(prefixe, session, mutation_id or uuid.uuid4().hex, erreur)
    lignes = []
    for lot in lots:
        ident = pages.e(lot.get("lot_id", ""))
        if not _UUID.fullmatch(str(lot.get("lot_id", ""))):
            continue
        lignes.append(
            "<tr>"
            f'<td><a href="{pages.e(prefixe)}/fusion/pdf/lots/{ident}"><code>{ident}</code></a></td>'
            f"<td>{pages.e(lot.get('acteur', ''))}</td><td>{pages.e(lot.get('statut', ''))}</td>"
            f"<td>{pages.e(lot.get('revision', ''))}</td><td>{pages.e(lot.get('total_pages', 0))}</td>"
            f"<td>{pages.e(lot.get('cree_le', ''))}</td></tr>"
        )
    table = (
        "<table><thead><tr><th>Lot</th><th>Auteur</th><th>État</th><th>Révision</th><th>Pages</th>"
        f"<th>Créé le</th></tr></thead><tbody>{''.join(lignes)}</tbody></table>"
        if lignes
        else "<p>Aucun lot PDF.</p>"
    )
    return (
        '<p><a href="'
        + pages.e(prefixe)
        + '/fusion">Retour à Fusion</a></p>'
        + form
        + '<section class="carte pile"><h2>Lots PDF récents (maximum 16)</h2>'
        + table
        + "</section>"
    )


def _detail(prefixe: str, session: Session, lot: Mapping[str, Any], erreur: str = "") -> str:
    statut = str(lot.get("statut", ""))
    if statut not in _STATUTS:
        raise HTTPException(502, "état de lot invalide")
    contenu = [
        f'<p><a href="{pages.e(prefixe)}/fusion/pdf">Retour aux lots</a></p>',
        _resume(lot),
    ]
    if erreur:
        contenu.append(f'<p role="alert">{pages.e(erreur)}</p>')
    if statut in {"RECU", "ERREUR_REPRENABLE"}:
        contenu.append(
            "<p>La préparation peut prendre jusqu’à 15 secondes. Si la page est quittée, le traitement "
            "peut continuer et son commit peut avoir lieu. Rechargez ensuite l’état du lot.</p>"
            f'<form method="post" action="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot["lot_id"])}/preparer">'
            f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
            f'<input type="hidden" name="revision_attendue" value="{pages.e(lot["revision"])}">'
            '<button class="principal" type="submit">Préparer les extraits</button></form>'
        )
    elif statut == "EXTRAIT_PREPARATOIRE":
        contenu.append(
            "<p>Texte dérivé préparatoire seulement; vérification humaine requise. Aucun décompte réel "
            "ni effet comptable n’en découle.</p>"
            f'<a href="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot["lot_id"])}/extraits?page=1">'
            "Consulter explicitement les extraits</a>"
            f'<p><a href="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot["lot_id"])}/ap">'
            "Ouvrir la revue AP préparatoire</a></p>"
        )
    elif statut == "REFUSE":
        contenu.append("<p>Le worker a refusé le document. Aucun extrait n’est disponible.</p>")
    return '<section class="carte pile"><h2>Lot PDF</h2>' + "".join(contenu) + "</section>"


def _extraits(prefixe: str, session: Session, lot_id: str, resultat: Mapping[str, Any], page: int) -> str:
    pages_resultat = resultat.get("pages")
    if not isinstance(pages_resultat, list) or not 1 <= page <= len(pages_resultat):
        raise HTTPException(400, "page d’extrait invalide")
    page_pdf = pages_resultat[page - 1]
    fragments = page_pdf.get("fragments", [])
    lignes = []
    for fragment in fragments:
        lignes.append(f"<pre>{pages.e(fragment.get('texte', ''))}</pre>")
    navigation = []
    if page > 1:
        navigation.append(
            f'<a rel="prev" href="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}'
            f'/extraits?page={page - 1}">Page précédente</a>'
        )
    if page < len(pages_resultat):
        navigation.append(
            f'<a rel="next" href="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}'
            f'/extraits?page={page + 1}">Page suivante</a>'
        )
    return (
        f'<p><a href="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}">Retour aux métadonnées</a></p>'
        '<p class="note">Extrait préparatoire dérivé du PDF, à vérifier. Ce texte ne représente pas '
        "un décompte ou une donnée comptable réelle et ne produit aucune écriture.</p>"
        f"<h2>Page {page} sur {len(pages_resultat)}</h2>{''.join(lignes)}"
        f'<nav aria-label="Pages d’extraits">{" · ".join(navigation)}</nav>'
    )


def _media(request: Request) -> tuple[str, str | None]:
    message = Message()
    message["content-type"] = request.headers.get("content-type", "")
    return message.get_content_type(), message.get_param("boundary", header="content-type")


async def _corps_borne(request: Request, maximum: int) -> bytes:
    annonce = request.headers.get("content-length")
    if annonce is not None:
        if not annonce.isascii() or not annonce.isdecimal() or len(annonce) > 10:
            raise HTTPException(400, "taille de requête invalide")
        if int(annonce) > maximum:
            raise HTTPException(413, "requête trop volumineuse")
    parties: list[bytes] = []
    taille = 0
    async for morceau in request.stream():
        taille += len(morceau)
        if taille > maximum:
            raise HTTPException(413, "requête trop volumineuse")
        parties.append(morceau)
    return b"".join(parties)


async def _multipart_pdf(request: Request) -> tuple[dict[str, str], bytes]:
    media, boundary = _media(request)
    if media != "multipart/form-data" or not isinstance(boundary, str) or not 1 <= len(boundary) <= 70:
        raise HTTPException(415, "multipart PDF requis")
    contenu = await _corps_borne(request, _BODY_MAX)
    recu = False

    async def recevoir():
        nonlocal recu
        if recu:
            return {"type": "http.disconnect"}
        recu = True
        return {"type": "http.request", "body": contenu, "more_body": False}

    clone = StarletteRequest(request.scope, receive=recevoir)
    formulaire = None
    try:
        formulaire = await clone.form(max_files=1, max_fields=2, max_part_size=16_384)
        elements = formulaire.multi_items()
        noms = [nom for nom, _ in elements]
        if len(noms) != len(set(noms)):
            raise HTTPException(400, "champs PDF dupliqués")
        valeurs = dict(elements)
        if set(valeurs) != {"csrf", "mutation_id", "pdf_file"}:
            raise HTTPException(400, "champs PDF invalides")
        csrf, mutation = valeurs["csrf"], valeurs["mutation_id"]
        fichier = valeurs["pdf_file"]
        if not isinstance(csrf, str) or not isinstance(mutation, str) or not _MUTATION.fullmatch(mutation):
            raise HTTPException(400, "champs PDF invalides")
        if not isinstance(fichier, UploadFile):
            raise HTTPException(400, "fichier PDF absent")
        nom = fichier.filename or ""
        if not nom or len(nom) > 160 or any(c in nom for c in ("/", "\\", "\x00")) or not nom.lower().endswith(".pdf"):
            raise HTTPException(400, "nom ou format PDF invalide")
        message_type = Message()
        message_type["content-type"] = fichier.content_type or ""
        type_fichier = message_type.get_content_type().lower()
        if type_fichier not in {"application/pdf", "application/octet-stream"}:
            raise HTTPException(415, "type de fichier PDF invalide")
        if fichier.headers.get("content-transfer-encoding") is not None:
            raise HTTPException(400, "encodage de fichier inattendu")
        octets = await fichier.read(_SOURCE_MAX + 1)
        if len(octets) > _SOURCE_MAX:
            raise HTTPException(413, "fichier PDF supérieur à 1 Mio")
        if not octets.startswith(b"%PDF-"):
            raise HTTPException(400, "signature PDF invalide")
        return {"csrf": csrf, "mutation_id": mutation}, octets
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "formulaire PDF invalide") from exc
    finally:
        if formulaire is not None:
            await formulaire.close()


async def _formulaire_action(request: Request) -> dict[str, str]:
    media, _ = _media(request)
    if media != "application/x-www-form-urlencoded":
        raise HTTPException(415, "formulaire urlencoded requis")
    contenu = await _corps_borne(request, _ACTION_MAX)
    recu = False

    async def recevoir():
        nonlocal recu
        if recu:
            return {"type": "http.disconnect"}
        recu = True
        return {"type": "http.request", "body": contenu, "more_body": False}

    clone = StarletteRequest(request.scope, receive=recevoir)
    formulaire = None
    try:
        formulaire = await clone.form(max_files=0, max_fields=2, max_part_size=_ACTION_MAX)
        elements = formulaire.multi_items()
        if len({nom for nom, _ in elements}) != len(elements):
            raise HTTPException(400, "champs dupliqués")
        champs = dict(elements)
        if set(champs) != {"csrf", "revision_attendue"}:
            raise HTTPException(400, "champs de préparation invalides")
        if any(not isinstance(v, str) for v in champs.values()):
            raise HTTPException(400, "champs de préparation invalides")
        return champs
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "formulaire de préparation invalide") from exc
    finally:
        if formulaire is not None:
            await formulaire.close()


def creer_router(
    *,
    session_page: Callable[..., Session],
    prefixe: str,
    cnx_factory: Callable[..., Any],
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
            raise HTTPException(exc.statut_http, {"code": exc.code, "detail": exc.detail}) from exc
        except PermissionError as exc:
            raise HTTPException(403, {"code": "ACCES_PDF_REFUSE", "detail": "accès PDF Finance refusé"}) from exc

    async def appeler_bloquant(action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await run_in_threadpool(appeler, action, *args, **kwargs)

    def code_erreur(erreur: HTTPException) -> str:
        detail = erreur.detail
        if isinstance(detail, Mapping) and isinstance(detail.get("code"), str):
            return detail["code"]
        return "REQUETE_REFUSEE"

    def page_erreur(request: Request, initiale: Session, erreur: HTTPException) -> HTMLResponse:
        session = session_vivante(request, initiale.utilisateur)
        code = pages.e(code_erreur(erreur))
        contenu = (
            f'<section class="carte"><h1>Action PDF refusée</h1><p role="alert">Code : {code}</p>'
            f'<p><a href="{pages.e(prefixe)}/fusion/pdf">Retour aux lots</a></p></section>'
        )
        return _reponse(prefixe, session, contenu, erreur.status_code)

    def sans_query(request: Request) -> None:
        if request.query_params:
            raise HTTPException(400, "paramètres invalides")

    @router.get("/fusion", response_class=HTMLResponse)
    def page_fusion(request: Request) -> HTMLResponse:
        session = session_vivante(request)
        if request.query_params:
            raise HTTPException(400, "paramètres invalides")
        contenu = (
            '<section class="carte pile"><h1>Fusion opérationnelle — sources et imports</h1>'
            f'<p><a href="{pages.e(prefixe)}/fusion-operationnelle/synthese">'
            'Consulter la synthèse des sources et des imports</a></p>'
            f'<p><a href="{pages.e(prefixe)}/fusion-operationnelle">Ouvrir les lots CSV</a></p>'
            f'<p><a href="{pages.e(prefixe)}/fusion/pdf">Ouvrir le pilote PDF préparatoire</a></p>'
            f'<p><a href="{pages.e(prefixe)}/memoire/procedures/imports">Mes imports M03</a></p></section>'
        )
        session_vivante(request, session.utilisateur)
        return _reponse(prefixe, session, contenu)

    @router.get("/fusion/pdf", response_class=HTMLResponse)
    async def page_pdf(request: Request) -> HTMLResponse:
        session = session_vivante(request)
        if request.query_params:
            raise HTTPException(400, "paramètres invalides")
        try:
            lots = await appeler_bloquant(fusion_pdf.lister, cnx_factory, session.utilisateur, limite=16)
        except HTTPException as exc:
            return page_erreur(request, session, exc)
        session = session_vivante(request, session.utilisateur)
        return _reponse(prefixe, session, _liste(prefixe, session, lots))

    @router.post("/fusion/pdf/lots")
    async def admettre(request: Request) -> Response:
        session = session_vivante(request)
        sans_query(request)
        fields, source = await _multipart_pdf(request)
        if not securite.csrf_valide(fields["csrf"], session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        session_vivante(request, session.utilisateur)
        try:
            lot = await appeler_bloquant(
                fusion_pdf.creer,
                cnx_factory,
                session.utilisateur,
                mutation_id=fields["mutation_id"],
                pdf_octets=source,
            )
        except HTTPException as exc:
            session = session_vivante(request, session.utilisateur)
            code = pages.e(code_erreur(exc))
            message = f"Admission refusée ou à reprendre ({code}). Réessayez avec le même fichier."
            try:
                lots = await appeler_bloquant(fusion_pdf.lister, cnx_factory, session.utilisateur, limite=16)
                session = session_vivante(request, session.utilisateur)
            except HTTPException:
                session = session_vivante(request, session.utilisateur)
                lots = []
            return _reponse(
                prefixe,
                session,
                _liste(prefixe, session, lots, message, mutation_id=fields["mutation_id"]),
                exc.status_code,
            )
        session = session_vivante(request, session.utilisateur)
        return _privee(RedirectResponse(f"{prefixe}/fusion/pdf/lots/{lot['lot_id']}", status_code=303))

    @router.get("/fusion/pdf/lots/{lot_id}", response_class=HTMLResponse)
    async def detail(lot_id: str, request: Request) -> HTMLResponse:
        session = session_vivante(request)
        if request.query_params:
            raise HTTPException(400, "paramètres invalides")
        if not _UUID.fullmatch(lot_id):
            raise HTTPException(400, "identifiant de lot invalide")
        try:
            lecture = await appeler_bloquant(fusion_pdf.lire_avec_provenance, cnx_factory, session.utilisateur, lot_id)
            if (
                not isinstance(lecture, Mapping) or set(lecture) != {"lot", "provenance"}
                or not isinstance(lecture["lot"], Mapping) or lecture["lot"].get("lot_id") != lot_id
                or lecture["lot"].get("classe") != "FINANCIAL" or lecture["lot"].get("type_source") != "pdf_natif"
                or type(lecture["lot"].get("revision")) is not int or lecture["lot"]["revision"] < 1
                or not isinstance(lecture["lot"].get("statut"), str) or lecture["lot"]["statut"] not in _STATUTS
            ):
                raise HTTPException(503, {"code": "PDF_PROVENANCE_INDISPONIBLE"})
            lot = lecture["lot"]
            provenance = appeler(_provenance, lot, lecture["provenance"])
            session = session_vivante(request, session.utilisateur)
            reponse = _reponse(prefixe, session, _detail(prefixe, session, lot) + provenance)
        except HTTPException as exc:
            return page_erreur(request, session, exc)
        session_vivante(request, session.utilisateur)
        return reponse

    @router.post("/fusion/pdf/lots/{lot_id}/preparer")
    async def preparer(lot_id: str, request: Request) -> Response:
        session = session_vivante(request)
        sans_query(request)
        if not _UUID.fullmatch(lot_id):
            raise HTTPException(400, "identifiant de lot invalide")
        champs = await _formulaire_action(request)
        if not securite.csrf_valide(champs["csrf"], session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        revision_brute = champs["revision_attendue"]
        if not revision_brute.isascii() or not re.fullmatch(r"[1-9][0-9]{0,9}", revision_brute):
            raise HTTPException(400, "révision invalide")
        revision = int(revision_brute)
        session_vivante(request, session.utilisateur)
        try:
            await appeler_bloquant(
                fusion_pdf.preparer,
                cnx_factory,
                session.utilisateur,
                lot_id,
                revision,
            )
        except HTTPException as exc:
            session = session_vivante(request, session.utilisateur)
            try:
                courant = await appeler_bloquant(fusion_pdf.lire, cnx_factory, session.utilisateur, lot_id)
                session = session_vivante(request, session.utilisateur)
            except HTTPException:
                session = session_vivante(request, session.utilisateur)
                contenu = (
                    f'<p role="alert">La préparation n’a pas abouti ({pages.e(code_erreur(exc))}). '
                    "Rechargez la liste avant de réessayer.</p>"
                    f'<p><a href="{pages.e(prefixe)}/fusion/pdf">Retour aux lots</a></p>'
                )
                return _reponse(prefixe, session, contenu, exc.status_code)
            message = (
                "Le lot a changé (CONFLIT_REVISION); rechargez sa révision."
                if code_erreur(exc) == "CONFLIT_REVISION"
                else (
                    f"La préparation n’a pas abouti ({pages.e(code_erreur(exc))}). Le worker peut avoir terminé "
                    "malgré la déconnexion."
                )
            )
            return _reponse(prefixe, session, _detail(prefixe, session, courant, message), exc.status_code)
        session = session_vivante(request, session.utilisateur)
        return _privee(RedirectResponse(f"{prefixe}/fusion/pdf/lots/{lot_id}", status_code=303))

    @router.get("/fusion/pdf/lots/{lot_id}/extraits", response_class=HTMLResponse)
    async def extraits(lot_id: str, request: Request) -> HTMLResponse:
        session = session_vivante(request)
        params = request.query_params
        valeurs = params.getlist("page")
        if set(params) != {"page"} or len(valeurs) != 1 or not _UUID.fullmatch(lot_id):
            raise HTTPException(400, "paramètres d’extrait invalides")
        raw_page = valeurs[0]
        if not raw_page.isascii() or not re.fullmatch(r"[1-9][0-9]?\Z", raw_page):
            raise HTTPException(400, "page d’extrait invalide")
        try:
            resultat = await appeler_bloquant(fusion_pdf.lire_resultat, cnx_factory, session.utilisateur, lot_id)
        except HTTPException as exc:
            return page_erreur(request, session, exc)
        session = session_vivante(request, session.utilisateur)
        corps = _extraits(prefixe, session, lot_id, resultat, int(raw_page))
        return _reponse(prefixe, session, corps)

    return router
