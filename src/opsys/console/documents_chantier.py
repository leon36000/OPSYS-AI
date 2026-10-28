"""Consultation admin du devis et des photos WCT exactes; aucun dépôt ni rattachement inventé."""
import hashlib
import json
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.exc import SQLAlchemyError

from .. import contexte, fichiers
from ..stockage import codec
from ..stockage.maillons import copier_maillons_avec_metadonnees
from . import memoire_chantier as autorite
from . import pages
from . import preparation_chantier as lecture

CATALOGUE = ((lecture.M2, 'principal'), (lecture.M3, 'devis'),
             (lecture.M3, 'principal'), (lecture.M4, 'principal'))
MAX_PHOTOS = 20
MAX_HTML = 131072


def _canonique(valeur):
    """Codec natif typé : Decimal/texte et bool/entier distincts, nombres non finis refusés."""
    return json.dumps(json.loads(codec.encoder(valeur)), sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)


def _capture(cnx):
    # Les quatre bornes avant le premier décodage; rang, texte SQL et date SQL font partie de la preuve.
    for dep, nom in CATALOGUE:
        lecture._borner(cnx, dep, nom)
    return {(dep, nom): copier_maillons_avec_metadonnees(cnx, departement=dep, registre=nom)
            for dep, nom in CATALOGUE}


def lire(cnx, deps, session, lead_id, devis_id):
    """Aucune référence n'est autorisée sans son triplet canonique et sa publication M4."""
    from m4_field_ops import outbox, registre

    autorite._admin(cnx, session)
    captures = _capture(cnx)
    ancre = lecture.lire(cnx, deps, session, lead_id, devis_id)
    chaine = registre.Registre([m.maillon for m in captures[(lecture.M4, 'principal')].lignes])
    try:
        chaine.assert_chaine()
    except registre.VerificationError:
        raise lecture.Refus('SOURCE-INCOHERENTE') from None
    valide, _ = outbox.verifier_invariants_outbox(chaine)
    if not valide:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    intervention = ancre['intervention']
    candidats = []
    if intervention is not None:
        candidats = [(i, w) for i, w in outbox.lire_outbox(chaine)
                     if w.get('intervention_id') == intervention['intervention_id'] or w.get('devis_id') == devis_id]
    if len(candidats) > 1:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    wct, maillon = None, None
    if candidats:
        index, wct = candidats[0]
        if (not ancre['ancre_complete'] or wct.get('lead_id') != lead_id or wct.get('devis_id') != devis_id
                or wct.get('intervention_id') != intervention['intervention_id']):
            raise lecture.Refus('SOURCE-INCOHERENTE')
        maillon = chaine.lire()[index]['ligne_id']
        publication = lecture._publication(cnx, wct['wct_id'], 'm4.travaux_termines', lecture.M4)
        if _canonique(publication) != _canonique(wct):
            raise lecture.Refus('SOURCE-INCOHERENTE')
    references = [] if wct is None else wct.get('photos', [])
    if (type(references) is not list or len(references) > MAX_PHOTOS
            or any(type(ref) is not str or len(ref) > 256 for ref in references)):
        raise lecture.Refus('PHOTOS-TROP-VOLUMINEUSES')
    sources = {dep + '/' + nom: capture.empreinte_snapshot_calculee
               for (dep, nom), capture in captures.items()}
    preuve = dict(sources=sources, ancre=ancre, wct=wct)
    vue = dict(lead_id=lead_id, devis_id=devis_id,
               intervention_id=None if intervention is None else intervention['intervention_id'],
               statut=None if intervention is None else intervention['statut'],
               wct_id=None if wct is None else wct['wct_id'], maillon=maillon,
               photos=[dict(position=i + 1, sha256=fichiers.empreinte_depuis_reference(ref))
                       for i, ref in enumerate(references)],
               source_calculee=hashlib.sha256(_canonique(preuve).encode('utf-8')).hexdigest())
    autorite._admin(cnx, session)
    if {dep + '/' + nom: s.empreinte_snapshot_calculee for (dep, nom), s in _capture(cnx).items()} != sources:
        raise lecture.Refus('SOURCE-MODIFIEE')
    return lecture._sortie(vue)


def _fermer(cnx, deps, session, vue):
    actuelle = lire(cnx, deps, session, vue['lead_id'], vue['devis_id'])
    if actuelle != vue:
        raise lecture.Refus('SOURCE-MODIFIEE')
    autorite._admin(cnx, session)


def _base(vue, prefixe):
    return (f'{prefixe}/crm/lead/{pages._segment(vue["lead_id"])}/soumissions/'
            f'{pages._segment(vue["devis_id"])}')


