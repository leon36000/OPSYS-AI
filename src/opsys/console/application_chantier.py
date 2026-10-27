"""Application interne N3 privée : sources relues, décision signée, reçu historique borné."""
import json
from datetime import UTC, datetime

from sqlalchemy import LargeBinary, cast, func, select

from .. import approbations, contexte, idempotence, identite, stockage
from ..etat import journaliser
from ..outils import Autonomie, Niveau
from ..stockage.schema import APPROBATIONS, MUTATIONS_APPLIQUEES
from . import preparation_chantier as lecture
from . import proposition_chantier as proposition

NOM = 'm4_appliquer_cedule'


def _application(plan_id):
    from m4_field_ops import cedule_tournees, registre

    chaine = registre.Registre(stockage.maillons(lecture.M4, 'principal'))
    lignes = chaine.lire()
    matches = [(n, m) for n, m in enumerate(lignes)
               if m['type_entree'] == cedule_tournees.TYPE_APPLIQUEE and m.get('plan_id') == plan_id]
    if len(matches) > 1:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    return chaine, matches[0] if matches else None


def preparer(cnx, deps, session, lead_id, devis_id, plan_id):
    apercu = proposition.preparer(cnx, deps, session, lead_id, devis_id)
    revue = proposition.lire(cnx, deps, session, lead_id, devis_id, plan_id)
    _, application = _application(plan_id)
    if idempotence.empreinte_arguments(proposition._profils()) != apercu['profils_source']:
        raise lecture.Refus('SOURCE-MODIFIEE')
    visites = [v for r in revue['proposition']['plan'] for v in r['visites']]
    permis = (application is None and revue['statut_intervention'] == 'a_planifier'
              and not revue['etat_ou_equipes_modifies'] and revue['preparation'] is not None
              and revue['preparation']['pret'] is True and len(visites) == 1)
    preuve = dict(apercu=apercu, revue=revue, application_presente=application is not None)
    return lecture._sortie(dict(revue=revue, peut_appliquer=permis,
        empreinte=idempotence.empreinte_arguments(preuve), profils_source=apercu['profils_source']))


def _preuve_application(cnx, revue, approbation_id, acteur):
    from m4_field_ops import cedule_tournees, etats, registre

    if type(approbation_id) is not str or not 1 <= len(approbation_id) <= 32:
        raise lecture.Refus('APPROBATION-INDISPONIBLE')
    chaine, application = _application(revue['proposition']['plan_id'])
    if application is None:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    rang, marqueur = application
    plan = cedule_tournees.plan_propose(cedule_tournees.instantane_du_registre(chaine), marqueur['plan_id'])
    if (plan is None or marqueur['empreinte_entree'] != plan['empreinte_entree']
            or marqueur['empreinte_sortie'] != plan['empreinte_sortie'] or marqueur['appliquee_par'] != acteur):
        raise lecture.Refus('SOURCE-INCOHERENTE')
    visites = [(r['equipe'], v['chantier']) for r in plan['sortie']['plan'] for v in r['visites']]
    if len(visites) != 1 or visites[0][1] != revue['intervention_id'] or marqueur['non_cedulees']:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    equipe, iid = visites[0]
    effet = (cedule_tournees.EFFET_DEJA_ASSIGNEE if plan['etat'][0]['technicien_assigne'] == equipe
             else cedule_tournees.EFFET_ASSIGNEE)
    attendu = [dict(intervention_id=iid, technicien_id=equipe, effet=effet,
                    transition=cedule_tournees.TRANSITION_SORTIE_A_PLANIFIER)]
    lignes = chaine.lire()
    depart = next(n for n, m in enumerate(lignes) if m['ligne_id'] == plan['ligne_id'])
    segment = list(enumerate(lignes[depart + 1:rang], depart + 1))
    transitions = [(n, m) for n, m in segment
                   if m['type_entree'] == etats.TYPE_TRANSITION and m.get('intervention_id') == iid]
    assignations = [(n, m) for n, m in segment
                    if m['type_entree'] == etats.TYPE_ASSIGNATION and m.get('intervention_id') == iid]
    if len(transitions) != 1:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    rang_transition, transition = transitions[0]
    if (transition.get('statut_precedent') != 'a_planifier' or transition.get('statut') != 'planifiee'
            or transition.get('horodatage') != marqueur['horodatage']
            or transition.get('empreinte_preparation') != plan['etat'][0]['preparation']):
        raise lecture.Refus('SOURCE-INCOHERENTE')
    if effet == cedule_tournees.EFFET_ASSIGNEE:
        if (len(assignations) != 1 or assignations[0][0] <= rang_transition
                or assignations[0][1].get('technicien_id') != equipe
                or assignations[0][1].get('horodatage') != marqueur['horodatage']):
            raise lecture.Refus('SOURCE-INCOHERENTE')
    elif assignations:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    passe = registre.Registre(lignes[:rang])
    passe.assert_chaine()
    if (marqueur['assignations'] != attendu or etats.statut_courant(passe, iid) != 'planifiee'
            or etats.technicien_assigne(passe, iid) != equipe):
        raise lecture.Refus('SOURCE-INCOHERENTE')
    condition = APPROBATIONS.c.id == approbation_id
    tailles = cnx.execute(select(func.length(cast(APPROBATIONS.c.arguments, LargeBinary)),
        func.length(cast(APPROBATIONS.c.resultat, LargeBinary))).where(condition)).one_or_none()
    if tailles is None or any(t is None or t > lecture.MAX_SORTIE_OCTETS for t in tailles):
        raise lecture.Refus('APPROBATION-INDISPONIBLE')
    decision = cnx.execute(select(APPROBATIONS).where(condition)).mappings().one()
    args = dict(plan_id=marqueur['plan_id'], horodatage=marqueur['horodatage'], confirme_par=acteur)
    if (decision['departement'] != lecture.M4 or decision['outil'] != NOM or decision['niveau'] != 'N3'
            or decision['statut'] != 'executee' or decision['decide_par'] != acteur
            or decision['decide_role'] != 'admin'
            or json.loads(decision['arguments']) != args):
        raise lecture.Refus('APPROBATION-INCOHERENTE')
    reponse = json.loads(decision['resultat'])
    metier = reponse.get('resultat') if isinstance(reponse, dict) and reponse.get('ok') is True else None
    projection = cedule_tournees._resultat_application(marqueur, plan, False)
    if (not isinstance(metier, dict) or metier.get('accepte') is not True
            or metier.get('resultat') != dict(projection, horodatage_appareil=marqueur['horodatage'])):
        raise lecture.Refus('APPROBATION-INCOHERENTE')
    return projection


