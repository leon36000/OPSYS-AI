"""Lecture privée M3→M5, calcul propriétaire et sources consommées, aucun effet financier."""
import copy
import hashlib
import importlib
import json
import uuid

from m5_financecore import encodage
from sqlalchemy import LargeBinary, cast, func, select

from .. import contexte
from ..outils import Autonomie, executer
from ..stockage import codec
from ..stockage.maillons import EcritureConcurrente, copier_maillons_avec_metadonnees
from ..stockage.schema import EVENEMENTS_RECUS, JOURNAL, OPSYS_INSTANCE
from . import memoire_chantier as autorite
from . import preparation_chantier as lecture

M5, M6 = 'm05-financecore', 'm06-material-control'
CATALOGUE = ((lecture.M2, 'principal'), (lecture.M3, 'devis'), (lecture.M3, 'principal'),
    *((M5, nom) for nom in ('devis_recus', 'wct_recus', 'variance_recue', 'factures', 'rentabilite')),
    (M6, 'livre_prix'))
MAX_CONFIGURATION = 1048576


def _capture(cnx):
    # Toutes les bornes avant le premier décodage des sources financières.
    for dep, nom in CATALOGUE:
        lecture._borner(cnx, dep, nom)
    return {(dep, nom): copier_maillons_avec_metadonnees(cnx, departement=dep, registre=nom)
            for dep, nom in CATALOGUE}


def _references(captures):
    return {dep + '/' + nom: s.empreinte_snapshot_calculee for (dep, nom), s in captures.items()}


def _lignes(captures, dep, nom):
    return [ligne.maillon for ligne in captures[(dep, nom)].lignes]


def _historique_v3(cnx, captures, devis_id):
    """Historique admin borné ; les preuves anciennes ne sont pas dites courantes."""
    traces = [ligne for ligne in captures[(M5, 'rentabilite')].lignes
              if isinstance(ligne.maillon, dict) and ligne.maillon.get('devis_id') == devis_id
              and 'provenance_v3' in ligne.maillon]
    if traces:
        lecture._borner(cnx, M5, 'rentabilite_mutations_v3')
        from m5_financecore import outils as m5

        recus = list(m5.stockage.maillons(M5, 'rentabilite_mutations_v3'))
        if len(recus) > 1000 or any(not isinstance(r, dict) for r in recus):
            raise lecture.Refus('RECU-INVALIDE')
    else:
        recus = []
    if any(not isinstance(r.get('mutation_id'), str) for r in recus) or len(
            {r['mutation_id'] for r in recus}) != len(recus):
        raise lecture.Refus('RECU-INVALIDE')
    candidats = list(reversed(traces))[:10]
    par_rang = {ligne.rang: [r for r in recus if r.get('trace_rang') == ligne.rang] for ligne in candidats}
    if any(not rs or len(rs) > 32 for rs in par_rang.values()):
        raise lecture.Refus('RECU-INVALIDE')
    choisis = [r for rs in par_rang.values() for r in rs]
    audits = _audits_recus(cnx, choisis)
    retenues = []
    for ligne in candidats:
        trace = ligne.maillon
        for recu in par_rang[ligne.rang]:
            _verifier_recu_trace(cnx, recu, snapshot=captures[(M5, 'rentabilite')], audits=audits)
        rentabilite = trace.get('rentabilite')
        if (not isinstance(trace.get('provenance_v3'), dict) or not isinstance(rentabilite, dict)
                or not isinstance(rentabilite.get('cout_reel'), dict)
                or not isinstance(rentabilite['cout_reel'].get('main_d_oeuvre'), dict)):
            raise lecture.Refus('SOURCE-INCOHERENTE')
        entree = lecture._sortie({
            'version_entrees': trace.get('version_entrees'), 'horodatage': trace.get('horodatage'),
            'verdict': trace.get('verdict'), 'provenance': trace['provenance_v3'],
            'lignes_main_oeuvre': rentabilite['cout_reel']['main_d_oeuvre'].get('lignes', []),
        })
        candidats = [*retenues, entree]
        if len(candidats) > 10 or len(json.dumps(candidats, ensure_ascii=False).encode('utf-8')) > 24000:
            break
        retenues.append(entree)
    return {'nombre': len(traces), 'affichees': len(retenues), 'reste': len(traces) - len(retenues),
            'diffusion': 'non_publiee_au_bus', 'traces': retenues}



def _historique_service(cnx, captures, devis_id, session):
    """Historique service : preuve SQL distincte d'un reçu console humain."""
    traces = [ligne for ligne in captures[(M5, 'rentabilite')].lignes
              if isinstance(ligne.maillon, dict) and ligne.maillon.get('devis_id') == devis_id
              and 'provenance_service_v1' in ligne.maillon]
    if not traces:
        return {'nombre': 0, 'traces': [], 'reste': 0}
    lecture._borner(cnx, M5, 'rentabilite_service_v1')
    from m5_financecore import outils as m5
    recus = list(m5.stockage.maillons(M5, 'rentabilite_service_v1'))
    if len(recus) > 1000 or any(not isinstance(r, dict) for r in recus):
        raise lecture.Refus('RECU-SERVICE-INVALIDE')
    instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one()
    resultat = []
    for ligne in list(reversed(traces))[:10]:
        trace = ligne.maillon
        correspondants = [r for r in recus if r.get('trace_rang') == ligne.rang]
        if len(correspondants) != 1:
            raise lecture.Refus('RECU-SERVICE-INVALIDE')
        recu = correspondants[0]
        noms = {'type', 'instance_id', 'wct_id', 'reference_core', 'trace_rang', 'trace_empreinte', 'empreinte'}
        reference = recu.get('reference_core')
        if (set(recu) != noms or recu['type'] != 'publication_service_v1'
                or type(recu['trace_rang']) is not int or recu['trace_rang'] < 0
                or recu['instance_id'] != instance or recu['wct_id'] != trace.get('wct_id')
                or type(reference) is not dict
                or set(reference) != {'schema', 'id', 'instance_id', 'evenement_id', 'operation', 'revision'}
                or reference.get('schema') != 'opsys.core.m4.audit-usage.v1'
                or reference.get('operation') != 'm4.verifier_v3'
                or type(reference.get('id')) is not int or reference['id'] <= 0
                or type(reference.get('revision')) is not int or reference['revision'] <= 0
                or reference.get('instance_id') != instance or reference.get('evenement_id') != recu['wct_id']
                or recu['trace_empreinte'] != encodage.empreinte(trace)
                or recu['empreinte'] != encodage.empreinte('m5.publication_service.v1',
                    {k: v for k, v in recu.items() if k != 'empreinte'})):
            raise lecture.Refus('RECU-SERVICE-INVALIDE')
        provenance = trace['provenance_service_v1']
        if (not isinstance(provenance, dict) or provenance.get('wct_id') != recu['wct_id']
                or provenance.get('instance_id') != instance):
            raise lecture.Refus('RECU-SERVICE-INVALIDE')
        from opsys import service_capability, service_history_m4
        try:
            verification = service_history_m4.lire_historique(cnx, session, recu)
        except service_capability.RefusAutorite:
            raise lecture.Refus('RECU-SERVICE-INVALIDE') from None
        resultat.append(lecture._sortie({'version_entrees': trace.get('version_entrees'),
            'horodatage': trace.get('horodatage'), 'verdict': trace.get('verdict'),
            'provenance': provenance, **verification}))
    return {'nombre': len(traces), 'traces': resultat, 'reste': len(traces)-len(resultat)}