def contenu(vue, prefixe):
    base = _base(vue, prefixe)
    corps = (f'<p><a href="{pages.e(base)}">Retour à la soumission</a></p>'
             '<h2>Photos et fichiers du chantier</h2>'
             f'<p>Projet : {pages.e(vue["lead_id"])} · Devis : {pages.e(vue["devis_id"])}</p>'
             '<h3>Documents de la soumission</h3>'
             '<p>Documents M3 générés à la demande depuis le devis courant; aucun original signé archivé ici.</p>'
             f'<p><a href="{pages.e(base)}/document/pdf">Consulter le PDF M3</a> · '
             f'<a href="{pages.e(base)}/document/html">Consulter le document HTML M3</a></p>'
             '<h3>Photos déclarées à la fin des travaux</h3>')
    if vue['wct_id'] is None:
        corps += '<p>Aucune fin de travaux publiée avec des photos pour ce chantier.</p>'
    else:
        corps += (f'<p>Statut actuel du chantier : {pages.e(vue["statut"])}</p>'
                  '<p>Les photos ne valent pas validation des travaux. Chaque ouverture revérifie le fichier.</p>')
        if not vue['photos']:
            corps += '<p>Aucune photo déclarée à la fin des travaux.</p>'
        else:
            corps += '<ul>'
            for photo in vue['photos']:
                sha = photo['sha256']
                corps += '<li>Photo ' + str(photo['position']) + ' : '
                corps += (f'<a href="{pages.e(base)}/fichiers/photos/{sha}">Consulter la photo</a>'
                          if sha is not None else 'Référence non consultable') + '</li>'
            corps += '</ul>'
        corps += (f'<details><summary>Source de rattachement</summary><p>Fin de travaux M4 : {pages.e(vue["wct_id"])}'
                  f' · Maillon M4 : {pages.e(vue["maillon"])}</p></details>')
    corps += ('<p>Les preuves de complétion historiques (photos après, notes et signature) sont non conservées '
              'dans ce rattachement. Aucun fichier manquant n’est reconstitué. '
              'Dépôt libre, classement et pièces jointes PDF reçues restent à raccorder.</p>'
              f'<p>Consulté le {pages.e(datetime.now(UTC).isoformat(timespec="seconds"))} · '
              f'Empreinte des sources : {pages.e(vue["source_calculee"])}</p>')
    return corps


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre):
    router = APIRouter()
    chemin = '/crm/lead/{lead_id}/soumissions/{devis_id}/fichiers'

    def consulter(request, lead_id, devis_id, sha=None):
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres de consultation invalides')
        try:
            with cnx_factory() as cnx:
                vue = lire(cnx, deps, session, lead_id, devis_id)
                if sha is None:
                    reponse = rendre(session, 'Photos et fichiers du chantier', contenu(vue, prefixe))
                    if len(reponse.body) > MAX_HTML:
                        raise lecture.Refus('SORTIE-TROP-VOLUMINEUSE')
                else:
                    if not fichiers.empreinte_valide(sha) or sha not in {p['sha256'] for p in vue['photos']}:
                        raise lecture.Refus('INTROUVABLE')
                    blob = fichiers.lire_blob_verifie(cnx, fichiers.reference_pour(sha))
                    if not blob.accepte:
                        raise lecture.Refus('FICHIER-INDISPONIBLE')
                    quota = contexte.limite_sortie()
                    if quota is not None and len(blob.octets) > quota:
                        raise lecture.Refus('SORTIE-TROP-VOLUMINEUSE')
                    extension = 'png' if blob.type_mime == 'image/png' else 'jpg'
                    reponse = Response(blob.octets, media_type=blob.type_mime, headers={
                        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                        'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'; sandbox",
                        'Content-Disposition': f'inline; filename="photo-chantier.{extension}"',
                    })
                _fermer(cnx, deps, session, vue)
                # Le lecteur CAS est sans cache : une modification durant le rendu/refus ferme la sortie.
                if sha is not None and fichiers.lire_blob_verifie(cnx, fichiers.reference_pour(sha)) != blob:
                    raise lecture.Refus('SOURCE-MODIFIEE')
                autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except lecture.Refus as exc:
            statut = {'INTROUVABLE': 404, 'DEVIS-NON-ACCEPTE': 409}.get(exc.code, 503)
            raise HTTPException(statut, 'Documents indisponibles : ' + exc.code) from None
        except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError, SQLAlchemyError):
            raise HTTPException(503, 'Sources documentaires indisponibles') from None
        return reponse

    @router.get(chemin)
    def page(lead_id: str, devis_id: str, request: Request):
        return consulter(request, lead_id, devis_id)

    @router.get(chemin + '/photos/{sha}')
    def photo(lead_id: str, devis_id: str, sha: str, request: Request):
        return consulter(request, lead_id, devis_id, sha)

    return router
