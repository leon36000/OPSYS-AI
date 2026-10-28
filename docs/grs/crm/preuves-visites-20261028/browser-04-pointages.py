"""QA fictive : deux pointages terrain, sans réseau ni données réelles."""
from m4_field_ops import cedule, etats, pointage
from m4_field_ops.registre import Registre
from opsys import stockage

iid = 'c09957d3e72a26380019fca7aee8451885274737c58083fe85bae696e4343031'
with stockage.transaction():
    reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
    assign = {'intervention_id': iid, 'technicien_id': 'eq-reprise-fictive'}
    recu, erreur = etats.transitionner(iid, 'en_route', reg, '2030-06-07T08:30:00-04:00', assignation=assign)
    assert erreur is None, erreur
    ref = {cedule.tokeniser_ville('sel-fictif', 'Laval'): {
        'latitude': 45.59, 'longitude': -73.74, 'rayon_km': 25.0}}
    fenetre = {'debut': '2030-06-07T08:00:00-04:00', 'fin': '2030-06-07T18:00:00-04:00'}
    for action, instant in [('arrivee', '2030-06-07T13:00:00+00:00'),
                            ('depart', '2030-06-07T17:00:00+00:00')]:
        recu, erreur = pointage.enregistrer_pointage(iid, 'eq-reprise-fictive', action, instant,
            {'latitude': 45.59, 'longitude': -73.74}, {'fictif': True, 'appareil_id': 'qa-fictif'},
            assign, fenetre, ref, 'Laval', 'sel-fictif', reg)
        assert erreur is None, erreur
    print('QA_POINTAGES_FICTIFS=2')
stockage.liberer()