def _configuration(m5):
    try:
        with m5._MANIFESTE.open('rb') as f:
            raw = f.read(MAX_CONFIGURATION + 1)
    except OSError:
        return None, None
    if len(raw) > MAX_CONFIGURATION:
        raise lecture.Refus('CONFIGURATION-TROP-VOLUMINEUSE')
    return hashlib.sha256(raw).hexdigest(), raw


def _ancre(cnx, deps, session, lead_id, devis_id):
    from m3_estimation import devis_durable, estime_vs_reel
    from m3_estimation import outils as m3

    lecture._appel(deps, session.utilisateur, lecture.M2, 'm2_trouver_client_de_lead', dict(lead_id=lead_id))
    devis, verdict = devis_durable.lire_devis(m3.registre_devis_production(), devis_id)
    if verdict is not None or devis.get('lead_id') != lead_id:
        raise lecture.Refus('INTROUVABLE')
    if devis.get('statut') != 'accepte':
        raise lecture.Refus('DEVIS-NON-ACCEPTE')
    charge = lecture._publication(cnx, 'm3-devis-accepte-' + devis_id, 'm3.devis_accepte', lecture.M3)
    if charge is None:
        return None
    attendu = devis_durable.charge_evenement_devis_accepte(devis)
    if m3._source_estimation_exacte(devis.get('estimation_source_hash'), devis_id, lead_id) is not None:
        attendu = estime_vs_reel.avec_duree_estimee(
            attendu, devis_id, m3.registre_devis_production(), m3.registre_production().lire())
    if charge != attendu:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    return charge


def _reception(cnx, devis_id):
    condition = ((EVENEMENTS_RECUS.c.evenement_id == 'm3-devis-accepte-' + devis_id)
                 & (EVENEMENTS_RECUS.c.consommateur == M5))
    taille = cnx.execute(select(func.length(cast(EVENEMENTS_RECUS.c.resultat, LargeBinary)))
                        .where(condition)).scalar_one_or_none()
    if taille is not None and taille > lecture.MAX_SORTIE_OCTETS:
        raise lecture.Refus('SOURCE-TROP-VOLUMINEUSE')
    ligne = cnx.execute(select(EVENEMENTS_RECUS).where(condition)).mappings().one_or_none()
    if ligne is None:
        return 'EN_ATTENTE', None
    reference = encodage.empreinte(dict(ligne))
    if ligne['statut'] in ('echec', 'quarantaine'):
        return ('ECHEC_LIVRAISON' if ligne['statut'] == 'echec' else 'QUARANTAINE'), reference
    resultat = codec.decoder(ligne['resultat']) if ligne['resultat'] is not None else None
    if (ligne['statut'] != 'traite' or not isinstance(resultat, dict)
            or resultat.get('traite') is not True or resultat.get('devis_id') != devis_id):
        raise lecture.Refus('SOURCE-INCOHERENTE')
    return 'TRAITE', reference


def _m5(deps, session, devis_id):
    dep = deps.get(M5)
    if dep is None or dep.module_outils != 'm5_financecore.outils':
        raise lecture.Refus('SOURCE-INDISPONIBLE')
    outil = next((o for o in dep.charger_outils() if o.nom == 'm5_lire_rentabilite_chantier'), None)
    if outil is None or outil.autonomie != Autonomie.T0:
        raise lecture.Refus('SOURCE-INDISPONIBLE')
    with (contexte.appele_par_appareil(contexte.IdentiteAppelante(session.utilisateur, 'admin', source='console')),
          contexte.appeler_en_tant_que(M5, origine='console')):
        r = executer(outil, dict(devis_id=devis_id, limite=1))
    res = r.get('resultat') if r.get('ok') is True else None
    if not isinstance(res, dict) or res.get('accepte') is not True or not isinstance(res.get('resultat'), dict):
        raise lecture.Refus('SOURCE-INDISPONIBLE')
    return lecture._sortie(res['resultat'])