def appliquer(cnx, deps, session, lead_id, devis_id, plan_id, empreinte_attendue, mutation_id):
    with cnx.begin_nested():
        courant = preparer(cnx, deps, session, lead_id, devis_id, plan_id)
        if (type(empreinte_attendue) is not str or proposition.EMPREINTE.fullmatch(empreinte_attendue) is None
                or type(mutation_id) is not str or not 1 <= len(mutation_id) <= 200 or not mutation_id.strip()):
            raise lecture.Refus('ARGUMENTS')
        maintenant = datetime.now(UTC)
        meta = idempotence.Meta(mutation_id, 'console:' + session.utilisateur, maintenant.isoformat())
        intention = dict(lead_id=lead_id, devis_id=devis_id, plan_id=plan_id, empreinte=empreinte_attendue)
        condition = ((MUTATIONS_APPLIQUEES.c.appareil == meta.appareil)
                     & (MUTATIONS_APPLIQUEES.c.cle_idempotence == meta.cle))
        precedent = cnx.execute(select(MUTATIONS_APPLIQUEES.c.statut,
            func.length(cast(MUTATIONS_APPLIQUEES.c.reponse, LargeBinary))).where(condition)).one_or_none()
        if precedent is not None and (precedent[0] != 'ok' or precedent[1] > lecture.MAX_SORTIE_OCTETS):
            raise lecture.Refus('RECU-INDISPONIBLE')
        try:
            recu = idempotence.reclamer(cnx, meta, NOM, intention, maintenant)
        except idempotence.MutationConflit:
            raise lecture.Refus('MUTATION-CONFLIT') from None
        if recu.rejouee:
            r = recu.reponse
            if (not isinstance(r, dict) or set(r) != {'ok', 'application', 'approbation_id', 'rejoue', 'historique'}
                    or r.get('ok') is not True or r.get('rejoue') is not False or r.get('historique') is not False):
                raise lecture.Refus('RECU-INDISPONIBLE')
            application = _preuve_application(cnx, courant['revue'], r['approbation_id'], session.utilisateur)
            if application != r['application']:
                raise lecture.Refus('SOURCE-INCOHERENTE')
            return lecture._sortie(dict(ok=True, application=application, approbation_id=r['approbation_id'],
                                        rejoue=True, historique=True))
        if courant['empreinte'] != empreinte_attendue:
            raise lecture.Refus('SOURCE-MODIFIEE')
        if not courant['peut_appliquer']:
            raise lecture.Refus('APPLICATION-NON-PERMISE')
        dep = deps.get(lecture.M4)
        if dep is None or dep.module_outils != lecture.MODULES[lecture.M4]:
            raise lecture.Refus('SOURCE-INDISPONIBLE')
        outil = next((o for o in dep.charger_outils() if o.nom == NOM), None)
        if outil is None or outil.autonomie != Autonomie.T1 or outil.niveau_effectif != Niveau.N3:
            raise lecture.Refus('SOURCE-INDISPONIBLE')
        args = dict(plan_id=plan_id, horodatage=maintenant.isoformat(), confirme_par=session.utilisateur)
        with (contexte.appele_par_appareil(contexte.IdentiteAppelante(
                session.utilisateur, 'admin', source='console')),
              contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, maintenant, maintenant))):
            ident = approbations.creer_demande(cnx, lecture.M4, NOM, args, niveau=Niveau.N3,
                motif='Affectation interne explicitement demandée depuis la revue du plan; aucune date ni envoi.')
            decision = approbations.decider(cnx, ident, True, session.utilisateur, {NOM: outil}, deps, role='admin',
                motif='Validation humaine du plan interne; disponibilité globale et météo datée non confirmées.')
        if decision.get('statut') != 'executee' or not approbations.execution_reussie(decision.get('reponse', {})):
            raise lecture.Refus('APPLICATION-REFUSEE')
        application = _preuve_application(cnx, courant['revue'], ident, session.utilisateur)
        if idempotence.empreinte_arguments(proposition._profils()) != courant['profils_source']:
            raise lecture.Refus('SOURCE-MODIFIEE')
        personne = identite.personne_active(cnx, session.utilisateur)
        if personne is None or 'admin' not in personne.roles or session.expire <= datetime.now(UTC).timestamp():
            raise PermissionError('admin actif requis')
        resultat = lecture._sortie(dict(ok=True, application=application, approbation_id=ident,
                                       rejoue=False, historique=False))
        journaliser(cnx, session.utilisateur, 'console.action_interne', NOM,
                    dict(plan_id=plan_id, approbation_id=ident, mutation_id=mutation_id))
        idempotence.finaliser(cnx, meta, resultat)
        return resultat
