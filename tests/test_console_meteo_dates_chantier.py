"""fictif: true — contrôle météo explicite des dates réelles, sans écriture."""
import importlib.util
from html.parser import HTMLParser
from pathlib import Path

import pytest

from opsys import meteo

spec = importlib.util.spec_from_file_location('meteo_dates_fixture',
    Path(__file__).with_name('test_console_dates_cedule.py'))
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
base = d.base
client_crm, planning = d.client_crm, d.planning


class Formulaire(HTMLParser):
    def __init__(self):
        super().__init__()
        self.dans = False
        self.champs = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.dans = attrs.get('action', '').endswith('/meteo')
        if self.dans and tag == 'input':
            self.champs[attrs['name']] = attrs['value']

    def handle_endtag(self, tag):
        if tag == 'form':
            self.dans = False


def _profil():
    return {'fuseau': 'America/Montreal', 'services': {
        'gouttieres': {'seuils': {'vent_kmh': {'validation': 25, 'blocage': 40},
            'pluie_mm_h': {'blocage': 3}, 'gel_c': {'blocage': 0}, 'verglas': {'blocage': True},
            'chaleur_c': {'blocage': 35}}}}}


@pytest.fixture
def dates(planning):
    meteo.enregistrer_meteo(_profil())
    return planning


def _form(client, dates):
    page = client.get(d._url(dates))
    assert page.status_code == 200, page.text
    f = Formulaire()
    f.feed(page.text)
    assert set(f.champs) == {'csrf', 'empreinte_attendue'}, page.text
    return f.champs


def test_meteo_dates_explicitement_verifiees_sans_fournisseur_ni_ecriture(client_crm, dates, session):
    base.base._connecter(client_crm, 'admin.fictif')
    avant = base.base._instantane_base(session)
    champs = _form(client_crm, dates)
    assert base.base._instantane_base(session) == avant
    page = client_crm.post(d._url(dates) + '/meteo', data=champs)
    assert page.status_code == 200, page.text
    assert 'inconnu' in page.text and '2030-06-03' in page.text
    assert 'Fraîcheur non qualifiée' in page.text
    assert 'dispatch' in page.text and page.headers['cache-control'] == 'no-store'
    assert base.base._instantane_base(session) == avant


spec_mono = importlib.util.spec_from_file_location('meteo_dates_mono_fixture',
    Path(__file__).with_name('test_console_application_chantier_http.py'))
h = importlib.util.module_from_spec(spec_mono)
spec_mono.loader.exec_module(h)
propose, pret, affaire, catalogue = h.propose, h.pret, h.affaire, h.catalogue


@pytest.fixture
def mono(propose, catalogue):
    form = h.Formulaire(catalogue.get(propose['revue_route']).text)
    r = catalogue.post(form.action.removeprefix(h.p.m.base.PREFIXE), data=form.champs, follow_redirects=False)
    assert r.status_code == 303, r.text
    route = '/crm/cedule/plan/' + propose['plan_id']
    csrf = catalogue.get('/api/session').json()['csrf']
    r = catalogue.post(route, data=d._champs(catalogue, propose['plan_id'], csrf=csrf, revision_attendue='0',
        mutation_id='dates-meteo-fictives', date_0='2030-06-03'), follow_redirects=False)
    assert r.status_code == 303, r.text
    return dict(propose, route=route)


def _fournisseur_manuel(monkeypatch, vent=5, avant=None):
    from m4_field_ops import meteo_manuelle
    from m4_field_ops import outils as m4

    saisie = dict(saisi_par='admin.fictif', source='Bulletin FICTIF <script>alert(1)</script>',
        emise_le='2020-01-01T00:00:00+00:00', points=[dict(heure=f'2030-06-03T{heure:02d}:00',
            vent_kmh=vent, rafales_kmh=vent, temperature_c=18, precipitation_mm_h=0,
            probabilite_precipitation_pct=0, verglas=False) for heure in range(24)])
    fournisseur, erreur = meteo_manuelle.creer_fournisseur_manuel(saisie)
    assert erreur is None, erreur
    original = m4.outils
    appels = []

    class Previsions:
        def previsions(self, *args):
            appels.append(args)
            if avant:
                avant()
            return fournisseur.previsions(*args)

    monkeypatch.setattr(m4, 'outils', lambda: original(fournisseur_meteo=Previsions()))
    return appels


def test_ancienne_prevision_citee_ne_devient_pas_fraiche(catalogue, mono, session, monkeypatch):
    appels = _fournisseur_manuel(monkeypatch)
    avant = h.p.m.base._instantane_base(session)
    # Lire la page ne charge aucune prévision.
    f = Formulaire()
    f.feed(catalogue.get(mono['route']).text)
    assert appels == [] and set(f.champs) == {'csrf', 'empreinte_attendue'}
    page = catalogue.post(mono['route'] + '/meteo', data=f.champs)
    assert page.status_code == 200, page.text
    assert appels and 'Verdict : ok' in page.text
    assert '2020-01-01T00:00:00+00:00' in page.text and 'saisie_manuelle' in page.text
    assert 'Fraîcheur non qualifiée' in page.text
    assert '&lt;script&gt;' in page.text and '<script>alert(1)</script>' not in page.text
    assert h.p.m.base._instantane_base(session) == avant