def _wct_publie_et_recu(cnx, recu):
    """Lie une charge publiée par M4 à la réception M5 et à son empreinte complète."""
    ident = recu.get('wct_id')
    if not isinstance(ident, str) or not ident:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    charge = lecture._publication(cnx, ident, 'm4.travaux_termines', 'm04-field-ops')
    if charge is None:
        return None
    condition = ((EVENEMENTS_RECUS.c.evenement_id == ident) & (EVENEMENTS_RECUS.c.consommateur == M5))
    taille = cnx.execute(select(func.length(cast(EVENEMENTS_RECUS.c.resultat, LargeBinary)))
                        .where(condition)).scalar_one_or_none()
    if taille is not None and taille > lecture.MAX_SORTIE_OCTETS:
        raise lecture.Refus('SOURCE-TROP-VOLUMINEUSE')
    ligne = cnx.execute(select(EVENEMENTS_RECUS).where(condition)).mappings().one_or_none()
    if ligne is None or ligne['statut'] != 'traite':
        return None
    resultat = codec.decoder(ligne['resultat']) if ligne['resultat'] is not None else None
    if (not isinstance(resultat, dict) or resultat.get('traite') is not True
            or (recu.get('devis_id') is None and resultat.get('wct_id') != ident)
            or (recu.get('devis_id') is not None and resultat.get('devis_id') != recu['devis_id'])
            or any(recu.get(k) != charge.get(k) for k in
                   ('wct_id', 'intervention_id', 'devis_id', 'horodatage_completion', 'duree_reelle_minutes'))):
        raise lecture.Refus('SOURCE-INCOHERENTE')
    if recu.get('empreinte_charge') is None:
        return 'HISTORIQUE', None
    if recu['empreinte_charge'] != encodage.empreinte(charge):
        raise lecture.Refus('SOURCE-INCOHERENTE')
    return charge, encodage.empreinte(dict(ligne))


def _ventilation_m4(cnx, session, recu, lead_id, *, _pieces=False):
    """Volet privé complémentaire : pas de mutation et pas de présence individuelle inférée."""
    from m5_financecore import cout_reel
    from m5_financecore import outils as m5

    autorite._admin(cnx, session)
    try:
        m4_v2 = importlib.import_module('m4_field_ops.temps_certifies_v2')
        try:
            m4 = importlib.import_module('m4_field_ops.temps_certifies_v3')
        except ModuleNotFoundError as exc:
            if exc.name != 'm4_field_ops.temps_certifies_v3':
                raise
            m4 = m4_v2
    except ModuleNotFoundError as exc:
        if exc.name == 'm4_field_ops.temps_certifies_v2':
            return {'statut': 'PRODUCTEUR_INDISPONIBLE'}
        raise lecture.Refus('VENTILATION-INDISPONIBLE') from None
    source_bus = _wct_publie_et_recu(cnx, recu)
    if source_bus is None:
        return {'statut': 'PUBLICATION_OU_RECEPTION_ABSENTE'}
    charge, recu_bus = source_bus
    if charge == 'HISTORIQUE':
        return {'statut': 'RECU_HISTORIQUE_NON_VERIFIABLE'}
    if not isinstance(lead_id, str) or charge.get('lead_id') != lead_id:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    identite = contexte.IdentiteAppelante(session.utilisateur, 'admin', source='console')
    try:
        with (contexte.appele_par_appareil(identite),
              contexte.appeler_en_tant_que('m04-field-ops', origine='console')):
            projection = m4.projeter(cnx, charge['intervention_id'], charge['wct_id'])
        with (contexte.appele_par_appareil(identite), contexte.appeler_en_tant_que(M5, origine='console')):
            tarifs = m5._lire_tarifs_equipes()
        p = projection['projection']
        if p['lead_id'] != lead_id:
            raise lecture.Refus('SOURCE-INCOHERENTE')
        instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one()
        if instance != p['instance_id']:
            raise lecture.Refus('INSTANCE-NON-QUALIFIEE')
        with (contexte.appele_par_appareil(identite),
              contexte.appeler_en_tant_que('m04-field-ops', origine='console')):
            relecture = m4.projeter(cnx, charge['intervention_id'], charge['wct_id'],
                                    source_attendue=projection['source'])
        with (contexte.appele_par_appareil(identite), contexte.appeler_en_tant_que(M5, origine='console')):
            tarifs_fin = m5._lire_tarifs_equipes()
        instance_fin = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one()
        if (relecture != projection or instance_fin != instance or tarifs_fin['source'] != tarifs['source']
                or _wct_publie_et_recu(cnx, recu) != source_bus):
            raise lecture.Refus('SOURCE-MODIFIEE')
        main = cout_reel._main_d_oeuvre_ventilee(charge, p, tarifs['lignes'], p['instance_id'],
                                                 projection['source'], p['sources'], relecture['source'])
        if main.get('projection_empreinte') != p.get('empreinte') or not main.get('projection_empreinte'):
            raise lecture.Refus('SOURCE-INCOHERENTE')
        autorite._admin(cnx, session)
    except lecture.Refus:
        raise
    except (m4_v2.Refus, ValueError, KeyError, TypeError, PermissionError):
        raise lecture.Refus('VENTILATION-INDISPONIBLE') from None
    equipes_inconnues = sum(v['equipe_pointee']['statut'] != 'identifiee' for v in p['visites'])
    resultat = {
        'statut': 'COMPLET' if main['statut'] == 'complet' else 'INCOMPLET',
        'wct_id': charge['wct_id'],
        'minutes_travail': p['totaux']['travail'],
        'minutes_pause': p['totaux']['pause'],
        'minutes_deplacement': p['totaux']['deplacement'],
        'cout_main_oeuvre': main['cout'],
        'cout_main_oeuvre_connu': main.get('cout_connu'),
        'equipes_indeterminees': equipes_inconnues,
        'revue': p['revue_chantier']['statut'],
        'manque': main['manque'],
        'empreinte_projection': p['empreinte'],
        'source': encodage.empreinte(projection['source'], tarifs['source'], recu_bus, encodage.empreinte(charge)),
    }
    if _pieces:
        return resultat, projection, tarifs, charge
    return resultat


