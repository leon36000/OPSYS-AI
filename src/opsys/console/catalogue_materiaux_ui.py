"""Gestion admin du catalogue M6 par ses ports privés, sans écriture SQL directe."""
import re
import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import identite
from . import metier, pages, prefill_ui

BASE = '/crm/materiaux'
CHAMPS = {'materiau_id', 'nom', 'unite', 'actif', 'raison', 'revision_attendue', 'csrf', 'mutation_id'}


def entier(valeur):
    if re.fullmatch(r'[0-9]{1,5}', valeur) is None or int(valeur) > 10000:
        raise HTTPException(400, 'Version ou pagination invalide')
    return int(valeur)


def extraire(reponse):
    r = reponse.get('resultat') if isinstance(reponse, dict) and reponse.get('ok') is True else None
    if not isinstance(r, dict):
        raise HTTPException(503, 'Catalogue matériaux indisponible')
    if r.get('accepte') is True and isinstance(r.get('resultat'), dict):
        return r['resultat']
    code = r.get('raison')
    statuts = {'IDENTITE': 403, 'ARGUMENTS': 400, 'INTROUVABLE': 404, 'REVISION-PERIMEE': 409,
               'UNITE-IMMUABLE': 409, 'MUTATION-CONFLIT': 409}
    messages = {'REVISION-PERIMEE': 'La fiche a changé : relire avant de modifier.',
                'UNITE-IMMUABLE': 'L’unité est immuable : créer une autre référence pour une autre unité.',
                'MUTATION-CONFLIT': 'Cette intention a déjà servi à une autre saisie.',
                'ARGUMENTS': 'Vérifier les textes, l’unité et la version.',
                'INTROUVABLE': 'Matériau ou version introuvable.'}
    raise HTTPException(statuts.get(code, 503), messages.get(code, 'Catalogue matériaux indisponible'))


def appeler(cnx_factory, deps, session, nom, arguments, mutation=None):
    try:
        with cnx_factory() as cnx:
            return extraire(metier.executer(cnx, deps, session, nom, arguments, mutation_id=mutation))
    except PermissionError:
        raise HTTPException(403, 'Accès admin requis') from None
    except KeyError:
        raise HTTPException(503, 'Catalogue matériaux indisponible') from None
    except ValueError:
        raise HTTPException(400, 'Saisie invalide') from None


def formulaire(session, prefixe, fiche=None):
    f = fiche or dict(materiau_id=str(uuid.uuid4()), nom='', unite='', actif=True, revision=0)
    contenu = (f'<form method="post" action="{pages.e(prefixe + BASE)}/enregistrer" class="pile">'
               + prefill_ui.caches(dict(materiau_id=f['materiau_id'], revision_attendue=f['revision'],
                                        csrf=session.csrf, mutation_id=str(uuid.uuid4())))
               + '<label>Nom du matériau<input name="nom" maxlength="200" required '
               f'value="{pages.e(f["nom"])}"></label>'
               '<label>Unité<input name="unite" maxlength="40" required '
               f'value="{pages.e(f["unite"])}"' + (' readonly' if fiche else '') + '></label>'
               '<label>Disponibilité<select name="actif">')
    for valeur, libelle in [('true', 'Actif'), ('false', 'Inactif')]:
        selected = ' selected' if f['actif'] == (valeur == 'true') else ''
        contenu += f'<option value="{valeur}"{selected}>{libelle}</option>'
    return (contenu + '</select></label><label>Raison de la saisie<input name="raison" maxlength="500" required>'
            '</label><button>Enregistrer la fiche</button></form>')


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
        return appeler(cnx_factory, deps, session, nom, args, mutation)

    @router.get(BASE)
    def catalogue(request: Request):
        session = admin(request)
        p = request.query_params
        if set(p) - {'debut'} or any(len(p.getlist(k)) != 1 for k in p):
            raise HTTPException(400, 'Paramètres invalides')
        debut = entier(p.get('debut', '0'))
        r = agir(session, 'm6_lister_materiaux_console', dict(debut=debut, limite=25, actifs_seulement=False))
        corps = '<h2>Matériaux</h2><p>Fiches versionnées. Les prix restent dans le livre de prix fournisseur.</p><ul>'
        for f in r['materiaux']:
            lien = base + '/' + pages._segment(f['materiau_id'])
            corps += (f'<li><a href="{pages.e(lien)}">{pages.e(f["nom"])}</a> · {pages.e(f["unite"])} · '
                      + ('Actif' if f['actif'] else 'Inactif') + f' · version {f["revision"]}</li>')
        corps += '</ul>' if r['materiaux'] else '</ul><p>Aucun matériau enregistré.</p>'
        corps += f'<p>{r["total"]} matériau(x).</p>'
        for offset, label in [(max(0, debut - 25) if debut else None, 'Page précédente'),
                              (r['suivant'], 'Page suivante')]:
            if offset is not None:
                corps += f'<p><a href="{pages.e(base + "?" + urlencode(dict(debut=offset)))}">{label}</a></p>'
        corps += '<h2>Nouveau matériau</h2>' + formulaire(session, prefixe)
        return rendre(session, 'Catalogue matériaux', corps)

    @router.post(BASE + '/enregistrer')
    async def enregistrer(request: Request):
        session = admin(request)
        p = await prefill_ui.extraire(request, CHAMPS)
        verifier_formulaire(p, session)
        if p['actif'] not in {'true', 'false'}:
            raise HTTPException(400, 'Disponibilité invalide')
        r = agir(session, 'm6_enregistrer_materiau_console',
                 dict(materiau_id=p['materiau_id'], nom=p['nom'], unite=p['unite'], actif=p['actif'] == 'true',
                      raison=p['raison'], revision_attendue=entier(p['revision_attendue'])), p['mutation_id'])
        return RedirectResponse(base + '/' + pages._segment(r['materiau_id']) + '?version=' + str(r['revision']), 303)

    @router.get(BASE + '/{materiau_id}')
    def fiche(materiau_id: str, request: Request):
        session = admin(request)
        p = request.query_params
        if set(p) - {'version'} or any(len(p.getlist(k)) != 1 for k in p):
            raise HTTPException(400, 'Paramètres invalides')
        args = dict(materiau_id=materiau_id, revision=entier(p.get('version', '0')))
        with cnx_factory():
            f = agir(session, 'm6_lire_materiau_console', args)
            courant = agir(session, 'm6_lire_materiau_console', dict(materiau_id=materiau_id, revision=0))
        corps = (f'<p><a href="{pages.e(base)}">Retour aux matériaux</a></p><h2>{pages.e(f["nom"])}</h2>'
                 f'<p>Référence : {pages.e(f["materiau_id"])} · unité : {pages.e(f["unite"])}</p>'
                 f'<p>Version {f["revision"]} sur {courant["revision"]} · '
                 + ('Actif' if f['actif'] else 'Inactif')
                 + f'</p><p>Raison : {pages.e(f["raison"])}</p>'
                 f'<p>Auteur : {pages.e(f["auteur"])} · {pages.e(f["horodatage"])}</p>')
        for version, label in [(f['revision'] - 1, 'Version précédente'), (f['revision'] + 1, 'Version suivante')]:
            if 1 <= version <= courant['revision']:
                lien = base + '/' + pages._segment(materiau_id) + '?version=' + str(version)
                corps += f'<p><a href="{pages.e(lien)}">{label}</a></p>'
        if f['revision'] == courant['revision']:
            corps += '<h2>Réviser cette fiche</h2>' + formulaire(session, prefixe, f)
        return rendre(session, 'Fiche matériau', corps)

    return router
