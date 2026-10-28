"""Proposition privée d'une reprise M4 : aucune affectation ni date civile implicite."""
from datetime import UTC, datetime

from m4_field_ops import cedule_tournees, encodage, etats, visites_chantier, visites_ecriture
from m4_field_ops.registre import Registre, VerificationError
from sqlalchemy import LargeBinary, cast, func, select

from .. import contexte, idempotence, stockage
from ..etat import journaliser
from ..outils import Autonomie, Niveau, executer_atomique
from ..stockage.schema import MUTATIONS_APPLIQUEES
from . import memoire_chantier as autorite
from . import preparation_chantier as lecture
from . import proposition_chantier as proposition

NOM = 'm4_proposer_cedule'



def _recu_borne(cnx, meta):
    condition = ((MUTATIONS_APPLIQUEES.c.appareil == meta.appareil)
                 & (MUTATIONS_APPLIQUEES.c.cle_idempotence == meta.cle))
    ancien = cnx.execute(select(MUTATIONS_APPLIQUEES.c.statut,
        func.length(cast(MUTATIONS_APPLIQUEES.c.reponse, LargeBinary))).where(condition)).one_or_none()
    if ancien is not None and (ancien[0] != 'ok' or ancien[1] is None
                               or not 0 < ancien[1] <= lecture.MAX_SORTIE_OCTETS):
        raise lecture.Refus('RECU-INDISPONIBLE')


def _verifier_intention(plan, intervention_id, equipe_id, debut_min, fin_min):
    try:
        entree = plan['entree']
        equipes, chantiers = entree['equipes'], entree['chantiers']
        if (len(equipes) != 1 or equipes[0]['id'] != equipe_id or len(chantiers) != 1
                or chantiers[0]['id'] != intervention_id
                or chantiers[0]['fenetre'] != dict(jours=[0], debut_min=debut_min, fin_min=fin_min)
                or chantiers[0]['creneau_fige'] is not None):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise lecture.Refus('SOURCE-INCOHERENTE') from None


def _controle_final(cnx, principal_attendu, courant):
    if (Registre(stockage.maillons(lecture.M4, 'principal')).lire() != principal_attendu
            or idempotence.empreinte_arguments(proposition._profils()) != courant['profils_source']
            or visites_ecriture.capturer_visites(cnx).empreinte_snapshot_calculee != courant['visite_source']):
        raise lecture.Refus('SOURCE-MODIFIEE')

def preparer(cnx, deps, session, intervention_id):
    """Source d'une intention : état M4, équipes courantes, visite et report vérifiés."""
    autorite._admin(cnx, session)
    if (cnx is not stockage.connexion_courante() or cnx.dialect.name != 'sqlite'
            or type(intervention_id) is not str or lecture.IDENTIFIANT.fullmatch(intervention_id) is None):
        raise lecture.Refus('ARGUMENTS')
    source = visites_ecriture.capturer_visites(cnx)
    lecture._borner(cnx, lecture.M4, 'principal')
    principal = Registre(stockage.maillons(lecture.M4, 'principal'))
    lignes = principal.lire()
    principal.assert_chaine()
    prev = Registre([r.maillon for r in source.lignes])
    ouvert = visites_chantier.visite_active(principal, intervention_id)
    reports = [m for m in lignes if m.get('type_entree') == etats.TYPE_TRANSITION
               and m.get('intervention_id') == intervention_id and m.get('statut') == 'reportee']
    if (etats.statut_courant(principal, intervention_id) != 'planifiee' or ouvert is not None
            or not reports or not reports[-1].get('visite_id') or not reports[-1].get('source_fermeture')):
        raise lecture.Refus('REPRISE-NON-PERMISE')
    fermetures = [m for m in lignes if m.get('type_entree') == 'visite_fermee'
                  and m.get('intervention_id') == intervention_id]
    if (not fermetures or reports[-1]['visite_id'] != fermetures[-1]['visite_id']
            or reports[-1]['source_fermeture'] != fermetures[-1]['ligne_id']
            or lignes.index(fermetures[-1]) >= lignes.index(reports[-1])):
        raise lecture.Refus('SOURCE-INCOHERENTE')
    visites_chantier.calculer_faits_certifies(principal, prev, intervention_id, ignorer_anciens=True)
    profil = proposition._profils()
    equipe = profil['equipes']
    if not isinstance(equipe, dict) or not isinstance(equipe.get('liste'), list):
        raise lecture.Refus('PROFIL-INDISPONIBLE')
    equipes = cedule_tournees._equipes_du_profil(equipe)
    if not 1 <= len(equipes) <= 100:
        raise lecture.Refus('PROFIL-INDISPONIBLE')
    noms = [x['id'] for x in equipes]
    if len(set(noms)) != len(noms) or any(type(x) is not str or not x for x in noms):
        raise lecture.Refus('PROFIL-INDISPONIBLE')
    empreinte = idempotence.empreinte_arguments(dict(intervention_id=intervention_id,
        principal=principal.tete(), visites=source.empreinte_snapshot_calculee, profils=profil))
    autorite._admin(cnx, session)
    return lecture._sortie(dict(empreinte=empreinte, equipes=noms,
        profils_source=idempotence.empreinte_arguments(profil), tete=principal.tete(),
        visite_source=source.empreinte_snapshot_calculee, report_horodatage=reports[-1]['horodatage'],
        report_id=reports[-1]['ligne_id']))