def lire(cnx, deps, session, lead_id, devis_id):
    from m5_financecore import devis_recus
    from m5_financecore import outils as m5

    autorite._admin(cnx, session)
    if any(type(i) is not str or lecture.IDENTIFIANT.fullmatch(i) is None or i in {'.', '..'}
           for i in (lead_id, devis_id)):
        raise lecture.Refus('INTROUVABLE')
    captures = _capture(cnx)
    refs, config = _references(captures), _configuration(m5)
    charge = _ancre(cnx, deps, session, lead_id, devis_id)
    statut, recu = _reception(cnx, devis_id) if charge is not None else ('NON_PUBLIE', None)
    resultat = dict(lead_id=lead_id, devis_id=devis_id, reception_m5=statut, chantier=None,
                    source_calculee=None, ventilation_m4={'statut': 'WCT_ABSENT'},
                    historique_v3=_historique_v3(cnx, captures, devis_id),
                    historique_service=_historique_service(cnx, captures, devis_id, session))
    recu_wct = None
    recus = [m for m in _lignes(captures, M5, 'devis_recus') if m.get('devis_id') == devis_id]
    if statut != 'TRAITE':
        if recus:
            raise lecture.Refus('SOURCE-INCOHERENTE')
    else:
        attendu = devis_recus.construire(**{k: charge[k] for k in ('devis_id', 'lead_id', 'chantier_id', 'lignes',
            'prix_total', 'horodatage_acceptation', 'cout_total', 'taux_marge')})
        if recus != [attendu]:
            raise lecture.Refus('SOURCE-INCOHERENTE')
        try:
            sources = m5._sources_cout_reel_depuis(dict(
                devis=_lignes(captures, M5, 'devis_recus'), wct=_lignes(captures, M5, 'wct_recus'),
                variance=_lignes(captures, M5, 'variance_recue'),
                factures=m5.registre_module.Registre(maillons=_lignes(captures, M5, 'factures')),
                rentabilite=_lignes(captures, M5, 'rentabilite'),
                livre=tuple(_lignes(captures, M6, 'livre_prix')), taux=m5._taux_horaire_depuis_octets(config[1])))
        except (ValueError, KeyError, TypeError):
            raise lecture.Refus('SOURCE-INCOHERENTE') from None
        etat = m5._etat_chantier(devis_id, sources)
        attendu_vue = lecture._sortie(m5._vue_chantier(etat, sources, True, detail=True))
        vue = _m5(deps, session, devis_id)
        if (vue.get('mention') != m5.analyse.MENTION_ANALYSE_PREPARATOIRE or vue.get('role') != 'admin'
                or (vue.get('nombre'), vue.get('affichees'), vue.get('reste')) != (1, 1, 0)
                or vue.get('chantiers') != [attendu_vue]):
            raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
        resultat['chantier'] = attendu_vue
        if etat.get('statut') == 'calculee':
            wct_id = etat['rentabilite']['wct_id']
            correspondants = [r for r in sources['wct'] if r.get('wct_id') == wct_id]
            if len(correspondants) != 1:
                raise lecture.Refus('SOURCE-INCOHERENTE')
            wcts_devis = [r for r in sources['wct'] if r.get('devis_id') == devis_id]
            if len(wcts_devis) > 1:
                resultat['ventilation_m4'] = {'statut': 'WCT_MULTIPLES'}
            elif (deps.get(lecture.M4) is None
                    or deps[lecture.M4].module_outils != 'm4_field_ops.outils'):
                resultat['ventilation_m4'] = {'statut': 'PRODUCTEUR_INDISPONIBLE'}
            else:
                recu_wct = correspondants[0]
                resultat['ventilation_m4'] = _ventilation_m4(cnx, session, recu_wct, lead_id)
                if resultat['ventilation_m4'].get('statut') == 'COMPLET':
                    volet, projection, tarifs, charge_wct = _ventilation_m4(
                        cnx, session, recu_wct, lead_id, _pieces=True)
                    if volet != resultat['ventilation_m4']:
                        raise lecture.Refus('SOURCE-MODIFIEE')
                    etat_verifie = m5._etat_chantier(devis_id, sources, ventilation_verifiee={
                        'projection': projection, 'tarifs': tarifs, 'charge': charge_wct})
                    resultat['chantier'] = lecture._sortie(m5._vue_chantier(etat_verifie, sources, True, detail=True))
    autorite._admin(cnx, session)
    if (_references(_capture(cnx)) != refs or _configuration(m5) != config
            or _ancre(cnx, deps, session, lead_id, devis_id) != charge
            or (charge is not None and _reception(cnx, devis_id) != (statut, recu))):
        raise lecture.Refus('SOURCE-MODIFIEE')
    if recu_wct is not None and _ventilation_m4(cnx, session, recu_wct, lead_id) != resultat['ventilation_m4']:
        raise lecture.Refus('SOURCE-MODIFIEE')
    resultat['source_calculee'] = encodage.empreinte(dict(registres=refs, configuration=config[0],
        acceptation=charge, reception=recu, ventilation=resultat['ventilation_m4']))
    autorite._admin(cnx, session)
    return lecture._sortie(m5.analyse.avec_mention(resultat))


def _audits_recus(cnx, recus):
    if not recus:
        return {}
    ids = [r['mutation_id'] for r in recus]
    if len(ids) != len(set(ids)) or len(ids) > 320:
        raise lecture.Refus('RECU-INVALIDE')
    condition = ((JOURNAL.c.action == 'm5.ventilation_v3_tracee') & JOURNAL.c.cible.in_(ids))
    taille = func.length(cast(JOURNAL.c.details, LargeBinary))
    nombre, total, maximum = cnx.execute(select(
        func.count(), func.coalesce(func.sum(taille), 0), func.coalesce(func.max(taille), 0),
    ).where(condition)).one()
    if nombre != len(ids) or total > 8 * 1024 * 1024 or maximum > 65536:
        raise lecture.Refus('RECU-INVALIDE')
    lignes = cnx.execute(select(JOURNAL.c.cible, JOURNAL.c.par, JOURNAL.c.details).where(condition)).all()
    resultat = {ligne.cible: (ligne.par, ligne.details) for ligne in lignes}
    if len(resultat) != len(ids):
        raise lecture.Refus('RECU-INVALIDE')
    return resultat