def test_profil_aba_reellement_utilise_ne_peut_etre_substitue(catalogue, mono, session, monkeypatch):
    from opsys.console import preparation_chantier as lecture

    _fournisseur_manuel(monkeypatch, vent=50)
    f = Formulaire()
    f.feed(catalogue.get(mono['route']).text)
    profil_a, erreur = meteo.charger_meteo()
    assert erreur is None
    profil_b = _profil()
    profil_b['services']['gouttieres']['seuils']['vent_kmh'] = {'blocage': 100}
    original = lecture._appel

    def remplacer(*args, **kwargs):
        if args[3] != 'm4_verifier_meteo_creneau':
            return original(*args, **kwargs)
        meteo.enregistrer_meteo(profil_b)
        try:
            res = original(*args, **kwargs)
            assert res['statut'] == 'ok', res
            return res
        finally:
            meteo.enregistrer_meteo(profil_a)

    monkeypatch.setattr(lecture, '_appel', remplacer)
    page = catalogue.post(mono['route'] + '/meteo', data=f.champs)
    assert page.status_code == 409, page.text
    # Les seuls effets sont les deux écritures de profil de la perturbation QA.
    assert meteo.charger_meteo()[0] == profil_a


def test_plan_rechaine_sans_empreinte_metier_ne_permet_pas_controle(client_crm, dates, session):
    from m4_field_ops import registre
    from sqlalchemy import update

    from opsys import stockage
    from opsys.stockage import codec
    from opsys.stockage.schema import REGISTRES

    base.base._connecter(client_crm, 'admin.fictif')
    with session() as cnx:
        chaine = registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        nouvelle = registre.Registre()
        liens = {}
        for ligne in chaine.lire():
            ancien = ligne['ligne_id']
            if ligne['type_entree'] == 'cedule_proposee':
                ligne['sortie']['plan'][0]['visites'][0]['fin_min'] += 1
            if 'source_application_id' in ligne:
                source = ligne['source_application_id']
                ligne['source_application_id'] = liens.get(source, source)
            nouvelle.ajouter(ligne)
            liens[ancien] = nouvelle.lire()[-1]['ligne_id']
        nouvelle.assert_chaine()
        for rang, ligne in enumerate(nouvelle.lire()):
            cnx.execute(update(REGISTRES).where((REGISTRES.c.departement == 'm04-field-ops')
                & (REGISTRES.c.registre == 'principal') & (REGISTRES.c.rang == rang)).values(
                    maillon=codec.encoder(ligne)))
    avant = base.base._instantane_base(session)
    page = client_crm.get(d._url(dates))
    assert page.status_code == 503, page.text
    assert base.base._instantane_base(session) == avant


@pytest.mark.parametrize('vent,statut', [(24, 'ok'), (25, 'validation_requise'), (40, 'bloquant')])
def test_seuils_reels_sur_date_exacte(catalogue, mono, session, monkeypatch, vent, statut):
    _fournisseur_manuel(monkeypatch, vent=vent)
    f = Formulaire()
    f.feed(catalogue.get(mono['route']).text)
    avant = h.p.m.base._instantane_base(session)
    page = catalogue.post(mono['route'] + '/meteo', data=f.champs)
    assert page.status_code == 200, page.text
    assert f'Verdict : {statut}' in page.text and '2030-06-03' in page.text
    assert h.p.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('changement', ['dates', 'profil', 'etat'])
def test_source_modifiee_depuis_formulaire_refusee(client_crm, dates, session, changement):
    from m4_field_ops import etats

    base.base._connecter(client_crm, 'admin.fictif')
    champs = _form(client_crm, dates)
    if changement == 'dates':
        r = client_crm.post(d._url(dates), data=d._champs(client_crm, dates[2]["plan_id"]), follow_redirects=False)
        assert r.status_code == 303, r.text
    elif changement == 'profil':
        profil = _profil()
        profil['services']['gouttieres']['seuils']['vent_kmh']['blocage'] = 41
        meteo.enregistrer_meteo(profil)
    else:
        with session():
            assert etats.transitionner(dates[1]['lead-fictif-001'], 'reportee', base.terrain._registre(),
                base.terrain.RECU_LE.isoformat(), motif='meteo')[1] is None
    avant = base.base._instantane_base(session)
    page = client_crm.post(d._url(dates) + '/meteo', data=champs)
    assert page.status_code == 409, page.text
    assert base.base._instantane_base(session) == avant


