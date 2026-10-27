"""Catalogue textuel M3 versionné, réservé au secrétariat admin."""
import re
import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import identite
from . import metier, pages

IDENTIFIANT = re.compile(r'[A-Za-z0-9_.:@-]{1,100}')
CHAMPS = {'modele_id', 'titre', 'description', 'clauses', 'revision_attendue', 'csrf', 'mutation_id'}
BASE = '/crm/modeles-soumission'


def extraire(reponse):
    r = reponse.get('resultat') if isinstance(reponse, dict) and reponse.get('ok') is True else None
    if not isinstance(r, dict):
        raise HTTPException(503, 'Catalogue temporairement indisponible')
    if r.get('accepte') is True and isinstance(r.get('resultat'), dict):
        return r['resultat']
    code = r.get('verdict', {}).get('code', '').removeprefix('REJ-MODELE-')
    codes = {'IDENTITE': 403, 'ARGUMENTS': 400, 'HORODATAGE-INVALIDE': 400, 'INTROUVABLE': 404,
             'REVISION-PERIMEE': 409, 'MUTATION-CONFLIT': 409, 'SOURCE-MODIFIEE': 409}
    messages = {'REVISION-PERIMEE': 'Le modèle a changé : relire avant de modifier.',
                'MUTATION-CONFLIT': 'Cette intention a déjà servi à une autre saisie.',
                'SOURCE-MODIFIEE': 'Le catalogue a changé : recommencer la lecture.',
                'ARGUMENTS': 'Saisie invalide : vérifier textes et version.',
                'INTROUVABLE': 'Modèle ou version introuvable.'}
    raise HTTPException(codes.get(code, 503), messages.get(code, 'Catalogue indisponible ou accès refusé'))


def entier(brut):
    if re.fullmatch(r'[0-9]{1,4}', brut) is None or int(brut) > 1000:
        raise HTTPException(400, 'Version ou pagination invalide')
    return int(brut)


def formulaire(session, prefixe, modele=None):
    m = modele or {'modele_id': str(uuid.uuid4()), 'revision': 0, 'titre': '', 'description': '', 'clauses': ''}
    champs = (f'<form method="post" action="{pages.e(prefixe + BASE)}/enregistrer" class="pile">'
              f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
              f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
              f'<input type="hidden" name="modele_id" value="{pages.e(m["modele_id"])}">'
              f'<input type="hidden" name="revision_attendue" value="{m["revision"]}">'
              '<label>Nom du modèle<input name="titre" maxlength="120" required '
              f'value="{pages.e(m["titre"])}"></label>')
    for k, label, limite in [('description', 'Description des travaux', 4000), ('clauses', 'Clauses et notes', 12000)]:
        obligatoire = ' required' if k == 'description' else ''
        champs += (f'<label>{label}<textarea name="{k}" maxlength="{limite}" rows="8"{obligatoire}>'
                   f'\n{pages.e(m[k])}</textarea></label>')
    return champs + '<button type="submit">Enregistrer une nouvelle version</button></form>'


async def champs(request):
    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Formulaire requis')
    corps = bytearray()
    async for bloc in request.stream():
        corps.extend(bloc)
        if len(corps) > 200000:
            raise HTTPException(413, 'Formulaire trop volumineux')
    try:
        p = parse_qs(corps.decode('utf-8'), keep_blank_values=True, strict_parsing=True,
                     max_num_fields=7, errors='strict')
        if set(p) != CHAMPS or any(len(v) != 1 for v in p.values()):
            raise ValueError('champs')
        return {k: v[0] for k, v in p.items()}
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'Formulaire invalide') from None