def _verifier_recu_trace(cnx, recu, *, snapshot=None, audits=None):
    champs = {'mutation_id', 'intention', 'version_entrees', 'trace_rang', 'trace_empreinte', 'operation'}
    if (not isinstance(recu, dict) or set(recu) != champs or not isinstance(recu['intention'], dict)
            or type(recu['trace_rang']) is not int or recu['trace_rang'] < 0
            or recu['operation'] != 'historique_sans_publication'):
        raise lecture.Refus('RECU-INVALIDE')
    if snapshot is None:
        lecture._borner(cnx, M5, 'rentabilite')
        snapshot = copier_maillons_avec_metadonnees(cnx, departement=M5, registre='rentabilite')
    lignes = [x.maillon for x in snapshot.lignes if x.rang == recu['trace_rang']]
    if len(lignes) != 1:
        raise lecture.Refus('RECU-INVALIDE')
    trace = lignes[0]
    if not isinstance(trace, dict) or not isinstance(trace.get('rentabilite'), dict):
        raise lecture.Refus('RECU-INVALIDE')
    provenance = trace.get('provenance_v3')
    instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one()
    if (not isinstance(provenance, dict) or provenance.get('instance_id') != instance
            or trace.get('devis_id') != recu['intention'].get('devis_id')
            or trace.get('version_entrees') != recu['version_entrees']
            or encodage.empreinte(trace) != recu['trace_empreinte']):
        raise lecture.Refus('RECU-INVALIDE')
    audit = (_audits_recus(cnx, [recu]) if audits is None else audits).get(recu['mutation_id'])
    try:
        details = json.loads(audit[1]) if audit is not None else None
    except (ValueError, TypeError):
        raise lecture.Refus('RECU-INVALIDE') from None
    if audit is None or audit[0] != recu['intention'].get('auteur') or details != {'recu': recu}:
        raise lecture.Refus('RECU-INVALIDE')


def tracer_ventilation(cnx, deps, session, lead_id, devis_id, source_attendue, mutation_id):
    """Trace une ventilation obtenue à nouveau des propriétaires sous autorité admin.

    Le client ne fournit ni faits ni tarifs. Toute divergence ou révocation annule
    la trace et son événement dans le même savepoint.
    """
    from m5_financecore import devis_recus
    from m5_financecore import outils as m5

    autorite._admin(cnx, session)
    if cnx is not m5.stockage.connexion_courante() or not cnx.in_transaction():
        raise lecture.Refus('INSTANCE-NON-QUALIFIEE')
    if (not isinstance(mutation_id, str) or len(mutation_id) != 32
            or any(c not in '0123456789abcdef' for c in mutation_id)):
        raise lecture.Refus('MUTATION-INVALIDE')
    nom_mutations = 'rentabilite_mutations_v3'
    lecture._borner(cnx, M5, nom_mutations)
    registre_mutations = m5.stockage.maillons(M5, nom_mutations)
    mutations = list(registre_mutations)
    if (any(not isinstance(m, dict) or not isinstance(m.get('mutation_id'), str) for m in mutations)
            or len({m['mutation_id'] for m in mutations}) != len(mutations)):
        raise lecture.Refus('RECU-INVALIDE')
    intention = dict(lead_id=lead_id, devis_id=devis_id, source_attendue=source_attendue,
                     auteur=session.utilisateur)
    existantes = [m for m in mutations if m.get('mutation_id') == mutation_id]
    if existantes:
        if len(existantes) != 1 or existantes[0].get('intention') != intention:
            raise lecture.Refus('MUTATION-CONFLIT')
        _verifier_recu_trace(cnx, existantes[0])
        autorite._admin(cnx, session)
        return {'statut': 'deja_tracee'}
    if len(mutations) >= 1000:
        raise lecture.Refus('MUTATIONS-TROP-NOMBREUSES')
    vue = lire(cnx, deps, session, lead_id, devis_id)
    if not isinstance(source_attendue, str) or source_attendue != vue['source_calculee']:
        raise lecture.Refus('SOURCE-PERIMEE')
    if vue['ventilation_m4'].get('statut') != 'COMPLET':
        raise lecture.Refus('VENTILATION-INCOMPLETE')
    captures = _capture(cnx)
    refs = _references(captures)
    config = _configuration(m5)
    acceptation = _ancre(cnx, deps, session, lead_id, devis_id)
    reception = _reception(cnx, devis_id)
    wct_id = vue['ventilation_m4']['wct_id']
    recus = [m for m in _lignes(captures, M5, 'wct_recus') if m.get('devis_id') == devis_id]
    if len(recus) != 1 or recus[0].get('wct_id') != wct_id:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    volet, projection, tarifs, charge = _ventilation_m4(cnx, session, recus[0], lead_id, _pieces=True)
    if lecture._sortie(volet) != vue['ventilation_m4']:
        raise lecture.Refus('SOURCE-MODIFIEE')
    sources = m5._sources_cout_reel_depuis(dict(
        devis=_lignes(captures, M5, 'devis_recus'), wct=_lignes(captures, M5, 'wct_recus'),
        variance=_lignes(captures, M5, 'variance_recue'),
        factures=m5.registre_module.Registre(maillons=_lignes(captures, M5, 'factures')),
        rentabilite=_lignes(captures, M5, 'rentabilite'),
        livre=tuple(_lignes(captures, M6, 'livre_prix')), taux=m5._taux_horaire_depuis_octets(config[1])))
    devis = devis_recus.pour_devis_id(devis_id, sources['devis'])
    if devis is None:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    p = projection['projection']
    etat = m5._etat_chantier(devis_id, sources, ventilation_verifiee={
        'projection': projection, 'tarifs': tarifs, 'charge': charge})
    rentabilite = etat['rentabilite']
    cout = rentabilite['cout_reel']
    if cout['main_d_oeuvre']['cout'] != volet['cout_main_oeuvre']:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    derniere = sources['traces'].get(devis_id)
    if derniere is not None and derniere.get('version_entrees') == rentabilite['version_entrees']:
        if lire(cnx, deps, session, lead_id, devis_id) != vue:
            raise lecture.Refus('SOURCE-MODIFIEE')
        return {'statut': 'deja_tracee'}
    with cnx.begin_nested():
        if lire(cnx, deps, session, lead_id, devis_id) != vue:
            raise lecture.Refus('SOURCE-MODIFIEE')
        provenance = {
            'version': p['version'], 'instance_id': p['instance_id'], 'wct_id': wct_id,
            'source_m4': projection['source'], 'empreinte_projection': p['empreinte'],
            'wct': p['wct'], 'empreinte_charge_wct': encodage.empreinte(charge),
            'sources_m4': p['sources'], 'source_tarifs': tarifs['source'],
            'preuves': [{'visite_id': v['visite_id'], 'equipe_id': v['equipe_pointee']['identifiant'],
                         'pointages': v['equipe_pointee']['preuves']} for v in p['visites']],
        }
        trace = m5._consigner_rentabilite(
            rentabilite, sources['nombre_de_traces'].get(devis_id, 0) + 1, charge['horodatage_completion'],
            rang_attendu=len(captures[(M5, 'rentabilite')].lignes), provenance=provenance, publier=False)
        autorite._admin(cnx, session)
        captures_fin = _capture(cnx)
        refs_fin = _references(captures_fin)
        attendu_traces = _lignes(captures, M5, 'rentabilite') + [trace]
        if (any(refs_fin[k] != v for k, v in refs.items() if k != M5 + '/rentabilite')
                or _lignes(captures_fin, M5, 'rentabilite') != attendu_traces
                or _configuration(m5) != config or _ancre(cnx, deps, session, lead_id, devis_id) != acceptation
                or _reception(cnx, devis_id) != reception
                or _ventilation_m4(cnx, session, recus[0], lead_id) != volet):
            raise lecture.Refus('SOURCE-MODIFIEE')
        traces_fin = [x for x in captures_fin[(M5, 'rentabilite')].lignes
                      if x.maillon.get('devis_id') == devis_id]
        if not traces_fin:
            raise lecture.Refus('SOURCE-INCOHERENTE')
        ligne_trace = traces_fin[-1]
        if sum(m.get('trace_rang') == ligne_trace.rang for m in mutations) >= 32:
            raise lecture.Refus('MUTATIONS-TROP-NOMBREUSES')
        recu = {'mutation_id': mutation_id, 'intention': intention, 'version_entrees': rentabilite['version_entrees'],
                'trace_rang': ligne_trace.rang, 'trace_empreinte': encodage.empreinte(ligne_trace.maillon),
                'operation': 'historique_sans_publication'}
        registre_mutations.append(recu, rang_attendu=len(mutations))
        from ..etat import journaliser

        journaliser(cnx, session.utilisateur, 'm5.ventilation_v3_tracee', mutation_id, {'recu': recu})
        _verifier_recu_trace(cnx, recu)
        captures_finales = _capture(cnx)
        refs_finales = _references(captures_finales)
        if (list(registre_mutations) != mutations + [recu]
                or any(refs_finales[k] != v for k, v in refs.items() if k != M5 + '/rentabilite')
                or _lignes(captures_finales, M5, 'rentabilite') != attendu_traces
                or _configuration(m5) != config or _ancre(cnx, deps, session, lead_id, devis_id) != acceptation
                or _reception(cnx, devis_id) != reception
                or _ventilation_m4(cnx, session, recus[0], lead_id) != volet):
            raise lecture.Refus('SOURCE-MODIFIEE')
        autorite._admin(cnx, session)
    return {'statut': 'tracee'}


