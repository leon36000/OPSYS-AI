"""Reprise privée : données, profils et SQLite fictifs uniquement."""
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops import (
    calendrier_civil,
    cedule,
    encodage,
    etats,
    pointage,
    registre,
    visites_chantier,
    visites_durables,
)

from opsys import equipes, stockage

spec = importlib.util.spec_from_file_location('fixture_application_reprise',
    Path(__file__).with_name('test_console_application_chantier.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
propose, pret, affaire, catalogue, client_crm = f.propose, f.pret, f.affaire, f.catalogue, f.client_crm


def test_serveur_fictif_reprise(propose, catalogue, session, monkeypatch):
    from datetime import UTC, datetime

    from opsys.console import application_chantier, reprise_visite

    class HorlogeFictive(datetime):
        instant = datetime(2030, 6, 3, 16, 4, tzinfo=UTC)
        @classmethod
        def now(cls, tz=None):
            return cls.instant.astimezone(tz)
    monkeypatch.setattr(reprise_visite, 'datetime', HorlogeFictive)
    from opsys.console import metier
    monkeypatch.setattr(metier, 'datetime', HorlogeFictive)
    profil, erreur = equipes.charger_equipes()
    assert erreur is None
    autre = dict(profil['liste'][0], id='eq-reprise-fictive', membres=['reprise.fictive'])
    profil['liste'].append(autre)
    # Le premier plan doit être appliqué avant le changement de profil.
    profil_initial = dict(profil, liste=profil['liste'][:1])
    equipes.enregistrer_equipes(profil_initial)
    with session() as cnx:
        vue = application_chantier.preparer(cnx, propose['deps'], f.p.AUTH, propose['lead'], f.p.DEVIS,
                                           propose['plan_id'])
        application_chantier.appliquer(cnx, propose['deps'], f.p.AUTH, propose['lead'], f.p.DEVIS,
                                      propose['plan_id'], vue['empreinte'], 'premier-plan-fictif')
        reg = registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        calendrier_civil.confirmer(reg, propose['plan_id'], {'0': '2030-06-03'}, 0,
                                           'admin.fictif', '2030-06-02T09:00:00+00:00')
        ligne = calendrier_civil.lire_semaine(reg, '2030-06-03')['interventions'][0]
        iid = ligne['intervention_id']
        ancre = {k: ligne[k] for k in ('intervention_id', 'plan_id', 'source_application_id', 'source_ligne_id')}
        prev = registre.Registre(stockage.maillons('m04-field-ops', visites_durables.REGISTRE))
        args = {'ancre': ancre, 'revision_attendue': 0}
        recu = visites_durables.prevoir(reg, prev, **args,
            auteur={'personne': 'admin.fictif', 'role': 'admin'},
            mutation={'appareil': 'fictif', 'cle': 'prevision-fictive',
                      'empreinte_arguments': encodage.empreinte(args)},
            horodatage='2030-06-03T07:30:00-04:00')
        visites_chantier.ouvrir(reg, prev, recu['visite_id'], '2030-06-03T08:00:00-04:00')
        assign = {'intervention_id': iid, 'technicien_id': ligne['equipe_id']}
        assert etats.transitionner(iid, 'en_route', reg, '2030-06-03T08:30:00-04:00', assignation=assign)[1] is None
        ref = {cedule.tokeniser_ville('sel-fictif', 'Laval'): {
            'latitude': 45.59, 'longitude': -73.74, 'rayon_km': 25.0}}
        fenetre = {'debut': '2030-06-03T08:00:00-04:00', 'fin': '2030-06-03T18:00:00-04:00'}
        for action, heure in [('arrivee', '09:00:00'), ('pause_debut', '10:00:00'),
                              ('pause_fin', '10:30:00'), ('depart', '12:00:00')]:
            assert pointage.enregistrer_pointage(iid, ligne['equipe_id'], action, f'2030-06-03T{heure}-04:00',
                {'latitude': 45.59, 'longitude': -73.74}, {'fictif': True, 'appareil_id': 'fictif'},
                assign, fenetre, ref, 'Laval', 'sel-fictif', reg)[1] is None
        visites_chantier.fermer(reg, prev, recu['visite_id'], '2030-06-03T12:01:00-04:00')
        assert etats.transitionner(iid, 'reportee', reg, '2030-06-03T12:02:00-04:00',
                                   motif='meteo', registre_visites=prev)[1] is None
        assert etats.transitionner(iid, 'planifiee', reg, '2030-06-03T12:03:00-04:00')[1] is None
    equipes.enregistrer_equipes(profil)
    import socket
    import uvicorn
    from opsys.console import application
    from opsys.console.securite import Configuration
    app = application.creer_application(Configuration(
        'secret-qa-fictif-' + 'x' * 40, cookie_securise=False, prefixe='', duree_session=315360000), None, session)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('127.0.0.1', 0))
    sock.listen(32)
    print('QA_PORT=' + str(sock.getsockname()[1]), flush=True)
    print('QA_INTERVENTION=' + iid, flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False)).run(sockets=[sock])
    finally:
        sock.close()
        print('QA_SERVEUR_FERME', flush=True)