def proposer(cnx, deps, session, intervention_id, equipe_id, debut_min, fin_min, empreinte_attendue, mutation_id):
    with cnx.begin_nested():
        autorite._admin(cnx, session)
        lecture._borner(cnx, lecture.M4, 'principal')
        try:
            Registre(stockage.maillons(lecture.M4, 'principal')).assert_chaine()
        except VerificationError:
            raise lecture.Refus('SOURCE-INCOHERENTE') from None
        if (type(intervention_id) is not str or lecture.IDENTIFIANT.fullmatch(intervention_id) is None
                or type(empreinte_attendue) is not str or proposition.EMPREINTE.fullmatch(empreinte_attendue) is None
                or type(mutation_id) is not str or not 1 <= len(mutation_id) <= 200 or not mutation_id.strip()
                or type(equipe_id) is not str or type(debut_min) is not int or type(fin_min) is not int
                or not 0 <= debut_min < fin_min <= 1440):
            raise lecture.Refus('ARGUMENTS')
        maintenant = datetime.now(UTC)
        meta = idempotence.Meta(mutation_id, 'console:' + session.utilisateur, maintenant.isoformat())
        intention = dict(intervention_id=intervention_id, equipe_id=equipe_id, debut_min=debut_min,
                         fin_min=fin_min, empreinte=empreinte_attendue)
        _recu_borne(cnx, meta)
        try:
            recu = idempotence.reclamer(cnx, meta, NOM, intention, maintenant)
        except idempotence.MutationConflit:
            raise lecture.Refus('MUTATION-CONFLIT') from None
        if recu.rejouee:
            if (not isinstance(recu.reponse, dict) or set(recu.reponse) != {'ok', 'proposition', 'rejoue'}
                    or recu.reponse.get('ok') is not True or recu.reponse.get('rejoue') is not False):
                raise lecture.Refus('RECU-INDISPONIBLE')
            entree, sortie = proposition._verifier_proposition(recu.reponse['proposition'], intervention_id)
            _verifier_intention(entree, intervention_id, equipe_id, debut_min, fin_min)
            autorite._admin(cnx, session)
            return lecture._sortie(dict(ok=True, proposition=sortie, rejoue=True))
        courant = preparer(cnx, deps, session, intervention_id)
        if maintenant < visites_chantier._instant(courant['report_horodatage']):
            raise lecture.Refus('HORODATAGE-INVALIDE')
        if courant['empreinte'] != empreinte_attendue:
            raise lecture.Refus('SOURCE-MODIFIEE')
        if equipe_id not in courant['equipes']:
            raise lecture.Refus('EQUIPE-INCONNUE')
        profils = proposition._profils()
        equipes = [e for e in cedule_tournees._equipes_du_profil(profils['equipes']) if e['id'] == equipe_id]
        dep = deps.get(lecture.M4)
        outil = None if dep is None or dep.module_outils != lecture.MODULES[lecture.M4] else next(
            (o for o in dep.charger_outils() if o.nom == NOM), None)
        if outil is None or outil.autonomie != Autonomie.T1 or outil.niveau_effectif != Niveau.N1:
            raise lecture.Refus('SOURCE-INDISPONIBLE')
        args = dict(intervention_ids=[intervention_id], equipes=equipes,
            chantiers=[dict(intervention_id=intervention_id,
                fenetre=dict(jours=[0], debut_min=debut_min, fin_min=fin_min), creneau_fige=None)],
            moteur='auto', horodatage=maintenant.isoformat())
        avant = Registre(stockage.maillons(lecture.M4, 'principal')).lire()
        if Registre(avant).tete() != courant['tete']:
            raise lecture.Refus('SOURCE-MODIFIEE')
        with (contexte.appele_par_appareil(contexte.IdentiteAppelante(session.utilisateur, 'admin', source='console')),
              contexte.appeler_en_tant_que(lecture.M4, origine='console'),
              contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, maintenant, maintenant))):
            reponse = executer_atomique(outil, args)
        res = reponse.get('resultat') if reponse.get('ok') is True else None
        if not isinstance(res, dict) or res.get('accepte') is not True or not isinstance(res.get('resultat'), dict):
            raise lecture.Refus('PROPOSITION-REFUSEE')
        entree, sortie = proposition._verifier_proposition(res['resultat'], intervention_id, maintenant.isoformat())
        apres = Registre(stockage.maillons(lecture.M4, 'principal')).lire()
        ajouts = apres[len(avant):]
        _verifier_intention(entree, intervention_id, equipe_id, debut_min, fin_min)
        if entree['entree']['equipes'] != equipes:
            raise lecture.Refus('SOURCE-INCOHERENTE')
        if (apres[:len(avant)] != avant or len(ajouts) != (0 if sortie['deja_proposee'] else 1)
                or (ajouts and ajouts[0]['ligne_id'] != entree['ligne_id'])
                or entree['empreinte_profil'] != encodage.empreinte('profil-equipes', profils['equipes'])
                or idempotence.empreinte_arguments(proposition._profils()) != courant['profils_source']
                or visites_ecriture.capturer_visites(cnx).empreinte_snapshot_calculee != courant['visite_source']):
            raise lecture.Refus('SOURCE-MODIFIEE')
        autorite._admin(cnx, session)
        resultat = lecture._sortie(dict(ok=True, proposition=sortie, rejoue=False))
        journaliser(cnx, session.utilisateur, 'console.proposition_reprise', NOM,
                    dict(intervention_id=intervention_id, plan_id=sortie['plan_id'], mutation_id=mutation_id))
        idempotence.finaliser(cnx, meta, resultat)
        _controle_final(cnx, apres, courant)
        autorite._admin(cnx, session)
        return resultat