@pytest.mark.parametrize('role', ['employe', 'nathan', 'revoque'])
def test_role_actuel_requis_avant_controle(client_crm, dates, session, role):
    from opsys import identite

    base.base._connecter(client_crm, 'admin.fictif' if role == 'revoque' else role)
    if role == 'revoque':
        champs = _form(client_crm, dates)
        with session() as cnx:
            identite.ajouter_role(cnx, 'admin.fictif', 'nathan_owner')
            identite.retirer_role(cnx, 'admin.fictif', 'admin')
    else:
        champs = dict(csrf=client_crm.get('/api/session').json()['csrf'], empreinte_attendue='a'*64)
    avant = base.base._instantane_base(session)
    assert client_crm.post(d._url(dates) + '/meteo', data=champs).status_code == 403
    assert base.base._instantane_base(session) == avant


def test_formulaire_csrf_ferme_borne_et_sans_date_injectee(client_crm, dates, session):
    from urllib.parse import urlencode

    base.base._connecter(client_crm, 'admin.fictif')
    champs = _form(client_crm, dates)
    route = d._url(dates) + '/meteo'
    avant = base.base._instantane_base(session)
    for changement in [dict(date_0='2030-06-04'), dict(previsions_saisies='{}'), dict(confirme_par='usurpe')]:
        assert client_crm.post(route, data={**champs, **changement}).status_code == 400
    assert client_crm.post(route, data={**champs, 'csrf': 'faux'}).status_code == 403
    assert client_crm.post(route, data=champs, params=dict(date_0='2030-06-04')).status_code == 400
    assert client_crm.post(route, content=urlencode(champs)+'&csrf=dup',
        headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 400
    assert client_crm.post(route, content=b'x'*9000,
        headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 413
    assert client_crm.post(route, json=champs).status_code == 415
    assert base.base._instantane_base(session) == avant


@pytest.mark.parametrize('fuseau,statut', [('UTC', 503), ('America/Toronto', 200)])
def test_fuseau_date_compatible_et_non_invente(client_crm, dates, session, fuseau, statut):
    profil = _profil()
    profil['fuseau'] = fuseau
    meteo.enregistrer_meteo(profil)
    base.base._connecter(client_crm, 'admin.fictif')
    champs = _form(client_crm, dates)
    avant = base.base._instantane_base(session)
    page = client_crm.post(d._url(dates) + '/meteo', data=champs)
    assert page.status_code == statut, page.text
    assert base.base._instantane_base(session) == avant


def test_profil_change_pendant_fournisseur_est_refuse(catalogue, mono, monkeypatch):
    profil = _profil()
    profil['services']['gouttieres']['seuils']['vent_kmh']['blocage'] = 99
    _fournisseur_manuel(monkeypatch, avant=lambda: meteo.enregistrer_meteo(profil))
    f = Formulaire()
    f.feed(catalogue.get(mono['route']).text)
    page = catalogue.post(mono['route'] + '/meteo', data=f.champs)
    assert page.status_code == 409, page.text


@pytest.mark.parametrize('defaut', ['reduit', 'volume', 'autre_date', 'visite_manquante'])
def test_projection_meteo_incomplete_ne_devient_pas_fiable(catalogue, mono, session, monkeypatch, defaut):
    from opsys.console import preparation_chantier as lecture

    _fournisseur_manuel(monkeypatch)
    f = Formulaire()
    f.feed(catalogue.get(mono['route']).text)
    original = lecture._appel

    def transport_altere(*args, **kwargs):
        res = original(*args, **kwargs)
        if args[3] == 'm4_verifier_meteo_creneau':
            if defaut == 'reduit':
                res['detail_reduit'] = 'partiel'
            elif defaut == 'volume':
                res['attributions'] = ['x' * 66000]
            elif defaut == 'autre_date':
                res['creneaux'][0]['date'] = '2030-06-04'
            else:
                res['creneaux'] = []
        return res

    monkeypatch.setattr(lecture, '_appel', transport_altere)
    avant = h.p.m.base._instantane_base(session)
    page = catalogue.post(mono['route'] + '/meteo', data=f.champs)
    assert page.status_code == 503, page.text
    assert h.p.m.base._instantane_base(session) == avant


def test_revocation_entre_lecture_civile_et_formulaire(client_crm, dates, session, monkeypatch):
    from opsys import identite
    from opsys.console import metier

    base.base._connecter(client_crm, 'admin.fictif')
    original = metier.executer

    def retirer_apres_lecture(cnx, deps, sess, nom, arguments, **kwargs):
        res = original(cnx, deps, sess, nom, arguments, **kwargs)
        if nom == 'm4_lire_calendrier_plan':
            identite.ajouter_role(cnx, 'admin.fictif', 'nathan_owner')
            identite.retirer_role(cnx, 'admin.fictif', 'admin')
        return res

    monkeypatch.setattr(metier, 'executer', retirer_apres_lecture)
    assert client_crm.get(d._url(dates)).status_code == 403
