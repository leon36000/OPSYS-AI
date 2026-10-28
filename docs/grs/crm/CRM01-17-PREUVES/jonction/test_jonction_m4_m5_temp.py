from copy import deepcopy
from test_temps_certifies_v2 import chantier_termine, _appel
from m4_field_ops.registre import Registre
from m5_financecore import validation_projection_visites, ventilation_couts_visites, cout_reel, encodage
from opsys import stockage


def test_jonction_producteur_reel_et_consommateur_refuse_total_inconnu(chantier_termine):
    cas = chantier_termine
    with stockage.transaction(cas['url']) as cnx:
        export = _appel(cnx, cas)
        p = export['projection']
        params = dict(instance_id=p['instance_id'], wct_id=cas['wct_id'], source_attendue=export['source'], sources_actuelles=p['sources'])
        validation = validation_projection_visites.valider_projection(p, **params)
        assert validation['valide'], validation
        assert not validation['exploitable'] and 'équipe pointée indéterminée' in validation['raisons']
        assert p['totaux'] == {'travail': 390, 'pause': 30, 'deplacement': 60}
        cout = ventilation_couts_visites.chiffrer_visites(p['visites'], [])
        assert not cout['complet'] and cout['cout_total'] is None and cout['cout_connu'] is None
        registre = Registre(stockage.maillons('m04-field-ops', 'principal'))
        wct = next(m['wct'] for m in registre.lire() if m.get('wct', {}).get('wct_id') == cas['wct_id'])
        finance = cout_reel._main_d_oeuvre_ventilee(wct, p, [], params['instance_id'], params['source_attendue'], params['sources_actuelles'])
        assert finance['statut'] == 'non_disponible' and finance['cout'] is None
        perime = validation_projection_visites.valider_projection(p, **{**params, 'source_attendue': 'f'*64})
        assert not perime['valide']


def test_m5_refuse_identification_equipe_sans_provenance_typee(chantier_termine):
    cas = chantier_termine
    with stockage.transaction(cas['url']) as cnx:
        export = _appel(cnx, cas)
        p = deepcopy(export['projection'])
        for v in p['visites']:
            v['equipe_pointee'] = {'statut': 'identifiee', 'identifiant': v['equipe_planifiee_id'], 'justification': 'egalite_route_et_prevision'}
        p['inconnus'] = [i for i in p['inconnus'] if i['code'] != 'equipe_pointee_indeterminee']
        p['empreinte'] = encodage.empreinte('m4.temps_certifies.v2', {k: v for k,v in p.items() if k != 'empreinte'})
        validation = validation_projection_visites.valider_projection(p, instance_id=p['instance_id'], wct_id=cas['wct_id'], source_attendue=export['source'], sources_actuelles=p['sources'])
        assert not validation['valide'], validation
