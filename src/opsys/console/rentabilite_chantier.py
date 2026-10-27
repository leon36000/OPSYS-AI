"""Lecture privée M3→M5, calcul propriétaire et sources consommées, aucun effet financier."""
import hashlib

from m5_financecore import encodage
from sqlalchemy import LargeBinary, cast, func, select

from .. import contexte
from ..outils import Autonomie, executer
from ..stockage import codec
from ..stockage.maillons import copier_maillons_avec_metadonnees
from ..stockage.schema import EVENEMENTS_RECUS
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
                    source_calculee=None)
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
    autorite._admin(cnx, session)
    if (_references(_capture(cnx)) != refs or _configuration(m5) != config
            or _ancre(cnx, deps, session, lead_id, devis_id) != charge
            or (charge is not None and _reception(cnx, devis_id) != (statut, recu))):
        raise lecture.Refus('SOURCE-MODIFIEE')
    resultat['source_calculee'] = encodage.empreinte(dict(registres=refs, configuration=config[0],
        acceptation=charge, reception=recu))
    autorite._admin(cnx, session)
    return lecture._sortie(m5.analyse.avec_mention(resultat))
