"""Formulaire privé de pièces reçues par projet; aucun aperçu ou traitement du document."""
import base64
import os
import re
import uuid
from contextlib import contextmanager
from email.message import Message
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.requests import Request as StarletteRequest

from . import classement_pieces as classement
from . import pages, pieces_projet, securite
from .fusion_pdf_ui import _corps_borne, _media

ENV_CLE = 'OPSYS_PIECES_PROJET_CLE'
MAX_HTML = 131072


def _cle():
    valeur = os.environ.get(ENV_CLE, '')
    try:
        if len(valeur) != 44:
            raise ValueError('format')
        cle = base64.b64decode(valeur, validate=True)
        if len(cle) != 32 or base64.b64encode(cle).decode('ascii') != valeur:
            raise ValueError('format')
    except (ValueError, UnicodeError):
        raise pieces_projet.Refus('CLE-INDISPONIBLE') from None
    return cle


@contextmanager
def _erreurs():
    try:
        yield
    except PermissionError:
        raise HTTPException(403, 'Accès admin actif requis') from None
    except pieces_projet.Refus as exc:
        if exc.code == 'CLE-INDISPONIBLE':
            raise HTTPException(
                503, 'Le stockage sécurisé des pièces doit être configuré par l’administrateur.') from None
        statut = {'INTROUVABLE': 404, 'SAISIE-CONFLIT': 409, 'TITRE-INVALIDE': 400,
                  'TAILLE-INVALIDE': 400, 'TYPE-INVALIDE': 400, 'SAISIE-INVALIDE': 400,
                  'PAGINATION-INVALIDE': 400, 'CLASSEMENT-ARGUMENTS': 400,
                  'REVISION-PERIMEE': 409, 'CLASSEMENT-INCHANGE': 409, 'LISTE-PERIMEE': 409}.get(exc.code, 503)
        raise HTTPException(statut, 'Pièces reçues indisponibles : ' + exc.code) from None
    except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError, SQLAlchemyError):
        raise HTTPException(503, 'Pièces reçues temporairement indisponibles') from None


def _base(prefixe, lead):
    return f'{prefixe}/crm/lead/{pages._segment(lead)}/pieces-recues'


def _parametres(request, *, page=False):
    q = request.query_params
    if not page:
        if q:
            raise HTTPException(400, 'Paramètres de pièces reçues invalides')
        return {}
    valeur = q.get('decalage', '0')
    categorie = q.get('categorie') or None
    source = q.get('source_attendue', '')
    if (set(q) - {'decalage', 'categorie', 'source_attendue'}
            or any(len(q.getlist(k)) != 1 for k in q)
            or re.fullmatch(r'0|[1-9][0-9]{0,2}', valeur) is None
            or int(valeur) >= pieces_projet.MAX_PIECES or int(valeur) % pieces_projet.PAGE
            or (categorie is not None and categorie not in classement.CATEGORIES)
            or (source and re.fullmatch('[0-9a-f]{64}', source) is None)
            or (int(valeur) and not source)):
        raise HTTPException(400, 'Paramètres de pièces reçues invalides')
    return dict(decalage=int(valeur), categorie=categorie, source_attendue=source)


def _url_filtre(base, categorie):
    return base + ('?' + urlencode({'categorie': categorie}) if categorie is not None else '')