def preparer_application(cnx, deps, session, intervention_id, plan_id):
    """Revue d'un plan mono-chantier : aucune affectation n'est exécutée ici."""
    courant = preparer(cnx, deps, session, intervention_id)
    if type(plan_id) is not str or proposition.EMPREINTE.fullmatch(plan_id) is None:
        raise lecture.Refus('ARGUMENTS')
    principal = Registre(stockage.maillons(lecture.M4, 'principal'))
    instantane = cedule_tournees.instantane_du_registre(principal)
    plan = cedule_tournees.plan_propose(instantane, plan_id)
    if plan is None:
        raise lecture.Refus('INTROUVABLE')
    projection = cedule_tournees._resultat_proposition(plan, False, plan['provenance'], [])
    plan, projection = proposition._verifier_proposition(projection, intervention_id)
    inscriptions = cedule_tournees.inscriptions_du_registre(instantane)
    if intervention_id not in inscriptions:
        raise lecture.Refus('INTROUVABLE')
    etat = cedule_tournees._etat_intervention(instantane, inscriptions[intervention_id], {})
    routes = [(r['equipe'], v['chantier']) for r in projection['plan'] for v in r['visites']]
    applications = [m for m in principal.lire() if m.get('type_entree') == cedule_tournees.TYPE_APPLIQUEE
                    and m.get('plan_id') == plan_id]
    rangs = {m['ligne_id']: n for n, m in enumerate(principal.lire())}
    permis = (rangs.get(plan['ligne_id'], -1) > rangs.get(courant['report_id'], len(rangs))
              and not applications and len(routes) == 1 and routes[0][1] == intervention_id
              and not projection['non_cedulees'] and routes[0][0] in courant['equipes']
              and plan['etat'][0] == etat and etat['statut'] == 'planifiee'
              and visites_chantier._instant(plan['horodatage']) >=
                  visites_chantier._instant(courant['report_horodatage']))
    empreinte = idempotence.empreinte_arguments(dict(source=courant, plan_id=plan_id, projection=projection,
                                                     peut_appliquer=permis))
    return lecture._sortie(dict(empreinte=empreinte, proposition=projection, peut_appliquer=permis,
                               profils_source=courant['profils_source'], visite_source=courant['visite_source'],
                               tete=courant['tete']))


