"""Formulaire privé et revue de proposition; aucune affectation ni confirmation de date."""
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import cedule_plan_ui, pages
from . import preparation_chantier as lecture
from . import proposition_chantier as port

BASE = '/crm/lead/{lead_id}/soumissions/{devis_id}/propositions-chantier'


def url(lead_id, devis_id, prefixe):
    return f'{prefixe}/crm/lead/{pages._segment(lead_id)}/soumissions/{pages._segment(devis_id)}/propositions-chantier'


def formulaire(apercu, csrf, prefixe):
    vue = apercu['vue']
    if (vue['ancre_complete'] is not True or vue['intervention'] is None
            or vue['intervention']['statut'] != 'a_planifier' or vue['preparation'] is None
            or vue['preparation']['pret'] is not True):
        return ''
    return (f'<form method="post" action="{pages.e(url(vue["lead_id"], vue["devis_id"], prefixe))}" class="pile">'
        f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">'
        f'<input type="hidden" name="empreinte_attendue" value="{pages.e(apercu["empreinte"])}">'
        f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
        '<p>Créer une proposition pour cette intervention avec les profils actuels. '
        'Les sources seront relues. Aucune affectation ni date client ne sera confirmée.</p>'
        '<button type="submit">Proposer une cédule</button></form>')


def _heure(minute):
    if type(minute) is not int or not 0 <= minute <= 1440:
        raise ValueError('heure de plan illisible')
    return f'{minute // 60:02d}:{minute % 60:02d}'


def contenu(vue, prefixe):
    p = vue['proposition']
    base = url(vue['lead_id'], vue['devis_id'], prefixe).removesuffix('/propositions-chantier')
    corps = (f'<p><a href="{pages.e(base)}/preparation-chantier">Relire la préparation du chantier</a></p>'
        '<h2>Proposition enregistrée</h2><p>Proposition historique M4. Aucune affectation ni date civile '
        'n’est confirmée par cet écran. Les règles météo ne constituent pas une prévision du créneau.</p>'
        f'<p>État actuel de l’intervention : {pages.e(vue["statut_intervention"])}</p>')
    if vue['etat_ou_equipes_modifies']:
        corps += '<p role="alert">État, localisation, préparation ou équipes modifiés depuis la proposition.</p>'
    corps += (f'<p>Plan : {pages.e(p["plan_id"])}</p><p>Proposé par : {pages.e(p["propose_par"])} · '
              f'{pages.e(p["horodatage"])}</p><p>Solveur : {pages.e(p["solveur"])}</p>')
    if p['avertissement']:
        corps += f'<p role="alert">{pages.e(p["avertissement"])}</p>'
    corps += '<h3>Visites proposées — jours numériques du plan</h3><ul>'
    for route in p['plan']:
        if type(route['jour']) is not int or not 0 <= route['jour'] <= 99999:
            raise ValueError('jour illisible')
        for visite in route['visites']:
            corps += (f'<li>{pages.e(route["equipe"])} · Jour {route["jour"] + 1} du plan · '
                f'{_heure(visite["debut_min"])}–{_heure(visite["fin_min"])} · '
                f'intervention {pages.e(visite["chantier"])}</li>')
    corps += '</ul><h3>Interventions non cédulées</h3><ul>'
    for ligne in p['non_cedulees']:
        corps += (f'<li>{pages.e(ligne["chantier"])} : {pages.e(ligne["raison"])} · '
                  f'{pages.e(ligne["action"])}</li>')
    corps += '</ul><h3>Provenance des paramètres</h3><dl>'
    for cle, valeur in p['provenance'].items():
        corps += f'<dt>{pages.e(cle)}</dt><dd>{pages.e(valeur)}</dd>'
    return corps + '</dl>'


def _refus(exc):
    if exc.code == 'INTROUVABLE':
        statut = 404
    elif exc.code == 'ARGUMENTS':
        statut = 400
    elif (exc.code in {'DEVIS-NON-ACCEPTE', 'PREPARATION-NON-PRETE', 'SOURCE-MODIFIEE', 'MUTATION-CONFLIT'}
          or exc.code.startswith(('REJ-CEDULE-', 'REJ-COORDONNEES-'))):
        statut = 409
    else:
        statut = 503
    return HTTPException(statut, 'Proposition indisponible : ' + exc.code)


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre, verifier_formulaire):
    router = APIRouter()

    @router.post(BASE)
    async def proposer(lead_id: str, devis_id: str, request: Request):
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres invalides')
        champs = await cedule_plan_ui.formulaire(request)
        verifier_formulaire(champs, session)
        if set(champs) != {'csrf', 'mutation_id', 'empreinte_attendue'}:
            raise HTTPException(400, 'Formulaire invalide')
        try:
            with cnx_factory() as cnx:
                resultat = port.proposer(cnx, deps, session, lead_id, devis_id,
                                         champs['empreinte_attendue'], champs['mutation_id'])
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except lecture.Refus as exc:
            raise _refus(exc) from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Sources de proposition indisponibles') from None
        destination = url(lead_id, devis_id, prefixe) + '/' + pages._segment(resultat['proposition']['plan_id'])
        return RedirectResponse(destination, status_code=303)

    @router.get(BASE + '/{plan_id}')
    def revoir(lead_id: str, devis_id: str, plan_id: str, request: Request):
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres invalides')
        try:
            with cnx_factory() as cnx:
                vue = port.lire(cnx, deps, session, lead_id, devis_id, plan_id)
            reponse = rendre(session, 'Revue de proposition M4', contenu(vue, prefixe))
            if len(reponse.body) > 131072:
                raise lecture.Refus('SORTIE-TROP-VOLUMINEUSE')
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except lecture.Refus as exc:
            raise _refus(exc) from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Sources de proposition indisponibles') from None
        return reponse

    return router
