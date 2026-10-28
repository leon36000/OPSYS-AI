"""Fiches fournisseurs humaines, privées, sans commande ni envoi de courriel."""
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import catalogue_materiaux_ui as catalogue
from . import pages, prefill_ui

BASE = '/crm/fournisseurs'
CHAMPS = {'fournisseur_id', 'nom', 'courriel_commande', 'telephone', 'source_attendue', 'csrf', 'mutation_id',
          'nom_action', 'courriel_commande_action', 'telephone_action'}


def formulaire(session, prefixe, fiche=None):
    f = fiche or dict(fournisseur_id=str(uuid.uuid4()), nom='', courriel_commande=None,
                      telephone=None, source_empreinte='')
    corps = (f'<form method="post" action="{pages.e(prefixe + BASE)}/enregistrer" class="pile">'
             + prefill_ui.caches(dict(fournisseur_id=f['fournisseur_id'], source_attendue=f['source_empreinte'],
                                      csrf=session.csrf, mutation_id=str(uuid.uuid4()))))
    for cle, libelle, maximum in [('nom', 'Nom du fournisseur', 200),
                                  ('courriel_commande', 'Courriel de commande (facultatif)', 254),
                                  ('telephone', 'Téléphone (facultatif)', 80)]:
        requis = ' required' if cle == 'nom' and fiche is None else ''
        corps += f'<label>Action pour {libelle}<select name="{cle}_action">'
        choix = ([('conserver', 'Conserver sans modification')] if fiche is not None else [])
        choix += [('remplacer', 'Saisir une nouvelle valeur')]
        if cle != 'nom':
            choix += [('effacer', 'Effacer ce contact')]
        for valeur, label in choix:
            selected = ' selected' if valeur == ('conserver' if fiche is not None else 'remplacer') else ''
            corps += f'<option value="{valeur}"{selected}>{label}</option>'
        corps += '</select></label>'
        corps += (f'<label>{libelle}<input name="{cle}" maxlength="{maximum}"{requis} '
                  f'value="{pages.e(f[cle] or "")}"></label>')
    return (corps + '<p>Choisir « Saisir une nouvelle valeur » pour modifier un champ, ou « Effacer ce contact ». '
            'Un champ en mode « Conserver » reste intact. Les catégories, délais et préférences '
            'déjà enregistrés restent conservés. Aucun message ne sera envoyé.</p>'
            '<button>Enregistrer le fournisseur</button></form>')


def creer_router(*, session_page, cnx_factory, deps, prefixe, verifier_formulaire, rendre):
    router = APIRouter()
    base = prefixe + BASE

    def agir(session, nom, args, mutation=None):
        return catalogue.appeler(cnx_factory, deps, session, nom, args, mutation)

    @router.get(BASE)
    def liste(request: Request):
        session = session_page(request)
        p = request.query_params
        if set(p) - {'debut'} or any(len(p.getlist(k)) != 1 for k in p):
            raise HTTPException(400, 'Paramètres invalides')
        debut = catalogue.entier(p.get('debut', '0'))
        r = agir(session, 'm6_lister_fournisseurs_console', dict(debut=debut, limite=25))
        corps = (f'<p><a href="{pages.e(prefixe + catalogue.BASE)}">Matériaux et tarifs</a></p>'
                 '<h2>Fournisseurs</h2><p>Coordonnées déclarées par l’admin, sans contact inventé.</p><ul>')
        for f in r['fournisseurs']:
            lien = base + '/' + pages._segment(f['fournisseur_id'])
            corps += f'<li><a href="{pages.e(lien)}">{pages.e(f["nom"])}</a></li>'
        corps += '</ul>' if r['fournisseurs'] else '</ul><p>Aucun fournisseur enregistré.</p>'
        corps += f'<p>{r["total"]} fournisseur(s).</p>'
        for offset, libelle in [(max(0, debut - 25) if debut else None, 'Page précédente'),
                                (r['suivant'], 'Page suivante')]:
            if offset is not None:
                lien = base + '?' + urlencode(dict(debut=offset))
                corps += f'<p><a href="{pages.e(lien)}">{libelle}</a></p>'
        return rendre(session, 'Fournisseurs', corps + '<h2>Nouveau fournisseur</h2>' + formulaire(session, prefixe))

    @router.post(BASE + '/enregistrer')
    async def enregistrer(request: Request):
        session = session_page(request)
        p = await prefill_ui.extraire(request, CHAMPS)
        verifier_formulaire(p, session)
        modifications = {}
        for cle in ('nom', 'courriel_commande', 'telephone'):
            action = p[cle + '_action']
            if action == 'conserver':
                continue
            if action == 'remplacer':
                modifications[cle] = p[cle] if cle == 'nom' else p[cle] or None
            elif action == 'effacer' and cle != 'nom':
                modifications[cle] = None
            else:
                raise HTTPException(400, 'Action de champ invalide')
        if not modifications:
            raise HTTPException(400, 'Choisir au moins un champ à modifier')
        r = agir(session, 'm6_enregistrer_fournisseur_console',
                 dict(fournisseur_id=p['fournisseur_id'], source_attendue=p['source_attendue'],
                      modifications=modifications), p['mutation_id'])
        return RedirectResponse(base + '/' + pages._segment(r['fournisseur_id']), 303)

    @router.get(BASE + '/{fournisseur_id}')
    def fiche(fournisseur_id: str, request: Request):
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres invalides')
        f = agir(session, 'm6_lire_fournisseur_console', dict(fournisseur_id=fournisseur_id))
        corps = (f'<p><a href="{pages.e(base)}">Tous les fournisseurs</a></p><h2>{pages.e(f["nom"])}</h2>'
                 f'<p>Référence : {pages.e(f["fournisseur_id"])} · dernière écriture : '
                 f'{pages.e(f["horodatage"])}</p>'
                 f'<p><a href="{pages.e(prefixe + catalogue.BASE)}">Matériaux et tarifs</a></p>'
                 '<h2>Corriger la fiche</h2>')
        from urllib.parse import urlencode

        lien = prefixe + catalogue.BASE + '/tarifs/importer?' + urlencode(dict(fournisseur_id=fournisseur_id))
        corps += f'<p><a href="{pages.e(lien)}">Préparer une liste de prix CSV pour ce fournisseur</a></p>'
        return rendre(session, 'Fiche fournisseur', corps + formulaire(session, prefixe, f))

    return router
