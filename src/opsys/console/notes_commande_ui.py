"""Notes d'achat privées du secrétariat, adossées à M3/M6, sans effet fournisseur."""
from __future__ import annotations

import base64
import binascii
import re
import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import contexte, idempotence, identite, notes_commande_affaire, notes_commande_memoire
from . import metier, pages

IDENTIFIANT = re.compile(r'[\w.:@\-]{1,200}')


def reference(note_id):
    """Les IDs M6 libres restent exacts; l'URL n'est pas un nouveau contrat métier."""
    if IDENTIFIANT.fullmatch(note_id) and note_id not in {".", ".."}:
        return note_id
    return '~'+base64.urlsafe_b64encode(note_id.encode('utf-8')).decode('ascii').rstrip('=')


def identifier(ref):
    if IDENTIFIANT.fullmatch(ref) and ref not in {".", ".."}:
        return ref
    if not re.fullmatch(r'~[A-Za-z0-9_-]{1,1067}', ref):
        raise HTTPException(404, 'Note introuvable')
    try:
        raw = ref[1:]
        ident = base64.urlsafe_b64decode(raw+'='*(-len(raw) % 4)).decode('utf-8')
        if not ident.strip() or len(ident) > 200 or reference(ident) != ref:
            raise ValueError('référence non canonique')
        return ident
    except (ValueError, UnicodeError, binascii.Error):
        raise HTTPException(404, 'Note introuvable') from None


def entier(brut, maximum):
    if not isinstance(brut, str) or not re.fullmatch(r'0|[1-9][0-9]{0,6}', brut) or int(brut) > maximum:
        raise HTTPException(400, 'Révision ou pagination invalide')
    return int(brut)


async def formulaire(request, reference_memoire=False):
    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Formulaire requis')
    corps = bytearray()
    async for bloc in request.stream():
        corps.extend(bloc)
        # 20 000 caractères Unicode, au plus 12 octets encodés chacun, plus métadonnées.
        if len(corps) > (4096 if reference_memoire else 260000):
            raise HTTPException(413, 'Formulaire trop volumineux')
    try:
        champs = parse_qs(corps.decode('utf-8'), keep_blank_values=True, max_num_fields=5,
                          strict_parsing=True, errors='strict')
        if any(len(v) != 1 for v in champs.values()):
            raise ValueError('doublon')
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'Formulaire illisible ou dupliqué') from None
    attendus = ({'csrf', 'revision', 'source_hash'} if reference_memoire else
                {'csrf', 'note_id', 'revision_attendue', 'mutation_id', 'texte_libre'})
    if set(champs) != attendus:
        raise HTTPException(400, 'Champs invalides')
    return {k: v[0] for k, v in champs.items()}


def extraire(reponse):
    if not isinstance(reponse, dict) or reponse.get('ok') is not True:
        raise HTTPException(503, 'Notes temporairement indisponibles')
    res = reponse.get('resultat')
    if not isinstance(res, dict):
        raise HTTPException(503, 'Notes temporairement indisponibles')
    if res.get('accepte') is True:
        return res
    code = res.get('verdict', {}).get('code', '')
    suffixe = code.removeprefix('REJ-NOTE-COMMANDE-')
    if suffixe == 'IDENTITE':
        raise HTTPException(403, 'Accès refusé')
    if suffixe == 'INTROUVABLE':
        raise HTTPException(404, 'Note introuvable')
    if suffixe in {'BESOIN-INTROUVABLE', 'CHANTIER-INCONNU'}:
        raise HTTPException(409, 'Le chantier de cette soumission doit être confirmé dans les besoins matériaux.')
    if suffixe in {'REVISION-PERIMEE', 'ANCRAGE-DIFFERENT', 'MUTATION-CONFLIT'}:
        raise HTTPException(409, 'Note non enregistrée : relire la version et son rattachement.')
    if suffixe == 'ARGUMENTS':
        raise HTTPException(400, 'Note invalide : texte non vide, 20 000 caractères maximum.')
    raise HTTPException(503, 'Note indisponible : source ou confirmation à vérifier.')