def contenu(vue, prefixe, csrf=None):
    from . import pages

    vue = _vue_sans_zero_invente(vue)

    def valeur(v):
        return 'Non disponible' if v is None else pages.e(v)

    base = (f'{prefixe}/crm/lead/{pages._segment(vue["lead_id"])}/soumissions/'
            f'{pages._segment(vue["devis_id"])}')
    export = base + '/couts-travaux/export.json'
    corps = (f'<p><a href="{pages.e(base)}">Retour à la soumission</a></p><section><h2>Coûts des travaux</h2>'
        f'<p><a href="{pages.e(export)}">Télécharger les coûts et leurs sources (JSON)</a></p>'
        '<p>Source : M5, devis accepté M3, temps et matériaux reçus par M5. '
        'Prix et taux actuels, sans attestation de dépense payée ou de coût historiquement figé.</p>'
        f'<p>{pages.e(vue["mention"])}</p>'
        '<p>Les extras et dépenses hors du contrat actuel M5 ne sont pas inventés.</p>')
    etat = vue['chantier']
    if etat is None:
        receptions = {'NON_PUBLIE': 'Acceptation sans publication vers M5', 'EN_ATTENTE': 'Réception M5 en attente',
            'QUARANTAINE': 'Réception M5 en quarantaine', 'ECHEC_LIVRAISON': 'Réception M5 en échec'}
        return corps + f'<p>{pages.e(receptions[vue["reception_m5"]])}</p></section>'
    if etat['statut'] != 'calculee':
        attentes = {'en_attente_travaux_termines': 'En attente des travaux terminés',
                    'en_attente_devis_accepte': 'En attente du devis accepté dans M5'}
        return corps + f'<p>{pages.e(attentes[etat["statut"]])}</p></section>'
    r = etat['rentabilite']
    cout, materiaux = r['cout_reel'], r['cout_reel']['materiaux']
    corps += (f'<h3>{"Coût complet selon M5" if cout["complet"] else "Coût partiel"}</h3>'
              f'<p>Devise : {valeur(cout["devise"])} · Facture : {valeur(r["statut_facture"])}</p>')
    if not r['prix_definitif']:
        corps += '<p role="alert">Prix non définitif : facture absente ou brouillon selon M5.</p>'
    corps += ('<p>Trace de calcul locale à jour</p>' if etat['trace']['a_jour'] else
              '<p role="alert">Trace de calcul antérieure : le calcul actuel n’a pas réécrit cette trace.</p>')
    chiffres = [('Coût prévu du devis', r['cout_prevu']), ('Prix prévu du devis', r['prix_prevu']),
        ('Coût total calculé', cout['cout_total']), ('Coût total connu', cout['cout_total_connu']),
        ('Matériaux connus', materiaux['cout_connu']), ('Main-d’œuvre', cout['main_d_oeuvre']['cout']),
        ('Prix de facture', r['prix_facture']), ('Marge prévue', r['marge_prevue']),
        ('Marge réelle calculée', r['marge_reelle']), ('Écart de marge', r['ecart_marge'])]
    corps += '<table><thead><tr><th>Mesure</th><th>Valeur M5</th></tr></thead><tbody>'
    corps += ''.join(f'<tr><th>{pages.e(nom)}</th><td>{valeur(v)}</td></tr>' for nom, v in chiffres)
    corps += '</tbody></table><h3>Matériaux reçus dans le calcul M5</h3>'
    corps += '<table><thead><tr><th>Matériau</th><th>Quantité réelle</th><th>Unité</th>'
    corps += '<th>Prix unitaire</th><th>Coût</th><th>État M5</th></tr></thead><tbody>'
    for ligne in materiaux['lignes']:
        corps += '<tr>' + ''.join(f'<td>{valeur(ligne[cle])}</td>' for cle in
            ('materiau', 'quantite_reelle', 'unite', 'prix_unitaire', 'cout', 'statut')) + '</tr>'
    corps += '</tbody></table><h3>Sources des prix M6 utilisées par M5</h3><ul>'
    for ligne in materiaux['lignes']:
        for source in ligne['sources_prix']:
            corps += '<li>' + ' · '.join(valeur(source.get(k)) for k in
                ('fournisseur_id', 'date_effet', 'source_document')) + '</li>'
    corps += '</ul><h3>Main-d’œuvre M5</h3>'
    mo = cout['main_d_oeuvre']
    corps += (f'<p>État : {valeur(mo["statut"])} · Minutes : {valeur(mo["minutes"])} · '
              f'Taux horaire : {valeur(mo["taux_horaire"])}</p><h3>Manques M5</h3><ul>')
    for manque in cout['manque'] + r['manque']:
        corps += f'<li>{pages.e(manque.get("code"))} : {pages.e(manque.get("detail"))}</li>'
    corps += '</ul><h3>Hypothèses M5</h3><ul>'
    corps += ''.join(f'<li>{pages.e(h)}</li>' for h in cout['hypotheses'])
    ventilation = vue.get('ventilation_m4', {'statut': 'PRODUCTEUR_INDISPONIBLE'})
    messages = {
        'PRODUCTEUR_INDISPONIBLE': 'Ventilation M4 indisponible : producteur non installé.',
        'PUBLICATION_OU_RECEPTION_ABSENTE': 'Ventilation M4 indisponible : publication ou réception non vérifiée.',
        'RECU_HISTORIQUE_NON_VERIFIABLE': 'Ventilation M4 indisponible : reçu historique sans empreinte complète.',
        'WCT_ABSENT': 'Ventilation M4 en attente du WCT.',
        'WCT_MULTIPLES': 'Ventilation indisponible : plusieurs WCT pour ce devis.',
    }
    corps += '</ul><h3>Ventilation M4 complémentaire</h3>'
    if ventilation['statut'] in ('INCOMPLET', 'COMPLET'):
        corps += (f'<p>Travail : {valeur(ventilation["minutes_travail"])} minutes · '
                  f'Pauses : {valeur(ventilation["minutes_pause"])} minutes · '
                  f'Déplacements : {valeur(ventilation["minutes_deplacement"])} minutes</p>'
                  f'<p>Revue : {valeur(ventilation["revue"])} · Équipes indéterminées : '
                  f'{valeur(ventilation["equipes_indeterminees"])}</p>'
                  f'<p>Coût de main-d’œuvre ventilé : {valeur(ventilation["cout_main_oeuvre"])}</p>'
                  f'<p>Ce WCT seulement : {valeur(ventilation["wct_id"])}</p>'
                  '<p>Ventilation calculée depuis les sources relues ; '
                  'les déplacements ne sont pas inclus dans ce coût.</p>')
        if ventilation['statut'] == 'COMPLET' and csrf is not None:
            libelle = 'Enregistrer cette analyse locale'
            corps += (f'<form method="post" action="{pages.e(base + "/couts-travaux/tracer")}">'
                      f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">'
                      f'<input type="hidden" name="source_attendue" value="{pages.e(vue["source_calculee"])}">'
                      f'<input type="hidden" name="mutation_id" value="{uuid.uuid4().hex}">'
                      f'<button type="submit">{pages.e(libelle)}</button></form>'
                      '<p>Cette analyse n’est pas publiée aux autres services.</p>')
    else:
        corps += f'<p>{pages.e(messages.get(ventilation["statut"], "Ventilation indisponible."))}</p>'
    historique = vue.get('historique_v3', {'nombre': 0, 'traces': [], 'reste': 0})
    if historique['nombre']:
        corps += ('<h3>Analyses enregistrées</h3><p>Ces analyses sont historiques et ne sont pas publiées '
                  'aux autres services ; la vue courante est recalculée.</p><ul>')
        for trace in historique['traces']:
            corps += (f'<li>Complétion WCT : {valeur(trace["horodatage"])} · {valeur(trace["verdict"])} · '
                      f'Référence : {valeur(trace["version_entrees"])}</li>')
        corps += '</ul>'
        if historique['reste']:
            corps += f'<p>Autres analyses non affichées : {historique["reste"]}</p>'
    service = vue.get('historique_service', {'nombre': 0, 'traces': [], 'reste': 0})
    if service['nombre']:
        corps += ('<h3>Publications de service</h3><p>La liaison historique est examinée par Core ; '
                  'sa fraîcheur actuelle reste à revalider.</p><ul>')
        for trace in service['traces']:
            preuve = ('Liaison historique vérifiée' if trace['preuve_core'] == 'liaison_historique_verifiee'
                      else 'Liaison historique non vérifiable')
            corps += (f'<li>Complétion WCT : {valeur(trace["horodatage"])} · {valeur(trace["verdict"])} · '
                      f'Référence : {valeur(trace["version_entrees"])} · {pages.e(preuve)}</li>')
        corps += '</ul>'
    corps += (f'<p>Arrondi M5 : {pages.e(cout["arrondi"])}</p><details><summary>Source de consultation</summary>'
              f'<p>Empreinte calculée : {pages.e(vue["source_calculee"])}</p></details></section>')
    return corps