def _preuve_application(cnx, intervention_id, plan_id, approbation_id, acteur):
    import json

    from sqlalchemy import LargeBinary, cast, func, select

    from ..stockage.schema import APPROBATIONS

    if type(approbation_id) is not str or not 1 <= len(approbation_id) <= 32:
        raise lecture.Refus('APPROBATION-INDISPONIBLE')
    principal = Registre(stockage.maillons(lecture.M4, 'principal'))
    lignes = principal.lire()
    principal.assert_chaine()
    instantane = cedule_tournees.instantane_du_registre(principal)
    plan = cedule_tournees.plan_propose(instantane, plan_id)
    matches = [(n, m) for n, m in enumerate(lignes)
               if m.get('type_entree') == cedule_tournees.TYPE_APPLIQUEE and m.get('plan_id') == plan_id]
    if plan is None or len(matches) != 1:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    proposition._verifier_proposition(
        cedule_tournees._resultat_proposition(plan, False, plan['provenance'], []), intervention_id)
    rang, marqueur = matches[0]
    routes = [(r['equipe'], v['chantier']) for r in plan['sortie']['plan'] for v in r['visites']]
    if (len(plan['etat']) != 1 or len(routes) != 1 or routes[0][1] != intervention_id
            or plan['etat'][0]['statut'] != 'planifiee' or marqueur['appliquee_par'] != acteur
            or marqueur['empreinte_entree'] != plan['empreinte_entree']
            or marqueur['empreinte_sortie'] != plan['empreinte_sortie'] or marqueur['non_cedulees']):
        raise lecture.Refus('SOURCE-INCOHERENTE')
    equipe = routes[0][0]
    effet = (cedule_tournees.EFFET_DEJA_ASSIGNEE if plan['etat'][0]['technicien_assigne'] == equipe
             else cedule_tournees.EFFET_ASSIGNEE)
    attendu = [dict(intervention_id=intervention_id, technicien_id=equipe, effet=effet, transition=None)]
    depart = next(n for n, m in enumerate(lignes) if m['ligne_id'] == plan['ligne_id'])
    segment = lignes[depart + 1:rang]
    assignations = [m for m in segment if m.get('type_entree') == etats.TYPE_ASSIGNATION
                    and m.get('intervention_id') == intervention_id]
    transitions = [m for m in segment if m.get('type_entree') == etats.TYPE_TRANSITION
                   and m.get('intervention_id') == intervention_id]
    if (transitions or marqueur['assignations'] != attendu
            or (effet == cedule_tournees.EFFET_ASSIGNEE and
                (len(assignations) != 1 or assignations[0].get('technicien_id') != equipe
                 or assignations[0].get('horodatage') != marqueur['horodatage']))
            or (effet == cedule_tournees.EFFET_DEJA_ASSIGNEE and assignations)):
        raise lecture.Refus('SOURCE-INCOHERENTE')
    avant = Registre(lignes[:rang])
    avant.assert_chaine()
    if (etats.statut_courant(avant, intervention_id) != 'planifiee'
            or etats.technicien_assigne(avant, intervention_id) != equipe):
        raise lecture.Refus('SOURCE-INCOHERENTE')
    condition = APPROBATIONS.c.id == approbation_id
    tailles = cnx.execute(select(func.length(cast(APPROBATIONS.c.arguments, LargeBinary)),
        func.length(cast(APPROBATIONS.c.resultat, LargeBinary))).where(condition)).one_or_none()
    if tailles is None or any(t is None or t > lecture.MAX_SORTIE_OCTETS for t in tailles):
        raise lecture.Refus('APPROBATION-INDISPONIBLE')
    decision = cnx.execute(select(APPROBATIONS).where(condition)).mappings().one()
    args = dict(plan_id=plan_id, horodatage=marqueur['horodatage'], confirme_par=acteur)
    if (decision['departement'] != lecture.M4 or decision['outil'] != 'm4_appliquer_cedule'
            or decision['niveau'] != 'N3' or decision['statut'] != 'executee'
            or decision['decide_par'] != acteur or decision['decide_role'] != 'admin'
            or json.loads(decision['arguments']) != args):
        raise lecture.Refus('APPROBATION-INCOHERENTE')
    reponse = json.loads(decision['resultat'])
    metier = reponse.get('resultat') if isinstance(reponse, dict) and reponse.get('ok') is True else None
    resultat = cedule_tournees._resultat_application(marqueur, plan, False)
    if (not isinstance(metier, dict) or metier.get('accepte') is not True
            or metier.get('resultat') != dict(resultat, horodatage_appareil=marqueur['horodatage'])):
        raise lecture.Refus('APPROBATION-INCOHERENTE')
    return resultat


