"""fictif: true — outils M4 de visite, identité console et périmètre privé."""
from m4_field_ops.outils import outils


def test_outils_visites_privatives_enregistres():
    par_nom = {outil.nom: outil for outil in outils()}
    assert par_nom['m4_lire_visites_console'].autonomie.value == 'T0'
    assert par_nom['m4_prevoir_visite_console'].autonomie.value == 'T1'
    assert par_nom['m4_evenement_visite_console'].autonomie.value == 'T1'


def test_outils_refusent_agents_et_appareils_sans_console():
    from opsys.outils import executer
    par_nom = {outil.nom: outil for outil in outils()}
    for nom, arguments in [
        ('m4_lire_visites_console', {'intervention_id': 'chantier-fictif'}),
        ('m4_prevoir_visite_console', {'ancre': {}, 'revision_attendue': 0}),
        ('m4_evenement_visite_console', {'operation': 'ouvrir', 'visite_id': 'a' * 64,
                                        'source_attendue': 'b' * 64}),
    ]:
        # Le validateur structurel peut refuser l'ancre vide avant le contrôle d'identité.
        reponse = executer(par_nom[nom], arguments)
        assert reponse.get('ok') is False or reponse['resultat']['accepte'] is False


def _fixtures_console():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        'visites_cedule_fixture', Path(__file__).with_name('test_console_cedule.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


f = _fixtures_console()
client_crm, planning = f.client_crm, f.planning


def test_outils_console_sql_admin_prevision_et_ouverture(planning, session, monkeypatch):
    from datetime import datetime

    from m4_field_ops import calendrier_civil
    from m4_field_ops import outils as module_outils
    from m4_field_ops.registre import Registre

    from opsys import contexte, idempotence, stockage
    from opsys.outils import executer_atomique

    par_nom, ids, _, _ = planning
    iid = ids['lead-fictif-001']
    with session():
        principal = Registre(stockage.maillons('m04-field-ops', 'principal'))
        ligne = next(x for x in calendrier_civil.lire_semaine(principal, '2030-06-03')['interventions']
                     if x['intervention_id'] == iid)
        ancre = {k: ligne[k] for k in ('intervention_id', 'plan_id', 'source_application_id', 'source_ligne_id')}
    def appeler(nom, arguments, heure, cle=None):
        instant = datetime.fromisoformat(heure)
        meta = idempotence.Meta(cle, 'console:admin.fictif', heure) if cle else None
        with (session(),
              contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')),
              contexte.appeler_en_tant_que('m04-field-ops', origine='console'),
              module_outils.contexte_annotation_calendrier(meta),
              contexte.receptionne_de(contexte.HorodatageAppareil('console:admin.fictif', instant, instant))):
            return executer_atomique(par_nom[nom], arguments)
    lecture = appeler('m4_lire_visites_console', {'intervention_id': iid}, '2030-06-03T07:30:00-04:00')
    assert lecture['ok'] and lecture['resultat']['accepte']
    assert lecture['resultat']['resultat']['visites'] == []
    cree = appeler('m4_prevoir_visite_console', {'ancre': ancre, 'revision_attendue': 0},
                   '2030-06-03T07:31:00-04:00', 'prev-fictive')
    assert cree['ok'] and cree['resultat']['accepte'], cree
    visite_id = cree['resultat']['resultat']['visite_id']
    vue = appeler('m4_lire_visites_console', {'intervention_id': iid}, '2030-06-03T07:32:00-04:00')
    assert vue['resultat']['resultat']['visites'][0]['visite_id'] == visite_id
    source = vue['resultat']['resultat']['source_sql']
    params = {'operation': 'ouvrir', 'visite_id': visite_id, 'source_attendue': source}
    ouvre = appeler('m4_evenement_visite_console', params, '2030-06-03T08:00:00-04:00', 'ouvre-fictive')
    assert ouvre['ok'] and ouvre['resultat']['accepte'], ouvre
    reprise = appeler('m4_evenement_visite_console', params, '2030-06-03T08:01:00-04:00', 'ouvre-fictive')
    assert reprise['resultat']['rejoue'] is True
    from m4_field_ops import cedule, etats, pointage
    equipe = vue['resultat']['resultat']['visites'][0]['creneau']['equipe_id']
    assign = {'intervention_id': iid, 'technicien_id': equipe}
    with session():
        principal = Registre(stockage.maillons('m04-field-ops', 'principal'))
        assert etats.transitionner(iid, 'en_route', principal, '2030-06-03T08:30:00-04:00',
                                   assignation=assign)[1] is None
        ref = {cedule.tokeniser_ville('sel-fictif', 'Repentigny'): {
            'latitude': 45.75, 'longitude': -73.45, 'rayon_km': 25.0}}
        fenetre = {'debut': '2030-06-03T08:00:00-04:00', 'fin': '2030-06-03T18:00:00-04:00'}
        for action, instant in [('arrivee', '2030-06-03T09:00:00-04:00'),
                                ('depart', '2030-06-03T12:00:00-04:00')]:
            assert pointage.enregistrer_pointage(iid, equipe, action, instant,
                {'latitude': 45.75, 'longitude': -73.45}, {'fictif': True, 'appareil_id': 'fictif'},
                assign, fenetre, ref, 'Repentigny', 'sel-fictif', principal)[1] is None
    vue = appeler('m4_lire_visites_console', {'intervention_id': iid}, '2030-06-03T12:00:00-04:00')
    fermeture = appeler('m4_evenement_visite_console', {
        'operation': 'fermer', 'visite_id': visite_id, 'source_attendue': vue['resultat']['resultat']['source_sql']},
        '2030-06-03T12:01:00-04:00', 'ferme-fictive')
    assert fermeture['ok'] and fermeture['resultat']['accepte'], fermeture
    vue_report = appeler('m4_lire_visites_console', {'intervention_id': iid}, '2030-06-03T12:01:00-04:00')
    report_args = {'intervention_id': iid, 'motif': 'meteo', 'horodatage': '2030-06-03T12:02:00-04:00',
                   'visite_id': visite_id, 'source_attendue': vue_report['resultat']['resultat']['source_sql']}
    with session():
        avant_report = list(stockage.maillons('m04-field-ops', 'principal'))
    original_acteur = module_outils._acteur_appareil
    appels = []
    def acteur_revoque():
        appels.append(1)
        if len(appels) == 2:
            return None, {'code': 'REJ-IDENTITE-APPAREIL-INVALIDE', 'statut': '', 'detail': 'fictif'}
        return original_acteur()
    with monkeypatch.context() as patch:
        patch.setattr(module_outils, '_acteur_appareil', acteur_revoque)
        echec = appeler('m4_signaler_report', report_args, '2030-06-03T12:02:00-04:00', 'report-fictif')
        assert echec['resultat']['accepte'] is False
    with session():
        assert list(stockage.maillons('m04-field-ops', 'principal')) == avant_report
    report = appeler('m4_signaler_report', report_args, '2030-06-03T12:02:00-04:00', 'report-fictif')
    assert report['ok'] and report['resultat']['accepte'], report
    with session() as cnx:
        from opsys import identite
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    refuse = appeler('m4_lire_visites_console', {'intervention_id': iid}, '2030-06-03T08:02:00-04:00')
    assert refuse['resultat']['accepte'] is False


def test_port_console_admin_verifie_metier_et_rejeu(planning, session, monkeypatch):
    from datetime import UTC, datetime

    from m4_field_ops import calendrier_civil
    from m4_field_ops.registre import Registre

    from opsys import stockage
    from opsys.console import metier
    from opsys.console.securite import Session
    from opsys.departements import charger_departements

    class HorlogeFictive(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2030, 6, 3, 12, 0, 0, tzinfo=UTC).astimezone(tz)
    monkeypatch.setattr(metier, 'datetime', HorlogeFictive)
    auth = Session('admin.fictif', frozenset({'admin'}), 'csrf-fictif', 4102444800)
    _, ids, _, _ = planning
    iid = ids['lead-fictif-001']
    with session() as cnx:
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        ligne = next(x for x in calendrier_civil.lire_semaine(reg, '2030-06-03')['interventions']
                     if x['intervention_id'] == iid)
        ancre = {k: ligne[k] for k in ('intervention_id', 'plan_id', 'source_application_id', 'source_ligne_id')}
        result = metier.executer(cnx, charger_departements(), auth, 'm4_prevoir_visite_console',
                                 {'ancre': ancre, 'revision_attendue': 0}, mutation_id='prevoir-metier-fictif')
        assert result['ok'] and result['resultat']['accepte'], result
        visite_id = result['resultat']['resultat']['visite_id']
        vue = metier.executer(cnx, charger_departements(), auth, 'm4_lire_visites_console', {'intervention_id': iid})
        source = vue['resultat']['resultat']['source_sql']
        args = {'operation': 'ouvrir', 'visite_id': visite_id, 'source_attendue': source}
        ouvert = metier.executer(cnx, charger_departements(), auth, 'm4_evenement_visite_console', args,
                                 mutation_id='ouvrir-metier-fictif')
        assert ouvert['ok'] and ouvert['resultat']['accepte'], ouvert
        rejoue = metier.executer(cnx, charger_departements(), auth, 'm4_evenement_visite_console', args,
                                 mutation_id='ouvrir-metier-fictif')
        assert rejoue['resultat']['rejoue'] is True
        import pytest

        from opsys import identite
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
        with pytest.raises(PermissionError):
            metier.executer(cnx, charger_departements(), auth, 'm4_lire_visites_console', {'intervention_id': iid})
        with pytest.raises(PermissionError):
            metier.executer(cnx, charger_departements(), auth, 'm4_evenement_visite_console', args,
                            mutation_id='ouvrir-metier-fictif')


def test_http_visites_depuis_chantier_prevision_et_csrf(client_crm, planning, session, monkeypatch):
    from datetime import UTC, datetime

    from opsys.console import metier

    class HorlogeFictive(datetime):
        instant = datetime(2030, 6, 3, 12, 0, 0, tzinfo=UTC)
        @classmethod
        def now(cls, tz=None):
            return cls.instant.astimezone(tz)
    monkeypatch.setattr(metier, 'datetime', HorlogeFictive)
    _, ids, _, _ = planning
    iid = ids['lead-fictif-001']
    chemin = '/crm/visites?intervention_id=' + iid
    assert client_crm.get(chemin, follow_redirects=False).status_code == 303
    f.base._connecter(client_crm, 'admin.fictif')
    # Cookie fictif à échéance 2100 : l'horloge métier est avancée pour tester le jour de visite.
    from dataclasses import replace

    from opsys.console import securite
    cookie = next(c for c in client_crm.cookies.jar if c.name == securite.NOM_COOKIE)
    sess = securite.lire_session(cookie.value, f.base.SECRET)
    cookie.value = securite.signer_session(replace(sess, expire=4102444800), f.base.SECRET)
    journal = client_crm.get('/crm/journal-equipes?jour=2030-06-03')
    assert journal.status_code == 200 and ('/crm/visites?intervention_id=' + iid) in journal.text
    page = client_crm.get(chemin)
    assert page.status_code == 200, page.text
    assert 'Prévisions et visites' in page.text and 'Composition' in page.text
    from html.parser import HTMLParser
    class Forms(HTMLParser):
        def __init__(self):
            super().__init__()
            self.forms, self.current = [], None
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'form':
                self.current = {}
                self.forms.append(self.current)
            elif tag == 'input' and self.current is not None and 'name' in attrs:
                self.current[attrs['name']] = attrs.get('value', '')
        def handle_endtag(self, tag):
            if tag == 'form':
                self.current = None
    def formulaire(html, operation):
        parser = Forms()
        parser.feed(html)
        return next(x for x in parser.forms if x.get('operation') == operation)
    prevoir = formulaire(page.text, 'prevoir')
    mauvais_csrf = {**prevoir, 'csrf': 'csrf-incorrect-fictif'}
    assert client_crm.post(chemin, data=mauvais_csrf, follow_redirects=False).status_code == 403
    cree = client_crm.post(chemin, data=prevoir, follow_redirects=False)
    assert cree.status_code == 303, cree.text
    page = client_crm.get(chemin)
    assert page.status_code == 200 and 'Composition déclarée inconnue' in page.text
    assert 'Notes de cette prévision' in page.text and prevoir['source_ligne_id'] in page.text
    ouvrir = formulaire(page.text, 'ouvrir')
    autre = next(x for x in ids.values() if x != iid)
    assert client_crm.post('/crm/visites?intervention_id=' + autre, data=ouvrir,
                           follow_redirects=False).status_code == 400
    resultat = client_crm.post(chemin, data=ouvrir, follow_redirects=False)
    assert resultat.status_code == 303, resultat.text
    page = client_crm.get(chemin)
    assert page.status_code == 200 and 'Temps pointé : inconnu' in page.text
    assert formulaire(page.text, 'fermer')
    from m4_field_ops import calendrier_civil, cedule, composition_journaliere, encodage, etats, pointage
    from m4_field_ops.registre import Registre

    from opsys import stockage
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        ligne = next(x for x in calendrier_civil.lire_semaine(reg, '2030-06-03')['interventions']
                     if x['intervention_id'] == iid)
        equipe = ligne['equipe_id']
        assign = {'intervention_id': iid, 'technicien_id': equipe}
        assert etats.transitionner(iid, 'en_route', reg, '2030-06-03T08:30:00-04:00', assignation=assign)[1] is None
        ref = {cedule.tokeniser_ville('sel-fictif', 'Repentigny'): {
            'latitude': 45.75, 'longitude': -73.45, 'rayon_km': 25.0}}
        fenetre = {'debut': '2030-06-03T08:00:00-04:00', 'fin': '2030-06-03T18:00:00-04:00'}
        for action, instant in [('arrivee', '2030-06-03T09:00:00-04:00'),
                                ('depart', '2030-06-03T12:00:00-04:00')]:
            assert pointage.enregistrer_pointage(iid, equipe, action, instant,
                {'latitude': 45.75, 'longitude': -73.45}, {'fictif': True, 'appareil_id': 'fictif'},
                assign, fenetre, ref, 'Repentigny', 'sel-fictif', reg)[1] is None
        declaration = {'jour': '2030-06-03', 'equipe_id': equipe, 'membres': ['personne<script>.fictive'],
                       'revision_attendue': 0, 'statut_declaration': 'declaree'}
        composition_journaliere.declarer(Registre(stockage.maillons('m04-field-ops',
                                                                    composition_journaliere.REGISTRE)),
            **declaration, auteur={'personne': 'admin.fictif', 'role': 'admin'},
            mutation={'appareil': 'test-fictif', 'cle': 'composition-fictive',
                      'empreinte_arguments': encodage.empreinte(declaration)},
            horodatage='2030-06-03T12:00:00-04:00')
    HorlogeFictive.instant = datetime(2030, 6, 3, 16, 1, 0, tzinfo=UTC)
    page = client_crm.get(chemin)
    fermer = formulaire(page.text, 'fermer')
    assert 'Composition déclarée : personne&lt;script&gt;.fictive' in page.text
    assert 'personne<script>.fictive' not in page.text
    assert client_crm.post(chemin, data=fermer, follow_redirects=False).status_code == 303
    assert client_crm.post(chemin, data=fermer, follow_redirects=False).status_code == 303
    page = client_crm.get(chemin)
    assert page.status_code == 200 and 'Pointé : 180 min nettes' in page.text
    assert 'ne prouve pas la présence individuelle' in page.text
    interrompre = formulaire(page.text, 'interrompre')
    interrompre['motif'] = 'meteo'
    HorlogeFictive.instant = datetime(2030, 6, 3, 16, 2, 0, tzinfo=UTC)
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        reg.ajouter({'type_entree': 'variance_m6_recue', 'intervention_id': autre,
                     'horodatage': '2030-06-03T16:01:30+00:00', 'fictif': True})
    assert client_crm.post(chemin, data=interrompre, follow_redirects=False).status_code == 409
    with session():
        assert etats.statut_courant(Registre(stockage.maillons('m04-field-ops', 'principal')), iid) == 'sur_site'
    page = client_crm.get(chemin)
    interrompre = formulaire(page.text, 'interrompre')
    interrompre['motif'] = 'meteo'
    response = client_crm.post(chemin, data=interrompre, follow_redirects=False)
    assert response.status_code == 303, response.text
    assert client_crm.post(chemin, data=interrompre, follow_redirects=False).status_code == 303
    with session():
        from m4_field_ops import outbox
        relu = Registre(stockage.maillons('m04-field-ops', 'principal'))
        assert etats.statut_courant(relu, iid) == 'reportee'
        assert outbox.lire_outbox(relu) == []
    page = client_crm.get(chemin)
    assert 'Interruption : meteo' in page.text
    replanifier = formulaire(page.text, 'replanifier')
    HorlogeFictive.instant = datetime(2030, 6, 3, 16, 3, 0, tzinfo=UTC)
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        reg.ajouter({'type_entree': 'variance_m6_recue', 'intervention_id': autre,
                     'horodatage': '2030-06-03T16:02:30+00:00', 'fictif': True})
    assert client_crm.post(chemin, data=replanifier, follow_redirects=False).status_code == 409
    with session():
        assert etats.statut_courant(Registre(stockage.maillons('m04-field-ops', 'principal')), iid) == 'reportee'
    replanifier = formulaire(client_crm.get(chemin).text, 'replanifier')
    assert client_crm.post(chemin, data=replanifier, follow_redirects=False).status_code == 303
    assert client_crm.post(chemin, data=replanifier, follow_redirects=False).status_code == 303
    with session():
        relu = Registre(stockage.maillons('m04-field-ops', 'principal'))
        assert etats.statut_courant(relu, iid) == 'planifiee'
        assert outbox.lire_outbox(relu) == []
    assert client_crm.get('/crm/visites?intervention_id=%3Cscript%3E').status_code == 400
    from opsys import identite
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    assert client_crm.get(chemin, follow_redirects=False).status_code in {303, 403}
    assert client_crm.post(chemin, data=fermer, follow_redirects=False).status_code in {303, 403}


def test_outil_completion_session_segmente_sqlite(planning, session, monkeypatch):
    import base64
    import hashlib
    import importlib.util
    from datetime import datetime
    from pathlib import Path

    from m4_field_ops import calendrier_civil, cedule, encodage, etats, pointage, visites_chantier, visites_durables
    from m4_field_ops.registre import Registre

    from opsys import contexte, stockage
    from opsys.outils import executer_atomique

    par_nom, ids, _, _ = planning
    iid = ids['lead-fictif-001']
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        prev = Registre(stockage.maillons('m04-field-ops', visites_durables.REGISTRE))
        ligne = next(x for x in calendrier_civil.lire_semaine(reg, '2030-06-03')['interventions']
                     if x['intervention_id'] == iid)
        ancre = {k: ligne[k] for k in ('intervention_id', 'plan_id', 'source_application_id', 'source_ligne_id')}
        args = {'ancre': ancre, 'revision_attendue': 0}
        mutation = {'appareil': 'console-fictive', 'cle': 'completion-prev-fictive',
                    'empreinte_arguments': encodage.empreinte(args)}
        visite = visites_durables.prevoir(reg, prev, **args, auteur={'personne': 'admin.fictif', 'role': 'admin'},
                                           mutation=mutation, horodatage='2030-06-03T07:30:00-04:00')
        visites_chantier.ouvrir(reg, prev, visite['visite_id'], '2030-06-03T08:00:00-04:00')
        equipe = ligne['equipe_id']
        assign = {'intervention_id': iid, 'technicien_id': equipe}
        assert etats.transitionner(iid, 'en_route', reg, '2030-06-03T08:30:00-04:00', assignation=assign)[1] is None
        ref = {cedule.tokeniser_ville('sel-fictif', 'Repentigny'): {
            'latitude': 45.75, 'longitude': -73.45, 'rayon_km': 25.0}}
        fenetre = {'debut': '2030-06-03T08:00:00-04:00', 'fin': '2030-06-03T18:00:00-04:00'}
        for action, instant in [('arrivee', '2030-06-03T09:00:00-04:00'),
                                ('depart', '2030-06-03T12:00:00-04:00')]:
            assert pointage.enregistrer_pointage(iid, equipe, action, instant,
                {'latitude': 45.75, 'longitude': -73.45}, {'fictif': True, 'appareil_id': 'fictif'},
                assign, fenetre, ref, 'Repentigny', 'sel-fictif', reg)[1] is None
        visites_chantier.fermer(reg, prev, visite['visite_id'], '2030-06-03T12:01:00-04:00')
    spec = importlib.util.spec_from_file_location('fixture_png_visites',
        Path(__file__).parents[1] / 'departments/m04-field-ops/tests/conftest.py')
    fixture_png = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_png)
    png = fixture_png.png_minimal()
    instant = datetime.fromisoformat('2030-06-03T12:02:00-04:00')
    def outil(nom, arguments):
        with (session(),
              contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')),
              contexte.receptionne_de(contexte.HorodatageAppareil('console:admin.fictif', instant, instant))):
            return executer_atomique(par_nom[nom], arguments)
    photo = outil('m4_deposer_fichier', {'empreinte_sha256': hashlib.sha256(png).hexdigest(),
        'taille_octets': len(png), 'type_mime': 'image/png', 'index_bloc': 0, 'nombre_blocs': 1,
        'bloc_base64': base64.b64encode(png).decode('ascii')})
    assert photo['ok'] and photo['resultat']['accepte'], photo
    reference = photo['resultat']['resultat']['reference']
    args = {'intervention_id': iid, 'horodatage': instant.isoformat(),
            'preuves_completion': {'checklist_complete': True, 'photos_apres': [reference],
                                   'notes': 'Fictif', 'signature': None}, 'signature_requise': False}
    from m4_field_ops import outils as module_outils
    from sqlalchemy import func, select

    from opsys.stockage.schema import EVENEMENTS_SORTANTS, JOURNAL
    with session() as cnx:
        avant_reg = list(stockage.maillons('m04-field-ops', 'principal'))
        avant_evenements = cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one()
        avant_audit = cnx.execute(select(func.count()).select_from(JOURNAL)).scalar_one()
    original = module_outils._acteur_appareil
    appels = []
    def revoque():
        appels.append(1)
        if len(appels) == 2:
            return None, {'code': 'REJ-IDENTITE-APPAREIL-INVALIDE', 'statut': '', 'detail': 'fictif'}
        return original()
    with monkeypatch.context() as patch:
        patch.setattr(module_outils, '_acteur_appareil', revoque)
        assert outil('m4_completer_intervention', args)['resultat']['accepte'] is False
    with session() as cnx:
        assert list(stockage.maillons('m04-field-ops', 'principal')) == avant_reg
        assert cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one() == avant_evenements
        assert cnx.execute(select(func.count()).select_from(JOURNAL)).scalar_one() == avant_audit
    resultat = outil('m4_completer_intervention', args)
    assert resultat['ok'] and resultat['resultat']['accepte'], resultat
    with session():
        from m4_field_ops import outbox
        wcts = outbox.lire_outbox(Registre(stockage.maillons('m04-field-ops', 'principal')))
        assert len([w for _, w in wcts if w['intervention_id'] == iid]) == 1
        assert next(w for _, w in wcts if w['intervention_id'] == iid)['duree_reelle_minutes'] == 180
    assert outil('m4_completer_intervention', args)['resultat']['accepte'] is False
