"""Créer un brouillon depuis une version M3 explicite; aucun envoi externe."""
import base64
import uuid
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from . import lignes_catalogue_ui, metier, pages, prefill_ui
from . import modeles_soumission_ui as modeles

CHAMPS_LIGNE = ('description', 'quantite', 'unite', 'cout_unitaire', 'reference_besoin_materiau')
CHAMPS = {'csrf', 'mutation_id', 'devis_id', 'chantier_id', 'taux_marge',
          'modele_id', 'modele_revision', 'modele_source'}
CHAMPS |= {f'{k}_{i}' for k in CHAMPS_LIGNE for i in range(20)}


async def extraire_formulaire(request):
    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Formulaire requis')
    corps = bytearray()
    async for bloc in request.stream():
        corps.extend(bloc)
        if len(corps) > 131072:
            raise HTTPException(413, 'Formulaire trop volumineux')
    try:
        p = parse_qs(corps.decode('utf-8'), keep_blank_values=True, strict_parsing=True,
                     max_num_fields=len(CHAMPS), errors='strict')
        if set(p) != CHAMPS or any(len(v) != 1 for v in p.values()):
            raise ValueError('champs')
        return {k: v[0] for k, v in p.items()}
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'Formulaire invalide') from None


def formulaire(session, base, m):
    valeurs = {'csrf': session.csrf, 'mutation_id': str(uuid.uuid4()), 'devis_id': str(uuid.uuid4()),
               'modele_id': m['modele_id'], 'modele_revision': m['revision'], 'modele_source': m['source_id']}
    corps = (f'<h2>{pages.e(m["titre"])} — version {m["revision"]}</h2>'
             '<p>Cette version et ses textes seront conservés dans le nouveau brouillon. '
             'Les révisions futures du catalogue ne le modifieront pas.</p>'
             f'<pre>\n{pages.e(m["description"])}</pre><pre>\n{pages.e(m["clauses"])}</pre>'
             '<p>Saisir les quantités et coûts connus. M3 calcule les prix; taxes en sus. '
             'Quantités/coûts : 9 chiffres entiers et 6 décimales maximum; majoration inférieure à 10000. '
             'Aucun envoi ni acceptation. Les lignes ne sont pas encore préremplies par le modèle.</p>'
             f'<form method="post" action="{pages.e(base)}" class="pile">')
    corps += ''.join(f'<input type="hidden" name="{k}" value="{pages.e(v)}">' for k, v in valeurs.items())
    corps += ('<label>Référence chantier (facultative)<input name="chantier_id" maxlength="100"></label>'
              '<label>Taux de majoration sur coût (décimal, 0.35 = 35 %)<input name="taux_marge" '
              'maxlength="24" required></label>')
    for i in range(20):
        corps += f'<fieldset><legend>Ligne {i+1}' + (' (facultative)' if i else '') + '</legend>'
        for k, label, maximum in [('description', 'Travaux ou matériau', 500), ('quantite', 'Quantité', 24),
                                 ('unite', 'Unité', 40), ('cout_unitaire', 'Coût unitaire CAD', 24),
                                 ('reference_besoin_materiau', 'Référence besoin matériau (facultative)', 100)]:
            requis = ' required' if i == 0 and k != 'reference_besoin_materiau' else ''
            corps += f'<label>{label}<input name="{k}_{i}" maxlength="{maximum}"{requis}></label>'
        corps += '</fieldset>'
    return corps + '<button type="submit">Créer le brouillon</button></form>'