def appliquer(cnx, deps, session, intervention_id, plan_id, empreinte_attendue, mutation_id):
    from .. import approbations

    with cnx.begin_nested():
        autorite._admin(cnx, session)
        lecture._borner(cnx, lecture.M4, 'principal')
        if (type(plan_id) is not str or proposition.EMPREINTE.fullmatch(plan_id) is None
                or type(empreinte_attendue) is not str or proposition.EMPREINTE.fullmatch(empreinte_attendue) is None
                or type(mutation_id) is not str or not 1 <= len(mutation_id) <= 200 or not mutation_id.strip()):
            raise lecture.Refus('ARGUMENTS')
        maintenant = datetime.now(UTC)
        meta = idempotence.Meta(mutation_id, 'console:' + session.utilisateur, maintenant.isoformat())
        intention = dict(intervention_id=intervention_id, plan_id=plan_id, empreinte=empreinte_attendue)
        _recu_borne(cnx, meta)
        try:
            recu = idempotence.reclamer(cnx, meta, 'm4_appliquer_cedule', intention, maintenant)
        except idempotence.MutationConflit:
            raise lecture.Refus('MUTATION-CONFLIT') from None
        if recu.rejouee:
            r = recu.reponse
            if (not isinstance(r, dict) or set(r) != {'ok', 'application', 'approbation_id', 'rejoue'}
                    or r.get('ok') is not True or r.get('rejoue') is not False):
                raise lecture.Refus('RECU-INDISPONIBLE')
            projection = _preuve_application(cnx, intervention_id, plan_id, r['approbation_id'], session.utilisateur)
            if projection != r['application']:
                raise lecture.Refus('RECU-INCOHERENT')
            autorite._admin(cnx, session)
            return lecture._sortie(dict(ok=True, application=projection, approbation_id=r['approbation_id'],
                                        rejoue=True))
        courant = preparer_application(cnx, deps, session, intervention_id, plan_id)
        if courant['empreinte'] != empreinte_attendue:
            raise lecture.Refus('SOURCE-MODIFIEE')
        if maintenant < visites_chantier._instant(courant['proposition']['horodatage']):
            raise lecture.Refus('HORODATAGE-INVALIDE')
        if not courant['peut_appliquer']:
            raise lecture.Refus('APPLICATION-NON-PERMISE')
        dep = deps.get(lecture.M4)
        outil = None if dep is None or dep.module_outils != lecture.MODULES[lecture.M4] else next(
            (o for o in dep.charger_outils() if o.nom == 'm4_appliquer_cedule'), None)
        if outil is None or outil.autonomie != Autonomie.T1 or outil.niveau_effectif != Niveau.N3:
            raise lecture.Refus('SOURCE-INDISPONIBLE')
        args = dict(plan_id=plan_id, horodatage=maintenant.isoformat(), confirme_par=session.utilisateur)
        avant = Registre(stockage.maillons(lecture.M4, 'principal')).lire()
        if Registre(avant).tete() != courant['tete']:
            raise lecture.Refus('SOURCE-MODIFIEE')
        with (contexte.appele_par_appareil(contexte.IdentiteAppelante(session.utilisateur, 'admin', source='console')),
              contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, maintenant, maintenant))):
            ident = approbations.creer_demande(cnx, lecture.M4, 'm4_appliquer_cedule', args, niveau=Niveau.N3,
                motif='Affectation interne explicitement demandée pour une reprise, sans date ni envoi.')
            decision = approbations.decider(cnx, ident, True, session.utilisateur, {'m4_appliquer_cedule': outil},
                deps, role='admin', motif='Validation humaine de la reprise ; disponibilité et météo à confirmer.')
        if decision.get('statut') != 'executee' or not approbations.execution_reussie(decision.get('reponse', {})):
            raise lecture.Refus('APPLICATION-REFUSEE')
        projection = _preuve_application(cnx, intervention_id, plan_id, ident, session.utilisateur)
        apres = Registre(stockage.maillons(lecture.M4, 'principal')).lire()
        ajouts = apres[len(avant):]
        attendu_types = (['assignation_technicien', 'cedule_appliquee']
                          if projection['assignations'][0]['effet'] == cedule_tournees.EFFET_ASSIGNEE
                          else ['cedule_appliquee'])
        if apres[:len(avant)] != avant or [x['type_entree'] for x in ajouts] != attendu_types:
            raise lecture.Refus('SOURCE-MODIFIEE')
        if (idempotence.empreinte_arguments(proposition._profils()) != courant['profils_source']
                or visites_ecriture.capturer_visites(cnx).empreinte_snapshot_calculee != courant['visite_source']):
            raise lecture.Refus('SOURCE-MODIFIEE')
        autorite._admin(cnx, session)
        resultat = lecture._sortie(dict(ok=True, application=projection, approbation_id=ident, rejoue=False))
        journaliser(cnx, session.utilisateur, 'console.application_reprise', 'm4_appliquer_cedule',
                    dict(intervention_id=intervention_id, plan_id=plan_id, approbation_id=ident,
                         mutation_id=mutation_id))
        idempotence.finaliser(cnx, meta, resultat)
        _controle_final(cnx, apres, courant)
        autorite._admin(cnx, session)
        return resultat


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre, verifier_formulaire):
    """Saisie humaine bornée : proposition, revue N3 puis accès au calendrier existant."""
    import uuid
    from urllib.parse import urlencode

    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import RedirectResponse

    from . import cedule_plan_ui, pages

    router = APIRouter()

    def cible(iid, plan=None):
        q = {'intervention_id': iid}
        if plan is not None:
            q['plan_id'] = plan
        return prefixe + '/crm/visites/reprise?' + urlencode(q)

    def identifiant(params, avec_plan=False):
        items = list(params.multi_items())
        attendus = {'intervention_id', 'plan_id'} if avec_plan else {'intervention_id'}
        if len(items) != len(attendus) or set(params) != attendus:
            raise HTTPException(400, 'Paramètres invalides')
        iid = params['intervention_id']
        if lecture.IDENTIFIANT.fullmatch(iid) is None:
            raise HTTPException(400, 'Chantier invalide')
        plan = params.get('plan_id')
        if avec_plan and proposition.EMPREINTE.fullmatch(plan) is None:
            raise HTTPException(400, 'Plan invalide')
        return iid, plan

    def refus(exc):
        code = 409 if exc.code in {'SOURCE-MODIFIEE', 'REPRISE-NON-PERMISE', 'APPLICATION-NON-PERMISE',
                                   'EQUIPE-INCONNUE', 'PROPOSITION-REFUSEE', 'APPLICATION-REFUSEE',
                                   'MUTATION-CONFLIT', 'HORODATAGE-INVALIDE'} else 503
        return HTTPException(code, 'Reprise indisponible : ' + exc.code)

    @router.get('/crm/visites/reprise')
    def page(request: Request):
        session = session_page(request)
        iid, plan = identifiant(request.query_params, 'plan_id' in request.query_params)
        try:
            with cnx_factory() as cnx:
                vue = (preparer_application(cnx, deps, session, iid, plan) if plan else
                       preparer(cnx, deps, session, iid))
                corps = (f'<section><h2>Préparer la reprise — {pages.e(iid)}</h2>'
                         '<p>La fenêtre choisie porte sur le jour du plan ; la date civile reste à confirmer. '
                         'Vérifier la disponibilité, les autres tournées et la météo.</p>')
                commun = (f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                          f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
                          f'<input type="hidden" name="empreinte_attendue" value="{pages.e(vue["empreinte"])}">')
                if plan:
                    p = vue['proposition']
                    corps += f'<p>Plan : {pages.e(plan)} · {pages.e(p["avertissement"])}</p><ul>'
                    for route in p['plan']:
                        for visite in route['visites']:
                            corps += (f'<li>Équipe {pages.e(route["equipe"])} · jour {route["jour"] + 1} · '
                                      f'{visite["debut_min"] // 60:02d}:{visite["debut_min"] % 60:02d}–'
                                      f'{visite["fin_min"] // 60:02d}:{visite["fin_min"] % 60:02d}</li>')
                    corps += '</ul>'
                    if vue['peut_appliquer']:
                        corps += (f'<form method="post" action="{pages.e(cible(iid, plan))}">{commun}'
                                  '<button type="submit">Confirmer l’affectation interne N3</button></form>')
                else:
                    options = ''.join(f'<option value="{pages.e(e)}">{pages.e(e)}</option>' for e in vue['equipes'])
                    corps += (f'<form method="post" action="{pages.e(cible(iid))}">{commun}'
                              f'<label>Équipe déclarée <select name="equipe_id">{options}</select></label>'
                              '<label>Début de fenêtre <input type="time" name="debut" required></label>'
                              '<label>Fin de fenêtre <input type="time" name="fin" required></label>'
                              '<button type="submit">Proposer la reprise</button></form>')
                corps += '</section>'
                reponse = rendre(session, 'Reprise du chantier', corps)
                if len(reponse.body) > 131072:
                    raise lecture.Refus('SORTIE-TROP-VOLUMINEUSE')
                autorite._admin(cnx, session)
                return reponse
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except lecture.Refus as exc:
            raise refus(exc) from None
        except (ValueError, KeyError, TypeError, VerificationError):
            raise HTTPException(503, 'Sources de reprise indisponibles') from None

    @router.post('/crm/visites/reprise')
    async def agir(request: Request):
        session = session_page(request)
        iid, plan = identifiant(request.query_params, 'plan_id' in request.query_params)
        champs = await cedule_plan_ui.formulaire(request)
        verifier_formulaire(champs, session)
        commun = {'csrf', 'mutation_id', 'empreinte_attendue'}
        if set(champs) != (commun if plan else commun | {'equipe_id', 'debut', 'fin'}):
            raise HTTPException(400, 'Formulaire invalide')
        try:
            with cnx_factory() as cnx:
                if plan:
                    appliquer(cnx, deps, session, iid, plan, champs['empreinte_attendue'], champs['mutation_id'])
                    destination = prefixe + '/crm/cedule/plan/' + plan
                else:
                    import re
                    def minute(valeur):
                        if re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', valeur) is None:
                            raise ValueError
                        return int(valeur[:2]) * 60 + int(valeur[3:])
                    debut, fin = minute(champs['debut']), minute(champs['fin'])
                    resultat = proposer(cnx, deps, session, iid, champs['equipe_id'], debut, fin,
                                         champs['empreinte_attendue'], champs['mutation_id'])
                    destination = cible(iid, resultat['proposition']['plan_id'])
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except lecture.Refus as exc:
            raise refus(exc) from None
        except (ValueError, KeyError, TypeError, VerificationError):
            raise HTTPException(400, 'Formulaire ou sources invalides') from None
        return RedirectResponse(destination, status_code=303)

    return router