def contenu(vue, csrf, prefixe):
    base = _base(prefixe, vue['lead_id'])
    corps = (f'<p><a href="{prefixe}/crm/lead/{pages._segment(vue["lead_id"])}">Retour au dossier</a></p>'
             '<h2>Pièces reçues de ce projet</h2>'
             f'<p>Projet : {pages.e(vue["lead_id"])} · {vue["nombre"]} pièce(s) correspondent sur '
             f'{vue["nombre_total"]} dans ce projet.</p>'
             '<p>Originaux conservés sans analyse du contenu ni validation de signature. '
             'Téléchargement uniquement. Aucun usage marketing automatique.</p>')
    corps += (f'<form method="get" action="{pages.e(base)}">'
              '<label>Classement <select name="categorie">')
    for code, label in [('', 'Toutes les catégories'), *classement.CATEGORIES.items()]:
        selection = ' selected' if code == (vue['categorie'] or '') else ''
        corps += f'<option value="{code}"{selection}>{pages.e(label)}</option>'
    corps += '</select></label><button type="submit">Filtrer les pièces</button></form><ul>'
    for piece in vue['pieces']:
        lien = base + '/' + piece['piece_id']
        type_court = {'application/pdf': 'PDF', 'image/png': 'PNG', 'image/jpeg': 'JPEG'}[piece['type_mime']]
        corps += (f'<li><strong>{pages.e(piece["titre"])}</strong> · {type_court} · '
                  f'{piece["taille_octets"]} octets · {pages.e(piece["statut"])}<br>'
                  f'Reçu le {pages.e(piece["recu_le"])} par {pages.e(piece["auteur"])}<br>'
                  f'SHA-256 : {pages.e(piece["source_sha256"])}<br>'
                  f'Classement : {pages.e(classement.CATEGORIES[piece["categorie_courante"]])} · '
                  f'révision {piece["revision_classement"]}<br>'
                  f'<a href="{pages.e(lien)}">Télécharger l’original {type_court}</a> · '
                  f'<a href="{pages.e(lien)}/classement">Classement et historique</a></li>')
    corps += '</ul>'
    if not vue['pieces']:
        corps += '<p>Aucune pièce reçue ne correspond à ce classement dans ce projet.</p>'
    for offset, libelle in ((vue['decalage'] - pieces_projet.PAGE, 'Page précédente'),
                            (vue['suivant'], 'Page suivante')):
        if offset is not None and offset >= 0:
            parametres = dict(decalage=offset, source_attendue=vue['source_calculee'])
            if vue['categorie'] is not None:
                parametres['categorie'] = vue['categorie']
            lien = base + '?' + urlencode(parametres)
            corps += f'<p><a href="{pages.e(lien)}">{libelle}</a></p>'
    corps += (f'<p><a href="{pages.e(_url_filtre(base, vue["categorie"]))}">'
              'Actualiser les résultats</a></p>')
    return corps + (f'<h3>Ajouter un original reçu</h3><form method="post" enctype="multipart/form-data" '
        f'action="{pages.e(base)}"><input type="hidden" name="csrf" value="{pages.e(csrf)}">'
        f'<input type="hidden" name="mutation_id" value="{uuid.uuid4().hex}">'
        '<label>Titre de la pièce <input name="titre" maxlength="160" required></label>'
        '<label>Photo ou PDF reçu <input type="file" name="piece" '
        'accept="image/jpeg,image/png,application/pdf" required></label>'
        '<p>1 Mio maximum. Aucun aperçu ni contrôle antivirus dans ce parcours.</p>'
        '<button type="submit">Conserver dans ce projet</button></form>')