def creer_router(*, session_page, cnx_factory, deps, prefixe, verifier_formulaire, verifier_lead, rendre):
    router = APIRouter()
    route = '/crm/lead/{lead_id}/nouvelle-soumission'

    def appeler(session, nom, args, mutation=None):
        try:
            with cnx_factory() as cnx:
                return modeles.extraire(metier.executer(cnx, deps, session, nom, args, mutation_id=mutation))
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except KeyError:
            raise HTTPException(503, 'M3 indisponible') from None
        except ValueError:
            raise HTTPException(400, 'Saisie invalide') from None

    @router.get(route)
    def nouveau(lead_id: str, request: Request):
        session = session_page(request)
        verifier_lead(session, lead_id)
        with cnx_factory() as cnx:
            if cnx.dialect.name != 'sqlite':
                raise HTTPException(503, 'Création non qualifiée sur cette instance')
        base = prefixe + '/crm/lead/' + pages._segment(lead_id) + '/nouvelle-soumission'
        p = request.query_params
        if any(len(p.getlist(k)) != 1 for k in p):
            raise HTTPException(400, 'Paramètres dupliqués')
        if 'modele_id' in p:
            if set(p) != {'modele_id', 'version', 'source'} or modeles.entier(p['version']) < 1:
                raise HTTPException(400, 'Version exacte requise')
            m = appeler(session, 'm3_lire_modele_soumission',
                        {'modele_id': p['modele_id'], 'version': modeles.entier(p['version'])})
            if m['source_id'] != p['source']:
                raise HTTPException(409, 'Source du modèle différente; reprendre la sélection')
            query = urlencode({'modele_id': m['modele_id'], 'modele_revision': m['revision'],
                               'modele_source': m['source_id']})
            lien = prefixe + '/crm/lead/' + pages._segment(lead_id) + '/soumission-preremplie?' + query
            edition = prefixe + '/crm/modeles-soumission/' + pages._segment(m['modele_id']) + '/lignes?' + query
            liens = (f'<p><a href="{pages.e(lien)}">Utiliser les lignes et tarifs M6</a> · '
                     f'<a href="{pages.e(edition)}">Configurer les lignes du modèle</a></p>')
            return rendre(session, 'Nouvelle soumission', liens + formulaire(session, base, m))
        if set(p) - {'decalage', 'source_attendue'}:
            raise HTTPException(400, 'Paramètres invalides')
        r = appeler(session, 'm3_lister_modeles_soumission',
                    {'decalage': modeles.entier(p.get('decalage', '0')),
                     'source_attendue': p.get('source_attendue', '')})
        corps = '<h2>Choisir un modèle pour ce projet</h2><ul>'
        for m in r['modeles']:
            lien = base + '?' + urlencode({'modele_id': m['modele_id'], 'version': m['revision'],
                                           'source': m['source_id']})
            corps += f'<li><a href="{pages.e(lien)}">{pages.e(m["titre"])} — version {m["revision"]}</a></li>'
        corps += '</ul>' if r['modeles'] else '</ul><p>Aucun modèle enregistré.</p>'
        for offset, label in [(r['decalage'] - 25, 'Page précédente'), (r['decalage_suivant'], 'Page suivante')]:
            if offset is not None and offset >= 0:
                lien = base + '?' + urlencode({'decalage': offset, 'source_attendue': r['source_empreinte']})
                corps += f'<p><a href="{pages.e(lien)}">{label}</a></p>'
        corps += f'<p><a href="{pages.e(prefixe)}/crm/modeles-soumission">Gérer les modèles</a></p>'
        return rendre(session, 'Choisir un modèle', corps)

    @router.post(route)
    async def creer(lead_id: str, request: Request):
        session = session_page(request)
        verifier_lead(session, lead_id)
        if request.query_params:
            raise HTTPException(400, 'Paramètres invalides')
        p = await extraire_formulaire(request)
        verifier_formulaire(p, session)
        lignes = []
        for i in range(20):
            ligne = {k: p[f'{k}_{i}'] for k in CHAMPS_LIGNE}
            if any(ligne.values()):
                ligne['reference_besoin_materiau'] = ligne['reference_besoin_materiau'] or None
                lignes.append(ligne)
        r = appeler(session, 'm3_creer_devis_depuis_modele', {
            'devis_id': p['devis_id'], 'lead_id': lead_id, 'chantier_id': p['chantier_id'] or None,
            'lignes': lignes, 'taux_marge': p['taux_marge'], 'modele_id': p['modele_id'],
            'modele_revision': modeles.entier(p['modele_revision']), 'modele_source': p['modele_source']},
            p['mutation_id'])
        lien = prefixe + '/crm/lead/' + pages._segment(lead_id) + '/soumissions/' + pages._segment(r['devis_id'])
        return RedirectResponse(lien, 303)

    @router.get('/crm/lead/{lead_id}/soumissions/{devis_id}/document/{format}')
    def document(lead_id: str, devis_id: str, format: str, request: Request):
        session = session_page(request)
        verifier_lead(session, lead_id)
        if request.query_params or format not in {'html', 'pdf'}:
            raise HTTPException(400, 'Format invalide')
        r = appeler(session, 'm3_document_devis_console', {'lead_id': lead_id, 'devis_id': devis_id, 'format': format})
        corps = r['document'].encode() if format == 'html' else base64.b64decode(r['contenu_base64'], validate=True)
        return Response(corps, media_type='text/html' if format == 'html' else 'application/pdf', headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "sandbox; default-src 'none'",
            'Content-Disposition': f'attachment; filename="soumission-brouillon.{format}"'})

    router.include_router(lignes_catalogue_ui.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe,
        verifier_formulaire=verifier_formulaire, rendre=rendre, appeler=appeler))
    router.include_router(prefill_ui.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, prefixe=prefixe, verifier_formulaire=verifier_formulaire,
        verifier_lead=verifier_lead, rendre=rendre, appeler=appeler))
    return router