def _vue_sans_zero_invente(vue):
    """Copie la vue pour distinguer une absence de coût d'un zéro attesté."""
    copie = copy.deepcopy(vue)
    etat = copie.get('chantier')
    if isinstance(etat, dict) and etat.get('statut') == 'calculee':
        rentabilite = etat['rentabilite']
        cout = rentabilite['cout_reel']
        materiaux, main = cout['materiaux'], cout['main_d_oeuvre']
        materiaux_connus = (materiaux['statut'] == 'complet'
                            or any(ligne.get('cout') is not None for ligne in materiaux['lignes']))
        if not materiaux_connus:
            materiaux['cout_connu'] = None
        if not materiaux_connus and main.get('cout') is None and main.get('cout_connu') is None:
            cout['cout_total_connu'] = None
            rentabilite['marge_partielle_plafond'] = None
            rentabilite['marge_partielle_plafond_pct_du_prix'] = None
    return copie


def _exporter(vue):
    """Encode la lecture vérifiée, sans convertir une absence de composante en coût nul."""
    document = {
        'format': 'opsys.couts-travaux.export.v1',
        'mention': 'Export préparatoire pour revue ; aucune écriture comptable, facture envoyée ou paiement.',
        'vue': _vue_sans_zero_invente(vue),
    }
    return json.dumps(document, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre):
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import Response

    router = APIRouter()

    @router.get('/crm/lead/{lead_id}/soumissions/{devis_id}/couts-travaux')
    def page(lead_id: str, devis_id: str, request: Request):
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres de consultation invalides')
        try:
            with cnx_factory() as cnx:
                vue = lire(cnx, deps, session, lead_id, devis_id)
                try:
                    reponse = rendre(session, 'Coûts des travaux', contenu(vue, prefixe, session.csrf))
                except (ValueError, KeyError, TypeError):
                    raise HTTPException(503, 'Présentation des coûts indisponible') from None
                if len(reponse.body) > 131072:
                    raise HTTPException(503, 'Présentation des coûts trop volumineuse')
                autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except lecture.Refus as exc:
            code = {'INTROUVABLE': 404, 'DEVIS-NON-ACCEPTE': 409}.get(exc.code, 503)
            raise HTTPException(code, 'Coûts indisponibles : ' + exc.code) from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Sources de coûts indisponibles') from None
        return reponse

    @router.get('/crm/lead/{lead_id}/soumissions/{devis_id}/couts-travaux/export.json')
    def export(lead_id: str, devis_id: str, request: Request):
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres de consultation invalides')
        try:
            with cnx_factory() as cnx:
                vue = lire(cnx, deps, session, lead_id, devis_id)
                donnees = _exporter(vue)
                if len(donnees) > 131072:
                    raise lecture.Refus('SORTIE-TROP-VOLUMINEUSE')
                reponse = Response(donnees, media_type='application/json', headers={
                    'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                    'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'; sandbox",
                    'Content-Disposition': 'attachment; filename="couts-travaux.json"',
                })
                if lire(cnx, deps, session, lead_id, devis_id) != vue:
                    raise lecture.Refus('SOURCE-MODIFIEE')
                autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except lecture.Refus as exc:
            code = {'INTROUVABLE': 404, 'DEVIS-NON-ACCEPTE': 409}.get(exc.code, 503)
            raise HTTPException(code, 'Coûts indisponibles : ' + exc.code) from None
        except (ValueError, KeyError, TypeError, OverflowError):
            raise HTTPException(503, 'Sources de coûts indisponibles') from None
        return reponse

    @router.post('/crm/lead/{lead_id}/soumissions/{devis_id}/couts-travaux/tracer')
    async def tracer(lead_id: str, devis_id: str, request: Request):
        from fastapi.responses import RedirectResponse

        from . import cedule_plan_ui, securite

        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres de traçage invalides')
        champs = await cedule_plan_ui.formulaire(request)
        if not securite.csrf_valide(champs.get('csrf'), session):
            raise HTTPException(403, 'Jeton CSRF absent ou invalide')
        if set(champs) != {'csrf', 'source_attendue', 'mutation_id'}:
            raise HTTPException(400, 'Champs de traçage invalides')
        try:
            with cnx_factory() as cnx:
                tracer_ventilation(cnx, deps, session, lead_id, devis_id, champs['source_attendue'],
                                   champs['mutation_id'])
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except EcritureConcurrente:
            raise HTTPException(409, 'Sources modifiées pendant le traçage') from None
        except lecture.Refus as exc:
            code = 409 if exc.code in {'SOURCE-PERIMEE', 'VENTILATION-INCOMPLETE', 'SOURCE-MODIFIEE',
                                       'MUTATION-CONFLIT'} else 503
            raise HTTPException(code, 'Traçage indisponible : ' + exc.code) from None
        except (ValueError, KeyError, TypeError, OverflowError):
            raise HTTPException(503, 'Sources de coûts indisponibles') from None
        from . import pages

        chemin = (f'{prefixe}/crm/lead/{pages._segment(lead_id)}/soumissions/'
                   f'{pages._segment(devis_id)}/couts-travaux')
        return RedirectResponse(chemin, status_code=303, headers={'Cache-Control': 'no-store'})

    return router
