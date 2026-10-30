"""Concurrence fictive réelle de deux saisies M4, même source attendue."""
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

from m4_field_ops import calendrier_civil, cedule, cedule_tournees, equipes_pointees_v3, etats, visites_chantier
from m4_field_ops.registre import Registre
from opsys import contexte, equipes, identite, stockage

spec = importlib.util.spec_from_file_location('qa_reprise', Path(__file__).with_name('test_visites_reprise.py'))
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


def test_deux_saisies_meme_source_une_seule_ecriture(base_durable, tmp_path, monkeypatch):
    monkeypatch.setenv('OPSYS_HOME', str(tmp_path / 'opsys'))
    initial, ids, positions = d.fixture.pur._monde(leads=('ch-01',))
    equipes.enregistrer_equipes({'liste': [{**e, 'membres': [e['id'] + '.fictif']}
                                         for e in d.fixture.pur._aide._equipes()]})
    with stockage.transaction(base_durable) as cnx:
        identite.creer_personne(cnx, 'admin.fictif', 'Admin fictif', 'Fictif#12345678', roles=['admin'])
        principal = Registre(stockage.maillons('m04-field-ops', 'principal'))
        for m in initial.lire():
            principal.ajouter({k: v for k, v in m.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
        plan = d.fixture.pur._reussi(d.fixture.pur._proposer(principal, ids, positions))['plan_id']
        d.fixture.pur._reussi(cedule_tournees.appliquer(principal, plan, positions,
                                                        d.fixture.pur.HORODATAGE, 'admin.fictif'))
        calendrier_civil.confirmer(principal, plan, {'0': '2030-06-03'}, 0, 'admin.fictif', '2030-06-02T09:00:00+00:00')
        ligne = calendrier_civil.lire_semaine(principal, '2030-06-03')['interventions'][0]
        ancre = {k: ligne[k] for k in d.fixture.CHAMPS_ANCRE}
        iid, equipe = ancre['intervention_id'], ligne['equipe_id']
        visites = Registre(stockage.maillons('m04-field-ops', 'visites_chantier'))
        prev = d.ecrire(principal, visites, ancre, heure='2030-06-03T07:30:00-04:00')
        visites_chantier.ouvrir(principal, visites, prev['visite_id'], '2030-06-03T08:00:00-04:00')
        assert etats.transitionner(iid, 'en_route', principal, '2030-06-03T08:30:00-04:00',
            assignation={'intervention_id': iid, 'technicien_id': equipe})[1] is None
        source = equipes_pointees_v3.empreinte_sources(cnx)
    args = {'intervention_id': iid, 'technicien_id': equipe, 'action': 'arrivee',
            'horodatage': '2030-06-03T09:00:00-04:00', 'fix_gps': None,
            'attestation': {'fictif': True, 'appareil_id': 'fictif'},
            'fenetre_travail': {'debut': '2030-06-03T08:00:00-04:00', 'fin': '2030-06-03T18:00:00-04:00'},
            'referentiel_villes': {cedule.tokeniser_ville('sel-fictif', 'Repentigny'): {
                'latitude': 45.75, 'longitude': -73.45, 'rayon_km': 25.0}},
            'ville': 'Repentigny', 'sel': 'sel-fictif'}
    barriere = Barrier(2)
    instant = datetime(2030, 6, 3, 13, tzinfo=UTC)
    def essayer(n):
        barriere.wait(timeout=10)
        try:
            with (stockage.transaction(base_durable) as cnx,
                  contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')),
                  contexte.appeler_en_tant_que('m04-field-ops', origine='console'),
                  contexte.receptionne_de(contexte.HorodatageAppareil('console:admin.fictif', instant, instant))):
                recu = equipes_pointees_v3.enregistrer(cnx, args, prev['visite_id'], equipe,
                                                       'concurrence-' + str(n), source)
                return ('accepte', recu['pointage_id'])
        except equipes_pointees_v3.Refus as e:
            return ('refus', str(e))
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = list(pool.map(essayer, [1, 2]))
    assert sorted(x[0] for x in resultats) == ['accepte', 'refus'], resultats
    assert next(x[1] for x in resultats if x[0] == 'refus') == 'SOURCE-PERIMEE'
    with stockage.transaction(base_durable):
        faits = Registre(stockage.maillons('m04-field-ops', 'principal')).lire()
        pointages = [m for m in faits if m.get('type_entree') == 'pointage' and m.get('visite_id') == prev['visite_id']]
        preuves = [m for m in faits if m.get('type_entree') == equipes_pointees_v3.TYPE
                   and m.get('visite_id') == prev['visite_id']]
        assert len(pointages) == len(preuves) == 1 and preuves[0]['pointage_id'] == pointages[0]['ligne_id']
    print('QA_CONCURRENCE=1_ACCEPTE_1_SOURCE_PERIMEE POINTAGE=1 PREUVE=1')
