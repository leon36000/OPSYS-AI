"""Rangement administratif manuel d’une pièce originale, avec historique courant distinct."""
import re
import uuid
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from . import classement_pieces as classement
from . import pages, securite
from . import pieces_projet_ui as transport


def _base(prefixe, piece):
    return transport._base(prefixe, piece['lead_id']) + '/' + piece['piece_id'] + '/classement'


def _parametres(request):
    q = request.query_params
    if set(q) - {'decalage', 'revision_max'} or any(len(q.getlist(k)) != 1 for k in q):
        raise HTTPException(400, 'Pagination du classement invalide')
    resultat = dict(decalage=0, revision_max=None)
    for k in q:
        valeur = q[k]
        if re.fullmatch('0|[1-9][0-9]?', valeur) is None or int(valeur) > classement.MAX_REVISIONS:
            raise HTTPException(400, 'Pagination du classement invalide')
        resultat[k] = int(valeur)
    if (resultat['decalage'] % classement.PAGE or
            (resultat['decalage'] and resultat['revision_max'] is None)):
        raise HTTPException(400, 'Pagination du classement invalide')
    return resultat


def contenu(vue, csrf, prefixe):
    piece = vue['piece']
    base = _base(prefixe, piece)
    courant = classement.CATEGORIES[vue['categorie_courante']]
    corps = (f'<p><a href="{pages.e(transport._base(prefixe, piece["lead_id"]))}">Retour aux pièces du projet</a></p>'
        f'<h2>{pages.e(piece["titre"])}</h2><h3>Classement courant : {pages.e(courant)}</h3>'
        f'<p>Révision {vue["revision_courante"]} · Projet : {pages.e(piece["lead_id"])}</p>'
        '<p>Rangement administratif manuel. L’original reste inchangé. '
        'Ce classement ne valide ni le document ni un engagement.</p>'
        f'<h3>Historique jusqu’à la révision {vue["revision_max"]}</h3><ol>')
    for r in vue['historique']:
        corps += (f'<li>Révision {r["revision"]} : {pages.e(classement.CATEGORIES[r["avant"]])} → '
            f'{pages.e(classement.CATEGORIES[r["categorie"]])} · {pages.e(classement.MOTIFS[r["motif"]])}<br>'
            f'{pages.e(r["horodatage"])} · {pages.e(r["auteur"])}</li>')
    corps += '</ol>'
    if not vue['historique']:
        corps += '<p>Aucun classement enregistré dans cette plage de révisions.</p>'
    for offset, label in ((vue['decalage'] - classement.PAGE, 'Page précédente'), (vue['suivant'], 'Page suivante')):
        if offset is not None and offset >= 0:
            corps += (f'<p><a href="{pages.e(base)}?decalage={offset}&amp;revision_max={vue["revision_max"]}">'
                      f'{label}</a></p>')
    corps += (f'<h3>Classer cette pièce</h3><form method="post" action="{pages.e(base)}">'
        f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">'
        f'<input type="hidden" name="mutation_id" value="{uuid.uuid4().hex}">'
        f'<input type="hidden" name="revision_attendue" value="{vue["revision_courante"]}">'
        '<label>Catégorie <select name="categorie" required>')
    for code, label in classement.CATEGORIES.items():
        selected = ' selected' if code == vue['categorie_courante'] else ''
        corps += f'<option value="{code}"{selected}>{pages.e(label)}</option>'
    corps += '</select></label><label>Motif <select name="motif" required><option value="">Choisir le motif</option>'
    for code, label in classement.MOTIFS.items():
        corps += f'<option value="{code}">{pages.e(label)}</option>'
    return corps + '</select></label><button type="submit">Enregistrer le classement</button></form>'


async def _formulaire(request):
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Formulaire de classement requis')
    corps = await transport._corps_borne(request, 4096)
    try:
        valeurs = parse_qs(corps.decode('utf-8', errors='strict'), keep_blank_values=True,
                           strict_parsing=True, max_num_fields=6, errors='strict')
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'Formulaire de classement invalide') from None
    if (set(valeurs) != {'csrf', 'mutation_id', 'revision_attendue', 'categorie', 'motif'}
            or any(len(v) != 1 for v in valeurs.values())):
        raise HTTPException(400, 'Champs de classement invalides')
    champs = {k: v[0] for k, v in valeurs.items()}
    valeur = champs['revision_attendue']
    if re.fullmatch('0|[1-9][0-9]?', valeur) is None or int(valeur) > classement.MAX_REVISIONS:
        raise HTTPException(400, 'Révision de classement invalide')
    champs['revision_attendue'] = int(valeur)
    return champs


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre):
    router = APIRouter()
    chemin = '/crm/lead/{lead_id}/pieces-recues/{piece_id}/classement'

    def afficher(cnx, session, lead, piece, cle, params, recu=None):
        ancre = classement.pieces._ancre(cnx, deps, session, lead)
        vue = classement.lire(cnx, deps, session, lead, piece, cle=cle, **params)
        debut = '' if recu is None else (
            f'<h2>Reçu historique — révision {recu["revision"]}</h2>'
            '<p>Aucun nouveau classement enregistré. Le classement courant est affiché ci-dessous.</p>')
        reponse = rendre(session, 'Classement de la pièce', debut + contenu(vue, session.csrf, prefixe))
        if len(reponse.body) > transport.MAX_HTML:
            raise classement.Refus('SORTIE-TROP-VOLUMINEUSE')
        classement.pieces._fermer(cnx, deps, session, lead, ancre)
        if transport._cle() != cle or classement.lire(cnx, deps, session, lead, piece, cle=cle, **params) != vue:
            raise classement.Refus('SOURCE-MODIFIEE')
        classement.pieces.autorite._admin(cnx, session)
        return reponse

    @router.get(chemin)
    def page(lead_id: str, piece_id: str, request: Request):
        session = session_page(request)
        params = _parametres(request)
        with transport._erreurs(), cnx_factory() as cnx:
            classement.pieces.autorite._admin(cnx, session)
            return afficher(cnx, session, lead_id, piece_id, transport._cle(), params)

    @router.post(chemin)
    async def enregistrer(lead_id: str, piece_id: str, request: Request):
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres de classement invalides')
        with transport._erreurs(), cnx_factory() as cnx:
            classement.pieces.autorite._admin(cnx, session)
        champs = await _formulaire(request)
        if not securite.csrf_valide(champs.pop('csrf'), session):
            raise HTTPException(403, 'Jeton CSRF invalide')
        def classer():
            with transport._erreurs(), cnx_factory() as cnx:
                classement.pieces.autorite._admin(cnx, session)
                cle = transport._cle()
                ancre = classement.pieces._ancre(cnx, deps, session, lead_id)
                resultat = classement.classer(cnx, deps, session, lead_id, piece_id, cle=cle, **champs)
                if resultat['rejoue']:
                    return afficher(cnx, session, lead_id, piece_id, cle, {}, resultat['recu'])
                vue_classee = classement.lire(cnx, deps, session, lead_id, piece_id, cle=cle)
                reponse = RedirectResponse(
                    _base(prefixe, dict(lead_id=lead_id, piece_id=piece_id)), status_code=303,
                    headers={'Cache-Control': 'no-store'})
                classement.pieces._fermer(cnx, deps, session, lead_id, ancre)
                if (transport._cle() != cle or
                        classement.lire(cnx, deps, session, lead_id, piece_id, cle=cle) != vue_classee):
                    raise classement.Refus('SOURCE-MODIFIEE')
                classement.pieces.autorite._admin(cnx, session)
                return reponse
        return await run_in_threadpool(classer)

    return router