def edition(url, csrf, note=None):
    note_id = note['note_id'] if note else 'note-'+str(uuid.uuid4())
    revision = note['revision'] if note else 0
    texte = note['texte_libre'] if note else ''
    return (
        f'<form method="post" action="{pages.e(url)}" class="pile">'
        f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">'
        f'<input type="hidden" name="note_id" value="{pages.e(note_id)}">'
        f'<input type="hidden" name="revision_attendue" value="{revision}">'
        f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
        '<label>Matériaux et achats à prévoir<textarea name="texte_libre" rows="12" required>'
        f'\n{pages.e(texte)}</textarea></label>'
        '<p>20 000 caractères maximum. Chaque correction conserve la version précédente.</p>'
        '<button type="submit">Enregistrer la note interne</button></form>')


def creer_router(*, session_page, cnx_factory, deps, prefixe, verifier_formulaire, lire, rendre, verifier_lead):
    router = APIRouter()
    chemin = '/crm/lead/{lead_id}/soumissions/{devis_id}/notes-achats'

    def base(lead_id, devis_id):
        return f'{prefixe}/crm/lead/{pages._segment(lead_id)}/soumissions/{pages._segment(devis_id)}/notes-achats'

    def ancrage(session, lead_id, devis_id):
        verifier_lead(session, lead_id)
        if IDENTIFIANT.fullmatch(devis_id) is None:
            raise HTTPException(404, 'Soumission introuvable')
        devis = lire(session, 'm3_lire_devis', {'devis_id': devis_id})
        if devis.get('lead_id') != lead_id:
            raise HTTPException(404, 'Soumission introuvable')

    def appeler(session, nom, args, mutation=None):
        try:
            with cnx_factory() as cnx:
                if mutation is not None and cnx.dialect.name != 'sqlite':
                    raise HTTPException(503, 'Écriture des notes indisponible sur cette instance')
                return extraire(metier.executer(cnx, deps, session, nom, args, mutation_id=mutation))
        except PermissionError:
            raise HTTPException(403, 'Accès refusé') from None
        except KeyError:
            raise HTTPException(503, 'Notes indisponibles') from None
        except ValueError as exc:
            if isinstance(exc.__cause__, idempotence.MutationConflit):
                raise HTTPException(409, 'Identifiant de saisie déjà utilisé') from None
            raise HTTPException(400, 'Formulaire invalide') from None

    def liste(session, devis_id, decalage=0):
        res = appeler(session, 'm6_lister_notes_commande', {'devis_id': devis_id, 'decalage': decalage, 'limite': 20})
        vue = res.get('resultat')
        if (not isinstance(vue, dict) or vue.get('devis_id') != devis_id or not vue.get('chantier_id')
                or not isinstance(vue.get('notes'), list) or len(vue['notes']) > 20):
            raise HTTPException(503, 'Liste de notes indisponible')
        return vue

    def lire_note(session, note_id, devis_id, chantier_id, revision=None):
        args = {'note_id': note_id}
        if revision is not None:
            args['revision'] = revision
        note = appeler(session, 'm6_lire_note_commande', args).get('note')
        if not isinstance(note, dict) or note.get('note_id') != note_id:
            raise HTTPException(503, 'Note indisponible')
        if note.get('devis_id') != devis_id or note.get('chantier_id') != chantier_id:
            raise HTTPException(404, 'Note introuvable')
        return note

    def rattachement(session, lead_id, devis_id, note):
        with cnx_factory() as cnx:
            personne = identite.personne_active(cnx, session.utilisateur)
            if (personne is None or 'admin' not in personne.roles
                    or session.expire <= datetime.now(UTC).timestamp()):
                raise HTTPException(403, 'Accès refusé')
            with contexte.appele_par_appareil(
                contexte.IdentiteAppelante(personne.identifiant, 'admin', source='console'),
            ):
                resultat = notes_commande_affaire.resoudre(note['note_id'], note['revision'], devis_id, lead_id)
                if resultat['statut'] == 'VERIFIE' and (
                    resultat['source_hash'] != note['source']['hash_maillon'] or
                    resultat['source_index'] != note['source']['index']
                ):
                    raise HTTPException(409, 'Source de la note modifiée : relire la page')
                memoire = (notes_commande_memoire.consulter(
                    note['note_id'], note['revision'], devis_id, lead_id, note['source']['hash_maillon'],
                ) if resultat['statut'] == 'VERIFIE' else None)
        if resultat['statut'] == 'VERIFIE':
            action = base(lead_id, devis_id)+'/'+pages._segment(reference(note['note_id']))+'/reference-memoire'
            bouton = ''
            if memoire['etat'] == 'NON_PUBLIE':
                bouton = (f'<form method="post" action="{pages.e(action)}">'
                          f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                          f'<input type="hidden" name="revision" value="{note["revision"]}">'
                          f'<input type="hidden" name="source_hash" value="{pages.e(resultat["source_hash"])}">'
                          '<button type="submit">Mémoriser la référence de cette révision</button></form>')
            return ('<section aria-label="Rattachement mémoire"><h3>Affaire M10</h3>'
                    '<p>Rattachement vérifié pour cette révision : '
                    f'{pages.e(resultat["affaire_id"])}.</p>'
                    '<p>La note reste privée dans M6 ; elle n’est pas mémorisée dans M10.</p>'
                    f'<p>Référence M10 : {pages.e(memoire["etat"])}.</p>{bouton}</section>')
        return ('<section aria-label="Rattachement mémoire"><h3>Affaire M10</h3>'
                '<p>Rattachement non vérifié. Référence à contrôler : '
                f'{pages.e(resultat["code"])}.</p>'
                '<p>Aucun fait mémoire créé ; les versions de la note sont conservées dans M6.</p></section>')

    def entete(url, chantier):
        return ('<section class="carte"><h2>Notes d’achat internes</h2>'
                f'<p>Chantier : {pages.e(chantier)}</p>'
                '<p>Aucune commande fournisseur, réservation, dépense ni mise à jour de stock '
                'n’est déclenchée par cette note.</p>'
                f'<p><a href="{pages.e(url.rsplit("/notes-achats", 1)[0])}">Retour à la soumission</a></p>')

    @router.get(chemin)
    def index(lead_id: str, devis_id: str, request: Request):
        session = session_page(request)
        if set(request.query_params) - {'decalage'} or len(request.query_params.getlist('decalage')) > 1:
            raise HTTPException(400, 'Pagination invalide')
        decalage = entier(request.query_params.get('decalage', '0'), 10000)
        ancrage(session, lead_id, devis_id)
        vue = liste(session, devis_id, decalage)
        url = base(lead_id, devis_id)
        corps = entete(url, vue['chantier_id'])
        for n in vue['notes']:
            corps += (f'<p><a href="{pages.e(url)}/{pages._segment(reference(n["note_id"]))}">'
                      f'{pages.e(n["note_id"])}</a>'
                      f' — Révision {pages.e(n["revision"])} — {pages.e(n["auteur"]["personne"])}'
                      f' — {pages.e(n["enregistree_le"])}</p>')
        corps += f'<p>{len(vue["notes"])} note(s) affichée(s) sur {pages.e(vue["total"])}.</p>'
        if decalage:
            corps += f'<a href="{pages.e(url)}?decalage={max(0, decalage-20)}">Page précédente</a> '
        if vue['suivant'] is not None:
            corps += f'<a href="{pages.e(url)}?decalage={vue["suivant"]}">Page suivante</a>'
        with cnx_factory() as cnx:
            disponible = cnx.dialect.name == 'sqlite'
        corps += (edition(url, session.csrf) if disponible else '<p>Écriture indisponible sur cette instance.</p>')
        return rendre(session, 'Notes d’achat', corps+'</section>')

    @router.get(chemin+'/{note_id}')
    def detail(lead_id: str, devis_id: str, note_id: str, request: Request):
        session = session_page(request)
        note_id = identifier(note_id)
        if set(request.query_params) - {'revision'} or len(request.query_params.getlist('revision')) > 1:
            raise HTTPException(400, 'Révision invalide')
        revision = entier(request.query_params['revision'], 1000000) if 'revision' in request.query_params else None
        if revision == 0:
            raise HTTPException(400, 'Révision invalide')
        ancrage(session, lead_id, devis_id)
        vue = liste(session, devis_id)
        courant = lire_note(session, note_id, devis_id, vue['chantier_id'])
        note = lire_note(session, note_id, devis_id, vue['chantier_id'], revision) if revision else courant
        url = base(lead_id, devis_id)
        lien = url+'/'+pages._segment(reference(note_id))
        corps = (entete(url, vue['chantier_id']) + f'<p><a href="{pages.e(url)}">Toutes les notes</a></p>'
                 f'<h3>Révision {note["revision"]}</h3><p>{pages.e(note["auteur"]["personne"])}'
                 f' — {pages.e(note["enregistree_le"])}</p><pre>{pages.e(note["texte_libre"])}</pre>'
                 f'<details><summary>Provenance M6</summary><p>{pages.e(note["source"]["hash_maillon"])}</p></details>')
        corps += rattachement(session, lead_id, devis_id, note)
        if note['revision'] > 1:
            corps += f'<a href="{pages.e(lien)}?revision={note["revision"]-1}">Révision précédente</a> '
        if note['revision'] < courant['revision']:
            corps += f'<a href="{pages.e(lien)}?revision={note["revision"]+1}">Révision suivante</a> '
        corps += f'<a href="{pages.e(lien)}">Version courante</a>'
        with cnx_factory() as cnx:
            disponible = cnx.dialect.name == 'sqlite'
        if revision is None and disponible:
            corps += edition(lien, session.csrf, note)
        return rendre(session, 'Historique de la note', corps+'</section>')

    async def enregistrer(lead_id, devis_id, request, note_id=None):
        session = session_page(request)
        if note_id is not None:
            note_id = identifier(note_id)
        if request.query_params:
            raise HTTPException(400, 'Paramètres interdits')
        champs = await formulaire(request)
        verifier_formulaire(champs, session)
        ident = champs['note_id']
        revision = entier(champs['revision_attendue'], 999999)
        if (not ident.strip() or len(ident) > 200 or (note_id is not None and ident != note_id)
                or (note_id is None and revision != 0) or (note_id is not None and revision == 0)
                or not champs['mutation_id'].strip() or len(champs['mutation_id']) > 200
                or not champs['texte_libre'].strip() or len(champs['texte_libre']) > 20000):
            raise HTTPException(400, 'Note ou intention invalide')
        ancrage(session, lead_id, devis_id)
        vue = liste(session, devis_id)
        if note_id is not None:
            lire_note(session, note_id, devis_id, vue['chantier_id'])
        appeler(session, 'm6_enregistrer_note_commande', {
            'note_id': ident, 'devis_id': devis_id, 'texte_libre': champs['texte_libre'],
            'revision_attendue': revision}, champs['mutation_id'])
        return RedirectResponse(base(lead_id, devis_id)+'/'+pages._segment(reference(ident)), status_code=303)

    @router.post(chemin)
    async def creation(lead_id: str, devis_id: str, request: Request):
        return await enregistrer(lead_id, devis_id, request)

    @router.post(chemin+'/{note_id}')
    async def correction(lead_id: str, devis_id: str, note_id: str, request: Request):
        return await enregistrer(lead_id, devis_id, request, note_id)

    @router.post(chemin+'/{note_id}/reference-memoire')
    async def memoriser_reference(lead_id: str, devis_id: str, note_id: str, request: Request):
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres interdits')
        ident = identifier(note_id)
        champs = await formulaire(request, reference_memoire=True)
        verifier_formulaire(champs, session)
        revision = entier(champs['revision'], 1000000)
        if revision == 0 or re.fullmatch(r'[0-9a-f]{64}', champs['source_hash']) is None:
            raise HTTPException(400, 'Référence invalide')
        # Revalidation dans la transaction d'écriture ; aucune autorité issue de l'URL/formulaire.
        try:
            with cnx_factory() as cnx:
                personne = identite.personne_active(cnx, session.utilisateur)
                if (personne is None or 'admin' not in personne.roles
                        or session.expire <= datetime.now(UTC).timestamp()):
                    raise HTTPException(403, 'Accès refusé')
                with contexte.appele_par_appareil(
                    contexte.IdentiteAppelante(personne.identifiant, 'admin', source='console'),
                ):
                    notes_commande_memoire.publier(ident, revision, devis_id, lead_id, champs['source_hash'])
        except notes_commande_memoire.ReferenceRefusee:
            raise HTTPException(409, 'Référence non vérifiée ou contradictoire ; relire ses sources') from None
        return RedirectResponse(base(lead_id, devis_id)+'/'+pages._segment(reference(ident))+
                                f'?revision={revision}', status_code=303)

    return router
