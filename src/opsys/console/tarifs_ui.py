"""Formulaires admin de saisie d'un tarif M6, avec comparaison puis confirmation."""
import re
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import catalogue_materiaux_ui as catalogue
from . import fournisseurs_ui, pages, prefill_ui

CHAMPS = {'csrf', 'mutation_id', 'materiau_id', 'fournisseur_id', 'prix_unitaire', 'date_effet', 'source_document'}
CONFIRMER = CHAMPS | {'materiau_source', 'fournisseur_source', 'tarif_rang', 'tarif_empreinte'}


def creer_router(*, session_page, cnx_factory, deps, prefixe, verifier_formulaire, rendre):
    router = APIRouter()
    route = catalogue.BASE + '/{materiau_id}/tarifs'

    def agir(session, nom, args, mutation=None):
        return catalogue.appeler(cnx_factory, deps, session, nom, args, mutation)

    def arguments(p, materiau_id):
        if p['materiau_id'] != materiau_id:
            raise HTTPException(400, 'Matériau incohérent')
        return dict(materiau_id=materiau_id, fournisseur_id=p['fournisseur_id'], prix_unitaire=p['prix_unitaire'],
                    date_effet=p['date_effet'], source_document=p['source_document'] or None)

    @router.get(route)
    def nouveau(materiau_id: str, request: Request):
        session = session_page(request)
        p = request.query_params
        if set(p) - {'debut'} or any(len(p.getlist(k)) != 1 for k in p):
            raise HTTPException(400, 'Paramètres invalides')
        with cnx_factory():
            materiau = agir(session, 'm6_lire_materiau_console', dict(materiau_id=materiau_id, revision=0))
            if not materiau['actif']:
                raise HTTPException(409, 'Réactiver la fiche matériau avant de saisir un nouveau tarif')
            debut = catalogue.entier(p.get('debut', '0'))
            liste = agir(session, 'm6_lister_fournisseurs_tarif_console', dict(debut=debut, limite=25))
        base = prefixe + catalogue.BASE + '/' + pages._segment(materiau_id) + '/tarifs'
        corps = (f'<h2>Nouveau tarif — {pages.e(materiau["nom"])}</h2>'
                 f'<p>Unité : {pages.e(materiau["unite"])} · devise : CAD.</p>'
                 '<p>Saisir le prix fourni par le fournisseur et sa date effective. Une référence documentaire '
                 'est déclarative; sans référence, le prix reste marqué FALLBACK_PRICE_BOOK.</p>')
        corps += (f'<p><a href="{pages.e(prefixe + fournisseurs_ui.BASE)}">Créer ou corriger un fournisseur</a></p>')
        for offset, label in [(max(0, debut - 25) if debut else None, 'Fournisseurs précédents'),
                              (liste['suivant'], 'Fournisseurs suivants')]:
            if offset is not None:
                corps += f'<p><a href="{pages.e(base + "?" + urlencode(dict(debut=offset)))}">{label}</a></p>'
        if not liste['fournisseurs']:
            return rendre(session, 'Tarifs fournisseurs', corps + '<p>Aucun fournisseur sur cette page. '
                          'Une fiche fournisseur connue est nécessaire avant la saisie.</p>')
        corps += (f'<form method="post" action="{pages.e(base)}/preparer" class="pile">'
                  + prefill_ui.caches(dict(csrf=session.csrf, mutation_id=str(uuid.uuid4()), materiau_id=materiau_id))
                  + '<label>Fournisseur<select name="fournisseur_id" required>'
                  '<option value="">Choisir un fournisseur</option>')
        for f in liste['fournisseurs']:
            corps += f'<option value="{pages.e(f["fournisseur_id"])}">{pages.e(f["nom"])}</option>'
        corps += ('</select></label><label>Prix unitaire CAD (ex. 12.50)'
                  '<input name="prix_unitaire" maxlength="16" required></label>'
                  '<label>Date effective du tarif<input name="date_effet" type="date" required></label>'
                  '<label>Référence du document source (facultative)'
                  '<input name="source_document" maxlength="1000"></label>'
                  '<button>Vérifier le tarif</button></form>')
        return rendre(session, 'Tarifs fournisseurs', corps)

    @router.post(route + '/preparer')
    async def preparer(materiau_id: str, request: Request):
        session = session_page(request)
        p = await prefill_ui.extraire(request, CHAMPS)
        verifier_formulaire(p, session)
        r = agir(session, 'm6_preparer_tarif_console', arguments(p, materiau_id))
        corps = (f'<h2>Confirmer le tarif — {pages.e(r["materiau_nom"])}</h2>'
                 f'<p>Fournisseur : {pages.e(r["fournisseur_nom"])} · unité : {pages.e(r["unite"])}.</p>'
                 f'<p>Nouveau prix : <strong>{pages.e(r["prix_unitaire_decimal"])}</strong> CAD '
                 f'· date effective : {pages.e(r["date_effet"])}.</p>'
                 f'<p>{pages.e(r["marquage_source"])} · {pages.e(r["source_document"] or "Sans document source")}</p>')
        if r['ancien_tarif'] is not None:
            ancien = r['ancien_tarif']
            corps += (f'<p>Prix actuellement utilisable : {pages.e(ancien["cout_unitaire_decimal"])} CAD '
                      f'· date : {pages.e(ancien["date_effet"])}.</p>')
        elif r['ancien_indisponible']:
            corps += '<p role="alert">Le dernier tarif enregistré est inutilisable pour cette unité/date/source.</p>'
        else:
            corps += '<p>Premier tarif pour ce matériau et ce fournisseur.</p>'
        valeurs = dict(p)
        valeurs.update({k: r[k] for k in ('materiau_source', 'fournisseur_source', 'tarif_rang', 'tarif_empreinte')})
        base = prefixe + catalogue.BASE + '/' + pages._segment(materiau_id) + '/tarifs'
        corps += (f'<form method="post" action="{pages.e(base)}/confirmer">' + prefill_ui.caches(valeurs)
                  + '<p>Confirmer ajoute une version au livre de prix. Aucun achat ni envoi fournisseur.</p>'
                  '<button>Confirmer ce tarif</button></form>')
        return rendre(session, 'Confirmer le tarif', corps)

    @router.post(route + '/confirmer')
    async def confirmer(materiau_id: str, request: Request):
        session = session_page(request)
        p = await prefill_ui.extraire(request, CONFIRMER)
        verifier_formulaire(p, session)
        if re.fullmatch(r'-?[0-9]{1,5}', p['tarif_rang']) is None:
            raise HTTPException(400, 'Rang du tarif invalide')
        args = dict(arguments(p, materiau_id), **{k: p[k] for k in
                    ('materiau_source', 'fournisseur_source', 'tarif_empreinte')}, tarif_rang=int(p['tarif_rang']))
        agir(session, 'm6_confirmer_tarif_console', args, p['mutation_id'])
        return RedirectResponse(prefixe + catalogue.BASE + '/' + pages._segment(materiau_id), 303)

    from . import historique_tarifs_ui, import_tarifs_ui

    router.include_router(historique_tarifs_ui.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe, rendre=rendre))
    router.include_router(import_tarifs_ui.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe,
        verifier_formulaire=verifier_formulaire, rendre=rendre))
    return router