async def _multipart(request):
    media, boundary = _media(request)
    if media != 'multipart/form-data' or not isinstance(boundary, str) or not 1 <= len(boundary) <= 70:
        raise HTTPException(415, 'Formulaire de pièce requis')
    corps = await _corps_borne(request, pieces_projet.MAX_ORIGINAL + 65536)
    recu = False
    async def recevoir():
        nonlocal recu
        if recu:
            return {'type': 'http.disconnect'}
        recu = True
        return {'type': 'http.request', 'body': corps, 'more_body': False}
    formulaire = None
    try:
        formulaire = await StarletteRequest(request.scope, receive=recevoir).form(
            max_files=1, max_fields=3, max_part_size=16384)
        elements = formulaire.multi_items()
        valeurs = dict(elements)
        if len(elements) != len(valeurs) or set(valeurs) != {'csrf', 'mutation_id', 'titre', 'piece'}:
            raise HTTPException(400, 'Champs de pièce invalides')
        if any(type(valeurs[k]) is not str for k in ('csrf', 'mutation_id', 'titre')):
            raise HTTPException(400, 'Champs de pièce invalides')
        fichier = valeurs['piece']
        if not isinstance(fichier, UploadFile) or fichier.headers.get('content-transfer-encoding') is not None:
            raise HTTPException(400, 'Pièce absente ou encodage invalide')
        message = Message()
        message['content-type'] = fichier.content_type or ''
        mime = message.get_content_type().lower()
        source = await fichier.read(pieces_projet.MAX_ORIGINAL + 1)
        if len(source) > pieces_projet.MAX_ORIGINAL:
            raise HTTPException(413, 'Pièce supérieure à 1 Mio')
        if mime not in {'application/pdf', 'image/png', 'image/jpeg'}:
            raise HTTPException(415, 'Type de pièce invalide')
        return {k: valeurs[k] for k in ('csrf', 'mutation_id', 'titre')}, mime, source
    except HTTPException:
        raise
    except (ValueError, TypeError, RuntimeError):
        raise HTTPException(400, 'Formulaire de pièce invalide') from None
    finally:
        if formulaire is not None:
            await formulaire.close()


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre):
    router = APIRouter()
    chemin = '/crm/lead/{lead_id}/pieces-recues'

    @router.get(chemin)
    def page(lead_id: str, request: Request):
        session = session_page(request)
        params = _parametres(request, page=True)
        with _erreurs(), cnx_factory() as cnx:
            pieces_projet.autorite._admin(cnx, session)
            cle = _cle()
            ancre = pieces_projet._ancre(cnx, deps, session, lead_id)
            try:
                vue = classement.lister_projet(cnx, deps, session, lead_id, cle=cle, **params)
            except pieces_projet.Refus as exc:
                if exc.code != 'LISTE-PERIMEE':
                    raise
                lien = _url_filtre(_base(prefixe, lead_id), params['categorie'])
                reponse = rendre(session, 'Liste à actualiser',
                    '<p>La liste a changé depuis cette consultation. Actualiser pour lire les résultats courants.</p>'
                    f'<p><a href="{pages.e(lien)}">Actualiser les résultats</a></p>')
                reponse.status_code = 409
                pieces_projet._fermer(cnx, deps, session, lead_id, ancre)
                if _cle() != cle:
                    raise pieces_projet.Refus('SOURCE-MODIFIEE') from None
                pieces_projet.autorite._admin(cnx, session)
                return reponse
            reponse = rendre(session, 'Pièces reçues du projet', contenu(vue, session.csrf, prefixe))
            if len(reponse.body) > MAX_HTML:
                raise pieces_projet.Refus('SORTIE-TROP-VOLUMINEUSE')
            pieces_projet._fermer(cnx, deps, session, lead_id, ancre)
            if _cle() != cle or classement.lister_projet(
                    cnx, deps, session, lead_id, cle=cle, **params) != vue:
                raise pieces_projet.Refus('SOURCE-MODIFIEE')
            pieces_projet.autorite._admin(cnx, session)
            reponse.headers['X-Content-Type-Options'] = 'nosniff'
        return reponse

    @router.get(chemin + '/{piece_id}')
    def original(lead_id: str, piece_id: str, request: Request):
        session = session_page(request)
        _parametres(request)
        with _erreurs(), cnx_factory() as cnx:
            pieces_projet.autorite._admin(cnx, session)
            cle = _cle()
            ancre = pieces_projet._ancre(cnx, deps, session, lead_id)
            meta, source = pieces_projet.lire(cnx, deps, session, lead_id, piece_id, cle=cle)
            extension = {'application/pdf': 'pdf', 'image/png': 'png', 'image/jpeg': 'jpg'}[meta['type_mime']]
            reponse = Response(source, media_type='application/octet-stream', headers={
                'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'; sandbox",
                'Content-Disposition': f'attachment; filename="piece-projet.{extension}"'})
            pieces_projet._fermer(cnx, deps, session, lead_id, ancre)
            if _cle() != cle or pieces_projet.lire(cnx, deps, session, lead_id, piece_id, cle=cle) != (meta, source):
                raise pieces_projet.Refus('SOURCE-MODIFIEE')
            pieces_projet.autorite._admin(cnx, session)
        return reponse

    @router.post(chemin)
    async def depot(lead_id: str, request: Request):
        session = session_page(request)
        _parametres(request)
        with _erreurs(), cnx_factory() as cnx:
            pieces_projet.autorite._admin(cnx, session)
        champs, mime, source = await _multipart(request)
        if not securite.csrf_valide(champs['csrf'], session):
            raise HTTPException(403, 'Jeton CSRF invalide')
        def conserver():
            with _erreurs(), cnx_factory() as cnx:
                pieces_projet.autorite._admin(cnx, session)
                cle = _cle()
                ancre = pieces_projet._ancre(cnx, deps, session, lead_id)
                pieces_projet.deposer(cnx, deps, session, lead_id, mutation_id=champs['mutation_id'],
                    titre=champs['titre'], type_mime=mime, contenu=source, cle=cle)
                reponse = RedirectResponse(_base(prefixe, lead_id), status_code=303,
                                           headers={'Cache-Control': 'no-store'})
                pieces_projet._fermer(cnx, deps, session, lead_id, ancre)
                if _cle() != cle:
                    raise pieces_projet.Refus('SOURCE-MODIFIEE')
                pieces_projet.autorite._admin(cnx, session)
            return reponse
        return await run_in_threadpool(conserver)

    return router
