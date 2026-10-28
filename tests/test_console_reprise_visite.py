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


def test_proposition_reprise_choisit_equipe_declaree_et_rejoue(propose, catalogue, session, monkeypatch):
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
    with session() as cnx:
        apercu = reprise_visite.preparer(cnx, propose['deps'], f.p.AUTH, iid)
        assert 'eq-reprise-fictive' in apercu['equipes']
    avant = f.p.m.base._instantane_base(session)
    from opsys.console import preparation_chantier
    for equipe_demande, empreinte, code in [('eq-reprise-fictive', '0' * 64, 'SOURCE-MODIFIEE'),
                                             ('inconnue-fictive', apercu['empreinte'], 'EQUIPE-INCONNUE')]:
        with session() as cnx, pytest.raises(preparation_chantier.Refus, match=code):
            reprise_visite.proposer(cnx, propose['deps'], f.p.AUTH, iid, equipe_demande,
                                    480, 1020, empreinte, 'refus-' + code)
        assert f.p.m.base._instantane_base(session) == avant
    def panne(*args, **kwargs):
        raise RuntimeError('panne fictive après proposition')
    with monkeypatch.context() as patch:
        patch.setattr(reprise_visite, 'journaliser', panne)
        with session() as cnx, pytest.raises(RuntimeError, match='panne fictive'):
            reprise_visite.proposer(cnx, propose['deps'], f.p.AUTH, iid, 'eq-reprise-fictive',
                                    480, 1020, apercu['empreinte'], 'rollback-fictif')
    assert f.p.m.base._instantane_base(session) == avant
    from opsys import identite
    audit = reprise_visite.journaliser
    def revoquer(cnx, *args, **kwargs):
        audit(cnx, *args, **kwargs)
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    with monkeypatch.context() as patch:
        patch.setattr(reprise_visite, 'journaliser', revoquer)
        with session() as cnx, pytest.raises(PermissionError):
            reprise_visite.proposer(cnx, propose['deps'], f.p.AUTH, iid, 'eq-reprise-fictive',
                                    480, 1020, apercu['empreinte'], 'revocation-fictive')
    assert f.p.m.base._instantane_base(session) == avant
    def changer_source(cnx, *args, **kwargs):
        audit(cnx, *args, **kwargs)
        registre.Registre(stockage.maillons('m04-field-ops', 'principal')).ajouter({
            'type_entree': 'variance_m6_recue', 'intervention_id': 'autre-fictif',
            'horodatage': '2030-06-03T16:04:00+00:00', 'fictif': True})
    with monkeypatch.context() as patch:
        patch.setattr(reprise_visite, 'journaliser', changer_source)
        with session() as cnx, pytest.raises(preparation_chantier.Refus, match='SOURCE-MODIFIEE'):
            reprise_visite.proposer(cnx, propose['deps'], f.p.AUTH, iid, 'eq-reprise-fictive',
                                    480, 1020, apercu['empreinte'], 'source-tardive')
    assert f.p.m.base._instantane_base(session) == avant
    from html.parser import HTMLParser
    class Champs(HTMLParser):
        def __init__(self, html):
            super().__init__()
            self.valeurs = {}
            self.feed(html)
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'input' and 'name' in attrs:
                self.valeurs[attrs['name']] = attrs.get('value', '')
    from dataclasses import replace

    from opsys.console import securite
    cookie = next(c for c in catalogue.cookies.jar if c.name == securite.NOM_COOKIE)
    sess = securite.lire_session(cookie.value, f.p.m.base.SECRET)
    cookie.value = securite.signer_session(replace(sess, expire=4102444800), f.p.m.base.SECRET)
    route = '/crm/visites/reprise?intervention_id=' + iid
    assert catalogue.get(route + '&intervention_id=autre').status_code == 400
    assert catalogue.get('/crm/visites/reprise?intervention_id=%3Cscript%3E').status_code == 400
    page = catalogue.get(route)
    assert page.headers['cache-control'] == 'no-store'
    assert 'content-security-policy' in page.headers
    assert page.status_code == 200 and 'eq-reprise-fictive' in page.text, page.text
    champs = Champs(page.text).valeurs
    champs.update(equipe_id='eq-reprise-fictive', debut='08:00', fin='17:00')
    assert catalogue.post(route, data={**champs, 'csrf': 'invalide'}, follow_redirects=False).status_code == 403
    assert catalogue.post(route, data={**champs, 'debut': '25:99'}, follow_redirects=False).status_code == 400
    reponse = catalogue.post(route, data=champs, follow_redirects=False)
    assert reponse.status_code == 303, reponse.text
    destination = reponse.headers['location'].removeprefix(f.p.m.base.PREFIXE)
    plan_id = destination.split('plan_id=')[1]
    with session() as cnx:
        rejoue = reprise_visite.proposer(cnx, propose['deps'], f.p.AUTH, iid, 'eq-reprise-fictive',
                                         480, 1020, apercu['empreinte'], champs['mutation_id'])
        assert rejoue['rejoue'] is True
        resultat = {'proposition': rejoue['proposition']}
        assert resultat['proposition']['plan'][0]['equipe'] == 'eq-reprise-fictive'

    with session() as cnx:
        revue = reprise_visite.preparer_application(cnx, propose['deps'], f.p.AUTH, iid,
                                                    resultat['proposition']['plan_id'])
        assert revue['peut_appliquer'] is True
    avant = f.p.m.base._instantane_base(session)
    with session() as cnx, pytest.raises(preparation_chantier.Refus, match='SOURCE-MODIFIEE'):
        reprise_visite.appliquer(cnx, propose['deps'], f.p.AUTH, iid, resultat['proposition']['plan_id'],
                                 '0' * 64, 'application-perimee')
    assert f.p.m.base._instantane_base(session) == avant
    with monkeypatch.context() as patch:
        patch.setattr(reprise_visite, 'journaliser', panne)
        with session() as cnx, pytest.raises(RuntimeError, match='panne fictive'):
            reprise_visite.appliquer(cnx, propose['deps'], f.p.AUTH, iid, resultat['proposition']['plan_id'],
                                     revue['empreinte'], 'application-rollback')
    assert f.p.m.base._instantane_base(session) == avant
    with monkeypatch.context() as patch:
        patch.setattr(reprise_visite, 'journaliser', revoquer)
        with session() as cnx, pytest.raises(PermissionError):
            reprise_visite.appliquer(cnx, propose['deps'], f.p.AUTH, iid, resultat['proposition']['plan_id'],
                                     revue['empreinte'], 'application-revocation')
    assert f.p.m.base._instantane_base(session) == avant
    with monkeypatch.context() as patch:
        patch.setattr(reprise_visite, 'journaliser', changer_source)
        with session() as cnx, pytest.raises(preparation_chantier.Refus, match='SOURCE-MODIFIEE'):
            reprise_visite.appliquer(cnx, propose['deps'], f.p.AUTH, iid, resultat['proposition']['plan_id'],
                                     revue['empreinte'], 'application-source-tardive')
    assert f.p.m.base._instantane_base(session) == avant
    page = catalogue.get(destination)
    assert page.status_code == 200 and 'eq-reprise-fictive' in page.text, page.text
    formulaire = Champs(page.text).valeurs
    assert catalogue.post(destination, data={**formulaire, 'csrf': 'invalide'},
                          follow_redirects=False).status_code == 403
    reponse = catalogue.post(destination, data=formulaire, follow_redirects=False)
    assert reponse.status_code == 303 and reponse.headers['location'].endswith('/crm/cedule/plan/' + plan_id)
    dates_route = '/crm/cedule/plan/' + plan_id
    dates_page = catalogue.get(dates_route)
    assert dates_page.status_code == 200, dates_page.text
    dates = Champs(dates_page.text).valeurs
    dates['date_0'] = '2030-06-07'
    confirmation = catalogue.post(dates_route, data=dates, follow_redirects=False)
    assert confirmation.status_code == 303, confirmation.text
    class Formulaires(HTMLParser):
        def __init__(self, html):
            super().__init__()
            self.forms, self.courant = [], None
            self.feed(html)
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'form':
                self.courant = {}
                self.forms.append(self.courant)
            elif tag == 'input' and self.courant is not None and 'name' in attrs:
                self.courant[attrs['name']] = attrs.get('value', '')
        def handle_endtag(self, tag):
            if tag == 'form':
                self.courant = None
    visite_route = '/crm/visites?intervention_id=' + iid
    page_visite = catalogue.get(visite_route)
    assert page_visite.status_code == 200 and '2030-06-07' not in page_visite.text  # prévision pas encore conservée
    prevoir = next(x for x in Formulaires(page_visite.text).forms if x.get('operation') == 'prevoir')
    assert catalogue.post(visite_route, data=prevoir, follow_redirects=False).status_code == 303
    HorlogeFictive.instant = datetime(2030, 6, 7, 12, 0, tzinfo=UTC)
    page_visite = catalogue.get(visite_route)
    assert page_visite.status_code == 200 and '2030-06-07' in page_visite.text
    ouvrir = next(x for x in Formulaires(page_visite.text).forms if x.get('operation') == 'ouvrir')
    assert catalogue.post(visite_route, data=ouvrir, follow_redirects=False).status_code == 303
    with session() as cnx:

        principal = registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        assert etats.statut_courant(principal, iid) == 'planifiee'
        assert etats.technicien_assigne(principal, iid) == 'eq-reprise-fictive'
        rejoue_app = reprise_visite.appliquer(cnx, propose['deps'], f.p.AUTH, iid,
            plan_id, revue['empreinte'], formulaire['mutation_id'])
        assert rejoue_app['rejoue'] is True
    # Les pointages terrain restent distincts des déclarations d'équipe.
    with session():
        principal = registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        assign_reprise = {'intervention_id': iid, 'technicien_id': 'eq-reprise-fictive'}
        assert etats.transitionner(iid, 'en_route', principal, '2030-06-07T08:30:00-04:00',
                                   assignation=assign_reprise)[1] is None
        fenetre = {'debut': '2030-06-07T08:00:00-04:00', 'fin': '2030-06-07T18:00:00-04:00'}
        for action, instant in [('arrivee', '2030-06-07T13:00:00+00:00'),
                                ('depart', '2030-06-07T17:00:00+00:00')]:
            assert pointage.enregistrer_pointage(iid, 'eq-reprise-fictive', action, instant,
                {'latitude': 45.59, 'longitude': -73.74}, {'fictif': True, 'appareil_id': 'fictif'},
                assign_reprise, fenetre, ref, 'Laval', 'sel-fictif', principal)[1] is None
    HorlogeFictive.instant = datetime(2030, 6, 7, 17, 1, tzinfo=UTC)
    page_visite = catalogue.get(visite_route)
    fermer = next(x for x in Formulaires(page_visite.text).forms if x.get('operation') == 'fermer')
    assert catalogue.post(visite_route, data=fermer, follow_redirects=False).status_code == 303
    page_visite = catalogue.get(visite_route)
    assert 'Pointé : 150 min nettes' in page_visite.text and 'Pointé : 240 min nettes' in page_visite.text
    from m4_field_ops import outbox
    with session():
        principal = registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        assert not [w for _, w in outbox.lire_outbox(principal) if w['intervention_id'] == iid]
    import base64
    import hashlib

    from m4_field_ops.outils import outils

    from opsys import contexte
    from opsys.outils import executer_atomique
    png_spec = importlib.util.spec_from_file_location('png_reprise_complete',
        Path(__file__).parents[1] / 'departments/m04-field-ops/tests/conftest.py')
    png_fixture = importlib.util.module_from_spec(png_spec)
    png_spec.loader.exec_module(png_fixture)
    png = png_fixture.png_minimal()
    par_nom = {o.nom: o for o in outils()}
    instant_fin = datetime(2030, 6, 7, 17, 2, tzinfo=UTC)
    def outil_final(nom, arguments):
        with (session(), contexte.appele_par_appareil(
                contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')),
              contexte.receptionne_de(contexte.HorodatageAppareil(
                  'console:admin.fictif', instant_fin, instant_fin))):
            return executer_atomique(par_nom[nom], arguments)
    photo = outil_final('m4_deposer_fichier', {'empreinte_sha256': hashlib.sha256(png).hexdigest(),
        'taille_octets': len(png), 'type_mime': 'image/png', 'index_bloc': 0, 'nombre_blocs': 1,
        'bloc_base64': base64.b64encode(png).decode('ascii')})
    assert photo['ok'] and photo['resultat']['accepte'], photo
    completion = {'intervention_id': iid, 'horodatage': instant_fin.isoformat(),
        'preuves_completion': {'checklist_complete': True,
            'photos_apres': [photo['resultat']['resultat']['reference']], 'notes': 'Fictif', 'signature': None},
        'signature_requise': False}
    reponse_fin = outil_final('m4_completer_intervention', completion)
    assert reponse_fin['ok'] and reponse_fin['resultat']['accepte'], reponse_fin
    assert not outil_final('m4_completer_intervention', completion)['resultat']['accepte']
    stockage.liberer()
    assert catalogue.get(visite_route).status_code == 200
    with session():
        principal = registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        wcts = [w for _, w in outbox.lire_outbox(principal) if w['intervention_id'] == iid]
        assert len(wcts) == 1 and wcts[0]['duree_reelle_minutes'] == 390
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    assert catalogue.get(route, follow_redirects=False).status_code in {303, 403}
    assert catalogue.post(route, data=champs, follow_redirects=False).status_code in {303, 403}
