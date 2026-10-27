"""fictif: true — décision N3 explicite de la console, dates civiles séparées."""
import importlib.util
from html.parser import HTMLParser
from pathlib import Path

from sqlalchemy import select

from opsys import contexte, identite
from opsys.outils import executer_atomique
from opsys.stockage.schema import APPROBATIONS

spec = importlib.util.spec_from_file_location('crm08_application_http_fixture',
    Path(__file__).with_name('test_console_application_chantier.py'))
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
h, p = a.h, a.p
propose, pret, affaire, catalogue, client_crm = a.propose, a.pret, a.affaire, a.catalogue, a.client_crm


class Formulaire(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.champs, self.actif, self.action = {}, False, None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        valeurs = dict(attrs)
        if tag == 'form':
            self.actif = valeurs.get('action', '').endswith('/appliquer')
            if self.actif:
                self.action = valeurs['action']
        if tag == 'input' and self.actif and 'name' in valeurs:
            assert valeurs['name'] not in self.champs
            self.champs[valeurs['name']] = valeurs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.actif = False


def test_confirmer_affectation_interne_puis_editeur_civil_separe(propose, catalogue, session):
    avant = p.m.base._instantane_base(session)
    revue = catalogue.get(propose['revue_route'])
    assert revue.status_code == 200, revue.text
    form = Formulaire(revue.text)
    assert form.action is not None, revue.text
    assert set(form.champs) == {'csrf', 'mutation_id', 'empreinte_attendue'}
    assert 'sans réservation de date' in revue.text
    assert p.m.base._instantane_base(session) == avant
    route = propose['revue_route'] + '/appliquer'
    reponse = catalogue.post(route, data=form.champs, follow_redirects=False)
    assert reponse.status_code == 303, reponse.text
    attendu = '/crm/cedule/plan/' + propose['plan_id']
    assert reponse.headers['location'] == p.m.base.PREFIXE + attendu
    apres = p.m.base._instantane_base(session)
    calendrier = catalogue.get(attendu)
    assert calendrier.status_code == 200 and 'name="revision_attendue" value="0"' in calendrier.text
    assert 'value="" required' in calendrier.text and 'confirmation client' in calendrier.text
    assert p.m.base._instantane_base(session) == apres
    rejoue = catalogue.post(route, data=form.champs)
    assert rejoue.status_code == 200 and 'Reçu historique' in rejoue.text
    assert p.m.base._instantane_base(session) == apres
    with session() as cnx:
        traces = cnx.execute(select(APPROBATIONS.c.niveau, APPROBATIONS.c.decide_role, APPROBATIONS.c.decide_par).where(
            APPROBATIONS.c.outil == 'm4_appliquer_cedule')).all()
    assert traces == [('N3', 'admin', p.AUTH.utilisateur)]



def test_formulaire_n3_ferme_csrf_borne_et_role_revoque(propose, catalogue, session):
    from urllib.parse import urlencode

    route = propose['revue_route'] + '/appliquer'
    champs = Formulaire(catalogue.get(propose['revue_route']).text).champs
    avant = p.m.base._instantane_base(session)
    assert catalogue.post(route, data={**champs, 'csrf': 'faux'}).status_code == 403
    for ajout in ({'confirme_par': 'usurpe'}, {'horodatage': p.b.ACCEPTE_LE}, {'plan_id': 'etranger'},
                  {'mutation_id': ''}, {'mutation_id': 'x' * 201}):
        assert catalogue.post(route, data={**champs, **ajout}).status_code == 400
    assert catalogue.post(route, content=urlencode(champs)+'&mutation_id=autre',
        headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 400
    assert catalogue.post(route, content=b'x' * 9000,
        headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 413
    assert catalogue.post(route, json=champs).status_code == 415
    assert catalogue.post(route+'?confirme_par=autre', data=champs).status_code == 400
    assert p.m.base._instantane_base(session) == avant
    with session() as cnx:
        identite.ajouter_role(cnx, p.AUTH.utilisateur, 'nathan_owner')
        identite.retirer_role(cnx, p.AUTH.utilisateur, 'admin')
    avant = p.m.base._instantane_base(session)
    assert catalogue.post(route, data=champs).status_code == 403
    assert catalogue.get(propose['revue_route']).status_code == 403
    assert p.m.base._instantane_base(session) == avant


def test_retirer_materiel_apres_revue_bloque_decision_n3(propose, catalogue, session):
    champs = Formulaire(catalogue.get(propose['revue_route']).text).champs
    outil = p.b._outils(propose['deps'], 'm06-material-control')['m6_liberer_reservation']
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(p.AUTH.utilisateur, 'admin', source='console')):
        p.b._ok(executer_atomique(outil, dict(devis_id=p.DEVIS, motif='Retrait FICTIF', horodatage=p.b.ACCEPTE_LE)))
    assert p.b._drainer(propose['deps'], p.b.DEBUT)['quarantaines'] == 0
    avant = p.m.base._instantane_base(session)
    assert catalogue.post(propose['revue_route']+'/appliquer', data=champs).status_code == 409
    page = catalogue.get(propose['revue_route'])
    assert page.status_code == 200 and 'Confirmer l’affectation interne' not in page.text
    assert p.m.base._instantane_base(session) == avant



def test_rejeu_http_apres_report_affiche_historique_sans_formulaire(propose, catalogue, session):
    form = Formulaire(catalogue.get(propose['revue_route']).text)
    route = propose['revue_route'] + '/appliquer'
    assert catalogue.post(route, data=form.champs, follow_redirects=False).status_code == 303
    with session():
        chaine = p.registre.Registre(p.stockage.maillons('m04-field-ops', 'principal'))
        iid = p.etats.intervention_du_devis(chaine, p.DEVIS)
        _, erreur = p.etats.transitionner(iid, 'reportee', chaine, p.b.ACCEPTE_LE, motif='meteo')
        assert erreur is None
    avant = p.m.base._instantane_base(session)
    page = catalogue.post(route, data=form.champs)
    assert page.status_code == 200 and 'Reçu historique' in page.text and 'reportee' in page.text
    assert Formulaire(page.text).action is None
    assert 'Aucune nouvelle affectation ni disponibilité confirmée' in page.text
    assert p.m.base._instantane_base(session) == avant
    assert catalogue.post(route, data={**form.champs, 'mutation_id': 'autre-affectation-fictive'}).status_code == 409
    assert p.m.base._instantane_base(session) == avant


def test_plan_inconnu_et_non_admin_ne_decident_pas(propose, catalogue, client_crm, session):
    form = Formulaire(catalogue.get(propose['revue_route']).text)
    route = propose['revue_route'] + '/appliquer'
    avant = p.m.base._instantane_base(session)
    assert catalogue.post(route.replace(propose['plan_id'], 'f' * 64), data=form.champs).status_code == 404
    assert p.m.base._instantane_base(session) == avant
    for acteur in ('employe', 'nathan'):
        p.m.base._connecter(client_crm, acteur)
        champs = dict(form.champs, csrf=client_crm.get('/api/session').json()['csrf'])
        avant = p.m.base._instantane_base(session)
        assert client_crm.post(route, data=champs).status_code == 403
        assert client_crm.get(propose['revue_route']).status_code == 403
        assert p.m.base._instantane_base(session) == avant