def creer_router(*, session_page, cnx_factory, deps, prefixe, verifier_formulaire, rendre):
    router = APIRouter()
    base = prefixe + BASE

    def admin(request):
        session = session_page(request)
        with cnx_factory() as cnx:
            personne = identite.personne_active(cnx, session.utilisateur)
            if (personne is None or 'admin' not in personne.roles
                    or session.expire <= datetime.now(UTC).timestamp()):
                raise HTTPException(403, 'Accès admin requis')
        return session

    def agir(session, nom, args, mutation=None):
        try:
            with cnx_factory() as cnx:
                return extraire(metier.executer(cnx, deps, session, nom, args, mutation_id=mutation))
        except PermissionError:
            raise HTTPException(403, 'Accès refusé') from None
        except KeyError:
            raise HTTPException(503, 'Catalogue indisponible') from None
        except ValueError:
            raise HTTPException(400, 'Saisie invalide') from None

    def ecriture():
        with cnx_factory() as cnx:
            return cnx.dialect.name == 'sqlite'

    def conflit(session, message):
        r = rendre(session, 'Modèles à relire', f'<p role="alert">{pages.e(message)}</p>'
                   f'<a href="{pages.e(base)}">Recommencer au catalogue</a>')
        r.status_code = 409
        return r

    @router.get(BASE)
    def catalogue(request: Request):
        session = admin(request)
        p = request.query_params
        if set(p) - {'decalage', 'source_attendue'} or any(len(p.getlist(k)) != 1 for k in p):
            raise HTTPException(400, 'Paramètres invalides')
        offset, source = entier(p.get('decalage', '0')), p.get('source_attendue', '')
        try:
            resultat = agir(session, 'm3_lister_modeles_soumission', {'decalage': offset, 'source_attendue': source})
        except HTTPException as exc:
            if exc.status_code == 409:
                return conflit(session, exc.detail)
            raise
        corps = ('<section class="carte"><h2>Modèles de soumission</h2>'
                 '<p>Textes versionnés : sélection depuis les soumissions du projet pour créer un brouillon HTML/PDF. '
                 'Enregistrer ici ne modifie aucune soumission existante.</p>')
        if resultat['modeles']:
            corps += '<ul>'
            for m in resultat['modeles']:
                lien = base + '/' + pages._segment(m['modele_id'])
                corps += (f'<li><a href="{pages.e(lien)}">{pages.e(m["titre"])}</a>'
                          f' · version {m["revision"]}</li>')
            corps += '</ul>'
        else:
            corps += '<p>Aucun modèle enregistré.</p>'
        corps += f'<p>{resultat["total"]} modèle(s), 25 par page.</p>'
        for offset, label in [(resultat['decalage'] - 25, 'Page précédente'),
                              (resultat['decalage_suivant'], 'Page suivante')]:
            if offset is not None and offset >= 0:
                lien = base + '?' + urlencode({'decalage': offset, 'source_attendue': resultat['source_empreinte']})
                corps += f'<p><a href="{pages.e(lien)}">{label}</a></p>'
        corps += '</section>'
        if ecriture():
            corps += '<section class="carte"><h2>Nouveau modèle</h2>' + formulaire(session, prefixe) + '</section>'
        return rendre(session, 'Modèles de soumission', corps)

    @router.post(BASE + '/enregistrer')
    async def enregistrer(request: Request):
        session = admin(request)
        valeurs = await champs(request)
        verifier_formulaire(valeurs, session)
        args = {k: valeurs[k] for k in ('modele_id', 'titre', 'description', 'clauses')}
        args['revision_attendue'] = entier(valeurs['revision_attendue'])
        try:
            r = agir(session, 'm3_enregistrer_modele_soumission', args, valeurs['mutation_id'])
        except HTTPException as exc:
            if exc.status_code == 409:
                return conflit(session, exc.detail)
            raise
        return RedirectResponse(base + '/' + pages._segment(r['modele_id']) + '?version=' + str(r['revision']), 303)

    @router.get(BASE + '/{modele_id}')
    def modele(modele_id: str, request: Request):
        session = admin(request)
        if IDENTIFIANT.fullmatch(modele_id) is None:
            raise HTTPException(404, 'Modèle introuvable')
        p = request.query_params
        if set(p) - {'version'} or any(len(p.getlist(k)) != 1 for k in p):
            raise HTTPException(400, 'Paramètres invalides')
        m = agir(session, 'm3_lire_modele_soumission',
                 {'modele_id': modele_id, 'version': entier(p.get('version', '0'))})
        corps = (f'<p><a href="{pages.e(base)}">Retour au catalogue</a></p>'
                 f'<section class="carte"><h2>{pages.e(m["titre"])}</h2><p>Version {m["revision"]}'
                 f' sur {m["revision_courante"]} · source M3 : {pages.e(m["source_id"])}</p>'
                 f'<p>Auteur : {pages.e(m["auteur"]["personne"])} · {pages.e(m["horodatage"])}</p>'
                 f'<h3>Description des travaux</h3><pre>\n{pages.e(m["description"])}</pre>'
                 f'<h3>Clauses et notes</h3><pre>\n{pages.e(m["clauses"])}</pre></section>')
        for version, label in [(m['revision'] - 1, 'Version précédente'), (m['revision'] + 1, 'Version suivante')]:
            if 1 <= version <= m['revision_courante']:
                lien = base + '/' + pages._segment(modele_id) + '?version=' + str(version)
                corps += f'<p><a href="{pages.e(lien)}">{label}</a></p>'
        if m['revision'] == m['revision_courante'] and ecriture():
            corps += ('<section class="carte"><h2>Réviser ce modèle</h2>'
                      + formulaire(session, prefixe, m) + '</section>')
        lien_lignes = base + '/' + pages._segment(modele_id) + '/lignes?' + urlencode({
            'modele_id': modele_id, 'modele_revision': m['revision'], 'modele_source': m['source_id']})
        corps += f'<p><a href="{pages.e(lien_lignes)}">Configurer les lignes réutilisables</a></p>'
        return rendre(session, 'Version du modèle', corps)

    return router
